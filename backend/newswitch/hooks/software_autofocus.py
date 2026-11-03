"""Software autofocus hook: refocus using the shared autofocus sweep core."""

import logging
from newswitch import protocols
from newswitch.routines.autofocus import autofocus_sweep

logger = logging.getLogger(__name__)

DEFAULT_Z_RANGE = 20.0  # micrometers, centered on the current Z
DEFAULT_STEPS = 11


def software_autofocus_hook(hook: protocols.Hook, context: protocols.HookContext) -> None:
    """Hook implementation: sweep Z around the current position, park at best focus."""
    stage = context.stage_manager
    z_center = stage.state.z
    z_positions = [
        z_center - DEFAULT_Z_RANGE / 2 + index * DEFAULT_Z_RANGE / (DEFAULT_STEPS - 1)
        for index in range(DEFAULT_STEPS)
    ]
    best_z, metrics = autofocus_sweep(stage, context.detector_manager, z_positions)
    stage.move(z=best_z, is_absolute=True)
    logger.info("Autofocus hook: best z=%.2f (metric %.1f)", best_z, max(metrics))
