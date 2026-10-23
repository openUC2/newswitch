"""The camera state: the detectors and whether they acquire."""

from dataclasses import dataclass, field

from newswitch.models.devices import Detector


@dataclass
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
