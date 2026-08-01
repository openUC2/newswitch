# Path to a Minimum Viable Product — newswitch

**Document ID:** MVP_TASKS
**Version:** 1.0 (draft)
**Date:** 2026-07-29
**Derived from:** `DOC/SRS_V1.md` (target) and `DOC/InitReview.md` (Version 1.0, current state)
**Constraint:** the architecture of `basicRequirements.md` §Base architectural setup is preserved;
no task below changes the backend/frontend split, the routines → managers → protocols layering, the
DI model, the control-plane transport structure or the generated-client contract.

**One exemption is in force:** `DEC-001` (2026-07-29) replaces the **video plane** with
LiveKit/WebRTC/VP8, explicitly waiving the freeze for that subsystem only (`CON-ARC-002-E1`).

---

## 1. What the MVP is

**One operator, at a browser, controls one real UC2 microscope and gets data off it.**

Concretely — the MVP is reached when this scenario runs end to end on real hardware:

> Start the backend on the Pi. Open the GUI in Chrome. See that the camera, stage and illumination are
> connected. Start the live view. Adjust exposure and gain — and see no frame-rate slider, because
> this camera has no frame-rate control. Switch on a light source and set its power. Jog the stage in
> X, Y and Z; type an absolute Z position and watch the stage move there. Take a snapshot; the file
> lands on the operator's machine. Run a Z-scan over 20 planes; the images and their metadata are
> stored and viewable. Open a second browser: it can watch but not touch. Close the first browser:
> the second gains control. Close both: the lasers go off and the stage stops.

The live view in that scenario is delivered over **LiveKit/WebRTC/VP8** (`DEC-001`), which means an
SFU is part of the MVP deployment — not a later addition.

**The MVP deliberately excludes** (see §6): stitching, focus lock, time series, DAHENG cameras, the
overview camera, and historical-state re-application.

---

## 2. Task format

| Field | Meaning |
|---|---|
| **ID** | `T-nnn`, stable |
| **Effort** | `S` ≤ 1 day · `M` 2–4 days · `L` 1–2 weeks · `XL` > 2 weeks |
| **Deps** | tasks that must complete first |
| **Req** | requirements from `SRS_V1.md` this task satisfies |
| **DoD** | definition of done — the observable result |

---

## 3. Phase 0 — Restore a working tree

**Nothing else can be verified until this phase is green.** All four tasks come from
`InitReview.md` §5.1 and §7.

| ID | Task | Effort | Deps | Req | DoD |
|---|---|---|---|---|---|
| **T-001** | Restore `newswitch/uc2_devices/__init__.py` (or equivalent) and re-sync the editable install so the package imports | S | — | NFR-MNT-006 | `python -c "import newswitch.app"` succeeds |
| **T-002** | Make the `Uc2DetectorManager` import in `app.py` lazy, so a hardware-driver failure cannot break virtual mode at import time | S | T-001 | REQ-DEV-007 | Backend starts in virtual mode with the UC2 driver module deliberately broken |
| **T-003** | Get the backend test suite running and green again | M | T-001 | NFR-MNT-006 | `uv run pytest` collects and passes; CI backend job green |
| **T-004** | Restore lint/format cleanliness: `ruff format` + `ruff check --fix` over the UC2 files, clear the remaining errors by hand, move `extend-select` under `[tool.ruff.lint]` | S | T-001 | NFR-MNT-004 | `ruff check` and `ruff format --check` clean; no deprecation warning |
| **T-005** | Confirm the frontend codegen drift check passes against the restored backend | S | T-003 | IF-SW-003, NFR-CMP-001 | `just drift-check` green; `codegen-drift` CI job green |
| **T-006** | **Decide the fate of the native layer** and make the tree consistent with the decision: either restore the C++ ring buffer, bindings and tests, or drop `scikit-build-core` and move the native sections of `uc2_devices/README.md` into a design doc marked "planned" | M | T-001 | NFR-MNT-005, REQ-IMG-007 | No documentation describes absent code; `uv build` succeeds and does what the docs say |

> **Blocked on a decision:** T-006 depends on `OP-011` (is 500 MB/s per camera or aggregate?). If the
> real sustained rate is well below 500 MB/s, a Python-level buffer may carry the MVP and the native
> layer can be deferred. **Answer `OP-011` before starting T-006.**

**Phase exit criterion:** backend imports, tests pass, lint clean, codegen drift clean, and the tree's
documentation matches the tree's contents.

---

## 4. Phase 1 — Foundations

These are the pieces every later task depends on. Building them after the device work means retrofitting
them into the device work.

| ID | Task | Effort | Deps | Req | DoD |
|---|---|---|---|---|---|
| **T-010** | **Logging facility** as a top-level backend tool: fatal/error/warning/info/debug, timestamp + level + module + user + device, level configurable at start-up | M | T-001 | REQ-LOG-001…004, CON-DEV-006 | Every layer logs through it; level set from config without code change |
| **T-011** | **Grow `ImswitchConfig`**: move `port`, `baudrate`, `base_path`, `settings_path` and travel limits out of call sites into config; resolve `uc2DevSettings.json` relative to the package, not the CWD | M | T-001 | IF-HW-007, REQ-DAT-004, NFR-FLX-002 | No hardcoded device paths remain; starting from any CWD works identically |
| **T-012** | Make a missing settings file at an explicitly configured path a hard error rather than silent empty defaults | S | T-011 | REQ-DEV-008 | Wrong path → clear startup error naming the path, not "no cameras found" |
| **T-013** | **Capability descriptor** — define the schema and publish it per device instance (parameter, readable/writable, min, max, step, unit) | L | T-001 | REQ-DEV-003, NFR-FUN-001 | Every manager returns a descriptor; schema published to the frontend; keys per `InvariantMatrix.md` §8 |
| **T-014** | **Safe state** — implement `enter_safe_state()`: all illumination off, all stage motion stopped, logged with cause | M | T-010 | REQ-SAF-001…003, NFR-SAF-001 | Callable from shutdown, last-user-disconnect and unrecoverable device error; verified in virtual mode |
| **T-015** | Call `detector.shutdown()` from `release_managers`; release every SDK camera handle on shutdown | S | T-001 | REQ-DEV-006, NFR-REL-004 | Restart cycle on hardware leaks no handles |
| **T-016** | Add pacing/sleep to both `acquire_live()` loops; pace against exposure time; no busy-spin with no active detector | S | T-001 | REQ-IMG-011, NFR-PER-007 | Idle backend CPU < 5 % of one core on the Pi |
| **T-017** | Confine `/files/{file_path:path}` to `base_path` using the traversal check `cache.py` already implements | S | T-001 | NFR-SEC-001 | Traversal attempt returns 404/403; regression test added |
| **T-018** | Make CORS origins configurable; closed list as the deployed default | S | T-011 | NFR-SEC-002, IF-CM-006 | Wildcard only under an explicit development flag |
| **T-019** | Retire the three inconsistent live-view URL conventions of `InitReview.md` §4.4 — the dead `/ws/video` default in `StreamingView` and the hand-written H.264/Zstd texture hooks are superseded by `DEC-001`. `IF-CM-004` stays in force for the control and bulk-data endpoints that remain | S | T-001 | IF-CM-004 | No dead route references remain; one URL convention for the surviving endpoints |

**Phase exit criterion:** configuration, logging, capability reporting and safe state exist and are used.

---

## 5. Phase 2 — Device control and GUI gating

| ID | Task | Effort | Deps | Req | DoD |
|---|---|---|---|---|---|
| **T-020** | **One concrete camera driver.** Restore or rewrite the HIK driver on top of [UC2_HikPy]; plus a `MockCamera` so the whole UC2 branch is unit-testable with no SDK present | L | T-006, T-013 | IF-HW-001, NFR-FUN-002 | Hardware path enumerates and opens a real HIK camera; CI exercises the UC2 branch via `MockCamera` |
| **T-021** | Fix the `enumerate()` contract mismatch between the ABC and `Uc2DetectorManager` (`list[Uc2Camera]` vs. `CameraInfo`) | S | T-020 | IF-HW-001 | One consistent contract; typed and tested |
| **T-022** | **Per-subsystem hardware/virtual selection** replacing the single `use_virtual_microscope` flag | M | T-011 | IF-SW-006 | Any subsystem can be real while others are virtual; the mixed configuration is a tested case |
| **T-023** | Wire the existing UC2 **illumination** path to hardware (currently virtual unconditionally) | M | T-022 | REQ-LGT-001…004 | Real light source switches on/off and sets power from the GUI |
| **T-024** | Verify and complete the UC2 **stage** path over CAN: jog, step, absolute, home, position read-back, velocity/acceleration/jerk where supported | L | T-022, T-013 | REQ-STG-001…013, IF-HW-003 | All stage requirements demonstrable on hardware |
| **T-025** | **Soft travel limits** enforced in the backend, independent of frontend validation; limits from configuration | M | T-011, T-024 | REQ-STG-010, NFR-SAF-002 | Out-of-range command rejected with a message; no motion occurs |
| **T-026** | **Frontend capability gating (G1/G2)** — build device panels from the capability descriptor; unsupported parameters are not rendered | L | T-013 | IF-UI-005, REQ-DEV-004, REQ-CAM-007, REQ-STG-003/007 | `ACC-04` passes: a camera without frame-rate control shows no frame-rate control |
| **T-027** | **Frontend mode gating (G3–G9)** — implement the gate chain of `InvariantMatrix.md` §5 as one shared mechanism, driven by the CSV table | L | T-026, T-013 | IF-UI-010, NFR-USA-002/003 | Every row of `InvariantMatrix.csv` has a passing test; disabled controls state their cause |
| **T-028** | Bidirectional sync review: every control reflects device-originated changes; rejected values revert to the device-reported value with a message | M | T-026 | IF-UI-006, REQ-CAM-009 | Change made from a second client appears in the first within 200 ms |
| **T-029** | Move the stage **home** control out of the direction-button cluster into a separate menu; move step size / velocity / acceleration / jerk into that menu | S | T-026 | REQ-STG-005, REQ-STG-007 | Layout matches `basicRequirements.md` §Stages |
| **T-030** | Units and labels pass: ms, dB, 1/s, µm on every numeric control; slider and numerical entry always consistent | S | T-026 | IF-UI-007/008, NFR-USA-005 | Inspection checklist complete |

**Phase exit criterion:** a real camera, a real stage and a real light source are controllable from the
GUI, and the GUI shows only what they support.

---

## 6. Phase 3 — Imaging path

| ID | Task | Effort | Deps | Req | DoD |
|---|---|---|---|---|---|
| **T-039** | **Spike: VP8 encode feasibility on the Pi 5.** Measure software libvpx VP8 encode cost at candidate resolutions and frame rates, alongside a running acquisition. Output: the encoder operating point (resolution, frame rate, decimation) that meets the latency budget within the CPU budget | M | — | NFR-PER-009, ASM-08 | A measured table of resolution × frame rate × CPU × latency; a chosen operating point, or an escalation that the Pi cannot carry it |
| **T-047** | **Deploy the LiveKit server** as a component of the instrument stack: compose service, configuration, healthcheck, startup ordering, lifecycle alongside the backend | M | T-011 | IF-CM-009, IF-CM-011, DEP-08 | Backend publishes to a running SFU; server restarts cleanly with the stack |
| **T-048** | **LiveKit access tokens and room model**: backend mints a token per user per session; room naming per instrument/detector; token lifetime and renewal | M | T-047, T-060 | IF-CM-011, REQ-SES-010 | A user with no valid token cannot subscribe; a reconnecting user is re-issued a token without losing their place in the authority queue |
| **T-049** | **Frontend LiveKit subscriber**: `livekit-client`, track subscription, render into `<video srcObject>`; video-plane connection state reported separately from the control plane | M | T-047 | IF-CM-010, IF-CM-012 | Live view renders in Chrome; killing the SFU leaves the rest of the GUI fully operable with a clear video-unavailable indication |
| **T-040** | **Ring buffer per camera** — per the decision of T-006. Python interface: settings structure, `read_image`, `read_latest_image`, each with a metadata flag. Camera → buffer hand-over below Python | XL | T-006, T-020 | REQ-IMG-007…009 | Sustained capture at the rate agreed in `OP-011` with zero loss; overrun drops oldest and reports the count |
| **T-041** | **Live-view publish pipeline** for one selected camera: ring buffer → decimate + downscale → Mono8 → I420 → `rtc.VideoSource.capture_frame()` → LiveKit SDK (VP8, GCC/transport-cc, pacer). Decimation and downscaling must never touch stored data | L | T-040, T-047, T-039 | IF-CM-005/007/008, REQ-IMG-002, REQ-IMG-010 | Live view runs for 1 h without leak, stall or unbounded queue growth; encode cost within the budget set by T-039 |
| **T-042** | Camera selection for live view without interrupting other cameras | M | T-041 | REQ-IMG-003 | Switching cameras leaves the other acquiring |
| **T-043** | **Snapshot** — capture, store with metadata, and transfer to the operator machine with no second user action | M | T-041 | REQ-IMG-004/005 | File arrives on the operator machine; format per `OP-002` |
| **T-044** | **Durable acquisition store** separated from the volatile cache; acquired data survives restart | M | T-011 | REQ-DAT-001/005 | Restart does not delete acquired datasets; cache still cleared |
| **T-045** | Relax the storage dimensional contract so multi-channel/volumetric frames fit without changing two places | M | T-044 | REQ-DAT-007 | Non-2D detector data stores without a reshape hack |
| **T-046** | Acquisition metadata completeness: light path, objective, filters, illumination, exposure, gain, stage position, timestamp travel with every frame | M | T-013, T-044 | REQ-DAT-001, NFR-DB-002 | A stored frame cannot be read without its context |

> **Blocked on decisions:** T-039 and T-041 on `OP-015` (latency target — the encoder operating point
> cannot be chosen without it); T-040 on `OP-011`; T-043 on `OP-002` and `OP-017`; T-044 on `OP-018`;
> T-048 on `OP-004`.

> **`DEC-001` reshaped this phase.** The video plane is now LiveKit/WebRTC/VP8 (`SRS_V1.md` Appendix D).
> T-047, T-048 and T-049 are new; T-041 is a publish pipeline into an SFU rather than a hand-rolled
> socket stream. Note the coupling this creates: **T-048 pulls user identity (T-060, `OP-004`) forward
> out of Phase 5**, because LiveKit rooms are token-authenticated and nobody sees a live view without a
> token. Plan T-060 early.

**Phase exit criterion:** live view, snapshot and durable storage work on hardware.

---

## 7. Phase 4 — Minimum procedures

| ID | Task | Effort | Deps | Req | DoD |
|---|---|---|---|---|---|
| **T-050** | **Z-scan**: synchronised move-and-record over a Z series, parameterised by start/stop/step | L | T-024, T-046 | REQ-PRC-001/002 | 20-plane scan completes with correct per-plane Z metadata |
| **T-051** | **Procedure framework**: progress reporting, abort, lock acquisition for the whole run, defined state on failure | L | T-014 | REQ-PRC-020…023 | Every procedure inherits progress + abort; failure leaves the system idle and safe with data retained |
| **T-052** | **Autofocus** with a selectable focus measure and a defined search strategy | L | T-050, T-051 | REQ-PRC-003/004 | Converges on a test sample; measure selectable in the GUI |
| **T-053** | **Calibration**: manual and automatic modes, affine transform, residual reported, result persists across restart | L | T-024, T-051 | REQ-PRC-009…013 | `ACC-06` passes |
| **T-054** | **Sample-area definition**: coarse XY boundaries set at commissioning, stored in the device settings JSON | M | T-011, T-024 | REQ-PRC-018 | Boundaries survive restart and bound the stage |
| **T-055** | Mode **M7 CALIB-MANUAL** in the frontend gating: the user drives the stage while a procedure runs | M | T-027, T-053 | InvariantMatrix §6 | Manual calibration is operable; automatic calibration is not offered in M7 |

> **Blocked on decisions:** T-052 on `OP-005`; T-050/T-053 on `OP-025` (units and coordinate
> convention) — do not implement two coordinate conventions.

**Phase exit criterion:** Z-scan, autofocus and calibration run on hardware, abortable and reporting progress.

---

## 8. Phase 5 — Multi-user, robustness, safety

| ID | Task | Effort | Deps | Req | DoD |
|---|---|---|---|---|---|
| **T-060** | **User identity** — whatever `OP-004` resolves to; identity must survive a reconnect | M | — | REQ-SES-010, NFR-SEC-003 | A reconnecting user is recognised as the same user |
| **T-061** | **Control arbitration**: ordered user list, first-come-first-served authority, observer mode read-only | L | T-060, T-027 | REQ-SES-001…004, REQ-SES-011 | `ACC-02` passes |
| **T-062** | **Authority hand-over on disconnect**: losing user's GUI disabled with an explicit message; next user promoted | M | T-061 | REQ-SES-005/006 | `ACC-02` and `ACC-08` pass |
| **T-063** | **Last-user-leaves → safe state**, with the running-experiment exception | M | T-014, T-062 | REQ-SES-007…009 | `ACC-03` passes: series completes, then safe state |
| **T-064** | **Mutual watchdogs** frontend↔backend, loss detected within 5 s; automatic reconnect with full state resync | M | T-062 | IF-CM-003, NFR-REL-001/002 | `ACC-08` passes: cable pull detected, GUI reports, safe state entered |
| **T-065** | **Historical states**: retention, persistence and (if `OP-008` says so) re-application | L | T-046 | REQ-HIS-001…003 | Browsing works; re-apply is either implemented behind confirmation or explicitly deferred |
| **T-066** | **Laser-safety review** and implementation of what it demands: emission indicator, unattended-emission policy, power/duration limits | M | T-014 | REQ-LGT-006, NFR-SAF-003/004 | Hazard analysis exists and its software actions are implemented |

> **Blocked on decisions:** T-060/T-061 on `OP-004`; T-063 on `OP-010` and `OP-029`; T-065 on `OP-008`;
> T-066 on `OP-013`. **`OP-004` and `OP-013` should be answered first in this phase — both have wide
> blast radius.**

**Phase exit criterion:** multi-user rules hold, connection loss is safe, and the safety story is written down.

---

## 9. Phase 6 — Verification and release

| ID | Task | Effort | Deps | Req | DoD |
|---|---|---|---|---|---|
| **T-070** | Automate acceptance scenarios `ACC-01` … `ACC-10` from `SRS_V1.md` §4.3 in virtual mode | L | Phase 5 | §4.3 | All ten run in CI against virtual devices |
| **T-071** | Hardware acceptance run (V3/V4) on the instrument, results recorded | M | T-070 | §4.2 | Signed-off record of each ACC scenario on hardware |
| **T-072** | Frontend test coverage for the gate chain and the transport/patch layer; extract `BundleProvider.tsx` far enough to make it testable | L | T-027 | NFR-MNT-003, IR §4.2 | Gate chain and patch application under test |
| **T-073** | CI job that builds the native layer (if T-006 retained it) | M | T-006 | NFR-MNT-004 | Native build is exercised in CI, not only locally |
| **T-074** | Remove the dead code identified in `InitReview.md` §5.3-14: `z_range` (per `OP-024`), `LightPath.transformation_hash()`, `FrameBroadcaster.get_latest_frame()`, `plugins/gonio_meter.py` | S | — | NFR-MNT-007 | Grep-verified removal; no behaviour change |
| **T-075** | Restore the `pyproject.toml` metadata commented out in the working tree (`readme`, `homepage`) | S | T-001 | — | Published wheel carries full metadata |
| **T-076** | Populate `DOC/CHANGELOG_KC.md` and keep it current | S | — | CON-DEV-006, REQ-LOG-006 | Every change from Phase 0 onward is logged |
| **T-077** | Retire the superseded H.264/Zstd video path once LiveKit is proven on hardware: `FrameBroadcaster`'s shared encoders, `/stream/h264/{slot}`, `/stream/zstd/{slot}` and the ffmpeg subprocess lifecycle. Keep until T-049 passes on hardware — do not delete the working path before the replacement works | M | T-049, T-071 | DEC-001, NFR-MNT-007 | One video transport in the tree; no orphaned encoder code or routes |

---

## 10. Explicitly **not** in the MVP

Deferred, with the reason. Each remains a requirement in `SRS_V1.md`; none is cancelled.

| Item | Requirement | Why deferred |
|---|---|---|
| XY stitching | REQ-PRC-014…016 | Depends on calibration being trustworthy first; scope unclear pending `OP-007` |
| Focus lock | REQ-PRC-005/006 | Sensing principle undecided (`OP-006`); competes with live view for camera time |
| Time series | REQ-PRC-017 | Straightforward once the procedure framework (T-051) exists, but bounds undefined (`OP-026`) |
| Overview camera | REQ-PRC-007/008 | Second camera path; needs `OP-021` answered |
| DAHENG cameras | IF-HW-002 | One vendor is enough to prove the driver abstraction (`OP-020`) |
| ~~LiveKit / WebRTC transport~~ | ~~IF-CM-005~~ | **Moved into the MVP by `DEC-001` (2026-07-29).** See T-039, T-041, T-047, T-048, T-049 |
| ESP32 hardware synchronisation | IF-HW-005/006 | Interface unspecified (`OP-012`); software sequencing carries the Z-scan for now |
| Historical-state **re-application** | REQ-HIS-003 | Safety implications (`OP-008`, `OP-013`); browsing is enough for MVP |
| `Kube`/`KubeState` unification | IR §3.3 | The highest-leverage refactor, but it is a refactor — it buys no MVP capability. Do it **immediately after** MVP, before more kube types are added |
| `provide_managers()` decomposition | IR §5.2-5 | Same reasoning; T-022 touches it minimally without restructuring it |
| MDA control/dialog split (2,100 LOC) | IR §4.3 | Frontend debt, not an MVP blocker |

---

## 11. Critical path

```
T-001 ─┬─ T-003 ─── T-005                                     (tree restored)
       ├─ T-002
       └─ T-011 ─┬─ T-012
                 ├─ T-022 ─┬─ T-023
                 │         └─ T-024 ─┬─ T-025
                 │                   └─ T-050 ─── T-052
       T-013 ────┴─ T-026 ─── T-027 ─── T-028         T-053 ─── T-055
       T-010 ─── T-014 ─── T-051

  imaging / video track
       T-006 ─── T-020 ─── T-040 ─┬─ T-043
                                  └─ T-046
       T-039 ────────────────────────┐                        (encode budget)
       T-011 ─── T-047 ─┬─ T-049     ├─ T-041 ─── T-042       (live view)
                        └─ T-048 ────┘                └─ T-077 (retire old path)
                            ▲
  session track             │
       T-060 ───────────────┴─ T-061 ─── T-062 ─── T-063 ─── T-064
                                                             └─ T-070 ─── T-071
```

**The long pole is still `T-006 → T-020 → T-040 → T-041`** — the native/ring-buffer decision, the
camera driver, the buffer, then the publish pipeline. Its scope remains set by an unanswered question
(`OP-011`).

**`DEC-001` added a second constraint on the same phase.** T-041 now has three predecessors instead of
one: the ring buffer (T-040), a running SFU (T-047), and a measured encode budget (T-039). None is
hard individually; together they mean live view cannot be the first thing demonstrated.

**T-060 moved.** User identity was a Phase 5 task; LiveKit token issuing (T-048) needs it, so it now
sits on the video path. Either pull T-060 forward, or accept a temporary anonymous-token stopgap in
T-048 and revisit — **the first is cheaper**, because the stopgap has to be unpicked later anyway.

**Recommended parallelisation** — three tracks after Phase 0:

| Track | Tasks | Note |
|---|---|---|
| **Control** | T-011 → T-013 → T-022 → T-024 → T-026 → T-027 | Longest by task count; start immediately |
| **Imaging/video** | T-006 → T-020 → T-040, and T-039 + T-047 in parallel → T-041 | T-039 and T-047 need neither the driver nor the buffer — start them on day one |
| **Session** | T-060 → T-061 → T-062 | Pulled forward by T-048 |

The three meet at T-046 (metadata) and T-070 (acceptance).

---

## 12. Decisions needed before starting

Ordered by how much they block:

| Priority | Open point | Blocks |
|---|---|---|
| ~~—~~ | ~~`OP-001` — LiveKit or WebSocket transport?~~ | ✅ **Closed 2026-07-29 by `DEC-001`: LiveKit/WebRTC/VP8.** See T-039, T-041, T-047, T-048, T-049 |
| 1 | `OP-023` — where is the line between "architecture" (frozen) and "implementation" (changeable)? | Phase 0 scoping and every refactor decision below. *(`DEC-001` set the precedent that exemptions are granted individually and recorded — this makes `OP-023` survivable, not answered)* |
| 2 | `OP-011` — 500 MB/s per camera or aggregate, sustained how long, to RAM or disk? | T-006, T-040 — the critical path |
| 3 | `OP-015` — live-view latency target | **Raised by `DEC-001`.** T-039 and T-041: the transport is fixed, but the encoder operating point cannot be chosen without a latency budget |
| 4 | `OP-004` — user identity and authentication | **Raised by `DEC-001`.** T-048 (LiveKit tokens) as well as T-060, T-061 and the rest of Phase 5 |
| 5 | `OP-013` / `OP-010` — laser safety and the exact extent of the safe state | T-014, T-063, T-066 |
| 6 | `OP-018` — cache vs. durable data | T-044 |
| 7 | `OP-002` / `OP-017` — snapshot format and destination | T-043 |
| 8 | `OP-025` — stage units and coordinate convention | T-024, T-050, T-053 |
| 9 | `OP-005` — autofocus measures | T-052 |
| 10 | `OP-022` — which subsystems must be real for the first hardware release | T-022, T-023 |

**Points 1 and 2 should be settled before any code is written.** Both change what gets built, not just
how it gets built. **Points 3 and 4 both rose as a direct consequence of `DEC-001`** and should be
settled before Phase 3 starts.

---

## 13. Rough effort summary

| Phase | Tasks | Sum of estimates | Change from `DEC-001` |
|---|---|---|---|
| 0 — Restore working tree | 6 | ~1.5 weeks | — |
| 1 — Foundations | 10 | ~4 weeks | T-019 shrinks (deletion instead of unification) |
| 2 — Device control + gating | 11 | ~7 weeks | — |
| 3 — Imaging path | 11 | ~9.5 weeks (dominated by T-040) | **+4 tasks, +2.5 weeks** (T-039, T-047, T-048, T-049) |
| 4 — Minimum procedures | 6 | ~6 weeks | — |
| 5 — Multi-user + safety | 7 | ~5 weeks | T-060 pulled forward into Phase 3's dependency chain |
| 6 — Verification + release | 8 | ~4.5 weeks | **+1 task** (T-077, retire the old video path) |
| | **59 tasks** | **~37 person-weeks** | **+5 tasks, +3 weeks** |

Single-developer serial reading. With the three-track parallelisation of §11, calendar time is roughly
**21–26 weeks**. These are planning figures from document analysis, not estimates from the team —
they should be re-derived by whoever will do the work.

**On the cost of `DEC-001`:** the +3 person-weeks is the honest direct cost, but the accounting is
kinder than it looks. Adopting the SFU deletes work that was implied but never itemised — adaptive
bitrate, congestion control, pacing and multi-viewer fan-out would all have had to be hand-built on
the WebSocket path (`InitReview.md` §3.5 notes the live loop has no backpressure at all today). The
real exposure is not schedule but `ASM-08`: **software VP8 on a Pi 5 alongside acquisition is
unproven.** T-039 exists to find that out in week one rather than in month four.
