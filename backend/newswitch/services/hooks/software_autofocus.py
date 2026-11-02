"""Software autofocus hook: refocus using the shared autofocus sweep core."""

import logging

from newswitch import protocols
from newswitch.models.hooks import SoftwareAutofocusHook
from newswitch.routines.autofocus import autofocus_sweep
from newswitch.routines.common import focus_range, z_sweep
from newswitch.services.stage import stage_of

logger = logging.getLogger(__name__)


def software_autofocus_hook(hook: SoftwareAutofocusHook, context: protocols.HookContext) -> None:
    """Sweep Z (`hook.z_range` around the current position, `hook.steps` planes), park at best focus:
    on every sample, by the first camera on that sees it.

    Registered only on a microscope with a stage and a detector (`newswitch.microscope.parts`).
    """
    assert context.detector_manager is not None
    instrument = context.values.instrument
    looking: dict[str, str] = {}
    for found in context.detector_manager.list_active_detectors():
        if found.delivers_images():
            looking.setdefault(instrument.sample_of(found.name), found.name)
    for detector in looking.values():
        _refocus(hook, context, detector)


def _refocus(hook: SoftwareAutofocusHook, context: protocols.HookContext, detector: str) -> None:
    """The sweep of `software_autofocus_hook`, by `detector`, on what focuses it."""
    assert context.detector_manager is not None
    stage = stage_of(context.values, detector)
    steps = max(3, hook.steps)
    z_range = hook.z_range
    if z_range is None:
        z_range = focus_range(context.optics_manager.depth_of_field_um(detector), steps)
    z_positions = z_sweep(stage.state.z, z_range, steps)
    best_z, metrics = autofocus_sweep(stage, context.detector_manager, z_positions, detector)
    stage.move(z=best_z, is_absolute=True)
    context.optics_manager.found_focus(detector)
    logger.info("Autofocus hook: best z=%.2f (metric %.1f)", best_z, max(metrics))
