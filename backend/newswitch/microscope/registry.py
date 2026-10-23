"""The app registry of one newswitch, created and filled for one device configuration.

Everything newswitch declares is a plain function or class in its own module (actions in
`newswitch.actions.<part>`, routines in `newswitch.routines`, states in `newswitch.states`,
locks in `newswitch.microscope.locks`); nothing registers itself. `create_registry` creates a fresh `App`, imports what to register by
name, and registers it here, explicitly, according to the device configuration:

1. the models (types that travel in arguments, returns and states), always;
2. the core every microscope has (files, the expanse, calibration, light paths, hooks);
3. one group per part the configuration has (stage, illumination, detector, objective,
   filter bank, UC2 board): its states and contexts, the startup hook that provides them,
   its actions and background tasks;
4. the actions that need several parts, when all of them are there;

How it is served is not registered here. The detectors stream to a `FrameSink` context
(registered here, a protocol); ``main_fastapi.py`` and ``main_arkitekt.py`` each provide it
their way (the websocket live view's `FrameBroadcaster`, a lovekit sink), pass in the
arkitekt services they need, and register the UI they show (``ui`` or ``agent_ui``,
checked strictly against what was registered here).

The startup hooks are defined here, next to what they provide. arkitekt hands a startup
hook only the app context, and the parts depend on each other, so the hooks hand out the
objects of one `build_microscope`, made on the first hook and kept in this function's
closure. Without a configuration only the models and the core are registered. Every
registry has its own build: two apps share nothing.
"""

from typing import Any, Sequence, Tuple

from arkitekt import App, OptimisticInput, Service

from newswitch import models
from newswitch.bloks import ASSET_ROOT
from newswitch.broadcasters import FrameSink
from newswitch.microscope import locks
from newswitch.actions import core, detector, filter_bank, illumination, objective, stage, uc2
from newswitch.settings import Settings
from newswitch.config_io import NewswitchConfig
from newswitch.microscope.parts import (
    Microscope,
    build_microscope,
    configured_parts,
    save_device_config,
)
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.devices import Detector, Filter, Illumination, ObjectiveLens
from newswitch.models.hooks import RegisteredHook, SoftwareAutofocusHook, ZCalibrationHook
from newswitch.protocols.acquisition import AcquisitionManager
from newswitch.protocols.cache import CacheManager
from newswitch.protocols.calibration import CalibrationManager
from newswitch.protocols.detector import DetectorManager
from newswitch.protocols.expanse import ExpanseManager
from newswitch.protocols.filter_bank import FilterBankManager
from newswitch.protocols.hook_manager import HookManager
from newswitch.protocols.illumination import IlluminationManager
from newswitch.protocols.io import IOManager
from newswitch.protocols.light_path import LightPathManager
from newswitch.protocols.metadata import MetadataManager
from newswitch.protocols.objective import ObjectiveManager
from newswitch.protocols.stage import StageManager
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.routines import multidimensional_acquisition as mda
from newswitch.routines.autofocus import run_autofocus
from newswitch.routines.calibration import calibrate_light_path
from newswitch.routines.region_scan import scan_region
from newswitch.states.autofocus import AutofocusState
from newswitch.states.calibration import CalibrationState
from newswitch.states.detector import CameraState
from newswitch.states.expanse import ExpanseState
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.hooks import HookState
from newswitch.states.illumination import IlluminationState
from newswitch.states.io import IOState
from newswitch.states.light_path import LightPathState
from newswitch.states.objective import ObjectiveState
from newswitch.states.stage import StageState
from newswitch.states.uc2 import UC2State


def create_registry(devices: NewswitchConfig | None, services: Sequence[Service[Any]] = ()) -> App:
    """A new app registry with what the microscope of `devices` has.

    Args:
        devices: The device configuration; None: no devices, the core only.
        services: The arkitekt services the app is created with (lovekit for the agent).
    """
    app = App("newswitch", app_context=Settings, services=services, root=ASSET_ROOT)
    parts = configured_parts(devices)
    built: list[Microscope] = []  # this registry's microscope, once started

    def microscope(settings: Settings) -> Microscope:
        """Built on the first startup hook, from the app context."""
        if not built:
            built.append(build_microscope(settings, devices))
        return built[0]

    register_models(app)

    # --- the core: every microscope -------------------------------------------------
    app.register_state(IOState, required_locks=[locks.IO])
    app.register_state(HookState, required_locks=[locks.HOOKS])
    app.register_state(ExpanseState, required_locks=[locks.EXPANSE])
    app.register_state(CalibrationState)
    app.register_state(LightPathState)
    app.register_context(IOManager, locks=[locks.IO])
    app.register_context(HookManager, locks=[locks.HOOKS])
    app.register_context(ExpanseManager, locks=[locks.EXPANSE])
    app.register_context(CalibrationManager)
    app.register_context(LightPathManager)
    app.register_context(MetadataManager)
    app.register_context(CacheManager, locks=[locks.CACHE])
    app.register_context(FrameSink)  # provided by the entrypoint

    async def provide_core(
        app_context: Settings,
    ) -> Tuple[
        IOManager,
        IOState,
        HookManager,
        HookState,
        ExpanseState,
        ExpanseManager,
        CalibrationState,
        CalibrationManager,
        LightPathState,
        LightPathManager,
        MetadataManager,
        CacheManager,
    ]:
        """What every microscope has: files, hooks, the expanse, calibration, light paths."""
        m = microscope(app_context)
        return (
            m.io,
            m.io_state,
            m.hooks,
            m.hook_state,
            m.expanse_state,
            m.expanse,
            m.calibration_state,
            m.calibration,
            m.light_path_state,
            m.light_path,
            m.metadata,
            m.cache,
        )

    def save_runtime_values(app_context: Settings) -> None:
        """Write the runtime values back into the device configuration, if it was started."""
        if built:
            save_device_config(app_context, built[0])

    app.register_startup(provide_core)
    app.register_shutdown(save_runtime_values)
    app.register_action(core.clear_expanse)

    # --- one group per part the configuration has -----------------------------------
    if parts.stage:

        async def provide_stage(app_context: Settings) -> Tuple[StageManager, StageState]:
            """The motion stage."""
            m = microscope(app_context)
            assert m.stage is not None
            return m.stage, m.stage_state

        app.register_state(StageState, required_locks=[locks.STAGE])
        app.register_context(StageManager, locks=[locks.STAGE])
        app.register_startup(provide_stage)
        app.register_action(
            stage.move_stage,
            optimistics=[
                OptimisticInput(state=StageState.__name__, path=f"/{axis}", accessor=f"/{axis}")
                for axis in ("x", "y", "z", "a")
            ],
        )
        app.register_action(stage.move_home)

    if parts.illumination:

        async def provide_illumination(
            app_context: Settings,
        ) -> Tuple[IlluminationManager, IlluminationState]:
            """The light sources."""
            m = microscope(app_context)
            assert m.illumination is not None
            return m.illumination, m.illumination_state

        app.register_state(IlluminationState, required_locks=[locks.ILLUMINATION])
        app.register_context(IlluminationManager, locks=[locks.ILLUMINATION])
        app.register_startup(provide_illumination)
        app.register_action(illumination.set_illumination_intensity)
        app.register_action(illumination.turn_on_illumination)
        app.register_action(illumination.turn_off_illumination_channel)

    if parts.detector:

        async def provide_detector(
            app_context: Settings,
        ) -> Tuple[DetectorManager, CameraState, AcquisitionManager]:
            """The detectors, and acquiring images with them."""
            m = microscope(app_context)
            assert m.detector is not None and m.acquisition is not None
            return m.detector, m.camera_state, m.acquisition

        app.register_state(CameraState, required_locks=[locks.DETECTOR])
        app.register_context(DetectorManager, locks=[locks.DETECTOR])
        app.register_context(AcquisitionManager, locks=[locks.EXPANSE, locks.IO])
        app.register_startup(provide_detector)
        app.register_shutdown(detector.close_detector)
        app.register_background(detector.run_detector_loop)
        app.register_action(detector.capture_image)
        app.register_action(detector.start_live_view)
        app.register_action(detector.stop_live_view)
        app.register_action(detector.activate_detector)
        app.register_action(detector.deactivate_detector)
        app.register_action(detector.update_detector)

    if parts.objective:

        async def provide_objective(
            app_context: Settings,
        ) -> Tuple[ObjectiveManager, ObjectiveState]:
            """The objectives."""
            m = microscope(app_context)
            assert m.objective is not None
            return m.objective, m.objective_state

        app.register_state(ObjectiveState, required_locks=[locks.OBJECTIVE])
        app.register_context(ObjectiveManager, locks=[locks.OBJECTIVE])
        app.register_startup(provide_objective)
        app.register_action(objective.switch_objective)
        app.register_action(objective.toggle_objective)

    if parts.filter_bank:

        async def provide_filter_bank(
            app_context: Settings,
        ) -> Tuple[FilterBankManager, FilterBankState]:
            """The filters."""
            m = microscope(app_context)
            assert m.filter_bank is not None
            return m.filter_bank, m.filter_bank_state

        app.register_state(FilterBankState, required_locks=[locks.FILTER_BANK])
        app.register_context(FilterBankManager, locks=[locks.FILTER_BANK])
        app.register_startup(provide_filter_bank)
        app.register_action(filter_bank.switch_filter)
        app.register_action(filter_bank.toggle_filter)

    if parts.uc2:

        async def provide_uc2(app_context: Settings) -> Tuple[UC2BusManager, UC2State]:
            """The UC2 board."""
            m = microscope(app_context)
            assert m.uc2_bus is not None
            return m.uc2_bus, m.uc2_state

        app.register_state(UC2State)
        app.register_context(UC2BusManager)
        app.register_startup(provide_uc2)
        app.register_background(uc2.run_uc2_bus)
        app.register_action(uc2.home_stage, locks=[locks.STAGE])
        app.register_action(uc2.stop_stage)
        app.register_action(uc2.led_matrix_fill, locks=[locks.ILLUMINATION])
        app.register_action(uc2.led_matrix_off, locks=[locks.ILLUMINATION])
        app.register_action(uc2.uc2_scan_nodes)
        app.register_action(uc2.home_objective, locks=[locks.OBJECTIVE])
        app.register_action(uc2.galvo_set_position, locks=[locks.GALVO])
        app.register_action(uc2.galvo_raster_scan, locks=[locks.GALVO])
        app.register_action(uc2.galvo_stop)
        app.register_action(uc2.galvo_get_status)

    # --- what needs several parts ---------------------------------------------------
    if parts.uc2 and parts.stage:
        app.register_background(uc2.run_uc2_event_dispatch)
    if parts.focus:

        async def provide_focus(app_context: Settings) -> Tuple[AutofocusState]:
            """Focusing (stage and detector): the autofocus state."""
            return (microscope(app_context).autofocus_state,)

        app.register_state(AutofocusState)
        app.register_startup(provide_focus)
        app.register_action(run_autofocus, locks=[locks.STAGE])
        app.register_action(calibrate_light_path)
        app.register_action(scan_region)
    if parts.stage and parts.detector and parts.illumination:
        app.register_action(mda.acquire_multidimensional_acquisition)

    return app


def register_models(app: App) -> None:
    """The models: what travels by value in arguments, returns and states."""
    for model in (
        Illumination,
        Detector,
        ObjectiveLens,
        Filter,
        models.ObjectiveKube,
        models.ObjectiveTurretKube,
        models.DetectorKube,
        models.IlluminationKube,
        models.DichroicKube,
        models.StageKube,
        models.FilterKube,
        models.FilterBankKube,
        models.GenericKube,
        models.LightEdge,
        models.LightPath,
        models.ObjectiveKubeState,
        models.DichroicKubeState,
        models.DetectorKubeState,
        models.IlluminationKubeState,
        models.FilterKubeState,
        models.FilterBankKubeState,
        models.ObjectiveTurretKubeState,
        models.StageKubeState,
        models.GenericKubeState,
        models.LightEdgeState,
        models.LightPathSnapshot,
        models.Metadata,
        models.Image,
        models.Scale,
        models.ArrayMetadata,
        models.Frame,
        SoftwareAutofocusHook,
        ZCalibrationHook,
        RegisteredHook,
        CalibratedLightPath,
        models.StreamIllumination,
        models.Streams,
        models.Stack,
        models.Position,
        models.Timepoint,
        models.MultidimensionalAcquisition,
        uc2.GalvoStatus,
    ):
        app.register_model(model)
