"""The microscope newswitch runs: the managers and states of what its instrument has.

Data and functions, no object with behaviour. `build_microscope` builds the managers and states of
what the instrument's ``parts`` section names (a `Microscope` record):

    ============ =========================================== ===============================
    part         when                                        provides
    ============ =========================================== ===============================
    core         always                                      io, expanse, cache,
                                                             calibration, light path,
                                                             metadata, hooks
    stage        a motion stage                              StageManager, StageState
    illumination a light source                              IlluminationManager, -State
    detector     a detector                                  DetectorManager, CameraState,
                                                             AcquisitionManager
    objective    an objective                                ObjectiveManager, ObjectiveState
    filter bank  a filter                                    FilterBankManager, FilterBankState
    uc2          a board in its ``hardware`` section         UC2BusManager, UC2State
    focus        a stage and a detector                      AutofocusState
    ============ =========================================== ===============================

`newswitch.microscope.registry.create_registry` merges one registry per part the instrument
has (`newswitch.microscope.apps`). Their startup hooks hand out the objects of one build, held
by the app context (`newswitch.microscope.run.Run`, never in a module): two apps share nothing.

A part the instrument lacks is not built: no manager exists for it (on hardware nothing
talks to the bus for it), and the states the shared managers read of it (light path,
metadata, the simulated detector) stay empty: no objectives, no filters, no light sources.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from newswitch import models, protocols, states
from newswitch.settings import Settings
from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.drivers.uc2.filter_bank_manager import UC2FilterBankConfig, UC2FilterBankManager
from newswitch.drivers.uc2.illumination_manager import (
    UC2IlluminationConfig,
    UC2IlluminationManager,
)
from newswitch.drivers.uc2.objective_manager import UC2ObjectiveConfig, UC2ObjectiveManager
from newswitch.drivers.uc2.rest_bus import UC2RestBus, UC2RestBusConfig
from newswitch.drivers.uc2.stage_manager import UC2StageConfig, UC2StageManager
from newswitch.drivers.uc2.virtual_bus import VirtualUC2Bus
from newswitch.drivers.virtual import (
    FilterBankConfig,
    LEDConfig,
    ObjectiveConfig,
    VirtualFilterBankManager,
    VirtualLEDManager,
    VirtualObjectiveManager,
    VirtualStageManager,
)
from newswitch.drivers.optics.detector import OpticsDetectorManager
from newswitch.drivers.virtual import StageConfig as VirtualStageConfig
from newswitch.instrument import parts as instrument_parts
from newswitch.instrument.errors import SpecError
from newswitch.instrument.predict import NotCompiled
from newswitch.instrument.spec import Instrument, Parts
from newswitch.protocols import (
    DetectorManager,
    FilterBankManager,
    IlluminationManager,
    ObjectiveManager,
    StageManager,
)
from newswitch.protocols.io import IOManager
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.services.acquisition import AcquisitionManager
from newswitch.services.cache.local_cache import LocalCacheConfig, LocalCacheManager
from newswitch.services.calibration import CalibrationManager
from newswitch.services.expanse import ExpanseManager
from newswitch.services.hooks.manager import PythonHookManager
from newswitch.services.hooks.software_autofocus import software_autofocus_hook
from newswitch.services.io import LocalFileConfig, LocalFileIOManager
from newswitch.services.light_path import LightPathManager
from newswitch.services.metadata import MetadataManager
from newswitch.states.autofocus import AutofocusState
from newswitch.states.calibration import CalibrationState
from newswitch.states.detector import CameraState
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.illumination import IlluminationState
from newswitch.states.io import IOState
from newswitch.states.objective import ObjectiveState
from newswitch.states.stage import StageState
from newswitch.states.uc2 import UC2State

logger = logging.getLogger(__name__)


def _driver_config(cls: type, options: dict[str, Any], where: str) -> Any:  # noqa: ANN401
    """The driver's config from what the description states.

    Raises:
        SpecError: An option is not one the driver has.
    """
    try:
        return cls(**options)
    except TypeError as exc:
        raise SpecError(f"hardware: {where}: {exc}") from exc


def build_detector_manager(
    config: Settings,
    instrument: Instrument,
    camera_state: CameraState,
    stage_state: StageState,
    objective_state: ObjectiveState,
    illumination_state: IlluminationState,
    filter_bank_state: FilterBankState,
) -> DetectorManager:
    """Choose the detector manager: real cameras through uc2_cam_py, else rendering from the optics.

    Cameras are used on real hardware only (``use_virtual_microscope: false``). Without the extra
    "camera" (uc2_cam_py not importable) the optics stand in, with a warning. A camera that cannot
    be opened is an error: startup fails. ``camera_debug_window`` opens uc2_cam_py's debug window
    per camera.
    """
    found = None if config.use_virtual_microscope else instrument_parts.cameras(instrument)
    if found:
        cameras, vendor_options = found
        try:
            from newswitch.drivers.uc2.uc2_detector import UC2DetectorManager
        except ImportError as exc:
            logger.warning(
                "%d camera(s) configured, but uc2_cam_py cannot be imported (%s); "
                "rendering from the optics. Install the extra: uv sync --extra camera",
                len(cameras),
                exc,
            )
        else:
            return UC2DetectorManager(
                camera_state=camera_state,
                cameras=cameras,
                vendor_options=vendor_options,
                recording_dir=config.camera_recording_dir,
                debug_window=config.camera_debug_window,
            )
    return OpticsDetectorManager(
        instrument=instrument,
        camera_state=camera_state,
        stage_state=stage_state,
        objective_state=objective_state,
        illumination_state=illumination_state,
        filter_bank_state=filter_bank_state,
        detectors=instrument_parts.detectors(instrument) or [],
    )


@dataclass
class Microscope:
    """Everything one microscope built; a part it lacks is None (its state stays empty)."""

    stage_state: StageState
    illumination_state: IlluminationState
    camera_state: CameraState
    objective_state: ObjectiveState
    filter_bank_state: FilterBankState
    uc2_state: UC2State
    io_state: IOState
    io: IOManager
    hook_state: states.HookState
    hooks: protocols.HookManager
    expanse_state: states.ExpanseState
    expanse: protocols.ExpanseManager
    calibration_state: CalibrationState
    calibration: protocols.CalibrationManager
    light_path_state: states.LightPathState
    light_path: protocols.LightPathManager
    metadata: protocols.MetadataManager
    cache: protocols.CacheManager
    autofocus_state: AutofocusState
    uc2_bus: Optional[UC2BusManager]
    stage: Optional[StageManager]
    illumination: Optional[IlluminationManager]
    detector: Optional[DetectorManager]
    acquisition: Optional[protocols.AcquisitionManager]
    objective: Optional[ObjectiveManager]
    filter_bank: Optional[FilterBankManager]


def _nominal_scale(
    instrument: Optional[Instrument],
    hardware: bool,
    *states_: Any,  # noqa: ANN401
) -> Any:  # noqa: ANN401
    """What the design predicts a detector's pixels are.

    Real hardware can run without a compiled table, with a warning: images no calibration covers
    then have no predicted pixel size. A simulation renders from the table, so it cannot.
    """
    if instrument is None:
        return None
    try:
        return instrument_parts.nominal_pixel_scale(instrument, *states_)
    except NotCompiled as exc:
        if not hardware:
            raise
        logger.warning("No predicted pixel size until it is compiled: %s", exc)
        return None


def build_microscope(settings: Settings, instrument: Optional[Instrument]) -> Microscope:
    """Build the managers and states of every part `instrument` has (see the module).

    Args:
        settings: The app context: virtual or hardware, folders.
        instrument: What to run; None: no devices, the core only.

    Raises:
        SpecError: On hardware, the description does not say how to reach something it has.
    """
    parts = instrument.parts if instrument is not None else Parts()
    hardware = not settings.use_virtual_microscope
    if hardware and instrument is not None:
        instrument_parts.check_wired(instrument)
    logger.info(
        "Initializing %s microscope: %s",
        "real hardware" if hardware else "virtual",
        instrument.name if instrument is not None else "no devices",
    )

    stage_state = StageState()
    illumination_state = IlluminationState()
    camera_state = CameraState()
    objective_state = ObjectiveState()
    filter_bank_state = FilterBankState()
    uc2_state = UC2State()

    uc2_bus = (
        build_uc2_bus(settings, instrument, uc2_state)
        if instrument is not None and instrument.hardware.boards
        else None
    )
    stage = build_stage(settings, instrument, stage_state, uc2_bus) if parts.stage else None
    illumination = (
        build_illumination(settings, instrument, illumination_state, uc2_bus)
        if parts.sources
        else None
    )
    objective = (
        build_objective(settings, instrument, objective_state, uc2_bus) if parts.objective else None
    )
    filter_bank = (
        build_filter_bank(settings, instrument, filter_bank_state, uc2_bus)
        if parts.filters
        else None
    )
    # Cameras (uc2_cam_py) on real hardware, else rendered from the optics
    detector = (
        build_detector_manager(
            settings,
            instrument,
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            filter_bank_state=filter_bank_state,
        )
        if parts.detectors
        else None
    )

    # --- the core: every microscope -------------------------------------------------
    io_state = IOState()
    io = LocalFileIOManager(
        state=io_state, config=LocalFileConfig(base_path=str(settings.image_dir))
    )
    calibration_state = CalibrationState()
    calibration = CalibrationManager(calibration_state=calibration_state)

    hook_state = states.HookState()
    hooks = PythonHookManager(
        protocols.HookContext(
            stage_manager=stage,
            detector_manager=detector,
            illumination_manager=illumination,
            objective_manager=objective,
            io_manager=io,
        )
    )
    if stage is not None and detector is not None:
        # The software autofocus sweeps the stage and reads the detector.
        hooks.register_hook(models.SoftwareAutofocusHook, software_autofocus_hook)

    expanse_state = states.ExpanseState()
    expanse = ExpanseManager(expanse=expanse_state)
    light_path_state = states.LightPathState()
    light_path = LightPathManager(
        light_path_state=light_path_state,
        objective_state=objective_state,
        illumination_state=illumination_state,
        filter_bank_state=filter_bank_state,
        camera_state=camera_state,
        has_stage=parts.stage is not None,
    )
    metadata = MetadataManager(
        objective_state=objective_state,
        stage_state=stage_state,
        filter_bank_state=filter_bank_state,
        illumination_state=illumination_state,
        camera_state=camera_state,
        calibration_state=calibration_state,
        nominal_scale=_nominal_scale(
            instrument,
            hardware,
            camera_state,
            stage_state,
            objective_state,
            illumination_state,
            filter_bank_state,
        ),
    )
    # The light paths this microscope's parts allow
    light_path.calculate_possible_light_paths()
    cache = LocalCacheManager(LocalCacheConfig(base_path=str(settings.cache_dir)))

    acquisition = (
        AcquisitionManager(
            expanse_manager=expanse,
            detector_manager=detector,
            metadata_manager=metadata,
            light_path_manager=light_path,
            cache_manager=cache,
        )
        if detector is not None
        else None
    )

    return Microscope(
        stage_state=stage_state,
        illumination_state=illumination_state,
        camera_state=camera_state,
        objective_state=objective_state,
        filter_bank_state=filter_bank_state,
        uc2_state=uc2_state,
        io_state=io_state,
        io=io,
        hook_state=hook_state,
        hooks=hooks,
        expanse_state=expanse_state,
        expanse=expanse,
        calibration_state=calibration_state,
        calibration=calibration,
        light_path_state=light_path_state,
        light_path=light_path,
        metadata=metadata,
        cache=cache,
        autofocus_state=AutofocusState(),
        uc2_bus=uc2_bus,
        stage=stage,
        illumination=illumination,
        detector=detector,
        acquisition=acquisition,
        objective=objective,
        filter_bank=filter_bank,
    )


def build_uc2_bus(settings: Settings, instrument: Instrument, uc2_state: UC2State) -> UC2BusManager:
    """The UC2 bus: simulated on the virtual microscope, else REST or CANopen, as its board says."""
    if settings.use_virtual_microscope:
        return VirtualUC2Bus(state=uc2_state)
    board = instrument.hardware.board
    assert board is not None
    logger.info("UC2 transport: %s", board.transport)
    options = dict(board.options)
    where = f"boards.{board.name}"
    if board.transport == "rest":
        options["serialport"] = board.resolved_port()
        return UC2RestBus(state=uc2_state, config=_driver_config(UC2RestBusConfig, options, where))
    options["port"] = board.resolved_port()
    turret = instrument_parts.objective_actuator(instrument)
    if turret is not None and turret.positions is not None:
        options["objective_slot_positions_steps"] = [
            turret.positions[slot] for slot in sorted(turret.positions)
        ]
    return UC2CanBus(state=uc2_state, config=_driver_config(UC2CanBusConfig, options, where))


def build_stage(
    settings: Settings,
    instrument: Instrument,
    stage_state: StageState,
    bus: Optional[UC2BusManager],
) -> StageManager:
    """The motion stage: its limits from the description; UC2 on hardware, else simulated."""
    instrument_parts.apply_stage_limits(instrument, stage_state)
    if not settings.use_virtual_microscope:
        assert bus is not None
        board = instrument.hardware.board
        assert board is not None
        return UC2StageManager(
            stage_state=stage_state,
            bus=bus,
            config=_driver_config(
                UC2StageConfig,
                {**board.stage, "axes": instrument_parts.stage_axes(instrument)},
                f"boards.{board.name}.stage",
            ),
        )
    config = VirtualStageConfig(
        min_x=stage_state.min_x,
        max_x=stage_state.max_x,
        min_y=stage_state.min_y,
        max_y=stage_state.max_y,
        min_z=stage_state.min_z,
        max_z=stage_state.max_z,
        min_a=stage_state.min_a,
        max_a=stage_state.max_a,
    )
    # The simulated stage travels at the slowest axis speed.
    config.speed_um_per_s = instrument_parts.stage_speed(instrument)
    return VirtualStageManager(stage=stage_state, config=config)


def build_illumination(
    settings: Settings,
    instrument: Instrument,
    illumination_state: IlluminationState,
    bus: Optional[UC2BusManager],
) -> IlluminationManager:
    """The light sources: UC2 on hardware, else simulated LEDs."""
    sources = instrument_parts.illuminations(instrument)
    if not settings.use_virtual_microscope:
        assert bus is not None and sources is not None
        options: dict[str, Any] = {}
        for source, name in zip(sources, instrument.sources()):
            actuator = instrument_parts.source_channel(instrument, name)
            assert actuator is not None and actuator.channel is not None
            source.channel = actuator.channel
            # Nothing turned it on yet, whatever power it is described to start from.
            source.is_active = False
            if actuator.pwm_max is not None:
                options["pwm_max"] = actuator.pwm_max
        return UC2IlluminationManager(
            illumination_state=illumination_state,
            bus=bus,
            config=UC2IlluminationConfig(sources=sources, **options),
        )
    return VirtualLEDManager(
        illumination_state=illumination_state,
        config=LEDConfig(sources=sources) if sources is not None else None,
    )


def build_objective(
    settings: Settings,
    instrument: Instrument,
    objective_state: ObjectiveState,
    bus: Optional[UC2BusManager],
) -> ObjectiveManager:
    """The objectives: UC2 on hardware, else simulated."""
    lenses = instrument_parts.objective_lenses(instrument)
    assert lenses is not None
    if not settings.use_virtual_microscope:
        assert bus is not None
        return UC2ObjectiveManager(
            objective_state=objective_state,
            bus=bus,
            config=UC2ObjectiveConfig(lenses=lenses[0]),
        )
    return VirtualObjectiveManager(
        objective_state=objective_state,
        config=ObjectiveConfig(objectives=lenses[0], default_slot=lenses[1]),
    )


def build_filter_bank(
    settings: Settings,
    instrument: Instrument,
    filter_bank_state: FilterBankState,
    bus: Optional[UC2BusManager],
) -> FilterBankManager:
    """The filters: UC2 on hardware, else simulated."""
    filters = instrument_parts.filters(instrument)
    assert filters is not None
    if not settings.use_virtual_microscope:
        assert bus is not None
        wheel = instrument_parts.filter_actuator(instrument)
        assert wheel is not None and wheel.axis is not None and wheel.positions is not None
        return UC2FilterBankManager(
            filter_bank_state=filter_bank_state,
            bus=bus,
            config=UC2FilterBankConfig(
                filters=filters[0],
                axis=wheel.axis,
                slot_positions=[wheel.positions[slot] for slot in sorted(wheel.positions)],
            ),
        )
    return VirtualFilterBankManager(
        filter_bank_state=filter_bank_state,
        config=FilterBankConfig(filters=filters[0], default_slot=filters[1]),
    )
