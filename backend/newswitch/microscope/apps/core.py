"""What every microscope has: files, hooks, the expanse, calibration, light paths."""

from typing import Tuple

from arkitekt import App

from newswitch.actions import core
from newswitch.protocols.frame_sink import FrameSink
from newswitch.microscope import locks
from newswitch.microscope.apps import models
from newswitch.microscope.run import Run
from newswitch.protocols.cache import CacheManager
from newswitch.protocols.calibration import CalibrationManager
from newswitch.protocols.dataset_store import DatasetStore
from newswitch.protocols.expanse import ExpanseManager
from newswitch.protocols.hook_manager import HookManager
from newswitch.protocols.io import IOManager
from newswitch.protocols.optics import OpticsManager
from newswitch.protocols.metadata import MetadataManager
from newswitch.states.calibration import CalibrationState
from newswitch.states.expanse import ExpanseState
from newswitch.states.hooks import HookState
from newswitch.states.io import IOState
from newswitch.states.optics import OpticsState
from newswitch.states.space import SpaceState
from newswitch.services.space import SpaceManager

app = App("newswitch", app_context=Run)
app.registry.merge(models.app.registry)

app.register_state(IOState, required_locks=[locks.IO])
app.register_state(HookState, required_locks=[locks.HOOKS])
app.register_state(ExpanseState, required_locks=[locks.EXPANSE])
app.register_state(CalibrationState)
app.register_state(OpticsState)
app.register_state(SpaceState)
app.register_context(IOManager, locks=[locks.IO])
app.register_context(HookManager, locks=[locks.HOOKS])
app.register_context(ExpanseManager, locks=[locks.EXPANSE])
app.register_context(CalibrationManager)
app.register_context(OpticsManager)
app.register_context(MetadataManager)
app.register_context(SpaceManager)
app.register_context(CacheManager, locks=[locks.CACHE])
app.register_context(FrameSink)  # provided by the entrypoint
app.register_context(DatasetStore)  # provided by the entrypoint


async def provide_core(
    run: Run,
) -> Tuple[
    IOManager,
    IOState,
    HookManager,
    HookState,
    ExpanseState,
    ExpanseManager,
    CalibrationState,
    CalibrationManager,
    OpticsState,
    OpticsManager,
    MetadataManager,
    SpaceState,
    SpaceManager,
    CacheManager,
]:
    """What every microscope has."""
    m = run.microscope
    return (
        m.io,
        m.io_state,
        m.hooks,
        m.hook_state,
        m.expanse_state,
        m.expanse,
        m.calibration_state,
        m.calibration,
        m.optics_state,
        m.optics,
        m.metadata,
        m.space_state,
        m.space,
        m.cache,
    )


app.register_startup(provide_core)
app.register_action(core.clear_expanse)
