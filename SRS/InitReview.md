# newswitch — Initial Architecture Review

**Date:** 2026-07-29
**Branch reviewed:** `DEV_KC` (working tree, including uncommitted changes)
**Scope:** Architecture of `backend/` and `frontend/`. No code was changed.

---

## 1. Executive summary

newswitch is a **two-halves monorepo** implementing a web-stack microscope controller:
a Python/FastAPI backend built on `rekuest-next`, and a React/TypeScript frontend whose
typed API layer is **generated from the running backend**. The overall design is coherent
and unusually well-documented for an alpha, with a clear `Protocol → Manager → State`
layering on the backend and a clean generated-client boundary to the frontend.

**Verdict on the architecture: sound and worth keeping.** The layering choices (structural
protocols, state-with-locks, generated client, separated data planes) are the right ones for
a lab instrument that must run both virtually and against real hardware.

**Verdict on the current tree: broken.** The in-flight UC2 hardware work has left the
backend unable to import at all, so the backend, its test suite, and the frontend codegen
are all down. This is a small, well-understood breakage — not an architectural problem —
but nothing else can be validated until it is fixed.

| | Backend | Frontend |
|---|---|---|
| Source LOC | ~8,600 (`newswitch/`) | ~18,700 hand-written + ~6,400 shadcn `ui/` + ~5,100 generated `apps/` |
| Test LOC | ~1,580 (7 files) | ~270 (2 files) |
| Import/build state | **Fails to import** | Not buildable locally (`node_modules` absent) |
| Lint | 41 errors, **all** in in-flight UC2 files | not run (deps absent) |
| Format | 8 files unformatted, all in-flight | not run (deps absent) |

---

## 2. System topology

```
┌──────────────────────────── frontend (Vite/React 19) ────────────────────────────┐
│  src/apps/default/**  ← GENERATED from the backend schemas (committed on purpose) │
│  src/lib/rekuest/**   ← hand-written client: transport, state, task, lock stores  │
│  src/components/**    ← microscope panels + react-three-fiber "stage" 3D viewer   │
└───────┬────────────────────┬───────────────────────┬─────────────────────┬────────┘
        │ control plane      │ video plane           │ bulk data plane     │ codegen
        │ WS  /ws            │ WS  /stream/{codec}/  │ HTTP /cache/{id}/** │ HTTP /schemas/*
        │ (rekuest agent:    │      {slot}           │ (Zarr v3 chunks)    │ (build time only)
        │  actions, states,  │ (H.264 / Zstd)        │ HTTP /files/**      │
        │  locks, tasks)     │                       │                     │
┌───────┴────────────────────┴───────────────────────┴─────────────────────┴────────┐
│                       backend (FastAPI + rekuest-next agent)                       │
│  app.py            wiring: provide_managers() @startup, @register functions        │
│  protocols/        Protocol interfaces + @state dataclasses (the contract)         │
│  managers/         implementations: virtual/ | uc2/ | io/ | cache/                 │
│  routines/         composite operations (MDA, region scan, calibration)            │
│  broadcasters/     FrameBroadcaster + shared H264/Zstd encoders                    │
│  uc2_devices/      SDK-only camera driver layer (+ native C++ ring buffer, WIP)    │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### Four distinct data planes — a genuine strength

The design deliberately does **not** push everything through one channel:

1. **Control plane** — `rekuest-next` over `/ws`: action invocation, task lifecycle,
   state snapshots + JSON-patch deltas, lock acquisition.
2. **Video plane** — `/stream/h264/{slot}` and `/stream/zstd/{slot}`: per-detector live
   view. Encoders are *shared* between clients with identical configs
   (`FrameBroadcaster._encoders` keyed by `(slot, config)`), so N viewers cost one encode.
3. **Bulk data plane** — acquired frames are written to a local **Zarr v3** store and served
   as raw chunks over `/cache/{store_id}/{key}`, consumed directly by `zarrita` in the
   browser. Large image data never travels through the control socket.
4. **File plane** — `/files/**` for exported PNG/TIFF artefacts.

Separating these is the single best structural decision in the codebase.

---

## 3. Backend architecture

### 3.1 Layering

```
protocols/  ── Protocol (structural interface) + @state dataclass, paired per subsystem
     ▲            e.g. stage.py → StageManager (Protocol) + StageState (@state)
     │
managers/  ── concrete implementations, selected at startup
     │            virtual/  VirtualStage, VirtualLED, VirtualDetector, VirtualObjective, VirtualFilterBank
     │            uc2/      UC2Serial, UC2Stage, Uc2Detector, (galvo, filter bank — unwired)
     │            io/       LocalFileIOManager      cache/  LocalCacheManager
     │            + cross-cutting: LightPath, Metadata, Acquisition, Expanse, Calibration, PythonHook
     ▲
app.py     ── provide_managers() constructs everything and returns a 26-tuple for DI
```

`provide_managers()` is the composition root. `@startup` returns a tuple whose **type
annotation** is the DI registration — rekuest matches each returned object to the
declared protocol/state type and injects it into `@register`ed functions by parameter type.

**Assessment.** The protocol/manager split is the right abstraction and it demonstrably
works: the same registered functions drive the virtual microscope and (by design) real UC2
hardware, selected by one flag (`ImswitchConfig.use_virtual_microscope`). Using structural
`Protocol` rather than inheritance keeps drivers free of framework coupling.

**Concerns.**

- **The composition root is doing too much.** `provide_managers()` is ~150 lines returning
  a 26-element tuple, with the virtual/hardware branch interleaved into the middle of state
  construction. Adding a subsystem means editing the return type, the tuple, and the body in
  three places that must stay positionally aligned. This should be split into small
  builder functions (`build_states()`, `build_device_managers(config, states)`,
  `build_domain_managers(...)`), or the tuple replaced by a container object.
- **Hardware selection is inconsistent.** `use_virtual_microscope=False` swaps only serial,
  stage and detector. Illumination, objective and filter bank stay virtual unconditionally,
  even though `managers/uc2/filter_bank_manager.py` (212 LOC) and
  `managers/uc2/galvo_scanner.py` (122 LOC) exist. There is no per-subsystem configuration.
- **Config is a stub.** `ImswitchConfig` has 5 fields, and real values are hardcoded at the
  call sites: `port="/dev/ttyUSB0"`, `baudrate=115200`, `base_path="/tmp/newswitch/images"`,
  `settings_path="uc2DevSettings.json"`. `ImswitchConfig` is the intended home for these
  (`test.py` already mutates `use_virtual_microscope` on it), and the README states the
  backend deliberately reads no `.env` — so the config object needs to grow rather than the
  literals staying scattered.

### 3.2 State and locking

States are plain dataclasses decorated `@state(required_locks=[...])`; managers are
decorated `@context(locks=[...])`. Mutation of shared state requires holding the named lock,
and the lock vocabulary (`stage_position`, `camera_parameters`, `objective`, `illumination`,
`filter_bank`, `io`, `expanse_state`, `cache`, `hook_registry`) is exported to the frontend
via `/schemas/locks` and mirrored into `src/apps/default/hooks/locks/**`.

This is the strongest idea in the system: **the concurrency model is part of the published
API**, so the UI can grey out a control because the backend lock that guards it is held —
by another browser tab, by a running MDA, or by a script. Optimistic updates are declared
the same way (`OptimisticInput` on `move_stage` → generated `OptimisticStageState` in
`moveStage.ts`), so the UI's optimistic behaviour is backend-authored rather than
reimplemented client-side.

Caveat: 12 `@state` classes exist but only 11 are wired. `protocols/z_range.py` +
`managers/virtual/virtual_z_range.py` are referenced from nowhere (verified by grep) — dead
on arrival.

### 3.3 The `Kube` / `KubeState` duplication

`protocols/core.py` (569 LOC) defines **nine** `*Kube` classes (Objective, ObjectiveTurret,
Detector, Illumination, Dichroic, Stage, Filter, FilterBank, Generic) and **nine** parallel
`*KubeState` classes with near-identical fields — the difference being that `*KubeState`
carries live values (gain, exposure, intensity, wavelength) while `*Kube` carries only
identity + affine matrix. `MetadataManager` converts between them.

This duplication is load-bearing and it **propagates into the frontend**: there are two
near-identical renderer trees, `components/stage/planes/kubes/**` (renders `KubeState`, for
the light path recorded in an acquired frame) and `components/stage/planes/lightpath/kubes/**`
(renders `Kube`, for the live/possible light path). Both are live — the file pairs differ by
6–32 lines each. One backend modelling decision is costing two parallel 3D renderer
hierarchies plus two `LightPathEdges` implementations plus two panel sets.

**Recommendation:** unify on one kube type with an optional live-state payload
(`Kube` + `state: KubeLiveState | None`), and collapse the frontend renderers to one tree.
This is the single highest-leverage refactor available, and it should be done *before* more
kube types are added, not after.

Related: `LightPath.transformation_hash()` (`core.py:254`) is dead (no callers) and buggy —
it filters `self.kubes` (which holds `Kube` values) with `isinstance(kube, FilterBankKubeState)`,
so the filter branch can never match, and it interpolates the whole `objective` object into
the hash string rather than its slot id.

### 3.4 Acquisition path

`capture_image` → `AcquistionManager.acquire()` → for each active detector:
`DetectorManager.capture_image()` → `LightPathManager.get_light_path_for_detector()` →
`MetadataManager.get_metadata_for_light_path()` → `CacheManager.save_frame()` (Zarr v3) →
`Frame` appended to `ExpanseState.current_frames` and returned.

This is a clean pipeline with good separation. Two notes:

- `LocalCacheManager` hardcodes `default_chunks=(1, 256, 256)` and **asserts** the array is
  exactly 3-D; `AcquistionManager` satisfies this by reshaping every 2-D camera frame to
  `(1, H, W)`. Multi-channel or true-volumetric detectors will not fit this contract without
  a change to both.
- `delete_on_restart=True` wipes `/tmp/newswitch/cache` on every boot. Correct for a cache;
  worth being explicit that the expanse is not durable across restarts.

### 3.5 Streaming

`FrameBroadcaster` is well-designed: shared encoders keyed by `(detector_slot, config)`,
refcounted subscriptions, `stop_all_encoders()` on shutdown to reap ffmpeg subprocesses.
The `@shutdown` hook (`release_managers`) explicitly documents *why* it exists.

Issues:

- **`release_managers` takes `detector: DetectorManager` and never uses it.** `Uc2DetectorManager`
  has a `shutdown()` that stops streaming and releases every SDK camera handle — it is never
  called. On the hardware path, camera handles leak on every restart.
- **`get_latest_frame()` / `_latest_frame` is vestigial** — `broadcast_sync` never assigns
  `_latest_frame`, so the accessor always returns `None`.
- **The live loop is a `while True` with no backpressure.** `Uc2DetectorManager.acquire_live()`
  sleeps only when `is_acquiring` is false; when it is true but no detector is active, the
  inner `for` body never runs and the outer loop spins at 100% CPU with no sleep.
  `VirtualDetectorManager` handles this case (`koil.sleep(0.1)`); the UC2 version does not.
  Neither loop paces itself against exposure time — the virtual one even has a dangling
  comment ("Use exposure time from first active detector for frame interval") with no code.

### 3.6 Route-level dependency injection

`routes/http/files.py`, `routes/http/cache.py` and `routes/ws/liveview.py` each reach managers
via `request.app.state.agent.get_context_for_type(X)`, with a hand-written
`get_X_from_request` helper duplicated per module. It works and is documented, but it is a
service-locator escape hatch: FastAPI routes bypass the typed DI that `@register`ed functions
enjoy. One shared `Depends` factory (`context_dependency(CacheManager)`) would remove the
triplication.

**Security note on `/files/{file_path:path}`:** unlike the cache route — which does a proper
`is_relative_to(store_dir)` traversal check — the files route passes the client-supplied path
straight to `io_manager.file_exists()` and then to `FileResponse` with no confinement to
`LocalFileConfig.base_path`. Combined with `allow_origins=["*"]` CORS, this is an arbitrary-file-read
surface. Acceptable on an isolated lab network; not acceptable if the instrument is ever
reachable beyond it. Worth fixing regardless, since the correct pattern already exists 40
lines away in `cache.py`.

### 3.7 `uc2_devices/` — the hardware driver layer

The intent is well thought through and thoroughly documented (an 18 KB README with mermaid
diagrams, a documented state machine for the native ring buffer, an on-disk RAW format spec):

- SDK-only layer *below* the managers, so `Uc2DetectorManager` composes a driver rather than
  inheriting from one.
- **ABC rather than Protocol here — deliberately and correctly**, because drivers share real
  logic (`apply_settings`, `compute_variance`, `save_stack`, context-manager lifecycle).
  The README explains this choice explicitly. Good.
- The stated boundary — *control in Python, frame data never through Python* — is the right
  call for a Pi-class device at ~1 GB/s, with `grab_frame()` as an explicitly-labelled
  snapshot-only path and the native ring buffer owning the sustained stream.

**However, this layer is currently mid-demolition** and is the source of every blocking
problem in §5.1. The entire C++ core, the pybind11 bindings, the ring buffer, the HIK driver
and the tests are deleted in the working tree (~4,000 lines), the root `CMakeLists.txt` has
its pybind targets commented out, and the remaining Python still imports the deleted pieces.
The documentation now describes a system that no longer exists in the tree.

---

## 4. Frontend architecture

### 4.1 The generated-client boundary

`plugins/generate-app.ts` (1,648 LOC) runs in Vite's `buildStart`, fetches
`/schemas/implementations`, `/schemas/states`, `/schemas/locks` from a *running* backend, and
emits `src/apps/default/**`: one module per action with a Zod schema, TS types, an
`ActionDefinition` (including `lockKeys` and optimistic accessors) and a `use<Action>()` hook;
plus one module per state and lock. `blok.json` and the generated tree are committed on
purpose.

This is a strong contract: 25 backend registrations map 1:1 to 25 generated action modules,
and validation, lock metadata and optimistic behaviour all derive from the same source of
truth. Docstrings become JSDoc.

The known hazard is documented honestly in the README and CI: **the generator fails silently**
(fetch errors are warnings; it falls back to the committed output). The mitigations are real
— `just dev` sequences backend-then-frontend, `just drift-check` and the `codegen-drift` CI
job boot the backend, regenerate, and fail on any diff, and compose's `depends_on` +
healthcheck removes the race entirely. The compensating controls are the right ones; the
residual risk is that a developer running `yarn dev` alone gets no hard failure.

Also worth noting: `codegen-drift` is the only CI job that catches this, and it currently
cannot pass, because the backend cannot boot (§5.1).

### 4.2 The `lib/rekuest` client

~6,000 LOC of hand-written client, layered:

- `transport/` — `TransportProvider` + `subscription-manager`: one WebSocket per app, INIT
  handshake declaring the action/state/lock keys this client cares about, reconnect with
  exponential backoff, ping keepalive.
- `state/` — global state store with snapshot + **JSON-patch delta** application
  (`fast-json-patch`), Zod validation of snapshots, and a `selectPath` selector family.
  `materialization.ts` reconstructs typed values from the wire format.
- `task/` — task store + `useAction`, optimistic application/rollback.
- `locks/` — lock store and `useLock`.
- `createScopedProvider` / `createScopedStore` — per-route scoping, so `/` and `/replay`
  hold independent store instances.

The union wire format is handled by a well-explained `createIndexedUnion` Zod codec
(positional `{__use, __value}` envelopes, idempotent decode so patched documents re-validate).
This is the only part of the frontend with real unit tests (`indexed-union.test.ts`,
`store.test.ts`).

**Concern: `BundleProvider.tsx` is 1,377 lines** and is the orchestration hub for every
store, subscription and patch stream. It is the highest-risk file in the frontend — the most
complex, the most central, and effectively untested. If any part of the client deserves
extraction and unit tests, it is this one.

`src/store/createScopedStore.ts` and `src/hooks/useLock.tsx` are thin re-export shims for
`lib/rekuest` equivalents — harmless, but two import paths for one thing.

### 4.3 Components

Two tiers: `components/ui/**` (~6,400 LOC of vendored shadcn/Radix primitives — treat as
dependency, not code to maintain) and the application tier:

- `components/microscope/**` — control panels (stage, camera, illumination, filter bank,
  objective, MDA). **`MultidimensionalAcquisitionControl.tsx` (1,110) and
  `MultidimensionalAcquisitionDialog.tsx` (995) are outliers** — 2,100 lines for one feature,
  with visible overlap between the two. Prime extraction candidates.
- `components/stage/**` — the react-three-fiber viewer: planes, volumes, kube renderers,
  Zarr-backed chunk loading with an LRU cache and colormaps, live textures fed from the
  H.264/Zstd sockets, interaction controllers. Architecturally the most interesting part, and
  where the `Kube`/`KubeState` duplication (§3.3) is paid for.
- `components/lightpathstate/**` — a `@xyflow/react` + `dagre` node-graph view of the light path.

Local UI state lives in `src/store/**` (zustand + immer, scoped per route) and is properly
kept separate from backend-synced state in `lib/rekuest/state`.

### 4.4 Live-view wiring is inconsistent

Three URL conventions coexist and only one of them is correct:

| Consumer | URL it builds | Backend route | Status |
|---|---|---|---|
| `useH264LiveTexture` | `BACKEND_API + "/stream/h264/" + slot` | `/stream/h264/{slot}` | path correct, but built from the **http** base and handed to `new WebSocket()` |
| `useZstdLiveTexture` | `BACKEND_API + "/stream/zstd/" + slot` | `/stream/zstd/{slot}` | same |
| `StreamingView` (default prop) | `VITE_WEBSOCKET_URL + "/video"` → `ws://…/ws/video` | **no such route** | dead |

`LiveView.tsx` renders `<StreamingView />` with no `url` prop, so the microscope panel's live
view points at an endpoint that does not exist — a leftover from an earlier single-stream
design (`/video`) that survived the move to per-slot, per-codec routes. The `constants.tsx`
pair uses `BACKEND_API` (http) where `BACKEND_WS` (ws) is the declared convention; modern
browsers do accept `http(s)` in the `WebSocket` constructor, so this may work today, but it
contradicts the project's own env-var contract and will break behind a proxy that maps the
two differently.

---

## 5. Findings

### 5.1 Blocking — the backend does not run

1. **`newswitch/uc2_devices/__init__.py` is deleted, but `uc2_detector_manager.py` still
   imports from it, and `app.py` imports that manager unconditionally at module scope.**
   Every entry point dies at import:

   ```
   app.py:29  → managers/uc2/uc2_detector_manager.py:38
              → from newswitch.uc2_devices import CameraInfo, Uc2Camera, Uc2DevSettings
   FileNotFoundError: .../newswitch/uc2_devices/__init__.py
   ```

   Consequence: `uvicorn main:app` fails, `uv run pytest` fails at conftest collection
   (**the whole 1,583-line backend suite is unrunnable**), `just dev-backend` fails, and the
   frontend codegen therefore silently falls back to committed hooks.
   (Aggravating detail: the editable install is a scikit-build-core loader whose file map
   still points at the deleted `__init__.py`, so a plain re-sync is also needed after
   restoring it.)

2. **No concrete camera driver exists.** `hik_camera.py` is deleted, so `Uc2Camera` — an ABC
   with abstract methods — is the only "driver". `Uc2DetectorManager`'s default
   `drivers=(Uc2Camera,)` calls `Uc2Camera.enumerate()`, an abstract classmethod with an
   empty body returning `None`, and then iterates it. The hardware path cannot work even
   after fixing (1).

3. **The native layer is gone but still referenced.** ~4,000 lines of C++ (ring buffer,
   MVS/HIK capture engine, pybind11 bindings, C++ and Python tests) are deleted;
   `backend/CMakeLists.txt` has all pybind targets commented out; `uc2_camera.py` still tries
   to load `_ringbuffer` (it degrades gracefully); `uc2_devices/README.md` still documents
   the whole thing as present. The build backend is still `scikit-build-core`, so every wheel
   build runs CMake for what is now an empty project.

### 5.2 Structural

4. **`Kube` / `KubeState` duplication** (§3.3) — 18 near-identical backend classes driving two
   parallel frontend renderer hierarchies. Highest-leverage refactor.
5. **`provide_managers()` as a 26-tuple composition root** (§3.1) — three places must stay
   positionally aligned per subsystem added.
6. **Partial hardware abstraction** (§3.1) — only 3 of 6 device subsystems switch on
   `use_virtual_microscope`; two written UC2 managers are unreachable.
7. **`BundleProvider.tsx` at 1,377 LOC** (§4.2) — the frontend's most central and least
   tested module.
8. **`Uc2DetectorManager.shutdown()` is never called** (§3.5) — `release_managers` receives
   the detector and ignores it; SDK handles leak on the hardware path.
9. **Unbounded live-acquisition loops** (§3.5) — `Uc2DetectorManager.acquire_live()` busy-spins
   when acquiring with no active detector; neither loop paces against exposure time.
10. **Path traversal on `/files/{file_path:path}`** (§3.6) — no confinement to `base_path`,
    while the neighbouring cache route does it correctly.
11. **Live-view URLs inconsistent; `StreamingView` points at a dead route** (§4.4).

### 5.3 Hygiene / smaller

12. **Silent settings loss.** `app.py` passes `settings_path="uc2DevSettings.json"` (relative
    to CWD) while the file lives at `newswitch/uc2_devices/uc2DevSettings.json`;
    `Uc2DevSettings.load()` returns empty defaults for a missing file, so a misconfigured
    path is indistinguishable from "no cameras configured". Separately,
    `uc2DevSettings.json` and the README both document `recording_format`, but
    `Uc2CameraSettings` has no such field and `from_dict` drops it silently.
13. **`enumerate()` contract mismatch (uncommitted).** The working tree changes the ABC's
    return type to `list[Uc2Camera]`, but `Uc2DetectorManager` still treats the items as
    `CameraInfo` (`driver(info)`, `info.serial`, `info.model`).
14. **Dead code:** `protocols/z_range.py` + `managers/virtual/virtual_z_range.py` (unwired);
    `LightPath.transformation_hash()` (no callers, and buggy); `FrameBroadcaster.get_latest_frame()`
    (always `None`); `plugins/gonio_meter.py` (docstring only).
15. **Lint/format regression, fully localised.** 41 ruff errors and 8 unformatted files — all
    in the in-flight UC2 files (27 errors in `uc2_camera.py` alone). The rest of the backend
    is clean, so this is new debt, not accumulated debt. Also, `[tool.ruff] extend-select`
    is in the deprecated top-level position and ruff warns on every run; it belongs under
    `[tool.ruff.lint]`.
16. **`pyproject.toml` metadata commented out** (uncommitted): `readme`, `homepage`.
    Presumably a workaround for a build error; it makes published wheels metadata-poor.
17. **Test asymmetry.** Backend ~1,580 test LOC across 7 files vs frontend ~270 LOC across 2.
    Nothing covers `BundleProvider`, the transport layer, the stage/3D components, or the
    codegen plugin — the codegen plugin's only guard is the CI drift job.
18. **CORS `allow_origins=["*"]` with `allow_credentials=True`** — invalid per spec (browsers
    reject the combination) and permissive by intent. Fine for a lab box; make it a config
    knob before any wider deployment.
19. **Empty scaffolding:** `CLAUDE.md`, `DOC/SRS.md`, `DOC/TODOS.md`, `DOC/CHANGELOG_KC.md`
    are 0 bytes. `newswitch/routes/__init__.py` and `newswitch/managers/__init__.py` are
    docstring-only.

---

## 6. Tooling, build and CI

**Good:**
- `just` as the single task entry point, with recipes that encode the ordering constraint
  (`dev` waits on the backend before starting vite) and warn loudly when it is violated.
- CI runs a 3-OS × 2-Python matrix for the backend, plus coverage, ruff check *and* ruff
  format on one platform.
- The frontend job comments record real history: `types` used to point at a solution tsconfig
  with `files: []` and checked **zero** files, hiding 165 type errors and 90 lint problems.
  Both gates are now blocking. That is exactly the right response.
- `codegen-drift` boots the real backend and diffs the regenerated output — the correct
  compensating control for a silently-failing generator, and only possible because both
  halves live at one commit.
- `ci-ok` aggregate job so path-filtered skips don't produce a vacuously-green required check.
- Dockerfile runs as uid 1000 with a documented reason (bind-mounted `agent_data.db` would
  otherwise be root-owned); compose healthcheck probes the exact endpoint codegen needs.
- lefthook: commitlint on `commit-msg`, ruff/prettier on `pre-commit`, with `src/apps/**`
  excluded because the generator owns its formatting.
- Unified semantic-release bumping `backend/pyproject.toml` and `frontend/package.json` to
  one version.

**Gaps:**
- **No CI job builds the native/C++ side**, and `scikit-build-core` is still the build backend
  for a CMake project that now compiles nothing. `just build` runs `uv build`, which will
  invoke CMake; this is untested in CI.
- **`agent_data.db` exists at both repo root and `backend/`** as untracked runtime artefacts
  (`*.db` is gitignored, correctly). The root copy suggests the backend has been started from
  the wrong CWD at some point — the same class of CWD-relative-path fragility as finding (12).
- CI never exercises the Docker path.

---

## 7. Recommendations, in order

**Immediate — restore a working tree (hours):**
1. Restore `newswitch/uc2_devices/__init__.py` (and re-sync the editable install), or make
   `app.py`'s `Uc2DetectorManager` import lazy so the virtual path never depends on hardware
   modules. Prefer **both**: a hardware driver should not be able to break virtual mode at
   import time.
2. Get `uv run pytest` green again and confirm `just drift-check` passes — nothing else can
   be verified until these two do.
3. Run `ruff format` + `ruff check --fix` over the UC2 files and clear the remaining 38 by
   hand; move `extend-select` under `[tool.ruff.lint]`.
4. Decide the fate of the native layer and make the tree say so: either restore it, or drop
   `scikit-build-core` back to a pure-Python backend and move `uc2_devices/README.md`'s
   native sections to a design doc marked "planned". Documentation describing deleted code is
   worse than no documentation.

**Short term — close the correctness gaps (days):**
5. Call `detector.shutdown()` from `release_managers` (§5.2-8).
6. Add the missing sleep/pacing to both `acquire_live()` loops (§5.2-9).
7. Confine `/files/**` to `base_path` using the same check `cache.py` already implements (§5.2-10).
8. Point `StreamingView` at a real route and unify the three live-view URL conventions on
   `BACKEND_WS` (§5.2-11).
9. Move `port`, `baudrate`, `base_path`, `settings_path` into `ImswitchConfig`; resolve
   `uc2DevSettings.json` relative to the package, and make a missing settings file at an
   explicitly-configured path an error rather than empty defaults (§5.3-12).
10. Restore or write one concrete camera driver so the hardware path is exercisable at all —
    a `MockCamera` (the README already contains a complete one) would let the whole UC2
    branch be unit-tested with no SDK present.

**Medium term — pay down the structural debt (weeks):**
11. Unify `Kube`/`KubeState` and collapse the two frontend renderer trees (§3.3). Do this
    before adding kube types.
12. Break up `provide_managers()` and replace the 26-tuple with a container (§3.1).
13. Extract `BundleProvider.tsx` into testable units and add transport/patch-application
    tests (§4.2).
14. Split the ~2,100-line MDA control/dialog pair (§4.3).
15. Make hardware selection per-subsystem and wire up (or delete) the unreachable UC2
    filter-bank and galvo managers (§5.2-6).
16. Delete the dead code in §5.3-14 rather than leaving it to be rediscovered.

---

## 8. Closing assessment

The bones are good. The protocol/manager/state layering, the four separated data planes, the
lock vocabulary as published API, and the generate-the-client-from-the-backend contract are
all decisions that will still look right in a year — and the tooling around them (the
sequencing in `just dev`, the drift-check job, the honest comments about gates that used to
be dead) shows a team that has already been bitten by the failure modes and built controls
for them.

The two things holding it back are both fixable and both localised: an in-flight hardware
refactor that has left the tree in a non-importing state, and one modelling decision
(`Kube`/`KubeState`) whose duplication has now replicated itself across the frontend. Fix the
first this week; plan the second before the kube taxonomy grows further.

*No code was modified in the course of this review.*
