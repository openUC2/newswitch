"""A point scanner: a detector whose image a scan makes, predicted and measured."""

import dataclasses
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from arkitekt import Task

from newswitch.drivers.simulator import SimulatedMicroscope
from newswitch.instrument.roles import Roles
from newswitch.microscope.parts import build_microscope
from newswitch.models.acquisition import AcquisitionChannel
from newswitch.routines.acquire import acquire as run_plan
from newswitch.routines.autofocus import run_autofocus
from newswitch.states.autofocus import AutofocusState
from tests.conftest import acquisition, run_settings
from tests.test_acquire import RecordingStore
from newswitch.instrument import parts, spec
from newswitch.instrument.compiler import compile_instrument
from newswitch.instrument.tracing import scan_um_per_degree
from newswitch.tools.check_instrument import measure

INSTRUMENT = Path(__file__).parent.parent / "instruments" / "point-scanner"


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """The point scanner as described."""
    return spec.load(INSTRUMENT)


def lit(instrument: spec.Instrument) -> dict[str, float]:
    """Its state with the laser on."""
    return {**instrument.initial_state(), "laser_488.power": 1.0}


def test_the_scan_is_what_the_lenses_make_of_an_angle(instrument: spec.Instrument) -> None:
    """Objective focal length x scan lens / tube lens, per degree, and a relay inverts."""
    expected = 20_000.0 * 50.0 / 200.0 * math.pi / 180.0
    scale = scan_um_per_degree(instrument, "galvo", instrument.initial_state())
    assert scale == pytest.approx(-expected)


def test_the_scan_makes_the_detectors_axes(instrument: spec.Instrument) -> None:
    """The point detector has no size of its own: its y and x are the scan's."""
    y, x = instrument.detector_axes("pmt")
    assert (y.name, y.size, y.step, y.delivered_by) == ("y", 512, 0.02, "galvo")
    assert (x.name, x.size, x.step, x.delivered_by) == ("x", 512, 0.02, "galvo")


def test_the_pixel_size_and_field_are_predicted(instrument: spec.Instrument) -> None:
    """A step of the scan on the sample, and as many of them as there are."""
    answer = compile_instrument(instrument).answer("pmt", lit(instrument))
    pixel = 0.02 * 20_000.0 * 0.25 * math.pi / 180.0
    assert abs(answer.pixel_to_stage[0][0]) == pytest.approx(pixel)
    assert abs(answer.pixel_to_stage[1][1]) == pytest.approx(pixel)
    assert answer.size == (512, 512)
    assert answer.field_of_view_um[0] == pytest.approx(pixel * 512)


def test_the_spot_is_the_objectives_diffraction_limit_in_pixels(
    instrument: spec.Instrument,
) -> None:
    """On the sample, against a pixel on the sample: no lens but the objective's NA counts."""
    answer = compile_instrument(instrument).answer("pmt", lit(instrument))
    airy = 0.61 * answer.band_nm / 1000.0 / 0.25
    assert answer.spot_px == pytest.approx(airy / 3.0 / abs(answer.pixel_to_stage[0][0]))


def test_a_shorter_objective_scans_a_smaller_field(tmp_path: Path) -> None:
    """The scale follows the optics, with nothing else said."""
    data = yaml.safe_load((INSTRUMENT / spec.DESCRIPTION).read_text())
    data["cubes"]["objective"]["element"]["f"] = "10 mm"
    data["illumination"][4]["distance"] = "210 mm"
    path = tmp_path / spec.DESCRIPTION
    path.write_text(yaml.safe_dump(data))
    scale = scan_um_per_degree(spec.load(path), "galvo", spec.load(path).initial_state())
    assert scale == pytest.approx(-10_000.0 * 0.25 * math.pi / 180.0)


def test_the_channels_are_found_through_the_scan_and_the_pinhole(
    instrument: spec.Instrument,
) -> None:
    """Neither of them is in the way of the light."""
    channels = compile_instrument(instrument).channels(instrument.initial_state())
    assert [(channel.source, channel.detector) for channel in channels] == [("laser_488", "pmt")]


def test_calibrating_on_scanned_images_finds_the_predicted_pixel(
    instrument: spec.Instrument,
) -> None:
    """newswitch's own calibration arithmetic works on a scan like on a camera's image."""
    microscope = SimulatedMicroscope(instrument)
    microscope.set({"laser_488.power": 1.0})
    measured, turned = measure(microscope, "pmt")
    predicted = abs(
        compile_instrument(instrument).answer("pmt", microscope.state).pixel_to_stage[0][0]
    )
    assert measured == pytest.approx(predicted, rel=0.02)
    assert abs(turned) < 1.0


def test_a_thin_section_out_of_focus_blurs(instrument: spec.Instrument) -> None:
    """Geometrically, by the objective's NA, from its nearest part: FLIM scans such a section."""
    section = spec.load(Path(__file__).parent.parent / "instruments" / "flim")
    table = compile_instrument(section)
    state = {**section.initial_state(), "laser_488.power": 1.0}
    focused = table.answer("spad", state)
    moved = table.answer("spad", {**state, "stage.z": 100.0})
    pixel = abs(focused.pixel_to_stage[0][0])
    assert moved.spot_px == pytest.approx(
        math.hypot(focused.spot_px, 98.0 * 0.25 / pixel), rel=1e-3
    )
    assert moved.light == focused.light


def test_in_a_volume_the_stage_moves_through_it(instrument: spec.Instrument) -> None:
    """The spot sections it: a move is another plane, just as sharp, and so no focus."""
    assert sorted(Roles(instrument).found["pmt"]["stage.z"]) == []
    assert Roles(instrument).focuses("pmt") == []
    table = compile_instrument(instrument)
    focused = table.answer("pmt", lit(instrument))
    moved = table.answer("pmt", {**lit(instrument), "stage.z": 50.0})
    assert moved.spot_px == pytest.approx(focused.spot_px)
    simulator = SimulatedMicroscope(instrument)
    simulator.set({"laser_488.power": 10.0})
    here = simulator.image("pmt").astype(float)
    simulator.set({"stage.z": 50.0})
    there = simulator.image("pmt").astype(float)
    assert np.corrcoef(here.ravel(), there.ravel())[0, 1] < 0.3


def test_autofocus_says_a_volume_has_nothing_to_focus_with(
    tmp_path: Path, instrument: spec.Instrument
) -> None:
    """Rather than sweep the stage for a sharpness that does not change."""
    m = build_microscope(run_settings(tmp_path), instrument)
    with pytest.raises(ValueError, match="Nothing here focuses pmt"):
        run_autofocus(
            m.values, m.detector, AutofocusState(), m.optics, Task.local(), detector_name="pmt"
        )


def test_a_stack_of_a_volume_sweeps_the_stage(tmp_path: Path, instrument: spec.Instrument) -> None:
    """With no focus to go by, it is the one thing that moves through the sample."""
    m = build_microscope(run_settings(tmp_path), instrument)
    channel = AcquisitionChannel(detectors=["pmt"], name="gfp", set_to={"laser_488.power": 10.0})
    store = RecordingStore()
    run_plan(
        acquisition([channel], planes=[0.0, 20.0]),
        store,
        m.optics,
        m.detector,
        m.values,
        m.space,
        m.hooks,
        Task.local(),
    )
    data = store.published[0].data
    assert data.shape[2] == 2 and not np.array_equal(data[0, 0, 0], data[0, 0, 1])


def test_the_server_takes_images_of_the_scans_size(tmp_path: Path, instrument) -> None:  # noqa: ANN001
    """Through the same detector manager as a camera."""
    m = build_microscope(run_settings(tmp_path), instrument)
    detector = m.detector_state.detectors[0]
    assert (detector.plane(), detector.colors) == ((512, 512), [])
    assert [(axis.name, axis.unit, axis.binnable) for axis in detector.axes] == [
        ("y", "deg", False),
        ("x", "deg", False),
    ]
    assert m.optics_state.detectors["pmt"].pixel_um == pytest.approx(
        0.02 * 5_000.0 * math.pi / 180.0
    )
    m.detector.activate_detector("pmt")
    image = m.detector.capture_channels("pmt")
    assert image.shape == (512, 512) and np.issubdtype(image.dtype, np.integer)


def edited(tmp_path: Path, change) -> Path:  # noqa: ANN001
    """The point scanner's description with `change` made to it."""
    data = yaml.safe_load((INSTRUMENT / spec.DESCRIPTION).read_text())
    change(data)
    path = tmp_path / spec.DESCRIPTION
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.mark.parametrize(
    "change, finding",
    [
        (lambda d: d.pop("drives"), "needs one scan wired to it, not 0"),
        (lambda d: d["cubes"]["objective"]["element"].pop("na"), "last one its na"),
        (lambda d: d["illumination"][2].pop("distance"), "needs the distance"),
        (lambda d: d["illumination"].__delitem__(5), "0 illumination routes"),
        (
            lambda d: d["drives"].__setitem__(0, {"from": "galvo.line", "to": "pmt.sample"}),
            "needs one scan wired to it",
        ),
        (
            lambda d: d["drives"].__setitem__(0, {"from": "galvo.pixel", "to": "laser_488.power"}),
            "can only walk a point detector",
        ),
        (lambda d: d["cubes"]["pmt"].pop("tunes"), "must tune"),
        (lambda d: d["cubes"]["pinhole"]["element"].pop("diameter"), "diameter"),
    ],
)
def test_a_scan_that_cannot_work_is_refused_when_parsed(
    tmp_path: Path,
    change: Callable[[dict], Any],
    finding: str,
) -> None:
    """Naming what is missing."""
    with pytest.raises(spec.SpecError, match=finding):
        spec.load(edited(tmp_path, change))


def test_a_point_detector_is_refused_on_real_hardware(instrument: spec.Instrument) -> None:
    """Nothing can read one yet."""
    with pytest.raises(spec.SpecError, match="the detector pmt has no camera"):
        parts.check_wired(instrument, "nothing")


def test_a_point_detector_is_no_camera(tmp_path: Path) -> None:
    """It cannot be opened as one."""

    def change(data: dict) -> None:
        data["hardware"] = {"cameras": {"pmt": {"protocol": "usb3-vision", "vendor": "Simulated"}}}

    with pytest.raises(spec.SpecError, match="no sensor 'pmt' for a camera"):
        spec.load(edited(tmp_path, change))


def test_a_scan_stepped_by_its_frames_delivers_z(tmp_path: Path) -> None:
    """The scan's frame clock can step the stage for a detector, as a camera's can."""

    def change(data: dict) -> None:
        data["cubes"]["stage"]["signals"] = {"in": ["z"]}
        data["drives"].append({"from": "galvo.frame", "to": "stage.z", "by": "1 um"})

    axes = spec.load(edited(tmp_path, change)).detector_axes("pmt")
    assert [axis.name for axis in axes] == ["z", "y", "x"]
    assert dataclasses.astuple(axes[0])[:3] == ("z", None, 1.0)
