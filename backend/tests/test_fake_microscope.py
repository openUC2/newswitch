"""The fake microscope: predictions from what it is made of, and catching what is really there."""

import ast
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from examples.fake_microscope import spec
from examples.fake_microscope.predict import Compiled

HERE = Path(spec.__file__).parent
PREDICTORS = ("spec.py", "optics.py", "compiler.py", "predict.py")


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """The microscope as described."""
    return spec.load()


@pytest.fixture(scope="module")
def compiled(instrument: spec.Instrument, tmp_path_factory: pytest.TempPathFactory) -> Compiled:
    """The microscope compiled, into a file of the test's own."""
    pytest.importorskip("optiland")
    from examples.fake_microscope.compiler import compile_instrument

    path = tmp_path_factory.mktemp("compiled") / "compiled.json"
    return Compiled.load(instrument, compile_instrument(instrument, path))


def changes(compiled: Compiled, variable: str, detector: str = "camera-a") -> dict[str, float]:
    """What nudging `variable` changes for `detector`, as the compiler calculated."""
    return next(
        row["changes"]
        for row in compiled.impacts
        if row["variable"] == variable and row["detector"] == detector
    )


# --- the description


def test_routes_are_found_by_walking_the_edges(instrument: spec.Instrument) -> None:
    """Each detector has its own way from the sample; no route is declared anywhere."""
    routes = instrument.routes(instrument.detection, "stage", "camera-b")
    assert len(routes) == 1
    assert [edge.target for edge in routes[0]][-2:] == ["tube-b", "camera-b"]


def test_an_edge_to_nothing_is_refused(tmp_path: Path) -> None:
    """Everything an edge names has to exist."""
    text = spec.DESCRIPTION.read_text().replace("to: tube-b", "to: nothing")
    bad = tmp_path / "bad.yml"
    bad.write_text(text)
    with pytest.raises(spec.SpecError, match="no cube 'nothing'"):
        spec.load(bad)


def test_a_sensors_size_lives_on_its_axes_and_nowhere_else(instrument: spec.Instrument) -> None:
    """There is no width or height to disagree with the axes."""
    sensor = instrument.cubes["camera-a"].element
    assert sensor is not None
    assert sensor.properties["axes"]["x"]["size"] == 256
    assert not {"width", "height", "sensor_width", "sensor_height"} & set(sensor.properties)


# --- the wall between predictions and the truth


@pytest.mark.parametrize("module", PREDICTORS)
def test_nothing_that_predicts_can_see_the_truth(module: str) -> None:
    """Comparing predictions with images only means something if the two are kept apart."""
    source = (HERE / module).read_text()
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
    assert not {name for name in imported if "hardware" in name or "demo" in name}


def test_the_microscope_side_runs_without_the_optics_library() -> None:
    """Predicting reads a file: optiland is too heavy for a Pi."""
    code = (
        "import sys; import examples.fake_microscope.predict; assert 'optiland' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=HERE.parent.parent)


# --- the optics


def test_the_prescription_is_the_lens_it_says_it_is() -> None:
    """Loaded from its file: a typed-in radius once made this lens f = 135."""
    pytest.importorskip("optiland")
    from optiland.fileio import load_optiland_file

    lens = load_optiland_file(str(HERE / "lenses" / "AC254-100-A.optiland"))
    assert float(lens.paraxial.f2()) == pytest.approx(100.0, abs=0.2)


def test_magnification_comes_from_the_pair_of_lenses(instrument: spec.Instrument) -> None:
    """Tube over objective, inverted: and each detector has its own tube lens."""
    pytest.importorskip("optiland")
    from examples.fake_microscope.optics import imaging

    state = instrument.initial_state()
    assert imaging(instrument, "camera-a", state, 525.0).magnification == pytest.approx(
        -2.0, abs=0.01
    )
    assert imaging(instrument, "camera-b", state, 525.0).magnification == pytest.approx(
        -4.0, abs=1e-6
    )
    swapped = {**state, "objective.slot": 2}
    assert imaging(instrument, "camera-b", swapped, 525.0).magnification == pytest.approx(
        -8.0, abs=1e-6
    )


def test_a_reflection_is_counted_along_the_route(instrument: spec.Instrument) -> None:
    """Camera b sits behind the splitter's reflection, camera a behind its transmission."""
    pytest.importorskip("optiland")
    from examples.fake_microscope.optics import imaging

    state = instrument.initial_state()
    assert imaging(instrument, "camera-a", state, 525.0).reflections == 0
    assert imaging(instrument, "camera-b", state, 525.0).reflections == 1


def test_the_tube_lens_aperture_darkens_the_corners_it_clips(instrument: spec.Instrument) -> None:
    """A prediction nobody declared: only the camera behind the real lens's aperture is affected."""
    pytest.importorskip("optiland")
    from examples.fake_microscope.optics import imaging

    state = instrument.initial_state()
    assert imaging(instrument, "camera-a", state, 525.0).relative_illumination < 0.95
    assert imaging(instrument, "camera-b", state, 525.0).relative_illumination == pytest.approx(1.0)


def test_a_source_blocked_by_the_filter_reaches_nothing(instrument: spec.Instrument) -> None:
    """Red light through a green filter: a black image, known before taking it."""
    from examples.fake_microscope.optics import coupling

    state = {**instrument.initial_state(), "filter-wheel.slot": 2}
    arriving = coupling(instrument, "camera-a", state)
    assert arriving["led-625"]["light_per_mw"] < 1e-6
    assert arriving["laser-488"]["light_per_mw"] > 0.001


def test_the_dichroic_keeps_the_laser_from_the_camera(instrument: spec.Instrument) -> None:
    """What arrives from the laser is the sample's emission, not the laser."""
    from examples.fake_microscope.optics import coupling

    arriving = coupling(instrument, "camera-a", instrument.initial_state())
    assert arriving["laser-488"]["band_mean_nm"] == pytest.approx(515.0, abs=5.0)


# --- what impacts what: calculated


def test_moving_the_stage_sideways_only_moves_the_image(compiled: Compiled) -> None:
    """The calibration still holds: position is all that changed."""
    assert set(changes(compiled, "stage.x")) == {"position"}


def test_focus_blurs_but_does_not_rescale(compiled: Compiled) -> None:
    """With the stop at the objective's back focal plane, z does not touch the pixel size."""
    assert set(changes(compiled, "stage.z")) == {"blur"}


def test_moving_the_tube_lens_changes_both_and_only_for_its_own_camera(compiled: Compiled) -> None:
    """Nothing declared this; the size is what makes it useful."""
    assert set(changes(compiled, "tube-a.dz", "camera-a")) == {"scale", "blur"}
    assert changes(compiled, "tube-a.dz", "camera-b") == {}


def test_swapping_the_objective_changes_the_scale(compiled: Compiled) -> None:
    """So a calibration of one objective does not hold for the other."""
    assert "scale" in changes(compiled, "objective.slot")


def test_swapping_the_filter_changes_the_light_and_not_the_geometry(compiled: Compiled) -> None:
    """As far as the model knows: it has no notion of a wedge, which the hardware has."""
    found = changes(compiled, "filter-wheel.slot")
    assert "light" in found
    assert not {"scale", "position", "blur"} & set(found)


def test_binning_makes_other_pixels_and_nothing_else_about_the_optics(compiled: Compiled) -> None:
    """It needs no calibration of its own."""
    found = changes(compiled, "camera-a.binning")
    assert "pixels" in found
    assert "scale" not in found


def test_tuning_one_camera_leaves_the_other_alone(compiled: Compiled) -> None:
    """Exposure is a matter of one detector."""
    assert "light" in changes(compiled, "camera-a.exposure", "camera-a")
    assert changes(compiled, "camera-a.exposure", "camera-b") == {}


# --- the table


def test_the_table_answers_what_a_trace_would(
    instrument: spec.Instrument, compiled: Compiled
) -> None:
    """What the microscope reads is what the tracer found."""
    from examples.fake_microscope.compiler import traced_answer

    state = {**instrument.initial_state(), "objective.slot": 2, "filter-wheel.slot": 2}
    for detector in instrument.detectors():
        assert np.allclose(
            compiled.answer(detector, state).pixel_to_stage,
            traced_answer(instrument, detector, state).pixel_to_stage,
        )


def test_the_table_follows_a_move_along_the_axis(
    instrument: spec.Instrument, compiled: Compiled
) -> None:
    """Scale and blur through the sensitivities, close to tracing it."""
    from examples.fake_microscope.compiler import traced_answer

    state = {**instrument.initial_state(), "tube-a.dz": 500.0}
    table = compiled.answer("camera-a", state)
    traced = traced_answer(instrument, "camera-a", state)
    assert table.pixel_to_stage[0][0] == pytest.approx(traced.pixel_to_stage[0][0], rel=1e-3)
    assert table.spot_px == pytest.approx(traced.spot_px, rel=0.1)


# --- the loop


@pytest.fixture(scope="module")
def microscope(instrument: spec.Instrument):  # noqa: ANN201 - only importable with optiland
    """The fake hardware, with its hidden errors."""
    pytest.importorskip("optiland")
    from examples.fake_microscope.hardware import FakeMicroscope

    return FakeMicroscope(instrument)


@pytest.mark.parametrize(
    ("detector", "nominal", "turn"), [("camera-a", 4.9978, 1.5), ("camera-b", 2.5, -0.7)]
)
def test_the_images_reveal_what_the_description_does_not_say(
    microscope,  # noqa: ANN001
    detector: str,
    nominal: float,
    turn: float,  # noqa: ANN001
) -> None:
    """A 2% scale error and a turned camera, found from the images alone."""
    from examples.fake_microscope.demo import measure

    microscope.set({"filter-wheel.slot": 1})
    size, measured_turn = measure(microscope, detector)
    assert size == pytest.approx(nominal * 1.02, rel=0.01)
    assert measured_turn == pytest.approx(turn, abs=0.1)


def test_the_filter_wedge_is_an_effect_the_model_has_no_notion_of(microscope, compiled) -> None:  # noqa: ANN001
    """The design says nothing moves, and the images say otherwise: it can tell the two apart."""
    from newswitch.routines.affine_matrix import pixel_shift

    assert "position" not in changes(compiled, "filter-wheel.slot")
    microscope.set({"filter-wheel.slot": 1})
    before = microscope.image("camera-a")
    microscope.set({"filter-wheel.slot": 2})
    after = microscope.image("camera-a")
    microscope.set({"filter-wheel.slot": 1})
    assert pixel_shift(before, after) == pytest.approx((3.0, -2.0), abs=0.2)


def test_a_predicted_black_image_is_black(microscope, compiled) -> None:  # noqa: ANN001
    """Red light through a green filter, on both sides of the wall."""
    microscope.set({"filter-wheel.slot": 2, "laser-488.power": 0.0, "led-625.power": 2.0})
    assert compiled.answer("camera-a", microscope.state).black
    assert np.mean(microscope.image("camera-a")) < 101.0
    microscope.set({"filter-wheel.slot": 1, "laser-488.power": 20.0, "led-625.power": 0.0})
