"""Building blocks the routines share: z sweeps, fields of view, acquisition steps."""

from typing import Optional

from arkitekt import Task

from newswitch import protocols
from newswitch.models.devices import Detector
from newswitch.models.frames import Frame


def z_sweep(center: float, z_range: float, steps: int) -> list[float]:
    """`steps` (>= 3) planes over `z_range` micrometres, centred on `center`."""
    if steps < 3:
        raise ValueError("a z sweep needs at least 3 planes")
    return [center - z_range / 2 + index * z_range / (steps - 1) for index in range(steps)]


def field_of_view(
    detector: Detector, um_per_px_x: float, um_per_px_y: float
) -> tuple[float, float]:
    """The (width, height) in micrometres a detector sees at a pixel scale."""
    return abs(um_per_px_x) * detector.width, abs(um_per_px_y) * detector.height


def acquire_step(
    acquisition_manager: protocols.AcquisitionManager,
    task: Task,
    done: int,
    total: int,
    message: str,
    slots: Optional[list[int]] = None,
) -> list[Frame]:
    """One step of a routine: a pause point, the frames, the progress (`done` of `total`)."""
    task.pausepoint()
    frames = acquisition_manager.acquire(slots)
    task.progress(int(done / total * 100) if total else 100, message)
    return frames
