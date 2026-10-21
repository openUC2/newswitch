"""Tests for the VirtualDetectorManager using protocol-based testing.

This module tests the VirtualDetectorManager implementation to ensure it correctly
implements the DetectorManager protocol, including detector activation/deactivation,
frame generation, illumination effects, and camera settings.
"""

import threading
import time
from typing import Callable, Generator

import numpy as np
import pytest
from rekuest_next.state.lock import acquired_locks

from newswitch.broadcasters import FrameBroadcaster
from newswitch.managers.virtual import VirtualDetectorManager
from newswitch.managers.virtual.virtual_detector import DetectorConfig
from newswitch.protocols import CameraState, DetectorManager, IlluminationState, StageState
from newswitch.protocols.detector import FULL_SENSOR, Detector, DetectorFrame
from newswitch.protocols.illumination import Illumination
from newswitch.protocols.objective import ObjectiveState


@pytest.fixture
def detector_states() -> Generator[
    tuple[CameraState, StageState, ObjectiveState, IlluminationState], None, None
]:
    """Create all required states for the detector.

    Creates camera, stage, objective, and illumination states with active illumination
    for testing detector functionality.

    Yields:
        A tuple of (CameraState, StageState, ObjectiveState, IlluminationState) for detector tests.
    """
    with acquired_locks("camera_parameters", "stage_position", "objective", "illumination"):
        camera_state = CameraState()
        stage_state = StageState()
        stage_state.x = 0.0
        stage_state.y = 0.0
        stage_state.z = 0.0
        stage_state.a = 0.0
        objective_state = ObjectiveState(slot=1, magnification=10.0, name="10x Air")
        # Create illumination state with active illumination for testing
        illumination_state = IlluminationState(
            illuminations=[
                Illumination(
                    slot=1, intensity=500.0, wavelength=488.0, max_intensity=1000.0, is_active=True
                )
            ],
        )
        yield camera_state, stage_state, objective_state, illumination_state


@pytest.fixture
def virtual_detector_manager(
    detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState],
) -> Generator[VirtualDetectorManager, None, None]:
    """Create a VirtualDetectorManager with cells sample type.

    Creates a detector manager configured for cells sample generation
    with a 256x256 pixel frame size and one activated detector.

    Args:
        detector_states: The required states from the detector_states fixture.

    Yields:
        VirtualDetectorManager: A configured detector manager ready for testing.
    """
    camera_state, stage_state, objective_state, illumination_state = detector_states
    broadcaster = FrameBroadcaster()
    manager = VirtualDetectorManager(
        camera_state=camera_state,
        stage_state=stage_state,
        objective_state=objective_state,
        illumination_state=illumination_state,
        broadcaster=broadcaster,
        config=DetectorConfig(sample_type="cells", width=256, height=256),
    )
    # Activate a detector for testing
    manager.activate_detector(1)
    yield manager


@pytest.fixture
def astigmatism_detector_manager(
    detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState],
) -> Generator[VirtualDetectorManager, None, None]:
    """Create a VirtualDetectorManager with astigmatism sample type.

    Creates a detector manager configured for astigmatism sample generation,
    which produces frames with z-dependent elliptical patterns useful for
    testing focus-related functionality.

    Args:
        detector_states: The required states from the detector_states fixture.

    Yields:
        VirtualDetectorManager: A configured detector manager ready for testing.
    """
    camera_state, stage_state, objective_state, illumination_state = detector_states
    broadcaster = FrameBroadcaster()
    manager = VirtualDetectorManager(
        camera_state=camera_state,
        stage_state=stage_state,
        objective_state=objective_state,
        illumination_state=illumination_state,
        broadcaster=broadcaster,
        config=DetectorConfig(sample_type="astigmatism", width=256, height=256),
    )
    # Activate a detector for testing
    manager.activate_detector(1)
    yield manager


class TestDetectorProtocolCompliance:
    """Test that VirtualDetectorManager implements the DetectorManager protocol."""

    def test_satisfies_the_protocol(self, virtual_detector_manager: VirtualDetectorManager) -> None:
        """The virtual manager is a DetectorManager."""
        assert isinstance(virtual_detector_manager, DetectorManager)

    def test_capture_image_returns_frame(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that capture_image returns the image with correct shape, dtype and timing."""
        frame = virtual_detector_manager.capture_image(slot=1)

        assert isinstance(frame, DetectorFrame)
        assert frame.slot == 1
        assert isinstance(frame.data, np.ndarray)
        assert frame.data.shape == (256, 256)
        assert frame.data.dtype == np.uint16
        assert frame.wall_time_ns is not None and abs(frame.wall_time_ns - time.time_ns()) < 60e9

    def test_activate_detector(
        self, detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState]
    ) -> None:
        """Test that `activate_detector()` keeps the requested detector active.

        Args:
            detector_states: The required states from the detector_states fixture.
        """
        camera_state, stage_state, objective_state, illumination_state = detector_states
        broadcaster = FrameBroadcaster()
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            broadcaster=broadcaster,
            config=DetectorConfig(sample_type="cells", width=256, height=256),
        )

        # The current virtual detector implementation starts with all detectors active.
        active = [d for d in camera_state.detectors if d.is_active]
        assert len(active) == len(camera_state.detectors)

        state = detector.activate_detector(1)

        active = [d for d in camera_state.detectors if d.is_active]
        assert len(active) == len(camera_state.detectors)
        assert state.slot == 1
        assert state.is_active is True

    def test_deactivate_detector(self, virtual_detector_manager: VirtualDetectorManager) -> None:
        """Test that `deactivate_detector()` deactivates the requested detector."""
        detector = virtual_detector_manager
        camera_state = detector.state

        # The current implementation starts with three active detectors.
        active = [d for d in camera_state.detectors if d.is_active]
        assert len(active) == len(camera_state.detectors)

        detector.deactivate_detector(1)

        active = [d for d in camera_state.detectors if d.is_active]
        assert len(active) == len(camera_state.detectors) - 1
        assert all(d.slot != 1 for d in active)

    def test_update_detector_exposure(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that update_detector updates exposure time."""
        detector = virtual_detector_manager

        state = detector.update_detector(slot=1, exposure_time=0.5)

        assert state.current_exposure_time == 0.5

    def test_update_detector_exposure_clamped_min(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that exposure is clamped to minimum."""
        detector = virtual_detector_manager

        state = detector.update_detector(slot=1, exposure_time=0.0001)  # Below min

        detector_config = detector.config
        assert state.current_exposure_time == detector_config.min_exposure

    def test_update_detector_exposure_clamped_max(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that exposure is clamped to maximum."""
        detector = virtual_detector_manager

        state = detector.update_detector(slot=1, exposure_time=100.0)  # Above max

        detector_config = detector.config
        assert state.current_exposure_time == detector_config.max_exposure

    def test_update_detector_gain(self, virtual_detector_manager: VirtualDetectorManager) -> None:
        """Test that update_detector updates gain."""
        detector = virtual_detector_manager

        state = detector.update_detector(slot=1, gain=5.0)

        assert state.current_gain == 5.0

    def test_update_detector_gain_clamped(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that gain is clamped to valid range."""
        detector = virtual_detector_manager
        detector_obj = detector.get_detector_state(1)
        assert detector_obj is not None

        # Below min
        state = detector.update_detector(slot=1, gain=-10.0)
        assert state.current_gain == detector_obj.min_gain

        # Above max
        state = detector.update_detector(slot=1, gain=200.0)
        assert state.current_gain == detector_obj.max_gain

    def test_list_available_detectors(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that list_available_detectors returns available detectors."""
        detector = virtual_detector_manager

        available = detector.list_available_detectors()

        assert len(available) == 3
        assert available[0].slot == 1
        assert available[1].slot == 2
        assert available[2].slot == 3

    def test_list_active_detectors(self, virtual_detector_manager: VirtualDetectorManager) -> None:
        """Test that list_active_detectors returns active detectors."""
        detector = virtual_detector_manager

        active = detector.list_active_detectors()

        assert len(active) == 3
        assert [item.slot for item in active] == [1, 2, 3]


class TestFrameGeneration:
    """Test frame generation behavior.

    These tests verify that frame generation responds correctly to
    stage position changes and produces valid output for different sample types.
    """

    def test_frame_changes_with_stage_position(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that frame content changes when stage position changes."""
        detector = virtual_detector_manager
        stage_state = detector.stage_state

        frame1 = detector.capture_image(slot=1).data

        stage_state.x = 200.0
        stage_state.y = 150.0
        frame2 = detector.capture_image(slot=1).data

        # Frames should be different (not exactly equal)
        assert not np.array_equal(frame1, frame2)

    def test_astigmatism_frame_generation(
        self, astigmatism_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test astigmatism mode produces valid frames."""
        detector = astigmatism_detector_manager

        frame = detector.capture_image(slot=1).data

        assert isinstance(frame, np.ndarray)
        assert frame.shape == (256, 256)
        assert frame.dtype == np.uint16

    def test_astigmatism_changes_with_z(
        self, astigmatism_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that astigmatism frame changes with z position."""
        detector = astigmatism_detector_manager
        stage_state = detector.stage_state

        stage_state.z = 0.0
        frame_z0 = detector.capture_image(slot=1).data

        stage_state.z = 2.0
        frame_z2 = detector.capture_image(slot=1).data

        stage_state.z = -2.0
        frame_z_neg2 = detector.capture_image(slot=1).data

        # All frames should be different
        assert not np.array_equal(frame_z0, frame_z2)
        assert not np.array_equal(frame_z0, frame_z_neg2)
        assert not np.array_equal(frame_z2, frame_z_neg2)


class TestIlluminationEffect:
    """Test illumination effects on frames.

    These tests verify that changes to illumination intensity
    correctly affect the brightness of captured frames.
    """

    def test_higher_intensity_brighter_frame(
        self, detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState]
    ) -> None:
        """Test that higher illumination intensity produces brighter frames.

        Args:
            detector_states: The required states from the detector_states fixture.
        """
        camera_state, stage_state, objective_state, illumination_state = detector_states
        broadcaster = FrameBroadcaster()

        # Use astigmatism mode which generates consistent frames
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            broadcaster=broadcaster,
            config=DetectorConfig(
                sample_type="astigmatism",
                width=128,
                height=128,
                poisson_noise=False,
                read_noise=0.0,
            ),
        )
        detector.activate_detector(1)

        # Low intensity - update the active illumination for testing
        illumination_state.illuminations[0].intensity = 100.0
        frame_low = detector.capture_image(slot=1).data

        # High intensity
        illumination_state.illuminations[0].intensity = 1000.0
        frame_high = detector.capture_image(slot=1).data

        # Higher intensity should produce higher mean pixel value
        assert frame_high.mean() > frame_low.mean()


class TestCameraSettings:
    """Test camera settings effects on frames.

    These tests verify that changes to camera settings (exposure, gain)
    correctly affect the brightness and quality of captured frames.
    """

    def test_higher_exposure_brighter_frame(
        self, detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState]
    ) -> None:
        """Test that higher exposure produces brighter frames.

        Args:
            detector_states: The required states from the detector_states fixture.
        """
        camera_state, stage_state, objective_state, illumination_state = detector_states
        broadcaster = FrameBroadcaster()

        # Use astigmatism mode which generates consistent frames
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            broadcaster=broadcaster,
            config=DetectorConfig(
                sample_type="astigmatism",
                width=128,
                height=128,
                poisson_noise=False,
                read_noise=0.0,
            ),
        )
        detector.activate_detector(1)

        detector.update_detector(slot=1, exposure_time=0.01)
        frame_short = detector.capture_image(slot=1).data

        detector.update_detector(slot=1, exposure_time=1.0)
        frame_long = detector.capture_image(slot=1).data

        # Longer exposure should produce brighter frame
        assert frame_long.mean() > frame_short.mean()

    def test_higher_gain_brighter_frame(
        self, detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState]
    ) -> None:
        """Test that higher gain produces brighter frames.

        Args:
            detector_states: The required states from the detector_states fixture.
        """
        camera_state, stage_state, objective_state, illumination_state = detector_states
        broadcaster = FrameBroadcaster()

        # Use astigmatism mode which generates consistent frames
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            broadcaster=broadcaster,
            config=DetectorConfig(
                sample_type="astigmatism",
                width=128,
                height=128,
                poisson_noise=False,
                read_noise=0.0,
            ),
        )
        detector.activate_detector(1)

        detector.update_detector(slot=1, gain=0.0)
        frame_low_gain = detector.capture_image(slot=1).data

        detector.update_detector(slot=1, gain=50.0)
        frame_high_gain = detector.capture_image(slot=1).data

        # Higher gain should produce brighter frame
        assert frame_high_gain.mean() > frame_low_gain.mean()


class RecordingBroadcaster(FrameBroadcaster):
    """Frame broadcaster that keeps what it is sent instead of encoding it."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        super().__init__()
        self.sent: list[tuple[int, np.ndarray]] = []

    def broadcast_sync(self, detector_slot: int, frame: np.ndarray) -> None:
        """Keep the frame."""
        self.sent.append((detector_slot, frame))


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

    def test_binning_averages_blocks(
        self, detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState]
    ) -> None:
        """A binned image holds the means of the blocks of the full image.

        Args:
            detector_states: The required states from the detector_states fixture.
        """
        camera_state, stage_state, objective_state, illumination_state = detector_states
        manager = VirtualDetectorManager(
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            broadcaster=FrameBroadcaster(),
            config=DetectorConfig(
                sample_type="astigmatism",
                width=128,
                height=128,
                poisson_noise=False,
                read_noise=0.0,
            ),
        )
        full = manager.capture_image(slot=1).data

        detector = manager.update_detector(1, binning=2)
        binned = manager.capture_image(slot=1).data

        expected = full.reshape(64, 2, 64, 2).mean(axis=(1, 3)).astype(np.uint16)
        np.testing.assert_array_equal(binned, expected)
        assert (detector.width, detector.height) == (64, 64)
        assert detector.current_binning == 2
        assert (detector.sensor_width, detector.sensor_height) == (128, 128)

    def test_binning_snaps_to_an_allowed_factor(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Binning snaps to the nearest allowed factor; factors < 1 are rejected."""
        detector = virtual_detector_manager.update_detector(1, binning=3)
        assert detector.current_binning == 2
        with pytest.raises(ValueError, match="binning"):
            virtual_detector_manager.update_detector(1, binning=0)

    def test_roi_cuts_out_the_region(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """The region sets the image and detector size."""
        detector = virtual_detector_manager.update_detector(1, roi=(10, 20, 100, 50))
        assert virtual_detector_manager.capture_image(slot=1).data.shape == (50, 100)
        assert (detector.width, detector.height) == (100, 50)
        assert detector.current_roi == [10, 20, 100, 50]

    def test_roi_is_clamped_and_reset(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """A region is clamped to the sensor; FULL_SENSOR reads the complete sensor again."""
        detector = virtual_detector_manager.update_detector(1, roi=(200, 200, 100, 100))
        assert detector.current_roi == [200, 200, 56, 56]

        detector = virtual_detector_manager.update_detector(1, roi=FULL_SENSOR)
        assert detector.current_roi is None
        assert (detector.width, detector.height) == (256, 256)
        assert virtual_detector_manager.capture_image(slot=1).data.shape == (256, 256)

        with pytest.raises(ValueError, match="negative"):
            virtual_detector_manager.update_detector(1, roi=(-1, 0, 10, 10))

    def test_roi_and_binning_combine(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """The region is cut out first, then binned; a region below the binning is rejected."""
        detector = virtual_detector_manager.update_detector(1, binning=4, roi=(0, 0, 100, 60))
        assert virtual_detector_manager.capture_image(slot=1).data.shape == (15, 25)
        with pytest.raises(ValueError, match="smaller than the binning"):
            virtual_detector_manager.update_detector(1, roi=(0, 0, 2, 2))
        assert detector.current_roi == [0, 0, 100, 60]  # unchanged

    def test_frame_rate(self, virtual_detector_manager: VirtualDetectorManager) -> None:
        """The frame rate is clamped to its range; 0 removes the limit, < 0 is rejected."""
        detector = virtual_detector_manager.update_detector(1, frame_rate=10.0)
        assert detector.current_frame_rate == 10.0
        virtual_detector_manager.update_detector(1, frame_rate=1000.0)
        assert detector.current_frame_rate == 100.0
        virtual_detector_manager.update_detector(1, frame_rate=0)
        assert detector.current_frame_rate is None
        with pytest.raises(ValueError, match="frame rate"):
            virtual_detector_manager.update_detector(1, frame_rate=-1.0)

    def test_detectors_are_described(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Every detector says what it is and can do; its size is the rendered image."""
        for detector in virtual_detector_manager.list_available_detectors():
            assert (detector.manufacturer, detector.model) == ("virtual", "simulated")
            assert detector.serial_number == f"virtual-{detector.slot}"
            assert detector.connection_type is None  # no camera behind it
            assert (detector.pixel_format, detector.data_type) == ("Mono16", "uint16")
            assert (detector.sensor_width, detector.sensor_height) == (256, 256)
            assert (detector.width, detector.height) == (256, 256)  # not the 1024 built in
            assert (detector.current_binning, detector.current_roi) == (1, None)
            assert detector.available_binnings == [1, 2, 4]
            assert (detector.min_frame_rate, detector.max_frame_rate) == (0.1, 100.0)
            assert detector.can_set_roi and not detector.is_recording
            assert detector.recording_file is None

    def test_configured_readout_is_kept(
        self, detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState]
    ) -> None:
        """Binning, region and frame rate of configured detectors are clamped and applied.

        Args:
            detector_states: The required states from the detector_states fixture.
        """
        camera_state, stage_state, objective_state, illumination_state = detector_states
        configured = Detector(
            slot=1,
            is_active=True,
            current_binning=3,
            current_roi=[0, 0, 400, 100],
            current_frame_rate=500.0,
        )
        manager = VirtualDetectorManager(
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            broadcaster=FrameBroadcaster(),
            config=DetectorConfig(width=256, height=256),
            detectors=[configured],
        )
        (detector,) = manager.list_available_detectors()
        assert (detector.current_binning, detector.current_roi) == (2, [0, 0, 256, 100])
        assert detector.current_frame_rate == 100.0
        assert (detector.width, detector.height) == (128, 50)
        assert manager.capture_image(slot=1).data.shape == (50, 128)


class TestSessions:
    """Acquisition sessions and the timing of the images."""

    def test_no_session_before_the_first_image(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Before anything is acquired there is no session; unknown slots are rejected."""
        assert virtual_detector_manager.get_image_info(1) is None
        with pytest.raises(ValueError, match="slot 9"):
            virtual_detector_manager.get_image_info(9)

    def test_snapshot_is_a_session_of_its_own(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Outside of the live stream every snapshot starts a session with its settings."""
        virtual_detector_manager.update_detector(1, exposure_time=0.2, binning=2)
        first = virtual_detector_manager.capture_image(slot=1)
        info = virtual_detector_manager.get_image_info(1)
        assert info is not None
        assert (info.width, info.height, info.channels, info.dtype) == (128, 128, 1, "uint16")
        assert info.recording_file is None
        assert info.settings["exposure_time_ms"] == pytest.approx(200.0)
        assert info.settings["binning"] == 2
        assert first.wall_time_ns == info.wall_time_ns(first.time_ns)

        second = virtual_detector_manager.capture_image(slot=1)
        assert (first.sequence, second.sequence) == (0, 0)
        assert virtual_detector_manager.get_image_info(1) is not info


class TestLiveStream:
    """The live loop: streaming, pacing, stopping and closing."""

    @pytest.fixture
    def live(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> Generator[tuple[VirtualDetectorManager, RecordingBroadcaster], None, None]:
        """The manager with only detector 1 active, its live loop running in a thread.

        Args:
            virtual_detector_manager: The manager fixture.

        Yields:
            The manager and the broadcaster that records what is streamed. Closing the
            manager afterwards must end the loop.
        """
        manager = virtual_detector_manager
        manager.deactivate_detector(2)
        manager.deactivate_detector(3)
        broadcaster = RecordingBroadcaster()
        manager.broadcaster = broadcaster
        thread = threading.Thread(target=manager.acquire_live, daemon=True)
        thread.start()
        yield manager, broadcaster
        manager.close()
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    def test_streams_the_active_detectors(
        self, live: tuple[VirtualDetectorManager, RecordingBroadcaster]
    ) -> None:
        """While acquiring, binned images of the active detector stream in one session."""
        manager, broadcaster = live
        manager.update_detector(1, binning=2)
        manager.state.is_acquiring = True
        wait_until(lambda: len(broadcaster.sent) >= 3)
        assert {slot for slot, _ in broadcaster.sent} == {1}
        assert all(frame.shape == (128, 128) for _, frame in broadcaster.sent)
        assert manager.state.get_detector_for_slot(1).is_recording

        info = manager.get_image_info(1)
        snapshot = manager.capture_image(slot=1)  # part of the live session
        assert snapshot.sequence >= 3
        assert manager.get_image_info(1) is info

    def test_frame_rate_paces_the_stream(
        self, live: tuple[VirtualDetectorManager, RecordingBroadcaster]
    ) -> None:
        """At 20 frames per second about 10 images stream in half a second."""
        manager, broadcaster = live
        manager.update_detector(1, frame_rate=20.0)
        manager.state.is_acquiring = True
        time.sleep(0.5)
        manager.stop_acquire_live()
        assert 2 <= len(broadcaster.sent) <= 12

    def test_stop_acquire_live(
        self, live: tuple[VirtualDetectorManager, RecordingBroadcaster]
    ) -> None:
        """Stopping ends the stream at once; the loop keeps running and can stream again."""
        manager, broadcaster = live
        manager.state.is_acquiring = True
        wait_until(lambda: len(broadcaster.sent) >= 3)
        first_session = manager.get_image_info(1)

        manager.stop_acquire_live()
        assert not manager.state.is_acquiring
        assert not manager.state.get_detector_for_slot(1).is_recording
        count = len(broadcaster.sent)
        time.sleep(0.2)
        assert len(broadcaster.sent) == count  # nothing after stop_acquire_live returned

        manager.state.is_acquiring = True
        wait_until(lambda: len(broadcaster.sent) > count)
        assert manager.get_image_info(1) is not first_session
