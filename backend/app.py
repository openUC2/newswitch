"""newswitch as an arkitekt app: the agent Orkestrator shows. The standard way to run newswitch.

    NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just agent --url <server>
    NEWSWITCH_CONFIG=... uv run --extra agent python app.py --url <server>
    NEWSWITCH_CONFIG=... uv run --extra agent arkitekt run prod app --context app:load_run --url <server>
    uv run --extra agent arkitekt inspect all app        # what it declares, without an instrument

`app` is one global, static app, declared below at module level: every model, state, context,
startup hook, action and background task newswitch has, registered here directly, on every
microscope. So arkitekt can inspect it without an instrument and compile it into a release. Which
microscope it runs is the app context, a `Run`, known only when it starts: `load_run` reads the
description ``NEWSWITCH_CONFIG`` names. A part that microscope lacks is a context its startup hook
(`newswitch.microscope.startup`) returns as None, which arkitekt does not provide: an action that
needs it fails when called, and a background task that needs it is not started.

Beside the microscope, `app` declares what is particular to the agent: a `LovekitSink` as the
detectors' `FrameSink`, published as one lovekit stream per detector, the mikro the server provides
as the `DatasetStore`, and the agent's bloks (`AGENT_BLOKS`, in Orkestrator's catalog). `__main__`
logs in to the arkitekt server (fakts: ``--url`` or ``$FAKTS_URL``, else the public deployment)
and provides it until stopped.

FastAPI mode (``main_fastapi.py``) declares the same microscope through the part registries of
`newswitch.microscope.apps`; ``tests/test_registry.py`` holds the two to the same actions, states
and locks.

An agent serves no HTTP routes: the files the IO manager writes and the frame cache
(``main_fastapi.py``) are not reachable from Orkestrator, so a frame's cache id or a file
handle points nowhere there. Serving them through arkitekt is open.

Needs the extra ``agent`` (``uv sync --extra agent``).
"""

import sys
from typing import Tuple

from arkitekt import App, run
from lovekit import lovekit_service
from mikro import Mikro, mikro_service

from newswitch.actions.core import clear_expanse
from newswitch.actions.detector import (
    activate_detector,
    capture_image,
    close_detector,
    deactivate_detector,
    run_detector_loop,
    set_window,
    start_live_view,
    stop_live_view,
)
from newswitch.actions.space import (
    mount_holder,
    move_to,
    register_mount,
    set_sample_origin_here,
)
from newswitch.actions.uc2 import (
    galvo_get_status,
    galvo_raster_scan,
    galvo_set_position,
    galvo_stop,
    home_objective,
    home_stage,
    keep_firmware,
    led_matrix_fill,
    led_matrix_off,
    run_uc2_bus,
    run_uc2_event_dispatch,
    stop_stage,
    uc2_scan_nodes,
    update_firmware,
)
from newswitch.actions.values import move, move_home, move_one, swap, tune
from newswitch.calibration.light_path import calibrate_light_path
from newswitch.calibration.mount import calibrate_mount
from newswitch.calibration.states import CalibrationState, MountCalibrationState
from newswitch.infra.mikro.store import MikroDatasetStore
from newswitch.infra.streaming.lovekit import (
    CameraStream,
    CameraStreams,
    LovekitSink,
    publish_camera_streams,
)
from newswitch.infra.ui import declare_agent_ui
from newswitch.instrument.spec import Instrument
from newswitch.logging_setup import setup_logging
from newswitch.microscope import locks
from newswitch.microscope.models import MODELS
from newswitch.microscope.registry import DESCRIPTION, IDENTIFIER, VERSION
from newswitch.microscope.run import Run
from newswitch.microscope.startup import (
    provide_core,
    provide_detector,
    provide_focus,
    provide_mount_calibration,
    provide_uc2,
    provide_values,
)
from newswitch.protocols.acquisition import AcquisitionManager
from newswitch.protocols.cache import CacheManager
from newswitch.protocols.calibration import CalibrationManager
from newswitch.protocols.dataset_store import DatasetStore
from newswitch.protocols.detector import DetectorManager
from newswitch.protocols.expanse import ExpanseManager
from newswitch.protocols.frame_sink import FrameSink
from newswitch.protocols.hook_manager import HookManager
from newswitch.protocols.io import IOManager
from newswitch.protocols.metadata import MetadataManager
from newswitch.protocols.optics import OpticsManager
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.routines.acquire import acquire
from newswitch.routines.autofocus import run_autofocus
from newswitch.routines.mda import acquire_mda
from newswitch.routines.region_scan import scan_region
from newswitch.services.space import SpaceManager
from newswitch.services.values import Values
from newswitch.settings import load_settings
from newswitch.states.autofocus import AutofocusState
from newswitch.states.detector import DetectorState
from newswitch.states.expanse import ExpanseState
from newswitch.states.hooks import HookState
from newswitch.states.io import IOState
from newswitch.states.optics import OpticsState
from newswitch.states.space import SpaceState
from newswitch.states.uc2 import UC2State
from newswitch.states.values import MoveState, SourceState, SwapState, TuneState


def cameras_of(instrument: Instrument | None) -> list[CameraStream]:
    """A stream per detector, keyed by its cube (lovekit keeps a stream's id by its key over
    restarts), titled by that too."""
    if instrument is None:
        return []
    return [CameraStream(detector=name, key=name, title=name) for name in instrument.detectors()]


async def provide_lovekit_sink(current: Run) -> Tuple[FrameSink, CameraStreams]:
    """Startup: the detectors stream to a lovekit sink, one stream per detector.

    Without detectors the sink is None: arkitekt then provides no `FrameSink` and does not start
    `publish_camera_streams`. (The annotation names the context, which arkitekt reads; it takes no
    Optional there.)
    """
    cameras = cameras_of(current.instrument)
    test_pattern = current.settings.simulate == "debug"  # the network tested, not the cameras
    sink = LovekitSink(cameras, test_pattern=test_pattern) if cameras else None
    return sink, CameraStreams()  # pyright: ignore[reportReturnType]


async def provide_dataset_store(current: Run, client: Mikro) -> DatasetStore:
    """Startup: acquisitions are stored in the mikro the server provides."""
    return MikroDatasetStore(client, current.instrument, current.microscope)


def load_run() -> Run:
    """The app context: the run of the description ``NEWSWITCH_CONFIG`` names
    (``arkitekt run ... --context app:load_run``).

    Raises:
        SpecError: None is named, or what is named is no valid description.
    """
    return Run.of(load_settings()) #TODO: make this more functional, i want a load_run that takes a path and returns a run,


#: newswitch, as arkitekt finds it (``arkitekt ... app``, ``$ARKITEKT_APP``). Global, and declared
#: without reading anything of an instrument.
app = App(
    IDENTIFIER,
    VERSION,
    description=DESCRIPTION,
    app_context=Run,
    services=(lovekit_service, mikro_service),
)

# --- models: what travels by value in arguments, returns and states
for model in MODELS:
    app.register_model(model) #TODO: do we really need all these models to be registered?

# --- what every microscope has: files, hooks, the expanse, calibration, light paths
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
app.register_context(FrameSink)  # provide_lovekit_sink
app.register_context(DatasetStore)  # provide_dataset_store
app.register_startup(provide_core)
app.register_action(clear_expanse)

# --- the variables: what can change on a microscope, by what it does
app.register_state(MoveState)
app.register_state(SwapState)
app.register_state(TuneState)
app.register_state(SourceState)
app.register_context(Values)
app.register_startup(provide_values)
app.register_action(move, locks=[locks.MOTION])
app.register_action(move_one, locks=[locks.MOTION])
app.register_action(move_home, locks=[locks.MOTION])
app.register_action(swap, locks=[locks.SWAP])
app.register_action(tune, locks=[locks.TUNE])
app.register_action(move_to, locks=[locks.MOTION])
app.register_action(set_sample_origin_here)
app.register_action(register_mount)
app.register_action(mount_holder, locks=[locks.MOTION, locks.EXPANSE])

# --- the detectors: what delivers images
app.register_state(DetectorState, required_locks=[locks.DETECTOR])
app.register_context(DetectorManager, locks=[locks.DETECTOR])
app.register_context(AcquisitionManager, locks=[locks.EXPANSE, locks.IO])
app.register_startup(provide_detector)
app.register_shutdown(close_detector)
app.register_background(run_detector_loop)
app.register_action(capture_image)
app.register_action(start_live_view)
app.register_action(stop_live_view)
app.register_action(activate_detector)
app.register_action(deactivate_detector)
app.register_action(set_window)

# --- focusing: a stage to move and a detector to see with
app.register_state(AutofocusState)
app.register_startup(provide_focus)
app.register_action(run_autofocus, locks=[locks.MOTION, locks.DETECTOR])
app.register_action(calibrate_light_path, locks=[locks.MOTION, locks.DETECTOR])
app.register_action(scan_region, locks=[locks.MOTION, locks.DETECTOR, locks.EXPANSE, locks.IO])

# --- acquisition: going where a plan says, setting what it says, and imaging it. Its locks are
# stated, so nothing is inferred from what it takes: everything it depends on staying as it is.
app.register_action(acquire, locks=[locks.MOTION, locks.SWAP, locks.TUNE, locks.DETECTOR])
# What a blok can ask for (it cannot build a plan): the plan made of plain values, then `acquire`.
app.register_action(acquire_mda, locks=[locks.MOTION, locks.SWAP, locks.TUNE, locks.DETECTOR])

# --- the UC2 board
app.register_state(UC2State)
app.register_context(UC2BusManager)
app.register_startup(provide_uc2)
app.register_background(run_uc2_bus)
app.register_background(run_uc2_event_dispatch)
app.register_background(keep_firmware)  # on start: what runs, against what is pinned
app.register_action(home_stage, locks=[locks.MOTION])
# Where the holder sits: homes, holds for a person to check the light is on the calibration
# slide, finds its mark, writes the mount down. Its state is what a panel shows of it.
app.register_state(MountCalibrationState)
app.register_startup(provide_mount_calibration)
app.register_action(calibrate_mount, locks=[locks.MOTION, locks.TUNE, locks.DETECTOR])
app.register_action(stop_stage)
app.register_action(led_matrix_fill, locks=[locks.TUNE])
app.register_action(led_matrix_off, locks=[locks.TUNE])
app.register_action(uc2_scan_nodes)
app.register_action(home_objective, locks=[locks.SWAP])
app.register_action(galvo_set_position, locks=[locks.GALVO])
app.register_action(galvo_raster_scan, locks=[locks.GALVO])
app.register_action(galvo_stop)
app.register_action(galvo_get_status)
# The bus is down while it flashes: nothing may move, swap, tune or scan meanwhile.
app.register_action(update_firmware, locks=[locks.MOTION, locks.SWAP, locks.TUNE, locks.GALVO])

# --- the agent's own: the cameras as lovekit streams, mikro from the server, Orkestrator's bloks
app.register_state(CameraStreams)
app.register_startup(provide_lovekit_sink)
app.register_startup(provide_dataset_store)
app.register_background(publish_camera_streams)
declare_agent_ui(app)


def main() -> None:
    """Run `app` on the microscope ``NEWSWITCH_CONFIG`` names, until stopped.

    ``--force`` takes over a connection the server still holds for this agent (one that was not
    closed, say, and has not timed out yet); without it such a start is refused.
    """
    # As sys_config.yaml says: what newswitch says at INFO (the firmware check, how the camera
    # streams keep up) is in the log file; on the terminal with log_to_terminal: info.
    setup_logging()
    run(app, context=load_run(), force="--force" in sys.argv[1:])


if __name__ == "__main__":
    main()
