"""What the optics find is published, and a calibration depends on what they find changes a pixel."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from newswitch.instrument import spec
from newswitch.instrument.compiler import difference, influences
from newswitch.instrument.predict import Answer
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.devices import AxisWindow
from newswitch.models.light_path import CalibratedLightPath
from newswitch.models.optics import DetectorOptics
from newswitch.routines.autofocus import autofocus_sweep
from newswitch.routines.common import focus_range, z_sweep
from newswitch.services.stage import stage_of
from newswitch.settings import Settings
from tests.conftest import run_settings

INSTRUMENTS = Path(__file__).parent.parent / "instruments"


def built(tmp_path: Path, name: str) -> Microscope:
    """A running microscope of the instrument `name`."""
    settings: Settings = run_settings(tmp_path)
    return build_microscope(settings, spec.load(INSTRUMENTS / name))


def first_detector(microscope: Microscope) -> DetectorOptics:
    """What is published for its first detector."""
    return next(iter(microscope.optics_state.detectors.values()))


def test_each_detector_has_its_own_facts(tmp_path: Path) -> None:
    """From the optics in front of each, not from a number written down anywhere."""
    optics = built(tmp_path, "dual-camera").optics_state
    assert set(optics.detectors) == {"camera_green", "camera_red"}
    green = optics.detectors["camera_green"]
    assert green.calibrated is False
    assert green.pixel_um > 0.0
    assert green.field_width_um == pytest.approx(green.pixel_um * 512, rel=0.01)
    assert {channel.detector for channel in optics.channels} == set(optics.detectors)


def test_the_light_paths_are_the_edges_the_description_states(tmp_path: Path) -> None:
    """What is on the way is what is drawn there: a scanner and a pinhole need no new type."""
    path = built(tmp_path, "point-scanner").optics_state.detectors["pmt"].path
    assert {"scanner", "pinhole"} <= {element.kind for element in path.elements}
    names = {element.name for element in path.elements}
    assert {cube for edge in path.edges for cube in (edge.source, edge.target)} == names


def test_a_sheet_is_not_a_field(tmp_path: Path) -> None:
    """How a source's light lands is found from its way there."""
    sheet = next(iter(built(tmp_path, "light-sheet").optics_state.sources.values()))
    assert (sheet.shape, sheet.side) == ("sheet", "orthogonal")
    assert sheet.thickness_um is not None and sheet.reach_um is not None
    assert sheet.along in {"x", "y"}
    field = next(iter(built(tmp_path, "dual-camera").optics_state.sources.values()))
    assert field.shape == "field"
    assert field.field_um is not None


def test_a_scanned_source_is_a_spot(tmp_path: Path) -> None:
    """All of it, on one pixel at a time."""
    assert (
        next(iter(built(tmp_path, "point-scanner").optics_state.sources.values())).shape == "spot"
    )


def test_what_changes_is_published_at_once(microscope: Microscope) -> None:
    """Another objective is another pixel; no one has to ask."""
    assert microscope.values is not None
    before = first_detector(microscope).pixel_um
    microscope.values.set({"objective.slot": 2})
    assert first_detector(microscope).pixel_um != pytest.approx(before, rel=0.1)


def test_more_power_is_published_as_more_counts(microscope: Microscope) -> None:
    """Expected counts follow the sources."""
    assert microscope.values is not None
    microscope.values.set({"laser_488.power": 5.0})
    dim = first_detector(microscope).expected_counts
    microscope.values.set({"laser_488.power": 40.0})
    assert first_detector(microscope).expected_counts > dim


def test_what_did_not_change_is_not_published_again(microscope: Microscope) -> None:
    """Exposure changes the counts, and leaves the sources and their channels' shape alone."""
    assert microscope.values is not None
    sources = microscope.optics_state.sources
    detectors = microscope.optics_state.detectors
    microscope.optics.refresh()
    assert microscope.optics_state.detectors is detectors
    microscope.values.set({"camera.exposure": 50.0})
    assert microscope.optics_state.detectors is not detectors
    assert microscope.optics_state.sources is sources


def test_a_calibration_is_published_over_the_prediction(microscope: Microscope) -> None:
    """Measured beats predicted, for as long as what it depends on holds."""
    path = microscope.optics.get_light_path_for_detector("camera")
    microscope.calibration.set_calibrated_state(
        CalibratedLightPath(
            key=microscope.optics.snapshot(path).key,
            affine_matrix=[
                [0.5, 0.0, 0.0, 0.0],
                [0.0, 0.5, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
        )
    )
    found = first_detector(microscope)
    assert (found.calibrated, found.pixel_um) == (True, 0.5)


def test_a_window_keeps_its_calibration(microscope: Microscope) -> None:
    """Reading out part of the sensor does not change where a pixel looks: the measurement holds."""
    assert microscope.detector is not None
    path = microscope.optics.get_light_path_for_detector("camera")
    microscope.calibration.set_calibrated_state(
        CalibratedLightPath(
            key=microscope.optics.snapshot(path).key,
            affine_matrix=[
                [0.5, 0.0, 0.0, 0.0],
                [0.0, 0.5, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
        )
    )
    assert first_detector(microscope).calibrated
    microscope.detector.update_detector(
        "camera", windows=[AxisWindow("x", 0, 100), AxisWindow("y", 0, 100)]
    )
    assert first_detector(microscope).calibrated


def test_what_a_calibration_depends_on_is_measured() -> None:
    """Scale-changing variables are found per detector; moving, filtering and exposing are not."""
    found = influences(spec.load(INSTRUMENTS / "fake-microscope"))
    assert {"objective.slot", "tube_a.dz", "camera_a.binning"} <= found["camera_a"]
    assert "tube_a.dz" not in found["camera_b"]
    for variable in ("stage.x", "stage.y", "stage.z", "camera_a.exposure", "laser_488.power"):
        assert variable not in found["camera_a"]


def answer(pixel_to_stage: tuple[tuple[float, float], tuple[float, float]]) -> Answer:
    """An answer with only a map, for what compares maps."""
    return Answer(
        detector="d",
        pixel_to_stage=pixel_to_stage,
        centre=(0.0, 0.0),
        size=(512, 512),
        field_of_view_um=(1.0, 1.0),
        spot_px=0.0,
        relative_illumination=1.0,
        distortion_percent=0.0,
        band_nm=None,
        light=0.0,
    )


def test_a_camera_turned_a_quarter_can_be_compared() -> None:
    """Its map's diagonal is zero, which is no reason to divide by it."""
    turned = answer(((0.0, -1.0), (1.0, 0.0)))
    assert difference(turned, turned) == {}


def test_a_flip_of_the_image_is_a_change_of_its_map() -> None:
    """Though every pixel stays the same size."""
    plain = answer(((1.0, 0.0), (0.0, 1.0)))
    assert "scale" in difference(plain, replace(plain, pixel_to_stage=((-1.0, 0.0), (0.0, 1.0))))


def test_how_far_to_sweep_follows_from_the_na(tmp_path: Path) -> None:
    """Half a depth of field apart: a low NA sweeps far, a high one barely."""
    assert focus_range(8.0, 11) == pytest.approx(40.0)
    assert focus_range(0.4, 11) == pytest.approx(2.0)
    found = next(iter(built(tmp_path, "dual-camera").optics_state.detectors.values()))
    assert found.depth_of_field_um == pytest.approx(0.525 / 0.25**2, rel=0.1)


def test_a_low_na_sweep_reaches_focus_from_where_a_fixed_one_could_not(
    microscope: Microscope,
) -> None:
    """Two depths of field off: what the NA asks for finds it, and 20 um would only walk towards it."""
    assert microscope.values is not None and microscope.detector is not None
    values = microscope.values
    sources = list(microscope.source_state.sources.values())
    values.set({source.power_variable: 0.0 for source in sources})
    values.set({sources[0].power_variable: sources[0].max_power * 0.5})
    values.set({"objective.slot": microscope.swap_state.swaps["objective"]["slot"].options[0].slot})
    depth = microscope.optics.depth_of_field_um("camera")
    stage = stage_of(values, "camera")

    stage.move(z=2.0 * depth, is_absolute=True)
    sweep = z_sweep(stage.state.z, focus_range(depth, 11), 11)
    best, _ = autofocus_sweep(stage, microscope.detector, sweep)
    assert abs(best) <= depth / 2.0

    stage.move(z=2.0 * depth, is_absolute=True)
    best, _ = autofocus_sweep(stage, microscope.detector, z_sweep(2.0 * depth, 20.0, 11))
    assert abs(best) > depth / 2.0


def test_defocus_counts_from_where_focus_was_found(tmp_path: Path) -> None:
    """Not from zero, which is only where a stage happens to start."""
    microscope = built(tmp_path, "dual-camera")
    assert microscope.values is not None
    microscope.values.set({"stage.z": 12.0})
    assert first_detector(microscope).defocus_um == pytest.approx(12.0)
    microscope.optics.found_focus("camera_green")
    assert first_detector(microscope).defocus_um == pytest.approx(0.0)
    microscope.values.set({"stage.z": 10.0})
    assert first_detector(microscope).defocus_um == pytest.approx(-2.0)


def test_a_sheet_says_how_strong_it_is_at_the_edge(tmp_path: Path) -> None:
    """What a view used to have written in, for one lens."""
    optics = built(tmp_path, "light-sheet").optics_state
    sheet = next(iter(optics.sources.values()))
    assert sheet.reach_um is not None and sheet.edge_share is not None
    half = next(iter(optics.detectors.values())).field_width_um / 2.0
    assert sheet.edge_share == pytest.approx((1.0 + (half / sheet.reach_um) ** 2) ** -0.5, rel=0.02)


def test_what_a_source_makes_arrive_has_its_colour(tmp_path: Path) -> None:
    """From one function, and from what arrives, not from guessing a dye by a wavelength."""
    microscope = built(tmp_path, "dual-camera")
    laser = microscope.optics_state.sources["laser_488"]
    assert laser.band_nm is not None and laser.band_color is not None
    assert microscope.source_state.sources["laser_488"].color == "cyan"
    assert microscope.source_state.sources["led_625"].color == "red"


def test_a_view_reads_any_element_by_its_cube(tmp_path: Path) -> None:
    """What is in it now, under keys it can name."""
    elements = built(tmp_path, "point-scanner").optics_state.elements
    kinds = {element.kind: element for element in elements.values()}
    assert "per_step" in kinds["scanner"].facts and "diameter" in kinds["pinhole"].facts


def test_a_view_can_be_a_file_of_its_own(tmp_path: Path) -> None:
    """Named, so that nothing is found by what it is called."""
    (tmp_path / "shared.bsx").write_text(
        '<Blok kind="agent" context="panel" catalog="newswitch"></Blok>\n'
    )
    (tmp_path / "i").mkdir()
    description = (INSTRUMENTS / "cam-test" / "microscope.yml").read_text()
    data = yaml.safe_load(description)
    data["ui"]["bloks"] = {"view-shared": {"file": "../shared.bsx", "description": "Shared: it."}}
    (tmp_path / "i" / "microscope.yml").write_text(yaml.safe_dump(data))
    assert (
        spec.load(tmp_path / "i").ui.bloks["view-shared"].bsx
        == '<Blok kind="agent" context="panel" catalog="newswitch"></Blok>\n'
    )

    data["ui"]["bloks"]["view-shared"]["file"] = "../gone.bsx"
    (tmp_path / "i" / "microscope.yml").write_text(yaml.safe_dump(data))
    with pytest.raises(spec.SpecError, match="gone.bsx does not exist"):
        spec.load(tmp_path / "i")

    data["ui"]["bloks"]["view-shared"] = {
        "file": "../shared.bsx",
        "bsx": '<Blok kind="agent" context="panel"></Blok>',
    }
    (tmp_path / "i" / "microscope.yml").write_text(yaml.safe_dump(data))
    with pytest.raises(spec.SpecError, match="not both"):
        spec.load(tmp_path / "i")
