"""Routine for scanning a rectangular region as a tiled grid of stage positions."""

import logging
import math
from typing import Annotated

from arkitekt import Description, Task

from newswitch import protocols
from newswitch.models.acquisition import (
    ScanOrder,
)
from newswitch.models.frames import Frame
from newswitch.routines.common import acquire_step

logger = logging.getLogger(__name__)


def scan_region(
    light_path_manager: protocols.LightPathManager,
    acquisition_manager: protocols.AcquisitionManager,
    metadata_manager: protocols.MetadataManager,
    detector_manager: protocols.DetectorManager,
    stage_manager: protocols.StageManager,
    task: Task,
    scan_order: ScanOrder,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    overlap: float = 0.1,
    detector_slot: Annotated[
        int,
        Description(
            "The detector to calculate the FOV for (all other detectors will follow). If None, use the first active detector."
        ),
    ]
    | None = None,
) -> list[Frame]:
    """Scan a rectangular region of the stage tile by tile.

    The region from (start_x, start_y) to (end_x, end_y) (stage micrometres) is covered
    with fields of view of the detector (`detector_slot`, else the first active one),
    overlapping by `overlap`, visited in `scan_order`; every active detector acquires a
    frame at each tile.

    Returns:
        The frames, in the order acquired.
    """

    logger.info(
        "Scanning (%s, %s)..(%s, %s) in %s order", start_x, start_y, end_x, end_y, scan_order
    )

    # 1. Calculate FOV for the current objective and detector configuration
    if detector_slot is not None:
        current_detector = detector_manager.state.get_detector_for_slot(detector_slot)
    else:
        active_detectors = detector_manager.state.get_active_detectors()
        if not active_detectors:
            raise ValueError("No active detectors found.")
        current_detector = active_detectors[0]

    current_light_path = light_path_manager.get_light_path_for_detector(
        detector_slot=current_detector.slot
    )
    metadata = metadata_manager.get_metadata_for_light_path(current_light_path)

    # The field of view of its light path (calibrated, else nominal): positive whatever the
    # camera's orientation
    fov_width, fov_height = abs(metadata.fov_width), abs(metadata.fov_height)
    logger.info("Field of view: %.2f x %.2f um", fov_width, fov_height)

    # 2. Define Region Bounds, ensuring min/max are correctly assigned regardless of drag direction
    min_x, max_x = min(start_x, end_x), max(start_x, end_x)
    min_y, max_y = min(start_y, end_y), max(start_y, end_y)

    # 3. Calculate Step Sizes (Clamp overlap to 0.99 max to prevent infinite loops)
    safe_overlap = min(overlap, 0.99)
    step_x = fov_width * (1.0 - safe_overlap)
    step_y = fov_height * (1.0 - safe_overlap)

    # Calculate how many columns and rows are needed to cover the drawn area
    cols = max(1, math.ceil((max_x - min_x - fov_width) / step_x) + 1)
    rows = max(1, math.ceil((max_y - min_y - fov_height) / step_y) + 1)

    # Center of the user-drawn region
    region_center_x = (min_x + max_x) / 2.0
    region_center_y = (min_y + max_y) / 2.0

    # Total physical dimensions of the resulting grid
    total_grid_width = (cols - 1) * step_x + fov_width
    total_grid_height = (rows - 1) * step_y + fov_height

    # Shift the starting point so the grid is perfectly centered over the drawn region
    start_grid_x = region_center_x - (total_grid_width / 2.0) + (fov_width / 2.0)
    start_grid_y = region_center_y - (total_grid_height / 2.0) + (fov_height / 2.0)

    # 4. Generate the path
    path_points: list[tuple[float, float]] = []

    if scan_order in (ScanOrder.SNAKE_ROW, ScanOrder.RASTER_ROW):
        for r in range(rows):
            y = start_grid_y + r * step_y
            is_reverse = (scan_order == ScanOrder.SNAKE_ROW) and (r % 2 != 0)

            for c in range(cols):
                actual_c = (cols - 1 - c) if is_reverse else c
                x = start_grid_x + actual_c * step_x
                path_points.append((x, y))
    else:
        for c in range(cols):
            x = start_grid_x + c * step_x
            is_reverse = (scan_order == ScanOrder.SNAKE_COL) and (c % 2 != 0)

            for r in range(rows):
                actual_r = (rows - 1 - r) if is_reverse else r
                y = start_grid_y + actual_r * step_y
                path_points.append((x, y))

    logger.info("%d cols x %d rows: %d tiles", cols, rows, len(path_points))

    acquired_images: list[Frame] = []
    total = len(path_points)
    for i, (tgt_x, tgt_y) in enumerate(path_points):
        stage_manager.move(x=tgt_x, y=tgt_y, is_absolute=True)
        acquired_images.extend(
            acquire_step(acquisition_manager, task, i + 1, total, f"Acquired tile {i + 1}/{total}")
        )

    return acquired_images
