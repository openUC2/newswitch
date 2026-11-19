"""A multidimensional acquisition from what a form gives: the plan `acquire` runs.

A blok cannot build a plan: it has no lists to fill and no loops to map one over. So it names what
it wants in plain values (the channels by the names the optics give them, a stack's range and step,
a grid's columns and rows, a time-lapse) and `acquire_mda` makes the plan of them as the newswitch
frontend does (``frontend/src/lib/microscope/plan.ts``): each channel at the brightness its source
has now, or its preset, and the exposure its detectors have now; those of one source at one
brightness under the same swaps one exposure of all their detectors; planes centred where the
focus is; a grid's tiles a field of view apart, less the overlap, around where the view is.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from arkitekt import Key, Task

from newswitch import protocols
from newswitch.models.acquisition import (
    AcquiredDataset,
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    AcquisitionStack,
)
from newswitch.models.optics import OpticalChannel
from newswitch.models.space import Position
from newswitch.models.values import LightSource
from newswitch.protocols.dataset_store import DatasetStore
from newswitch.routines.acquire import acquire
from newswitch.services.space import SpaceManager
from newswitch.services.values import Values
from newswitch.states.optics import OpticsState
from newswitch.states.values import SourceState


def _half_up(value: float) -> int:
    """Rounded as JavaScript's Math.round does, so a plan here is the frontend's."""
    return math.floor(value + 0.5)


def stack_offsets(range_um: float, step_um: float) -> list[float]:
    """Where the planes of a stack `range_um` deep, `step_um` apart, are: around where it is.

    At least two planes; none (one plane, where it is) for no range.

    Raises:
        ValueError: A range with no step.
    """
    if range_um <= 0:
        return []
    if not step_um > 0:
        raise ValueError("The planes of a stack need a distance apart")
    planes = max(2, _half_up(range_um / step_um) + 1)
    return [(i - (planes - 1) / 2) * step_um for i in range(planes)]


def grid_positions(
    columns: int,
    rows: int,
    overlap: float,
    looking: tuple[float, float],
    field: tuple[float, float],
    system: str = "sample",
) -> list[AcquisitionPosition]:
    """A grid's tiles around `looking`, each a field of view apart less the overlap; row by row,
    every other row backwards, so that the stage never runs back across the grid."""
    share = 1 - min(max(overlap, 0.0), 0.9)

    def along(index: int, count: int, size: float) -> float:
        return (index - (count - 1) / 2) * size * share

    positions = []
    for row in range(rows):
        for step in range(columns):
            column = step if row % 2 == 0 else columns - 1 - step
            positions.append(
                AcquisitionPosition(
                    name=f"r{row + 1}c{column + 1}",
                    at=Position(
                        system=system,
                        coordinates={
                            "x": looking[0] + along(column, columns, field[0]),
                            "y": looking[1] + along(row, rows, field[1]),
                        },
                    ),
                )
            )
    return positions


def _power(source: LightSource | None) -> float:
    """The brightness a channel of `source` is taken at: what it has now, if it is on, else its
    preset, else a fifth of what it can."""
    if source is None:
        return 0.0
    if source.on and source.power > 0:
        return source.power
    return source.lit_power or source.max_power / 5


def channels_of(
    picked: Sequence[OpticalChannel],
    sources: Mapping[str, LightSource],
    values: Mapping[str, Any],
    swaps: Mapping[str, int],
) -> list[AcquisitionChannel]:
    """The picked channels as the plan's: those of one source at one brightness, under the same
    swaps, one exposure of all their detectors at once. Each sets the swaps it takes over those as
    they are now (`swaps`), its source's power and its detectors' exposures as they are now."""
    lit: dict[tuple, AcquisitionChannel] = {}
    for channel in picked:
        source = sources.get(channel.source)
        power = _power(source)
        own = {swap.variable: swap.slot for swap in channel.swaps}
        key = (channel.source, power, tuple(sorted(own.items())))
        if key not in lit:
            set_to: dict[str, float] = {**swaps, **own}
            if source is not None and source.power_variable:
                set_to[source.power_variable] = power
            lit[key] = AcquisitionChannel(name=channel.name, detectors=[], set_to=set_to)
        acquired = lit[key]
        if channel.detector not in acquired.detectors:
            acquired.detectors.append(channel.detector)
        exposure = f"{channel.detector}.exposure"
        if exposure in values:
            acquired.set_to[exposure] = float(values[exposure])
    return list(lit.values())


def mda_plan(
    picked: Sequence[OpticalChannel],
    sources: Mapping[str, LightSource],
    values: Mapping[str, Any],
    swaps: Mapping[str, int],
    looking: tuple[float, float] | None,
    z_range_um: float = 0.0,
    z_step_um: float = 1.0,
    columns: int = 1,
    rows: int = 1,
    overlap: float = 0.1,
    times: int = 1,
    every_s: float = 0.0,
    name: str = "mda",
) -> AcquisitionPlan:
    """The plan of `picked` channels, a stack, a grid around `looking` and a time-lapse.

    Raises:
        ValueError: Nothing picked; channels of more than one sample; a grid where the view is not
            known, or a stack with no step.
    """
    if not picked:
        raise ValueError("Pick a channel to image")
    samples = sorted({channel.sample for channel in picked if channel.sample})
    if len(samples) > 1:
        raise ValueError(f"An acquisition is of one sample; these channels see {samples}")
    sample = samples[0] if samples else ""
    columns, rows = max(1, columns), max(1, rows)
    if columns * rows == 1:
        positions = [AcquisitionPosition()]
    else:
        if looking is None:
            raise ValueError("Where the view is is not known, so a grid has nowhere to go")
        field = (
            min(channel.field_width_um for channel in picked),
            min(channel.field_height_um for channel in picked),
        )
        system = f"sample:{sample}" if sample else "sample"
        positions = grid_positions(columns, rows, overlap, looking, field, system)
    return AcquisitionPlan(
        name=name or "mda",
        channels=channels_of(picked, sources, values, swaps),
        positions=positions,
        stack=AcquisitionStack(offsets=stack_offsets(z_range_um, z_step_um)),
        times=max(1, times),
        every_s=max(0.0, every_s),
    )


def acquire_mda(
    channels: list[str],
    store: DatasetStore,
    optics_state: OpticsState,
    source_state: SourceState,
    optics_manager: protocols.OpticsManager,
    detector_manager: protocols.DetectorManager,
    values: Values,
    space: SpaceManager,
    hook_manager: protocols.HookManager,
    task: Task,
    z_range_um: float = 0.0,
    z_step_um: float = 1.0,
    columns: int = 1,
    rows: int = 1,
    overlap: float = 0.1,
    times: int = 1,
    every_s: float = 0.0,
    name: str = "mda",
) -> Annotated[list[AcquiredDataset], Key("datasets")]:
    """Acquire the channels named, on a stack of planes, over a grid of tiles, some times.

    Each channel is taken at the brightness its source has now (its preset when it is off) and the
    exposure its detectors have now. The planes are centred where the focus is, and the tiles of a
    grid around where the view is, a field of view apart less the overlap.

    Args:
        channels: The channels to image, by the names the optics give them; all of one sample.
        z_range_um: How deep the stack is, in micrometres; 0: one plane, where the focus is.
        z_step_um: How far apart its planes are, in micrometres.
        columns: How many tiles across.
        rows: How many tiles down.
        overlap: How much neighbouring tiles share, from 0 to 0.9.
        times: How many times to take all of it.
        every_s: Seconds from the start of one time to the next; 0: right after it.
        name: What to call the datasets; each tile's gets its tile's name too.

    Returns:
        The datasets created: for each tile, one per detector.
    """
    by_name = {channel.name: channel for channel in optics_state.channels}
    unknown = [wanted for wanted in channels if wanted not in by_name]
    if unknown:
        raise ValueError(f"No channel is called {unknown}; there are {sorted(by_name)}")
    picked = [by_name[wanted] for wanted in channels]
    now = values.snapshot()
    swaps = {
        variable: int(now[variable])
        for variable, spec in values.instrument.variables.items()
        if spec.verb == "swaps"
    }
    looking = space.looking_at(picked[0].detector) if columns * rows > 1 and picked else None
    plan = mda_plan(
        picked,
        source_state.sources,
        now,
        swaps,
        looking,
        z_range_um=z_range_um,
        z_step_um=z_step_um,
        columns=int(columns),
        rows=int(rows),
        overlap=overlap,
        times=int(times),
        every_s=every_s,
        name=name,
    )
    return acquire(plan, store, optics_manager, detector_manager, values, space, hook_manager, task)
