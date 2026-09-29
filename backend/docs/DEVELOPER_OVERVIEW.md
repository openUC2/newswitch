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

### Key pieces

- **States** are created once at startup: `StageState`, `IlluminationState`, `CameraState`, `ObjectiveState`, `IOState`.
- **Managers** are concrete implementations of the protocol interfaces:
  - `VirtualStageManager`
  - `VirtualLEDManager`
  - `VirtualDetectorManager`
  - `VirtualObjectiveManager`
  - `LocalFileIOManager`
- **FrameBroadcaster** is created to serve live video encoders and share video streams.
- **Startup hook** (`provide_managers`) returns all managers and states to the agent.
- **Shutdown hook** (`save_device_config`) writes runtime values back into the device config.
- **Background hook** (`run_detector_loop`) keeps acquisition running for live view.

### Device configuration (`newswitch/config_io/`)

`ImswitchConfig.config_file` names the device file (`main.py` sets `newswitch-config.yaml`;
bare names resolve against `backend/Configs/`). At startup `config_io.load_config()` validates
it (jsonschema per device type, then pydantic) into one dataclass per device, and
`config_io.adapters` turns those into the managers' dataclasses (`Illumination`, `Detector`,
`ObjectiveLens`, `Filter`, stage limits, serial port). A device kind missing from the file,
or `config_file=None` (the tests), keeps the manager's built-in virtual defaults. On shutdown
exposure, gain, revolver positions and stage position are written back; comments stay intact.
Details: `backend/Configs/README.md`.

### Registered functions

`app.py` registers multiple callable functions (e.g., illumination control, detector settings, capture) that receive **managers + state** injected by the agent. These functions are the primary API surface for automation or external systems.

## Locking mechanism (state safety)

- State classes are decorated with `@state(required_locks=[...])` in the protocol definitions.
- Mutations of shared state must occur while holding the required locks.
- In tests, you’ll see `acquired_locks("camera_parameters", "stage_position", "objective", ...)` used to guard state initialization and mutation.
- At runtime, this ensures multi-threaded access to camera/stage/illumination/objective state is safe and consistent.

## Managers: what they do

Managers are protocol implementations that mutate state and provide behavior:

- **VirtualStageManager** updates `StageState` (positioning and movements).
- **VirtualLEDManager** updates `IlluminationState` (sources, intensities, on/off state).
- **VirtualDetectorManager** produces frames based on `CameraState`, `StageState`, `ObjectiveState`, and `IlluminationState`, and publishes them via `FrameBroadcaster`.
- **VirtualObjectiveManager** updates `ObjectiveState` (selected lens, magnification data).
- **LocalFileIOManager** writes/reads image files and updates `IOState`.

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
- Device configuration: newswitch/config_io/ and backend/Configs/README.md
- Manager implementations: newswitch/managers/
- Frame generation and helpers: newswitch/managers/helpers/
- Routes: newswitch/routes/http/ and newswitch/routes/ws/
