"""Taking images, and what a detector does beyond its variables."""

from newswitch import protocols
from newswitch.protocols.frame_sink import FrameSink
from newswitch.models.devices import AxisWindow
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


def set_window(detector: DetectorManager, name: str, windows: list[AxisWindow]) -> None:
    """Read out only a part of a detector's axes: of a camera its sensor, of a scan the field.

    Args:
        name: The detector.
        windows: From where, and how far, on each axis, in unbinned steps; an axis none names
            is read whole, so none reads everything.
    """
    detector.update_detector(name, windows=windows)


def run_detector_loop(detector: DetectorManager, sink: FrameSink) -> None:
    """Background task: the detectors' live loop."""
    detector.acquire_live(sink)


def close_detector(detector: DetectorManager) -> None:
    """Shutdown: end the live loop, and close the cameras."""
    detector.close()
