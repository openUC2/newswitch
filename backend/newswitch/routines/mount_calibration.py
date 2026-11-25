"""Measuring where a holder sits on the stage, its mount, from a calibration slide's mark.

The description says what lies where: a holder (``holders``, from the library) with its `mount`,
the place of its origin on the stage, counted from where homing puts the stage; and its
`calibration`, a calibration slide centred in one of the holder's places, with a mark that shows
in an image (`newswitch.instrument.spec.Calibration`). Where the mark is on the holder is known,
then. The stage is homed, taken to where the mount puts the mark, the mark is looked for and
brought into the middle of the image: there the stage is at the mark, and the mount is where the
stage is less where the mark is on the holder. It is used at once and written into the
description, which stays the one place a holder's position is stated.

The stage's own 0 is where homing puts it: nothing of the sample is measured from anywhere else.
"""


import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np
from arkitekt import AssignPrompt, Task

from koil import unkoil

from newswitch import protocols
from newswitch.instrument.space import holder_to_stage
from newswitch.instrument.spec import _UNITS, Calibration, Instrument, Mount
from newswitch.models.calibration import MeasuredMount
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.services.space import SpaceManager
from newswitch.services.values import Values
from newswitch.states.mount_calibration import MountCalibrationState

logger = logging.getLogger(__name__)

#: How far the brightest pixel must stand above the image's median, in units of its noise (the
#: median absolute deviation, at least 1): a mark in transmitted light is a disc on black.
MIN_CONTRAST = 50.0
#: How many pixels a mark covers at least, and at most as a share of the image.
MIN_PIXELS = 50
MAX_SHARE = 0.5
#: How far the stage is moved to measure how the image follows it, in micrometres.
PROBE_UM = 50.0
#: When the mark is in the middle: within this many pixels.
CENTRED_PX = 1.5
#: How often it is moved towards the middle at most.
CENTRING_STEPS = 8


@dataclass(frozen=True)
class Spot:
    """A bright disc in an image: its middle from the image's middle, in pixels (x to the
    right, y down), how wide it is, and whether the image's edge cuts it."""

    x: float
    y: float
    diameter: float
    cut: bool


def bright_spot(image: np.ndarray) -> Optional[Spot]:
    """The bright disc in `image`, if there is one: what stands far above the rest."""
    gray = np.asarray(image, dtype=float)
    if gray.ndim == 3:
        gray = gray.mean(axis=2)
    background = float(np.median(gray))
    noise = max(float(np.median(np.abs(gray - background))), 1.0)
    brightest = float(gray.max())
    if brightest - background < MIN_CONTRAST * noise:
        return None
    mask = gray > background + 0.5 * (brightest - background)
    count = int(mask.sum())
    if count < MIN_PIXELS or count > MAX_SHARE * mask.size:
        return None
    ys, xs = np.nonzero(mask)
    height, width = gray.shape
    cut = bool(xs.min() == 0 or ys.min() == 0 or xs.max() == width - 1 or ys.max() == height - 1)
    return Spot(
        x=float(xs.mean()) - (width - 1) / 2,
        y=float(ys.mean()) - (height - 1) / 2,
        diameter=2.0 * math.sqrt(count / math.pi),
        cut=cut,
    )


def spiral(radius_um: float, step_um: float) -> Iterator[tuple[float, float]]:
    """Offsets to look at, nearest first: the middle, then square rings `step_um` apart."""
    yield 0.0, 0.0
    rings = int(radius_um // step_um)
    for ring in range(1, rings + 1):
        ring_offsets = [
            (i * step_um, j * step_um)
            for i in range(-ring, ring + 1)
            for j in range(-ring, ring + 1)
            if max(abs(i), abs(j)) == ring
        ]
        yield from sorted(ring_offsets, key=lambda o: math.hypot(*o))


def mount_from(stage_um: tuple[float, float], mark_mm: tuple[float, float], rotation: float) -> Mount:
    """The mount of a holder turned by `rotation` whose place `mark_mm` is at `stage_um`."""
    turn = math.radians(rotation)
    mx, my = mark_mm[0] * 1000.0, mark_mm[1] * 1000.0
    x = stage_um[0] - (math.cos(turn) * mx - math.sin(turn) * my)
    y = stage_um[1] - (math.sin(turn) * mx + math.cos(turn) * my)
    return mount_of(round(x) / 1000.0, round(y) / 1000.0, rotation)


def mount_of(x_mm: float, y_mm: float, rotation: float = 0.0) -> Mount:
    """A mount from numbers: millimetres, and degrees."""
    return Mount(x=f"{x_mm!r} mm", y=f"{y_mm!r} mm", rotation=f"{rotation!r} deg")  # type: ignore[arg-type]


def _mm(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") + " mm"


def write_mount(path: Path, sample: str, holder: str, mount: Mount) -> None:
    """Write `mount` as the mount of `holder` of the cube `sample` into the description at `path`,
    leaving the rest of it as it is.

    Raises:
        ValueError: The description does not state that mount as ``mount: {...}`` on one line.
    """
    lines = path.read_text().splitlines(keepends=True)
    stated = f"x: {_mm(mount.x)}, y: {_mm(mount.y)}"
    if mount.rotation:
        stated += f", rotation: {mount.rotation:g} deg"

    def indent(line: str) -> int:
        return len(line) - len(line.lstrip())

    def find(start: int, stop: int, key: str) -> int:
        for index in range(start, stop):
            if re.match(rf"\s*{re.escape(key)}:(\s|$)", lines[index]):
                return index
        raise ValueError(f"{path}: no {key}: where the mount of {sample}'s {holder} is")

    def end_of(start: int) -> int:
        for index in range(start + 1, len(lines)):
            if lines[index].strip() and not lines[index].lstrip().startswith("#"):
                if indent(lines[index]) <= indent(lines[start]):
                    return index
        return len(lines)

    cube = find(find(0, len(lines), "cubes"), len(lines), sample)
    holders = find(cube, end_of(cube), "holders")
    entry = find(holders, end_of(holders), holder)
    for index in range(entry, end_of(entry)):
        found = re.search(r"mount:\s*\{[^}]*\}", lines[index])
        if found:
            lines[index] = (
                lines[index][: found.start()] + f"mount: {{{stated}}}" + lines[index][found.end() :]
            )
            path.write_text("".join(lines))
            return
    raise ValueError(f"{path}: the mount of {sample}'s {holder} is not stated as mount: {{...}}")


def _description_file() -> Optional[Path]:
    """The description this run was started with, if a measured mount is written into it: not
    when the run is simulated (``simulate: everything`` or ``virtual``), whose mount says nothing
    of the real microscope the description is of."""
    from newswitch.settings import SIMULATED, load_settings

    settings = load_settings()
    if settings.simulate in SIMULATED:
        logger.info("a simulated run (%s): the mount is not written down", settings.simulate)
        return None
    named = settings.instrument
    if named is None:
        return None
    return named / "microscope.yml" if named.is_dir() else named


def _quantity(instrument: Instrument, name: str, stated: str) -> Any:  # noqa: ANN401
    """`stated` in the unit of the variable `name`."""
    variable = instrument.variables.get(name)
    if variable is None:
        raise ValueError(f"calibration: {name} is no variable: {sorted(instrument.variables)}")
    unit = getattr(variable, "unit", "")
    if not unit:
        return float(stated)
    return float(_UNITS.Quantity(stated).to(unit).magnitude)


def _moves_along(instrument: Instrument, sample: str, along: str) -> str:
    for variable in instrument.variables.values():
        if variable.cube == sample and variable.verb == "moves" and variable.along == along:
            return variable.name
    raise ValueError(f"{sample} does not move along {along}")


def _detector(space: SpaceManager, calibration: Calibration, sample: str) -> str:
    if calibration.detector is not None:
        return calibration.detector
    for detector in space.detector_state.detectors:
        if not detector.delivers_images():
            continue
        try:
            if space.sample_of(detector.name) == sample:
                return detector.name
        except Exception:  # noqa: BLE001 - one the switches keep dark: not this one
            continue
    raise ValueError(f"no detector looks at {sample}: name one (calibration: detector)")


def calibrate_mount(
    space: SpaceManager,
    values: Values,
    detector_manager: protocols.DetectorManager,
    uc2_bus: UC2BusManager,
    mount_calibration: MountCalibrationState,
    task: Task,
    sample: Optional[str] = None,
    save: bool = True,
    confirm: bool = True,
) -> MeasuredMount:
    """Measure where the calibration's holder sits on the stage, from its calibration slide.

    Homes what the calibration says (the stage's 0 is there), sets what it says (light, focus),
    goes where the holder's mount puts the mark and holds: someone checks that the stage was homed
    and the light falls on the calibration slide's mark, and approves. Then it looks for the mark
    around there, brings it into the middle of the image and takes the mount from where the stage
    is. The mount is used from then on, and written into the description.

    Args:
        sample: Which sample, by the cube holding it; may be left out when there is one.
        save: Write the mount into the description (else it holds until the next start).
        confirm: Hold for a person to check the light is on the mark before looking for it.

    Raises:
        ValueError: The sample has no calibration, the hold was denied, or the mark was not found
            or not centred.
    """
    state = mount_calibration

    def step(progress: int, what: str) -> None:
        state.progress, state.step = progress, what
        task.progress(progress, what)

    instrument = values.instrument
    sample = space.one_sample(sample)
    holding = instrument.sample_holder(sample)
    calibration = holding.calibration
    if calibration is None:
        raise ValueError(f"{sample} states no calibration (calibration: in its element)")
    mounted = space.mounted_holder(calibration.holder, sample)
    mark = holding.mark_on_holder()
    x_name, y_name = _moves_along(instrument, sample, "x"), _moves_along(instrument, sample, "y")
    detector = _detector(space, calibration, sample)
    settings = {name: _quantity(instrument, name, text) for name, text in calibration.values.items()}
    before = values.snapshot()
    restore = {n: before[n] for n in settings if n not in (x_name, y_name)}

    state.busy, state.error, state.waiting = True, None, None
    try:
        for index, axis in enumerate(calibration.home):
            step(int(10 * index / len(calibration.home)), f"homing {axis}")
            unkoil(uc2_bus.ahome_axis, axis)

        step(10, "light and focus on the calibration slide")
        values.set(settings, task=task)
        if not any(d.name == detector and d.is_active for d in space.detector_state.detectors):
            detector_manager.activate_detector(detector)

        def go(x: float, y: float) -> None:
            values.set({x_name: x, y_name: y}, task=task)

        def look() -> Optional[Spot]:
            return bright_spot(detector_manager.capture_image(detector).data)

        expected = holder_to_stage(mounted.mount) @ np.array([mark[0] * 1e3, mark[1] * 1e3, 0, 1])
        # Where the stage is, as commanded: a board's position at rest is not always what it
        # reports (some report 0), and every move here is one this routine made.
        x0, y0 = float(expected[0]), float(expected[1])
        go(x0, y0)

        if confirm:
            homed = ", ".join(calibration.home) or "nothing"
            question = (
                f"Homed ({homed}): the stage's 0 is at its endstops. The stage is where the "
                f"{calibration.mark} of the calibration slide in {calibration.at} should be: does "
                f"the light fall on it? Approve to look for it and centre it; deny to stop."
            )
            step(12, "waiting for you: does the light fall on the calibration mark?")
            state.waiting = question
            decision = task.hold(
                question,
                prompt=AssignPrompt(
                    title="Homed: does the light fall on the calibration mark?",
                    description=(
                        f"The stage was homed and moved to where {calibration.holder}'s mount puts "
                        f"the {calibration.mark} of the slide in {calibration.at}. Check the light "
                        "spot lies on it (it may be off by a millimetre or two: it is looked for)."
                    ),
                ),
            )
            state.waiting = None
            if not decision.approved:
                raise ValueError("stopped: the hold was denied (the light is not on the mark)")

        spot = None
        offsets = list(spiral(calibration.search_radius * 1e3, calibration.search_step * 1e3))
        for index, (dx, dy) in enumerate(offsets):
            step(15 + int(40 * index / len(offsets)), f"looking for the mark ({index + 1})")
            x0, y0 = float(expected[0] + dx), float(expected[1] + dy)
            go(x0, y0)
            spot = look()
            if spot is not None:
                break
        if spot is None:
            raise ValueError(
                f"no mark within {calibration.search_radius:g} mm of where the mount puts it "
                f"(stage {expected[0]:.0f}, {expected[1]:.0f} um): is the slide in "
                f"{calibration.at}, the light on and the image in focus?"
            )

        # how the mark moves in the image as the stage moves: pixels per micrometre
        step(60, "measuring how the image follows the stage")
        start = spot
        columns = []
        for ddx, ddy in ((PROBE_UM, 0.0), (0.0, PROBE_UM)):
            go(x0 + ddx, y0 + ddy)
            moved = look()
            if moved is None:
                raise ValueError("the mark left the image while measuring how it follows the stage")
            columns.append(((moved.x - start.x) / PROBE_UM, (moved.y - start.y) / PROBE_UM))
        follows = np.array(columns).T  # pixels per micrometre: d(px) = follows @ d(stage)
        if abs(np.linalg.det(follows)) < 1e-6:
            raise ValueError("the image does not follow the stage: is the mark on the stage?")

        step(75, "centring the mark")
        x, y = x0, y0
        go(x, y)
        spot = look()
        for _ in range(CENTRING_STEPS):
            if spot is None:
                raise ValueError("the mark was lost while centring it")
            if math.hypot(spot.x, spot.y) <= CENTRED_PX:
                break
            dx, dy = -np.linalg.solve(follows, np.array([spot.x, spot.y]))
            x, y = x + float(dx), y + float(dy)
            go(x, y)
            spot = look()
        if spot is None or math.hypot(spot.x, spot.y) > CENTRED_PX:
            raise ValueError("the mark could not be brought into the middle of the image")

        mount = mount_from((x, y), mark, mounted.mount.rotation)
        space.set_mount(calibration.holder, mount, sample)
        saved = None
        if save:
            path = _description_file()
            if path is not None:
                write_mount(path, sample, calibration.holder, mount)
                saved = str(path)
        pixel_um = 1.0 / math.sqrt(abs(np.linalg.det(follows)))
        shift = [(mount.x - mounted.mount.x) * 1e3, (mount.y - mounted.mount.y) * 1e3]
        logger.info(
            "mount of %s's %s: (%s, %s) mm, %.0f / %.0f um from before; %.3f um per pixel",
            sample,
            calibration.holder,
            mount.x,
            mount.y,
            shift[0],
            shift[1],
            pixel_um,
        )
        result = MeasuredMount(
            sample=sample,
            holder=calibration.holder,
            x_mm=mount.x,
            y_mm=mount.y,
            rotation_deg=mount.rotation,
            shift_um=shift,
            pixel_um=pixel_um,
            saved_to=saved,
        )
        state.mount_x_mm, state.mount_y_mm, state.last = mount.x, mount.y, result
        step(100, "measured" + ("" if saved else " (not saved)"))
        return result
    except BaseException as error:
        state.error = str(error) or type(error).__name__
        state.step = "failed" if isinstance(error, Exception) else "stopped"
        raise
    finally:
        state.busy, state.waiting = False, None
        if restore:
            values.set(restore)
