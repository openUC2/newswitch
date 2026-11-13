"""
FastAPI-based Virtual Microscope Controller

This module provides a FastAPI server with arkitekt_next integration
for controlling a virtual microscope through registered functions.
"""

import argparse
import logging
import os
from pathlib import Path
from typing import Any, Optional, Tuple
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from newswitch.hooks.software_autofocus import software_autofocus_hook
from rekuest_next.agents.base import app_context
from rekuest_next.state.lock import acquired_locks
from rekuest_next.app import get_default_app_registry
from rekuest_next.contrib.fastapi import (
    configure_fastapi,
)
from rekuest_next.agents.hooks.startup import startup
from rekuest_next.agents.hooks.shutdown import shutdown
from rekuest_next.agents.hooks.background import background


# Import protocol contexts and states
from newswitch.managers.acquistion_manager import AcquistionManager
from newswitch.managers.cache.local_cache import LocalCacheManager
from newswitch.managers.calibration import CalibrationManager
from newswitch.managers.light_path import LightPathManager
from newswitch.managers.uc2.stage_manager import UC2StageManager
from newswitch.managers.uc2.yaml_runtime import YamlUC2Bus
from newswitch.managers.uc2.illumination_manager import (
    UC2IlluminationManager,
)
from newswitch.managers.uc2.virtual_bus import VirtualUC2Bus
from newswitch.managers.uc2.dispatch import dispatch_uc2_events
from newswitch.protocols.autofocus import AutofocusState
from newswitch.protocols.uc2 import UC2BusManager, UC2State
from newswitch import registers  # noqa: F401  (registration side effects: every action)
from newswitch.logging_setup import LogLevel, configure_logging
from newswitch.managers.expanse_manager import ExpanseManager
from newswitch.managers.metadata_manager import MetadataManager
from newswitch.protocols import (
    StageManager,
    StageState,
    IlluminationManager,
    IlluminationState,
    DetectorManager,
    CameraState,
    ObjectiveManager,
    ObjectiveState,
    FilterBankManager,
    FilterBankState,
)
from newswitch.protocols.calibration import CalibrationState
from newswitch.protocols.io import IOManager, IOState
from newswitch import protocols
from newswitch import config_io
from newswitch.config_io import adapters

# Import concrete implementations
from newswitch.managers.virtual import (
    VirtualStageManager,
    VirtualLEDManager,
    VirtualDetectorManager,
    VirtualObjectiveManager,
    VirtualFilterBankManager,
    FilterBankConfig,
    LEDConfig,
    ObjectiveConfig,
    StageConfig as VirtualStageConfig,
)
from newswitch.managers.io import LocalFileIOManager, LocalFileConfig

# Import broadcaster
from newswitch.broadcasters import FrameBroadcaster

# Import routes
from newswitch.auth import (
    AuthMiddleware,
    Authenticator,
    default_authenticator,
    make_expand_user_from_request,
    router as auth_router,
)
from newswitch.routes.ws.liveview import router as liveview_router
from newswitch.routes.http.files import router as files_router
from newswitch.routes.http.cache import router as cache_router
from newswitch.routes.http.users import router as users_router

from newswitch.managers.python_hook_manager import PythonHookManager

logger = logging.getLogger(__name__)

# ====================
# Configuration
# ====================


#: The base settings file; see the comments in it. Relative folders in it are taken
#: relative to its own folder, so the working directory does not matter.
BASE_CONFIG_FILE = Path(__file__).parent.parent / "base_config.yaml"


@app_context
class ImswitchConfig(BaseSettings):
    """Configuration for imswitch application, read from `BASE_CONFIG_FILE`.

    Keyword arguments override the file, e.g. ``ImswitchConfig(config_file=None)``.
    Host and port are not part of it; they come from BACKEND_HOST / BACKEND_PORT.
    """

    # extra="forbid": a misspelled key in base_config.yaml is an error, not ignored
    model_config = SettingsConfigDict(extra="forbid")

    use_virtual_microscope: bool
    db_path: str
    available_cubes: list[str]

    config_dir: Path
    """Folder of the device configuration files."""
    schema_dir: Path
    """Folder of the generated schema files."""

    static_config_path: Path
    persistent_config_path: Path
    load_from_static_config_path: bool

    config_file: Optional[Path] = Field(
        default_factory=lambda data: (
            data["static_config_path"]
            if data["load_from_static_config_path"]
            else data["persistent_config_path"]
        )
    )
    """Device configuration read at startup: `static_config_path` or
    `persistent_config_path` (changes always go into the persistent one, see
    `config_io.open_config`). None keeps the built-in virtual devices."""

    camera_recording_dir: Optional[Path] = None
    """Folder the cameras record into (see `managers.uc2.uc2_detector`). None: the default of
    uc2_cam_py (``~/UC2_recordings``)."""

    camera_debug_window: bool = False
    """Show every camera's newest image in a window of uc2_cam_py (debugging without the
    frontend); the cameras then acquire from startup on."""

    log_to_terminal: LogLevel = "none"
    """Lowest level of the log records written to the terminal (see `logging_setup`)."""
    log_to_file: LogLevel = "debug"
    """Lowest level of the log records written to `log_file_path`."""
    log_file_path: Optional[str] = "backend.log"
    """Log file, relative to the working directory. Missing or not openable: backend.log."""

    # UC2 hardware transport (used when use_virtual_microscope is False).
    # "canopen" (preferred, multi-node CAN bus) or "rest" (single ESP32 master
    # over serial JSON). Both are plug-in replacements behind UC2BusManager.
    uc2_transport: str = "rest"  # "canopen"
    uc2_can_interface: Optional[str] = None  # "socketcan" | "waveshare" | None (auto)
    uc2_can_channel: Optional[str] = "can0"
    uc2_can_port: Optional[str] = None  # Waveshare USB-CAN-A serial port
    uc2_serial_port: Optional[str] = None  # None = autodetect
    uc2_baudrate: int = 962100
    # Detailed per-component overrides, keyed like the corresponding config
    # dataclasses (UC2CanBusConfig / UC2RestBusConfig / UC2StageConfig /
    # UC2IlluminationConfig). Nested values win over the flat fields above.
    # See backend/configs/*.json for complete examples.
    uc2_can: dict[str, Any] = {}
    uc2_rest: dict[str, Any] = {}
    uc2_stage: dict[str, Any] = {}
    uc2_illumination: dict[str, Any] = {}
    uc2_objective: dict[str, Any] = {}
    uc2_filter_bank: dict[str, Any] = {}

    def open_device_config(self) -> config_io.ConfigFile | None:
        """Honor an explicit file and always write to a separate persistent YAML."""
        if self.config_file is None:
            return None
        selected = (
            self.static_config_path
            if self.load_from_static_config_path
            else self.persistent_config_path
        )
        if self.config_file.resolve() != selected.resolve():
            source = self.config_file
            target = source.with_name(source.stem + ".persistent" + source.suffix)
            return config_io.open_config(source, target, from_static=True)
        return config_io.open_config(
            self.static_config_path,
            self.persistent_config_path,
            from_static=self.load_from_static_config_path,
        )

    def __init__(self, **values: Any) -> None:  # noqa: ANN401 - passed on to pydantic
        """Read `BASE_CONFIG_FILE`; keyword arguments override single values.

        Declared explicitly so type checkers do not demand every field as an argument:
        the values normally come from the file, which they cannot see.
        """
        super().__init__(**values)

    @model_validator(mode="before")
    @classmethod
    def _drop_comment_keys(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        # JSON has no comments, so the files in backend/configs/ carry them as "_comment"
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if not str(key).startswith("_")}
        return data

    @field_validator("config_dir", "schema_dir", "camera_recording_dir")
    @classmethod
    def _relative_to_base_config(cls, path: Optional[Path]) -> Optional[Path]:
        if path is None or path.is_absolute():
            return path
        return BASE_CONFIG_FILE.parent / path

    @field_validator("static_config_path", "persistent_config_path")
    @classmethod
    def _bare_name_in_config_dir(cls, path: Path, info: ValidationInfo) -> Path:
        # an explicit path (absolute, or with a directory part) is taken as given
        if path.is_absolute() or path.parent != Path("."):
            return path
        return info.data["config_dir"] / path

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read keyword arguments, then `BASE_CONFIG_FILE`; never the environment.

        Raises:
            FileNotFoundError: `BASE_CONFIG_FILE` does not exist.
        """
        if not BASE_CONFIG_FILE.is_file():
            raise FileNotFoundError(f"{BASE_CONFIG_FILE} is missing; newswitch needs it to start")
        return (init_settings, YamlConfigSettingsSource(settings_cls, yaml_file=BASE_CONFIG_FILE))


#: Environment variable selecting a device YAML, resolved relative to the backend folder.
CONFIG_ENV_VAR = "NEWSWITCH_CONFIG"


def load_app_config(
    config_file: str | Path | None = None, mode: str | None = None
) -> ImswitchConfig:
    """Select device YAML and mode; explicit arguments override environment variables."""
    overrides = {}
    source = config_file if config_file is not None else os.environ.get("NEWSWITCH_CONFIG")
    if source:
        path = Path(source).expanduser()
        if path.suffix.lower() not in (".yaml", ".yml"):
            raise ValueError(
                "NEWSWITCH_CONFIG must select a device YAML; legacy JSON startup is unsupported"
            )
        path = path if path.is_absolute() else BASE_CONFIG_FILE.parent / path
        overrides.update(
            config_file=path,
            static_config_path=path,
            persistent_config_path=path.with_name(path.stem + ".persistent" + path.suffix),
            load_from_static_config_path=True,
        )
    mode = mode if mode is not None else os.environ.get("NEWSWITCH_MODE")
    if mode:
        if mode not in ("hardware", "virtual"):
            raise ValueError("NEWSWITCH_MODE must be hardware or virtual")
        overrides["use_virtual_microscope"] = mode == "virtual"
    return ImswitchConfig(**overrides)


# ====================
# Startup Functions We initialize all microscope managers and states
# ====================


def build_detector_manager(
    config: ImswitchConfig,
    devices: Optional[config_io.NewswitchConfig],
    camera_state: CameraState,
    stage_state: StageState,
    objective_state: ObjectiveState,
    illumination_state: IlluminationState,
    filter_bank_state: FilterBankState,
    broadcaster: FrameBroadcaster,
) -> DetectorManager:
    """Choose the detector manager: real cameras through uc2_cam_py, else the virtual one.

    Cameras are used on real hardware only (``use_virtual_microscope: false``) and when
    the device configuration maps a detector to a camera controller (see
    `adapters.cameras`). Without the extra "camera" (uc2_cam_py not importable) the
    virtual detector stands in, with a warning. A camera that cannot be opened is an
    error: startup fails. ``camera_debug_window`` opens uc2_cam_py's debug window per camera.
    """
    found = None
    if not config.use_virtual_microscope and devices is not None:
        found = adapters.cameras(devices)
    if found:
        cameras, vendor_options = found
        try:
            from newswitch.managers.uc2.uc2_detector import UC2DetectorManager
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
                broadcaster=broadcaster,
                cameras=cameras,
                vendor_options=vendor_options,
                recording_dir=config.camera_recording_dir,
                debug_window=config.camera_debug_window,
            )
    configured_detectors = adapters.detectors(devices) if devices is not None else None
    if not config.use_virtual_microscope and configured_detectors is None:
        configured_detectors = []
    return VirtualDetectorManager(
        camera_state=camera_state,
        stage_state=stage_state,
        illumination_state=illumination_state,
        broadcaster=broadcaster,
        objective_state=objective_state,
        filter_bank_state=filter_bank_state,
        detectors=configured_detectors,
    )


@startup
async def provide_managers(  # TODO: can we make this adaptive so that we read this list from a config like in ImSwitch?
    app_context: ImswitchConfig,
) -> Tuple[
    FrameBroadcaster,
    UC2BusManager,
    UC2State,
    StageManager,
    IlluminationManager,
    DetectorManager,
    ObjectiveManager,
    FilterBankManager,
    IOManager,
    protocols.HookManager,
    StageState,
    IlluminationState,
    CameraState,
    ObjectiveState,
    FilterBankState,
    IOState,
    protocols.HookState,
    protocols.ExpanseState,
    CalibrationState,
    protocols.LightPathState,
    protocols.LightPathManager,
    protocols.CalibrationManager,
    protocols.ExpanseManager,
    protocols.MetadataManager,
    protocols.AcquistionManager,
    protocols.CacheManager,
    AutofocusState,
]:
    """
    Startup function that initializes all microscope managers and states.

    Returns a tuple of managers (implementing their protocols) and their associated states
    for dependency injection into registered functions.
    """
    # Load state from esp32 or other hardware interfaces here if needed, for now we just initialize them with default values
    # Which cubes are isntalled
    if not app_context:
        app_context = ImswitchConfig()

    with acquired_locks(
        "stage_position", "illumination", "objective", "filter_bank", "camera_parameters"
    ):
        mode = "virtual" if app_context.use_virtual_microscope else "real hardware"
        logger.info("Initializing %s microscope managers", mode)
        frame_broadcaster = FrameBroadcaster()

        config = app_context
        if config.use_virtual_microscope:
            logger.info("Using virtual microscope managers.")

        illumination_state = IlluminationState()

        camera_state = CameraState()

        objective_state = ObjectiveState()

        calibration_state = protocols.CalibrationState()

        filter_bank_state = FilterBankState()

        # Initialize states with current values from managers
        stage_state = StageState()

        io_state = IOState()

        uc2_state = UC2State()

        # Devices from the device configuration (static or persistent file, see
        # base_config.yaml). Simulation may use built-in defaults; hardware requires
        # explicit mappings and never invents device addresses.
        cfg_file = config.open_device_config()
        devices = cfg_file.config if cfg_file is not None else None
        led_config = objective_config = filter_bank_config = virtual_stage_config = None
        if devices is not None:
            sources = adapters.illuminations(devices)
            if sources is not None:
                led_config = LEDConfig(sources=sources)
            lenses = adapters.objective_lenses(devices)
            if lenses is not None:
                objective_config = ObjectiveConfig(objectives=lenses[0], default_slot=lenses[1])
            filters = adapters.filters(devices)
            if filters is not None:
                filter_bank_config = FilterBankConfig(filters=filters[0], default_slot=filters[1])
            if devices.stages:
                adapters.apply_stage_limits(devices, stage_state)
                virtual_stage_config = VirtualStageConfig(
                    min_x=stage_state.min_x,
                    max_x=stage_state.max_x,
                    min_y=stage_state.min_y,
                    max_y=stage_state.max_y,
                    min_z=stage_state.min_z,
                    max_z=stage_state.max_z,
                    min_a=stage_state.min_a,
                    max_a=stage_state.max_a,
                )

        if config.use_virtual_microscope:
            uc2_bus: UC2BusManager = VirtualUC2Bus(state=uc2_state)
            stage: StageManager = VirtualStageManager(
                stage=stage_state, config=virtual_stage_config
            )
            led: IlluminationManager = VirtualLEDManager(
                illumination_state=illumination_state, config=led_config
            )
        else:
            if devices is None:
                raise ValueError("Hardware mode requires a YAML device configuration")
            legacy = [
                name
                for name, field in type(config).model_fields.items()
                if name.startswith("uc2_") and getattr(config, name) != field.default
            ]
            if legacy:
                raise ValueError(
                    f"Use controller mappings in YAML instead of legacy overrides: {legacy}"
                )
            routed_bus = YamlUC2Bus(devices, uc2_state, illumination_state)
            uc2_bus = routed_bus
            stage = UC2StageManager(
                stage_state=stage_state, bus=uc2_bus, config=routed_bus.stage_config
            )
            led = UC2IlluminationManager(
                illumination_state=illumination_state,
                bus=uc2_bus,
                config=routed_bus.illumination_config,
            )
            objective_config = objective_config or ObjectiveConfig(objectives=[])
            filter_bank_config = filter_bank_config or FilterBankConfig(filters=[])

        # Passive metadata only; no default hardware actuators are invented.
        objective: ObjectiveManager = VirtualObjectiveManager(
            objective_state=objective_state, config=objective_config
        )
        filter_bank: FilterBankManager = VirtualFilterBankManager(
            filter_bank_state=filter_bank_state, config=filter_bank_config
        )

        detector = build_detector_manager(
            config=config,
            devices=devices,
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            filter_bank_state=filter_bank_state,
            broadcaster=frame_broadcaster,
        )
        io_manager = LocalFileIOManager(
            state=io_state,
            config=LocalFileConfig(base_path="/tmp/newswitch/images"),
        )

        calibration_manager = CalibrationManager(calibration_state=calibration_state)

        hook_state = protocols.HookState()

        hook_manager = PythonHookManager(
            protocols.HookContext(
                stage_manager=stage,
                detector_manager=detector,
                illumination_manager=led,
                objective_manager=objective,
                io_manager=io_manager,
            )
        )
        hook_manager.register_hook(protocols.SoftwareAutofocusHook, software_autofocus_hook)
        hook_manager.register_hook(
            protocols.ZCalibrationHook,
            lambda hook, context: logger.info("Z-calibration hook executed"),
        )

        expanse_state = protocols.ExpanseState()
        light_path_state = protocols.LightPathState()

        light_path_manager = LightPathManager(
            light_path_state=light_path_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            filter_bank_state=filter_bank_state,
            camera_state=camera_state,
        )

        expanse_manager = ExpanseManager(expanse=expanse_state)

        metadata_manager = MetadataManager(
            objective_state=objective_state,
            stage_state=stage_state,
            filter_bank_state=filter_bank_state,
            illumination_state=illumination_state,
            camera_state=camera_state,
            calibration_state=calibration_state,
        )  # We can pass actual light paths here if needed

        # We can calculate possible light paths at startup if needed,
        # this will populate the light path state with possible configurations based on the current microscope setup
        light_path_manager.calculate_possible_light_paths()

        cache_manager = LocalCacheManager()

        autofocus_state = AutofocusState()

        acquistion_manager = AcquistionManager(
            expanse_manager=expanse_manager,
            detector_manager=detector,
            metadata_manager=metadata_manager,
            light_path_manager=light_path_manager,
            cache_manager=cache_manager,
        )

        return (
            frame_broadcaster,
            uc2_bus,
            uc2_state,
            stage,
            led,
            detector,
            objective,
            filter_bank,
            io_manager,
            hook_manager,
            stage_state,
            illumination_state,
            camera_state,
            objective_state,
            filter_bank_state,
            io_state,
            hook_state,
            expanse_state,
            calibration_state,
            light_path_state,
            light_path_manager,
            calibration_manager,
            expanse_manager,
            metadata_manager,
            acquistion_manager,
            cache_manager,
            autofocus_state,
        )


@shutdown
def save_device_config(
    app_context: ImswitchConfig,
    camera_state: CameraState,
    objective_state: ObjectiveState,
    filter_bank_state: FilterBankState,
    stage_state: StageState,
) -> None:
    """Write runtime values (exposure, gain, wheel positions, stage position) back.

    They always go into the persistent file; the static one is never written. The source
    file is re-read rather than kept from startup, so edits made while newswitch was
    running are preserved; only the runtime values are merged in.
    """
    if not app_context.config_file:
        return
    try:
        cfg_file = app_context.open_device_config()
        assert cfg_file is not None
        adapters.sync_runtime_state(
            cfg_file.config, camera_state, objective_state, filter_bank_state, stage_state
        )
        logger.info("Saved device configuration to %s", cfg_file.save())
    except config_io.ConfigError as exc:
        logger.warning("Device configuration not saved: %s", exc)


@shutdown
def close_detector(detector: DetectorManager) -> None:
    """Stop and release the detectors, so camera recordings are complete on disk."""
    detector.close()


@background
def run_detector_loop(
    detector: DetectorManager,
) -> None:
    """Background task to run the detector acquisition loop."""

    detector.acquire_live()


@background
async def run_uc2_bus(uc2_bus: UC2BusManager) -> None:
    """Connect the UC2 hardware bus and pump its transport until shutdown."""
    await uc2_bus.abackground()


@background
async def run_uc2_event_dispatch(
    uc2_bus: UC2BusManager,
    stage_state: StageState,
    uc2_state: UC2State,
) -> None:
    """Mirror spontaneous UC2 hardware events into the shared reactive states."""
    await dispatch_uc2_events(uc2_bus, stage_state, uc2_state)


# ====================
# FastAPI Application
# ====================


default_app_registry = get_default_app_registry()


def create_app(
    config: ImswitchConfig,
    authenticator: Authenticator | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: The app context handed to every registered function.
        authenticator: Overrides the credentials file. Tests pass
            `AllowAllAuthenticator()`; production leaves this unset. Injected as an
            argument rather than read from the environment so that authentication
            cannot be switched off by a stray variable on a deployed machine.
    """

    app = FastAPI(
        title="Virtual Microscope API",  # TODO: should we load this from config?
        description="Integrated virtual microscope controller with protocol-based managers based on rekuest-next",
        version="2.0.0",
    )

    authenticator = authenticator or default_authenticator()
    app.state.authenticator = authenticator

    # Middleware order is load-bearing. `add_middleware` PREPENDS, so the LAST call
    # here ends up OUTERMOST: auth is added first and CORS wraps it. Reversed, a 401
    # would leave without CORS headers and the browser at :5173 would report an opaque
    # CORS failure instead of the 401 that tells the app to send the user to /login.
    app.add_middleware(AuthMiddleware, authenticator=authenticator)

    # Add CORS middleware
    # bceause CORS sucks
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        # Auth travels in an Authorization header or a query parameter, never a
        # cookie, so credentialed CORS is not needed - and without it the wildcard
        # origin above can be sent literally instead of being echoed back.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Configure rekuest_next app registry
    # We use the default app registry that is being used
    # for @register calls, we could of course just use this
    # pattern here
    # default_app_registry.startup(provide_managers) # We use the @startup decorator for this, so no need to register it here

    # Configure all agent routes and OpenAPI
    configure_fastapi(
        app=app,
        app_registry=default_app_registry,
        expand_user_from_request=make_expand_user_from_request(authenticator),
        app_context=config,
        db_file=config.db_path,
    )

    # Mount the public auth + health routes
    app.include_router(auth_router)

    # Mount account/role/audit management routes (admin-only except /auth/me)
    app.include_router(users_router)

    # Mount WebSocket routes for live video streaming
    app.include_router(liveview_router, prefix="/stream")

    # Mount HTTP routes for file serving
    app.include_router(files_router)

    # Mount Cache routes for serving cached data
    app.include_router(cache_router)

    return app


# ====================
# Main
# ====================


def main(argv: list[str] | None = None) -> None:
    """Run the backend with CLI overrides for YAML, mode, host and port."""
    parser = argparse.ArgumentParser(description="Start the Newswitch backend")
    parser.add_argument(
        "--config",
        help="Device YAML (relative paths resolve against backend); overrides NEWSWITCH_CONFIG",
    )
    parser.add_argument(
        "--mode",
        choices=("hardware", "virtual"),
        help="Real hardware or simulation; overrides NEWSWITCH_MODE",
    )
    parser.add_argument("--host", default=os.environ.get("BACKEND_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=os.environ.get("BACKEND_PORT", "8099"))
    args = parser.parse_args(argv)
    config = load_app_config(config_file=args.config, mode=args.mode)
    configure_logging(config.log_to_terminal, config.log_to_file, config.log_file_path)
    app = create_app(config)
    uvicorn.run(app, host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
