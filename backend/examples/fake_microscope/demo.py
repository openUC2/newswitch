"""The whole loop: what the design predicts, what the images measure, and what was really there.

    uv run --with optiland python -m examples.fake_microscope.demo

Images land in ``examples/fake_microscope/out/``.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from examples.fake_microscope.compiler import compile_instrument
from examples.fake_microscope.hardware import FakeMicroscope
from examples.fake_microscope.predict import Compiled
from examples.fake_microscope.spec import load
from newswitch.routines.affine_matrix import calibrate_pixel_to_stage, pixel_shift

OUT = Path(__file__).parent / "out"

#: How far apart prediction and measurement may be before it is worth saying so.
SCALE_TOLERANCE_PERCENT = 0.5
ROTATION_TOLERANCE_DEG = 0.25
SHIFT_TOLERANCE_PX = 0.5


def save(name: str, frame: np.ndarray) -> None:
    """Keep an image to look at, stretched to its own range."""
    OUT.mkdir(exist_ok=True)
    low, high = np.percentile(frame, (0.5, 99.9))
    scaled = np.clip((frame.astype(float) - low) / max(high - low, 1.0), 0.0, 1.0)
    Image.fromarray((scaled * 255).astype(np.uint8)).save(OUT / f"{name}.png")


def _stage_moves(
    microscope: FakeMicroscope, detector: str, step: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """An image, one after moving the stage in x, and one after moving it in y."""
    x, y = microscope.state["stage.x"], microscope.state["stage.y"]
    reference = microscope.image(detector)
    microscope.set({"stage.x": x + step})
    moved_x = microscope.image(detector)
    microscope.set({"stage.x": x, "stage.y": y + step})
    moved_y = microscope.image(detector)
    microscope.set({"stage.y": y})
    return reference, moved_x, moved_y


def _size_and_rotation(matrix: np.ndarray) -> tuple[float, float]:
    """Pixel size, and the turn of the x column, which flips and inversion do not change."""
    sign = np.sign(matrix[0, 0])
    return float(np.hypot(matrix[0, 0], matrix[1, 0])), math.degrees(
        math.atan2(matrix[1, 0] * sign, matrix[0, 0] * sign)
    )


def measure(microscope: FakeMicroscope, detector: str) -> tuple[float, float]:
    """newswitch's own calibration arithmetic on the fake images: pixel size, and its turn."""
    step = 100.0
    frames = _stage_moves(microscope, detector, step)
    return _size_and_rotation(np.array(calibrate_pixel_to_stage(*frames, step, step)))


def flag(mismatch: float, tolerance: float) -> str:
    """Whether a difference is worth saying something about."""
    return "MISMATCH" if abs(mismatch) > tolerance else "ok"


def main() -> None:
    """Run the loop."""
    instrument = load()
    print("=== Compile: ray trace every combination of swaps, and nudge every variable")
    compiled = Compiled.load(instrument, compile_instrument(instrument))
    print(f"  {len(compiled.states)} combinations, {len(instrument.detectors())} detectors")

    print("\n=== What impacts what: calculated, nothing declared this")
    for row in compiled.impacts:
        if row["detector"] != "camera-a" and row["variable"] not in (
            "camera-b.exposure",
            "tube-a.dz",
        ):
            continue
        changes = ", ".join(f"{k} {v:.3g}" for k, v in row["changes"].items()) or "nothing"
        print(f"  {row['variable']:20} {row['verb']:6} {row['detector']:9} -> {changes}")

    state = instrument.initial_state()
    print("\n=== What each detector will see, from the table")
    for slot in (1, 2):
        current = {**state, "filter-wheel.slot": slot}
        for detector in instrument.detectors():
            answer = compiled.answer(detector, current)
            pixel = abs(answer.pixel_to_stage[0][0])
            print(
                f"  filter {slot} {detector}: {pixel:.3f} um/px, flip x {answer.pixel_to_stage[0][0] > 0}, "
                f"fov {answer.field_of_view_um[0]:.0f} um, band {answer.band_nm or 0:.0f} nm, "
                f"{answer.light:.0f} counts, corner {answer.relative_illumination:.2f}"
            )

    print("\n=== Which source reaches which detector, per filter (mW-normalised light)")
    for key, entry in compiled.states.items():
        if "objective.slot=1" not in key:
            continue
        row = {
            d: {s: round(c["light_per_mw"], 4) for s, c in entry[d]["coupling"].items()}
            for d in entry
        }
        print(f"  {key}: {row['camera-a']}")

    microscope = FakeMicroscope(instrument)
    print("\n=== Measure the fake images with newswitch's own calibration code")
    print(f"  {'':22} {'predicted':>10} {'measured':>10}")
    for detector in instrument.detectors():
        microscope.set({"filter-wheel.slot": 1})
        predicted = abs(compiled.answer(detector, microscope.state).pixel_to_stage[0][0])
        size, turn = measure(microscope, detector)
        mismatch = (size / predicted - 1.0) * 100.0
        print(
            f"  {detector} um/px          {predicted:10.4f} {size:10.4f}   "
            f"{flag(mismatch, SCALE_TOLERANCE_PERCENT)} ({mismatch:+.2f}%)"
        )
        print(
            f"  {detector} turn, degrees  {0.0:10.2f} {turn:10.2f}   "
            f"{flag(turn, ROTATION_TOLERANCE_DEG)}"
        )
        save(f"{detector}-filter1", microscope.image(detector))

    print("\n=== Swap the filter: the design says the image cannot move")
    for detector in instrument.detectors():
        microscope.set({"filter-wheel.slot": 1})
        before = microscope.image(detector)
        microscope.set({"filter-wheel.slot": 2})
        after = microscope.image(detector)
        save(f"{detector}-filter2", after)
        shift = pixel_shift(before, after)
        print(
            f"  {detector}: predicted 0.00 px, measured ({shift[0]:+.2f}, {shift[1]:+.2f})   "
            f"{flag(float(np.hypot(*shift)), SHIFT_TOLERANCE_PX)}"
        )

    print("\n=== A black image, predicted before taking it: the LED through the green filter")
    microscope.set({"filter-wheel.slot": 2, "laser-488.power": 0.0, "led-625.power": 2.0})
    answer = compiled.answer("camera-a", microscope.state)
    frame = microscope.image("camera-a")
    print(
        f"  predicted {answer.light:.1f} counts, black: {answer.black}; "
        f"image mean {frame.mean() - 100:.1f} above the offset"
    )
    microscope.set({"filter-wheel.slot": 1})
    answer = compiled.answer("camera-a", microscope.state)
    save("camera-a-transmitted", microscope.image("camera-a"))
    print(f"  filter open: predicted {answer.light:.0f} counts, black: {answer.black}")

    print("\n=== The truth, now that everyone has answered")
    for name, value in microscope.truth.items():
        print(f"  {name}: {value}")


if __name__ == "__main__":
    main()
