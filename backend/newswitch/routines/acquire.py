"""Performing an acquisition: every channel, on every plane, at every position, every time.

What it takes is kept rather than saved image by image: each detector, at each position, makes one
record in the `DatasetStore`, along its own axes (`Detector.axes`), with nothing in the local cache.
Its axes are ``t``, ``c`` (the channels that name it, each of its colors), what else it delivers
but space (``m``, when a photon arrived), the plane ``z``, and its space (``y``, ``x``); a
thermometer, which measures at a point, has ``(t, c, plane, z, y, x)``, one position along each of
``z, y, x``. Each record is placed on the sample by
its own detector's route through the coordinate graph (`SpaceManager.record_map`), as a BY_DIMENSION
that names only what has a place. A thermometer is placed as mikro places what has no extent: its
``z, y, x`` have one position each, at its point; the plane it was read at is an index of its own.

A plan is regular by what it is, so what is left to refuse, before anything moves, is what cannot
be one record: uneven planes, or a detector whose image size or placement changes between the
channels that name it.
"""

import logging
import os
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
from arkitekt import Task

from newswitch import protocols
from newswitch.instrument.space import AxisMap, to_parts, zyx_rows
from newswitch.instrument.spec import Move
from newswitch.models.acquisition import (
    AcquiredDataset,
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    PositionOrder,
)
from newswitch.models.devices import Detector
from newswitch.models.space import Axis
from newswitch.protocols.dataset_store import (
    AcquiredChannel,
    AcquiredPlane,
    AcquiredRecord,
    DatasetStore,
)
from newswitch.services.space import AXIS_TYPES, SpaceManager
from newswitch.services.values import Values

logger = logging.getLogger(__name__)

#: How far apart one detector's pixel sizes may be between its channels: one record, one map. A
#: filter in the way alone changes it by a hundredth of a percent; another objective, by far more.
PLACEMENT_TOLERANCE = 0.01


@dataclass(frozen=True)
class _Exposure:
    """What one detector contributes to a channel: its record's channels, from `first_channel` on."""

    detector: Detector
    first_channel: int


@dataclass(frozen=True)
class _Lighting:
    """One channel of the plan: what to set for it, and what it exposes."""

    channel: AcquisitionChannel
    targets: Mapping[str, float]
    exposures: tuple[_Exposure, ...]


@dataclass
class _Record:
    """What one detector acquires at one position, and what it has so far."""

    detector: Detector
    channels: list[AcquiredChannel] = field(default_factory=list)
    axes: tuple[Axis, ...] = ()
    data: np.ndarray | None = None
    planes: list[AcquiredPlane] = field(default_factory=list)
    calibrated: bool = True
    shape: tuple[int, int] | None = None  # its image, the same under every channel
    scale: np.ndarray | None = None  # its pixels on the sample, the same under every channel
    sample: str = ""  # the sample its detector sees
    sets: Mapping[str, float] = field(default_factory=dict)  # what its first channel sets
    placed: AxisMap | None = None  # its axes on the sample, once there

    @property
    def dims(self) -> tuple[str, ...]:
        return tuple(axis.name for axis in self.axes)


@dataclass
class _Merge:
    """What is being acquired at one position, and what it has so far."""

    position: AcquisitionPosition
    index: int
    offsets: list[float]
    sweeps: dict[str, Move | None]  # what sweeps each sample's stack, by sample
    lightings: tuple[_Lighting, ...]
    records: dict[str, _Record]  # by detector, in the order the plan first names them
    swept: bool
    targets: dict[str, float]  # what to set to get there: its places, then what it sets
    light_sweeps: frozenset[str] = frozenset()  # the samples whose sweep moves the light


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
    plan: AcquisitionPlan,
    offsets: list[float],
    detector: str | None,
    values: Values,
    sample: str,
    alone: bool = True,
) -> Move | None:
    """What sweeps `sample`'s stack: none for one plane where it is, unless one is named.

    What a detector's own wire steps, or what is named among what moves through the sample or
    focuses; otherwise the one thing that does either. Without a detector that takes images,
    nothing focuses: it is named, or refused, when the sample is `alone` in the plan; beside others,
    what measures at a point is read at each of their planes where it is.
    """
    named = plan.stack.variable
    if named is None and offsets == [0.0]:
        return None
    instrument = values.instrument
    if detector is None:
        if not alone:
            return None
        variable = instrument.variables.get(named or "")
        if not isinstance(variable, Move):
            raise ValueError(
                "Nothing in this plan takes images, so nothing says what a stack sweeps: name "
                "what moves (stack.variable)"
            )
        return variable
    wired = instrument.z_drive(detector)
    if wired is not None and named in (None, wired.target):
        return instrument.variables[wired.target]
    through = instrument.sample_moves(sample)
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
    unit = f"({detector.unit})" if detector.unit else None
    return " ".join(part for part in (channel.name, detector.name, color, unit) if part)


#: Along which axis a record of a detector that measures at a point has the planes of the stack:
#: they are where it was read, not where it is.
PLANE = "plane"


def _axes_of(detector: Detector) -> tuple[Axis, ...]:
    """A record's axes: time, its channels, what it delivers but space, the plane, its space.

    A detector that measures at a point is, as mikro has a dataset of no extent, one position along
    each of ``z, y, x``, at its point; the plane it was read at is an index of its own (`PLANE`).
    """
    if not detector.delivers_images():
        return (
            Axis("t", "TIME"),
            Axis("c", "CHANNEL"),
            Axis(PLANE, "INDEX"),
            *(Axis(name, "SPACE") for name in ("z", "y", "x")),
        )
    own = [axis for axis in detector.axes if axis.name not in ("c", "z")]
    return (
        Axis("t", "TIME"),
        Axis("c", "CHANNEL"),
        *(Axis(a.name, AXIS_TYPES[a.domain]) for a in own if a.domain != "space"),
        Axis("z", "SPACE"),
        *(Axis(a.name, "SPACE") for a in own if a.domain == "space"),
    )


def _check_alike(record: _Record, shape: tuple[int, int], scale: np.ndarray, name: str) -> None:
    """One detector is one record: the same image size and placement under every channel.

    Raises:
        ValueError: Its channels set it differently (a binning, an objective of their own).
    """
    if record.shape is None or record.scale is None:
        record.shape, record.scale = shape, scale
        return
    if shape != record.shape:
        raise ValueError(
            f"{name} takes images of {shape[0]} x {shape[1]} in one channel and "
            f"{record.shape[0]} x {record.shape[1]} in another: one record has one size"
        )
    if not np.allclose(scale, record.scale, rtol=PLACEMENT_TOLERANCE, atol=1e-9):
        raise ValueError(
            f"{name} has pixels of {scale.tolist()} um in one channel and "
            f"{record.scale.tolist()} um in another: one record has one placement"
        )


def _plan_position(
    plan: AcquisitionPlan,
    position: AcquisitionPosition,
    index: int,
    offsets: list[float],
    sweeps: dict[str, Move | None],
    detector_manager: protocols.DetectorManager,
    optics_manager: protocols.OpticsManager,
    values: Values,
    space: SpaceManager,
    firsts: dict[str, str | None],
) -> _Merge:
    """Everything that can be refused about one position, and the records it will fill."""
    going = {**_going(position, firsts, space), **position.set_to}
    values.check(going)
    at = {**values.snapshot(), **values.resolved(going)}
    for sweep in sweeps.values():
        if sweep is not None:
            values.check({sweep.name: at[sweep.name] + offset for offset in offsets})

    records: dict[str, _Record] = {}
    lightings: list[_Lighting] = []
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
            record = records.setdefault(
                name,
                _Record(detector, sample=space.sample_of(name), sets=values.resolved(targets)),
            )
            images = detector.delivers_images()
            if images:
                scale, measured = optics_manager.scale_under(name, under)
                _check_alike(
                    record,
                    detector_manager.plane_under(name, under.get(f"{name}.binning")),
                    np.array(scale.affine_matrix, dtype=float),
                    name,
                )
                record.calibrated = record.calibrated and measured
            else:
                record.calibrated = False  # where it reads is described, never measured
            exposures.append(_Exposure(detector, len(record.channels)))
            record.channels.extend(
                AcquiredChannel(
                    label=_channel_label(channel, detector, color),
                    detector=detector.name,
                    sources=names if images else (),
                    color=color,
                    light=images,
                )
                for color in (detector.colors or [None])
            )
        lightings.append(_Lighting(channel, targets, tuple(exposures)))

    for record in records.values():
        detector = record.detector
        microtime = next((axis.size for axis in detector.axes if axis.name == "m"), None)
        record.axes = _axes_of(detector)
        sizes = {"t": plan.times, "c": len(record.channels), "z": len(offsets), "m": microtime}
        if record.shape is not None:
            sizes["y"], sizes["x"] = record.shape
        else:  # at a point: read at every plane, there at one place
            sizes.update({PLANE: len(offsets), "z": 1, "y": 1, "x": 1})
        record.data = np.empty(
            tuple(int(sizes[name] or 0) for name in record.dims), dtype=detector.data_type
        )
    (only,) = list(sweeps.values()) if len(sweeps) == 1 else [None]
    return _Merge(
        position=position,
        index=index,
        offsets=offsets,
        sweeps=sweeps,
        lightings=tuple(lightings),
        records=records,
        targets=going,
        light_sweeps=frozenset(
            sample
            for sample, sweep in sweeps.items()
            if sweep is not None and sweep in values.instrument.sheet_moves(sample)
        ),
        swept=_check_sweep(plan, offsets, lightings, only, values),
    )


def _going(
    position: AcquisitionPosition, firsts: dict[str, str | None], space: SpaceManager
) -> dict[str, float]:
    """What brings each sample's image to where `position` is: a place on "the sample" is that
    place on each sample, by its own stage; a place on one sample is only that one's.

    Raises:
        ValueError: Nothing that takes images looks at the samples it names.
    """
    if position.at is None:
        return {}
    on = space.sample_of_system(position.at.system)
    looking = {
        sample: first
        for sample, first in firsts.items()
        if first is not None and (on is None or on == sample)
    }
    if not looking:
        raise ValueError(
            "Nothing in this plan takes images of "
            + (f"the sample {on}" if on is not None else "any sample")
            + ", so no image's middle can be brought to a place: give its positions by what to "
            "set (set_to)"
        )
    return {
        name: value
        for first in looking.values()
        for name, value in space.targets(position.at, first).items()
    }


def _check_memory(arrays: list[np.ndarray]) -> None:
    """The images stay in memory until they are written: refuse what would not fit."""
    needed = sum(array.nbytes for array in arrays)
    available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    if needed > available:
        raise ValueError(
            f"This acquisition takes {needed / 1e9:.1f} GB in memory until it is written, and "
            f"{available / 1e9:.1f} GB are free"
        )


def _place(merge: _Merge, space: SpaceManager, values: Values) -> None:
    """Where every record's axes go on its sample: once at each position, where it is now (after
    its hooks), under what the record's channels set (one binning, one objective for all)."""
    now = values.snapshot()
    for name, record in merge.records.items():
        if record.placed is None:
            record.placed = space.record_map(
                name,
                record.dims,
                merge.offsets,
                record.sample in merge.light_sweeps,
                {**now, **record.sets},
            )


def _expose(
    merge: _Merge,
    lighting: _Lighting,
    time_index: int,
    z_index: int,
    store: DatasetStore,
    detector_manager: protocols.DetectorManager,
) -> None:
    """Every detector of a channel takes what it takes, into its record at the position."""
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
    """One exposure (`capture_channels`: one per color, along what the detector delivers), into its
    detector's record, as it was delivered."""
    ended = datetime.now(timezone.utc)
    now = store.state()
    record = merge.records[exposure.detector.name]
    assert record.data is not None
    if not exposure.detector.has_axis("c"):
        images = images[np.newaxis]  # one color: what it delivers is its only one
    for offset, image in enumerate(images):
        channel = exposure.first_channel + offset
        stack = PLANE if PLANE in record.dims else "z"
        at = {"t": time_index, "c": channel, stack: z_index}
        place: tuple[Any, ...] = tuple(at.get(name, slice(None)) for name in record.dims)
        record.data[place] = image
        record.planes.append(AcquiredPlane(time_index, channel, z_index, started, ended, now))


def _lights_off(values: Values) -> None:
    """Turn off every source that can be, and is on."""
    values.set(
        {
            source.power_variable: 0.0
            for source in values.source_state.sources.values()
            if source.on and source.power_variable is not None
        }
    )


def _sweep_to(
    merge: _Merge, bases: Mapping[str, float], offset: float, values: Values, task: Task
) -> None:
    """Every sample's stack to its plane `offset` from where it was: each by what sweeps it."""
    planes = {
        sweep.name: bases[sweep.name] + offset
        for sweep in merge.sweeps.values()
        if sweep is not None
    }
    if planes:
        values.set(planes, task=task)


def acquire(
    plan: AcquisitionPlan,
    store: DatasetStore,
    optics_manager: protocols.OpticsManager,
    detector_manager: protocols.DetectorManager,
    values: Values,
    space: SpaceManager,
    hook_manager: protocols.HookManager,
    task: Task,
) -> list[AcquiredDataset]:
    """Acquire times x positions x planes x channels, into a record per position and detector.

    Each time it visits each position, then each plane of the stack, and every channel sets what it
    sets and its detectors take their images; hooks run at the start (`m_hooks`), each time
    (`t_hooks`), at each position (`p_hooks`) and at each plane (`z_hooks`).

    Returns:
        The datasets created: for each position, one per detector, in the order the plan names
        them.

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
    named = list(dict.fromkeys(name for channel in plan.channels for name in channel.detectors))
    if not named:
        raise ValueError(f"The channel {plan.channels[0].name!r} names no detector")
    # Each sample the plan sees, and on each what looks: whose image's middle goes to a place,
    # and whose focus sweeps the sample's stack.
    for name in named:
        _find_detector(name, detector_manager)
    samples = list(dict.fromkeys(space.sample_of(name) for name in named))
    if plan.stack.variable is not None and len(samples) > 1:
        raise ValueError(
            f"This plan sees the samples {samples}, and {plan.stack.variable} would sweep one of "
            "them: leave stack.variable out, and each sweeps what focuses it"
        )
    firsts = {
        sample: next(
            (
                name
                for name in named
                if space.sample_of(name) == sample
                and _find_detector(name, detector_manager).delivers_images()
            ),
            None,
        )
        for sample in samples
    }
    sweeps = {
        sample: _sweep_of(plan, offsets, firsts[sample], values, sample, len(samples) == 1)
        for sample in samples
    }
    merges = [
        _plan_position(
            plan,
            position,
            index,
            offsets,
            sweeps,
            detector_manager,
            optics_manager,
            values,
            space,
            firsts,
        )
        for index, position in enumerate(plan.positions)
    ]
    _check_memory(
        [
            record.data
            for merge in merges
            for record in merge.records.values()
            if record.data is not None
        ]
    )

    # Every hook must be able to run where it is asked for, before anything moves
    for hooks, level in (
        (plan.m_hooks, "m"),
        (plan.t_hooks, "t"),
        (plan.p_hooks, "p"),
        (plan.z_hooks, "z"),
    ):
        hook_manager.check(hooks or [], level)

    hook_manager.execute_all(plan.m_hooks or [])

    total = sum(plan.times * len(merge.offsets) * len(merge.lightings) for merge in merges)
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
                values.set(merge.targets, task=task)
                # Position hooks run there (an autofocus may refocus); the stacks are centred on where
                # it is afterwards.
                hook_manager.execute_all(plan.p_hooks or [])
                bases = {
                    sweep.name: float(values[sweep.name])
                    for sweep in merge.sweeps.values()
                    if sweep is not None
                }
                _place(merge, space, values)

                if merge.swept:
                    # The detector steps what sweeps: the routine only brings it to the first plane.
                    for lighting in merge.lightings:
                        task.pausepoint()
                        _sweep_to(merge, bases, merge.offsets[0], values, task)
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
                    _sweep_to(merge, bases, offset, values, task)
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
        for detector, record in merge.records.items():
            assert record.data is not None and record.placed is not None
            parts = [plan.name, *([] if len(merges) == 1 else [label]), detector]
            datasets.append(
                store.publish(
                    AcquiredRecord(
                        name=" ".join(part for part in parts if part),
                        position=merge.index,
                        detector=detector,
                        data=record.data,
                        axes=record.axes,
                        channels=tuple(record.channels),
                        planes=tuple(record.planes),
                        registration=tuple(to_parts(record.placed)),
                        calibrated=record.calibrated,
                        quantity=record.detector.quantity,
                        unit=record.detector.unit,
                        sample=record.sample,
                        mount_id=space.state.samples[record.sample].mount_id,
                        mount=zyx_rows(space.mount(record.sample)),
                    )
                )
            )
    task.progress(100, message=f"Acquisition complete: {len(datasets)} datasets")
    return datasets
