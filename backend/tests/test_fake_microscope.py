"""The fake microscope: predictions from what it is made of, and catching what is really there."""

import ast
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from newswitch.instrument import spec
from newswitch.instrument.compiler import compile_instrument, impacts
from newswitch.instrument.predict import Compiled

BACKEND = Path(__file__).parent.parent
INSTRUMENT = BACKEND / "instruments" / "fake-microscope"
PREDICTORS = ("spec.py", "tracing.py", "compiler.py", "predict.py", "parts.py", "roles.py")


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """The microscope as described."""
    return spec.load(INSTRUMENT)


@pytest.fixture(scope="module")
def compiled(instrument: spec.Instrument) -> Compiled:
    """What is compiled for the microscope, as a server does when it starts."""
    return compile_instrument(instrument)


def changes(compiled: Compiled, variable: str, detector: str = "camera_a") -> dict[str, float]:
    """What nudging `variable` changes for `detector`, as the compiler calculated."""
    return next(
        row["changes"]
        for row in impacts(compiled.instrument, compiled.instrument.initial_state())
        if row["variable"] == variable and row["detector"] == detector
    )


# --- the description


def test_routes_are_found_by_walking_the_edges(instrument: spec.Instrument) -> None:
    """Each detector has its own way from the sample; no route is declared anywhere."""
    routes = instrument.routes(instrument.detection, "stage", "camera_b")
    assert len(routes) == 1
    assert [edge.target for edge in routes[0]][-2:] == ["tube_b", "camera_b"]


def test_an_edge_to_nothing_is_refused(tmp_path: Path) -> None:
    """Everything an edge names has to exist."""
    data = yaml.safe_load((INSTRUMENT / spec.DESCRIPTION).read_text())
    data.pop("ui", None)
    data.pop("agent_ui", None)
    edge = next(edge for edge in data["detection"] if edge["to"] == "tube_b")
    edge["to"] = "nothing"
    text = yaml.safe_dump(data)
    bad = tmp_path / "bad.yml"
    bad.write_text(text)
    with pytest.raises(spec.SpecError, match="no cube 'nothing'"):
        spec.load(bad)


def test_a_sensors_size_lives_on_its_axes_and_nowhere_else(instrument: spec.Instrument) -> None:
    """There is no width or height to disagree with the axes."""
    sensor = instrument.cubes["camera_a"].element
    assert sensor is not None
    assert sensor.axes["x"].size == 512
    assert not {"width", "height", "sensor_width", "sensor_height"} & set(vars(sensor))


# --- the wall between predictions and the truth


@pytest.mark.parametrize("module", PREDICTORS)
def test_nothing_that_predicts_can_see_the_truth(module: str) -> None:
    """Comparing predictions with images only means something if the two are kept apart."""
    source = (BACKEND / "newswitch" / "instrument" / module).read_text()
    assert "truth.yml" not in source
    imported = {
        name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
    }
    assert not {name for name in imported if "drivers" in name or "check_instrument" in name}


# --- the optics


def test_the_prescription_is_the_lens_it_says_it_is() -> None:
    """Loaded from its file: a typed-in radius once made this lens f = 135."""
    from optiland.fileio import load_optiland_file

    lens = load_optiland_file(str(INSTRUMENT / "lenses" / "AC254-100-A.optiland"))
    assert float(lens.paraxial.f2()) == pytest.approx(100.0, abs=0.2)


def test_magnification_comes_from_the_pair_of_lenses(instrument: spec.Instrument) -> None:
    """Tube over objective, inverted: and each detector has its own tube lens."""
    from newswitch.instrument.tracing import imaging

    state = instrument.initial_state()
    assert imaging(instrument, "camera_a", state, 525.0).magnification == pytest.approx(
        -2.0, abs=0.01
    )
    assert imaging(instrument, "camera_b", state, 525.0).magnification == pytest.approx(
        -4.0, abs=1e-6
    )
    swapped = {**state, "objective.slot": 2}
    assert imaging(instrument, "camera_b", swapped, 525.0).magnification == pytest.approx(
        -8.0, abs=1e-6
    )


def test_a_reflection_is_counted_along_the_route(instrument: spec.Instrument) -> None:
    """Camera b sits behind the splitter's reflection, camera a behind its transmission."""
    from newswitch.instrument.tracing import imaging

    state = instrument.initial_state()
    assert imaging(instrument, "camera_a", state, 525.0).reflections == 0
    assert imaging(instrument, "camera_b", state, 525.0).reflections == 1


def test_the_tube_lens_aperture_darkens_the_corners_it_clips(instrument: spec.Instrument) -> None:
    """A prediction nobody declared: only the camera behind the real lens's aperture is affected."""
    from newswitch.instrument.tracing import imaging

    state = instrument.initial_state()
    assert imaging(instrument, "camera_a", state, 525.0).relative_illumination < 0.95
    assert imaging(instrument, "camera_b", state, 525.0).relative_illumination == pytest.approx(1.0)


def test_a_source_blocked_by_the_filter_reaches_nothing(instrument: spec.Instrument) -> None:
    """Red light through a green filter: a black image, known before taking it. So the red light
    reaches camera_a only through the open slot: a channel of its own, which the wheel decides."""
    state = {
        **instrument.initial_state(),
        "filter_wheel.slot": 2,
        "laser_488.power": 0.0,
        "led_625.power": instrument.cubes["led_625"].element.max_power,
    }
    table = compile_instrument(instrument)
    assert table.answer("camera_a", state).black
    found = {(c.source, c.detector): dict(c.swaps) for c in table.channels(state)}
    assert found[("led_625", "camera_a")] == {"filter_wheel.slot": 1}
    assert ("laser_488", "camera_a") in found


def test_the_dichroic_keeps_the_laser_from_the_camera(
    instrument: spec.Instrument, compiled: Compiled
) -> None:
    """The laser's channel is of what is emitted, not of the laser: so the design says, and what
    arrives on the simulated beads is their emission."""
    from newswitch.simulation import light

    [laser] = [
        c
        for c in compiled.channels(instrument.initial_state())
        if c.source == "laser_488" and c.detector == "camera_a"
    ]
    assert laser.kind == "emitted"
    arriving = light.traced(instrument, "camera_a", instrument.initial_state())
    assert arriving["laser_488"]["band_mean_nm"] == pytest.approx(515.0, abs=5.0)


# --- what impacts what: calculated


def test_moving_the_stage_sideways_only_moves_the_image(compiled: Compiled) -> None:
    """The calibration still holds: position is all that changed."""
    assert set(changes(compiled, "stage.x")) == {"position"}


def test_focus_blurs_but_does_not_rescale(compiled: Compiled) -> None:
    """With the stop at the objective's back focal plane, z does not touch the pixel size."""
    assert set(changes(compiled, "stage.z")) == {"blur"}


def test_moving_the_tube_lens_changes_both_and_only_for_its_own_camera(compiled: Compiled) -> None:
    """Nothing declared this; the size is what makes it useful."""
    assert set(changes(compiled, "tube_a.dz", "camera_a")) == {"scale", "blur", "light"}
    assert changes(compiled, "tube_a.dz", "camera_b") == {}


def test_swapping_the_objective_changes_the_scale(compiled: Compiled) -> None:
    """So a calibration of one objective does not hold for the other."""
    assert "scale" in changes(compiled, "objective.slot")


def test_swapping_the_filter_changes_the_light_and_not_the_geometry(compiled: Compiled) -> None:
    """As far as the model knows: it has no notion of a wedge, which the hardware has."""
    found = changes(compiled, "filter_wheel.slot")
    assert "light" in found
    assert not {"scale", "position", "blur"} & set(found)


def test_binning_makes_other_pixels_and_nothing_else_about_the_optics(compiled: Compiled) -> None:
    """It needs no calibration of its own."""
    found = changes(compiled, "camera_a.binning")
    assert "pixels" in found
    assert "scale" not in found


def test_tuning_one_camera_leaves_the_other_alone(compiled: Compiled) -> None:
    """Exposure is a matter of one detector."""
    assert "light" in changes(compiled, "camera_a.exposure", "camera_a")
    assert changes(compiled, "camera_a.exposure", "camera_b") == {}


def test_the_table_answers_what_a_trace_would(
    instrument: spec.Instrument, compiled: Compiled
) -> None:
    """What the microscope reads is what the tracer found."""
    from newswitch.instrument.compiler import traced_answer

    state = {**instrument.initial_state(), "objective.slot": 2, "filter_wheel.slot": 2}
    for detector in instrument.detectors():
        assert np.allclose(
            compiled.answer(detector, state).pixel_to_stage,
            traced_answer(instrument, detector, state).pixel_to_stage,
        )


def test_the_table_follows_a_move_along_the_axis(
    instrument: spec.Instrument, compiled: Compiled
) -> None:
    """Scale and blur through the sensitivities, close to tracing it."""
    from newswitch.instrument.compiler import traced_answer

    state = {**instrument.initial_state(), "tube_a.dz": 500.0}
    table = compiled.answer("camera_a", state)
    traced = traced_answer(instrument, "camera_a", state)
    assert table.pixel_to_stage[0][0] == pytest.approx(traced.pixel_to_stage[0][0], rel=1e-3)
    assert table.spot_px == pytest.approx(traced.spot_px, rel=0.1)


# --- the loop


@pytest.fixture(scope="module")
def microscope(instrument: spec.Instrument):  # noqa: ANN201
    """The fake hardware, with its hidden errors."""
    from newswitch.simulation.simulator import SimulatedMicroscope

    return SimulatedMicroscope(instrument)


@pytest.mark.parametrize(
    ("detector", "nominal", "turn"), [("camera_a", 4.9978, 1.5), ("camera_b", 2.5, -0.7)]
)
def test_the_images_reveal_what_the_description_does_not_say(
    microscope,  # noqa: ANN001
    detector: str,
    nominal: float,
    turn: float,  # noqa: ANN001
) -> None:
    """A 2% scale error and a turned camera, found from the images alone."""
    from newswitch.tools.check_instrument import measure

    microscope.set({"filter_wheel.slot": 1})
    size, measured_turn = measure(microscope, detector)
    assert size == pytest.approx(nominal * 1.02, rel=0.01)
    assert measured_turn == pytest.approx(turn, abs=0.1)


def test_the_filter_wedge_is_an_effect_the_model_has_no_notion_of(microscope, compiled) -> None:  # noqa: ANN001
    """The design says nothing moves, and the images say otherwise: it can tell the two apart."""
    from newswitch.calibration.affine import pixel_shift

    assert "position" not in changes(compiled, "filter_wheel.slot")
    microscope.set({"filter_wheel.slot": 1})
    before = microscope.image("camera_a")
    microscope.set({"filter_wheel.slot": 2})
    after = microscope.image("camera_a")
    microscope.set({"filter_wheel.slot": 1})
    assert pixel_shift(before, after) == pytest.approx((3.0, -2.0), abs=0.2)


def test_a_predicted_black_image_is_black(microscope, compiled) -> None:  # noqa: ANN001
    """Red light through a green filter, on both sides of the wall."""
    microscope.set({"filter_wheel.slot": 2, "laser_488.power": 0.0, "led_625.power": 2.0})
    assert compiled.answer("camera_a", microscope.state).black
    assert np.mean(microscope.image("camera_a")) < 101.0
    microscope.set({"filter_wheel.slot": 1, "laser_488.power": 20.0, "led_625.power": 0.0})


def test_compiling_writes_nothing(tmp_path: Path) -> None:
    """A server works it out when it starts, and a folder stays what its author wrote."""
    copy = tmp_path / "instrument"
    shutil.copytree(INSTRUMENT, copy)
    before = sorted(path.name for path in copy.rglob("*"))
    compile_instrument(spec.load(copy))
    assert sorted(path.name for path in copy.rglob("*")) == before


def test_a_changed_description_only_takes_loading_it_again(tmp_path: Path) -> None:
    """There is no table that could be about another microscope."""
    copy = tmp_path / "instrument"
    shutil.copytree(INSTRUMENT, copy)
    state = spec.load(copy).initial_state()
    before = compile_instrument(spec.load(copy)).answer("camera_b", state).pixel_to_stage[0][0]
    description = copy / spec.DESCRIPTION
    description.write_text(description.read_text().replace("f: 200 mm", "f: 100 mm"))
    after = compile_instrument(spec.load(copy)).answer("camera_b", state).pixel_to_stage[0][0]
    assert abs(after) > abs(before)
