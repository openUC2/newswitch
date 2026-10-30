"""Work out what the microscope does, from what it is made of.

Run through ``newswitch.tools.compile_instrument``. Traces every combination of what the swaps can put in place, for each detector, and nudges every
variable to see what changes. So what impacts what is calculated, with a size, and nothing declares
it. The result is a plain file, which is all a microscope needs to read.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from newswitch.instrument import tracing
from newswitch.instrument.predict import COMPILED, Answer, assemble, state_key
from newswitch.instrument.spec import Instrument

#: How much of a change counts: below these, a nudge did not matter.
TOLERANCES = {
    "position": 0.1,
    "scale": 0.25,
    "blur": 0.25,
    "colour": 1.0,
    "light": 0.01,
    "pixels": 1.0,
}


def traced_answer(instrument: Instrument, detector: str, state: Mapping[str, Any]) -> Answer:
    """What `detector` sees under `state`, tracing it."""
    return assemble(instrument, detector, state, *_trace(instrument, detector, state))


def _trace(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    errors: tracing.Errors = tracing.Errors(),
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    coupling = tracing.coupling(instrument, detector, state)
    bands = [a["band_mean_nm"] for a in coupling.values() if a["band_mean_nm"] is not None]
    wavelength = bands[0] if bands else 550.0
    return asdict(tracing.imaging(instrument, detector, state, wavelength, errors)), coupling


def _axial(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    imaging: Mapping[str, float],
    errors: tracing.Errors,
) -> dict[str, dict[str, float]]:
    """How each move along the optical axis changes scale and blur, per micrometre."""
    found = {}
    for name, variable in instrument.variables.items():
        if variable.verb != "moves" or variable.along != "axis":
            continue
        assert variable.step is not None
        moved, _ = _trace(
            instrument, detector, {**state, name: state[name] + variable.step}, errors
        )
        blur = max(moved["spot_center_um"] ** 2 - imaging["spot_center_um"] ** 2, 0.0) ** 0.5
        found[name] = {
            "magnification_per_um": (moved["magnification"] - imaging["magnification"])
            / variable.step,
            "blur_um_per_um": blur / variable.step,
        }
    return found


def difference(before: Answer, after: Answer) -> dict[str, float]:
    """How far two answers apart are, in what each kind of change is measured in.

    Position, scale and blur are in pixels on the sensor, so that the same tolerance means the same
    thing for every detector; colour is in nanometres, light is a fraction, and pixels counts how
    many columns the image gained or lost.
    """
    half_width = before.size[0] / 2.0
    pixel = abs(before.pixel_to_stage[0][0])
    # Binning makes other pixels, exactly: that is no change of what the optics do.
    regridded = before.size != after.size
    scale = 0.0 if regridded else abs(abs(after.pixel_to_stage[0][0]) / pixel - 1.0)
    changes = {
        "pixels": float(abs(before.size[0] - after.size[0])),
        "position": max(
            abs(after.centre[0] - before.centre[0]), abs(after.centre[1] - before.centre[1])
        )
        / pixel,
        "scale": scale * half_width,
        "blur": abs(after.spot_px - before.spot_px),
        "colour": abs((after.band_nm or 0.0) - (before.band_nm or 0.0)),
        "light": abs(after.light - before.light) / max(before.light, 1.0),
    }
    return {name: size for name, size in changes.items() if size >= TOLERANCES[name]}


def impacts(instrument: Instrument, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Nudge every variable, and report what changed for each detector."""
    rows = []
    for name, variable in instrument.variables.items():
        if variable.verb == "swaps":
            assert variable.slots is not None
            nudges = [slot for slot in variable.slots if slot != state[name]]
        else:
            assert variable.step is not None
            nudges = [state[name] + variable.step]
        for nudge in nudges:
            for detector in instrument.detectors():
                changes = difference(
                    traced_answer(instrument, detector, state),
                    traced_answer(instrument, detector, {**state, name: nudge}),
                )
                rows.append(
                    {
                        "variable": name,
                        "verb": variable.verb,
                        "nudge": nudge,
                        "detector": detector,
                        "changes": changes,
                    }
                )
    return rows


def compile_instrument(
    instrument: Instrument, name: str = COMPILED, errors: tracing.Errors | None = None
) -> Path:
    """Write what `instrument` does to the file `name` in its folder.

    With `errors`, what a microscope with those errors really does, so that a simulator can render
    it without tracing. Those are passed in: the compiler itself knows only the description.
    """
    applied = errors or tracing.Errors()
    states: dict[str, dict[str, Any]] = {}
    for state in instrument.swap_states():
        entry = {}
        for detector in instrument.detectors():
            imaging, coupling = _trace(instrument, detector, state, applied)
            entry[detector] = {
                "imaging": imaging,
                "coupling": coupling,
                "axial": _axial(instrument, detector, state, imaging, applied),
            }
        states[state_key(instrument, state)] = entry
    path = instrument.folder / name
    path.write_text(
        json.dumps(
            {
                "instrument": instrument.name,
                "digest": instrument.digest,
                "states": states,
                "impacts": [] if errors else impacts(instrument, instrument.initial_state()),
            },
            indent=1,
        )
        + "\n"
    )
    return path
