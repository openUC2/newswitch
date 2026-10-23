# Developer Overview

This document gives a high-level description of how this project is used, how the app is wired, and how managers, states, and routes interact.

## High-level usage

- This project provides a **virtual microscope** stack with a FastAPI server and an embedded arkitekt agent (`arkitekt`, `arkitekt-runtime`, `arkitekt-spec`, `arkitekt-fastapi`, pinned in `pyproject.toml`).
- Core functionality is exposed through **actions** registered on an app registry that `create_registry` (`newswitch/microscope/registry.py`) creates fresh for every app, that operate on shared **state objects** (camera, stage, illumination, objective, IO). Modules only declare plain functions and plain `@dataclass` models/states; nothing registers itself on import, and `create_registry` registers everything explicitly, by name, according to the device configuration.
- The application can stream live video frames via WebSocket and serves captured image files via HTTP.
- It is served one of two ways, each its own entry file: **FastAPI** (`main_fastapi.py`, the newswitch frontend) or as an **arkitekt agent** (`main_arkitekt.py`, Orkestrator, cameras over lovekit). See "Two ways to serve" below.

## Wiring: main.py, main_fastapi.py, main_arkitekt.py, microscope/registry.py, microscope/parts.py, actions/

Files: backend/main_fastapi.py, newswitch/microscope/registry.py, newswitch/microscope/parts.py, newswitch/actions/, newswitch/microscope/locks.py

### What it does

- `settings.py` (`load_settings`, `load_devices`) reads `base_config.yaml` (or the file `NEWSWITCH_CONFIG` names) and the device configuration; both entrypoints use it (`main.load_settings` no longer exists).
- `main.py` is where to start: the steps every way of serving shares (settings → `load_devices(config, "ui" | "agent_ui")`, which raises `ConfigError` for a configuration without that UI section → registry → serve; `python main.py fastapi|arkitekt`). `main_fastapi.py` (`create_fastapi_registry`, `create_app`, the uvicorn factory `create`, `main`) bootstraps the FastAPI app, reads the device configuration (`load_devices(config, "ui")`), creates its registry (`create_fastapi_registry(devices)` → `App`: `create_registry(devices)`, the module-level startup hook `provide_frame_broadcaster(app_context: Settings) -> Tuple[FrameSink]`, which provides a new `FrameBroadcaster` as the detectors' `FrameSink`, then `declare_ui`) and serves it through arkitekt-fastapi:
  `configure_fastapi(app=..., app_registry=registry.registry, app_context=config, db_file=config.db_path, ...)`, then adds the auth and account routes (`accounts/`) and the module-level routers of `newswitch/routes/` (`liveview.router` at `/stream`, `files.router`, `cache.router`).
  The agent's journal and task history go into `arkitekt_agent.db` (`db_path` in `base_config.yaml`).
- `microscope/registry.py::create_registry(devices, services=())` creates a fresh `App("newswitch", app_context=Settings, services=services)` and registers, explicitly and by name: the models always (`register_models`); the core (io, hooks, expanse, calibration, light path, metadata, cache, the context `FrameSink`, the action `clear_expanse`); one group per configured part — stage, illumination, detector, objective, filter bank, UC2 board (a uc2-rest or canopen controller) — each with its states, contexts, startup hook, actions and background tasks; what needs several parts: the focus group (stage + detector, `parts.focus`: the state `AutofocusState` provided by `provide_focus`, and `run_autofocus`, `calibrate_light_path`, `scan_region`), `acquire_multidimensional_acquisition` (stage + detector + illumination) and `run_uc2_event_dispatch` (UC2 board + stage). The `FrameSink` context (a runtime-checkable protocol, `newswitch.broadcasters.FrameSink`: where the detectors send their frames) is registered here but provided by the entry file, with a startup hook of its own; the `services` come from the entry file too, which then registers how the frames are watched and the UI (`declare_ui` for `ui`, `declare_agent_ui` for `agent_ui`) on the returned app. Without a configuration only the models and the core are registered, so `clear_expanse` is the only action (beside the core states). The configuration's UI bloks are validated strictly against what was registered: a blok calling an action whose device is absent is refused.
- `microscope/parts.py` is data and functions: `configured_parts(devices)` says which parts there are (a `Parts` value); `build_microscope(settings, devices)` creates the **state objects** and the **manager implementations** of the configured parts and returns them as a `Microscope` record (no sink: detector managers take none; `DetectorManager.acquire_live(sink)` streams to the sink it is given).
- `create_registry` defines one startup hook per part as a closure next to its registration; they hand the agent the objects of one `build_microscope` (made on the first hook: hooks see only the app context, and the parts depend on each other), as dependency-injection tuples used by registered functions.
- `actions/` holds the plain action, background and shutdown functions `create_registry` registers, one module per part: `core.py` (`clear_expanse`), `stage.py`, `illumination.py`, `detector.py` (also `run_detector_loop`, `close_detector`), `objective.py`, `filter_bank.py`, `uc2.py` (also `run_uc2_bus`, `run_uc2_event_dispatch`). The routines needing several parts live in `routines/`.

### Key pieces

- **States** (`newswitch/states/`, one module per state) are created once at startup (a part the configuration lacks keeps an empty state that shared managers read): `StageState`, `IlluminationState`, `CameraState`, `ObjectiveState`, `FilterBankState`, `IOState`, `HookState`, `ExpanseState`, `CalibrationState`, `LightPathState`, `AutofocusState`, `UC2State`. The values they hold and the actions exchange are the models in `newswitch/models/`.
- **Managers** are concrete implementations of the protocol interfaces (`newswitch/protocols/`):
  - drivers (`newswitch/drivers/`): `VirtualStageManager`, `VirtualLEDManager`, `VirtualDetectorManager` (or `UC2DetectorManager` for real cameras, see below), `VirtualObjectiveManager`, `VirtualFilterBankManager`; on UC2 hardware the bus-based managers in `drivers/uc2/`
  - services (`newswitch/services/`): `AcquisitionManager`, `LocalCacheManager`, `CalibrationManager`, `ExpanseManager`, `LocalFileIOManager`, `LightPathManager`, `MetadataManager`, `PythonHookManager`
- **FrameSink**: the context the detectors stream to, registered by `create_registry` and provided by the entry file's startup hook (`main_fastapi.py`: a `FrameBroadcaster`, which serves the live video encoders and shares video streams; `main_arkitekt.py`: a `LovekitSink`).
- **Startup hooks** (`app.register_startup`, one per configured part): `provide_core`, `provide_stage`, `provide_illumination`, `provide_detector`, `provide_objective`, `provide_filter_bank`, `provide_uc2`, and `provide_focus` for the focus group — closures in `create_registry` with static `Tuple[...]` return annotations, each returning its part's managers and states to the agent. Startup hooks get only the app context injected (no states/contexts exist yet) and none sees another's result, which is why they share one `build_microscope`, made on the first hook; an absent part's manager is never constructed (on hardware nothing talks to the bus for it). The entry files add one module-level startup hook each that provides the `FrameSink` (`provide_frame_broadcaster`, `provide_lovekit_sink`).
- **Shutdown hooks** (`app.register_shutdown`): `save_device_config` (if the microscope was started) writes runtime values back into the device config,
  `close_detector` closes the detector manager (stops and releases the cameras, which
  completes their recordings).
- **Background hooks** (`app.register_background`): `run_detector_loop(detector: DetectorManager, sink: FrameSink)` keeps acquisition running for live view (both contexts injected; it calls `detector.acquire_live(sink)`); `run_uc2_bus` and `run_uc2_event_dispatch` keep the UC2 bus connected and mirror its events into the states.

### Device configuration (`newswitch/config_io/`)

`Settings` (`newswitch/settings.py`, the app context of the registry) reads `backend/base_config.yaml` (no environment variables, unknown keys are
errors). Besides the device configuration it names where the file IO writes (`image_dir`)
and where acquired frames are cached (`cache_dir`, cleared when the microscope starts).
The device configuration is read from `static_config_path`
(`configs/newswitch-config.yaml`) or, with `load_from_static_config_path: false`, from
`persistent_config_path`, which is created as a copy of the static file on first start;
bare names resolve against `config_dir` (`backend/configs/`). The static file is never
written: every change goes into the persistent one. At startup `config_io.open_config()`
validates the file (jsonschema per device type, pydantic, cross-device references) into one
dataclass per device, and `config_io.adapters` turns those into the managers' dataclasses
(`Illumination`, `Detector`, `ObjectiveLens`, `Filter`, stage limits, serial port;
for cameras the `Detector` with its camera fields plus the vendor options).
Connection data lives only in controllers, whose `mapping` assigns the other devices.
A device kind missing from the file, or `config_file=None` (the tests), keeps the manager's
built-in virtual defaults. On shutdown exposure, gain, wheel positions and stage position
are written back; comments stay intact. Details: `backend/configs/README.md`.

### Registered functions

`create_registry` registers the actions of `newswitch/actions/<part>.py` (`app.register_action`, e.g., illumination control, detector settings, capture; the UC2 board's in `actions/uc2.py`) that receive **managers + state** injected by the agent; the routines in `newswitch/routines/` add more, each only when the parts it needs are configured. These actions are the primary API surface for automation or external systems. Long-running actions take an injected `task: Task` and call `task.progress(...)` / `task.pausepoint()`, passing the task down to managers that report progress (e.g. `StageManager.move(..., task=task)`); tests calling an action directly pass `Task.local()`.

## Locking mechanism (action locks)

- Locks belong to actions: explicit `locks=[...]` on `app.register_action`, or inferred from the contexts/states the action takes (`app.register_state(required_locks=[...])` and `app.register_context(locks=[...])` name the locks every action taking them holds).
- The lock names are the constants of `newswitch/microscope/locks.py`, one per part (and per shared service): `STAGE` (`"stage_position"`), `ILLUMINATION`, `DETECTOR` (`"camera_parameters"`), `OBJECTIVE`, `FILTER_BANK`, `GALVO`, `IO`, `HOOKS` (`"hook_registry"`), `EXPANSE` (`"expanse_state"`), `CACHE`. Each part's state and manager carry its lock (the `ObjectiveManager` too); the `AcquisitionManager` holds `EXPANSE` and `IO`; the UC2 actions name theirs explicitly (`home_stage` holds `STAGE`, the galvo actions `GALVO`, ...). Keep the strings stable: clients know the locks by name.
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
- **UC2DetectorManager** (`drivers/uc2/uc2_detector.py`) drives real cameras through the
  camera library uc2_cam_py (extra `camera`, see below); acquisition sessions are recorded to
  `.uc2rb` files.

Both implement `DetectorManager` (`protocols/detector.py`): besides activation, exposure and
gain it covers frame rate, binning and ROI (`update_detector`; `frame_rate=0` removes the
limit, `FULL_SENSOR` selects the complete sensor), snapshots with their timing
(`capture_image` returns a `DetectorFrame`), the session metadata (`get_image_info`), the
live loop (`acquire_live`, `stop_acquire_live`) and `close`. The `Detector` in
`CameraState` holds everything about a detector: how it is configured and opened, what the
device reports (identity, sensor, ranges, capabilities), the current settings and whether it
records; the managers keep it up to date, so the frontend sees all of it.

- **VirtualObjectiveManager** updates `ObjectiveState` (selected lens, magnification data).
- **LocalFileIOManager** (`services/io/`) writes/reads image files in `image_dir` and updates `IOState`.

### Light paths, calibration and metadata

- **LightPathManager** (`services/light_path.py`) derives the light paths from the parts the
  microscope has: light sources (behind a dichroic), stage, objective turret and filter bank
  appear only when configured, nothing is hardcoded. A detector-only configuration (e.g.
  `camTest`) gets a path with just its detector, so capture works there too. The snapshot a frame carries is a `LightPathSnapshot`
  (`models/light_path.py`); the state `LightPathState` holds the paths.
- **`calibrate_light_path`** (`routines/calibration.py`) measures the pixel→stage transform
  of every active detector: at a fixed focus the stage moves `CALIBRATION_STEP_UM` (20 µm)
  in x only, then in y only; the image shifts (phase correlation,
  `routines/affine_matrix.py`: `pixel_shift`, `calibrate_pixel_to_stage`) give the 4×4 affine
  (scale, rotation and flip included), stored per light path in `CalibrationState`. The
  stage ends where it started.
- **MetadataManager** (`services/metadata.py`) places each frame with the calibrated affine of
  its light path; without a calibration it falls back to the nominal pixel size (the
  detector's `pixel_size_um` / the objective's magnification).

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
`use_virtual_microscope: false` every detector that the device configuration maps to a camera
controller (`protocol: gige-vision` / `usb3-vision`) is opened through uc2_cam_py; otherwise
(and when uc2_cam_py is not installed, with a warning) the virtual detector is used. The vendor
is the detector's `manufacturer`, passed on unchanged; vendor-specific options come from the
mapping entry's `vendor_options`. Details: `backend/configs/README.md`, section "Cameras".

- uc2_cam_py (https://github.com/openUC2/UC2_cam_py, pinned to a commit in the extra
  `camera`) is a C++ extension; building it needs the MVS SDK (`/opt/MVS`) and Python 3.12,
  also for its simulated camera: `uv sync --extra camera`. CI leaves the extra out; the
  camera tests skip there.
- A camera acquires while anyone holds it (live stream, snapshot, debug window); every
  start is a new session and, with `store_image_data`, a new `.uc2rb` file in
  `camera_recording_dir` (`base_config.yaml`).
- `camera_debug_window` (`base_config.yaml`, shipped `true`) passes `debug_window=True` to
  every `create_camera`: uc2_cam_py shows each camera's newest image in an X11 window, and the
  manager holds the cameras from startup so the window always has an image.
- `backend/configs/camTest_config.yaml` is a simulated camera for trying it out; boot with
  `NEWSWITCH_CONFIG=configs/camTest.json` (real-hardware mode, own persistent file). The
  walkthrough is "End-to-end test for camera" in the root `README.md`.

Managers are used in two places:
- **Registered functions** (for control/automation)
- **Routes** (for file serving and live streaming)

## Two ways to serve

Files: backend/main.py, backend/main_fastapi.py, backend/main_arkitekt.py, newswitch/broadcasters/sink.py, newswitch/broadcasters/lovekit.py

- Both entry files start the same way (`main.py`: settings, then `load_devices(config, "ui" | "agent_ui")`, a `ConfigError` without that UI section), call `create_registry(devices, services=())`, then register on the returned app what is particular to them, among it a module-level startup hook that provides the `FrameSink`.
- Detectors only know the `FrameSink` protocol: `start_broadcasting()` and `broadcast_sync(slot, frame)`, called from the detector's thread. It is a context `create_registry` registers; each entry file provides it its way.

| | `main_fastapi.py` | `main_arkitekt.py` |
|---|---|---|
| Run | `uvicorn main_fastapi:create --factory`, `just dev` | `python main_arkitekt.py`, `just agent` |
| Registry | `create_fastapi_registry(devices)` → `App` | `create_arkitekt_registry(devices)` → `App` |
| Sink | `FrameBroadcaster`, provided as the `FrameSink` | `LovekitSink(cameras_of(devices))`, provided as the `FrameSink`; `services=(lovekit_service,)` |
| Registers | startup `provide_frame_broadcaster` → `Tuple[FrameSink]` | state `CameraStreams`, startup `provide_lovekit_sink` → `Tuple[FrameSink, CameraStreams]`, background `publish_camera_streams` (when there are detectors) |
| UI | config `ui`, newswitch frontend's catalog (`declare_ui`) | config `agent_ui`, Orkestrator's standard catalog (`declare_agent_ui`) |
| HTTP routes | auth, accounts, `newswitch/routes/` (live view, files, cache) | none |

- **`main_fastapi.py`**: the websocket live view (`/stream/...`, below) subscribes to the `FrameBroadcaster` the startup hook `provide_frame_broadcaster` provides as the `FrameSink`, read off the running agent's contexts; `create_app` includes the module-level routers of `newswitch/routes/`.
- **`main_arkitekt.py`** (extra `agent` = `arkitekt[rekuest,lovekit]`, `uv sync --extra agent`): runs via `arkitekt.run`, logging in to the arkitekt server fakts finds (`--url` / `$FAKTS_URL`). `create_arkitekt_registry(devices)` → `App` is `create_registry(devices, services=(lovekit_service,))`, the state `CameraStreams`, the startup hook `provide_lovekit_sink`, `publish_camera_streams` when there are detectors, and `declare_agent_ui`. Each configured detector becomes a lovekit `VideoStream` (`cameras_of(devices)` → `list[CameraStream]`), keyed by its device-config key (stable across restarts), titled by its name. `provide_lovekit_sink(app_context: Settings) -> Tuple[FrameSink, CameraStreams]` provides `LovekitSink(cameras_of(load_devices(app_context)))` (it takes its cameras in the constructor) and a `CameraStreams()`. `LovekitSink` keeps the newest frame per detector; the background hook `publish_camera_streams(lovekit, sink: FrameSink, live: CameraStreams)` (a `TypeError` for a sink that is not a `LovekitSink`) sends at most `MAX_FPS` (15) frames per stream, converting with `to_rgba` off the event loop (`asyncio.to_thread`, ~37 ms per 1920×1200 frame). The declared streams are held in the state `CameraStreams`. UI = the config's `agent_ui`, in Orkestrator's standard catalog (`orkestrator@v4.2.1`), checked strictly against it and the registry (`declare_agent_ui`, `check_agent_catalog`); a config without `agent_ui` does not start. Only `main_arkitekt.py` imports lovekit (`newswitch/broadcasters/lovekit.py`, not imported by the `broadcasters` package). Tested offline with a fake lovekit client only. The agent serves no HTTP routes: the files the IO manager writes and the frame cache are not reachable from Orkestrator, so a frame's cache id or a file handle points nowhere there (open).

## Routes: HTTP vs WebSocket

The routes `main_fastapi.py` serves beside the agent live in `newswitch/routes/`; `create_app` includes their module-level routers (`newswitch.routes.liveview.router` at `/stream`, `newswitch.routes.files.router`, `newswitch.routes.cache.router`). All read what they need off the running agent's contexts (`running_context(connection, cls)` in `routes/__init__.py`, for requests and websockets): files the `IOManager`, cache the `CacheManager`, the live view the `FrameBroadcaster` (provided as the `FrameSink`). Before startup the HTTP routes answer 503 and the live-view websocket closes with 1013. Account management stays in `newswitch/accounts/routes.py`.

File: newswitch/routes/files.py

- **HTTP file routes** serve or download captured images (the `IOManager`'s files).
- Endpoint examples:
  - `GET /files/{file_path}`: serve the file
  - `GET /files/download/{file_path}`: force download

File: newswitch/routes/cache.py

- `GET /cache/{store_id}/{key}`: the frame cache (Zarr stores) for the frontend's viewer.

File: newswitch/routes/liveview.py

- **WebSocket live view**: `/stream/zstd/{detector_slot}` and `/stream/h264/{detector_slot}` deliver a detector's frames, encoded as the client asks; the client's first message is its auth frame.
- Clients subscribe to a shared encoder so multiple viewers can share a single encoding pipeline.

## Where to look next

- The app registry and settings: newswitch/microscope/registry.py, newswitch/settings.py, newswitch/settings.py
- The two entry files: backend/main.py, backend/main_fastapi.py, backend/main_arkitekt.py; frame sinks: newswitch/broadcasters/ (lovekit.py for the agent)
- Managers and states of the configured parts: newswitch/microscope/parts.py
- Actions, background and shutdown functions: newswitch/actions/ (one module per part); routines: newswitch/routines/
- Locks: newswitch/microscope/locks.py
- Manager protocols: newswitch/protocols/; states: newswitch/states/; models: newswitch/models/
- Device configuration: newswitch/config_io/ and backend/configs/README.md
- Manager implementations: newswitch/drivers/ (uc2/, virtual/) and newswitch/services/
- Frame generation and helpers: newswitch/drivers/virtual/simulation/
- Routes: newswitch/routes/ (live view, files, cache) and newswitch/accounts/routes.py (accounts)
