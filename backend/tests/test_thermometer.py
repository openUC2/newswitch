"""A thermometer: a detector with no axes, placed by the graph where it measures, beside the sample."""

import shutil
import threading
from pathlib import Path

import numpy as np
import pytest
import yaml
from arkitekt import Task

from newswitch.drivers.simulated_detector import SimulatedDetectorManager
from newswitch.instrument import spec
from newswitch.instrument.errors import SpecError
from newswitch.instrument.parts import check_wired
from newswitch.instrument.space import translation
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import (
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    AcquisitionStack,
)
from newswitch.models.space import Position
from newswitch.routines.acquire import acquire as run_plan
from tests.conftest import acquisition, run_settings
from tests.test_acquire import RecordingStore, sample_of
from tests.test_simulated_detector import RecordingBroadcaster, wait_until

HE = Path(__file__).parents[1] / "instruments" / "he-microscope"
#: Where the he-microscope's thermometer sits on the stage insert: 3 cm along x.
ON_STAGE = {"x": 30_000.0, "y": 0.0, "z": 0.0}
THERMOMETER = Position("detector:thermometer")


def he(tmp_path: Path, truth: dict[str, float] | None = None) -> Microscope:
    """The he-microscope, simulated; with `truth`, a copy that knows what the air really is."""
    folder = HE
    if truth is not None:
        folder = tmp_path / "he"
        shutil.copytree(HE, folder)
        (folder / "truth.yml").write_text(yaml.safe_dump(truth))
    return build_microscope(run_settings(tmp_path, instrument=folder), spec.load(folder))


@pytest.fixture
def m(tmp_path: Path) -> Microscope:
    """The he-microscope, simulated."""
    return he(tmp_path)


def test_it_is_a_detector_with_no_axes(m: Microscope) -> None:
    """Of no light: it delivers no image, and measures a temperature."""
    found = m.detector_state.get("thermometer")
    assert (found.axes, found.quantity, found.unit) == ([], "temperature", "degC")
    assert not found.delivers_images()
    assert m.values is not None and m.values.instrument.detectors() == ["camera"]


def test_its_system_is_a_point_placed_on_the_stage(m: Microscope) -> None:
    """detector:thermometer has no axes; a BY_DIMENSION part from none onto x, y, z places it."""
    system = next(s for s in m.space_state.systems if s.name == "detector:thermometer")
    assert system.axes == []
    (edge,) = [t for t in m.space_state.transformations if t.input == "detector:thermometer"]
    assert (edge.output, edge.kind) == ("stage:stage", "BY_DIMENSION")
    (part,) = edge.parts
    assert (part.kind, part.input_axes, part.output_axes) == ("AFFINE", [], ["x", "y", "z"])
    assert m.space.transform(THERMOMETER, "stage") == pytest.approx(ON_STAGE)


def test_it_is_three_centimetres_from_the_sample(m: Microscope) -> None:
    """Nothing mounted, the sample's frame is the stage's: it measures 3 cm from the section.
    Published from the start, before anything moves."""
    point = m.space_state.points["thermometer"]
    assert (point.x, point.y, point.z) == pytest.approx((30_000.0, 0.0, 0.0))


def test_it_moves_with_the_stage_not_with_the_mount(m: Microscope) -> None:
    """Said where the sample really sits, the thermometer stays where it is on the stage, and where
    it is on the sample follows."""
    m.space.register_mount(translation(-1_000.0, 250.0).tolist())
    assert m.space.transform(THERMOMETER, "stage") == pytest.approx(ON_STAGE)
    assert m.space.transform(THERMOMETER, "sample") == pytest.approx(
        {"x": 29_000.0, "y": 250.0, "z": 0.0}
    )
    point = m.space_state.points["thermometer"]
    assert (point.x, point.y) == pytest.approx((29_000.0, 250.0))


def test_nothing_on_the_sample_says_it_is_the_thermometer(m: Microscope) -> None:
    """It is placed from no axes: walked forwards only."""
    with pytest.raises(ValueError, match="no route"):
        m.space.transform(Position("sample", {"x": 0.0, "y": 0.0}), "detector:thermometer")


def test_it_reads_the_air_the_truth_says(tmp_path: Path) -> None:
    """What it reads is the air beside the sample, within its noise; a reading has no axes."""
    m = he(tmp_path, {"air_temperature_c": 37.0})
    assert m.detector is not None
    reading = m.detector.capture_channels("thermometer")
    assert reading.shape == () and reading.dtype == np.float32
    assert float(reading) == pytest.approx(37.0, abs=0.3)
    assert m.detector_state.get("thermometer").reading == pytest.approx(float(reading))


def test_it_has_no_image(m: Microscope) -> None:
    """Asking it for one is refused by what it is, not by a missing axis."""
    assert m.detector is not None
    with pytest.raises(ValueError, match="at one point"):
        m.detector.capture_image("thermometer")
    with pytest.raises(ValueError, match="at one point"):
        m.detector.plane_under("thermometer")


def test_live_it_publishes_its_reading_and_streams_no_image(m: Microscope) -> None:
    """The live loop streams the camera's images and reads the thermometer, once a second."""
    manager = m.detector
    assert isinstance(manager, SimulatedDetectorManager)
    broadcaster = RecordingBroadcaster()
    thread = threading.Thread(target=manager.acquire_live, args=(broadcaster,), daemon=True)
    thread.start()
    try:
        manager.state.is_acquiring = True
        wait_until(lambda: manager.state.get("thermometer").reading is not None)
        wait_until(lambda: len(broadcaster.sent) >= 2)
        assert {name for name, _ in broadcaster.sent} == {"camera"}
    finally:
        manager.close()
        thread.join(timeout=2.0)


def test_the_acquire_button_takes_the_images(m: Microscope) -> None:
    """Every active detector that takes images gives a frame; the thermometer gives none."""
    assert m.acquisition is not None
    assert m.detector_state.get("thermometer").is_active
    assert len(m.acquisition.acquire()) == 1


def run(
    m: Microscope, plan: AcquisitionPlan, store: RecordingStore | None = None
) -> RecordingStore:
    """Acquire `plan` on `m`, into a store that keeps what it is given."""
    assert m.values is not None and m.detector is not None
    store = store or RecordingStore()
    run_plan(plan, store, m.optics, m.detector, m.values, m.space, m.hooks, Task.local())
    return store


def test_an_acquisition_keeps_a_record_of_it_beside_the_camera(tmp_path: Path) -> None:
    """Each by what it measures: the camera's images along (t, c, z, y, x), placed by its pixels,
    and the thermometer's readings along (t, c, plane), one position along z, y and x: its point,
    3 cm from the section."""
    m = he(tmp_path, {"air_temperature_c": 37.0})
    channel = AcquisitionChannel(name="air", detectors=["camera", "thermometer"])
    camera, thermometer = run(
        m, acquisition([channel], planes=[-2.0, 0.0, 2.0], times=2, places=((500.0, 0.0),))
    ).published

    assert camera.dims == ("t", "c", "z", "y", "x") and camera.data.shape == (2, 3, 3, 512, 512)
    assert [axis.type for axis in camera.axes] == ["TIME", "CHANNEL", "SPACE", "SPACE", "SPACE"]
    middle = sample_of(camera, z=1.0, y=255.5, x=255.5)
    assert (middle["x"], middle["y"]) == pytest.approx((500.0, 0.0), abs=1e-6)

    assert thermometer.dims == ("t", "c", "plane", "z", "y", "x")
    assert thermometer.data.shape == (2, 1, 3, 1, 1, 1)
    assert [axis.type for axis in thermometer.axes] == [
        "TIME",
        "CHANNEL",
        "INDEX",
        "SPACE",
        "SPACE",
        "SPACE",
    ]
    assert thermometer.stack == "plane" and camera.stack == "z"
    assert (thermometer.quantity, thermometer.unit) == ("temperature", "degC")
    assert camera.calibrated is False  # nothing calibrated yet: inferred from the optics
    assert thermometer.calibrated is False  # where it reads is described, never measured
    assert thermometer.data.dtype == np.float32
    assert np.allclose(thermometer.data, 37.0, atol=0.3)
    assert [c.label for c in thermometer.channels] == ["air thermometer (degC)"]
    assert not thermometer.channels[0].light and thermometer.channels[0].sources == ()
    (part,) = thermometer.registration
    assert (part.kind, part.input_axes, part.output_axes) == (
        "AFFINE",
        ["z", "y", "x"],
        ["z", "y", "x"],
    )
    # Its one position along each, index 0, is its point; nothing reads the plane it was read at.
    assert sample_of(thermometer, z=0, y=0, x=0) == pytest.approx(
        {"z": 0.0, "y": 0.0, "x": 30_000.0}
    )


def test_a_thermometer_alone_is_read_where_the_stage_is_set(tmp_path: Path) -> None:
    """Nothing takes images: no image's middle to bring anywhere, and nothing that focuses."""
    m = he(tmp_path)
    channel = AcquisitionChannel(name="air", detectors=["thermometer"])
    (record,) = run(m, acquisition([channel], times=3)).published
    assert record.data.shape == (3, 1, 1, 1, 1, 1)
    with pytest.raises(ValueError, match="give its positions by what to set"):
        run(
            m,
            AcquisitionPlan(
                channels=[channel],
                positions=[AcquisitionPosition(at=Position("sample", {"x": 1.0, "y": 0.0}))],
            ),
        )
    with pytest.raises(ValueError, match="name what moves"):
        run(m, acquisition([channel], planes=[0.0, 1.0]))
    swept = run(
        m,
        AcquisitionPlan(
            channels=[channel], stack=AcquisitionStack(offsets=[0.0, 1.0], variable="stage.z")
        ),
    ).published[0]
    assert swept.data.shape == (1, 1, 2, 1, 1, 1)


def test_looking_goes_by_an_imaging_detector(m: Microscope) -> None:
    """Moving to a place puts it under the camera's image, even with the camera off and the
    thermometer on: a point has no middle to bring anywhere."""
    from newswitch.actions.space import move_to

    assert m.values is not None and m.detector is not None
    m.detector.deactivate_detector("camera")
    move_to(m.space, m.values, Task.local(), Position("sample", {"x": 120.0, "y": -40.0}))
    middle = m.space.placement("camera") @ np.array([255.5, 255.5, 0.0, 1.0])
    assert middle[:2] == pytest.approx([120.0, -40.0])


def test_an_image_of_whatever_is_on_is_never_the_thermometers(m: Microscope) -> None:
    """With the camera off, there is no image to take: said so, not that a thermometer has none."""
    assert m.detector is not None
    m.detector.deactivate_detector("camera")
    with pytest.raises(ValueError, match="No active detector"):
        m.detector.capture_image(None)


def test_no_driver_reads_a_real_thermometer_yet() -> None:
    """Only a simulated one reads: anything else is refused, not left out."""
    with pytest.raises(SpecError, match="no driver reads a thermometer"):
        check_wired(spec.load(HE), "unwired")
