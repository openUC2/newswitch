"""What each variable is for, found from what it does; and the one way of changing it."""

import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import yaml
from arkitekt import Task

from main_fastapi import create_fastapi_registry
from newswitch.actions import values as actions
from newswitch.drivers.base import register_driver
from newswitch.instrument import spec
from newswitch.instrument.compiler import influences
from newswitch.instrument.roles import Roles
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.routines.autofocus import run_autofocus
from newswitch.services.stage import stage_of, where
from newswitch.services.values import Values
from newswitch.simulation.drivers import Simulated
from tests.conftest import run_settings, wired_only

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
FAKE = INSTRUMENTS / "fake-microscope"
CAM_TEST = INSTRUMENTS / "cam-test"


def edited_fake(tmp_path: Path, change: Callable[[dict[str, Any]], Any]) -> spec.Instrument:
    """The fake microscope, in a folder of its own, without its views and with `change` made."""
    copy = tmp_path / "instrument"
    shutil.copytree(FAKE, copy)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    data.pop("ui", None)
    data.pop("agent_ui", None)
    change(data)
    path.write_text(yaml.safe_dump(data))
    return spec.load(copy)


def with_a_second_focus(data: dict[str, Any]) -> None:
    """A fine focus on the sample holder, beside its z."""
    data["cubes"]["stage"]["moves"]["fine_z"] = {
        "along": "axis",
        "initial": "0 um",
        "step": "100 um",
        "min": "-500 um",
        "max": "500 um",
    }


@pytest.fixture(scope="module")
def fake() -> Roles:
    """What is found of the fake microscope's variables."""
    return Roles(spec.load(FAKE))


@pytest.fixture
def values(microscope: Microscope) -> Values:
    """The reference microscope's values, built as the app builds them."""
    assert microscope.values is not None
    return microscope.values


# --- roles


@pytest.mark.parametrize("detector", ["camera_a", "camera_b"])
def test_what_moves_the_view_sideways_is_found(fake: Roles, detector: str) -> None:
    """Each camera's view moves with the stage's x and y, each along its own."""
    assert [move.name for move in fake.sideways(detector, "x")] == ["stage.x"]
    assert [move.name for move in fake.sideways(detector, "y")] == ["stage.y"]
    assert fake.x(detector).name == "stage.x"
    assert fake.y(detector).name == "stage.y"


@pytest.mark.parametrize("detector", ["camera_a", "camera_b"])
def test_what_focuses_is_found(fake: Roles, detector: str) -> None:
    """The stage's z changes how sharp an image is, and not how large."""
    assert [move.name for move in fake.focuses(detector)] == ["stage.z"]
    assert fake.focus(detector).name == "stage.z"


def test_a_tube_lens_that_changes_the_scale_does_not_focus(fake: Roles) -> None:
    """It blurs the image of its own camera, and makes it another size: so no focus of it."""
    found = fake.found["camera_a", "stage"]["tube_a.dz"]
    assert {"blur", "scale"} <= found
    assert "tube_a.dz" not in [move.name for move in fake.focuses("camera_a")]
    assert fake.found["camera_b", "stage"]["tube_a.dz"] == frozenset()


def test_what_a_variable_does_is_said(fake: Roles) -> None:
    """On any detector: the stage's x moves the image, the filter changes its light."""
    assert fake.does("stage.x") == ["position"]
    assert fake.does("stage.z") == ["blur"]
    assert "light" in fake.does("filter_wheel.slot")
    assert not {"position", "scale"} & set(fake.does("filter_wheel.slot"))


def test_two_moves_that_focus_are_refused_with_both_named(tmp_path: Path) -> None:
    """Nothing silently picks which motor an autofocus drives; a call can name the one it means."""
    roles = Roles(edited_fake(tmp_path, with_a_second_focus))
    with pytest.raises(ValueError, match=r"stage\.fine_z, stage\.z|stage\.z, stage\.fine_z"):
        roles.focus("camera_a")
    assert roles.focus("camera_a", named="stage.fine_z").name == "stage.fine_z"
    assert roles.focus("camera_a", named="stage.z").name == "stage.z"
    with pytest.raises(ValueError, match="stage.x is no focus of camera_a"):
        roles.focus("camera_a", named="stage.x")


def test_nothing_that_focuses_is_refused() -> None:
    """A camera alone: nothing here moves at all, and what is asked for is said."""
    roles = Roles(spec.load(CAM_TEST))
    assert roles.focuses("sim_cam") == []
    with pytest.raises(ValueError, match="Nothing here is a focus of sim_cam"):
        roles.focus("sim_cam")
    with pytest.raises(ValueError, match="sideways move of sim_cam"):
        roles.x("sim_cam")


# --- what moves a detector's view


def test_a_stage_is_what_was_found(tmp_path: Path) -> None:
    """Its moves are the ones that do that, with their limits; what it lacks says so."""
    m = build_microscope(run_settings(tmp_path), spec.load(FAKE))
    assert m.values is not None
    stage = stage_of(m.values, "camera_a")
    assert (stage.x_move.name, stage.y_move.name, stage.z_move.name) == (
        "stage.x",
        "stage.y",
        "stage.z",
    )
    assert (stage.min_x, stage.max_x, stage.max_z) == (-2000.0, 2000.0, 500.0)

    stage.move(x=30.0, z=5.0, is_absolute=True)
    stage.move(x=10.0)
    assert (stage.x, stage.y, stage.z) == pytest.approx((40.0, 0.0, 5.0))
    assert where(m.values, "camera_a") == pytest.approx((40.0, 0.0, 5.0))


def test_a_stage_with_nothing_to_move_refuses_before_anything_moves(tmp_path: Path) -> None:
    """A camera alone has no such stage, and its image stays where it is."""
    m = build_microscope(run_settings(tmp_path), spec.load(CAM_TEST))
    assert m.values is not None
    stage = stage_of(m.values, "sim_cam")
    assert (stage.x_move, stage.y_move, stage.z_move) == (None, None, None)
    assert (stage.x, stage.y, stage.z) == (0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="Nothing here moves along x"):
        stage.move(x=1.0)


def test_a_stage_of_two_focuses_needs_one_named(tmp_path: Path) -> None:
    """Asked for what moves a view, it cannot tell which focus is meant; it can be told."""
    m = build_microscope(run_settings(tmp_path), edited_fake(tmp_path, with_a_second_focus))
    assert m.values is not None
    with pytest.raises(ValueError, match="Several things are a focus of camera_a"):
        stage_of(m.values, "camera_a")
    assert stage_of(m.values, "camera_a", focus="stage.fine_z").z_move.name == "stage.fine_z"


def test_where_a_detector_looks_is_what_all_of_it_adds_up_to(tmp_path: Path) -> None:
    """However many things focus it: that asks none of them to go."""
    m = build_microscope(run_settings(tmp_path), edited_fake(tmp_path, with_a_second_focus))
    assert m.values is not None
    m.values.set({"stage.z": 3.0, "stage.fine_z": 2.0})
    assert where(m.values, "camera_a")[2] == pytest.approx(5.0)


def test_an_autofocus_refuses_to_guess_and_runs_on_the_one_named(tmp_path: Path) -> None:
    """A second focus motor stops it with a clear message, and moves nothing until it is named."""
    m = build_microscope(run_settings(tmp_path), edited_fake(tmp_path, with_a_second_focus))
    assert m.values is not None and m.detector is not None
    before = m.values.snapshot()
    with pytest.raises(ValueError, match="Several things are a focus of camera_a"):
        run_autofocus(
            m.values, m.detector, m.autofocus_state, m.optics, Task.local(), steps=3, z_range=4.0
        )
    assert m.values.snapshot() == before

    run_autofocus(
        m.values,
        m.detector,
        m.autofocus_state,
        m.optics,
        Task.local(),
        steps=3,
        z_range=4.0,
        focus="stage.fine_z",
    )
    assert m.values["stage.z"] == before["stage.z"]
    assert m.autofocus_state.best_z == m.values["stage.fine_z"]


# --- values


def test_set_clamps_to_the_range_a_variable_states(values: Values) -> None:
    """On both sides, for what moves as for what is tuned; what it got to is published."""
    values.set({"stage.z": 99999.0})
    assert values["stage.z"] == 5000.0
    assert values.move_state.moves["stage"]["z"].current == 5000.0
    values.set({"stage.z": -99999.0})
    assert values["stage.z"] == -5000.0
    values.set({"camera.gain": 200.0})
    assert values["camera.gain"] == 40.0
    assert values.tune_state.tunes["camera"]["gain"].current == 40.0


def test_set_refuses_an_unknown_variable_before_anything_moves(values: Values) -> None:
    """With what there is, and with what else was asked for still where it was."""
    before = values.snapshot()
    with pytest.raises(ValueError, match="stage.w is no variable"):
        values.set({"stage.x": 10.0, "stage.w": 1.0})
    assert values.snapshot() == before


def test_set_refuses_an_unknown_slot_before_anything_moves(values: Values) -> None:
    """With the slots there are, and with what else was asked for still where it was."""
    before = values.snapshot()
    with pytest.raises(ValueError, match=r"objective.slot has no slot 99: \[1, 2\]"):
        values.set({"stage.x": 10.0, "objective.slot": 99})
    assert values.snapshot() == before


def test_set_goes_by_a_value_when_it_is_relative(values: Values) -> None:
    """On top of where it is, and within its range."""
    values.set({"stage.x": 100.0})
    values.set({"stage.x": 25.0, "stage.y": -5.0}, relative=True)
    assert (values["stage.x"], values["stage.y"]) == pytest.approx((125.0, -5.0))
    values.set({"stage.z": 99999.0}, relative=True)
    assert values["stage.z"] == 5000.0


def test_lit_power_remembers_the_last_power_that_was_not_zero(values: Values) -> None:
    """What a switch comes on at: as it was, however often it was turned off."""
    laser = lambda: values.source_state.sources["laser_488"]  # noqa: E731
    assert (laser().power, laser().lit_power, laser().on) == (20.0, 20.0, True)

    values.set({"laser_488.power": 35.0})
    assert (laser().power, laser().lit_power, laser().on) == (35.0, 35.0, True)

    values.set({"laser_488.power": 0.0})
    assert (laser().power, laser().lit_power, laser().on) == (0.0, 35.0, False)

    values.set({"laser_488.power": 0.0})
    assert laser().lit_power == 35.0


def test_lit_power_of_a_source_that_starts_off_is_its_maximum(values: Values) -> None:
    """It has never been on, and 0 mW would be no light."""
    led = values.source_state.sources["led_625"]
    assert (led.power, led.on) == (0.0, False)
    assert led.lit_power == led.max_power


def test_a_source_with_nothing_to_tune_it_is_at_its_maximum(tmp_path: Path) -> None:
    """Whatever anyone asks: there is no variable to ask, and no ``parts`` said there has to be."""

    def tuneless(data: dict[str, Any]) -> None:
        del data["cubes"]["laser_488"]["tunes"]
        del data["hardware"]["actuators"]["laser-dac"]

    instrument = edited_fake(tmp_path, tuneless)
    m = build_microscope(run_settings(tmp_path), instrument)
    assert m.values is not None and m.detector is not None
    laser = m.source_state.sources["laser_488"]
    assert (laser.power_variable, laser.power, laser.on) == (None, laser.max_power, True)
    assert "laser_488.power" not in m.values.snapshot()
    frame = m.detector.capture_image("camera_a").data
    assert np.percentile(frame, 99.9) > np.median(frame)


def test_a_change_reaches_what_the_optics_publish(microscope: Microscope, values: Values) -> None:
    """Without anyone asking: another objective is another pixel, more power more counts."""
    found = lambda: microscope.optics_state.detectors["camera"]  # noqa: E731
    pixel = found().pixel_um
    values.set({"objective.slot": 2})
    assert found().pixel_um == pytest.approx(pixel / 2.0, rel=0.05)

    counts = found().expected_counts
    values.set({"laser_488.power": 40.0})
    assert found().expected_counts > counts


def test_what_is_published_is_a_new_copy(values: Values) -> None:
    """What was published is left as it was: a change replaces the whole field."""
    moves, sources = values.move_state.moves, values.source_state.sources
    values.set({"stage.x": 5.0})
    assert values.move_state.moves is not moves
    assert moves["stage"]["x"].current == 0.0
    values.set({"laser_488.power": 1.0})
    assert values.source_state.sources is not sources
    assert sources["laser_488"].power == 20.0


def test_every_variable_is_published_by_what_it_does(values: Values) -> None:
    """Keyed by its cube, and with what changing it was found to do."""
    x = values.move_state.moves["stage"]["x"]
    assert (x.name, x.unit, x.along, x.minimum, x.maximum) == (
        "stage.x",
        "µm",
        "x",
        -50000.0,
        50000.0,
    )
    assert x.does == ["position"]
    objective = values.swap_state.swaps["objective"]["slot"]
    assert (objective.current, objective.label) == (1, "f20 NA 0.25")
    assert objective.options[1].kind == "lens"
    assert "scale" in objective.does
    exposure = values.tune_state.tunes["camera"]["exposure"]
    assert (exposure.current, exposure.unit) == (100.0, "ms")


# --- the actions, which are that one way


@pytest.fixture
def task() -> SimpleNamespace:
    """A task nobody pauses."""
    return SimpleNamespace(pausepoint=lambda: None, progress=lambda *_: None)


def test_the_actions_take_a_variable_by_its_name(values: Values, task: SimpleNamespace) -> None:
    """To a value, or by one; home is where each is described to start."""
    actions.move(values, task, {"stage.x": 10.0, "stage.y": -5.0})  # type: ignore[arg-type]
    actions.move(values, task, {"stage.x": 1.0}, relative=True)  # type: ignore[arg-type]
    assert (values["stage.x"], values["stage.y"]) == pytest.approx((11.0, -5.0))

    actions.move_one(values, task, "stage.z", to=7.0)  # type: ignore[arg-type]
    actions.move_one(values, task, "stage.z", by=1.0)  # type: ignore[arg-type]
    assert values["stage.z"] == pytest.approx(8.0)

    actions.swap(values, "objective.slot", 2)
    assert values["objective.slot"] == 2
    actions.tune(values, "laser_488.power", 3.0)
    assert values["laser_488.power"] == 3.0

    actions.move_home(values, task)  # type: ignore[arg-type]
    assert (values["stage.x"], values["stage.y"], values["stage.z"]) == pytest.approx((0, 0, 0))
    assert values["objective.slot"] == 2  # a swap is no move


@pytest.mark.parametrize("asked", [{}, {"to": 1.0, "by": 1.0}])
def test_moving_one_says_to_or_by(values: Values, task: SimpleNamespace, asked: dict) -> None:
    """One of them, or it cannot tell what is meant."""
    with pytest.raises(ValueError, match="Say either"):
        actions.move_one(values, task, "stage.z", **asked)  # type: ignore[arg-type]


def test_a_source_stops_at_its_max_power(microscope: Microscope) -> None:
    """Whatever its tune states: its tune need not state a max at all."""
    assert microscope.values is not None
    source = next(iter(microscope.source_state.sources.values()))
    assert source.power_variable is not None
    microscope.values.set({source.power_variable: source.max_power * 1000.0})
    assert microscope.values[source.power_variable] == source.max_power


def test_a_driver_of_someone_elses_needs_no_board(tmp_path: Path) -> None:
    """`register_driver` is for what newswitch knows nothing of: it is told what it was wired with."""
    built: dict[str, Any] = {}

    class Elsewhere(Simulated):
        pass

    def factory(variable: Any, options: Any, context: Any) -> Elsewhere:  # noqa: ANN401
        built.update(variable=variable.name, options=dict(options))
        return Elsewhere()

    register_driver("someone.else", factory)
    data = yaml.safe_load((FAKE / "microscope.yml").read_text())
    data.pop("ui", None)
    data["cubes"]["stage"]["moves"]["z"]["actuator"] = "focus-drive"
    wired_only(data, {"focus-drive": {"driver": "someone.else", "gear": 3}})
    data["settings"]["simulate"] = "unwired"
    folder = tmp_path / "instrument"
    shutil.copytree(FAKE, folder)
    (folder / "microscope.yml").write_text(yaml.safe_dump(data))

    microscope = build_microscope(run_settings(tmp_path, simulate="unwired"), spec.load(folder))
    assert built == {"variable": "stage.z", "options": {"gear": 3}}
    assert microscope.values is not None
    assert isinstance(microscope.values.drivers["stage.z"], Elsewhere)


def test_a_driver_that_needs_a_board_says_so(tmp_path: Path) -> None:
    """Rather than failing on the first move."""
    data = yaml.safe_load((FAKE / "microscope.yml").read_text())
    data.pop("ui", None)
    data["cubes"]["stage"]["moves"]["z"]["actuator"] = "focus-drive"
    wired_only(data, {"focus-drive": {"driver": "uc2.stepper", "axis": "Z", "steps_per_um": 3.2}})
    folder = tmp_path / "instrument"
    shutil.copytree(FAKE, folder)
    (folder / "microscope.yml").write_text(yaml.safe_dump(data))

    with pytest.raises(spec.SpecError, match="needs a board"):
        build_microscope(run_settings(tmp_path, simulate="unwired"), spec.load(folder))


def test_what_is_finely_stepped_still_counts_for_a_calibration(tmp_path: Path) -> None:
    """A zoom whose step changes nothing a detector can tell is still a zoom."""
    data = yaml.safe_load((FAKE / "microscope.yml").read_text())
    data.pop("ui", None)
    data.pop("agent_ui", None)
    data["cubes"]["tube_a"]["moves"]["dz"].update(step="1 um", min="-20 mm", max="20 mm")
    folder = tmp_path / "instrument"
    shutil.copytree(FAKE, folder)
    (folder / "microscope.yml").write_text(yaml.safe_dump(data))
    assert "tube_a.dz" in influences(spec.load(folder))["camera_a"]


def test_every_action_that_acquires_holds_what_it_depends_on(tmp_path: Path) -> None:
    """Locks an action states replace those it would have had inferred: nothing may change a
    detector's image size under an array it is filling."""
    registry = create_fastapi_registry(spec.load(FAKE)).registry.snapshot()
    for name in ("acquire", "run_autofocus", "calibrate_light_path", "scan_region"):
        assert "detector" in registry.implementations[name].locks, name
    assert {"motion", "swap", "tune"} <= set(registry.implementations["acquire"].locks)
