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

from newswitch.drivers.simulator import SimulatedMicroscope
from newswitch.instrument.compiler import compile_instrument, difference, impacts
from newswitch.instrument.roles import Roles
from newswitch.instrument.spec import load
from newswitch.routines.affine_matrix import calibrate_pixel_to_stage, pixel_shift

#: How far apart prediction and measurement may be before it is worth saying so.
SCALE_TOLERANCE_PERCENT = 0.5
ROTATION_TOLERANCE_DEG = 0.25
SHIFT_TOLERANCE_PX = 0.5


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
    roles = Roles(microscope.simulator.instrument)
    move_x, move_y = roles.x(detector).name, roles.y(detector).name
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


def main(argv: list[str] | None = None) -> None:
    """Run the loop on the instrument the command line names."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("instrument", type=Path, help="the instrument's folder")
    instrument = load(parser.parse_args(argv).instrument)
    compiled = compile_instrument(instrument)
    out = instrument.folder / "out"
    print(f"=== {len(compiled.states)} combinations, {len(instrument.detectors())} detectors")

    print("\n=== What impacts what: calculated, nothing declared this")
    for row in impacts(instrument, instrument.initial_state()):
        changes = ", ".join(f"{k} {v:.3g}" for k, v in row["changes"].items()) or "nothing"
        print(f"  {row['variable']:20} {row['verb']:6} {row['detector']:9} -> {changes}")

    state = instrument.initial_state()
    print("\n=== The logical detectors: what each delivers, from its parts and its wires")
    for detector in instrument.detectors():
        axes = ", ".join(
            f"{axis.name}{'*' if axis.size is None else ''}"
            for axis in instrument.detector_axes(detector)
        )
        print(f"  {detector}: ({axes})")
    for drive in instrument.drives:
        print(f"  wire: {drive.source} -> {drive.target}")

    print("\n=== The channels each simulation has: calculated, nothing declared these")
    for sample in instrument.samples():
        for simulation in instrument.sample_holder(sample).simulations:
            current = {**state, instrument.simulation_key(sample): simulation}
            for channel in compiled.channels(current):
                if instrument.sample_of(channel.detector) != sample:
                    continue
                print(
                    f"  {sample}: {simulation}: {channel.source} -> {channel.detector}, "
                    f"{channel.electrons:.4g} electrons at full power, at {channel.band_nm:.0f} nm"
                )

    print("\n=== What each detector will see, for each combination of swaps")
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
            answer = compiled.answer(detector, current)
            print(
                f"  {swaps} {detector}: {_size_and_rotation(np.array(answer.pixel_to_stage))[0]:.3f} "
                f"um/px, fov {answer.field_of_view_um[0]:.0f} um, "
                f"band {answer.band_nm or 0:.0f} nm, {answer.light:.0f} counts, "
                f"corner {answer.relative_illumination:.2f}"
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
    print(f"\n=== Measure images with newswitch's own calibration code, under {powers[:1]}")
    print(f"  {'':22} {'predicted':>10} {'measured':>10}")
    for detector in instrument.detectors():
        if not (roles.sideways(detector, "x") and roles.sideways(detector, "y")):
            print(f"  {detector}: nothing moves its view")
            continue
        predicted = _size_and_rotation(
            np.array(compiled.answer(detector, microscope.state).pixel_to_stage)
        )[0]
        save(out, detector, microscope.image(detector))
        try:
            size, turn = measure(microscope, detector)
        except ValueError as error:
            print(f"  {detector}: {error}")
            continue
        mismatch = (size / predicted - 1.0) * 100.0
        print(
            f"  {detector} um/px          {predicted:10.4f} {size:10.4f}   "
            f"{flag(mismatch, SCALE_TOLERANCE_PERCENT)} ({mismatch:+.2f}%)"
        )
        print(
            f"  {detector} turn, degrees  {0.0:10.2f} {turn:10.2f}   "
            f"{flag(turn, ROTATION_TOLERANCE_DEG)}"
        )

    print("\n=== Swap each: where the design says the image does not move, does it?")
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
                    print(
                        f"  {swap.name}={slot} {detector}: measured "
                        f"({shift[0]:+.2f}, {shift[1]:+.2f}) px   "
                        f"{flag(float(np.hypot(*shift)), SHIFT_TOLERANCE_PX)}"
                    )
            microscope.set({swap.name: start})

    if microscope.truth:
        print("\n=== The truth, now that everyone has answered")
        for name, value in microscope.truth.items():
            print(f"  {name}: {value}")


if __name__ == "__main__":
    main()
