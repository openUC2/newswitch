"""Tests for the VirtualDetectorManager using protocol-based testing.

This module tests the VirtualDetectorManager implementation to ensure it correctly
implements the DetectorManager protocol, including detector activation/deactivation,
frame generation, illumination effects, and camera settings.
"""

from typing import Generator

import numpy as np
import pytest
from rekuest_next.state.lock import acquired_locks

from newswitch.broadcasters import FrameBroadcaster
from newswitch.managers.virtual import VirtualDetectorManager, VirtualSetup
from newswitch.managers.virtual.virtual_detector import DetectorConfig
from newswitch.managers.virtual.virtual_setup import SceneConfig
from newswitch.protocols import CameraState, IlluminationState, StageState
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
    setup = VirtualSetup(
        stage_state=stage_state,
        objective_state=objective_state,
        illumination_state=illumination_state,
        config=SceneConfig(sample_type="cells"),
    )
    manager = VirtualDetectorManager(
        camera_state=camera_state,
        broadcaster=broadcaster,
        frame_source=setup,
        config=DetectorConfig(width=256, height=256),
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
    setup = VirtualSetup(
        stage_state=stage_state,
        objective_state=objective_state,
        illumination_state=illumination_state,
        config=SceneConfig(sample_type="astigmatism"),
    )
    manager = VirtualDetectorManager(
        camera_state=camera_state,
        broadcaster=broadcaster,
        frame_source=setup,
        config=DetectorConfig(width=256, height=256),
    )
    # Activate a detector for testing
    manager.activate_detector(1)
    yield manager


class TestDetectorProtocolCompliance:
    """Test that VirtualDetectorManager implements the DetectorManager protocol."""

    def test_capture_image_returns_array(
        self, virtual_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that capture_image returns a numpy array with correct shape and dtype."""
        frame = virtual_detector_manager.capture_image(slot=1)

        assert isinstance(frame, np.ndarray)
        assert frame.shape == (256, 256)
        assert frame.dtype == np.uint16

    def test_activate_detector(
        self, detector_states: tuple[CameraState, StageState, ObjectiveState, IlluminationState]
    ) -> None:
        """Test that `activate_detector()` keeps the requested detector active.

        Args:
            detector_states: The required states from the detector_states fixture.
        """
        camera_state, stage_state, objective_state, illumination_state = detector_states
        broadcaster = FrameBroadcaster()
        setup = VirtualSetup(
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            config=SceneConfig(sample_type="cells"),
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            broadcaster=broadcaster,
            frame_source=setup,
            config=DetectorConfig(width=256, height=256),
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
        stage_state = detector.frame_source.stage_state

        frame1 = detector.capture_image(slot=1)

        stage_state.x = 200.0
        stage_state.y = 150.0
        frame2 = detector.capture_image(slot=1)

        # Frames should be different (not exactly equal)
        assert not np.array_equal(frame1, frame2)

    def test_astigmatism_frame_generation(
        self, astigmatism_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test astigmatism mode produces valid frames."""
        detector = astigmatism_detector_manager

        frame = detector.capture_image(slot=1)

        assert isinstance(frame, np.ndarray)
        assert frame.shape == (256, 256)
        assert frame.dtype == np.uint16

    def test_astigmatism_changes_with_z(
        self, astigmatism_detector_manager: VirtualDetectorManager
    ) -> None:
        """Test that astigmatism frame changes with z position."""
        detector = astigmatism_detector_manager
        stage_state = detector.frame_source.stage_state

        stage_state.z = 0.0
        frame_z0 = detector.capture_image(slot=1)

        stage_state.z = 2.0
        frame_z2 = detector.capture_image(slot=1)

        stage_state.z = -2.0
        frame_z_neg2 = detector.capture_image(slot=1)

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
        setup = VirtualSetup(
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            config=SceneConfig(
                sample_type="astigmatism",
                poisson_noise=False,
                read_noise=0.0,
            ),
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            broadcaster=broadcaster,
            frame_source=setup,
            config=DetectorConfig(width=128, height=128),
        )
        detector.activate_detector(1)

        # Low intensity - update the active illumination for testing
        illumination_state.illuminations[0].intensity = 100.0
        frame_low = detector.capture_image(slot=1)

        # High intensity
        illumination_state.illuminations[0].intensity = 1000.0
        frame_high = detector.capture_image(slot=1)

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
        setup = VirtualSetup(
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            config=SceneConfig(
                sample_type="astigmatism",
                poisson_noise=False,
                read_noise=0.0,
            ),
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            broadcaster=broadcaster,
            frame_source=setup,
            config=DetectorConfig(width=128, height=128),
        )
        detector.activate_detector(1)

        detector.update_detector(slot=1, exposure_time=0.01)
        frame_short = detector.capture_image(slot=1)

        detector.update_detector(slot=1, exposure_time=1.0)
        frame_long = detector.capture_image(slot=1)

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
        setup = VirtualSetup(
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            config=SceneConfig(
                sample_type="astigmatism",
                poisson_noise=False,
                read_noise=0.0,
            ),
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            broadcaster=broadcaster,
            frame_source=setup,
            config=DetectorConfig(width=128, height=128),
        )
        detector.activate_detector(1)

        detector.update_detector(slot=1, gain=0.0)
        frame_low_gain = detector.capture_image(slot=1)

        detector.update_detector(slot=1, gain=50.0)
        frame_high_gain = detector.capture_image(slot=1)

        # Higher gain should produce brighter frame
        assert frame_high_gain.mean() > frame_low_gain.mean()
