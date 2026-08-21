"""
FastAPI-based Virtual Microscope Controller

This module provides a FastAPI server with arkitekt_next integration
for controlling a virtual microscope through registered functions.
"""

import os
from typing import Optional, Tuple
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from newswitch.hooks.software_autofocus import software_autofocus_hook
from rekuest_next import pausepoint, progress
from rekuest_next.agents.base import app_context
from rekuest_next.api.schema import OptimisticInput
from rekuest_next.app import get_default_app_registry
from rekuest_next.contrib.fastapi import (
    configure_fastapi,
)
from rekuest_next import jsx
import koil
from rekuest_next.register import register
from rekuest_next.agents.hooks.startup import startup
from rekuest_next.agents.hooks.background import background


# Import protocol contexts and states
from newswitch.protocols.core import Frame
from newswitch.managers.acquistion_manager import AcquistionManager
from newswitch.managers.cache.local_cache import LocalCacheManager
from newswitch.managers.calibration import CalibrationManager
from newswitch.managers.light_path import LightPathManager
from newswitch.managers.uc2.serial_manager import UC2SerialManager
from newswitch.managers.uc2.stage_manager import UC2StageManager
from newswitch.managers.virtual.virtual_serial_manager import VirtualSerialManager
from newswitch.managers.expanse_manager import ExpanseManager
from newswitch.managers.metadata_manager import MetadataManager
from newswitch.protocols import (
    StageManager,
    StageState,
    IlluminationManager,
    IlluminationState,
    SerialManager,
    DetectorManager,
    CameraState,
    ObjectiveManager,
    ObjectiveState,
    FilterBankManager,
    FilterBankState,
)
from newswitch.protocols.calibration import CalibrationState
from newswitch.protocols.detector import Detector
from newswitch.protocols.io import IOManager, IOState
from newswitch import protocols

# Import concrete implementations
from newswitch.managers.virtual import (
    VirtualStageManager,
    VirtualLEDManager,
    VirtualDetectorManager,
    VirtualObjectiveManager,
    VirtualFilterBankManager,
)
from newswitch.managers.io import LocalFileIOManager, LocalFileConfig

# Import broadcaster
from newswitch.broadcasters import FrameBroadcaster

# Import routes
from newswitch.protocols.serial_manager import SerialState
from newswitch.auth import (
    AuthMiddleware,
    Authenticator,
    CredentialAuthenticator,
    load_credentials,
    make_expand_user_from_request,
    router as auth_router,
)
from newswitch.routes.ws.liveview import router as liveview_router
from newswitch.routes.http.files import router as files_router
from newswitch.routes.http.cache import router as cache_router

# Import routines
from newswitch.routines import scan_region
from newswitch.routines.calibration import calibrate_light_path
from newswitch.routines.multidimensional_acquisition import (
    acquire_multidimensional_acquisition,
)
from newswitch.managers.python_hook_manager import PythonHookManager

# ====================
# Configuration
# ====================


@app_context
class ImswitchConfig(BaseModel):
    """Configuration for imswitch application."""

    server: str = "localhost"
    port: int = 8001
    use_virtual_microscope: bool = True
    db_path: str = "agent_data.db"
    available_cubes: list[str] = ["cube1", "cube2", "cube3"]


# ====================
# Startup Functions We initialize all microscope managers and states
# ====================


@startup
async def provide_managers(
    app_context: ImswitchConfig,
) -> Tuple[
    FrameBroadcaster,
    SerialManager,
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
    SerialState,
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
]:
    """
    Startup function that initializes all microscope managers and states.

    Returns a tuple of managers (implementing their protocols) and their associated states
    for dependency injection into registered functions.
    """
    print(f"Initializing virtual microscope managers (config: {app_context})")

    # Load state from esp32 or other hardware interfaces here if needed, for now we just initialize them with default values
    # Which cubes are isntalled
    if not app_context:
        app_context = ImswitchConfig()

    frame_broadcaster = FrameBroadcaster()

    config = app_context
    if config.use_virtual_microscope:
        print("Using virtual microscope managers.")

    illumination_state = IlluminationState()

    camera_state = CameraState()

    objective_state = ObjectiveState()

    calibration_state = protocols.CalibrationState()

    filter_bank_state = FilterBankState()

    # Initialize states with current values from managers
    stage_state = StageState()

    io_state = IOState()

    serial_state = SerialState()

    if config.use_virtual_microscope:
        serial = VirtualSerialManager(state=serial_state)
        stage = VirtualStageManager(stage=stage_state)
    else:
        serial = UC2SerialManager(
            state=serial_state,
            port="/dev/ttyUSB0",
            baudrate=115200,
            stage_state=stage_state,
        )  # Replace with actual serial manager for hardware
        stage = UC2StageManager(stage_state=stage_state, serial_manager=serial)  #

    led = VirtualLEDManager(illumination_state=illumination_state)
    objective = VirtualObjectiveManager(objective_state=objective_state)
    filter_bank = VirtualFilterBankManager(filter_bank_state=filter_bank_state)
    detector = VirtualDetectorManager(
        camera_state=camera_state,
        stage_state=stage_state,
        illumination_state=illumination_state,
        broadcaster=frame_broadcaster,
        objective_state=objective_state,
        filter_bank_state=filter_bank_state,
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
        lambda hook, context: print("Z-calibration hook executed"),
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

    acquistion_manager = AcquistionManager(
        expanse_manager=expanse_manager,
        detector_manager=detector,
        metadata_manager=metadata_manager,
        light_path_manager=light_path_manager,
        cache_manager=cache_manager,
    )

    return (
        frame_broadcaster,
        serial,
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
        serial_state,
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
    )


@background
def run_detector_loop(
    detector: DetectorManager,
) -> None:
    """Background task to run the detector acquisition loop."""

    detector.acquire_live()


# ====================
# Registered Functions - Illumination
# ====================
@register
def clear_expanse(expanse_manager: protocols.ExpanseManager) -> None:
    """Clear the expanse state, removing all current images."""
    expanse_manager.reset_expanse()


@register
def set_illumination_intensity(
    illumination: IlluminationManager,
    intensity: float,
    channel: int = 1,
) -> float:
    """
    Set illumination intensity for a specific channel.

    Args:
        intensity: Light intensity value
        channel: Illumination channel number (default 1)

    Returns:
        The actual clamped intensity value.
    """
    result = illumination.set_intensity(intensity, channel)
    return result


@register
def long_stuff_running() -> None:
    """A long-running function to test optimistic updates and progress."""

    for i in range(10):
        progress(i * 10, f"Long task progress: {i * 10}%")
        pausepoint()  # Await for a breakpoint to allow for testing of progress updates
        koil.sleep(0.5)


@register
def turn_on_illumination(
    illumination: IlluminationManager,
    state: IlluminationState,
    channel: int = 1,
    intensity: Optional[float] = None,
) -> str:
    """
    Turn on a specific illumination channel.

    Args:
        channel: Illumination channel number (default 1)
        intensity: Optional intensity to set. Uses current/default if not provided.

    Returns:
        Confirmation message.
    """
    result = illumination.turn_on(channel, intensity)
    return result


@register
def turn_off_illumination_channel(
    illumination: IlluminationManager,
    state: IlluminationState,
    channel: int,
) -> str:
    """
    Turn off a specific illumination channel.

    Args:
        channel: Illumination channel number to turn off

    Returns:
        Confirmation message.
    """  # Move stage home when turning off illumination for safety
    result = illumination.turn_off_channel(channel)
    return result


# ====================
# Registered Functions - Stage
# ====================


# Here we use the locks explicitly, when setting them like this we are ourselves responsible
# for ensuring that the locks are properly set for this execution context
@register(locks=["stage_position"])
def failing_camera(camera: CameraState, intensity: int) -> str:
    """A function that always fails to test lock release."""
    camera.detectors[0].current_gain += intensity  # type: igThis is just to have some side effect that we can check in the test, but the function will still fail
    return "This function should fail."


# This function uses the optimistic pattern
# It allows for the function to define how the state should be updated optimistically at the moment the function runs
# This is useful for setters like this move function, where we want the UI to reflect the new position immediately,
# without waiting for the function to complete
@register(
    optimistics=[
        OptimisticInput(
            state=StageState.__name__,
            path="",
            accessor="({...state, x: args.x, y: args.y, z: args.z, a: args.a})",
        )
    ],
)
def move_stage(
    stage: StageManager,
    x: Optional[float] = None,
    y: Optional[float] = None,
    z: Optional[float] = None,
    a: Optional[float] = None,
    is_absolute: bool = False,
    step_size: float = 1.0,
) -> None:
    """
    Move the stage to a new position.

    Args:
        x: X position (micrometers)
        y: Y position (micrometers)
        z: Z position (micrometers)
        a: A (rotation) position
        is_absolute: If True, move to absolute position; if False, relative move
        step_size: Step size in micrometers for movement simulation (default: 1.0)
    """
    # Read current position from state
    stage.move(x=x, y=y, z=z, a=a, step_size=step_size, is_absolute=is_absolute)


@register
def move_home(stage: StageManager, state: StageState) -> None:
    """Move stage to home position."""
    pos = stage.move_home()
    return pos


@register(
    description="Move the stage to a specified position with a long execution time to test optimistic updates."
)
def kill_benedict(stage: StageManager, kill_hard: str, die_young: bool) -> None:
    """A function that simulates a critical failure to test error handling and lock release."""
    raise RuntimeError("Benedict has been killed. This is a simulated critical failure.")


@register
def move_to_stage_position(
    stage: StageManager,
    state: StageState,
    position_x: int,
    position_y: int,
    position_z: int,
) -> None:
    """
    Move the stage to a specified position.

    Args:
        position: Target stage position
    """
    stage.move(
        x=position_x,
        y=position_y,
        z=position_z,
        is_absolute=True,
    )


# ====================
# Registered Functions - Detector
# ====================


@register
def capture_image(
    detector: DetectorManager,
    acquisition_manager: protocols.AcquistionManager,
) -> list[Frame]:
    """
    Capture an image from the detector and save it to disk.

    Args:
        slot: Detector slot number

    Returns a FileHandle that can be used to retrieve the image via the
    /files/{file_path} HTTP endpoint.
    """
    files = (
        acquisition_manager.acquire()
    )  # This will capture an image and save it to disk, returning the file handle

    return files


@register
def dump_states_to_stdin(
    stage_state: StageState,
    illumination_state: IlluminationState,
    camera_state: CameraState,
    objective_state: ObjectiveState,
    filter_bank_state: FilterBankState,
    expanse_state: protocols.ExpanseState,
) -> None:
    """Dump the current states of all managers for debugging purposes."""
    print("Dumping states to JSON:")
    print(len(expanse_state.current_frames))


@register
def start_live_view(camera_state: CameraState) -> str:
    """
    Start broadcasting frames to the video WebSocket endpoint.

    Call this to begin streaming frames captured by the detector
    to connected video clients.
    """

    camera_state.is_acquiring = True
    return "Broadcasting started. Frames will now be sent to video clients."


@register
def stop_live_view(camera_state: CameraState) -> str:
    """
    Stop broadcasting frames to the video WebSocket endpoint.

    Call this to stop streaming frames captured by the detector
    to connected video clients.
    """
    camera_state.is_acquiring = False
    return "Broadcasting stopped. No frames will be sent to video clients."


@register
def activate_detector(detector: DetectorManager, slot: int) -> None:
    """
    Activate a detector by its slot number.

    Args:
        slot: Detector slot number to activate
    """

    detector.activate_detector(slot)
    return None


@register
def deactivate_detector(detector: DetectorManager, slot: int) -> str:
    """
    Deactivate a detector by its slot number.

    Args:
        slot: Detector slot number to deactivate
    """
    detector.deactivate_detector(slot)
    return f"Detector slot {slot} deactivated"


@register
def update_detector(
    detector: DetectorManager,
    slot: int,
    exposure_time: float | None = None,
    gain: float | None = None,
) -> Detector:
    """
    Update detector settings.

    Args:
        slot: Detector slot number
        exposure_time: Exposure time in seconds (optional)
        gain: Gain value (optional)
    """
    return detector.update_detector(slot, exposure_time, gain)


# ====================
# Registered Functions - Objective
# ====================


@register
def never_ending_function() -> None:
    """A function that never ends to test how the system handles long-running functions."""
    pass


@register
def switch_objective(objective: ObjectiveManager, state: ObjectiveState, slot: int) -> None:
    """
    Switch to a specific objective slot.

    Args:
        slot: Objective slot number
    """
    objective.switch_objective(slot)


@register
def toggle_objective(objective: ObjectiveManager, state: ObjectiveState) -> None:
    """Toggle to the next objective in the turret."""
    objective.toggle_objective()


# ====================
# Registered Functions - Filter Bank
# ====================


@register
def switch_filter(
    filter_bank: FilterBankManager, state: FilterBankState, slot: int
) -> protocols.Filter:
    """
    Switch to a specific filter slot.

    Args:
        slot: Filter slot number

    Returns:
        The newly active filter.
    """
    return filter_bank.switch_filter(slot)


@register
def toggle_filter(filter_bank: FilterBankManager, state: FilterBankState) -> protocols.Filter:
    """Toggle to the next filter in the wheel.

    Returns:
        The newly active filter.
    """
    return filter_bank.toggle_filter()


# ====================
# FastAPI Application
# ====================


default_app_registry = get_default_app_registry()
default_app_registry.register(acquire_multidimensional_acquisition)
default_app_registry.register(calibrate_light_path)
default_app_registry.register(scan_region)
default_app_registry.register_blok(
    "jonda",
    jsx("""
            <Card id="opentrons-controller" className="w-[380px] border-blue-200 shadow-md">
                <CardHeader>
                    <CardTitle text="Newswitch Handler" />
                    <CardDescription text="Bene don't look at this yet, this is just a placeholder" />
                </CardHeader>
                <CardContent className="grid gap-4">
                    <div className="flex items-center justify-between p-3 border rounded-md bg-slate-50">
                        <span className="text-sm font-medium text-slate-700" text="Deck Status" />
                        <span className="text-xs font-bold text-blue-700 bg-blue-100 border border-blue-200 px-2 py-1 rounded-full" text="Idle" />
                    </div>
                    <div className="grid grid-cols-2 gap-2 mt-2">
                        <foreach items="@self.ObjectiveState.mounted_lenses" let="#lens">
                            <Button
                                label="@lens.name"
                                onClick="@self.switch_objective(lens.slot)"
                            />
                        </foreach>
                    </div>
                </CardContent>
            </Card>
        """),
)


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
        title="Virtual Microscope API",
        description="Integrated virtual microscope controller with protocol-based managers based on rekuest-next",
        version="2.0.0",
    )

    authenticator = authenticator or CredentialAuthenticator(load_credentials())
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


def main() -> None:
    """Main entry point to run the FastAPI server.

    Host and port come from BACKEND_HOST / BACKEND_PORT (the repo's root .env, which
    `just` and docker compose export), so they stay defined in exactly one place.
    """
    config = ImswitchConfig()
    app = create_app(config)
    uvicorn.run(
        app,
        host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        port=int(os.environ.get("BACKEND_PORT", "8099")),
    )


if __name__ == "__main__":
    main()
