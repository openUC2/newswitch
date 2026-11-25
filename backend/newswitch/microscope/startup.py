"""The startup hooks of the microscope: what each part hands out, from the `Run` it is given.

Plain functions, registered by name by the app that serves them (``app.py``; FastAPI through the part
registries of `newswitch.microscope.apps`). A context a hook returns as None (a part the instrument
lacks) is not provided: arkitekt fails an action that needs it when it is called. The annotations
name the contexts and states, which arkitekt reads; it takes no Optional there.
"""

from typing import Tuple

from newswitch.microscope.run import Run
from newswitch.protocols.acquisition import AcquisitionManager
from newswitch.protocols.cache import CacheManager
from newswitch.protocols.calibration import CalibrationManager
from newswitch.protocols.detector import DetectorManager
from newswitch.protocols.expanse import ExpanseManager
from newswitch.protocols.hook_manager import HookManager
from newswitch.protocols.io import IOManager
from newswitch.protocols.metadata import MetadataManager
from newswitch.protocols.optics import OpticsManager
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.services.space import SpaceManager
from newswitch.services.values import Values
from newswitch.states.autofocus import AutofocusState
from newswitch.states.calibration import CalibrationState
from newswitch.states.detector import DetectorState
from newswitch.states.expanse import ExpanseState
from newswitch.states.hooks import HookState
from newswitch.states.io import IOState
from newswitch.states.mount_calibration import MountCalibrationState
from newswitch.states.optics import OpticsState
from newswitch.states.space import SpaceState
from newswitch.states.uc2 import UC2State
from newswitch.states.values import MoveState, SourceState, SwapState, TuneState


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
    # TODO: build the microscope here
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


async def provide_values(
    run: Run,
) -> Tuple[Values, MoveState, SwapState, TuneState, SourceState]:
    """Every variable (no `Values` without an instrument)."""
    m = run.microscope
    return m.values, m.move_state, m.swap_state, m.tune_state, m.source_state  # pyright: ignore[reportReturnType]


async def provide_detector(run: Run) -> Tuple[DetectorManager, DetectorState, AcquisitionManager]:
    """The detectors, and acquiring images with them (no managers without a detector)."""
    m = run.microscope
    return m.detector, m.detector_state, m.acquisition  # pyright: ignore[reportReturnType]


async def provide_focus(run: Run) -> AutofocusState:
    """The autofocus state."""
    return run.microscope.autofocus_state


async def provide_uc2(run: Run) -> Tuple[UC2BusManager, UC2State]:
    """The UC2 board (no bus without one)."""
    return run.microscope.uc2_bus, run.microscope.uc2_state  # pyright: ignore[reportReturnType]


async def provide_mount_calibration(run: Run) -> MountCalibrationState:
    """The holder calibration: of the first sample whose description says how its holder is
    calibrated (empty, when none does)."""
    instrument = run.instrument
    for sample in [] if instrument is None else instrument.samples():
        holding = instrument.sample_holder(sample)
        calibration = holding.calibration
        if calibration is None:
            continue
        mounted = holding.holders[calibration.holder]
        return MountCalibrationState(
            sample=sample,
            holder=calibration.holder,
            holder_kind=mounted.holder.description.split(",")[0].split(".")[0],
            slide=calibration.slide.description.split(",")[0].split(".")[0],
            at=calibration.at,
            mark=calibration.mark,
            mount_x_mm=mounted.mount.x,
            mount_y_mm=mounted.mount.y,
        )
    return MountCalibrationState()
