"""Registered functions for the detectors (cameras). Importing this module registers them."""

from rekuest_next.register import register

from newswitch import protocols
from newswitch.protocols import DetectorManager
from newswitch.protocols.core import Frame
from newswitch.protocols.detector import Detector


@register
def capture_image(
    detector: DetectorManager,
    acquisition_manager: protocols.AcquistionManager,
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


@register
def capture_image_and_save_to_disk(
    detector: DetectorManager,
    acquisition_manager: protocols.AcquistionManager,
) -> list[Frame]:
    """
    Capture an image from every active detector and also write it to disk.

    Like capture_image; each image also goes to a recording file of its detector
    (Detector.recording_file). Depending on the frame rate the file may hold an image
    or two next to it. The virtual detector cannot record and fails.
    """
    return acquisition_manager.acquire(save_to_disk=True)


@register
def start_live_view(detector: DetectorManager) -> str:
    """
    Start broadcasting frames to the video WebSocket endpoint.

    Call this to begin streaming frames captured by the detector
    to connected video clients.
    """
    print("Starting live view broadcasting...")
    detector.start_acquire_live(save_to_disk=False)
    return "Broadcasting started. Frames will now be sent to video clients."


@register
def start_live_view_and_save_to_disk(detector: DetectorManager) -> str:
    """
    Start broadcasting frames and write every image of the active detectors to disk.

    Like start_live_view; the images also go to a recording file per detector until
    stop_live_view or until the detector is deactivated. The virtual detector cannot
    record and fails.
    """
    print("Starting live view broadcasting with saving to disk...")
    detector.start_acquire_live(save_to_disk=True)
    return "Broadcasting started. Frames are sent to video clients and written to disk."


@register
def stop_live_view(detector: DetectorManager) -> str:
    """
    Stop broadcasting frames to the video WebSocket endpoint.

    Call this to stop streaming frames captured by the detector
    to connected video clients. Writing to disk ends with it.
    """
    print("Stopping live view broadcasting...")
    detector.stop_acquire_live()
    return "Broadcasting stopped. No frames will be sent to video clients."


@register
def activate_detector(detector: DetectorManager, slot: int) -> None:
    """
    Activate a detector by its slot number.

    Args:
        slot: Detector slot number to activate
    """
    print(f"Activating detector in slot {slot}...")
    detector.activate_detector(slot)
    return None


@register
def deactivate_detector(detector: DetectorManager, slot: int) -> str:
    """
    Deactivate a detector by its slot number.

    Args:
        slot: Detector slot number to deactivate
    """
    print(f"Deactivating detector in slot {slot}...")
    detector.deactivate_detector(slot)
    return f"Detector slot {slot} deactivated"


@register
def update_detector(
    detector: DetectorManager,
    slot: int,
    exposure_time: float | None = None,
    gain: float | None = None,
    frame_rate: float | None = None,
    binning: int | None = None,
    roi: list[int] | None = None,
) -> Detector:
    """
    Update detector settings; a value left out is kept. The detector clamps to its ranges.

    Args:
        slot: Detector slot number
        exposure_time: Exposure time in seconds (optional)
        gain: Gain value (optional)
        frame_rate: Frame rate in frames per second, 0 removes the limit (optional)
        binning: Symmetric binning factor, snapped to an allowed one (optional)
        roi: [x, y, width, height] in unbinned sensor pixels, [0, 0, 0, 0] = full sensor (optional)
    """
    return detector.update_detector(slot, exposure_time, gain, frame_rate, binning, roi)
