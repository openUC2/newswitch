# Developer Overview

This document gives a high-level description of how this project is used, how the app is wired, and how managers, states, and routes interact.

## High-level usage

- This project provides a **virtual microscope** stack as one arkitekt app, run as an arkitekt agent or served by FastAPI with the agent embedded (`arkitekt`, `arkitekt-runtime`, `arkitekt-spec`, `arkitekt-fastapi`, pinned in `pyproject.toml`).
- Core functionality is exposed through **actions** registered on a global app (`app` in `app.py`, declared at module level), that operate on shared **state objects** (camera, stage, illumination, objective, IO). Modules only declare plain functions and plain `@dataclass` models/states; the part registries of `microscope/apps/` register every one of them, by name: every part a microscope can have, whatever the instrument has. `app` in `newswitch/microscope/registry.py` includes them all, and both `app.py` and FastAPI mode include that. The instrument is known only at run time, through the app context `Run`.
- The application streams live video frames (lovekit as an agent; a WebSocket, beside captured image files over HTTP, served by FastAPI).
- It is served one of two ways, each its own entry file: as an **arkitekt agent** (`app.py`, the standard way: Orkestrator, cameras over lovekit) or by **FastAPI** (`main_fastapi.py`, the newswitch frontend). See "Two ways to serve" below.

## Two halves: the microscope and `infra`

`newswitch/infra/` is what serves the microscope: users and auth (`accounts/`), the HTTP routes beside the agent (`http/`: live view, files, cache), the `FrameSink`s the detectors stream to (`streaming/`: the websocket live view's `FrameBroadcaster`, lovekit), where acquisitions are stored (`mikro/`) and the UI's bloks and catalog (`ui/`). Everything else under `newswitch/` is the microscope: what it is (`instrument`, `settings`), what it is built of (`drivers`, `services`, `states`, `models`), the contracts between them (`protocols`, `FrameSink` and `DatasetStore` included) and what it offers (`actions`, `routines`, assembled by `microscope/`). `infra` (and the entry files `app.py`, `main_fastapi.py`) import the microscope, never the reverse; `tests/test_layering.py` holds that (type-only imports under `TYPE_CHECKING` aside: `Run.mikro` names a `MikroConnection`).

## Wiring: main.py, app.py, main_fastapi.py, microscope/registry.py, microscope/parts.py, actions/

Files: backend/app.py, backend/main_fastapi.py, newswitch/microscope/registry.py, newswitch/microscope/parts.py, newswitch/actions/, newswitch/microscope/locks.py

### What it does

- `settings.py` (`load_settings`, `load_devices`) reads the `settings` section of the instrument `NEWSWITCH_CONFIG` names, and that instrument; both entrypoints use it.
- `main.py` is where to start: the steps every way of serving shares (registry → serve; settings → `load_devices(config)`, the instrument, as the app context `Run`; `python main.py [arkitekt|fastapi]`, the agent by default). `app.py` is the agent (below). `main_fastapi.py` (`create_fastapi_registry`, `create_app`, the uvicorn factory `create`, `main`) bootstraps the FastAPI app, reads the instrument (`Run.of(config, ...)`), creates its registry (`create_fastapi_registry(instrument)` → `App`: a fresh one the global microscope registry is merged into, the module-level startup hook `provide_frame_broadcaster(run: Run) -> FrameSink`, which provides a new `FrameBroadcaster` as the detectors' `FrameSink`, then `declare_ui`, for which alone the instrument counts) and serves it through arkitekt-fastapi:
  `configure_fastapi(app=..., app_registry=registry.registry, app_context=run, db_file=config.db_path, ...)`, then adds the auth and account routes (`newswitch/infra/accounts/`) and the module-level routers of `newswitch/infra/http/` (`liveview.router` at `/stream`, `files.router`, `cache.router`).
  The agent's journal and task history go into `arkitekt_agent.db` (`db_path` in the description's `settings`).
- `microscope/registry.py` declares `app`, `App("newswitch", app_context=Run)` (with `IDENTIFIER`, `VERSION`, `DESCRIPTION` for the served apps), and includes every part registry of `microscope/apps/` on import: the models (`MODELS`, `microscope/models.py`), the startup hooks (`microscope/startup.py`), and each state, context, action and background task. `app.py` and `main_fastapi.py` both include it. The parts: `core` (the models, io, hooks, expanse, calibration, light path, metadata, cache, the contexts `FrameSink` and `DatasetStore`, the action `clear_expanse`); `values` (the variables: `MoveState`, `SwapState`, `TuneState`, `SourceState`, `Values`, `move`, `move_one`, `move_home`, `swap`, `tune`); `detector`; `uc2` (a UC2 board in the instrument's `hardware` section, with its two background tasks); what needs several parts: `focus` (the state `AutofocusState` provided by `provide_focus`, and `run_autofocus`, `calibrate_light_path`, `scan_region`) and `acquisition` (`acquire`, `acquire_mda`). A part merges the parts it names things of, so what reaches an app through two parts counts once. What is registered does not depend on the instrument, which is known only at run time, through the app context `Run`: a part the instrument lacks (no UC2 board, no detector, no variables) is built all the same, empty, and every context and state is always provided. An argument naming a part (a stage, a variable, a detector, a board) is `Annotated[str, withStateChoices("self.<state>.<list>")]`, chosen from what its state lists (`self.move.homes`, `self.uc2.boards`, ...). States are published under short names, the class without `State` in lower case (`detector`, `move`, `uc2`, ...): a microscope without one lists nothing, and an action asked anyway refuses by name. The declaration has to be static: `arkitekt plugin build` runs `arkitekt inspect all app` inside the image, which imports the module-level `app` without any app context and bakes the declared actions, states and bloks into the release (`just agent-inspect` runs that locally, with `NEWSWITCH_CONFIG` unset). The `FrameSink` context (a runtime-checkable protocol, `newswitch.protocols.frame_sink.FrameSink`: where the detectors send their frames) is declared by the core but provided by the entry file, with a startup hook of its own; the `services` come from the entry file too, whose app merges the microscope's and registers how the frames are watched and the UI (`declare_agent_ui` for the agent's bloks, which ship with newswitch; `declare_ui` for the description's `ui` bloks). Nothing is declared on the microscope's registry from outside: it lives as long as the process. The bloks are validated strictly against what was registered: a blok calling an action newswitch does not register is refused.
- `microscope/parts.py` is data and functions: `build_microscope(settings, instrument)` creates the **state objects** and the **manager implementations** of the configured parts and returns them as a `Microscope` record (no sink: detector managers take none; `DetectorManager.acquire_live(sink)` streams to the sink it is given).
- `microscope/run.py::Run` is the app context: the settings, instrument and mikro of one run, and its one `build_microscope` (`Run.microscope`, made on the first hook: hooks see only the app context, and the parts depend on each other). Each part's startup hook in `microscope/apps/` is a plain module-level function handing out what that build made, as dependency-injection tuples used by registered functions.
- `actions/` holds the plain action, background and shutdown functions the registries of `microscope/apps/` register, one module per part: `core.py` (`clear_expanse`), `stage.py`, `illumination.py`, `detector.py` (also `run_detector_loop`, `close_detector`), `objective.py`, `filter_bank.py`, `uc2.py` (also `run_uc2_bus`, `run_uc2_event_dispatch`). The routines needing several parts live in `routines/`.

### Key pieces

- **States** (`newswitch/states/`, one module per state) are created once at startup (a part the instrument lacks keeps an empty state that shared managers read): `StageState`, `IlluminationState`, `CameraState`, `ObjectiveState`, `FilterBankState`, `IOState`, `HookState`, `ExpanseState`, `CalibrationState`, `LightPathState`, `AutofocusState`, `UC2State`. The values they hold and the actions exchange are the models in `newswitch/models/`.
- **Managers** are concrete implementations of the protocol interfaces (`newswitch/protocols/`):
  - drivers (`newswitch/drivers/`): `VirtualStageManager`, `VirtualLEDManager`, `OpticsDetectorManager` (or `UC2DetectorManager` for real cameras, see below), `VirtualObjectiveManager`, `VirtualFilterBankManager`; on UC2 hardware the bus-based managers in `drivers/uc2/`
  - services (`newswitch/services/`): `AcquisitionManager`, `LocalCacheManager`, `CalibrationManager`, `ExpanseManager`, `LocalFileIOManager`, `LightPathManager`, `MetadataManager`, `PythonHookManager`
- **FrameSink**: the context the detectors stream to, declared by the core registry and provided by the entry file's startup hook (`app.py`: a `LovekitSink`, of no cameras without detectors; `main_fastapi.py`: a `FrameBroadcaster`, which keeps the newest frame per detector for the websocket live view).
- **Startup hooks** (`app.register_startup`, one per part): `provide_core`, `provide_values`, `provide_detector`, `provide_uc2`, and `provide_focus` for the focus group — module-level functions in `microscope/apps/` with static return annotations, each returning its part's managers and states to the agent. Startup hooks get only the app context injected (no states/contexts exist yet) and none sees another's result, which is why they share one `build_microscope`, held by `Run`; an absent part's manager is never constructed (on hardware nothing talks to the bus for it): the hook returns it as None, so that context is not provided, while every state is. The entry files add one module-level startup hook each that provides the `FrameSink` (`provide_lovekit_sink`, `provide_frame_broadcaster`).
- **Shutdown hooks** (`app.register_shutdown`): `close_detector` closes the detector manager (stops and releases the cameras, which
  completes their recordings).
- **Background hooks** (`app.register_background`): `run_detector_loop(detector: DetectorManager, sink: FrameSink)` keeps acquisition running for live view (both contexts injected; it calls `detector.acquire_live(sink)`); `run_uc2_bus` and `run_uc2_event_dispatch` keep every UC2 board's bus (`UC2Boards`) connected and mirror its events into the states. Every background hook is started; one with nothing to do (no board) returns at once.

### The instrument (`newswitch/instrument/`)

`Settings` (`newswitch/settings.py`, the app context of the registry) is the `settings` section of the description (unknown keys are
errors, and every key must be there). It says whether the run is simulated (`use_virtual_microscope`), the agent's database
(`db_path`), the cameras' `camera_recording_dir` and `camera_debug_window`, where the file IO writes (`image_dir`)
and where acquired frames are cached (`cache_dir`, cleared when the microscope starts).
`load_settings` takes the instrument from `NEWSWITCH_CONFIG` (a file or folder; the root `.env` and the
Dockerfile default it to `instruments/fake-microscope/microscope.yml`); unset, or anything but a valid description, is
a `SpecError`. `load_devices(config)` reads the instrument, `Instrument | None`:
a read-only description, `backend/instruments/<name>/microscope.yml` (`instrument/spec.py`), whose `parts` section
states what the server has a control for, in which role and by which slot. newswitch never writes it: runtime values live only in the
arkitekt states and restart from each variable's `initial`. `instrument/parts.py` turns it into the managers' dataclasses
(`Illumination`, `Detector`, `ObjectiveLens`, `Filter`, stage limits;
for cameras the `Detector` with its camera fields plus the vendor options).
Its top-level `hardware:` section (`instrument/hardware.py`: boards, actuators, cameras)
says what the cubes' actuators are wired to. A simulated run ignores it, apart from a board giving it the UC2 actions
on a `VirtualUC2Bus`; a real one reaches the board over its `transport` (`rest`, `canopen`) and refuses to start until
everything with a control is wired (`check_wired`). Details: `backend/instruments/README.md`.

### Logging (`newswitch/logging_setup.py`, `backend/sys_config.yaml`)

The backend does not print, its command-line tools included (ruff rule T20, no exceptions); every
module logs through `logging.getLogger(__name__)`. `backend/sys_config.yaml` holds the backend's
global settings, whatever the microscope (`newswitch/sys_config.py`: every key must be there,
unknown keys are errors): one level for the terminal (`log_to_terminal`) and one for the log file
(`log_to_file`), each `fatal`, `error`, `warn`, `info`, `debug` or `none`, and the file
(`log_file_path`, relative to `backend/`). The file is appended to and rotated at 10 MB
(`backend.log.1` … `.3`); if it cannot be opened, `backend/backend.log` is used with a warning.
`setup_logging()` reads the file and configures logging; it runs in the entry points
(`main_fastapi.create`, the uvicorn factory; `app.main`; the tools `tools/uc2.py` (`--verbose`:
terminal at `info`), `tools/check_instrument.py`, `infra/accounts/cli.py`, `infra/export_schemas.py`),
never in `create_app`, so tests write no log files (the autouse fixture `log_dir` in
`tests/conftest.py` points it at a folder of the test's own). It takes away uvicorn's own handlers.

What a tool reports as its result goes through `console("<tool>")` (loggers under
`newswitch.console`): the bare message to stdout, warnings and errors to stderr, whatever
`log_to_terminal` says, and into the log file like every other record (not to the terminal twice).

Libraries: a library that logs to a logger of its own name without a handler, or is handed a
logger of the `newswitch` tree, follows these levels and this file. uc2_cam_py is such a library:
`drivers/uc2/uc2_detector.py` hands each camera `logging.getLogger("newswitch.camera.<name>")`,
which also gets what its C++ core says. `route_to_root` and `log_prints` take away the handlers
of a library that attaches its own, or turn its prints into records (uc2rest while its client is
built, `drivers/uc2/rest_bus.py`). Not covered: `arkitekt run …` (arkitekt's command line sets up
logging itself and does not call `app.main`), uvicorn's reloader process under `--reload`,
warnings raised while the backend is imported, prints of libraries outside `log_prints` (uc2rest
while it runs), native output.

### Registered functions

The registries of `microscope/apps/` register the actions of `newswitch/actions/<part>.py` (`app.register_action`, e.g., illumination control, detector settings, capture; the UC2 board's in `actions/uc2.py`) that receive **managers + state** injected by the agent; the routines in `newswitch/routines/` add more, each only when the parts it needs are configured. These actions are the primary API surface for automation or external systems. Long-running actions take an injected `task: Task` and call `task.progress(...)` / `task.pausepoint()`, passing the task down to managers that report progress (e.g. `StageManager.move(..., task=task)`); tests calling an action directly pass `Task.local()`.

## Locking mechanism (action locks)

- Locks belong to actions: explicit `locks=[...]` on `app.register_action`, or inferred from the contexts/states the action takes (`app.register_state(required_locks=[...])` and `app.register_context(locks=[...])` name the locks every action taking them holds).
- The lock names are the constants of `newswitch/microscope/locks.py`, one per part (and per shared service): `STAGE` (`"stage_position"`), `ILLUMINATION`, `DETECTOR` (`"camera_parameters"`), `OBJECTIVE`, `FILTER_BANK`, `GALVO`, `IO`, `HOOKS` (`"hook_registry"`), `EXPANSE` (`"expanse_state"`), `CACHE`. Each part's state and manager carry its lock (the `ObjectiveManager` too); the `AcquisitionManager` holds `EXPANSE` and `IO`; the actions that need several name theirs explicitly (`home_stage` holds `MOTION`, the galvo actions `GALVO`, ...). Keep the strings stable: clients know the locks by name.
- An action waits until no other running action holds the same lock, so two actions never command the same device at once, for the whole multi-step operation. The UI is told (LOCK/UNLOCK frames) so it can disable conflicting actions.
- State writes are not checked against locks: managers, background loops (the UC2 event dispatch) and shutdown hooks write states freely, and tests set up states without holding anything.
- Thread safety of a state write is the state's own RLock. Writes made inside an action through the injected state are attributed to the task (the patch carries its `task_id`) and are refused after the task ended; writes made by managers or hooks directly carry no task id.

## Managers: what they do

Managers are protocol implementations that mutate state and provide behavior:

- **VirtualStageManager** updates `StageState` (positioning and movements).
- **VirtualLEDManager** updates `IlluminationState` (sources, intensities, on/off state).
- **VirtualDetectorManager** produces frames based on `CameraState`, `StageState`, `ObjectiveState`, `IlluminationState` and `FilterBankState`, and streams them to the `FrameSink` `acquire_live` is given. It simulates
  the camera readout too: region of interest, binning (block means), frame rate (paces the
  live stream) and acquisition sessions. The rendering helpers are in
  `drivers/virtual/simulation/` (`frame.py`, `psf.py`). Brightness = the sample (0..1) ×
  the light (each active source's intensity / max_intensity × the transmission of the
  filters in its path; ambient light 0.02 at least) × exposure × `SIGNAL_RATE` (2e5
  counts/s), so a dark microscope gives a dark image. Defocus is a Gaussian blur of
  sigma 0.5 px per µm between the stage z and the detector's `focal_plane_z` (its
  `DetectorConfig`): the image is sharp only in focus. The autofocus scores a plane by the
  variance of its Laplacian of Gaussian (σ = 1).
- **OpticsDetectorManager** (`drivers/optics/detector.py`) is the detector of a simulated run: a
  `VirtualDetectorManager` whose images come from what the instrument's compiler finds at startup
  (`drivers/optics/simulator.py`).
- **UC2DetectorManager** (`drivers/uc2/uc2_detector.py`) drives real cameras through the
  camera library uc2_cam_py (extra `camera`, see below); acquisition sessions are recorded to
  `.uc2rb` files.

All implement `DetectorManager` (`protocols/detector.py`): besides activation, exposure and
gain it covers frame rate, binning and windows (`update_detector`; `frame_rate=0` removes the
limit, an axis no window names is read whole), snapshots with their timing
(`capture_image` returns a `DetectorFrame`, always the `(y, x)` image; `capture_channels` every
axis but `z`), the session metadata (`get_image_info`), the live loop (`acquire_live`,
`stop_acquire_live`) and `close`.

A detector has no width and height: it has **axes** (`Detector.axes`, from
`Instrument.detector_axes`), each measuring a domain of the sample (`space`, `spectrum`,
`microtime`, `time`) in the unit of what delivers it (a sensor's µm pitch, a scan's degrees, ps).
Of each spatial axis with a size it reads a **window** (`window_start`, `window_size`, in unbinned
steps; `set_window`), and a sensor's own pixels bin (`binnable`); `delivered_size` is what an image
has along it. For a camera the windows are its region of interest; for a scan the part scanned, at
the same step: a smaller field, not a zoom. `newswitch/drivers/readout.py` checks windows and reads
them out for every manager. The `Detector` in
`CameraState` holds everything about a detector: how it is configured and opened, what the
device reports (identity, sensor, ranges, capabilities), the current settings and whether it
records; the managers keep it up to date, so the frontend sees all of it.

- **VirtualObjectiveManager** updates `ObjectiveState` (selected lens, magnification data).
- **LocalFileIOManager** (`services/io/`) writes/reads image files in `image_dir` and updates `IOState`.

### Light paths, calibration and metadata

- **LightPathManager** (`services/light_path.py`) derives the light paths from the parts the
  microscope has: light sources (behind a dichroic), stage, objective turret and filter bank
  appear only when configured, nothing is hardcoded. A detector-only instrument (e.g.
  `cam-test`) gets a path with just its detector, so capture works there too. The snapshot a frame carries is a `LightPathSnapshot`
  (`models/light_path.py`); the state `LightPathState` holds the paths.
- **`calibrate_light_path`** (`routines/calibration.py`) measures how large every active
  detector's pixels are on the sample: at a fixed focus the stage moves in x only, then in y only;
  the image shifts (phase correlation, `routines/affine_matrix.py`: `pixel_shift`,
  `calibrate_pixel_to_stage`) give pixel→sample (scale, rotation and flip included), stored per
  light path in `CalibrationState`, as the optics predict it where nothing was measured
  (`OpticsManager.scale_under`). A window is not part of what a calibration is of. The stage ends
  where it started.
- **SpaceManager** (`services/space.py`) is the one place a pixel is placed: the coordinate graph
  of `newswitch/instrument/space.py`, modelled on mikro's, with each **sample** a hub of its own
  (`sample:<cube>`, on its stage `stage:<cube>`: an instrument may have several,
  `Instrument.samples`, each detector seeing one at a time, the one the swaps on its way leave
  open: `Instrument.sample_of(detector, state)`, none for one a flip mirror leaves dark). A system
  has named, typed axes (`Axis`: SPACE, CHANNEL, MICROTIME, ...); an edge is one of mikro's kinds
  (`Transformation`: IDENTITY, SCALE, TRANSLATION, AFFINE, BY_DIMENSION). A BY_DIMENSION is parts
  side by side over named axes and says nothing of an axis no part names, and a route composes
  axis by axis, by name: an axis it let go of is dropped, never taken as 0. A part that changes
  rank is walked forwards only. A detector's pixels go to the stage by that scale, where it looks
  (`where`) and where the pixel is in its window (`(x, y) -> (x, y)`, and `() -> (z)` its plane;
  its colors no part); a thermometer, which has no axes, by one part `() -> (x, y, z)`; the stage
  goes to its sample by that sample's **mount** (`SpaceState.samples[cube].mount`); an image taken
  is its detector's placement then (`image:<id>`, on its sample); a mounted plate's wells are
  places (`well:<cube>:B3`). A `Position` is coordinates by axis name; a bare `sample`, `stage` or
  `well:B3` is that of the sample the detector looking sees, or of the only one
  (`SpaceManager.resolve`), and is refused when it could be either. `move_to(position)` brings a
  place in any of those systems to the middle of the image; `set_sample_origin_here`,
  `register_mount` and `mount_holder` set a sample's mount. `SpaceState` publishes the live graph
  (`systems`, `transformations`), each sample's mount and what it is mounted on (`samples`), every
  imaging detector's placement as a 4x4 and where each point detector measures (`points`), each
  with its sample.
- **MetadataManager** (`services/metadata.py`) places each frame by `SpaceManager.placement`;
  an acquisition keeps a record per position and detector (`AcquiredRecord`), along its own axes,
  placed by its detector's route (`SpaceManager.record_map`, as BY_DIMENSION parts: `to_parts`).
- **Holders** (`newswitch/instrument/holders/*.yml`): a slide, a dish, a 96-well plate, each a
  frame from its top left corner. A description names the ones its sample takes and where each
  sits on its stage (`holders`, `mounted` on the `kind: sample` element).

### Hooks

Acquisition hooks (`models/hooks.py`) run through `PythonHookManager`
(`services/hooks/manager.py`), which runs each hook with the handler registered for its
type. `execute` refuses a hook without a handler (`UnsupportedHook`) rather than skipping
it, and `check(hooks, level)` validates the hooks of an acquisition before anything moves.
`SoftwareAutofocusHook` (`z_range`, `steps`) is handled by
`services/hooks/software_autofocus.py`, registered only with a stage and a detector;
`ZCalibrationHook` has no handler, so it is refused. In a multidimensional acquisition
`m_hooks` run at the start, `t_hooks` per timepoint, `p_hooks` after the stage moved to the
position (the stack is then centred on the refocused z), and an autofocus among the
`z_hooks` is refused (it would move the stack it is part of). The models of an acquisition
(`MultidimensionalAcquisition`, `StreamIllumination`, `Stack`, ...) are in
`models/acquisition.py`; the routines share `routines/common.py` (`z_sweep`,
`field_of_view`, `acquire_step`).

### Cameras (uc2_cam_py)

`build_detector_manager` in `microscope/parts.py` picks the detector manager. With
`use_virtual_microscope: false` every sensor with a camera in the description's `hardware.cameras`
(`protocol: gige-vision` / `usb3-vision`) is opened through uc2_cam_py (`UC2DetectorManager`; a sensor
without one stops `check_wired`); otherwise
(and when uc2_cam_py is not installed, with a warning) the `OpticsDetectorManager` is used. The vendor
is the entry's `vendor`, passed on unchanged; vendor-specific options come from its
`vendor_options`. Details: `backend/instruments/README.md`.

- uc2_cam_py (https://github.com/openUC2/UC2_cam_py, pinned to a commit in the extra
  `camera`) is a C++ extension; building it needs the MVS SDK (`/opt/MVS`) and Python 3.12,
  also for its simulated camera: `uv sync --extra camera`. CI leaves the extra out; the
  camera tests skip there.
- A camera acquires while anyone holds it (live stream, snapshot, debug window); every
  start is a new session and, with `store_image_data`, a new `.uc2rb` file in
  `camera_recording_dir` (the description's `settings`).
- `camera_debug_window` (the description's `settings`) passes `debug_window=True` to
  every `create_camera`: uc2_cam_py shows each camera's newest image in an X11 window, and the
  manager holds the cameras from startup so the window always has an image.
- `backend/instruments/cam-test/` is a simulated camera for trying it out; boot with
  `NEWSWITCH_CONFIG=instruments/cam-test/microscope.yml` (real-hardware mode). The
  walkthrough is "End-to-end test for camera" in the root `README.md`.

Managers are used in two places:
- **Registered functions** (for control/automation)
- **Routes** (for file serving and live streaming)

## Two ways to serve

Files: backend/main.py, backend/app.py, backend/main_fastapi.py, newswitch/protocols/frame_sink.py, newswitch/infra/streaming/lovekit.py, newswitch/infra/ui/

- Both entry files declare the same microscope (both include `newswitch.microscope.registry.app`), register on it what is particular to them, among it a module-level startup hook that provides the `FrameSink`, and run it with a `Run` of the description `NEWSWITCH_CONFIG` names (`main.py`; `python main.py [arkitekt|fastapi]`, the agent by default).
- Detectors only know the `FrameSink` protocol: `start_broadcasting()` and `broadcast_sync(slot, frame)`, called from the detector's thread. It is a context the microscope registry registers; each entry file provides it its way.

| | `app.py` (agent, standard) | `main_fastapi.py` |
|---|---|---|
| Run | `just agent --url <server>`, `python app.py`, `arkitekt run prod app --context app:load_run` | `uvicorn main_fastapi:create --factory`, `just dev` |
| Registry | the global, module-level `app`; context `load_run()` | `create_fastapi_registry(instrument, with_mikro)` → `App` |
| Sink | `LovekitSink(cameras_of(current.instrument))`, provided as the `FrameSink` (of no cameras without detectors); `services=(lovekit_service, mikro_service)` | `FrameBroadcaster`, provided as the `FrameSink` |
| Registers | state `CameraStreams`, startup `provide_lovekit_sink` → `Tuple[FrameSink, CameraStreams]`, startup `provide_dataset_store`, background `publish_camera_streams` (returns at once without detectors) | startup `provide_frame_broadcaster` → `FrameSink`; `provide_no_dataset_store`, or the part `mikro_app` |
| UI | the agent's bloks, shipped with newswitch (`newswitch/infra/ui/agent/`), the base catalog or Orkestrator's (`declare_agent_ui`) | the description's `ui`, newswitch frontend's catalog (`declare_ui`) |
| HTTP routes | none | auth, accounts, `newswitch/infra/http/` (live view, files, cache) |

- **`app.py`** (extra `agent` = `arkitekt[rekuest,lovekit]`, `uv sync --extra agent`; arkitekt's default target name): the global `app`, declared at module level, reads nothing of an instrument; `load_run()` is the zero-argument factory of its context (`Run.of(load_settings())`, reading `NEWSWITCH_CONFIG`); `main()` runs `run(app, context=load_run())`, logging in to the arkitekt server fakts finds (`--url` / `$FAKTS_URL`). `app` is an `App` with `services=(lovekit_service, mikro_service)` on which every part is registered directly, the state `CameraStreams`, the startup hooks `provide_lovekit_sink` and `provide_dataset_store`, the background `publish_camera_streams`, and `declare_agent_ui(app)`. It runs on any instrument: each detector becomes a lovekit `VideoStream` (`cameras_of(instrument)` → `list[CameraStream]`), keyed by its sensor's cube (stable across restarts), titled by that too. `provide_lovekit_sink(current: Run) -> Tuple[FrameSink, CameraStreams]` provides `LovekitSink(cameras_of(current.instrument))` (it takes its cameras in the constructor; none without detectors, and `publish_camera_streams` then returns at once), and a `CameraStreams()`. `LovekitSink` keeps the newest frame per detector; the background hook `publish_camera_streams(lovekit, sink: FrameSink, live: CameraStreams)` (a `TypeError` for a sink that is not a `LovekitSink`) sends at most `MAX_FPS` (15) frames per stream, converting with `to_rgba` off the event loop (`asyncio.to_thread`, ~37 ms per 1920×1200 frame). The declared streams are held in the state `CameraStreams`. UI = the agent's bloks (`AGENT_BLOKS` in `newswitch/infra/ui/__init__.py`: `view-microscope`, the default, from `agent/microscope.bsx`, and `view-acquire` from `agent/mda.bsx`), the same on every microscope, checked strictly against the catalog each names and the registry (`declare_agent_ui`). They bind variables by name, so a description follows the convention that the stage is the cube `stage` with moves `x`, `y`, `z`. A description's `agent_ui` section is refused (`spec.load`). Only `app.py` imports lovekit (`newswitch/infra/streaming/lovekit.py`, not imported by the `infra.streaming` package). Tested offline with a fake lovekit client only. The agent serves no HTTP routes: the files the IO manager writes and the frame cache are not reachable from Orkestrator, so a frame's cache id or a file handle points nowhere there (open).
- **`main_fastapi.py`**: the websocket live view (`/stream/...`, below) subscribes to the `FrameBroadcaster` the startup hook `provide_frame_broadcaster` provides as the `FrameSink`, read off the running agent's contexts; `create_app` includes the module-level routers of `newswitch/infra/http/`.

## Routes: HTTP vs WebSocket

The routes `main_fastapi.py` serves beside the agent live in `newswitch/infra/http/`; `create_app` includes their module-level routers (`newswitch.infra.http.liveview.router` at `/stream`, `newswitch.infra.http.files.router`, `newswitch.infra.http.cache.router`). All read what they need off the running agent's contexts (`running_context(connection, cls)` in `infra/http/__init__.py`, for requests and websockets): files the `IOManager`, cache the `CacheManager`, the live view the `FrameBroadcaster` (provided as the `FrameSink`). Before startup the HTTP routes answer 503 and the live-view websocket closes with 1013. Account management stays in `newswitch/infra/accounts/routes.py`.

File: newswitch/infra/http/files.py

- **HTTP file routes** serve or download captured images (the `IOManager`'s files).
- Endpoint examples:
  - `GET /files/{file_path}`: serve the file
  - `GET /files/download/{file_path}`: force download

File: newswitch/infra/http/cache.py

- `GET /cache/{store_id}/{key}`: the frame cache (Zarr stores) for the frontend's viewer.

File: newswitch/infra/http/liveview.py

- **WebSocket live view**: `/stream/frames/{detector_slot}?max_size=640&max_fps=30` delivers a detector's frames, one whole frame per message (`newswitch/infra/streaming/wire.py`): the detector's own values, binned to `max_size` (0 sends full size), compressed losslessly; the client's first message is its auth frame, then it answers each frame with a message.
- A viewer is sent the newest frame once it acknowledged the last (`FrameBroadcaster.subscribe`): a slow one skips frames instead of the server buffering them without limit, and one can join at any time. Run uvicorn with `--ws-per-message-deflate false`, or the websocket's own compression of every frame takes a core and most of the frame rate.

## Where to look next

- The app registry and settings: newswitch/microscope/registry.py, newswitch/settings.py, newswitch/settings.py
- The two entry files: backend/main.py, backend/app.py, backend/main_fastapi.py; frame sinks: newswitch/infra/streaming/ (lovekit.py for the agent)
- Managers and states of the configured parts: newswitch/microscope/parts.py
- Actions, background and shutdown functions: newswitch/actions/ (one module per part); routines: newswitch/routines/
- Locks: newswitch/microscope/locks.py
- Manager protocols: newswitch/protocols/; states: newswitch/states/; models: newswitch/models/
- The instrument: newswitch/instrument/ and backend/instruments/README.md
- Manager implementations: newswitch/drivers/ (optics/, uc2/, virtual/) and newswitch/services/
- Frame generation and helpers: newswitch/drivers/virtual/simulation/
- Routes: newswitch/infra/http/ (live view, files, cache) and newswitch/infra/accounts/routes.py (accounts)
