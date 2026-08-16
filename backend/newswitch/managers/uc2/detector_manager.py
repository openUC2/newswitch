"""
UC2 Detector Manager

Detector manager for real openUC2 camera hardware.

This is a skeleton: it fixes the shape of the ``DetectorManager`` protocol for the
hardware case, but the camera driver layer (``newswitch/uc2_devices``) does not
exist on this branch, so every method that would actually touch a camera raises
``NotImplementedError``. The pure state queries are implemented, by delegating to
``CameraState``.

Note what the constructor does *not* take: no stage, objective, illumination or
filter bank state. A real detector reads photons - the optical scene reaches it
through physics, not through injected state. Only the virtual stack needs a
``VirtualSetup`` to model that coupling explicitly.
"""

from typing import TYPE_CHECKING, Optional

import numpy as np

from newswitch.protocols.detector import CameraState, Detector

if TYPE_CHECKING:  # only needed for type hints, not at runtime
    from newswitch.broadcasters import FrameBroadcaster

_NO_DRIVER = (
    "The UC2 camera driver layer (newswitch/uc2_devices) is not available on this "
    "branch, so {action} cannot be performed."
)


class Uc2DetectorManager:
    """Detector manager backed by real UC2 camera hardware."""

    state: CameraState
    broadcaster: "FrameBroadcaster"

    def __init__(
        self,
        camera_state: CameraState,
        broadcaster: "FrameBroadcaster",
    ) -> None:
        """
        Initialize the UC2 detector manager.

        Args:
            camera_state: Shared state for camera parameters.
            broadcaster: Frame broadcaster for video streaming.
        """
        self.state = camera_state
        self.broadcaster = broadcaster

    # ------------------------------------------------------------------ #
    # pure state queries - no hardware needed, delegate to CameraState
    # ------------------------------------------------------------------ #
    def get_detector_state(self, slot: int) -> Optional[Detector]:
        """
        Get the state of a detector.

        Args:
            slot: Detector slot number.

        Returns:
            The detector if found, None otherwise.
        """
        try:
            return self.state.get_detector_for_slot(slot)
        except ValueError:
            return None

    def list_available_detectors(self) -> list[Detector]:
        """
        List all available detectors.

        Returns:
            List of detector configurations.
        """
        return self.state.detectors

    def list_active_detectors(self) -> list[Detector]:
        """
        List all active detectors.

        Returns:
            List of active detectors.
        """
        return self.state.get_active_detectors()

    # ------------------------------------------------------------------ #
    # hardware-facing - awaiting the camera driver layer
    # ------------------------------------------------------------------ #
    def capture_image(self, slot: int) -> np.ndarray:
        """Capture a single image from a specific detector.

        Args:
            slot: Detector slot number.
        """
        raise NotImplementedError(_NO_DRIVER.format(action="image capture"))

    def activate_detector(self, slot: int) -> Detector:
        """Activate a detector by its slot number.

        Args:
            slot: Detector slot number to activate.
        """
        raise NotImplementedError(_NO_DRIVER.format(action="detector activation"))

    def deactivate_detector(self, slot: int) -> None:
        """Deactivate a detector by its slot number.

        Args:
            slot: Detector slot number to deactivate.
        """
        raise NotImplementedError(_NO_DRIVER.format(action="detector deactivation"))

    def update_detector(
        self,
        slot: int,
        exposure_time: Optional[float] = None,
        gain: Optional[float] = None,
    ) -> Detector:
        """Update detector settings.

        Args:
            slot: Detector slot number.
            exposure_time: New exposure time in seconds (if provided).
            gain: New gain value (if provided).
        """
        raise NotImplementedError(_NO_DRIVER.format(action="detector updates"))

    def acquire_live(self) -> None:
        """Start continuous acquisition mode."""
        raise NotImplementedError(_NO_DRIVER.format(action="live acquisition"))
