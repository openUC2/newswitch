"""The detectors of a simulated instrument: as any detector has them, rendered from the optics.

Sessions, binning and regions, the live loop and its pacing, on real instruments; what is rendered
follows from what the variables are.
"""

import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Generator

import numpy as np
import pytest
import yaml

from newswitch.infra.streaming import FrameBroadcaster
from newswitch.drivers.simulated_detector import SimulatedDetectorManager
from newswitch.instrument import parts, spec
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.devices import FULL_SENSOR
from newswitch.protocols import DetectorManager
from newswitch.protocols.detector import DetectorFrame
from newswitch.services.values import Values
from newswitch.states.detector import DetectorState
from newswitch.tools.export_schemas import REFERENCE_INSTRUMENT
from tests.conftest import run_settings

FAKE = Path(__file__).parent.parent / "instruments" / "fake-microscope"


@pytest.fixture
def values(microscope: Microscope) -> Values:
    """What the variables of the reference microscope are."""
    assert microscope.values is not None
    return microscope.values


@pytest.fixture
def manager(microscope: Microscope) -> SimulatedDetectorManager:
    """The detector manager of the reference microscope: one sensor of 512 x 512, `camera`."""
    assert isinstance(microscope.detector, SimulatedDetectorManager)
    return microscope.detector


@pytest.fixture
def two_cameras(tmp_path: Path) -> Microscope:
    """The fake microscope, as the server builds it: `camera_a` and `camera_b`."""
    return build_microscope(run_settings(tmp_path), spec.load(FAKE))


class TestDetectorProtocolCompliance:
    """A simulated manager does what any `DetectorManager` does."""

    def test_satisfies_the_protocol(self, manager: SimulatedDetectorManager) -> None:
        """The simulated manager is a DetectorManager."""
        assert isinstance(manager, DetectorManager)

    def test_capture_image_returns_frame(self, manager: SimulatedDetectorManager) -> None:
        """capture_image returns the image with correct shape, dtype and timing."""
        frame = manager.capture_image("camera")

        assert isinstance(frame, DetectorFrame)
        assert frame.detector == "camera"
        assert isinstance(frame.data, np.ndarray)
        assert frame.data.shape == (512, 512)
        assert frame.data.dtype == np.uint16
        assert frame.wall_time_ns is not None and abs(frame.wall_time_ns - time.time_ns()) < 60e9

    def test_capture_image_takes_the_first_that_is_on(self, two_cameras: Microscope) -> None:
        """Without a name, in the order the description has them; a detector that is off gives none."""
        assert two_cameras.detector is not None
        assert two_cameras.detector.capture_image().detector == "camera_a"
        two_cameras.detector.deactivate_detector("camera_a")
        assert two_cameras.detector.capture_image().detector == "camera_b"
        with pytest.raises(ValueError, match="No active detector camera_a"):
            two_cameras.detector.capture_image("camera_a")
        two_cameras.detector.deactivate_detector("camera_b")
        with pytest.raises(ValueError, match="No active detector"):
            two_cameras.detector.capture_image()

    def test_activate_detector(self, two_cameras: Microscope) -> None:
        """activate_detector keeps the requested detector active; all start on."""
        assert two_cameras.detector is not None
        state = two_cameras.detector_state
        assert all(detector.is_active for detector in state.detectors)

        activated = two_cameras.detector.activate_detector("camera_a")

        assert all(detector.is_active for detector in state.detectors)
        assert activated.name == "camera_a"
        assert activated.is_active is True

    def test_deactivate_detector(self, two_cameras: Microscope) -> None:
        """deactivate_detector deactivates the requested detector, and only it."""
        assert two_cameras.detector is not None

        two_cameras.detector.deactivate_detector("camera_a")

        active = [d.name for d in two_cameras.detector_state.detectors if d.is_active]
        assert active == ["camera_b"]

    def test_update_detector_exposure(self, manager: SimulatedDetectorManager) -> None:
        """update_detector updates the exposure."""
        assert manager.update_detector("camera", exposure_ms=500.0).current_exposure_ms == 500.0

    def test_update_detector_gain(self, manager: SimulatedDetectorManager) -> None:
        """update_detector updates the gain."""
        assert manager.update_detector("camera", gain=5.0).current_gain == 5.0

    def test_exposure_is_kept_in_its_range_as_the_app_changes_it(
        self, values: Values, manager: SimulatedDetectorManager
    ) -> None:
        """Through its variable, which says what its range is: 1 ms to 10 s."""
        detector = manager.state.get("camera")
        values.set({"camera.exposure": 0.0001})
        assert detector.current_exposure_ms == 1.0
        assert values["camera.exposure"] == 1.0
        values.set({"camera.exposure": 100_000.0})
        assert detector.current_exposure_ms == 10_000.0

    def test_gain_is_kept_in_its_range_as_the_app_changes_it(
        self, values: Values, manager: SimulatedDetectorManager
    ) -> None:
        """Through its variable, which says what its range is: 0 to 40 dB."""
        detector = manager.state.get("camera")
        values.set({"camera.gain": -10.0})
        assert detector.current_gain == 0.0
        values.set({"camera.gain": 200.0})
        assert detector.current_gain == 40.0

    def test_list_available_detectors(self, two_cameras: Microscope) -> None:
        """All of them, in the order the description has them."""
        assert two_cameras.detector is not None
        available = two_cameras.detector.list_available_detectors()
        assert [detector.name for detector in available] == ["camera_a", "camera_b"]

    def test_list_active_detectors(self, two_cameras: Microscope) -> None:
        """All of them, until one is turned off."""
        assert two_cameras.detector is not None
        active = two_cameras.detector.list_active_detectors()
        assert [detector.name for detector in active] == ["camera_a", "camera_b"]


class TestFrameGeneration:
    """What is rendered follows from where the sample is and what lights it."""

    def test_frame_changes_with_stage_position(
        self, values: Values, manager: SimulatedDetectorManager
    ) -> None:
        """The image moves with the stage."""
        frame1 = manager.capture_image("camera").data

        values.set({"stage.x": 200.0, "stage.y": 150.0})
        frame2 = manager.capture_image("camera").data

        assert not np.array_equal(frame1, frame2)

    def test_frame_changes_with_z(self, values: Values, manager: SimulatedDetectorManager) -> None:
        """Each focus gives another image."""
        values.set({"stage.z": 0.0})
        frame_z0 = manager.capture_image("camera").data

        values.set({"stage.z": 200.0})
        frame_z2 = manager.capture_image("camera").data

        values.set({"stage.z": -200.0})
        frame_z_neg2 = manager.capture_image("camera").data

        assert not np.array_equal(frame_z0, frame_z2)
        assert not np.array_equal(frame_z0, frame_z_neg2)
        assert not np.array_equal(frame_z2, frame_z_neg2)

    def test_higher_power_brighter_frame(
        self, values: Values, manager: SimulatedDetectorManager
    ) -> None:
        """More light on the sample is more light on the sensor."""
        values.set({"laser_488.power": 5.0})
        frame_low = manager.capture_image("camera").data

        values.set({"laser_488.power": 50.0})
        frame_high = manager.capture_image("camera").data

        assert frame_high.mean() > frame_low.mean()

    def test_higher_exposure_brighter_frame(
        self, values: Values, manager: SimulatedDetectorManager
    ) -> None:
        """A longer exposure collects more."""
        values.set({"camera.exposure": 10.0})
        frame_short = manager.capture_image("camera").data

        values.set({"camera.exposure": 1000.0})
        frame_long = manager.capture_image("camera").data

        assert frame_long.mean() > frame_short.mean()

    def test_higher_gain_brighter_frame(
        self, values: Values, manager: SimulatedDetectorManager
    ) -> None:
        """A higher gain multiplies what was collected."""
        values.set({"camera.gain": 0.0})
        frame_low_gain = manager.capture_image("camera").data

        values.set({"camera.gain": 20.0})
        frame_high_gain = manager.capture_image("camera").data

        assert frame_high_gain.mean() > frame_low_gain.mean()


class RecordingBroadcaster(FrameBroadcaster):
    """Frame broadcaster that keeps everything it is sent."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        super().__init__()
        self.sent: list[tuple[str, np.ndarray]] = []

    def broadcast_sync(self, detector: str, frame: np.ndarray) -> None:
        """Keep the frame."""
        self.sent.append((detector, frame))


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Poll `condition` until it holds.

    Raises:
        TimeoutError: It did not hold within `timeout` seconds.
    """
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        time.sleep(0.005)


class TestReadout:
    """Region of interest, binning and frame rate set by update_detector."""

    def test_binning_averages_blocks(self, manager: SimulatedDetectorManager) -> None:
        """A binned image holds the means of the blocks of the full image."""
        sensor = np.arange(512 * 512, dtype=np.uint16).reshape(512, 512)
        detector = manager.update_detector("camera", binning=2)

        binned = manager._read_out(sensor, detector)

        expected = sensor.reshape(256, 2, 256, 2).mean(axis=(1, 3)).astype(np.uint16)
        np.testing.assert_array_equal(binned, expected)
        assert (detector.width, detector.height) == (256, 256)
        assert detector.current_binning == 2
        assert (detector.sensor_width, detector.sensor_height) == (512, 512)

    def test_a_captured_image_is_binned(
        self, manager: SimulatedDetectorManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What capture_image gives is the rendered sensor, read out as the detector says."""
        sensor = np.arange(512 * 512, dtype=np.uint16).reshape(512, 512)
        monkeypatch.setattr(manager, "_whole_sensor", lambda detector: sensor)
        manager.update_detector("camera", binning=2)
        np.testing.assert_array_equal(
            manager.capture_image("camera").data,
            sensor.reshape(256, 2, 256, 2).mean(axis=(1, 3)).astype(np.uint16),
        )

    def test_binning_snaps_to_an_allowed_factor(self, manager: SimulatedDetectorManager) -> None:
        """Binning snaps to the nearest allowed factor; factors < 1 are rejected."""
        detector = manager.update_detector("camera", binning=3)
        assert detector.current_binning == 2
        with pytest.raises(ValueError, match="binning"):
            manager.update_detector("camera", binning=0)

    def test_binning_through_its_variable_is_what_the_detector_made_of_it(
        self, values: Values, manager: SimulatedDetectorManager
    ) -> None:
        """The variable reports the factor the detector snapped to, and the image has its size."""
        values.set({"camera.binning": 3})
        assert values["camera.binning"] == 2
        assert values.tune_state.tunes["camera"]["binning"].value == 2
        assert manager.capture_image("camera").data.shape == (256, 256)

    def test_roi_cuts_out_the_region(self, manager: SimulatedDetectorManager) -> None:
        """The region sets the image and detector size."""
        detector = manager.update_detector("camera", roi=(10, 20, 100, 50))
        assert manager.capture_image("camera").data.shape == (50, 100)
        assert (detector.width, detector.height) == (100, 50)
        assert detector.current_roi == [10, 20, 100, 50]

    def test_roi_is_clamped_and_reset(self, manager: SimulatedDetectorManager) -> None:
        """A region is clamped to the sensor; FULL_SENSOR reads the complete sensor again."""
        detector = manager.update_detector("camera", roi=(456, 456, 100, 100))
        assert detector.current_roi == [456, 456, 56, 56]

        detector = manager.update_detector("camera", roi=FULL_SENSOR)
        assert detector.current_roi is None
        assert (detector.width, detector.height) == (512, 512)
        assert manager.capture_image("camera").data.shape == (512, 512)

        with pytest.raises(ValueError, match="negative"):
            manager.update_detector("camera", roi=(-1, 0, 10, 10))

    def test_roi_and_binning_combine(self, manager: SimulatedDetectorManager) -> None:
        """The region is cut out first, then binned; a region below the binning is rejected."""
        detector = manager.update_detector("camera", binning=4, roi=(0, 0, 100, 60))
        assert manager.capture_image("camera").data.shape == (15, 25)
        with pytest.raises(ValueError, match="smaller than the binning"):
            manager.update_detector("camera", roi=(0, 0, 2, 2))
        assert detector.current_roi == [0, 0, 100, 60]  # unchanged

    def test_frame_rate(self, values: Values, manager: SimulatedDetectorManager) -> None:
        """A frame rate is kept in its range by its variable; 0 removes the limit, < 0 is rejected."""
        detector = manager.update_detector("camera", frame_rate=10.0)
        assert detector.current_frame_rate == 10.0
        values.set({"camera.frame_rate": 1000.0})
        assert detector.current_frame_rate == 100.0
        manager.update_detector("camera", frame_rate=0)
        assert detector.current_frame_rate is None
        with pytest.raises(ValueError, match="frame rate"):
            manager.update_detector("camera", frame_rate=-1.0)

    def test_a_described_readout_is_kept(self, tmp_path: Path) -> None:
        """A sensor described to start binned has the size of its image, at a factor it allows.

        What the detector made of it is what its variable says, so the optics predict its pixels.
        """
        copy = tmp_path / "instrument"
        shutil.copytree(REFERENCE_INSTRUMENT, copy)
        path = copy / spec.DESCRIPTION
        data = yaml.safe_load(path.read_text())
        data["cubes"]["camera"]["tunes"]["binning"]["initial"] = 3
        path.write_text(yaml.safe_dump(data))
        m = build_microscope(run_settings(tmp_path), spec.load(copy))
        assert m.detector is not None and m.values is not None
        (detector,) = m.detector.list_available_detectors()
        assert detector.current_binning == 2
        assert (detector.width, detector.height) == (256, 256)
        assert (detector.sensor_width, detector.sensor_height) == (512, 512)
        assert m.detector.capture_image("camera").data.shape == (256, 256)
        assert m.values["camera.binning"] == 2
        assert m.tune_state.tunes["camera"]["binning"].value == 2

        pixel = m.optics_state.detectors["camera"].pixel_um
        m.values.set({"camera.binning": 2})
        assert m.optics_state.detectors["camera"].pixel_um == pixel

    def test_an_unknown_detector_is_refused(self, manager: SimulatedDetectorManager) -> None:
        """By name, saying which there are."""
        with pytest.raises(ValueError, match="No detector 'nope'"):
            manager.update_detector("nope", gain=1.0)
        assert manager.get_detector_state("nope") is None

    def test_detectors_are_described(self, two_cameras: Microscope) -> None:
        """Every detector says what it is; its size is what its description states."""
        assert two_cameras.detector is not None
        for detector in two_cameras.detector.list_available_detectors():
            assert detector.manufacturer == "simulated"
            assert detector.connection_type is None  # no camera behind it
            assert detector.data_type == "uint16"
            assert (detector.sensor_width, detector.sensor_height) == (512, 512)
            assert (detector.width, detector.height) == (512, 512)
            assert (detector.current_binning, detector.current_roi) == (1, None)
            assert detector.current_frame_rate == 30.0
            assert detector.current_exposure_ms == 100.0
            assert not detector.is_recording
            assert detector.recording_file is None

    def test_it_is_built_from_an_instrument(self) -> None:
        """All it takes is the detectors of a description, and what its variables are."""
        instrument = spec.load(REFERENCE_INSTRUMENT)
        state = DetectorState()
        manager = SimulatedDetectorManager(
            instrument,
            state,
            parts.detectors(instrument),
            instrument.initial_state,
            lambda name, value: None,
        )
        assert [detector.name for detector in state.detectors] == ["camera"]
        assert manager.capture_image("camera").data.shape == (512, 512)


class TestSessions:
    """Acquisition sessions and the timing of the images."""

    def test_no_session_before_the_first_image(self, manager: SimulatedDetectorManager) -> None:
        """Before anything is acquired there is no session; unknown detectors are rejected."""
        assert manager.get_image_info("camera") is None
        with pytest.raises(ValueError, match="No detector 'nope'"):
            manager.get_image_info("nope")

    def test_snapshot_is_a_session_of_its_own(self, manager: SimulatedDetectorManager) -> None:
        """Outside of the live stream every snapshot starts a session with its settings."""
        manager.update_detector("camera", exposure_ms=200.0, binning=2)
        first = manager.capture_image("camera")
        info = manager.get_image_info("camera")
        assert info is not None
        assert (info.width, info.height, info.channels, info.dtype) == (256, 256, 1, "uint16")
        assert info.recording_file is None
        assert info.settings["exposure_time_ms"] == pytest.approx(200.0)
        assert info.settings["binning"] == 2
        assert first.wall_time_ns == info.wall_time_ns(first.time_ns)

        second = manager.capture_image("camera")
        assert (first.sequence, second.sequence) == (0, 0)
        assert manager.get_image_info("camera") is not info


class TestLiveStream:
    """The live loop: streaming, pacing, stopping and closing."""

    @pytest.fixture
    def live(
        self, two_cameras: Microscope
    ) -> Generator[tuple[SimulatedDetectorManager, RecordingBroadcaster], None, None]:
        """The manager with only `camera_a` active, its live loop running in a thread.

        Args:
            two_cameras: A microscope with more detectors than the one that streams.

        Yields:
            The manager and the broadcaster that records what is streamed. Closing the
            manager afterwards must end the loop.
        """
        manager = two_cameras.detector
        assert isinstance(manager, SimulatedDetectorManager)
        manager.deactivate_detector("camera_b")
        broadcaster = RecordingBroadcaster()
        thread = threading.Thread(target=manager.acquire_live, args=(broadcaster,), daemon=True)
        thread.start()
        yield manager, broadcaster
        manager.close()
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    def test_streams_the_active_detectors(
        self, live: tuple[SimulatedDetectorManager, RecordingBroadcaster]
    ) -> None:
        """While acquiring, binned images of the active detector stream in one session."""
        manager, broadcaster = live
        manager.update_detector("camera_a", binning=2)
        manager.state.is_acquiring = True
        wait_until(lambda: len(broadcaster.sent) >= 3)
        assert {name for name, _ in broadcaster.sent} == {"camera_a"}
        assert all(frame.shape == (256, 256) for _, frame in broadcaster.sent)
        assert manager.state.get("camera_a").is_recording

        info = manager.get_image_info("camera_a")
        snapshot = manager.capture_image("camera_a")  # part of the live session
        assert snapshot.sequence >= 3
        assert manager.get_image_info("camera_a") is info

    def test_frame_rate_paces_the_stream(
        self, live: tuple[SimulatedDetectorManager, RecordingBroadcaster]
    ) -> None:
        """At 20 frames per second about 10 images stream in half a second."""
        manager, broadcaster = live
        manager.update_detector("camera_a", frame_rate=20.0)
        manager.state.is_acquiring = True
        time.sleep(0.5)
        manager.stop_acquire_live()
        assert 2 <= len(broadcaster.sent) <= 12

    def test_stop_acquire_live(
        self, live: tuple[SimulatedDetectorManager, RecordingBroadcaster]
    ) -> None:
        """Stopping ends the stream at once; the loop keeps running and can stream again."""
        manager, broadcaster = live
        manager.state.is_acquiring = True
        wait_until(lambda: len(broadcaster.sent) >= 3)
        first_session = manager.get_image_info("camera_a")

        manager.stop_acquire_live()
        assert not manager.state.is_acquiring
        assert not manager.state.get("camera_a").is_recording
        count = len(broadcaster.sent)
        time.sleep(0.2)
        assert len(broadcaster.sent) == count  # nothing after stop_acquire_live returned

        manager.state.is_acquiring = True
        wait_until(lambda: len(broadcaster.sent) > count)
        assert manager.get_image_info("camera_a") is not first_session
