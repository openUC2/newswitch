"""Software autofocus routine: sweep Z, score sharpness, move to the best plane.

Port of ImSwitch's AutofocusController core. The metric/sweep core
(`autofocus_sweep`) is a plain function usable from hooks and tests; the
registered `run_autofocus` adds task progress, pause points, and the shared
`AutofocusState`.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from rekuest_next import pausepoint, progress
from rekuest_next.register import register
from scipy import ndimage

from newswitch.protocols.autofocus import AutofocusState
from newswitch.protocols.detector import DetectorManager
from newswitch.protocols.stage import StageManager


def compute_focus_metric(image: np.ndarray, metric: str = "laplacian_variance") -> float:
    """Score the sharpness of an image (higher = sharper)."""
    data = np.asarray(image, dtype=np.float32)
    while data.ndim > 2:
        data = data.mean(axis=0)
    if metric == "laplacian_variance":
        return float(ndimage.laplace(data).var())
    if metric == "intensity_variance":
        return float(data.var())
    raise ValueError(f"Unknown focus metric {metric!r}")


def autofocus_sweep(
    stage: StageManager,
    detector: DetectorManager,
    z_positions: list[float],
    detector_slot: int = 1,
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
        image = detector.capture_image(slot=detector_slot)
        value = compute_focus_metric(image, metric)
        metrics.append(value)
        if value > best_value:
            best_value = value
            best_z = z_position
        if on_step is not None:
            on_step(index, z_position, value)
    return best_z, metrics


@register(locks=["stage_position"])
def run_autofocus(
    stage: StageManager,
    detector: DetectorManager,
    autofocus_state: AutofocusState,
    z_range: float = 20.0,
    steps: int = 11,
    detector_slot: int = 1,
    metric: str = "laplacian_variance",
) -> float:
    """Autofocus: sweep Z around the current position and move to the sharpest plane.

    Args:
        z_range: Total sweep range in micrometers, centered on the current Z.
        steps: Number of Z planes to score (>= 3).
        detector_slot: Detector to read frames from.
        metric: "laplacian_variance" (default) or "intensity_variance".

    Returns:
        The Z position (micrometers) of best focus; the stage is left there.
    """
    if steps < 3:
        raise ValueError("steps must be >= 3")

    z_center = stage.state.z
    z_positions = [z_center - z_range / 2 + index * z_range / (steps - 1) for index in range(steps)]

    autofocus_state.running = True
    autofocus_state.metric_name = metric
    autofocus_state.z_positions = []
    autofocus_state.metrics = []

    def on_step(index: int, z_position: float, value: float) -> None:
        pausepoint()
        autofocus_state.z_positions = autofocus_state.z_positions + [z_position]
        autofocus_state.metrics = autofocus_state.metrics + [value]
        progress(int((index + 1) / steps * 90), f"z={z_position:.2f} metric={value:.1f}")

    try:
        best_z, metrics = autofocus_sweep(
            stage,
            detector,
            z_positions,
            detector_slot=detector_slot,
            metric=metric,
            on_step=on_step,
        )
        stage.move(z=best_z, is_absolute=True)
        autofocus_state.best_z = best_z
        autofocus_state.best_metric = max(metrics)
        progress(100, f"focused at z={best_z:.2f}")
        return best_z
    finally:
        autofocus_state.running = False
