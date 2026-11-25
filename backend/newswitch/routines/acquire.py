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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np
from arkitekt import Task

from newswitch import protocols
from newswitch.instrument.space import AxisMap, affine_part, to_parts, zyx_rows
from newswitch.instrument.spec import Dark, Move
from newswitch.models.acquisition import (
    AcquiredDataset,
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    PositionOrder,
)
from newswitch.models.devices import Detector
from newswitch.models.space import Axis, DimensionPart
from newswitch.protocols.dataset_store import (
    AcquiredChannel,
    AcquiredPlane,
    AcquiredRecord,
    DatasetStore,
    FrameMemory,
    RecordStream,
    StreamingDatasetStore,
)
from newswitch.routines.pace import Timing, Writes
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
    record: str  # the record it goes into, by its key in `_Merge.records`


@dataclass(frozen=True)
class _Lighting:
    """One channel of the plan: what to set for it, and what it exposes."""

    channel: AcquisitionChannel
    targets: Mapping[str, float]
    exposures: tuple[_Exposure, ...]


@dataclass(frozen=True)
class _Cadence:
    """When a channel is taken, on the acquisition's clock: `times` times, `every_s` apart, the
    first `start_s` after it starts."""

    start_s: float
    every_s: float
    times: int


def _cadence_of(channel: AcquisitionChannel, plan: AcquisitionPlan) -> _Cadence:
    """When `channel` is taken: as it says, else as the plan does.

    Raises:
        ValueError: Never, or before the start, or less than no time apart.
    """
    cadence = _Cadence(
        start_s=channel.start_s,
        every_s=plan.every_s if channel.every_s is None else channel.every_s,
        times=plan.times if channel.times is None else channel.times,
    )
    if cadence.times < 1 or cadence.start_s < 0 or cadence.every_s < 0:
        raise ValueError(
            f"The channel {channel.name or channel.detectors[0]!r} is taken {cadence.times} times, "
            f"every {cadence.every_s} s from {cadence.start_s} s: at least once, from 0 s on"
        )
    return cadence


def _events(cadences: list[_Cadence]) -> list[tuple[float, dict[int, int]]]:
    """When each channel is due, on the acquisition's clock: each a time and the channels due then,
    with which of their times it is. Channels due at once are taken in one visit; one channel twice
    at once (no time between) is two visits, one after the other."""
    due = sorted(
        (cadence.start_s + k * cadence.every_s, k, index)
        for index, cadence in enumerate(cadences)
        for k in range(cadence.times)
    )
    events: list[tuple[float, dict[int, int]]] = []
    for at, k, index in due:
        if events and abs(events[-1][0] - at) < 1e-9 and index not in events[-1][1]:
            events[-1][1][index] = k
        else:
            events.append((at, {index: k}))
    return events


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
    cadence: _Cadence | None = None  # when it is taken: as all its channels are
    stream: RecordStream | None = None  # where its exposures go as they come, instead of `data`
    streamed: tuple[tuple[int, ...], str] = ((), "")  # its shape and type, when streamed

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
    records: dict[str, _Record]  # by `_record_key`, in the order the plan first names them
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
    if values.roles.focuses(detector, sample):
        return values.roles.focus(detector, named, sample)
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

    A probe is read at every plane, which it does not move with: the plane is an index of its own
    (`PLANE`). One at a point is, as mikro has a dataset of no extent, one position along each of
    ``z, y, x``, at its point; one on a grid has its places along ``y, x``, and samples in time
    along ``s`` if it samples time.
    """
    if not detector.delivers_images():
        own = [axis for axis in detector.axes if axis.domain != "space"]
        return (
            Axis("t", "TIME"),
            Axis("c", "CHANNEL"),
            *(Axis(a.name, AXIS_TYPES[a.domain]) for a in own),
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


@dataclass(frozen=True)
class _Look:
    """A detector of a channel: the sample it sees under what that channel sets, and that."""

    channel: int
    detector: str
    sample: str
    under: Mapping[str, Any]


def _looks_of(
    plan: AcquisitionPlan,
    values: Values,
    space: SpaceManager,
    detector_manager: protocols.DetectorManager,
) -> list[_Look]:
    """What every detector of every channel sees, the switches set as that channel sets them.

    Raises:
        ValueError: A channel names no detector, or one that is no detector.
        Dark: A channel sets the switches so that no light gets to one of its detectors.
    """
    now = values.snapshot()
    looks = []
    for index, channel in enumerate(plan.channels):
        if not channel.detectors:
            raise ValueError(f"The channel {channel.name!r} names no detector")
        under = {**now, **values.resolved(channel.set_to)}
        for name in channel.detectors:
            _find_detector(name, detector_manager)
            if not space.sees(name, under):
                assert space.instrument is not None
                if space.instrument.sample_of(name, under) is None:
                    raise space.instrument.dark(name, under)
                raise Dark(f"{name} reads a grid that what its sample is mounted on has not")
            looks.append(_Look(index, name, space.sample_of(name, under), under))
    return looks


def _record_key(look: _Look, split: frozenset[str]) -> str:
    """Which record a look goes into: its detector's, or, where the switches show the detector
    several samples in this plan, its detector's of that sample."""
    return f"{look.detector}-{look.sample}" if look.detector in split else look.detector


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
    firsts: dict[str, _Look | None],
    looks: list[_Look],
    cadences: list[_Cadence],
) -> _Merge:
    """Everything that can be refused about one position, and the records it will fill."""
    going = {**_going(position, firsts, space), **position.set_to}
    values.check(going)
    at = {**values.snapshot(), **values.resolved(going)}
    for sweep in sweeps.values():
        if sweep is not None:
            values.check({sweep.name: at[sweep.name] + offset for offset in offsets})

    seen: dict[str, set[str]] = {}
    for look in looks:
        seen.setdefault(look.detector, set()).add(look.sample)
    split = frozenset(name for name, samples in seen.items() if len(samples) > 1)
    records: dict[str, _Record] = {}
    lightings: list[_Lighting] = []
    for channel_index, channel in enumerate(plan.channels):
        targets = _lights_of(channel, values)
        values.check(targets)
        under = {**at, **targets}
        names = _sources_of(targets, values)
        exposures: list[_Exposure] = []
        for look in (look for look in looks if look.channel == channel_index):
            name = look.detector
            detector = _find_detector(name, detector_manager)
            key = _record_key(look, split)
            record = records.setdefault(
                key,
                _Record(
                    detector,
                    sample=look.sample,
                    sets=values.resolved(targets),
                    cadence=cadences[channel_index],
                ),
            )
            if record.cadence != cadences[channel_index]:
                raise ValueError(
                    f"{name} is taken at other times in one channel than in another: one record "
                    "has one time axis, so give each its own detector, or the same times"
                )
            images = detector.delivers_images()
            if images:
                scale, measured = optics_manager.scale_under(name, under)
                _check_alike(
                    record,
                    detector_manager.plane_under(name, under.get(f"{name}.binning")),
                    np.array(scale.affine_matrix, dtype=float),
                    key,
                )
                record.calibrated = record.calibrated and measured
            else:
                record.calibrated = False  # where it reads is described, never measured
            exposures.append(_Exposure(detector, len(record.channels), key))
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
        record.axes = _axes_of(detector)
        sizes = {
            "t": record.cadence.times if record.cadence is not None else plan.times,
            "c": len(record.channels),
            "z": len(offsets),
            **{a.name: a.delivered() for a in detector.axes if a.name not in ("c", "z", "y", "x")},
        }
        if record.shape is not None:
            sizes["y"], sizes["x"] = record.shape
        else:  # a probe: read at every plane, there at its places or its point
            sizes.update(
                {
                    PLANE: len(offsets),
                    "z": 1,
                    **{
                        a: detector.axis(a).delivered() if detector.has_axis(a) else 1 for a in "yx"
                    },
                }
            )
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
    position: AcquisitionPosition, firsts: dict[str, _Look | None], space: SpaceManager
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
        for name, value in space.targets(position.at, first.detector, first.under).items()
    }


def _position_hooks(
    plan: AcquisitionPlan,
    merge: _Merge,
    firsts: dict[str, _Look | None],
    values: Values,
    hook_manager: protocols.HookManager,
) -> None:
    """Run the position hooks: once, as things are; or, where the channels set the switches so that
    the samples are seen one after the other, once under each sample's first channel, so that a
    refocus sees, and lights, what it refocuses."""
    hooks = plan.p_hooks or []
    if not hooks:
        return
    swaps = [v.name for v in values.instrument.variables.values() if v.verb == "swaps"]
    looks = [look for look in firsts.values() if look is not None]
    if len({tuple(look.under[name] for name in swaps) for look in looks}) <= 1:
        hook_manager.execute_all(hooks)
        return
    for look in looks:
        values.set(merge.lightings[look.channel].targets)
        hook_manager.execute_all(hooks)


@dataclass
class _Stream:
    """A probe recording without pause through the acquisition, and the blocks it has read."""

    channel: AcquisitionChannel
    detector: Detector
    sample: str
    blocks: list[np.ndarray] = field(default_factory=list)
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _streams_of(
    channels: list[AcquisitionChannel],
    detector_manager: protocols.DetectorManager,
    space: SpaceManager,
    values: Values,
) -> list[_Stream]:
    """What the streamed channels record: each detector of each.

    Raises:
        ValueError: One samples no time of its own, so has nothing to stream.
        Dark: One reads a grid that what its sample is mounted on has not.
    """
    found = []
    for channel in channels:
        if not channel.detectors:
            raise ValueError(f"The channel {channel.name!r} names no detector")
        for name in channel.detectors:
            detector = _find_detector(name, detector_manager)
            if not (detector.is_probe() and detector.has_axis("s")):
                raise ValueError(
                    f"{name} samples no time of its own, so it has nothing to stream: take it when "
                    "it is due instead (stream: false)"
                )
            if not space.sees(name, values.snapshot()):
                raise Dark(f"{name} reads a grid that what its sample is mounted on has not")
            found.append(_Stream(channel, detector, space.sample_of(name)))
    return found


def _since(mounted_at: str, then: datetime) -> float:
    """How many seconds after a sample's mounting `then` is: where on its clock."""
    return 0.0 if not mounted_at else (then - datetime.fromisoformat(mounted_at)).total_seconds()


def _time_part(detector: Detector, step_s: float, offset_s: float) -> DimensionPart:
    """A record's ``t`` onto its sample's clock, in seconds: `offset_s` and then `step_s` a time;
    with its detector's own samples in time (``s``), each a sample further."""
    if detector.has_axis("s"):
        sample_s = (detector.axis("s").step or 0.0) / 1000.0
        return affine_part(("t", "s"), ("t",), [[step_s, sample_s, offset_s]])
    return affine_part(("t",), ("t",), [[step_s, offset_s]])


def _stream_record(
    plan: AcquisitionPlan, stream: _Stream, space: SpaceManager, store: DatasetStore
) -> AcquiredRecord | None:
    """What a stream recorded, as a record of its own: no position, since what it reads stays
    under the sample wherever the stage goes; its blocks one after another along ``t``, each its
    samples along ``s``. None when not one whole block was recorded."""
    if not stream.blocks:
        return None
    detector = stream.detector
    block_s = detector.axis("s").size * (detector.axis("s").step or 0.0) / 1000.0  # type: ignore[operator]
    rows, columns = (
        (detector.axis("y").delivered() or 1, detector.axis("x").delivered() or 1)
        if detector.has_axis("x")
        else (1, 1)
    )
    blocks = np.stack(stream.blocks)
    data = blocks.reshape(len(stream.blocks), 1, blocks.shape[1], 1, rows, columns)
    axes = (
        Axis("t", "TIME"),
        Axis("c", "CHANNEL"),
        Axis("s", AXIS_TYPES["time"]),
        *(Axis(name, "SPACE") for name in ("z", "y", "x")),
    )
    dims = tuple(axis.name for axis in axes)
    placed = space.record_map(detector.name, dims, [0.0], False)
    sample = space.state.samples[stream.sample]
    state = store.state()
    started = stream.started
    return AcquiredRecord(
        name=" ".join(part for part in (plan.name, detector.name) if part),
        position=0,
        detector=detector.name,
        data=data.astype(detector.data_type),
        axes=axes,
        channels=(
            AcquiredChannel(
                label=_channel_label(stream.channel, detector, None),
                detector=detector.name,
                sources=(),
                color=None,
                light=False,
            ),
        ),
        planes=tuple(
            AcquiredPlane(
                k,
                0,
                0,
                started + timedelta(seconds=k * block_s),
                started + timedelta(seconds=(k + 1) * block_s),
                state,
            )
            for k in range(len(stream.blocks))
        ),
        registration=(
            *to_parts(placed),
            _time_part(detector, block_s, _since(sample.mounted_at, started)),
        ),
        calibrated=False,
        quantity=detector.quantity,
        unit=detector.unit,
        sample=stream.sample,
        mount_id=sample.mount_id,
        mounted_at=sample.mounted_at,
        mount=zyx_rows(space.mount(stream.sample)),
        pyramid=plan.pyramid,
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


def _place(merge: _Merge, space: SpaceManager, values: Values) -> None:
    """Where every record's axes go on its sample: once at each position, where it is now (after
    its hooks), under what the record's channels set (one binning, one objective for all)."""
    now = values.snapshot()
    for record in merge.records.values():
        if record.placed is None:
            record.placed = space.record_map(
                record.detector.name,
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
    timing: Timing | None = None,
    writes: Writes | None = None,
) -> None:
    """Every detector of a channel takes what it takes, into its record at the position."""
    timing = timing or Timing()
    for exposure in lighting.exposures:
        _activate(exposure, detector_manager)
        started = datetime.now(timezone.utc)
        name = exposure.detector.name
        if merge.records[exposure.record].stream is not None:
            capture = getattr(detector_manager, "capture_frame", None)
            frame_of = (
                (lambda: capture(name))
                if capture is not None
                else (lambda: FrameMemory.of_array(detector_manager.capture_channels(name)))
            )
            _stream_in(
                merge, exposure, frame_of, time_index, z_index, started, store, timing, writes
            )
            continue
        with timing("camera"):
            images = detector_manager.capture_channels(name)
        with timing("write"):
            _keep(merge, exposure, images, time_index, z_index, started, store)


#: How often an exposure is taken again when the camera reused its slot while it was copied.
STREAM_ATTEMPTS = 3
#: The axes of a record that is streamed: a camera's.
STREAMED_DIMS = ("t", "c", "z", "y", "x")


def _streamable(record: _Record, store: DatasetStore) -> bool:
    """Whether `record` goes to `store` exposure by exposure: a camera's, into a store that takes
    them so (`StreamingDatasetStore`)."""
    return (
        isinstance(store, StreamingDatasetStore)
        and bool(getattr(store, "streams", True))
        and record.dims == STREAMED_DIMS
        and record.data is not None
    )


def _open_streams(
    merges: list[_Merge], store: DatasetStore, pyramid: bool = False
) -> list[RecordStream]:
    """A stream for every record that goes so, its array never made (`data` was planned only:
    `np.empty` holds no memory until written); building its coarser levels too when `pyramid`."""
    opened = []
    for merge in merges:
        for record in merge.records.values():
            if not _streamable(record, store):
                continue
            assert record.data is not None
            shape, dtype = tuple(int(n) for n in record.data.shape), str(record.data.dtype)
            record.stream = store.stream(  # type: ignore[attr-defined]
                shape, dtype, record.dims, len(record.detector.colors) or 1, pyramid=pyramid
            )
            record.streamed = (shape, dtype)
            record.data = None
            opened.append(record.stream)
    return opened


def _stream_in(
    merge: _Merge,
    exposure: _Exposure,
    frame_of: Callable[[], FrameMemory],
    time_index: int,
    z_index: int,
    started: datetime,
    store: DatasetStore,
    timing: Timing | None = None,
    writes: Writes | None = None,
) -> None:
    """One exposure into its record's stream, from where it is: taken again if the camera reused
    its slot while it was copied. One that stays where it is until the next is asked for (a
    triggered camera's) is copied by `writes` while the acquisition goes on."""
    timing = timing or Timing()
    record = merge.records[exposure.record]
    assert record.stream is not None
    for attempt in range(STREAM_ATTEMPTS):
        with timing("camera"):
            frame = frame_of()
        if frame.held and writes is not None:
            with timing("write"):
                writes.later(record.stream, time_index, exposure.first_channel, z_index, frame)
            break
        with timing("write"):
            record.stream.write(time_index, exposure.first_channel, z_index, frame)
        if frame.valid():
            break
        logger.warning(
            "%s: the camera reused the slot while it was copied, taken again (%d)",
            exposure.detector.name,
            attempt + 1,
        )
    else:
        raise RuntimeError(f"{exposure.detector.name}: no exposure held still long enough to copy")
    ended = datetime.now(timezone.utc)
    with timing("bookkeeping"):
        now = store.state()
        for offset in range(len(exposure.detector.colors) or 1):
            record.planes.append(
                AcquiredPlane(
                    time_index, exposure.first_channel + offset, z_index, started, ended, now
                )
            )


def _light(targets: Mapping[str, Any], lit: dict[str, Any], values: Values) -> None:
    """Set the lights to `targets`, sending only what differs from what they were last set to
    here (`lit`): each is a write on the bus, and most exposures light as the last did."""
    changed = {name: value for name, value in targets.items() if name not in lit or lit[name] != value}
    if changed:
        values.set(changed)
        lit.update(changed)


def _trigger(named: list[str], detector_manager: protocols.DetectorManager) -> list[str]:
    """The detectors that expose each frame only when it is captured, for the whole acquisition
    (`begin_triggered`): never one exposed before it was asked for, while the stage still moved
    or the light changed, and no camera started for each."""
    begin = getattr(detector_manager, "begin_triggered", None)
    if begin is None:
        return []
    triggered = []
    for name in named:
        state = detector_manager.get_detector_state(name)
        if state is None or not state.is_active:
            detector_manager.activate_detector(name)
        if begin(name):
            triggered.append(name)
    return triggered


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
    record = merge.records[exposure.record]
    assert record.data is not None
    if not exposure.detector.has_axis("c"):
        images = images[np.newaxis]  # one color: what it delivers is its only one
    for offset, image in enumerate(images):
        channel = exposure.first_channel + offset
        stack = PLANE if PLANE in record.dims else "z"
        at = {"t": time_index, "c": channel, stack: z_index}
        place: tuple[Any, ...] = tuple(at.get(name, slice(None)) for name in record.dims)
        target = record.data[place]
        # a probe's reading has one position along what it has no extent along: as its record does
        record.data[place] = image if image.shape == target.shape else image.reshape(target.shape)
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
    # What streams records alongside, the whole time; the rest is taken when it is due.
    streamed = [channel for channel in plan.channels if channel.stream]
    plan = replace(plan, channels=[channel for channel in plan.channels if not channel.stream])
    if not plan.channels:
        raise ValueError(
            "A stream records while something is taken: add a channel that is not streamed"
        )
    streams = _streams_of(streamed, detector_manager, space, values)
    cadences = [_cadence_of(channel, plan) for channel in plan.channels]
    events = _events(cadences)
    offsets = _offsets_of(plan)
    named = list(dict.fromkeys(name for channel in plan.channels for name in channel.detectors))
    if not named:
        raise ValueError(f"The channel {plan.channels[0].name!r} names no detector")
    # Each sample the plan sees, and on each what looks: whose image's middle goes to a place,
    # and whose focus sweeps the sample's stack. Which sample a detector sees is what its
    # channel's switches say.
    looks = _looks_of(plan, values, space, detector_manager)
    samples = list(dict.fromkeys(look.sample for look in looks))
    if plan.stack.variable is not None and len(samples) > 1:
        raise ValueError(
            f"This plan sees the samples {samples}, and {plan.stack.variable} would sweep one of "
            "them: leave stack.variable out, and each sweeps what focuses it"
        )
    firsts = {
        sample: next(
            (
                look
                for look in looks
                if look.sample == sample
                and _find_detector(look.detector, detector_manager).delivers_images()
            ),
            None,
        )
        for sample in samples
    }
    sweeps = {
        sample: _sweep_of(
            plan,
            offsets,
            None if firsts[sample] is None else firsts[sample].detector,
            values,
            sample,
            len(samples) == 1,
        )
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
            looks,
            cadences,
        )
        for index, position in enumerate(plan.positions)
    ]
    _check_memory(
        [
            record.data
            for merge in merges
            for record in merge.records.values()
            if record.data is not None and not _streamable(record, store)
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

    total = sum(len(merge.offsets) * len(due) for _, due in events for merge in merges)
    done = 0
    task.progress(0, message=f"Starting acquisition: {total} exposures of all detectors")

    # One clock: every channel is due on it, and every stream starts with it.
    started_at = time.monotonic()
    started_wall = datetime.now(timezone.utc)
    for stream in streams:
        detector_manager.start_stream(stream.detector.name)
        stream.started = datetime.now(timezone.utc)
    opened: list[RecordStream] = []
    timing = Timing()
    writes = Writes()
    lit: dict[str, Any] = {}  # what the lights were last set to here: only changes are sent
    triggered: list[str] = []
    try:
        with timing("setup"):
            opened += _open_streams(merges, store, plan.pyramid)
            triggered += _trigger(named, detector_manager)
        for due_s, due in events:
            wait = started_at + due_s - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            for stream in streams:
                stream.blocks += detector_manager.read_stream(stream.detector.name)

            hook_manager.execute_all(plan.t_hooks or [])
            if plan.t_hooks:
                lit.clear()  # a hook may have set a light

            order = list(range(len(plan.positions)))
            if plan.order == PositionOrder.RANDOM:
                random.shuffle(order)

            for position_index in order:
                merge = merges[position_index]
                with timing("move"):
                    values.set(merge.targets, task=task)
                    # Position hooks run there (an autofocus may refocus); the stacks are centred on
                    # where it is afterwards.
                    _position_hooks(plan, merge, firsts, values, hook_manager)
                if plan.p_hooks:
                    lit.clear()
                bases = {
                    sweep.name: float(values[sweep.name])
                    for sweep in merge.sweeps.values()
                    if sweep is not None
                }
                _place(merge, space, values)
                lightings = [
                    (lighting, due[index])
                    for index, lighting in enumerate(merge.lightings)
                    if index in due
                ]

                if merge.swept:
                    # The detector steps what sweeps: the routine only brings it to the first plane.
                    for lighting, time_index in lightings:
                        task.pausepoint()
                        with timing("move"):
                            _sweep_to(merge, bases, merge.offsets[0], values, task)
                        with timing("light"):
                            _light(lighting.targets, lit, values)
                        exposure = lighting.exposures[0]
                        _activate(exposure, detector_manager)
                        begun = datetime.now(timezone.utc)
                        for z_index, images in enumerate(
                            detector_manager.capture_stack(
                                exposure.detector.name, len(merge.offsets)
                            )
                        ):
                            if merge.records[exposure.record].stream is not None:
                                _stream_in(
                                    merge, exposure, lambda images=images: FrameMemory.of_array(images),
                                    time_index, z_index, begun, store,
                                )
                            else:
                                _keep(merge, exposure, images, time_index, z_index, begun, store)
                            begun = datetime.now(timezone.utc)
                            done += 1
                            timing.exposures += 1
                            with timing("bookkeeping"):
                                task.progress(
                                    int(done / total * 90),
                                    f"{due_s:g} s, P{position_index + 1}, Z{z_index + 1}: "
                                    f"{lighting.channel.name or 'channel'} ({done}/{total})",
                                )
                    continue

                for z_index, offset in enumerate(merge.offsets):
                    with timing("move"):
                        _sweep_to(merge, bases, offset, values, task)
                        hook_manager.execute_all(plan.z_hooks or [])
                    if plan.z_hooks:
                        lit.clear()

                    for lighting, time_index in lightings:
                        task.pausepoint()
                        with timing("light"):
                            _light(lighting.targets, lit, values)
                        _expose(
                            merge, lighting, time_index, z_index, store, detector_manager,
                            timing, writes,
                        )
                        done += 1
                        timing.exposures += 1
                        with timing("bookkeeping"):
                            task.progress(
                                int(done / total * 90),
                                f"{due_s:g} s, P{position_index + 1}, Z{z_index + 1}: "
                                f"{lighting.channel.name or 'channel'} ({done}/{total})",
                            )
        with timing("write"):
            writes.wait()  # the last exposure is in its stream
        timing.stop()
        for stream in streams:
            stream.blocks += detector_manager.read_stream(stream.detector.name)
    except BaseException:
        writes.close()
        for record_stream in opened:  # nothing half-taken is kept: the store drops it
            record_stream.abort()
        raise
    finally:
        # However it ended: a failure leaves no sample lit for as long as nobody looks, and no
        # stream recording; no write still reads a camera's slot as it is let run free.
        writes.close()
        for name in triggered:
            detector_manager.end_triggered(name)  # type: ignore[attr-defined]
        for stream in streams:
            detector_manager.stop_stream(stream.detector.name)
        _lights_off(values)

    datasets = []
    for merge in merges:
        task.progress(
            90 + int(10 * merge.index / len(merges)), f"Writing position {merge.index + 1}"
        )
        label = merge.position.name or f"P{merge.index + 1}"
        for key, record in merge.records.items():
            assert (record.data is not None or record.stream is not None) and record.placed is not None
            assert record.cadence is not None
            parts = [plan.name, *([] if len(merges) == 1 else [label]), key]
            mounted_at = space.state.samples[record.sample].mounted_at
            datasets.append(
                store.publish(
                    AcquiredRecord(
                        name=" ".join(part for part in parts if part),
                        position=merge.index,
                        detector=record.detector.name,
                        data=record.data,
                        axes=record.axes,
                        channels=tuple(record.channels),
                        planes=tuple(record.planes),
                        registration=(
                            *to_parts(record.placed),
                            _time_part(
                                record.detector,
                                record.cadence.every_s or 1.0,
                                _since(mounted_at, started_wall) + record.cadence.start_s,
                            ),
                        ),
                        calibrated=record.calibrated,
                        quantity=record.detector.quantity,
                        unit=record.detector.unit,
                        sample=record.sample,
                        mount_id=space.state.samples[record.sample].mount_id,
                        mounted_at=mounted_at,
                        mount=zyx_rows(space.mount(record.sample)),
                        stream=record.stream,
                        shape=record.streamed[0],
                        dtype=record.streamed[1],
                        pyramid=plan.pyramid,
                    )
                )
            )
    datasets += [
        store.publish(record)
        for record in (_stream_record(plan, stream, space, store) for stream in streams)
        if record is not None
    ]
    show = getattr(store, "show", None)
    if show is not None and datasets:
        # A scene of the run: a view of what it stored, so a failure here loses nothing.
        scene = f"{plan.name or 'acquisition'} {started_wall.astimezone():%Y-%m-%d %H:%M}"
        try:
            show(scene, datasets)
        except Exception:  # noqa: BLE001 - the datasets are stored; only the view is missing
            logger.exception("acquisition %s: no scene made of it", scene)
    logger.info("acquisition %s: %s", plan.name or "", timing.summary())
    task.progress(
        100,
        message=f"Acquisition complete: {len(datasets)} datasets; {timing.summary()}",
    )
    return datasets
