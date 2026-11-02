"""A detector measures domains of the sample along its axes, and reads a window of each."""

from pathlib import Path

import numpy as np
import pytest

from newswitch.drivers.simulated_detector import SimulatedDetectorManager
from newswitch.instrument import spec
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.devices import AxisWindow
from tests.conftest import run_settings

INSTRUMENTS = Path(__file__).parent.parent / "instruments"


def built(tmp_path: Path, name: str) -> Microscope:
    """The simulated microscope of the instrument `name`."""
    return build_microscope(run_settings(tmp_path), spec.load(INSTRUMENTS / name))


def simulated(microscope: Microscope) -> SimulatedDetectorManager:
    """Its detector manager, which renders."""
    assert isinstance(microscope.detector, SimulatedDetectorManager)
    return microscope.detector


@pytest.mark.parametrize(
    ("instrument", "detector", "axes"),
    [
        ("dual-camera", "camera_green", [("y", "space", "um"), ("x", "space", "um")]),
        (
            "rgb-camera",
            "camera",
            [("c", "spectrum", ""), ("y", "space", "um"), ("x", "space", "um")],
        ),
        ("point-scanner", "pmt", [("y", "space", "deg"), ("x", "space", "deg")]),
        (
            "flim",
            "spad",
            [("m", "microtime", "ps"), ("y", "space", "deg"), ("x", "space", "deg")],
        ),
        (
            "light-sheet",
            "camera",
            [("z", "space", "um"), ("y", "space", "um"), ("x", "space", "um")],
        ),
    ],
)
def test_every_axis_says_what_it_measures(
    tmp_path: Path, instrument: str, detector: str, axes: list[tuple[str, str, str]]
) -> None:
    """Of the sample: where, which colors, or when a photon came; in the unit of what delivers it."""
    (found,) = [
        d for d in built(tmp_path, instrument).detector_state.detectors if d.name == detector
    ]
    assert [(axis.name, axis.domain, axis.unit) for axis in found.axes] == axes


def test_a_scan_window_scans_part_of_the_field(tmp_path: Path) -> None:
    """At the same step: half the positions each way, from where the window starts."""
    m = built(tmp_path, "point-scanner")
    manager = simulated(m)
    whole = np.arange(512 * 512, dtype=np.uint16).reshape(512, 512)
    manager.simulator.render = lambda detector, values: whole  # type: ignore[method-assign]
    manager.update_detector("pmt", windows=[AxisWindow("x", 128, 256), AxisWindow("y", 64, 256)])
    image = manager.capture_image("pmt").data
    np.testing.assert_array_equal(image, whole[64:320, 128:384])
    pmt = manager.get_detector_state("pmt")
    assert pmt is not None and pmt.plane() == (256, 256)
    assert pmt.axis("x").step == pytest.approx(0.02)  # the galvo's: a smaller field, no zoom


def test_a_scan_does_not_bin(tmp_path: Path) -> None:
    """A binning does not touch the positions of a scan."""
    manager = simulated(built(tmp_path, "point-scanner"))
    pmt = manager.update_detector("pmt", binning=2)
    assert pmt.plane() == (512, 512)


def test_only_space_has_a_window(tmp_path: Path) -> None:
    """Colors and arrival times are read whole."""
    flim = simulated(built(tmp_path, "flim"))
    with pytest.raises(ValueError, match="no window"):
        flim.update_detector("spad", windows=[AxisWindow("m", 0, 8)])
    rgb = simulated(built(tmp_path / "rgb", "rgb-camera"))
    with pytest.raises(ValueError, match="no window"):
        rgb.update_detector("camera", windows=[AxisWindow("c", 0, 1)])


def test_a_window_reaches_every_axis_of_an_exposure(tmp_path: Path) -> None:
    """A color camera's windowed exposure is each color, windowed; a timed one each bin."""
    rgb = simulated(built(tmp_path, "rgb-camera"))
    rgb.update_detector("camera", windows=[AxisWindow("x", 0, 100), AxisWindow("y", 0, 60)])
    assert rgb.capture_channels("camera").shape == (3, 60, 100)
    assert rgb.capture_image("camera").data.shape == (60, 100)
    flim = simulated(built(tmp_path / "flim", "flim"))
    flim.update_detector("spad", windows=[AxisWindow("x", 0, 100), AxisWindow("y", 0, 60)])
    assert flim.capture_channels("spad").shape == (64, 60, 100)


def test_what_an_axis_delivers_is_published_with_it(tmp_path: Path) -> None:
    """A view reads how many values an image has along an axis, after window and binning."""
    manager = simulated(built(tmp_path, "dual-camera"))
    camera = manager.update_detector("camera_green", binning=2, windows=[AxisWindow("x", 0, 100)])
    assert [(axis.name, axis.delivered_size) for axis in camera.axes] == [("y", 256), ("x", 50)]
