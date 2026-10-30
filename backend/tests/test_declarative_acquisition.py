"""The declarative acquisition example: a place to be, and what it takes to get there."""

import copy
from typing import Any

import numpy as np
import pytest
import yaml

from examples.declarative_acquisition import simulated
from examples.declarative_acquisition.instrument import (
    Acquisition,
    Blocked,
    CoordinateGraph,
    DescriptionError,
    Edge,
    Instrument,
    NoRoute,
    Position,
    Request,
    Validity,
    scaling,
    translation,
)
from newswitch.services.mikro_connection import MikroConfigError, MikroConnection

PATH = "epi-488"


@pytest.fixture
def clock() -> simulated.Clock:
    """A clock the test moves."""
    return simulated.Clock()


@pytest.fixture
def instrument(clock: simulated.Clock) -> Instrument:
    """The pretend microscope, nothing calibrated."""
    return simulated.instrument(clock)


def at_stage(x: float = 100.0, y: float = 50.0, **settings: Any) -> Request:  # noqa: ANN401
    """An image of the gfp channel at a stage position."""
    return Request(Position("stage", x, y), "gfp", settings)


def action(plan: Any, quantity: str) -> str:  # noqa: ANN401
    """What the plan does about `quantity`."""
    return next(need.action for need in plan.needs if need.quantity == quantity)


def key_of(instrument: Instrument, quantity: str, **settings: Any) -> str:  # noqa: ANN401
    """Which calibration of `quantity` applies with `settings` on top of the current values."""
    return instrument.key(quantity, instrument.paths[PATH], {**instrument.values, **settings})


# --- the graph


def test_a_route_may_walk_an_edge_backwards() -> None:
    """Going to a place means walking from it to the motors, whichever way the edges were made."""
    graph = CoordinateGraph(
        [
            Edge("pixels", "stage", scaling(0.5, 0.5), Validity.MANUAL),
            Edge("plate", "stage", translation(100.0, 0.0), Validity.VALIDATED),
        ]
    )
    assert graph.transform((4.0, 2.0, 0.0), "pixels", "plate") == pytest.approx([-98.0, 1.0, 0.0])


def test_a_route_is_known_as_far_as_its_weakest_edge() -> None:
    """A measured scale after a nominal one is no better than the nominal one."""
    graph = CoordinateGraph(
        [
            Edge("a", "b", np.eye(4), Validity.INFERRED),
            Edge("b", "c", np.eye(4), Validity.VALIDATED),
        ]
    )
    assert graph.validity("a", "c") == Validity.INFERRED


def test_systems_that_are_not_connected_have_no_route() -> None:
    """Nothing is guessed."""
    with pytest.raises(NoRoute):
        CoordinateGraph().route("a", "b")


def test_a_position_goes_through_the_graph_to_the_motors(instrument: Instrument) -> None:
    """Plate to stage by its registration, stage to steps by each actuator's own calibration."""
    instrument.calibrate("stage_zero", PATH)
    instrument.calibrate("plate_registration", PATH)
    plan = instrument.plan(Request(Position("plate-1", 9000.0, 9000.0), "gfp"))
    assert plan.route == ["plate-1", "stage"]
    moves = {step.variable: step for step in plan.moves}
    assert moves["sample-stage.x"].target == 10000.0
    assert moves["sample-stage.x"].native == 80000.0
    assert moves["sample-stage.y"].native == 88000.0


def test_an_inverted_actuator_is_told_the_other_way(instrument: Instrument) -> None:
    """The sign belongs to the edge between the stage and the motors."""
    plan = instrument.plan(Request(Position("stage", 0.0, 0.0, z=10.0), "gfp"))
    assert plan.z is not None
    assert plan.z.native == -250.0


def test_a_point_in_an_earlier_image_is_a_place_to_go(instrument: Instrument) -> None:
    """The image's own edge says where that pixel is; the stage centres it."""
    instrument.calibrate("pixel_to_sample", PATH)
    record = instrument.apply(instrument.plan(at_stage()))
    plan = instrument.plan(Request(Position(record.image, 31.5, 23.5), "gfp"))
    # the middle of the image is where the stage already was
    assert plan.target["x"] == pytest.approx(100.0)
    assert plan.target["y"] == pytest.approx(50.0)
    corner = instrument.plan(Request(Position(record.image, 0.0, 0.0), "gfp"))
    assert corner.target["x"] == pytest.approx(100.0 + 0.663 * 31.5)  # x is flipped
    assert corner.target["y"] == pytest.approx(50.0 - 0.663 * 23.5)


# --- what impacts what


def test_which_variable_matters_on_which_path_is_derived(instrument: Instrument) -> None:
    """No cube names a path, yet the report knows the turret matters for epi-488."""
    rows = instrument.impact_report()
    turret = [row for row in rows if row["actuator"] == "turret"]
    assert {row["quantity"] for row in turret} >= {"pixel_to_sample", "focus_plane"}
    assert all(row["relation"] == "selects" and row["paths"] == [PATH] for row in turret)


def test_what_selects_a_calibration_changes_its_key(instrument: Instrument) -> None:
    """Another objective needs another pixel size."""
    assert key_of(instrument, "pixel_to_sample", **{"objective.slot": 2}) != key_of(
        instrument, "pixel_to_sample"
    )


@pytest.mark.parametrize(
    "setting",
    [{"sample-stage.x": 500.0}, {"sample-stage.z": 5.0}, {"camera.exposure_ms": 500.0}],
)
def test_what_does_not_select_a_calibration_leaves_its_key(
    instrument: Instrument, setting: dict[str, float]
) -> None:
    """Moving, refocusing and exposing longer do not touch the pixel size."""
    assert key_of(instrument, "pixel_to_sample", **setting) == key_of(instrument, "pixel_to_sample")


def test_exposure_selects_the_dark_frame_but_not_the_flat_field(instrument: Instrument) -> None:
    """One hash per light path could not say this: each calibration has its own key."""
    longer = {"camera.exposure_ms": 500.0}
    assert key_of(instrument, "dark", **longer) != key_of(instrument, "dark")
    assert key_of(instrument, "flat_field", **longer) == key_of(instrument, "flat_field")


def test_a_filter_selects_the_chromatic_shift_but_not_the_pixel_size(
    instrument: Instrument,
) -> None:
    """The calibration found again after changing the filter is the pixel size's."""
    other = {"emission-wheel.slot": 2}
    assert key_of(instrument, "chromatic_shift", **other) != key_of(instrument, "chromatic_shift")
    assert key_of(instrument, "pixel_to_sample", **other) == key_of(instrument, "pixel_to_sample")


# --- what is stale


def test_what_was_never_measured_counts_as_out_of_spec(instrument: Instrument) -> None:
    """Unknown is not good: the plan says what it is missing."""
    assert action(instrument.plan(at_stage()), "focus_plane") == "repair"
    assert action(instrument.plan(at_stage()), "flat_field") == "warn"


def test_a_missing_pixel_size_falls_back_on_the_nominal_one_and_says_so(
    instrument: Instrument,
) -> None:
    """10x and 6.5 um pixels: 0.65 um per pixel, known from the datasheet only."""
    plan = instrument.plan(at_stage())
    assert action(plan, "pixel_to_sample") == "nominal"
    record = instrument.apply(plan)
    assert record.validity == Validity.INFERRED
    assert record.matrix[0, 0] == pytest.approx(0.65)


def test_a_measured_pixel_size_replaces_the_nominal_one(instrument: Instrument) -> None:
    """The measurement wins, flip included, and the image says it was measured."""
    instrument.calibrate("pixel_to_sample", PATH)
    record = instrument.apply(instrument.plan(at_stage()))
    assert record.validity == Validity.MANUAL
    assert record.matrix[0, 0] == pytest.approx(-0.663)


def test_a_confirmed_calibration_is_validated_and_holds_for_longer(
    instrument: Instrument, clock: simulated.Clock
) -> None:
    """A check that passes keeps the value and starts its time again."""
    instrument.calibrate("stage_zero", PATH)
    instrument.calibrate("focus_plane", PATH)
    clock.advance(1.5)
    assert instrument.confirm("focus_plane", PATH).validity == Validity.VALIDATED
    clock.advance(1.5)
    assert action(instrument.plan(at_stage()), "focus_plane") == "ok"


def test_a_calibration_ages_out(instrument: Instrument, clock: simulated.Clock) -> None:
    """Focus holds two hours, the pixel size a month."""
    instrument.calibrate("stage_zero", PATH)
    instrument.calibrate("focus_plane", PATH)
    instrument.calibrate("pixel_to_sample", PATH)
    clock.advance(3)
    plan = instrument.plan(at_stage())
    assert action(plan, "focus_plane") == "repair"
    assert action(plan, "pixel_to_sample") == "ok"


def test_an_event_invalidates_what_does_not_survive_it(
    instrument: Instrument, clock: simulated.Clock
) -> None:
    """A new sample takes the focus with it, and leaves the pixel size."""
    instrument.calibrate("stage_zero", PATH)
    instrument.calibrate("focus_plane", PATH)
    instrument.calibrate("pixel_to_sample", PATH)
    clock.advance(0.1)
    instrument.event("sample-changed")
    plan = instrument.plan(at_stage())
    assert action(plan, "focus_plane") == "repair"
    assert action(plan, "pixel_to_sample") == "ok"


def test_what_depends_on_something_stale_is_stale(
    instrument: Instrument, clock: simulated.Clock
) -> None:
    """A power cycle costs the stage its zero, and with it the focus and the plate."""
    instrument.calibrate("stage_zero", PATH)
    instrument.calibrate("focus_plane", PATH)
    instrument.calibrate("plate_registration", PATH)
    clock.advance(0.1)
    instrument.event("power-cycle")
    plan = instrument.plan(Request(Position("plate-1", 0.0, 0.0), "gfp"))
    assert action(plan, "stage_zero") == "repair"
    assert action(plan, "focus_plane") == "repair"
    assert action(plan, "plate_registration") == "block"


def test_recalibrating_something_invalidates_what_depends_on_it(
    instrument: Instrument, clock: simulated.Clock
) -> None:
    """Rehoming moves the zero, so what was measured against the old one no longer holds."""
    instrument.calibrate("stage_zero", PATH)
    instrument.calibrate("focus_plane", PATH)
    assert action(instrument.plan(at_stage()), "focus_plane") == "ok"
    clock.advance(0.1)
    instrument.calibrate("stage_zero", PATH)
    assert action(instrument.plan(at_stage()), "focus_plane") == "repair"


def test_repairs_start_at_the_deepest_failure(instrument: Instrument) -> None:
    """The zero first, and the focus against it."""
    assert instrument.plan(at_stage()).repairs == ["stage_zero", "focus_plane"]


def test_a_stale_registration_blocks_before_anything_moves(instrument: Instrument) -> None:
    """A position that cannot be reached leaves the microscope alone."""
    plan = instrument.plan(Request(Position("plate-1", 0.0, 0.0), "gfp"))
    assert plan.blocked
    before = dict(instrument.values)
    with pytest.raises(Blocked):
        instrument.apply(plan)
    assert instrument.values == before
    assert instrument.log == []


# --- the plan


def test_the_plan_only_changes_what_differs(instrument: Instrument) -> None:
    """A second image at the same place moves nothing."""
    instrument.apply(instrument.plan(at_stage()))
    plan = instrument.plan(at_stage())
    assert plan.moves == []
    assert plan.before == []
    assert plan.after == []
    assert plan.repairs == []


def test_the_laser_goes_off_before_the_filter_moves_and_on_again_after(
    instrument: Instrument,
) -> None:
    """The one rule of this microscope: stated, not searched for."""
    instrument.apply(instrument.plan(at_stage()))
    instrument.log.clear()
    instrument.apply(instrument.plan(Request(Position("stage", 100.0, 50.0), "reflection")))
    assert instrument.log.index("set laser-488.on") < instrument.log.index(
        "set emission-wheel.slot"
    )
    assert instrument.log[-2] == "set laser-488.on"
    assert instrument.values["laser-488.on"] is True


def test_focus_is_measured_where_the_image_is_taken(instrument: Instrument) -> None:
    """Moves, then the repair, then z from what it found, then the light."""
    instrument.apply(instrument.plan(at_stage()))
    log = instrument.log
    assert log.index("set sample-stage.x") < log.index("calibrate focus_plane")
    assert log.index("calibrate focus_plane") < log.index("set sample-stage.z")
    assert log.index("set sample-stage.z") < log.index("set laser-488.on")


def test_z_follows_the_tilted_sample(instrument: Instrument) -> None:
    """Z is computed forwards from x and y, so a focus map never has to be inverted."""
    instrument.apply(instrument.plan(at_stage()))
    plan = instrument.plan(at_stage(x=1000.0, y=2000.0))
    assert plan.target["z"] == pytest.approx(60.0 + 0.001 * 1000.0 - 0.002 * 2000.0)


def test_the_stage_position_is_an_offset_the_pixel_scale_does_not_touch(
    instrument: Instrument,
) -> None:
    """A pixel is at stage + scale @ (pixel - centre), so an image centres on the stage."""
    instrument.calibrate("pixel_to_sample", PATH)
    record = instrument.apply(instrument.plan(at_stage(x=1000.0, y=2000.0)))
    centre = record.matrix @ np.array([31.5, 23.5, 0.0, 1.0])
    assert centre[:2] == pytest.approx([1000.0, 2000.0])


def test_an_acquisition_is_the_requests_it_expands_into() -> None:
    """Per timepoint, per position, per plane, per channel."""
    acquisition = Acquisition(
        positions=(Position("stage", 0.0, 0.0), Position("stage", 1.0, 0.0)),
        channels=("gfp", "reflection"),
        z_offsets=(-1.0, 1.0),
        timepoints=3,
    )
    requests = list(acquisition.requests())
    assert len(requests) == 3 * 2 * 2 * 2
    assert requests[0].at.z_offset == -1.0
    assert requests[1].channel == "reflection"


def test_an_acquisition_repairs_once_and_only_moves_what_it_has_to(
    instrument: Instrument,
) -> None:
    """Each request is planned on its own, against what the last one left behind."""
    acquisition = Acquisition(
        positions=(Position("stage", 0.0, 0.0), Position("stage", 10.0, 0.0)), channels=("gfp",)
    )
    for request in acquisition.requests():
        instrument.apply(instrument.plan(request))
    assert instrument.log.count("calibrate focus_plane") == 1
    assert instrument.log.count("set emission-wheel.slot") == 1
    assert instrument.log.count("acquire image:1") == 1


# --- a description that contradicts itself


@pytest.mark.parametrize(
    ("change", "complaint"),
    [
        (lambda d: d["paths"]["epi-488"]["detection"].append("nope"), "no cube 'nope'"),
        (lambda d: d["channels"]["gfp"].update(path="nope"), "no path 'nope'"),
        (lambda d: d["channels"]["gfp"]["set"].update({"nope.x": 1}), "no variable 'nope.x'"),
        (
            lambda d: d["cubes"]["camera"]["impacts"]["dark"]["selects"].append("nope"),
            "no variable 'nope'",
        ),
        (lambda d: d["calibrations"]["dark"].update(routine="nope"), "no routine 'nope'"),
        (lambda d: d["calibrations"]["dark"].update(depends_on=["nope"]), "unknown 'nope'"),
        (lambda d: d["calibrations"]["dark"].update(depends_on=["dark"]), "depends on itself"),
        (lambda d: d["systems"]["plate-1"].update(registered_by="nope"), "no calibration 'nope'"),
        (lambda d: d["calibrations"]["dark"].update(on_stale="panic"), "on_stale 'panic'"),
    ],
)
def test_a_description_that_contradicts_itself_is_refused(change: Any, complaint: str) -> None:  # noqa: ANN401
    """Everything a part names has to exist, before the first plan."""
    description = copy.deepcopy(yaml.safe_load(simulated.DESCRIPTION.read_text()))
    change(description)
    with pytest.raises(DescriptionError, match=complaint):
        Instrument(description, simulated.ROUTINES, simulated.camera)


# --- mikro


def test_mikro_is_off_unless_the_environment_names_it() -> None:
    """Unset or empty, as compose passes it: FastAPI mode runs without one."""
    assert MikroConnection.from_env({}) is None
    assert MikroConnection.from_env({"MIKRO_URL": ""}) is None


def test_half_a_mikro_configuration_is_refused() -> None:
    """It should not look like running without mikro."""
    with pytest.raises(MikroConfigError, match="MIKRO_TOKEN"):
        MikroConnection.from_env({"MIKRO_URL": "http://m", "MIKRO_DATALAYER_URL": "http://s"})


def test_mikro_is_configured_by_hand_from_the_environment() -> None:
    """A trailing slash does not end up in the path."""
    connection = MikroConnection.from_env(
        {"MIKRO_URL": "http://m/", "MIKRO_DATALAYER_URL": "http://s", "MIKRO_TOKEN": "t"}
    )
    assert connection == MikroConnection("http://m", "http://s", "t")


def test_a_record_becomes_mikros_own_inputs(instrument: Instrument) -> None:
    """The real input types of mikro accept the record, so the two cannot quietly drift apart."""
    pytest.importorskip("mikro")
    from examples.declarative_acquisition.mikro_export import anchor, light_graph, registration

    instrument.calibrate("pixel_to_sample", PATH)
    record = instrument.apply(instrument.plan(at_stage()))

    graph = light_graph(instrument, record)
    assert {element.id for element in graph.elements} == set(instrument.paths[PATH].cubes)
    assert len(graph.edges) == 3 + 4

    state = anchor(instrument, record).microscope
    assert state is not None
    assert {device.label for device in state.devices} >= {"camera", "laser-488", "objective"}

    edge = registration(record)
    assert edge["scale"]["x"] == pytest.approx(-0.663)
    assert edge["x"] == pytest.approx(100.0 + 0.663 * 31.5)
    assert edge["name"].startswith("pixel_to_sample:")


def test_a_rotated_image_is_refused_rather_than_written_without_its_rotation(
    instrument: Instrument,
) -> None:
    """`register` takes a scale and an offset; losing the rotation would misplace the image."""
    pytest.importorskip("mikro")
    from dataclasses import replace

    from examples.declarative_acquisition.mikro_export import registration

    record = instrument.apply(instrument.plan(at_stage()))
    rotated = record.matrix.copy()
    rotated[0, 1] = 0.1
    with pytest.raises(ValueError, match="rotated"):
        registration(replace(record, matrix=rotated))
