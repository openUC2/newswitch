"""Software autofocus routine: sweep Z, score sharpness, move to the best plane.

Port of ImSwitch's AutofocusController core. The metric/sweep core
(`autofocus_sweep`) is a plain function usable from hooks and tests; the
registered `run_autofocus` adds task progress, pause points, and the shared
`AutofocusState`.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from arkitekt import Task
from scipy import ndimage

from newswitch.protocols.detector import DetectorManager
from newswitch.protocols.optics import OpticsManager
from newswitch.routines.common import focus_range, z_sweep
from newswitch.services.stage import Stage, stage_of
from newswitch.services.values import Values
from newswitch.states.autofocus import AutofocusState

#: The Gaussian (px) the Laplacian focus metric is taken over, against pixel noise.
FOCUS_METRIC_SIGMA = 1.0


def compute_focus_metric(image: np.ndarray, metric: str = "laplacian_variance") -> float:
    """Score the sharpness of an image (higher = sharper).

    ``laplacian_variance`` is the variance of the image's Laplacian of Gaussian: the small
    Gaussian (1 px) keeps shot and read noise, which is sharp at every focus, from
    drowning the sample's edges. ``intensity_variance`` is the plain image variance.
    """
    data = np.asarray(image, dtype=np.float32)
    while data.ndim > 2:
        data = data.mean(axis=0)
    if metric == "laplacian_variance":
        return float(ndimage.gaussian_laplace(data, sigma=FOCUS_METRIC_SIGMA).var())
    if metric == "intensity_variance":
        return float(data.var())
    raise ValueError(f"Unknown focus metric {metric!r}")


def autofocus_sweep(
    stage: Stage,
    detector: DetectorManager,
    z_positions: list[float],
    detector_name: str | None = None,
    metric: str = "laplacian_variance",
    on_step: Optional[Callable[[int, float, float], None]] = None,
) -> tuple[float, list[float]]:
    """Visit each absolute Z, score sharpness, and return (best_z, metrics).

    Plain core shared by the registered routine, the autofocus hook, and
    tests — no task-context calls in here.
    """
    metrics: list[float] = []
    best_z = z_positions[0]
    best_value = -np.inf
    for index, z_position in enumerate(z_positions):
        stage.move(z=z_position, is_absolute=True)
        image = detector.capture_image(detector_name).data
        value = compute_focus_metric(image, metric)
        metrics.append(value)
        if value > best_value:
            best_value = value
            best_z = z_position
        if on_step is not None:
            on_step(index, z_position, value)
    return best_z, metrics


def _first_camera(detector: DetectorManager, values: Values) -> str:
    """The first camera that is on, when those that are on see one sample.

    Raises:
        ValueError: None is on; or they see several samples, and which to focus is not said.
    """
    cameras = [d.name for d in detector.list_active_detectors() if d.delivers_images()]
    if not cameras:
        raise ValueError("No camera is on to focus with")
    seen = sorted({values.instrument.sample_of(name) for name in cameras})
    if len(seen) > 1:
        raise ValueError(f"The cameras on see the samples {seen}: name the detector to focus with")
    return cameras[0]


def run_autofocus(
    values: Values,
    detector: DetectorManager,
    autofocus_state: AutofocusState,
    optics: OpticsManager,
    task: Task,
    z_range: Optional[float] = None,
    steps: int = 11,
    detector_name: Optional[str] = None,
    focus: Optional[str] = None,
    metric: str = "laplacian_variance",
) -> float:
    """Autofocus: sweep Z around the current position and move to the sharpest plane.

    Args:
        z_range: Total sweep range in micrometers, centered on the current Z. By default, from
            how deep the detector's objective sees sharply.
        steps: Number of Z planes to score (>= 3).
        detector_name: The detector to read frames from; by default, the first camera that is on,
            when the cameras that are on see one sample.
        focus: What to focus with, if several things do.
        metric: "laplacian_variance" (default) or "intensity_variance".

    Returns:
        The Z position (micrometers) of best focus; the stage is left there.
    """
    name = detector_name or _first_camera(detector, values)
    stage = stage_of(values, name, focus)
    if stage.z_move is None:
        raise ValueError(f"Nothing here focuses {name}")
    if z_range is None:
        z_range = focus_range(optics.depth_of_field_um(name), steps)
    z_positions = z_sweep(stage.state.z, z_range, steps)

    autofocus_state.running = True
    autofocus_state.metric_name = metric
    autofocus_state.z_positions = []
    autofocus_state.metrics = []

    def on_step(index: int, z_position: float, value: float) -> None:
        task.pausepoint()
        autofocus_state.z_positions.append(z_position)
        autofocus_state.metrics.append(value)
        task.progress(int((index + 1) / steps * 90), f"z={z_position:.2f} metric={value:.1f}")

    try:
        best_z, metrics = autofocus_sweep(
            stage,
            detector,
            z_positions,
            detector_name=name,
            metric=metric,
            on_step=on_step,
        )
        stage.move(z=best_z, is_absolute=True, task=task)
        optics.found_focus(name)
        autofocus_state.best_z = best_z
        autofocus_state.best_metric = max(metrics)
        task.progress(100, f"focused at z={best_z:.2f}")
        return best_z
    finally:
        autofocus_state.running = False
