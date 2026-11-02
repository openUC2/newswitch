"""Work out what the microscope does, from what it is made of.

A server does this when it starts, and keeps the result in memory: nothing is written, so a changed
description only takes a restart. Traces every combination of what the swaps can put in place, for
each detector. Nudging every variable to see what changes (`impacts`) says what impacts what, with a
size, and nothing declares it; only `newswitch.tools.check_instrument` asks that.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from newswitch.instrument import tracing
from newswitch.instrument.predict import Answer, Compiled, assemble, state_key
from newswitch.instrument.spec import Instrument, Variable

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
    wavelength = tracing.design_wavelength(instrument, detector, state)
    return asdict(tracing.imaging(instrument, detector, state, wavelength, errors)), coupling


#: How far from focus a detector's blur per micrometre is measured.
_FOCUS_NUDGE_UM = 100.0


def _focus_response(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    errors: tracing.Errors,
) -> dict[str, Any]:
    """How sharp what is in focus is, and how blur grows with the distance from there."""
    wavelength = tracing.design_wavelength(instrument, detector, state)
    sharp = tracing.imaging(instrument, detector, state, wavelength, errors, 0.0).spot_center_um
    away = tracing.imaging(
        instrument, detector, state, wavelength, errors, _FOCUS_NUDGE_UM
    ).spot_center_um
    return {
        "in_focus_um": sharp,
        "blur_um_per_um": max(away**2 - sharp**2, 0.0) ** 0.5 / _FOCUS_NUDGE_UM,
        "moves": tracing.focus_moves(instrument, detector, state),
    }


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
    pixel = math.hypot(before.pixel_to_stage[0][0], before.pixel_to_stage[1][0])
    # Binning makes other pixels, exactly: that is no change of what the optics do.
    regridded = before.size != after.size
    # A turn or a flip of the image changes a pixel's direction, not its size: that counts too.
    scale = (
        0.0
        if regridded
        else max(
            abs(new - old)
            for was, now in zip(before.pixel_to_stage, after.pixel_to_stage)
            for old, new in zip(was, now)
        )
        / pixel
    )
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


def nudge_of(variable: Variable) -> float:
    """How far to move a variable to see what it does: a part of its range, not its finest step.

    A piezo's 10 nm step changes nothing a detector can tell, and it is still what focuses.
    """
    assert variable.step is not None
    if variable.min is not None and variable.max is not None:
        return max(variable.step, (variable.max - variable.min) / 20.0)
    return variable.step * 10.0


def impacts(instrument: Instrument, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Nudge every variable, and report what changed for each detector."""
    rows = []
    for name, variable in instrument.variables.items():
        if variable.verb == "swaps":
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


def influences(instrument: Instrument) -> dict[str, frozenset[str]]:
    """What a calibration of each detector depends on: the variables found to change its pixels.

    A pixel's size or direction, or how many pixels there are, measured under every combination of
    swaps. Where the image lands too, for a swap: a move shifts the image by what it is for, while
    a swap that shifts it puts the same pixel somewhere else.
    """
    found: dict[str, set[str]] = {detector: set() for detector in instrument.detectors()}
    on_them = {
        instrument.simulation_key(sample): instrument.sample_holder(sample).simulation
        for sample in instrument.samples()
    }
    states = [
        s for s in instrument.swap_states() if all(s[key] == on for key, on in on_them.items())
    ]
    for state in states:
        for detector in instrument.detectors():
            before = traced_answer(instrument, detector, state)
            for name, variable in instrument.variables.items():
                if variable.verb == "swaps":
                    nudges = [slot for slot in variable.slots if slot > state[name]]
                    matter = {"scale", "pixels", "position"}
                else:
                    nudges = [state[name] + nudge_of(variable)]
                    matter = {"scale", "pixels"}
                for nudge in nudges:
                    after = traced_answer(instrument, detector, {**state, name: nudge})
                    if matter & set(difference(before, after)):
                        found[detector].add(name)
    return {detector: frozenset(names) for detector, names in found.items()}


def compile_instrument(instrument: Instrument, errors: tracing.Errors | None = None) -> Compiled:
    """What `instrument` does, for every simulation and combination of swaps.

    With `errors`, what a microscope with those errors really does, so that a simulator can render
    it. Those are passed in: the compiler itself knows only the description.
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
                "focus": _focus_response(instrument, detector, state, applied),
            }
        states[state_key(instrument, state)] = entry
    return Compiled(instrument, states)
