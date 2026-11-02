"""Performing an acquisition: every channel, on every plane, at every position, every time.

What it takes is merged rather than saved image by image: every detector of every channel becomes
channels of the dataset, and each position one ``(t, c, z, y, x)`` dataset in the `DatasetStore`,
placed in stage space, with nothing in the local cache. A plan is regular by what it is, so what is
left to refuse, before anything moves, is what cannot be one array: uneven planes, detectors that
disagree on their image size or pixel size under what their channel sets.
"""

import logging
import os
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
from arkitekt import Task

from newswitch import protocols
from newswitch.instrument.spec import Move
from newswitch.models.acquisition import (
    AcquiredDataset,
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    PositionOrder,
)
from newswitch.models.devices import Detector
from newswitch.protocols.dataset_store import (
    AcquiredChannel,
    AcquiredPlane,
    AcquiredPosition,
    DatasetStore,
)
from newswitch.services.stage import where
from newswitch.services.values import Values

logger = logging.getLogger(__name__)

#: How far apart the pixel sizes of two channels may be: one registration maps them all.
SCALE_TOLERANCE = 0.01


@dataclass(frozen=True)
class _Exposure:
    """What one detector contributes to a channel: dataset channels, from `first_channel` on."""

    detector: Detector
    first_channel: int
    flip_x: bool
    flip_y: bool


@dataclass(frozen=True)
class _Lighting:
    """One channel of the plan: what to set for it, and what it exposes."""

    channel: AcquisitionChannel
    targets: Mapping[str, float]
    exposures: tuple[_Exposure, ...]


@dataclass
class _Merge:
    """What is being acquired at one position, and what it has so far."""

    position: AcquisitionPosition
    index: int
    offsets: list[float]
    sweep: Move | None
    lightings: tuple[_Lighting, ...]
    channels: tuple[AcquiredChannel, ...]
    data: np.ndarray
    dims: tuple[str, ...]  # the axes of `data`: t, c, then what the detectors deliver
    planes: list[AcquiredPlane]
    pixel_to_world: np.ndarray  # x, y pixels to x, y micrometres, every axis increasing
    calibrated: bool
    swept: bool
    x: float = 0.0
    y: float = 0.0
    first_z: float | None = None
    light_moves: tuple[Move, ...] = ()


def _z_step(detector: Detector) -> float | None:
    """How far each image of `detector` steps what its wire reaches, if it delivers z by itself."""
    return next((axis.step for axis in detector.axes if axis.name == "z"), None)


def _check_sweep(
    plan: AcquisitionPlan,
    offsets: list[float],
    lightings: list[_Lighting],
    sweep: Move | None,
    values: Values,
) -> bool:
    """Whether a position's stack is swept, by detectors whose wires step what sweeps it.

    Raises:
        ValueError: What is asked for is not what such a wire can do. Nothing has moved then.
    """
    detectors = [exposure.detector for lighting in lightings for exposure in lighting.exposures]
    steps = {detector.name: _z_step(detector) for detector in detectors}
    wired = [values.instrument.z_drive(name) for name in steps]
    if all(step is None for step in steps.values()) or (
        sweep is not None
        and plan.stack.variable is not None
        and all(drive is not None and drive.target != sweep.name for drive in wired)
    ):
        # Nothing here steps itself, or what was named is another: moved plane by plane.
        return False
    if any(step is None for step in steps.values()) or any(
        len(lighting.exposures) > 1 for lighting in lightings
    ):
        raise ValueError(
            f"Detectors that step the stage by themselves take a stack alone, not with others: "
            f"{sorted(steps)}"
        )
    for name, step in steps.items():
        if not np.allclose(np.diff(offsets), step):
            target = values.instrument.z_drive(name).target
            raise ValueError(f"{name} steps {target} by {step} um, not as in {offsets}")
        drive = values.instrument.z_drive(name)
        if sweep is None or drive is None or drive.target != sweep.name:
            raise ValueError(f"{name} steps {drive and drive.target}, so it sweeps only that")
    if plan.z_hooks:
        raise ValueError("Nothing can run between the planes of a stack a detector sweeps")
    return True


def _find_detector(name: str, detector_manager: protocols.DetectorManager) -> Detector:
    """The detector called `name`."""
    available = detector_manager.list_available_detectors()
    for detector in available:
        if name == detector.name:
            return detector
    raise ValueError(f"No detector {name!r}: there are {[d.name for d in available]}")


def _offsets_of(plan: AcquisitionPlan) -> list[float]:
    """Where a stack's planes are, from the position; evenly spaced, or it is no array."""
    offsets = list(plan.stack.offsets) or [0.0]
    steps = np.diff(offsets)
    if len(steps) and (np.any(steps <= 0) or not np.allclose(steps, steps[0])):
        raise ValueError(f"The planes of a stack must be evenly spaced and rising, not {offsets}")
    return offsets


def _sweep_of(
    plan: AcquisitionPlan, offsets: list[float], detector: str, values: Values
) -> Move | None:
    """What sweeps a stack: none for one plane where it is, unless one is named.

    What a detector's own wire steps, or what is named among what moves through the sample or
    focuses; otherwise the one thing that does either.
    """
    named = plan.stack.variable
    if named is None and offsets == [0.0]:
        return None
    instrument = values.instrument
    wired = instrument.z_drive(detector)
    if wired is not None and named in (None, wired.target):
        return instrument.variables[wired.target]
    through = instrument.sample_moves()
    if named in (move.name for move in through):
        return instrument.variables[named]
    if values.roles.focuses(detector):
        return values.roles.focus(detector, named)
    return values.roles.one(f"what moves through the sample of {detector}", through, named)


def _lights_of(channel: AcquisitionChannel, values: Values) -> dict[str, float]:
    """What a channel sets, and that a source it does not name is off."""
    off = {
        source.power_variable: 0.0
        for source in values.source_state.sources.values()
        if source.power_variable is not None
    }
    return {**off, **values.resolved(channel.set_to)}


def _sources_of(targets: Mapping[str, float], values: Values) -> tuple[str, ...]:
    """Which sources a channel lights, by name."""
    return tuple(
        source.name
        for source in values.source_state.sources.values()
        if source.power_variable is None or targets.get(source.power_variable, 0.0) > 0.0
    )


def _channel_label(channel: AcquisitionChannel, detector: Detector, color: str | None) -> str:
    return " ".join(part for part in (channel.name, detector.name, color) if part)


def _plan_position(
    plan: AcquisitionPlan,
    position: AcquisitionPosition,
    index: int,
    offsets: list[float],
    sweep: Move | None,
    detector_manager: protocols.DetectorManager,
    optics_manager: protocols.OpticsManager,
    values: Values,
) -> _Merge:
    """Everything that can be refused about one position, and the array it will fill."""
    values.check(position.set_to)
    at = {**values.snapshot(), **values.resolved(position.set_to)}
    if sweep is not None:
        values.check({sweep.name: at[sweep.name] + offset for offset in offsets})

    reference: np.ndarray | None = None
    size: tuple[int, int] | None = None
    bins: set[int | None] = set()
    types: set[str] = set()
    calibrated = True
    lightings: list[_Lighting] = []
    channels: list[AcquiredChannel] = []
    for channel in plan.channels:
        if not channel.detectors:
            raise ValueError(f"The channel {channel.name!r} names no detector")
        targets = _lights_of(channel, values)
        values.check(targets)
        under = {**at, **targets}
        names = _sources_of(targets, values)
        exposures: list[_Exposure] = []
        for name in channel.detectors:
            detector = _find_detector(name, detector_manager)
            shape = detector_manager.plane_under(name, under.get(f"{name}.binning"))
            if size is None:
                size = shape
            elif size != shape:
                raise ValueError(
                    f"{detector.name} takes images of {shape[0]} x {shape[1]}, others "
                    f"{size[0]} x {size[1]}: they cannot share an array"
                )
            bins.add(next((axis.size for axis in detector.axes if axis.name == "m"), None))
            if len(bins) > 1:
                raise ValueError(
                    f"{detector.name} has {sorted(map(str, bins))} arrival-time bins and others "
                    "have not: they cannot share an array"
                )
            types.add(detector.data_type)
            scale, measured = optics_manager.scale_under(name, under)
            matrix = scale.affine_matrix
            # A calibration says how far the stage moves to shift the image by a pixel, the
            # opposite of which point of the sample that pixel sees.
            to_world = -np.array([[matrix[0][0], matrix[0][1]], [matrix[1][0], matrix[1][1]]])
            flip_x, flip_y = bool(to_world[0, 0] < 0), bool(to_world[1, 1] < 0)
            upright = to_world * np.array([[-1 if flip_x else 1, -1 if flip_y else 1]] * 2)
            if reference is None:
                reference = upright
            elif not np.allclose(
                np.diag(upright), np.diag(reference), rtol=SCALE_TOLERANCE, atol=0.0
            ):
                raise ValueError(
                    f"{detector.name} has pixels of {np.diag(upright).tolist()} um, the others "
                    f"{np.diag(reference).tolist()}: one dataset has one pixel size"
                )
            calibrated = calibrated and measured
            exposures.append(_Exposure(detector, len(channels), flip_x, flip_y))
            channels.extend(
                AcquiredChannel(
                    label=_channel_label(channel, detector, color),
                    detector=detector.name,
                    sources=names,
                    color=color,
                )
                for color in (detector.colors or [None])
            )
        lightings.append(_Lighting(channel, targets, tuple(exposures)))

    assert size is not None and reference is not None
    microtime = next(iter(bins))
    # Arrival time sits before z, where mikro has its axes: (t, c, m, z, y, x).
    dims = ("t", "c", *([] if microtime is None else ["m"]), "z", "y", "x")
    shape = (
        plan.times,
        len(channels),
        *([] if microtime is None else [microtime]),
        len(offsets),
        *size,
    )
    return _Merge(
        position=position,
        index=index,
        offsets=offsets,
        sweep=sweep,
        lightings=tuple(lightings),
        channels=tuple(channels),
        data=np.empty(shape, dtype=np.result_type(*types)),
        dims=dims,
        planes=[],
        pixel_to_world=reference,
        calibrated=calibrated,
        light_moves=tuple(values.instrument.sheet_moves()),
        swept=_check_sweep(plan, offsets, lightings, sweep, values),
    )


def _check_memory(arrays: list[np.ndarray]) -> None:
    """The images stay in memory until they are written: refuse what would not fit."""
    needed = sum(array.nbytes for array in arrays)
    available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    if needed > available:
        raise ValueError(
            f"This acquisition takes {needed / 1e9:.1f} GB in memory until it is written, and "
            f"{available / 1e9:.1f} GB are free"
        )


def _to_stage(merge: _Merge) -> tuple[tuple[float, float, float, float], ...]:
    """``z, y, x`` pixel index to stage micrometres: the middle of the image is where the stage was."""
    assert merge.first_z is not None
    height, width = merge.data.shape[-2:]
    middle_x, middle_y = (width - 1) / 2, (height - 1) / 2
    (xx, xy), (yx, yy) = merge.pixel_to_world
    # Moving the light is moving the sample the other way.
    direction = -1.0 if merge.sweep in merge.light_moves else 1.0
    dz = direction * (merge.offsets[1] - merge.offsets[0]) if len(merge.offsets) > 1 else 1.0
    return (
        (float(dz), 0.0, 0.0, float(merge.first_z + direction * merge.offsets[0])),
        (0.0, float(yy), float(yx), float(merge.y - yy * middle_y - yx * middle_x)),
        (0.0, float(xy), float(xx), float(merge.x - xy * middle_y - xx * middle_x)),
    )


def _expose(
    merge: _Merge,
    lighting: _Lighting,
    time_index: int,
    z_index: int,
    store: DatasetStore,
    detector_manager: protocols.DetectorManager,
) -> None:
    """Every detector of a channel takes its image, into the array of the position."""
    for exposure in lighting.exposures:
        _activate(exposure, detector_manager)
        started = datetime.now(timezone.utc)
        images = detector_manager.capture_channels(exposure.detector.name)
        _keep(merge, exposure, images, time_index, z_index, started, store)


def _activate(exposure: _Exposure, detector_manager: protocols.DetectorManager) -> None:
    """Make sure the detector of `exposure` is on."""
    name = exposure.detector.name
    state = detector_manager.get_detector_state(name)
    if state is None or not state.is_active:
        detector_manager.activate_detector(name)


def _keep(
    merge: _Merge,
    exposure: _Exposure,
    images: np.ndarray,
    time_index: int,
    z_index: int,
    started: datetime,
    store: DatasetStore,
) -> None:
    """One exposure's `images` (`capture_channels`), one per channel, into the array, the way round
    all channels are."""
    ended = datetime.now(timezone.utc)
    now = store.state()
    if not exposure.detector.has_axis("c"):
        images = images[np.newaxis]  # one channel: what it delivers is its only image
    for offset, image in enumerate(images):
        if exposure.flip_x:
            image = image[..., ::-1]
        if exposure.flip_y:
            image = image[..., ::-1, :]
        channel = exposure.first_channel + offset
        place: tuple[Any, ...] = (time_index, channel, z_index)
        if "m" in merge.dims:
            place = (time_index, channel, slice(None), z_index)
        merge.data[place] = image
        merge.planes.append(AcquiredPlane(time_index, channel, z_index, started, ended, now))


def _lights_off(values: Values) -> None:
    """Turn off every source that can be, and is on."""
    values.set(
        {
            source.power_variable: 0.0
            for source in values.source_state.sources.values()
            if source.on and source.power_variable is not None
        }
    )


def _sweep_to(merge: _Merge, base: float, offset: float, values: Values, task: Task) -> None:
    if merge.sweep is not None:
        values.set({merge.sweep.name: base + offset}, task=task)


def acquire(
    plan: AcquisitionPlan,
    store: DatasetStore,
    optics_manager: protocols.OpticsManager,
    detector_manager: protocols.DetectorManager,
    values: Values,
    hook_manager: protocols.HookManager,
    task: Task,
) -> list[AcquiredDataset]:
    """Acquire times x positions x planes x channels, into one dataset per position.

    Each time it visits each position, then each plane of the stack, and every channel sets what it
    sets and its detectors take their images; hooks run at the start (`m_hooks`), each time
    (`t_hooks`), at each position (`p_hooks`) and at each plane (`z_hooks`).

    Returns:
        The datasets created, one per position.

    Raises:
        ValueError: What is asked for is no array, or names something this microscope has not.
            Nothing has moved then.
    """
    store.check()
    if not plan.channels or not plan.positions:
        raise ValueError("An acquisition needs a channel and a position")
    if plan.times < 1:
        raise ValueError(f"An acquisition is done at least once, not {plan.times} times")
    offsets = _offsets_of(plan)
    first = next((name for channel in plan.channels for name in channel.detectors), None)
    if first is None:
        raise ValueError(f"The channel {plan.channels[0].name!r} names no detector")
    first = _find_detector(first, detector_manager).name
    sweep = _sweep_of(plan, offsets, first, values)
    merges = [
        _plan_position(
            plan, position, index, offsets, sweep, detector_manager, optics_manager, values
        )
        for index, position in enumerate(plan.positions)
    ]
    _check_memory([merge.data for merge in merges])

    # Every hook must be able to run where it is asked for, before anything moves
    for hooks, level in (
        (plan.m_hooks, "m"),
        (plan.t_hooks, "t"),
        (plan.p_hooks, "p"),
        (plan.z_hooks, "z"),
    ):
        hook_manager.check(hooks or [], level)

    hook_manager.execute_all(plan.m_hooks or [])

    total = sum(merge.data.shape[0] * len(merge.offsets) * len(merge.lightings) for merge in merges)
    done = 0
    task.progress(0, message=f"Starting acquisition: {total} exposures of all detectors")

    started_at = time.monotonic()
    try:
        for time_index in range(plan.times):
            due = started_at + time_index * plan.every_s
            if time.monotonic() < due:
                time.sleep(due - time.monotonic())

            hook_manager.execute_all(plan.t_hooks or [])

            order = list(range(len(plan.positions)))
            if plan.order == PositionOrder.RANDOM:
                random.shuffle(order)

            for position_index in order:
                merge = merges[position_index]
                values.set(merge.position.set_to, task=task)
                # Position hooks run there (an autofocus may refocus); the stacks are centred on where
                # it is afterwards.
                hook_manager.execute_all(plan.p_hooks or [])
                base = 0.0 if merge.sweep is None else float(values[merge.sweep.name])
                if merge.first_z is None:
                    merge.x, merge.y, merge.first_z = where(values, first)

                if merge.swept:
                    # The detector steps what sweeps: the routine only brings it to the first plane.
                    for lighting in merge.lightings:
                        task.pausepoint()
                        _sweep_to(merge, base, merge.offsets[0], values, task)
                        values.set(lighting.targets)
                        exposure = lighting.exposures[0]
                        _activate(exposure, detector_manager)
                        begun = datetime.now(timezone.utc)
                        for z_index, images in enumerate(
                            detector_manager.capture_stack(
                                exposure.detector.name, len(merge.offsets)
                            )
                        ):
                            _keep(merge, exposure, images, time_index, z_index, begun, store)
                            begun = datetime.now(timezone.utc)
                            done += 1
                            task.progress(
                                int(done / total * 90),
                                f"T{time_index + 1}, P{position_index + 1}, Z{z_index + 1}: "
                                f"{lighting.channel.name or 'channel'} ({done}/{total})",
                            )
                    continue

                for z_index, offset in enumerate(merge.offsets):
                    _sweep_to(merge, base, offset, values, task)
                    hook_manager.execute_all(plan.z_hooks or [])

                    for lighting in merge.lightings:
                        task.pausepoint()
                        values.set(lighting.targets)
                        _expose(merge, lighting, time_index, z_index, store, detector_manager)
                        done += 1
                        task.progress(
                            int(done / total * 90),
                            f"T{time_index + 1}, P{position_index + 1}, Z{z_index + 1}: "
                            f"{lighting.channel.name or 'channel'} ({done}/{total})",
                        )
    finally:
        # However it ended: a failure leaves no sample lit for as long as nobody looks.
        _lights_off(values)

    datasets = []
    for merge in merges:
        task.progress(
            90 + int(10 * merge.index / len(merges)), f"Writing position {merge.index + 1}"
        )
        label = merge.position.name or f"P{merge.index + 1}"
        name = plan.name if len(merges) == 1 else f"{plan.name} {label}"
        datasets.append(
            store.publish(
                AcquiredPosition(
                    name=name,
                    position=merge.index,
                    data=merge.data,
                    dims=merge.dims,
                    channels=merge.channels,
                    planes=tuple(merge.planes),
                    to_stage=_to_stage(merge),
                    calibrated=merge.calibrated,
                )
            )
        )
    task.progress(100, message=f"Acquisition complete: {len(datasets)} datasets")
    return datasets
