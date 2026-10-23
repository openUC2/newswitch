"""The detectors: acquiring, the live view, their settings; the acquisition loop and closing them."""

from newswitch.broadcasters import FrameSink
from newswitch import protocols
from newswitch.models.devices import Detector
from newswitch.models.frames import Frame
from newswitch.protocols import (
    DetectorManager,
)
from newswitch.states.detector import CameraState


def capture_image(
    detector: DetectorManager,
    acquisition_manager: protocols.AcquisitionManager,
) -> list[Frame]:
    """
    Capture an image from the detector and save it to disk.

    Args:
        slot: Detector slot number

    Returns a FileHandle that can be used to retrieve the image via the
    /files/{file_path} HTTP endpoint.
    """
    files = (
        acquisition_manager.acquire()
    )  # This will capture an image and save it to disk, returning the file handle

    return files


def start_live_view(camera_state: CameraState) -> str:
    """
    Start broadcasting frames to the video WebSocket endpoint.

    Call this to begin streaming frames captured by the detector
    to connected video clients.
    """

    camera_state.is_acquiring = True
    return "Broadcasting started. Frames will now be sent to video clients."


def stop_live_view(camera_state: CameraState) -> str:
    """
    Stop broadcasting frames to the video WebSocket endpoint.

    Call this to stop streaming frames captured by the detector
    to connected video clients.
    """
    camera_state.is_acquiring = False
    return "Broadcasting stopped. No frames will be sent to video clients."


def activate_detector(detector: DetectorManager, slot: int) -> None:
    """
    Activate a detector by its slot number.

    Args:
        slot: Detector slot number to activate
    """

    detector.activate_detector(slot)
    return None


def deactivate_detector(detector: DetectorManager, slot: int) -> str:
    """
    Deactivate a detector by its slot number.

    Args:
        slot: Detector slot number to deactivate
    """
    detector.deactivate_detector(slot)
    return f"Detector slot {slot} deactivated"


def update_detector(
    detector: DetectorManager,
    slot: int,
    exposure_time: float | None = None,
    gain: float | None = None,
) -> Detector:
    """
    Update detector settings.

    Args:
        slot: Detector slot number
        exposure_time: Exposure time in seconds (optional)
        gain: Gain value (optional)
    """
    return detector.update_detector(slot, exposure_time, gain)


def run_detector_loop(detector: DetectorManager, sink: FrameSink) -> None:
    """Background: the detectors' live loop, streaming to the sink the entrypoint provides."""
    detector.acquire_live(sink)


def close_detector(detector: DetectorManager) -> None:
    """Stop and release the detectors, so camera recordings are complete on disk."""
    detector.close()
