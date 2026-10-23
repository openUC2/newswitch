# newswitch

`newswitch` is a Vite + React + TypeScript frontend for operating and replaying a microscope workflow.
It combines a generated app API, a scoped runtime for live state/task/lock synchronization, and a replay mode that can scrub through recorded sessions.

## What this project does

The application has two main faces:

- **Live control** for driving microscope hardware and acquisition workflows.
- **Replay** for inspecting recorded sessions on a timeline and reconstructing application state at any point in time.

At runtime, the UI is built around generated app definitions and a shared provider stack that keeps task state, lock state, and state snapshots synchronized with the backend.

## Main features

### Microscope control

The default route is an operator workspace with:

- **Settings panel** for camera, illumination, filters, and objective control
- **Live / stop / snap / reset** acquisition actions
- **Status panel** for camera, stage, light, and objective connectivity
- **Stage control** with XY jog, Z jog, absolute moves, homing, and progress feedback
- **Expanse / stage view** for the central visualization surface
- **Light path calibration** tools
- **Multidimensional acquisition** setup for positions, stacks, timepoints, channels, and illumination plans

Relevant entry points include [src/pages/IndexPage.tsx](src/pages/IndexPage.tsx), [src/components/microscope/SettingsPanel.tsx](src/components/microscope/SettingsPanel.tsx), [src/components/microscope/StageControl.tsx](src/components/microscope/StageControl.tsx), and [src/components/microscope/MultidimensionalAcquisitionControl.tsx](src/components/microscope/MultidimensionalAcquisitionControl.tsx).

### Replay

The replay route reconstructs a recorded session rather than talking to the microscope as a live control surface.

Key ideas:

- session boundaries are loaded and exposed in the navigation chrome
- a selected time is converted into a global revision
- the runtime checks out snapshots for that revision
- recent patches are surfaced in the UI so it is clear what changed most recently
- the same app-scoped state model is reused for live and replay views

The replay UI is mounted from [src/pages/ReplayPage.tsx](src/pages/ReplayPage.tsx), while the timeline and latest-change indicators live in [src/components/navigation/AppNavigationChrome.tsx](src/components/navigation/AppNavigationChrome.tsx).

## General architecture

### App-scoped runtime

The frontend uses generated app definitions and wires them into a scoped provider created in [src/App.tsx](src/App.tsx).

That provider stack is responsible for:

- connecting to the backend API and websocket endpoints
- holding synchronized stores for states, tasks, and locks
- hydrating initial live data
- switching between live updates and replay checkout
- validating incoming snapshots against generated schemas

The core orchestration is in [src/lib/arkitekt/BundleProvider.tsx](src/lib/arkitekt/BundleProvider.tsx).

### Generated app definitions

This project does not hand-write most app bindings.
Instead, it generates them from backend-exposed schemas.

Generated output includes app-specific:

- action/task hooks
- state hooks and schemas
- lock hooks and schemas
- app registry definitions consumed by the runtime

The generated registry is consumed from [src/apps](src/apps).

## Autogeneration workflow

Schema-driven generation is centralized in [plugins/generate-app.ts](plugins/generate-app.ts).

The generator:

1. reads the committed schema export (`frontend/schemas/*.json`, written by the backend's
   `just export-schemas` from a complete reference microscope)
2. derives port and model information
3. emits strongly typed frontend bindings
4. writes the shared app registry

Important behavior:

- model generation is consolidated in one place
- state/task/lock generation shares the same schema translation approach
- no backend is needed: a missing or unreadable export fails the build (`just export-schemas` writes it)

This keeps the UI aligned with backend contracts while reducing manual maintenance.

## Project structure

- [src/App.tsx](src/App.tsx) – top-level routing and provider composition
- [src/pages](src/pages) – route-level pages for live and replay modes
- [src/components/microscope](src/components/microscope) – microscope UI and workflows
- [src/components/navigation](src/components/navigation) – app chrome and replay timeline UI
- [src/lib/arkitekt](src/lib/arkitekt) – runtime integration and synchronization logic
- [src/store](src/store) – local shared stores
- [src/apps](src/apps) – generated app bindings used by the runtime
- [plugins/generate-app.ts](plugins/generate-app.ts) – schema-driven code generation

## Development

### Install

```bash
yarn
```

### Run

```bash
yarn dev
```

### Type-check

```bash
yarn types
```

### Build

```bash
yarn build
```

## Backend configuration

The frontend reads backend endpoints from injected globals when available, with environment fallbacks:

- `window.__agent_url__` or `VITE_BACKEND_URL`
- `window.__agent_ws_url__` or `VITE_WEBSOCKET_URL`

This allows the same UI to run in local development and in embedded/deployed environments.

## Summary

`newswitch` is a generated, replay-aware microscope frontend.
Its main design goal is to keep live control, recorded replay, and backend schema contracts in one consistent app model rather than treating them as separate products.
