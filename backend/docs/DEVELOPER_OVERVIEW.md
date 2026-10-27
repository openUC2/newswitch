# Developer Overview

This document gives a high-level description of how this project is used, how the app is wired, and how managers, states, and routes interact.

## High-level usage

- This project provides a **virtual microscope** stack with a FastAPI server and arkitekt/rekuest integration.
- Core functionality is exposed through **registered functions** (rekuest) that operate on shared **state objects** (camera, stage, illumination, objective, IO).
- The application can stream live video frames via WebSocket and serves captured image files via HTTP.

## app.py: states, controllers, and wiring

File: newswitch/app.py

### What it does

- Bootstraps the FastAPI app and the rekuest agent wiring.
- Creates and shares **state objects** that represent the microscope’s current state.
- Instantiates **manager implementations** that operate on those states.
- Returns everything as a dependency-injection tuple used by registered functions.

Entry points: `main.py` (`uvicorn main:app`, with reload; or `python main.py`) and
`python -m newswitch.app` (`app.main()`) both build the settings with `load_app_config()`:
`base_config.yaml`, overridden by the JSON file named in `NEWSWITCH_CONFIG`, and serve on
`BACKEND_HOST`/`BACKEND_PORT` when run directly. `python -m newswitch.cli` is the
account-database tool, no server.

### Key pieces

- **States** are created once at startup: `StageState`, `IlluminationState`, `CameraState`, `ObjectiveState`, `IOState`.
- **Managers** are concrete implementations of the protocol interfaces:
  - `VirtualStageManager`
  - `VirtualLEDManager`
  - `VirtualDetectorManager`, or `UC2DetectorManager` for real cameras (see below)
  - `VirtualObjectiveManager`
  - `LocalFileIOManager`
- **FrameBroadcaster** is created to serve live video encoders and share video streams.
- **Startup hook** (`provide_managers`) returns all managers and states to the agent.
- **Shutdown hooks**: `save_device_config` writes runtime values back into the device config,
  `close_detector` closes the detector manager (stops and releases the cameras, which
  completes their recordings).
- **Background hook** (`run_detector_loop`) keeps acquisition running for live view.

### Device configuration (`newswitch/config_io/`)

`ImswitchConfig` reads `backend/base_config.yaml` (no environment variables, unknown keys are
errors). The device configuration is read from `static_config_path`
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

Everything the frontend can call lives in `newswitch/registers/`: one module per device
(`detector`, `stage`, `illumination`, `objective`, `filter_bank`, `expanse`), `uc2` (the UC2
bus itself), `routines` (registers the workflows of `newswitch/routines/`), `debug` (test and
demo actions) and `bloks`. The functions receive **managers + state** injected by the agent
and are the primary API surface for automation or external systems. `app.py` only imports
the package (`from newswitch import registers`) for its registration side effects; it holds
no `@register` function itself.

## Locking mechanism (state safety)

- State classes are decorated with `@state(required_locks=[...])` in the protocol definitions.
- Mutations of shared state must occur while holding the required locks.
- In tests, you’ll see `acquired_locks("camera_parameters", "stage_position", "objective", ...)` used to guard state initialization and mutation.
- At runtime, this ensures multi-threaded access to camera/stage/illumination/objective state is safe and consistent.

## Managers: what they do

Managers are protocol implementations that mutate state and provide behavior:

- **VirtualStageManager** updates `StageState` (positioning and movements).
- **VirtualLEDManager** updates `IlluminationState` (sources, intensities, on/off state).
- **VirtualDetectorManager** produces frames based on `CameraState`, `StageState`, `ObjectiveState`, and `IlluminationState`, and publishes them via `FrameBroadcaster`. It simulates
  the camera readout too: region of interest, binning (block means), frame rate (paces the
  live stream) and acquisition sessions.
- **UC2DetectorManager** (`managers/uc2/uc2_detector.py`) drives real cameras through the
  camera library uc2_cam_py (extra `camera`, see below); acquisition sessions are recorded to
  `.uc2rb` files.

Both implement `DetectorManager` (`protocols/detector.py`): besides activation, exposure and
gain it covers frame rate, binning and ROI (`update_detector`; `frame_rate=0` removes the
limit, `FULL_SENSOR` selects the complete sensor), snapshots with their timing
(`capture_image` returns a `DetectorFrame`), the session metadata (`get_image_info`), the
live loop (`acquire_live`, `start_acquire_live`, `stop_acquire_live`) and `close`. Live
stream and snapshot take `save_to_disk` (the virtual detector refuses it). The `Detector` in
`CameraState` holds everything about a detector: how it is configured and opened, what the
device reports (identity, sensor, ranges, capabilities), the current settings and whether it
records; the managers keep it up to date, so the frontend sees all of it.

- **VirtualObjectiveManager** updates `ObjectiveState` (selected lens, magnification data).
- **LocalFileIOManager** writes/reads image files and updates `IOState`.

### Cameras (uc2_cam_py)

`build_detector_manager` in `app.py` picks the detector manager. With
`use_virtual_microscope: false` every detector that the device configuration maps to a camera
controller (`protocol: gige-vision` / `usb3-vision`) is opened through uc2_cam_py; otherwise
(and when uc2_cam_py is not installed, with a warning) the virtual detector is used. The vendor
is the detector's `manufacturer`, passed on unchanged; vendor-specific options come from the
mapping entry's `vendor_options`. Details: `backend/configs/README.md`, section "Cameras".

- uc2_cam_py (https://github.com/openUC2/UC2_cam_py, pinned to a commit in the extra
  `camera`) is a C++ extension built from source, for Python 3.12: `uv sync --extra camera`.
  With the MVS SDK at `MVS_ROOT` (`[tool.uv] config-settings-package` in `pyproject.toml`,
  `/opt/MVS`) it supports HikRobot cameras; without it, only the simulated camera. CI leaves
  the extra out; the camera tests skip there.
- A camera acquires while anyone holds it (live stream, snapshot, debug window); every
  start is a new session.
- Writing to disk (a `.uc2rb` file in `camera_recording_dir`, `base_config.yaml`) is off
  when a camera opens and is switched by the actions `start_live_view_and_save_to_disk`
  (until `stop_live_view` or deactivating the detector) and
  `capture_image_and_save_to_disk`; uc2_cam_py's property `store_image_data` switches it
  without restarting the acquisition. A saved snapshot's file may hold an image or two next
  to it. `Detector.store_image_data` shows whether a camera writes right now.
- `camera_debug_window` (`base_config.yaml`, shipped `true`) passes `debug_window=True` to
  every `create_camera`: uc2_cam_py shows each camera's newest image in an X11 window, and the
  manager holds the cameras from startup so the window always has an image.
- `backend/configs/camTest_config.yaml` is a simulated camera for trying it out; boot with
  `NEWSWITCH_CONFIG=configs/camTest.json` (real-hardware mode, own persistent file). The
  walkthrough is "End-to-end test for camera" in the root `README.md`.

Managers are used in two places:
- **Registered functions** (for control/automation)
- **Routes** (for file serving and live streaming)

## Routes: HTTP vs WebSocket

File: newswitch/routes/http/files.py

- **HTTP file routes** serve or download captured images.
- The route uses dependency injection to fetch the `IOManager` from the app’s agent context.
- Endpoint examples:
  - `GET /files/{file_path}`: serve the file
  - `GET /files/download/{file_path}`: force download

File: newswitch/routes/ws/liveview.py

- **WebSocket live view** is a streaming endpoint (`/video`) that delivers H.264 chunks.
- The endpoint gets the `FrameBroadcaster` from the app’s agent context.
- Clients subscribe to a shared encoder so multiple viewers can share a single encoding pipeline.

## Where to look next

- Protocols and state definitions: newswitch/protocols/
- Device configuration: newswitch/config_io/ and backend/configs/README.md
- Manager implementations: newswitch/managers/
- Frame generation and helpers: newswitch/managers/helpers/
- Routes: newswitch/routes/http/ and newswitch/routes/ws/
