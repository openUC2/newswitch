"""The whole loop: what the design predicts, what the images measure, and what was really there.

    uv run python -m newswitch.tools.check_instrument instruments/fake-microscope

Images land in the instrument's ``out/``.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image

from newswitch.calibration.affine import calibrate_pixel_to_stage, pixel_shift
from newswitch.instrument.compiler import compile_instrument, difference, impacts
from newswitch.instrument.naming import channel_names
from newswitch.instrument.roles import Roles
from newswitch.instrument.spec import load
from newswitch.logging_setup import console, setup_logging
from newswitch.simulation.simulator import SimulatedMicroscope

#: How far apart prediction and measurement may be before it is worth saying so.
SCALE_TOLERANCE_PERCENT = 0.5
ROTATION_TOLERANCE_DEG = 0.25
SHIFT_TOLERANCE_PX = 0.5

#: What this tool reports: to stdout, and into the log file.
report = console("check_instrument")


def save(folder: Path, name: str, frame: np.ndarray) -> None:
    """Keep an image to look at, stretched to its own range."""
    folder.mkdir(exist_ok=True)
    low, high = np.percentile(frame, (0.5, 99.9))
    scaled = np.clip((frame.astype(float) - low) / max(high - low, 1.0), 0.0, 1.0)
    Image.fromarray((scaled * 255).astype(np.uint8)).save(folder / f"{name}.png")


def _stage_moves(
    microscope: SimulatedMicroscope, detector: str, step: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """An image, one after moving what moves its view in x, and one after moving it in y."""
    instrument = microscope.simulator.instrument
    roles = Roles(instrument)
    sample = instrument.seen_sample(detector, microscope.state)
    move_x = roles.x(detector, sample=sample).name
    move_y = roles.y(detector, sample=sample).name
    x, y = microscope.state[move_x], microscope.state[move_y]
    reference = microscope.image(detector)
    microscope.set({move_x: x + step})
    moved_x = microscope.image(detector)
    microscope.set({move_x: x, move_y: y + step})
    moved_y = microscope.image(detector)
    microscope.set({move_y: y})
    return reference, moved_x, moved_y


def _size_and_rotation(matrix: np.ndarray) -> tuple[float, float]:
    """Pixel size, and the turn of the x column, which flips and inversion do not change."""
    sign = np.sign(matrix[0, 0])
    return float(np.hypot(matrix[0, 0], matrix[1, 0])), math.degrees(
        math.atan2(matrix[1, 0] * sign, matrix[0, 0] * sign)
    )


def measure(microscope: SimulatedMicroscope, detector: str) -> tuple[float, float]:
    """newswitch's own calibration arithmetic on the fake images: pixel size, and its turn."""
    step = 100.0
    frames = _stage_moves(microscope, detector, step)
    return _size_and_rotation(np.array(calibrate_pixel_to_stage(*frames, step, step)))


def flag(mismatch: float, tolerance: float) -> str:
    """Whether a difference is worth saying something about."""
    return "MISMATCH" if abs(mismatch) > tolerance else "ok"


def _heading(title: str, *args: object) -> None:
    """A section of the report: an empty line, then its title."""
    report.info("")
    report.info(title, *args)


def main(argv: list[str] | None = None) -> None:
    """Run the loop on the instrument the command line names."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("instrument", type=Path, help="the instrument's folder")
    instrument = load(parser.parse_args(argv).instrument)
    compiled = compile_instrument(instrument)
    out = instrument.folder / "out"
    report.info(
        "=== %d combinations, %d detectors", len(compiled.states), len(instrument.detectors())
    )

    _heading("=== What impacts what: calculated, nothing declared this")
    for row in impacts(instrument, instrument.initial_state()):
        changes = ", ".join(f"{k} {v:.3g}" for k, v in row["changes"].items()) or "nothing"
        report.info(
            "  %-20s %-6s %-9s -> %s", row["variable"], row["verb"], row["detector"], changes
        )

    state = instrument.initial_state()
    _heading("=== The logical detectors: what each delivers, from its parts and its wires")
    for detector in instrument.detectors():
        axes = ", ".join(
            f"{axis.name}{'*' if axis.size is None else ''}"
            for axis in instrument.detector_axes(detector)
        )
        report.info("  %s: (%s)", detector, axes)
    for drive in instrument.drives:
        report.info("  wire: %s -> %s", drive.source, drive.target)

    _heading("=== The channels each simulation has: calculated, nothing declared these")
    for sample in instrument.samples():
        for simulation in instrument.sample_holder(sample).simulations:
            current = {**state, instrument.simulation_key(sample): simulation}
            found = compiled.channels(current)
            named = channel_names(instrument, found, current, lambda name, slot: f"{name}={slot}")
            for channel, (name, _) in zip(found, named):
                if channel.sample != sample:
                    continue
                swaps = ", ".join(f"{name}={slot}" for name, slot in channel.swaps.items())
                report.info(
                    "  %s: %s: %s: %s -> %s, %.4g electrons at full power, at %.0f nm%s",
                    sample,
                    simulation,
                    name,
                    channel.source,
                    channel.detector,
                    channel.electrons,
                    channel.band_nm,
                    f", with {swaps}" if swaps else "",
                )

    _heading("=== What each detector will see, for each combination of swaps")
    for current in instrument.swap_states():
        if any(
            current[instrument.simulation_key(sample)]
            != instrument.sample_holder(sample).simulation
            for sample in instrument.samples()
        ):
            continue
        swaps = {
            v.name: current[v.name] for v in instrument.variables.values() if v.verb == "swaps"
        }
        for detector in instrument.detectors():
            if instrument.sample_of(detector, current) is None:
                report.info("  %s %s: dark, the switches send its light elsewhere", swaps, detector)
                continue
            answer = compiled.answer(detector, current)
            report.info(
                "  %s %s: %.3f um/px, fov %.0f um, band %.0f nm, %.0f counts, corner %.2f",
                swaps,
                detector,
                _size_and_rotation(np.array(answer.pixel_to_stage))[0],
                answer.field_of_view_um[0],
                answer.band_nm or 0,
                answer.light,
                answer.relative_illumination,
            )

    roles = Roles(instrument)
    microscope = SimulatedMicroscope(instrument)
    # One light: what emits from a bead and what a bead shadows would cancel out.
    powers = [f"{source}.power" for source in instrument.sources()]
    powers = [name for name in powers if name in instrument.variables]
    microscope.set({name: 0.0 for name in powers})
    if powers:
        source = instrument.cubes[powers[0].split(".")[0]]
        microscope.set({powers[0]: source.element_at(state).max_power})
    _heading("=== Measure images with newswitch's own calibration code, under %s", powers[:1])
    report.info("  %-22s %10s %10s", "", "predicted", "measured")
    for detector in instrument.detectors():
        sample = instrument.sample_of(detector, microscope.state)
        if sample is None:
            report.info("  %s: dark, the switches send its light elsewhere", detector)
            continue
        if not (roles.sideways(detector, "x", sample) and roles.sideways(detector, "y", sample)):
            report.info("  %s: nothing moves its view", detector)
            continue
        predicted = _size_and_rotation(
            np.array(compiled.answer(detector, microscope.state).pixel_to_stage)
        )[0]
        save(out, detector, microscope.image(detector))
        try:
            size, turn = measure(microscope, detector)
        except ValueError as error:
            report.info("  %s: %s", detector, error)
            continue
        mismatch = (size / predicted - 1.0) * 100.0
        report.info(
            "  %s um/px          %10.4f %10.4f   %s (%+.2f%%)",
            detector,
            predicted,
            size,
            flag(mismatch, SCALE_TOLERANCE_PERCENT),
            mismatch,
        )
        report.info(
            "  %s turn, degrees  %10.2f %10.2f   %s",
            detector,
            0.0,
            turn,
            flag(turn, ROTATION_TOLERANCE_DEG),
        )

    _heading("=== Swap each: where the design says the image does not move, does it?")
    for swap in (v for v in instrument.variables.values() if v.verb == "swaps"):
        start = microscope.state[swap.name]
        for detector in instrument.detectors():
            before = microscope.image(detector)
            for slot in swap.slots:
                if slot == start:
                    continue
                microscope.set({swap.name: slot})
                predicted = difference(
                    compiled.answer(detector, {**microscope.state, swap.name: start}),
                    compiled.answer(detector, microscope.state),
                )
                if "scale" not in predicted:
                    shift = pixel_shift(before, microscope.image(detector))
                    report.info(
                        "  %s=%s %s: measured (%+.2f, %+.2f) px   %s",
                        swap.name,
                        slot,
                        detector,
                        shift[0],
                        shift[1],
                        flag(float(np.hypot(*shift)), SHIFT_TOLERANCE_PX),
                    )
            microscope.set({swap.name: start})

    if microscope.truth:
        _heading("=== The truth, now that everyone has answered")
        for name, value in microscope.truth.items():
            report.info("  %s: %s", name, value)


if __name__ == "__main__":
    main()
