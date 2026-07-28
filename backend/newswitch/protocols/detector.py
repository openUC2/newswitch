"""
Detector Manager Protocol

Defines the protocol for detector/camera control and associated state.
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable, TYPE_CHECKING
import numpy as np
from rekuest_next.agents.context import context
from rekuest_next import model, state
from enum import Enum
from newswitch.protocols.base import Manager
from newswitch.utils.units import PhysicalValue

if TYPE_CHECKING:
    from newswitch.broadcasters import FrameBroadcaster


class Colormap(str, Enum):
    """Enumeration of colormap options."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"


@model
@dataclass
class Detector:
    """Shared state for detector parameters."""

    slot: int = 1
    name: str = "Virtual Camera"
    width: int = 512
    height: int = 512
    is_active: bool = False
    current_exposure_time: float = 0.1  # seconds
    current_gain: float = 1.0
    current_colormap: Colormap = Colormap.RED

    pixel_size_um: float = 6.5
    preset_exposure_times: list[float] = field(
        default_factory=lambda: [0.01, 0.1, 0.5, 1.0, 2.0, 5.0]
    )
    max_exposure_time: float = 10.0
    min_exposure_time: float = 0.001
    max_gain: float = 100.0
    min_gain: float = 0.0
    is_acquiring: bool = False
    data_type: str = "uint8"

    ## TODO: Consider using PhysicalValue for exposure_time and gain to encapsulate units and constraints.
    # exposure_time: PhysicalValue = field(default_factory=lambda: PhysicalValue(value=0.1, unit="s"))
    # gain: PhysicalValue = field(default_factory=lambda: PhysicalValue(value=1.0, unit=""))


@state(required_locks=["camera_parameters"])
class CameraState:
    """Shared state for camera parameters.

    Default values are set to produce visible images with default illumination.
    Higher exposure and gain ensure the captured images have sufficient
    brightness after uint16→uint8 conversion for PNG output.
    """

    is_acquiring: bool = False
    detectors: list[Detector] = field(default_factory=lambda: [])

    def get_active_detectors(self) -> list[Detector]:
        """Get the currently active detectors."""
        active_detectors: list[Detector] = []
        for detector in self.detectors:
            if detector.is_active:
                active_detectors.append(detector)
        return active_detectors

    def get_detector_for_slot(self, slot: int) -> Detector:
        """Get the detector for a specific slot, if it exists."""
        for detector in self.detectors:
            if detector.slot == slot:
                return detector
        raise ValueError(f"No detector found for slot {slot}")


@context(locks=["camera_parameters"])
@runtime_checkable
class DetectorManager(Manager, Protocol):
    """Protocol defining the interface for detector/camera managers."""

    state: CameraState
    broadcaster: "FrameBroadcaster"

    def capture_image(self, slot: int) -> np.ndarray:
        """Capture a single image from a specific detector.

        Args:
            slot: Detector slot number.
        """
        ...

    def activate_detector(self, slot: int) -> Detector:
        """Activate a detector by its slot number.

        Args:
            slot: Detector slot number from available_detectors.

        Returns:
            The activated detector's state.
        """
        ...

    def deactivate_detector(self, slot: int) -> None:
        """Deactivate a detector by its slot number.

        Args:
            slot: Detector slot number to deactivate.
        """
        ...

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

        Returns:
            The updated detector state.
        """
        ...

    def get_detector_state(self, slot: int) -> Optional[Detector]:
        """Get the state of a detector.

        Args:
            slot: Detector slot number.

        Returns:
            The detector if found, None otherwise.
        """
        ...

    def list_available_detectors(self) -> list[Detector]:
        """List all available detectors.

        Returns:
            List of available detector configurations.
        """
        ...

    def list_active_detectors(self) -> list[Detector]:
        """List all active detectors.

        Returns:
            List of active detectors.
        """
        ...

    def acquire_live(self) -> None:
        """Start continuous acquisition mode."""
        ...
