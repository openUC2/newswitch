# Status — virtual scene extraction

Branch: `REV_MANAGER_KC` (based on `main`). Date: 2026-08-16.
**Everything below is uncommitted working tree.** Nothing has been committed or pushed.

Net diff: **+224 / −1057** across 10 tracked files, plus 1 new file.

## What was done

### 1. Architecture Q&A → `.claude/Q&A.md`

Nine questions on states / managers / protocols answered in German, each below its
question. **Caveat:** written while a *different* branch was checked out, one that
had `managers/uc2/uc2_detector_manager.py` and `newswitch/uc2_devices/`. Neither
exists on `REV_MANAGER_KC`. Answers 2, 3, 4, 5 and 9 contrast the virtual manager
with that hardware manager, so those comparisons do not apply to this branch.
*Open: offer stands to rewrite it against the actual tree.*

### 2. Refactor plan → `.claude/REFACTOR_VIRTUAL_SETUP.md`

The living design doc. Kept in sync with the implementation, including the
`FrameSource` decision made after the first implementation pass.

### 3. Implementation — complete

Goal: get `stage_state`, `objective_state`, `illumination_state` and
`filter_bank_state` out of the detector managers.

| File | Change |
|---|---|
| `managers/virtual/virtual_setup.py` | **new** — `VirtualSetup` (the simulated optical scene) + `SceneConfig` |
| `protocols/detector.py` | **new** `FrameSource` protocol — the pixel-source seam |
| `managers/virtual/virtual_detector.py` | 722 → 337 lines; no scene states; takes `frame_source: FrameSource` |
| `managers/uc2/detector_manager.py` | stale duplicate of `virtual_detector.py` replaced by a `Uc2DetectorManager` protocol skeleton |
| `app.py` | `virtual_setup` built after the states, before the detector; **not** in the `provide_managers` return tuple |
| `managers/virtual/__init__.py`, `newswitch/__init__.py` | export `VirtualSetup`, `SceneConfig` |
| `tests/` (4 files) | 10 construction sites updated |

**Key design decisions**

- **Render arrow is forced: `detector → frame source`.** `capture_image(slot)` is a
  protocol method that `AcquistionManager.acquire()` calls and expects an array
  from, so the manager must reach *something* that makes pixels. It now reaches
  an abstraction (`FrameSource`) rather than a concrete class.
- **Ownership arrow is free**, so plain constructor injection: states →
  `VirtualSetup` → `VirtualDetectorManager`. Building the setup last would have
  forced a setter or two-phase init.
- **`VirtualSetup` deliberately does not take `CameraState`.** The manager owns
  that state (it writes `state.detectors`); a second handle would mean two owners
  and would drag slot lookup into the scene. A scene models light, not slots.
- **`Uc2DetectorManager` takes no scene states** — `(camera_state, broadcaster)`
  only. That is the payoff of the refactor made concrete. Its three pure queries
  delegate to `CameraState`; the five hardware-facing methods raise
  `NotImplementedError` (no driver layer on this branch). It is **not** wired into
  `app.py`, because `run_detector_loop` calls `acquire_live()` at startup and would
  throw immediately.

**Bugs fixed in passing**

- **Frame-size mismatch:** `_initialize_detectors` hardcoded `width=1024, height=1024`
  while rendering used `config.width/height` (512) — the published state disagreed
  with the actual frames. Detectors are now built from `config.width/height` and
  render at `detector.width/height`.
- `test_affine_matrix.py:119` referenced `detector.objective_state`, which no longer
  exists. It sits inside a `@pytest.mark.skip`ped test, so neither pytest nor ruff
  caught it. Repointed at `detector.frame_source.objective_state`.

## Verification (all green)

- `uv run pytest -k "not integration"` → **31 passed, 1 skipped** (pre-existing skip)
- `ruff check .` → clean; `ruff format --check .` → 81 files formatted
- Backend boots; `/schemas/states` returns 11 states; no tracebacks in the log
- `isinstance(setup, FrameSource)`, `isinstance(det, DetectorManager)`,
  `isinstance(uc2, DetectorManager)` → all `True` (first real use of
  `runtime_checkable` in this codebase)
- Decoupling proven: a 5-line stub `render()` returning constant pixels drives the
  real manager. `virtual_detector.py` greps clean for `VirtualSetup|virtual_setup|
  stage_state|objective_state|illumination_state|filter_bank_state`.
- Non-square check: `DetectorConfig(width=320, height=200)` → detector state 320×200,
  frame `(200, 320)`.

## Open / deferred

1. **Composition root ("rig")** — a class that *owns* the states, the scene and all
   five virtual managers, so `provide_managers` (~150 lines) delegates instead of
   assembling by hand. This is the shape where "the setup depends on the detectors"
   is literally true. Deferred by decision; composes cleanly on top of what exists.
2. **`render()` is slot-agnostic** — all detectors see the same light, differing only
   by exposure, gain and sensor size. Per-detector optical paths (different emission
   filter per port) would need a light-path argument; natural join with `LightPathManager`.
3. **Carried-forward TODOs:**
   - `Detector.is_acquiring` duplicates `CameraState.is_acquiring` and is unused
   - `VirtualSetup.invalidate_illumination_cache` is never called (cache-key compare covers it)
   - `VirtualDetectorManager._get_detector` / `_get_active_detectors` duplicate
     `CameraState.get_detector_for_slot` / `get_active_detectors`; `Uc2DetectorManager`
     already delegates — align the virtual one the same way
   - no `isinstance` assertion in `provide_managers` yet (would make the protocols
     enforce themselves at startup)
4. **`Q&A.md` branch mismatch** (see above).
5. **Commit** — decide message/granularity; nothing staged yet.

## Key paths

```
.claude/REFACTOR_VIRTUAL_SETUP.md          design doc (kept in sync)
.claude/Q&A.md                             architecture Q&A (stale re: this branch)
backend/newswitch/managers/virtual/virtual_setup.py     VirtualSetup + SceneConfig
backend/newswitch/managers/virtual/virtual_detector.py  detector bookkeeping only
backend/newswitch/managers/uc2/detector_manager.py      Uc2DetectorManager skeleton
backend/newswitch/protocols/detector.py                 FrameSource + DetectorManager + CameraState
backend/newswitch/app.py:184-205                        provide_managers wiring
```

Commands: `just test-backend`, `just lint`, `just fmt-check`, `just dev-backend` (port 8099).
