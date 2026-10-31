"""Routine for performing a multidimensional acquisition: timepoints, positions, z planes, channels.

What it takes is merged rather than saved image by image: every detector of every stream becomes
channels, and each stage position one ``(t, c, z, y, x)`` dataset in the `DatasetStore`, placed in
stage space, with nothing in the local cache. An array is regular, so what cannot be one is refused
before anything moves: a position that wanders between timepoints, uneven z planes, detectors that
disagree on their image size or pixel size.
"""

import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from arkitekt import Task

from newswitch import protocols
from newswitch.models.acquisition import (
    AcquiredDataset,
    MultidimensionalAcquisition,
    Position,
    PositionOrder,
    Stack,
    Streams,
)
from newswitch.models.devices import Detector
from newswitch.models.values import LightSource
from newswitch.protocols.dataset_store import (
    AcquiredChannel,
    AcquiredPlane,
    AcquiredPosition,
    DatasetStore,
)
from newswitch.states.calibration import CalibrationState
from newswitch.services.stage import Stage, stage_of
from newswitch.services.values import Values

logger = logging.getLogger(__name__)

#: How far apart the pixel sizes of two channels may be: one registration maps them all.
SCALE_TOLERANCE = 0.01


@dataclass(frozen=True)
class _Exposure:
    """What one detector contributes to a stream: its channels, from `first_channel` on."""

    detector: Detector
    first_channel: int
    flip_x: bool
    flip_y: bool


@dataclass(frozen=True)
class _Lighting:
    """One stream: which sources it turns on at which intensity, and what it exposes."""

    stream: Streams
    sources: tuple[tuple[LightSource, float], ...]
    exposures: tuple[_Exposure, ...]


@dataclass
class _Merge:
    """What is being acquired at one position, and what it has so far."""

    position: Position
    index: int
    stack: Stack
    offsets: list[float]
    lightings: tuple[_Lighting, ...]
    channels: tuple[AcquiredChannel, ...]
    data: np.ndarray
    planes: list[AcquiredPlane]
    pixel_to_world: np.ndarray  # x, y pixels to x, y micrometres, every axis increasing
    calibrated: bool
    first_z: float | None = None
    swept: bool = False  # its detectors deliver z: each stream sweeps the stack by itself


def _z_step(detector: Detector) -> float | None:
    """How far each image of `detector` steps the stage, if it delivers z by itself."""
    return next((axis.step for axis in detector.axes if axis.name == "z"), None)


def _check_sweep(
    position: Position,
    offsets: list[float],
    lightings: list[_Lighting],
    stage_manager: Stage,
) -> bool:
    """Whether a position's stack is swept, by detectors whose wires step the stage.

    Raises:
        ValueError: What is asked for is not what such a wire can do. Nothing has moved then.
    """
    detectors = [exposure.detector for lighting in lightings for exposure in lighting.exposures]
    steps = {detector.name: _z_step(detector) for detector in detectors}
    if all(step is None for step in steps.values()):
        return False
    if any(step is None for step in steps.values()) or any(
        len(lighting.exposures) > 1 for lighting in lightings
    ):
        raise ValueError(
            f"Detectors that step the stage by themselves take a stack alone, not with others: "
            f"{sorted(steps)}"
        )
    stepped = [(name, step) for name, step in steps.items() if step is not None]
    for name, step in stepped:
        if not np.allclose(np.diff(offsets), step):
            raise ValueError(f"{name} steps the stage by {step} um, not as in {offsets}")
    if position.stacks[0].z_hooks:
        raise ValueError("Nothing can run between the planes of a stack a detector sweeps")
    stage = stage_manager.state
    for offset in offsets:
        if not stage.min_z <= position.z + offset <= stage.max_z:
            raise ValueError(
                f"The plane at {position.z + offset} um is outside the stage's travel "
                f"({stage.min_z} to {stage.max_z} um)"
            )
    return True


def _find_detector(name: str, detector_manager: protocols.DetectorManager) -> Detector:
    """The detector called `name`."""
    available = detector_manager.list_available_detectors()
    for detector in available:
        if name == detector.name:
            return detector
    raise ValueError(f"No detector {name!r}: there are {[d.name for d in available]}")


def _find_source(name: str, values: Values) -> LightSource:
    """The light source called `name`."""
    sources = values.source_state.sources
    if name not in sources:
        raise ValueError(f"No light source {name!r}: there are {sorted(sources)}")
    return sources[name]


def _z_offsets(stack: Stack) -> list[float]:
    """Where a stack's planes are, from the position; evenly spaced, or it is no array."""
    offsets = list(stack.z_slices) if stack.z_slices else [stack.z_offset or 0.0]
    steps = np.diff(offsets)
    if len(steps) and (np.any(steps <= 0) or not np.allclose(steps, steps[0])):
        raise ValueError(f"The planes of a stack must be evenly spaced and rising, not {offsets}")
    return offsets


def _check_regular(config: MultidimensionalAcquisition) -> list[Position]:
    """The positions of an acquisition, which must be the same ones at every timepoint."""
    if not config.timepoints or not config.timepoints[0].positions:
        raise ValueError("An acquisition needs a timepoint with a position")
    first = config.timepoints[0].positions
    for time_index, timepoint in enumerate(config.timepoints):
        if len(timepoint.positions) != len(first):
            raise ValueError(
                f"Timepoint {time_index + 1} has {len(timepoint.positions)} positions, the first "
                f"{len(first)}: a dataset has the same positions at every time"
            )
        for index, (position, expected) in enumerate(zip(timepoint.positions, first)):
            if (position.x, position.y, position.z) != (expected.x, expected.y, expected.z):
                raise ValueError(
                    f"Position {index + 1} moves at timepoint {time_index + 1}: one dataset is "
                    "one place. Make it a position of its own"
                )
            if len(position.stacks) != 1:
                raise ValueError(
                    f"Position {index + 1} has {len(position.stacks)} stacks: a dataset has one"
                )
            stack, kept = position.stacks[0], expected.stacks[0]
            if (stack.z_slices, stack.z_offset, stack.channels) != (
                kept.z_slices,
                kept.z_offset,
                kept.channels,
            ):
                raise ValueError(
                    f"Position {index + 1} changes its stack at timepoint {time_index + 1}"
                )
    return list(first)


def _pixel_to_world(
    detector: Detector,
    optics_manager: protocols.OpticsManager,
    metadata_manager: protocols.MetadataManager,
) -> np.ndarray:
    """What a pixel step of `detector` is on the sample, in x, y micrometres.

    A calibration says how far the stage moves to shift the image by a pixel, the opposite of which
    point of the sample that pixel sees.
    """
    path = optics_manager.get_light_path_for_detector(detector.name)
    matrix = metadata_manager.get_metadata_for_light_path(path).affine_matrix
    return -np.array([[matrix[0][0], matrix[0][1]], [matrix[1][0], matrix[1][1]]], dtype=float)


def _is_calibrated(
    detector: Detector,
    optics_manager: protocols.OpticsManager,
    metadata_manager: protocols.MetadataManager,
    calibration_state: CalibrationState,
) -> bool:
    path = optics_manager.get_light_path_for_detector(detector.name)
    snapshot = metadata_manager.get_metadata_for_light_path(path).light_state
    try:
        calibration_state.get_calibrated_path(light_path_state=snapshot)
    except ValueError:
        return False
    return True


def _channel_label(stream: Streams, detector: Detector, color: str | None) -> str:
    return " ".join(part for part in (stream.mapping, detector.name, color) if part)


def _plan_position(
    position: Position,
    index: int,
    times: int,
    detector_manager: protocols.DetectorManager,
    optics_manager: protocols.OpticsManager,
    metadata_manager: protocols.MetadataManager,
    calibration_state: CalibrationState,
    stage_manager: Stage,
    values: Values,
) -> _Merge:
    """Everything that can be refused about one position, and the array it will fill."""
    stack = position.stacks[0]
    offsets = _z_offsets(stack)
    if not stack.channels:
        raise ValueError(f"Position {index + 1} has nothing to acquire: no streams")

    reference: np.ndarray | None = None
    size: tuple[int, int] | None = None
    bins: set[int | None] = set()
    calibrated = True
    lightings: list[_Lighting] = []
    channels: list[AcquiredChannel] = []
    for stream in stack.channels:
        if not stream.detectors:
            raise ValueError(f"The stream {stream.mapping!r} names no detector")
        sources = tuple(
            (_find_source(light.source, values), light.intensity)
            for light in stream.illuminations or []
        )
        names = tuple(source.name for source, _ in sources)
        exposures: list[_Exposure] = []
        for name in stream.detectors:
            detector = _find_detector(name, detector_manager)
            if size is None:
                size = (detector.height, detector.width)
            elif size != (detector.height, detector.width):
                raise ValueError(
                    f"{detector.name} takes images of {detector.height} x {detector.width}, the "
                    f"others {size[0]} x {size[1]}: they cannot share an array"
                )
            bins.add(next((axis.size for axis in detector.axes if axis.name == "m"), None))
            if len(bins) > 1:
                raise ValueError(
                    f"{detector.name} has {sorted(map(str, bins))} arrival-time bins and others "
                    "have not: they cannot share an array"
                )
            to_world = _pixel_to_world(detector, optics_manager, metadata_manager)
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
            calibrated = calibrated and _is_calibrated(
                detector, optics_manager, metadata_manager, calibration_state
            )
            exposures.append(_Exposure(detector, len(channels), flip_x, flip_y))
            channels.extend(
                AcquiredChannel(
                    label=_channel_label(stream, detector, color),
                    detector=detector.name,
                    sources=names,
                    color=color,
                )
                for color in (detector.colors or [None])
            )
        lightings.append(_Lighting(stream, sources, tuple(exposures)))

    assert size is not None and reference is not None
    microtime = next(iter(bins))
    shape = (times, len(channels), *([] if microtime is None else [microtime]), len(offsets), *size)
    return _Merge(
        position=position,
        index=index,
        stack=stack,
        offsets=offsets,
        lightings=tuple(lightings),
        channels=tuple(channels),
        data=np.empty(shape, dtype=np.uint16),
        planes=[],
        pixel_to_world=reference,
        calibrated=calibrated,
        swept=_check_sweep(position, offsets, lightings, stage_manager),
    )


def _check_memory(shapes: list[tuple[int, ...]]) -> None:
    """The images stay in memory until they are written: refuse what would not fit."""
    needed = sum(int(np.prod(shape)) * np.dtype(np.uint16).itemsize for shape in shapes)
    available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    if needed > available:
        raise ValueError(
            f"This acquisition takes {needed / 1e9:.1f} GB in memory until it is written, and "
            f"{available / 1e9:.1f} GB are free"
        )


def _to_stage(merge: _Merge) -> tuple[tuple[float, float, float, float], ...]:
    """``z, y, x`` pixel index to stage micrometres: the middle of the image is where the stage is."""
    assert merge.first_z is not None
    height, width = merge.data.shape[-2:]
    middle_x, middle_y = (width - 1) / 2, (height - 1) / 2
    (xx, xy), (yx, yy) = merge.pixel_to_world
    dz = merge.offsets[1] - merge.offsets[0] if len(merge.offsets) > 1 else 1.0
    position = merge.position
    return (
        (float(dz), 0.0, 0.0, float(merge.first_z + merge.offsets[0])),
        (0.0, float(yy), float(yx), float(position.y - yy * middle_y - yx * middle_x)),
        (0.0, float(xy), float(xx), float(position.x - xy * middle_y - xx * middle_x)),
    )


def _only_these_on(lighting: _Lighting, values: Values) -> None:
    """Light the stream with its own sources, and nothing else."""
    wanted = {source.name: source.max_power * share for source, share in lighting.sources}
    targets = {}
    for source in values.source_state.sources.values():
        if source.power_variable is None:
            continue
        if source.name in wanted:
            targets[source.power_variable] = wanted[source.name]
        elif source.on:
            targets[source.power_variable] = 0.0
    values.set(targets)


def _expose(
    merge: _Merge,
    lighting: _Lighting,
    time_index: int,
    z_index: int,
    store: DatasetStore,
    detector_manager: protocols.DetectorManager,
) -> None:
    """Every detector of a stream takes its image, into the array of the position."""
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
    """One exposure's `images`, one per channel, into the array, the way round all channels are."""
    ended = datetime.now(timezone.utc)
    now = store.state()
    for offset, image in enumerate(images):
        if exposure.flip_x:
            image = image[..., ::-1]
        if exposure.flip_y:
            image = image[..., ::-1, :]
        channel = exposure.first_channel + offset
        # Arrival time sits before z, where mikro has its axes: (t, c, m, z, y, x).
        place = (time_index, channel, z_index)
        if merge.data.ndim == 6:
            place = (time_index, channel, slice(None), z_index)
        merge.data[place] = image
        merge.planes.append(AcquiredPlane(time_index, channel, z_index, started, ended, now))


def _first_detector(positions: list[Position], detector_manager: protocols.DetectorManager) -> str:
    """Whose view an acquisition moves: the one its first stream names, or else the first that is on."""
    for position in positions:
        for stream in position.stacks[0].channels:
            if stream.detectors:
                return _find_detector(stream.detectors[0], detector_manager).name
    available = detector_manager.list_available_detectors()
    if not available:
        raise ValueError("There is no detector")
    return available[0].name


def acquire_multidimensional_acquisition(
    config: MultidimensionalAcquisition,
    store: DatasetStore,
    optics_manager: protocols.OpticsManager,
    detector_manager: protocols.DetectorManager,
    values: Values,
    calibration_state: CalibrationState,
    metadata_manager: protocols.MetadataManager,
    hook_manager: protocols.HookManager,
    task: Task,
) -> list[AcquiredDataset]:
    """Acquire timepoints x positions x z planes x channels, into one dataset per position.

    Per timepoint the stage visits each position, then each plane of its stack, and every stream
    lights the sample for its detectors; hooks (`m_hooks`, `t_hooks`, `p_hooks`, `z_hooks`) run at
    the start, per timepoint, per position and per plane.

    Returns:
        The datasets created, one per position.

    Raises:
        ValueError: What is asked for is no array, or names something this microscope has not.
            Nothing has moved then.
    """
    store.check()
    positions = _check_regular(config)
    stage_manager = stage_of(values, _first_detector(positions, detector_manager))
    merges = [
        _plan_position(
            position,
            index,
            len(config.timepoints),
            detector_manager,
            optics_manager,
            metadata_manager,
            calibration_state,
            stage_manager,
            values,
        )
        for index, position in enumerate(positions)
    ]
    _check_memory([merge.data.shape for merge in merges])

    # Every hook must be able to run where it is asked for, before anything moves
    hook_manager.check(config.m_hooks or [], "m")
    for timepoint in config.timepoints:
        hook_manager.check(timepoint.t_hooks or [], "t")
        for position in timepoint.positions:
            hook_manager.check(position.p_hooks or [], "p")
            hook_manager.check(position.stacks[0].z_hooks or [], "z")

    hook_manager.execute_all(config.m_hooks or [])

    total = sum(merge.data.shape[0] * len(merge.offsets) * len(merge.lightings) for merge in merges)
    done = 0
    task.progress(0, message=f"Starting acquisition: {total} exposures of all detectors")

    for time_index, timepoint in enumerate(config.timepoints):
        if timepoint.time and timepoint.time > datetime.now():
            time.sleep((timepoint.time - datetime.now()).total_seconds())

        hook_manager.execute_all(timepoint.t_hooks or [])

        order = list(range(len(timepoint.positions)))
        if timepoint.position_order == PositionOrder.RANDOM:
            random.shuffle(order)

        for position_index in order:
            position, merge = timepoint.positions[position_index], merges[position_index]
            stage_manager.move(
                x=position.x, y=position.y, z=position.z, is_absolute=True, task=task
            )
            # Position hooks run there (an autofocus may refocus); the stacks are centred
            # on where the stage is afterwards.
            hook_manager.execute_all(position.p_hooks or [])
            base_z = stage_manager.state.z
            if merge.first_z is None:
                merge.first_z = base_z

            if merge.swept:
                # The detector steps the stage: the routine only brings it to the first plane.
                for lighting in merge.lightings:
                    task.pausepoint()
                    stage_manager.move(
                        x=position.x,
                        y=position.y,
                        z=base_z + merge.offsets[0],
                        is_absolute=True,
                        task=task,
                    )
                    _only_these_on(lighting, values)
                    exposure = lighting.exposures[0]
                    _activate(exposure, detector_manager)
                    started = datetime.now(timezone.utc)
                    for z_index, images in enumerate(
                        detector_manager.capture_stack(exposure.detector.name, len(merge.offsets))
                    ):
                        _keep(merge, exposure, images, time_index, z_index, started, store)
                        started = datetime.now(timezone.utc)
                        done += 1
                        task.progress(
                            int(done / total * 90),
                            f"T{time_index + 1}, P{position_index + 1}, Z{z_index + 1}: "
                            f"{lighting.stream.mapping or 'stream'} ({done}/{total})",
                        )
                continue

            for z_index, offset in enumerate(merge.offsets):
                stage_manager.move(
                    x=position.x, y=position.y, z=base_z + offset, is_absolute=True, task=task
                )
                hook_manager.execute_all(position.stacks[0].z_hooks or [])

                for lighting in merge.lightings:
                    task.pausepoint()
                    _only_these_on(lighting, values)
                    _expose(merge, lighting, time_index, z_index, store, detector_manager)
                    done += 1
                    task.progress(
                        int(done / total * 90),
                        f"T{time_index + 1}, P{position_index + 1}, Z{z_index + 1}: "
                        f"{lighting.stream.mapping or 'stream'} ({done}/{total})",
                    )

    values.set(
        {
            source.power_variable: 0.0
            for source in values.source_state.sources.values()
            if source.on and source.power_variable is not None
        }
    )

    datasets = []
    for merge in merges:
        task.progress(
            90 + int(10 * merge.index / len(merges)), f"Writing position {merge.index + 1}"
        )
        name = config.file_name if len(merges) == 1 else f"{config.file_name} P{merge.index + 1}"
        datasets.append(
            store.publish(
                AcquiredPosition(
                    name=name,
                    position=merge.index,
                    data=merge.data,
                    channels=merge.channels,
                    planes=tuple(merge.planes),
                    to_stage=_to_stage(merge),
                    calibrated=merge.calibrated,
                )
            )
        )
    task.progress(100, message=f"Acquisition complete: {len(datasets)} datasets")
    return datasets
