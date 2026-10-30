"""The microscope newswitch runs: the managers and states of the configured devices.

Data and functions, no object with behaviour. `configured_parts` says which parts a device
configuration has (a `Parts` value); `build_microscope` builds their managers and states
(a `Microscope` record):

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
    uc2          a UC2 controller (uc2-rest or canopen)      UC2BusManager, UC2State
    focus        a stage and a detector                      AutofocusState
    ============ =========================================== ===============================

`newswitch.microscope.registry.create_registry` registers one startup hook per part the
configuration has. arkitekt hands a startup hook only the app context, and no hook sees
what another returned; yet the parts depend on each other (the simulated detector reads
the stage, objective, illumination and filter states; acquisition and hooks use several
managers; the UC2 parts share one bus). So the hooks hand out the objects of one build,
made on the first hook and kept in `create_registry` (never in a module): two apps share
nothing.

A part the configuration lacks is not built: no manager exists for it (on hardware nothing
talks to the bus for it), and the states the shared managers read of it (light path,
metadata, the simulated detector) stay empty: no objectives, no filters, no light sources.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from newswitch import config_io, models, protocols, states
from newswitch.settings import Settings
from newswitch.config_io import adapters
from newswitch.config_io.devices import ControllerConfig
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
    VirtualDetectorManager,
    VirtualFilterBankManager,
    VirtualLEDManager,
    VirtualObjectiveManager,
    VirtualStageManager,
)
from newswitch.drivers.optics.detector import OpticsDetectorManager
from newswitch.drivers.virtual import StageConfig as VirtualStageConfig
from newswitch.instrument import parts as instrument_parts
from newswitch.instrument.spec import Instrument
from newswitch.models.devices import Filter as OpticalFilter
from newswitch.models.devices import Illumination, ObjectiveLens
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

#: Controller protocols that are a UC2 board.
UC2_PROTOCOLS = ("uc2-rest", "canopen")


#: What a microscope can be built from: a device configuration, or an instrument.
Devices = config_io.NewswitchConfig | Instrument


def _adapters(devices: Devices) -> Any:  # noqa: ANN401 - two modules with the same functions
    """What turns `devices` into the models the managers take."""
    return instrument_parts if isinstance(devices, Instrument) else adapters


def build_detector_manager(
    config: Settings,
    devices: Optional[Devices],
    camera_state: CameraState,
    stage_state: StageState,
    objective_state: ObjectiveState,
    illumination_state: IlluminationState,
    filter_bank_state: FilterBankState,
) -> DetectorManager:
    """Choose the detector manager: real cameras through uc2_cam_py, else the virtual one.

    Cameras are used on real hardware only (``use_virtual_microscope: false``) and when
    the device configuration maps a detector to a camera controller (see
    `adapters.cameras`). Without the extra "camera" (uc2_cam_py not importable) the
    virtual detector stands in, with a warning. A camera that cannot be opened is an
    error: startup fails. ``camera_debug_window`` opens uc2_cam_py's debug window per camera.

    An instrument renders from its optics instead.
    """
    if isinstance(devices, Instrument):
        return OpticsDetectorManager(
            instrument=devices,
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            filter_bank_state=filter_bank_state,
            detectors=instrument_parts.detectors(devices) or [],
        )
    found = None
    if not config.use_virtual_microscope and devices is not None:
        found = adapters.cameras(devices)
    if found:
        cameras, vendor_options = found
        try:
            from newswitch.drivers.uc2.uc2_detector import UC2DetectorManager
        except ImportError as exc:
            logger.warning(
                "%d camera(s) configured, but uc2_cam_py cannot be imported (%s); "
                "using the virtual detector. Install the extra: uv sync --extra camera",
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
    configured_detectors = adapters.detectors(devices) if devices is not None else None
    return VirtualDetectorManager(
        camera_state=camera_state,
        stage_state=stage_state,
        illumination_state=illumination_state,
        objective_state=objective_state,
        filter_bank_state=filter_bank_state,
        detectors=configured_detectors,
    )


@dataclass(frozen=True)
class Parts:
    """Which parts a device configuration has (besides the core every microscope has)."""

    stage: bool
    illumination: bool
    detector: bool
    objective: bool
    filter_bank: bool
    uc2: bool

    @property
    def focus(self) -> bool:
        """It can focus: a stage to move and a detector to see with."""
        return self.stage and self.detector

    def names(self) -> list[str]:
        """The configured parts, by name."""
        return [
            name
            for name, present in (
                ("stage", self.stage),
                ("illumination", self.illumination),
                ("detector", self.detector),
                ("objective", self.objective),
                ("filter bank", self.filter_bank),
                ("uc2", self.uc2),
            )
            if present
        ]


def configured_parts(devices: Optional[Devices]) -> Parts:
    """The parts `devices` has; None (no configuration): none, the core only."""
    if devices is None:
        return Parts(False, False, False, False, False, False)
    if isinstance(devices, Instrument):
        return Parts(
            stage=instrument_parts.has_stage(devices),
            illumination=bool(devices.sources()),
            detector=bool(devices.detectors()),
            objective=instrument_parts.has_objective(devices),
            filter_bank=instrument_parts.has_filters(devices),
            uc2=False,
        )
    return Parts(
        stage=adapters.motion_stage(devices) is not None,
        illumination=adapters.illuminations(devices) is not None,
        detector=adapters.detectors(devices) is not None,
        objective=adapters.objective_lenses(devices) is not None,
        filter_bank=adapters.filters(devices) is not None,
        uc2=any(
            controller.connection is not None and controller.connection.protocol in UC2_PROTOCOLS
            for controller in devices.of_type(ControllerConfig)
        ),
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


def build_microscope(settings: Settings, devices: Optional[Devices]) -> Microscope:
    """Build the managers and states of every part `devices` has (see the module).

    Args:
        settings: The app context: virtual or hardware, transports, folders.
        devices: The device configuration; None: no devices, the core only.

    Raises:
        config_io.ConfigError: On hardware, a part that needs a UC2 board has none, or the
            microscope is an instrument, which does not yet say how to reach any hardware.
    """
    parts = configured_parts(devices)
    hardware = not settings.use_virtual_microscope
    if hardware and isinstance(devices, Instrument):
        raise config_io.ConfigError(
            f"{devices.name} is an instrument, which only runs simulated so far: "
            "set use_virtual_microscope: true"
        )
    logger.info(
        "Initializing %s microscope: %s",
        "real hardware" if hardware else "virtual",
        ", ".join(parts.names()) or "no devices",
    )
    if hardware and not parts.uc2:
        # On hardware these parts are driven through a UC2 board; without one in the
        # configuration a bus would be built that nothing ever connects.
        bus_parts = [
            name
            for name, present in (
                ("stage", parts.stage),
                ("illumination", parts.illumination),
                ("objective", parts.objective),
                ("filter bank", parts.filter_bank),
            )
            if present
        ]
        if bus_parts:
            raise config_io.ConfigError(
                f"on real hardware {', '.join(bus_parts)} need a UC2 board, but the "
                "device configuration has no uc2-rest or canopen controller"
            )

    stage_state = StageState()
    illumination_state = IlluminationState()
    camera_state = CameraState()
    objective_state = ObjectiveState()
    filter_bank_state = FilterBankState()
    uc2_state = UC2State()

    uc2_bus = build_uc2_bus(settings, devices, uc2_state) if parts.uc2 else None
    stage = (
        build_stage(settings, devices, stage_state, uc2_bus)
        if devices is not None and parts.stage
        else None
    )
    illumination = (
        build_illumination(settings, devices, illumination_state, uc2_bus)
        if devices is not None and parts.illumination
        else None
    )
    objective = (
        build_objective(settings, devices, objective_state, uc2_bus)
        if devices is not None and parts.objective
        else None
    )
    filter_bank = (
        build_filter_bank(settings, devices, filter_bank_state, uc2_bus)
        if devices is not None and parts.filter_bank
        else None
    )
    # Cameras (uc2_cam_py) on real hardware when configured, else the virtual detector
    detector = (
        build_detector_manager(
            settings,
            devices,
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            filter_bank_state=filter_bank_state,
        )
        if parts.detector
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
        has_stage=parts.stage,
    )
    metadata = MetadataManager(
        objective_state=objective_state,
        stage_state=stage_state,
        filter_bank_state=filter_bank_state,
        illumination_state=illumination_state,
        camera_state=camera_state,
        calibration_state=calibration_state,
        nominal_scale=instrument_parts.nominal_pixel_scale(
            devices,
            camera_state,
            stage_state,
            objective_state,
            illumination_state,
            filter_bank_state,
        )
        if isinstance(devices, Instrument)
        else None,
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


def build_uc2_bus(
    settings: Settings, devices: Optional[config_io.NewswitchConfig], uc2_state: UC2State
) -> UC2BusManager:
    """The UC2 bus: simulated on the virtual microscope, else REST or CANopen."""
    if settings.use_virtual_microscope:
        return VirtualUC2Bus(state=uc2_state)
    logger.info("UC2 transport: %s", settings.uc2_transport)
    if settings.uc2_transport == "rest":
        rest_kwargs: dict[str, Any] = {
            "serialport": settings.uc2_serial_port,
            "baudrate": settings.uc2_baudrate,
        }
        # A uc2-rest controller in the device configuration wins over the flat
        # convenience fields; nested per-component overrides win over both.
        serial = adapters.serial_settings(devices) if devices is not None else None
        if serial is not None:
            rest_kwargs.update(serialport=serial.port, baudrate=serial.baudrate)
        rest_kwargs.update(settings.uc2_rest)
        return UC2RestBus(state=uc2_state, config=UC2RestBusConfig(**rest_kwargs))
    logger.info(
        "CAN interface: %s, channel=%s, port=%s",
        settings.uc2_can_interface,
        settings.uc2_can_channel,
        settings.uc2_can_port,
    )
    can_kwargs: dict[str, Any] = {
        "interface": settings.uc2_can_interface,
        "channel": settings.uc2_can_channel,
        "port": settings.uc2_can_port,
        **settings.uc2_can,
    }
    return UC2CanBus(state=uc2_state, config=UC2CanBusConfig(**can_kwargs))


def build_stage(
    settings: Settings,
    devices: Devices,
    stage_state: StageState,
    bus: Optional[UC2BusManager],
) -> StageManager:
    """The motion stage: its limits from the configuration; UC2 on hardware, else simulated."""
    _adapters(devices).apply_stage_limits(devices, stage_state)
    if "design" in devices.assets:
        # A design's stage (its configuration carries the design's model) travels
        # millimetres: steps that show on its model.
        stage_state.registered_step_sizes = [10.0, 100.0, 1000.0, 5000.0]
    if not settings.use_virtual_microscope:
        assert bus is not None
        return UC2StageManager(
            stage_state=stage_state,
            bus=bus,
            config=UC2StageConfig(**settings.uc2_stage) if settings.uc2_stage else None,
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
    # The simulated stage travels at the slowest configured axis speed.
    config.speed_um_per_s = _adapters(devices).stage_speed(devices)
    return VirtualStageManager(stage=stage_state, config=config)


def build_illumination(
    settings: Settings,
    devices: Devices,
    illumination_state: IlluminationState,
    bus: Optional[UC2BusManager],
) -> IlluminationManager:
    """The light sources: UC2 on hardware, else simulated LEDs."""
    if not settings.use_virtual_microscope:
        assert bus is not None
        kwargs = dict(settings.uc2_illumination)
        if "sources" in kwargs:
            kwargs["sources"] = [Illumination(**source) for source in kwargs["sources"]]
        return UC2IlluminationManager(
            illumination_state=illumination_state,
            bus=bus,
            config=UC2IlluminationConfig(**kwargs) if kwargs else None,
        )
    sources = _adapters(devices).illuminations(devices)
    return VirtualLEDManager(
        illumination_state=illumination_state,
        config=LEDConfig(sources=sources) if sources is not None else None,
    )


def build_objective(
    settings: Settings,
    devices: Devices,
    objective_state: ObjectiveState,
    bus: Optional[UC2BusManager],
) -> ObjectiveManager:
    """The objectives: UC2 on hardware, else simulated."""
    if not settings.use_virtual_microscope:
        assert bus is not None
        kwargs = dict(settings.uc2_objective)
        if "lenses" in kwargs:
            kwargs["lenses"] = [ObjectiveLens(**lens) for lens in kwargs["lenses"]]
        return UC2ObjectiveManager(
            objective_state=objective_state,
            bus=bus,
            config=UC2ObjectiveConfig(**kwargs) if kwargs else None,
        )
    lenses = _adapters(devices).objective_lenses(devices)
    assert lenses is not None
    return VirtualObjectiveManager(
        objective_state=objective_state,
        config=ObjectiveConfig(objectives=lenses[0], default_slot=lenses[1]),
    )


def build_filter_bank(
    settings: Settings,
    devices: Devices,
    filter_bank_state: FilterBankState,
    bus: Optional[UC2BusManager],
) -> FilterBankManager:
    """The filters: UC2 on hardware, else simulated."""
    if not settings.use_virtual_microscope:
        assert bus is not None
        kwargs = dict(settings.uc2_filter_bank)
        if "filters" in kwargs:
            kwargs["filters"] = [OpticalFilter(**item) for item in kwargs["filters"]]
        return UC2FilterBankManager(
            filter_bank_state=filter_bank_state,
            bus=bus,
            config=UC2FilterBankConfig(**kwargs) if kwargs else None,
        )
    filters = _adapters(devices).filters(devices)
    assert filters is not None
    return VirtualFilterBankManager(
        filter_bank_state=filter_bank_state,
        config=FilterBankConfig(filters=filters[0], default_slot=filters[1]),
    )


def save_device_config(settings: Settings, microscope: Microscope) -> None:
    """Write runtime values (exposure, gain, wheel positions, stage position) back.

    They always go into the persistent file; the static one is never written. The
    source file is re-read rather than kept from startup, so edits made while newswitch
    was running are preserved; only the runtime values are merged in. A part the
    configuration lacks has nothing to write back.
    """
    if not settings.config_file:
        return
    try:
        cfg_file = config_io.open_config(
            settings.static_config_path,
            settings.persistent_config_path,
            from_static=settings.load_from_static_config_path,
        )
        adapters.sync_runtime_state(
            cfg_file.config,
            microscope.camera_state,
            microscope.objective_state,
            microscope.filter_bank_state,
            microscope.stage_state,
        )
        logger.info("Saved device configuration to %s", cfg_file.save())
    except config_io.ConfigError as exc:
        logger.warning("Device configuration not saved: %s", exc)
