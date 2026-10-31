"""Taking images, and what a detector does beyond its variables."""

from newswitch import protocols
from newswitch.broadcasters import FrameSink
from newswitch.models.frames import Frame
from newswitch.protocols import DetectorManager
from newswitch.states.detector import DetectorState


def capture_image(
    detector: DetectorManager,
    acquisition_manager: protocols.AcquisitionManager,
    name: str | None = None,
) -> list[Frame]:
    """Take an image with one detector, or with each that is on.

    Args:
        name: The detector.

    Returns:
        The frames taken, cached and added to the expanse.
    """
    return acquisition_manager.acquire(None if name is None else [name])


def start_live_view(detector_state: DetectorState) -> str:
    """Start streaming every active detector.

    Returns:
        Status message.
    """
    detector_state.is_acquiring = True
    return "Live view started"


def stop_live_view(detector_state: DetectorState) -> str:
    """Stop streaming.

    Returns:
        Status message.
    """
    detector_state.is_acquiring = False
    return "Live view stopped"


def activate_detector(detector: DetectorManager, name: str) -> None:
    """Turn a detector on.

    Args:
        name: The detector.
    """
    detector.activate_detector(name)


def deactivate_detector(detector: DetectorManager, name: str) -> str:
    """Turn a detector off.

    Args:
        name: The detector.
    """
    detector.deactivate_detector(name)
    return f"Detector {name} deactivated"


def set_region(
    detector: DetectorManager, name: str, x: int, y: int, width: int, height: int
) -> None:
    """Read out only a part of a detector's sensor; a width or height of 0 is all of it.

    Args:
        name: The detector.
        x: Where it starts, in unbinned sensor pixels.
        y: Where it starts, in unbinned sensor pixels.
        width: How wide it is.
        height: How high it is.
    """
    detector.update_detector(name, roi=(x, y, width, height))


def run_detector_loop(detector: DetectorManager, sink: FrameSink) -> None:
    """Background task: the detectors' live loop."""
    detector.acquire_live(sink)


def close_detector(detector: DetectorManager) -> None:
    """Shutdown: end the live loop, and close the cameras."""
    detector.close()
