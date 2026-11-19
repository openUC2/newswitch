"""A multidimensional acquisition from a form's plain values: the plan the frontend would make."""

from pathlib import Path
from typing import Any

import pytest
from arkitekt import Task
from arkitekt_fastapi.testing import AsyncAgentTestClient
from fastapi import FastAPI

from newswitch.models.optics import ChannelSwap, OpticalChannel
from newswitch.models.values import LightSource
from newswitch.routines.mda import (
    acquire_mda,
    channels_of,
    grid_positions,
    mda_plan,
    stack_offsets,
)
from tests.conftest import collect_until_completed
from tests.test_acquire import RecordingStore, built


def channel(
    name: str = "GFP",
    source: str = "laser_488",
    detector: str = "camera_a",
    sample: str = "stage",
    swaps: tuple[ChannelSwap, ...] = (),
    field: tuple[float, float] = (100.0, 80.0),
) -> OpticalChannel:
    """A channel the optics found."""
    return OpticalChannel(
        source=source,
        detector=detector,
        electrons=1.0,
        name=name,
        description=name,
        sample=sample,
        swaps=list(swaps),
        field_width_um=field[0],
        field_height_um=field[1],
    )


def source(
    name: str, power: float = 0.0, lit: float = 0.0, max_power: float = 100.0
) -> LightSource:
    """A light source, on at `power` or off with `lit` as its preset."""
    return LightSource(
        name=name,
        emits="laser",
        wavelength=488.0,
        lines=[488.0],
        color="cyan",
        max_power=max_power,
        power=power,
        lit_power=lit,
        on=power > 0,
        power_variable=f"{name}.power",
    )


# --- the plan's parts, as plan.ts makes them ---------------------------------------------------


def test_no_range_is_one_plane_where_it_is() -> None:
    """Nothing to sweep: the stack is the focus as it is."""
    assert stack_offsets(0.0, 1.0) == []


def test_a_stack_is_at_least_two_planes_centred_where_it_is() -> None:
    """Planes either side of the focus, the step apart, never fewer than two."""
    assert stack_offsets(4.0, 2.0) == [-2.0, 0.0, 2.0]
    assert stack_offsets(0.5, 2.0) == [-1.0, 1.0]


def test_a_stack_needs_a_step() -> None:
    """A range with no distance between planes is no stack."""
    with pytest.raises(ValueError, match="distance apart"):
        stack_offsets(10.0, 0.0)


def test_a_grid_goes_row_by_row_every_other_row_backwards() -> None:
    """Serpentine, so the stage never runs back across the grid; a field apart less the overlap."""
    tiles = grid_positions(2, 2, 0.5, looking=(10.0, 20.0), field=(100.0, 80.0))
    assert [t.name for t in tiles] == ["r1c1", "r1c2", "r2c2", "r2c1"]
    assert [(t.at.coordinates["x"], t.at.coordinates["y"]) for t in tiles] == [
        (-15.0, 0.0),
        (35.0, 0.0),
        (35.0, 40.0),
        (-15.0, 40.0),
    ]


def test_overlap_is_held_below_all_of_a_tile() -> None:
    """Tiles sharing everything would never move: at most 90 % is shared."""
    tiles = grid_positions(2, 1, 5.0, looking=(0.0, 0.0), field=(100.0, 100.0))
    assert tiles[1].at.coordinates["x"] - tiles[0].at.coordinates["x"] == pytest.approx(10.0)


def test_one_source_at_one_brightness_exposes_its_detectors_together() -> None:
    """Two cameras behind one laser are one exposure, each at its own exposure time."""
    picked = [channel(detector="camera_a"), channel(name="GFP b", detector="camera_b")]
    values = {"camera_a.exposure": 20.0, "camera_b.exposure": 30.0}
    (lit,) = channels_of(picked, {"laser_488": source("laser_488", power=40.0)}, values, {})
    assert lit.detectors == ["camera_a", "camera_b"]
    assert lit.set_to == {
        "laser_488.power": 40.0,
        "camera_a.exposure": 20.0,
        "camera_b.exposure": 30.0,
    }


def test_channels_under_other_swaps_stay_apart_each_setting_its_own() -> None:
    """The same light through another filter is another exposure, over the swaps as they are."""
    green = channel(swaps=(ChannelSwap(variable="filter.slot", slot=1, label="GFP"),))
    red = channel(name="RFP", swaps=(ChannelSwap(variable="filter.slot", slot=2, label="RFP"),))
    lights = {"laser_488": source("laser_488", power=10.0)}
    now = {"filter.slot": 0, "turret.slot": 3}
    first, second = channels_of([green, red], lights, {}, now)
    assert first.set_to == {"filter.slot": 1, "turret.slot": 3, "laser_488.power": 10.0}
    assert second.set_to == {"filter.slot": 2, "turret.slot": 3, "laser_488.power": 10.0}


def test_a_source_that_is_off_is_taken_at_its_preset_or_a_fifth() -> None:
    """Off, it is lit as it was last; never lit, at a fifth of what it can."""
    (preset,) = channels_of([channel()], {"laser_488": source("laser_488", lit=7.0)}, {}, {})
    (fifth,) = channels_of([channel()], {"laser_488": source("laser_488")}, {}, {})
    assert preset.set_to["laser_488.power"] == 7.0
    assert fifth.set_to["laser_488.power"] == 20.0


def test_nothing_picked_is_no_plan() -> None:
    """A plan needs something to image."""
    with pytest.raises(ValueError, match="Pick a channel"):
        mda_plan([], {}, {}, {}, None)


def test_an_acquisition_is_of_one_sample() -> None:
    """Channels of two samples are refused, as the frontend's planner refuses them."""
    with pytest.raises(ValueError, match="one sample"):
        mda_plan([channel(sample="left"), channel(sample="right")], {}, {}, {}, None)


def test_one_tile_stays_where_it_is() -> None:
    """No grid: the one position goes nowhere, so where the view is need not be known."""
    plan = mda_plan([channel()], {}, {}, {}, None)
    assert len(plan.positions) == 1
    assert plan.positions[0].at is None


def test_a_grid_is_on_the_sample_of_its_channels_and_needs_the_view() -> None:
    """Tiles are placed on the one sample imaged, around where the view is; unknown, no grid."""
    plan = mda_plan(
        [channel(field=(100.0, 50.0)), channel(name="b", field=(60.0, 80.0))],
        {},
        {},
        {},
        (0.0, 0.0),
        columns=2,
        overlap=0.0,
    )
    assert [t.at.system for t in plan.positions] == ["sample:stage", "sample:stage"]
    # The smaller field of the two, so neither leaves a gap.
    assert plan.positions[1].at.coordinates["x"] - plan.positions[0].at.coordinates["x"] == 60.0
    with pytest.raises(ValueError, match="not known"):
        mda_plan([channel()], {}, {}, {}, None, rows=2)


# --- the action, on a simulated microscope -----------------------------------------------------


def run_mda(tmp_path: Path, channels: list[str], **form: Any) -> RecordingStore:  # noqa: ANN401
    """`acquire_mda` on the fake microscope, wired as the app wires it."""
    m = built(tmp_path, "fake-microscope")
    assert m.values is not None
    store = RecordingStore()
    acquire_mda(
        channels,
        store,
        m.optics.state,
        m.values.source_state,
        m.optics,
        m.detector,
        m.values,
        m.space,
        m.hooks,
        Task.local(),
        **form,
    )
    return store


def test_it_acquires_the_channels_named_over_a_grid_and_a_stack(tmp_path: Path) -> None:
    """Two cameras behind one laser, two tiles, three planes: a record per tile and camera."""
    store = run_mda(
        tmp_path,
        ["GFP · 488/>500 · camera_a", "GFP · 488/>500 · camera_b"],
        z_range_um=4.0,
        z_step_um=2.0,
        columns=2,
        name="run",
    )
    assert [(r.name, r.detector) for r in store.published] == [
        ("run r1c1 camera_a", "camera_a"),
        ("run r1c1 camera_b", "camera_b"),
        ("run r1c2 camera_a", "camera_a"),
        ("run r1c2 camera_b", "camera_b"),
    ]
    assert {r.data.shape[2] for r in store.published} == {3}


def test_a_channel_it_does_not_have_is_refused_naming_those_it_has(tmp_path: Path) -> None:
    """A name from another microscope says which there are, before anything moves."""
    with pytest.raises(ValueError, match="Brightfield 625 · camera_a"):
        run_mda(tmp_path, ["DAPI"])


# --- through the agent, as a blok calls it ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_call_reaches_the_store_with_the_states_injected(
    virtual_microscope_app: FastAPI,
) -> None:
    """Assigned as a blok assigns it, the plan is made of the states arkitekt injects: with no
    mikro here, it gets as far as the store and says what is missing."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        result = await client.assign(
            "acquire_mda",
            {"channels": ["GFP · 488/>500"], "columns": 2, "z_range_um": 4.0, "z_step_um": 2.0},
        )
        events = await collect_until_completed(client, result.task_id, timeout=30.0)
    assert events[-1].event_type != "COMPLETED"
    assert "MIKRO_URL" in events[-1].raw


@pytest.mark.asyncio
async def test_a_call_naming_no_channel_says_which_there_are(
    virtual_microscope_app: FastAPI,
) -> None:
    """The channels come from the published optics, so a wrong name is answered with the right."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        result = await client.assign("acquire_mda", {"channels": ["DAPI"]})
        events = await collect_until_completed(client, result.task_id, timeout=30.0)
    assert "Brightfield 625" in events[-1].raw
