# Refactor plan: extract virtual scene generation into `VirtualSetup`

Branch: `REV_MANAGER_KC` (based on `main`). Status: **planned, not implemented.**
No code has been changed yet.

## Context

`VirtualDetectorManager` currently does two unrelated jobs: it manages detectors
(slots, exposure, gain, activation) *and* it simulates the whole optical scene.
The simulation half is why it has to hold `stage_state`, `objective_state`,
`illumination_state` and `filter_bank_state` — none of which a detector has any
business knowing. A real hardware detector manager needs none of them.

Goal: move scene/sample generation into its own class so the detector managers
depend only on `CameraState` + `FrameBroadcaster`.

## Scope decisions

| # | Item | Decision |
|---|---|---|
| 1 | Stale duplicate `managers/uc2/detector_manager.py` | **In scope** — replace its content with a protocol-conforming `Uc2DetectorManager` skeleton |
| 2 | `width`/`height` mismatch (1024 vs 512) | **In scope** — detectors are built from `config.width/height` |
| 3 | Composition root ("rig") | **Deferred** — see follow-ups |
| 4 | Assorted cleanups | **Deferred** — tracked as TODOs |

## Current state on this branch (verified)

- `app.py` always builds `VirtualDetectorManager` (`app.py:187-194`); there is no
  `Uc2DetectorManager` and no `@shutdown` hook on this branch.
- `newswitch/managers/uc2/detector_manager.py` is **not** a UC2 manager. It is a
  stale, slightly older duplicate of `virtual_detector.py` — it defines its own
  `class VirtualDetectorManager` + `DetectorConfig` and is **imported by nothing**.
- `newswitch/uc2_devices/` no longer exists (only `__pycache__`), so there is no
  camera driver layer to call into.
- ~10 `VirtualDetectorManager(...)` construction sites across 4 test files.

## Target design

New file: **`newswitch/managers/virtual/virtual_setup.py`**, class `VirtualSetup`.

**It belongs in `managers/virtual/`** — it is a virtual-only implementation and
that package already holds the virtual implementations plus their config classes.
One caveat to record: `VirtualSetup` is *not* a Manager in this codebase's sense —
no `@context`, not injected, not returned from `provide_managers`. It is a plain
collaborator of `VirtualDetectorManager`.

Public seam:

```python
class VirtualSetup:
    def __init__(self, stage_state, objective_state, illumination_state,
                 filter_bank_state, config: SceneConfig | None = None) -> None: ...

    def render(self, width: int, height: int,
               exposure_time: float, gain: float) -> np.ndarray: ...
```

### The detector depends on an abstraction, not on `VirtualSetup`

`VirtualDetectorManager` must be able to obtain pixels (`capture_image` is a
protocol method that has to return an array), but it must not know *what* is
producing them. A minimal structural protocol in `protocols/detector.py` provides
that seam:

```python
@runtime_checkable
class FrameSource(Protocol):
    def render(self, width: int, height: int,
               exposure_time: float, gain: float) -> np.ndarray: ...
```

`VirtualDetectorManager` takes `frame_source: FrameSource`. `VirtualSetup`
satisfies it structurally - no inheritance, and `virtual_detector.py` never
imports `virtual_setup` at all. Verified: any object with a `render` method drives
the manager (a stub returning constant pixels works), and
`isinstance(setup, FrameSource)` is `True`.

Why this matters beyond tidiness: every other manager constructor in the codebase
depends on a `@state` class, a `@context` protocol, or a plain config dataclass.
A concrete `setup: VirtualSetup` parameter would have been the only exception.
It also mirrors the hardware case - there the frame source is a camera driver
handle, exactly as the deleted UC2 manager used `Uc2Camera.grab_frame()`.

Known limitation: `render()` is slot-agnostic, so all detectors currently see the
same light and differ only by exposure/gain and sensor size. Per-detector optical
paths (a different emission filter per port) would need a light-path argument,
which is where `LightPathManager` would come in.

### Moves out of `virtual_detector.py` into `virtual_setup.py`

- `SampleType`, `SampleFrameCacheKey`, `AstigmatismFrameCacheKey`,
  `IlluminationCacheKey`, `FrameCache`
- new `SceneConfig` = the simulation half of today's `DetectorConfig`:
  `sample_type`, `sample_width`, `sample_height`, `sample_seed`,
  `astig_phi_deg`, `astig_s0`, `astig_slope`, `astig_amplitude`,
  `astig_background`, `read_noise`, `poisson_noise`
- the four states, `_rng`, `_sample_image`, `_cache`
- `_generate_frame` → `render(...)`; `_generate_sample_frame` → `_render_sample`;
  `_generate_astigmatism_frame` → `_render_astigmatism`
- `_get_illumination_cache_key`, `_get_filter_transmission`,
  `_get_cached_illumination_value`, `calculate_illumination_value`,
  `clear_cache`, `invalidate_illumination_cache`
- all `managers/helpers/frame.py` imports move with them

### Stays in `virtual_detector.py`

- `DetectorConfig`, trimmed to detector-only fields: `width`, `height`,
  `min_exposure`, `max_exposure`, `default_exposure`, `min_gain`, `max_gain`,
  `default_gain`
- ctor becomes `(camera_state, broadcaster, frame_source: FrameSource, config=None)`
- `_initialize_detectors`, `_clamp`, `_get_detector`, `_get_active_detector`,
  `_get_active_detectors`, `activate/deactivate/update_detector`,
  `get_detector_state`, `list_*`, `capture_image`, `_compose_rgb_frame`,
  `acquire_live`, `shutdown`, `background`

### Decision 2 — frame size comes from `DetectorConfig`

`_initialize_detectors` currently hardcodes `width=1024, height=1024` into every
`Detector` while rendering happens at `config.width/height` (default 512), so the
state published to the frontend disagrees with the actual frames. Fix:

- `_initialize_detectors` builds all three detectors with
  `width=self.config.width, height=self.config.height`.
- the three former `self._generate_frame(detector)` call sites — `capture_image`,
  `_compose_rgb_frame`, `acquire_live` — become
  `self.setup.render(detector.width, detector.height, detector.current_exposure_time, detector.current_gain)`.

Existing assertions stay green because they already derive from `DetectorConfig`:
256×256 in `test_virtual_detector.py:124`, 512×512 in `test_capture_image_io.py:215`.

Keep the existing resize branch in `_compose_rgb_frame` as-is: it becomes a no-op
while all slots share the config size, but still guards the case where a detector's
dimensions are changed per slot later.

### Decision 1 — `managers/uc2/detector_manager.py` becomes a protocol skeleton

Replace the stale duplicate's entire content with a `Uc2DetectorManager` that
conforms to the `DetectorManager` protocol (`protocols/detector.py:88-168`).
The point of the exercise: its constructor takes **no scene states** — that is the
payoff of this refactor made concrete.

```python
class Uc2DetectorManager:
    state: CameraState
    broadcaster: "FrameBroadcaster"

    def __init__(self, camera_state: CameraState,
                 broadcaster: "FrameBroadcaster") -> None:
        self.state = camera_state
        self.broadcaster = broadcaster

    # pure state queries -> delegate to CameraState (no duplication)
    def get_detector_state(self, slot: int) -> Optional[Detector]: ...
    def list_available_detectors(self) -> list[Detector]: ...
    def list_active_detectors(self) -> list[Detector]: ...

    # hardware-facing -> NotImplementedError until a driver layer exists
    def capture_image(self, slot: int) -> np.ndarray: ...
    def activate_detector(self, slot: int) -> Detector: ...
    def deactivate_detector(self, slot: int) -> None: ...
    def update_detector(self, slot, exposure_time=None, gain=None) -> Detector: ...
    def acquire_live(self) -> None: ...
```

- The three pure queries get real bodies delegating to
  `CameraState.get_detector_for_slot` / `.get_active_detectors`, so the lookup
  logic is not duplicated a third time.
- The five hardware-facing methods raise `NotImplementedError` with a clear
  message — `newswitch/uc2_devices/` does not exist on this branch.
- **Not wired into `app.py`.** There is no driver layer to reach, so adding an
  `else:` branch on `use_virtual_microscope` would only produce a manager that
  throws. The skeleton makes the contract explicit and gives the hardware work a
  place to land.

## Initialization order

**`VirtualSetup` is the renderer only.** The "setup owns the managers" shape is
deferred as follow-up 1.

Two arrows, and only one of them is forced:

- **Render arrow — forced, `detector → frame source`.** Pixels must be reachable from
  `detector.capture_image(slot)`, because that is what the rest of the system
  calls: `AcquistionManager.acquire()` (`managers/acquistion_manager.py:38-47`)
  and `run_detector_loop` → `detector.acquire_live()` (`app.py:285-291`), both
  through the `DetectorManager` protocol. A renderer that instead owned the
  detectors and pushed frames would leave `capture_image()` with nothing to
  return; a renderer that owned them *and* was called by them would be a cycle.
- **Ownership arrow — free.** With a renderer-only setup, plain constructor
  injection is the simplest correct choice, so the setup must exist before the
  detector:

```
states  →  VirtualSetup(states)  →  VirtualDetectorManager(camera_state, broadcaster, setup)
```

Building the setup *after* the detector would then require a setter
(`detector.set_setup(...)`) or a two-phase init — but only as a consequence of
these two choices together, not because ownership inherently has to run that way.

Placement is otherwise unconstrained: `VirtualSetup` reads the four states only at
**render time**, never in `__init__`. So even though `VirtualObjectiveManager` /
`VirtualFilterBankManager` seed their states in their own constructors,
construction order relative to those managers is irrelevant.

**Constraint to respect:** `virtual_setup` must **not** be added to the
`provide_managers` return tuple. The startup hook classifies every returned
element as either `@state` or `@context` and raises `StartupHookError` for
anything else (`rekuest_next/agents/hooks/startup.py`). It stays a local variable.

## Impact by file

| File | Change |
|---|---|
| `managers/virtual/virtual_setup.py` | **new** — `VirtualSetup` + `SceneConfig` |
| `protocols/detector.py` | **new** `FrameSource` protocol (the pixel-source seam) |
| `managers/virtual/virtual_detector.py` | remove 4 states + scene code; take `frame_source: FrameSource`; trim `DetectorConfig`; build detectors from `config.width/height`; render at `detector.width/height` |
| `managers/uc2/detector_manager.py` | **content replaced** — `Uc2DetectorManager` protocol skeleton, no scene states |
| `managers/virtual/__init__.py` | export `VirtualSetup`, `SceneConfig` |
| `newswitch/__init__.py` | mirror those exports (it re-exports `VirtualDetectorManager`/`DetectorConfig`) |
| `app.py` | build `virtual_setup` after the states; pass it to the detector; drop the 4 state args; **not** in the return tuple |
| `tests/` (4 files, ~10 sites) | build a `VirtualSetup` first; recommend one shared fixture in `tests/conftest.py` |

## Follow-ups (deferred)

1. **Composition root ("rig").** A second, different role could also be called a
   setup: a class that *owns* the states, the renderer and all five virtual
   managers, so that `provide_managers` (~150 lines of assembly, `app.py:142-282`)
   delegates instead of assembling by hand. That shape is the one where "the setup
   depends on the detectors" is literally true, and it composes cleanly on top of
   this refactor — the renderer stays as designed above and the rig simply builds
   it first. Revisit once the renderer extraction has landed, then decide whether
   it covers only the virtual devices or all of `provide_managers`.

2. **TODOs carried forward:**
   - `Detector.is_acquiring` duplicates `CameraState.is_acquiring` and is unused
   - `invalidate_illumination_cache` is never called
   - `VirtualDetectorManager._get_detector` / `_get_active_detectors` duplicate
     existing `CameraState.get_detector_for_slot` / `get_active_detectors`
     (the new `Uc2DetectorManager` already delegates instead — align the virtual
     one the same way)
   - `runtime_checkable` is on all 15 protocols but no `isinstance()` check exists
     anywhere; a startup assertion in `provide_managers` would make it earn its keep

## Verification (once implemented)

- `just test-backend` (`cd backend && uv run pytest -k "not integration"`) —
  the 4 detector test files are the ones that must stay green.
- `just lint` and `just fmt-check`.
- `just dev-backend`, then confirm `/schemas/states` answers and the live view at
  `/stream` still produces frames (the `acquire_live` path is the one that moved).
