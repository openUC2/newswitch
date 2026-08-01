# Open Points Register — newswitch SRS

**Date:** 2026-07-29
**Relates to:** `DOC/SRS_V1.md`
**Purpose:** every question that arose while drafting the SRS and that cannot be answered from
`basicRequirements.md` or `InitReview.md`. Each entry blocks or weakens one or more requirements.

**Status values:** `OPEN` — needs a decision · `ASSUMED` — SRS proceeds on a stated assumption that
must be confirmed · `CONFLICT` — two source documents disagree · `CLOSED` — decided; the decision is
recorded in `SRS_V1.md` Appendix D and in the entry below

**Severity:** `S1` blocks MVP · `S2` blocks v1 · `S3` refinement

---

## Summary

| ID | Title | Sev | Status | Affected requirements |
|---|---|---|---|---|
| OP-001 | Live-video transport: LiveKit/WebRTC vs. WebSocket H.264/Zstd | S1 | **CLOSED — DEC-001** | IF-CM-005…012, NFR-PER-003/009, DEP-08/09 |
| OP-002 | Snapshot / export file format, bit depth, metadata | S1 | OPEN | REQ-IMG-006, REQ-DAT-006 |
| OP-003 | Semantics of "channel weighting" | S2 | OPEN | REQ-CAM-005, REQ-CAM-006 |
| OP-004 | User identification and authentication model | S1 | OPEN | REQ-SES-010, NFR-SEC-003 |
| OP-005 | Which autofocus focus measures | S1 | OPEN | REQ-PRC-003, REQ-PRC-004 |
| OP-006 | Focus-lock sensing principle and actuator | S2 | OPEN | REQ-PRC-005, REQ-PRC-006 |
| OP-007 | Stitching tile overlap and blending | S1 | OPEN | REQ-PRC-014, REQ-PRC-016 |
| OP-008 | Historical states: depth, persistence, re-apply | S2 | OPEN | REQ-HIS-001…003 |
| OP-009 | Data retention and storage-exhaustion behaviour | S2 | OPEN | REQ-DAT-008, NFR-DB-004 |
| OP-010 | Exact extent of the safe state | S1 | OPEN | REQ-SAF-001, REQ-SAF-004 |
| OP-011 | 500 MB/s — per camera or aggregate, for how long | S1 | OPEN | NFR-PER-001, NFR-PER-002 |
| OP-012 | ESP32 synchronisation hat interface | S2 | OPEN | IF-HW-005, IF-HW-006 |
| OP-013 | Laser safety requirements and hazard analysis | S1 | OPEN | REQ-LGT-006, NFR-SAF-004 |
| OP-014 | Hardware inventory: slot counts and models | S1 | OPEN | REQ-OPT-006, IF-HW-004 |
| OP-015 | Live-view latency target | S2 | OPEN | NFR-PER-003 |
| OP-016 | Number of concurrent users to support | S3 | OPEN | NFR-PER-008 |
| OP-017 | Destination of an "immediately downloaded" snapshot | S1 | ASSUMED | REQ-IMG-005 |
| OP-018 | Cache-wipe-on-restart vs. durable acquisition data | S1 | **CONFLICT** | REQ-DAT-005 |
| OP-019 | Browser support scope beyond Chrome | S3 | ASSUMED | IF-UI-001, IF-UI-002 |
| OP-020 | DAHENG camera support — required for v1? | S2 | OPEN | IF-HW-002 |
| OP-021 | Simultaneous acquisition on non-displayed cameras | S2 | OPEN | REQ-IMG-001, REQ-IMG-003 |
| OP-022 | Which subsystems must run on real hardware for v1 | S1 | OPEN | IF-SW-006 |
| OP-023 | "Architecture must not change" vs. recommended refactors | S1 | **CONFLICT** | CON-ARC-002, NFR-MNT-002 |
| OP-024 | `z_range` protocol — intended feature or dead code? | S3 | OPEN | — |
| OP-025 | Stage units, coordinate system and origin convention | S2 | OPEN | REQ-STG-006, REQ-STG-009 |
| OP-026 | Time-series bounds (max duration, interval, volume) | S2 | OPEN | REQ-PRC-017 |
| OP-027 | Off-site / remote access outside the lab network | S2 | ASSUMED | ASM-01, NFR-SEC-002 |
| OP-028 | May an observer operate the safe-state / stop-all control? | S1 | OPEN | INV-007, matrix S-07 |
| OP-029 | Which mode applies to an experiment running with no user connected? | S1 | OPEN | REQ-SES-008, matrix M5 |
| OP-030 | Is snapshot permitted during stage motion? | S3 | ASSUMED | matrix C-04 / M4 |
| OP-031 | Is "moving" a global mode or a per-axis lock state? | S2 | OPEN | matrix M4 column |
| OP-032 | Do rotators need their own lock in the backend vocabulary? | S3 | OPEN | REQ-OPT-003, matrix O-03 |

---

## 1. Conflicts between source documents

These are not gaps — they are two statements that cannot both hold. They need a decision, not an
answer.

### OP-001 — Live-video transport: LiveKit/WebRTC vs. WebSocket H.264/Zstd

**Severity:** S1 · **Status:** ✅ **CLOSED — `DEC-001`, 2026-07-29**

> ## Decision (2026-07-29, C. Karras)
>
> **Option B — LiveKit / WebRTC / VP8, with an SFU**, exactly as specified in
> `basicRequirements.md` §Image handling.
>
> **The architecture-freeze rule (`CON-ARC-002`) is exceptionally waived for this subsystem.** The
> waiver covers the video plane only; every other subsystem remains frozen. Recorded as
> `CON-ARC-002-E1` in `SRS_V1.md` §3.6.
>
> **What this makes binding:** `IF-CM-005` … `IF-CM-012`.
> **What it supersedes:** the H.264/Zstd `FrameBroadcaster` transport of Version 1.0
> (`/stream/h264/{slot}`, `/stream/zstd/{slot}`).
>
> **Consequences to carry forward:**
>
> 1. **A LiveKit server becomes a deployed component** (`DEP-08`) — not just a library. It needs a
>    home (on the Pi, or adjacent to it), a place in the compose/Docker setup, and a lifecycle.
> 2. **The frontend gains `livekit-client`** (`IF-CM-010`) and loses its two hand-written live-texture
>    hooks. `InitReview.md` §4.4 lists three inconsistent live-view URL conventions — this decision
>    deletes that problem rather than fixing it, and `T-019` shrinks accordingly.
> 3. **Software VP8 encode on a Raspberry Pi 5** (`DEP-09`, `ASM-08`). There is no hardware VP8
>    encoder on this platform. This must be measured early — see `NFR-PER-009` and `T-041`.
> 4. **WebRTC needs UDP** (`ASM-07`). On a flat lab network this is a non-issue; behind a restrictive
>    firewall a TURN server becomes a further dependency.
> 5. **Access tokens.** LiveKit rooms are token-authenticated. Who issues those tokens is now coupled
>    to `OP-004` (user identity) — the backend must mint a token per user per session, which means it
>    needs to know who the user is. **`OP-004` rose in priority as a result of this decision.**
> 6. **The shared-encoder optimisation of Version 1.0 is no longer needed.** `FrameBroadcaster` keys
>    encoders by `(slot, config)` so N viewers cost one encode; the SFU now provides that fan-out
>    natively. One publisher per camera, N subscribers.
> 7. **`OP-016` (concurrent user count) becomes cheaper to answer** — SFU fan-out scales better than
>    WebSocket fan-out, so the number is less likely to be a constraint.
>
> **Still open and now more urgent:** `OP-015` (latency target). The transport is fixed, but the
> encoder operating point — resolution, frame rate, decimation factor — cannot be chosen without a
> latency budget and a CPU budget. Answer `OP-015` before `T-041` starts.

**Original analysis, retained for the record:**

**Context.** `basicRequirements.md` §Image handling specifies the stream flow explicitly:

```
Camera → RingBuffer → [decimate + downscale + Mono8→I420]
   → rtc.VideoSource.capture_frame() → LiveKit SDK (VP8 + GCC/transport-cc + pacer)
   → LiveKit Server (SFU) → Browser: livekit-client
```

`InitReview.md` §2 records what Version 1.0 actually does: per-slot WebSocket routes
`/stream/h264/{slot}` and `/stream/zstd/{slot}`, served by `FrameBroadcaster` with shared encoders.
No LiveKit, no SFU, no WebRTC.

**Question.** Which is the target?

**Why it matters.** This is the single largest scope item in the document. The LiveKit route adds a
server component to deploy on/next to the Raspberry Pi, a new client dependency, and a different
latency and congestion-control profile. It also directly contests `CON-ARC-002` ("architecture must
not be changed") — because the *existing* architecture is the WebSocket one.

**Options.**

| | Option | Consequence |
|---|---|---|
| A | Keep WebSocket H.264/Zstd | No new infrastructure. Congestion control and adaptive bitrate must be built by hand. Matches `CON-ARC-002` |
| B | Move to LiveKit/WebRTC as specified | Gets adaptive bitrate, pacing and NAT traversal for free. Requires deploying a LiveKit server; contradicts `CON-ARC-002` |
| C | Keep WebSocket for MVP, LiveKit as a later transport behind the same interface | Defers the decision; requires the transport to be abstracted now |

**Recommendation:** **C** for MVP — the ring buffer already isolates the frame source, so the encoder
and transport sit behind one seam. **Do not** build LiveKit before the backend imports again.

**Owner:** C. Karras · **Needed by:** before any live-view work starts

---

### OP-018 — Cache wiped on restart vs. durable acquisition data

**Severity:** S1 · **Status:** CONFLICT

**Context.** `InitReview.md` §3.4: the local cache is created with `delete_on_restart=True`, wiping
`/tmp/newswitch/cache` at every boot. Meanwhile the requirements ask for time series, stitching and
Z-scans — multi-hour acquisitions whose results must survive.

**Question.** Where does acquired data live, and what guarantees does it have?

**Why it matters.** If an overnight time series lands in a directory that the next restart deletes,
the data-loss mode is silent and total.

**Options.** (A) Keep cache volatile, add a separate durable store with an explicit "save" step ·
(B) Make the acquisition store durable and add explicit cleanup · (C) Stream results off the
instrument as they are produced.

**Recommendation:** **A** — keep the cache honest (it is a cache), and make persistence a distinct,
visible operation. Pairs with `OP-002` and `OP-017`.

**Owner:** C. Karras · **Needed by:** before time-series/stitching work

---

### OP-023 — "Architecture must not change" vs. the refactors recommended in the review

**Severity:** S1 · **Status:** CONFLICT

**Context.** `basicRequirements.md` §Base architectural setup: *"the current basic design and
architecture of the newswitch package must not be changed"*. `InitReview.md` §7 recommends, among
others: unifying `Kube`/`KubeState` (and collapsing two frontend renderer trees), breaking up the
26-tuple composition root, and making hardware selection per-subsystem.

**Question.** Where is the line between "the architecture" (frozen) and "the implementation of it"
(open to change)?

**Partial answer already on record.** `DOC/CHANGELOG_KC.md` v1.0 (28.07.26) states: *"basic design
decisions, that can be concluded from the current structure shall not be changed. What this means is
written in **General setup rule**"*. That points at `basicRequirements.md` §General setup rule — i.e.
the frozen set is: backend/frontend split, React/Vite/TypeScript frontend, Python backend with
dependency injection and protocol setup, the routines → managers → protocols (states) → devices
layering, availability of purely simulated devices, and the rekuest-next + FastAPI connection
structure. **This reading needs confirming**, because it would place the `Kube`/`KubeState` model, the
shape of the composition root and the frontend component decomposition *outside* the freeze — all
three are implementation of the layering, not the layering itself.

**Proposed reading**, to be confirmed:

| Frozen — architecture | Open — implementation |
|---|---|
| backend/frontend split | shape of the composition root |
| routines → managers → protocols layering | number/kind of `Kube` classes |
| protocol-based DI | how hardware/virtual selection is configured |
| rekuest-next + FastAPI transport structure | internal module sizes and file splits |
| generated frontend client | frontend component decomposition |
| ring buffer in C/C++ below Python | ring buffer internals |

**Why it matters.** Without this line, every finding in `InitReview.md` §5.2 is either mandatory or
forbidden, and the MVP task list cannot be prioritised.

**Precedent set by `DEC-001` (2026-07-29).** The video transport was granted an explicit, scoped
exemption from the freeze rather than a reinterpretation of it. That establishes a workable mechanism:
**the freeze holds by default, and exemptions are granted individually, named, and recorded** (here as
`CON-ARC-002-E1`). This does not answer `OP-023` — it makes it survivable in the meantime. Each
remaining `InitReview.md` §5.2 refactor can be raised as its own exemption request.

**Owner:** C. Karras · **Needed by:** immediately — gates `DOC/MVP_TASKS.md`

---

## 2. Functional gaps

### OP-002 — Snapshot / export file format

**Severity:** S1 · **Status:** OPEN

`basicRequirements.md` §Imaging requires a snapshot that is "immediately downloaded". Unspecified:
container (PNG / TIFF / OME-TIFF / raw), bit depth (8 vs. 12/16), whether raw sensor data or the
displayed rendering is saved, and which metadata travels with it.

**Question.** For a snapshot and for an exported dataset: what format, what bit depth, what metadata?

**Recommendation:** OME-TIFF, native bit depth, full acquisition metadata for scientific export; PNG
of the rendered view as a separate, explicitly-labelled "screenshot" function. The two are different
user needs and should not share one button.

---

### OP-017 — Destination of an "immediately downloaded" snapshot

**Severity:** S1 · **Status:** ASSUMED

The phrase is *"Snapshot shall be immediately downloaded to the remote machine"*. "Remote machine"
is ambiguous: from the instrument's perspective the remote machine is the operator's browser host;
from the operator's perspective it might be a network share or a data server.

**SRS assumption:** the operator machine running the browser, via a normal browser download.

**Question.** Confirm, or specify the network target (share, S3, data server) instead.

---

### OP-003 — Semantics of "channel weighting"

**Severity:** S2 · **Status:** OPEN

Listed under camera settings, marked "only for live viewer". Could mean: (a) RGB channel gains for a
colour camera, (b) per-illumination-channel blend weights in a composite live view, (c) display
LUT/contrast weighting.

**Question.** Which? And: does it ever affect stored data? (SRS currently says no — `REQ-CAM-005`.)

---

### OP-005 — Autofocus focus measures

**Severity:** S1 · **Status:** OPEN

`basicRequirements.md`: *"Autofocus → options → select measure"*. The set of measures is not given.

**Question.** Which measures must be offered? Candidates: normalised variance, Brenner gradient,
Tenengrad, Laplacian energy, Vollath F4, DCT-based. Also: search strategy (coarse-to-fine, hill
climbing, fixed sweep + fit), Z range and step, and the abort criterion.

**Note.** Version 1.0 contains `managers/helpers/psf.py` and a variance helper — the beginnings of
this exist and should be inspected before deciding.

---

### OP-006 — Focus-lock sensing principle and actuator

**Severity:** S2 · **Status:** OPEN

**Question.** Is focus lock image-based (repeated focus measure on the live stream) or hardware-based
(reflection/IR sensor)? What is the correcting actuator — the Z stage, or a separate piezo? What
update rate and correction limit?

**Why it matters.** An image-based lock competes with the live view and the acquisition for camera
time; a hardware-based one is an additional device with its own protocol and capability descriptor.

---

### OP-007 — Stitching tile overlap and blending

**Severity:** S1 · **Status:** OPEN

**Question.** Tile overlap fraction; whether stitching is blind (stage-coordinate placement using the
affine calibration) or feature-based (cross-correlation registration); blending method (none, linear
feather, multi-band); whether the stitched result is assembled on the instrument or in the browser.

**Why it matters.** Blind stitching on stage coordinates is a small feature on top of existing
calibration. Feature-based registration with blending is a significant image-processing component on
a Raspberry Pi.

---

### OP-008 — Historical states

**Severity:** S2 · **Status:** OPEN

`basicRequirements.md` says historical states "shall be available (in init version already
implemented)".

**Questions.** (1) How many states are retained, or over what time window? (2) Do they persist across
a backend restart? (3) Can a historical state be **re-applied** to the instrument, or is it
view-only? (4) Are they per-user or global?

**Why it matters.** (3) is the difference between a log viewer and a state-restoration feature with
its own safety implications (re-applying a state turns lasers on).

---

### OP-010 — Extent of the safe state

**Severity:** S1 · **Status:** OPEN

`basicRequirements.md`: *"If there is no further user, the microscope shall stop immediately."*

**Question.** What exactly does "stop" include? Proposed minimum in `REQ-SAF-001`: all light sources
off, all stage motion halted. Additional candidates: stop camera acquisition, close the shutter,
park/retract the objective, home an axis, disable motor drivers.

**Why it matters.** This is the system's principal safety behaviour and it is currently one clause
long.

---

### OP-014 — Hardware inventory

**Severity:** S1 · **Status:** OPEN

**Question.** For the target instrument: how many objective slots, filter banks and filters per bank,
which rotators and how many axes, which specific camera models, which stage controller, and what are
the travel ranges per axis?

**Why it matters.** Capability descriptors (`REQ-DEV-003`) cannot be validated without knowing the
real device set, and `basicRequirements.md` §Further devices lists only *"rotators, filters and
objective"*.

---

### OP-021 — Simultaneous acquisition on non-displayed cameras

**Severity:** S2 · **Status:** OPEN

*"Multiple cameras should be able to be used (only one will be shown in the live view)"* — clear for
display. Unclear for acquisition.

**Question.** May a second camera acquire and record while the first is displayed (e.g. the overview
camera of `REQ-PRC-008`)? If so, the 500 MB/s budget of `OP-011` is an aggregate figure.

---

### OP-024 — `z_range` protocol

**Severity:** S3 · **Status:** OPEN

`InitReview.md` §3.2 records `protocols/z_range.py` + `managers/virtual/virtual_z_range.py` as
present but referenced from nowhere, with a `z_range` lock in the vocabulary.

**Question.** Was this the start of the Z-scan feature (`REQ-PRC-001`), or abandoned? Delete, or
finish?

---

### OP-025 — Stage units, coordinate system, origin

**Severity:** S2 · **Status:** OPEN

**Question.** Units for position and step size (µm assumed); axis sign convention; where the origin
sits (hardware home vs. a sample-relative origin); whether Z is positive towards or away from the
sample.

**Why it matters.** Every stage requirement, the calibration transform and the stitching layout
depend on one consistent answer.

---

### OP-026 — Time-series bounds

**Severity:** S2 · **Status:** OPEN

**Question.** Shortest interval, longest duration, maximum frame count, and expected total data
volume for a time series. Related to `OP-009` and `OP-018`.

---

## 3. Non-functional gaps

### OP-011 — 500 MB/s: per camera or aggregate?

**Severity:** S1 · **Status:** OPEN

`basicRequirements.md` §Cameras states *"Max DataRate: 500 MB/sec"* under a heading listing two camera
families.

**Questions.** (1) Per camera, or summed across all cameras? (2) Peak or sustained? (3) For how long
must it be sustained — the ring buffer depth follows directly from this. (4) What is the destination
of that data: RAM only, or disk? A Raspberry Pi 5 cannot write 500 MB/s to storage.

**Why it matters.** Ring-buffer sizing, the decision of what is native vs. Python, and whether
sustained recording at full rate is possible at all, all follow from this number.

---

### OP-015 — Live-view latency target

**Severity:** S2 · **Status:** OPEN

**Question.** What glass-to-glass latency is acceptable for the live view? Interactive focusing by
hand typically needs < 150 ms; a monitoring view tolerates seconds.

**Why it matters — and this changed with `DEC-001`.** The transport and codec are now fixed
(LiveKit/WebRTC/VP8), so this number no longer selects a technology. It selects the **operating point
inside it**: resolution, frame rate, decimation factor and the encoder's latency/quality trade-off,
all bounded by what software VP8 costs on a Pi 5 (`ASM-08`). `T-039` measures the envelope; this
number says where in that envelope to sit. **Answer before `T-041`.**

---

### OP-016 — Concurrent user count

**Severity:** S3 · **Status:** OPEN

**Question.** How many simultaneous viewers must one instrument support? Affects the fan-out design of
the live stream (shared-encoder WebSocket fan-out scales differently from an SFU).

---

### OP-004 — User identification and authentication

**Severity:** S1 · **Status:** OPEN

The multi-user control-arbitration rules (`REQ-SES-001`…`012`) presuppose identifiable users.
Version 1.0 has a `get_user_from_request` returning an integer, and CORS `allow_origins=["*"]`.

**Questions.** (1) Is there a login at all, or is a user simply a connection? (2) If there are
accounts, where do they live? (3) Are there roles (operator vs. observer vs. admin)? (4) May an admin
force control away from the current holder?

**Why it matters.** "First come, first served" is only meaningful if the system can tell two users
apart across a reconnect. Without identity, a reconnecting user is a new user and goes to the back of
the queue.

**Raised in priority by `DEC-001`.** LiveKit rooms are access-token authenticated, so the backend must
mint a token per user per session before anyone can see a live view at all. Video now depends on
identity — this can no longer be deferred behind the imaging work.

---

### OP-013 — Laser safety and hazard analysis

**Severity:** S1 · **Status:** OPEN

The system commands lasers and motorised stages. No hazard analysis exists, and
`basicRequirements.md` contains no safety section.

**Questions.** (1) Laser class of the sources? (2) Is there a hardware interlock, and must software
observe or report it? (3) Must the GUI show an emission indicator? (4) Is a software-commanded
emission permitted while no user is watching (during an unattended time series — note this is
explicitly allowed by `REQ-SES-008`)? (5) Are there maximum-power or maximum-duration limits to
enforce in software?

**Why it matters.** `REQ-SES-008` deliberately keeps experiments running with **no user connected** —
i.e. lasers emitting unattended. That is a defensible requirement for long acquisitions, but it must
be a conscious decision, recorded, not a side effect.

---

### OP-027 — Off-site access

**Severity:** S2 · **Status:** ASSUMED

**SRS assumption (`ASM-01`):** the instrument is on a trusted, isolated lab network.

**Question.** Confirm. If remote access over an untrusted network is ever intended, then `NFR-SEC-001`
…`003`, transport encryption and authentication move from "hygiene" to "blocking", and `OP-004` must
be answered first.

---

### OP-009 — Retention and storage exhaustion

**Severity:** S2 · **Status:** OPEN

**Questions.** (1) How long does acquired data stay on the instrument? (2) What happens when the disk
fills mid-acquisition — abort, oldest-first eviction, or refuse to start? (3) Who deletes data?

---

### OP-012 — ESP32 synchronisation hat

**Severity:** S2 · **Status:** OPEN

*"If devices shall be synced together this is done via an ESP32 hat for the Raspberry PI."*

**Questions.** (1) Which devices participate (camera trigger, stage step, illumination gating)? (2)
Electrical interface and protocol between Pi and hat? (3) Which procedures require it —
`REQ-PRC-001` (Z-scan) says "synchronized movement", is that hat-synchronised or software-sequenced?
(4) Is the hat present in the MVP hardware?

---

## 4. Scope questions

### OP-019 — Browser support

**Severity:** S3 · **Status:** ASSUMED

`basicRequirements.md`: *"Shall run basically in browser (Chrome)"* plus four operating systems.
**SRS assumption:** Chrome is the only supported browser; the OS list refers to Chrome on those
platforms. Firefox and Safari are untested, not forbidden.

---

### OP-020 — DAHENG support in v1

**Severity:** S2 · **Status:** OPEN

Both HIKROBOT and DAHENG are listed. Version 1.0 has a HIK driver path (currently deleted from the
tree) and no DAHENG driver.

**Question.** Is DAHENG required for the MVP, or is HIKROBOT-only acceptable for the first release
with DAHENG following?

---

### OP-022 — Which subsystems must run on real hardware for v1

**Severity:** S1 · **Status:** OPEN

`InitReview.md` §3.1: only serial, stage and detector switch to hardware; illumination, objective and
filter bank stay virtual unconditionally even though UC2 filter-bank and galvo managers exist,
unwired.

**Question.** For the first hardware release, which subsystems must be real? A microscope with virtual
illumination cannot image anything, so illumination is presumably mandatory — confirm and rank the
rest.

---

## 5. GUI operability questions (raised by `DOC/InvariantMatrix.md`)

### OP-028 — May an observer operate the safe-state / stop-all control?

**Severity:** S1 · **Status:** OPEN

Two defensible positions collide. **Physical safety:** anyone who can see the instrument misbehaving
should be able to stop it, regardless of who holds control authority. **Control arbitration:** an
observer who can stop the instrument can sabotage another user's multi-hour acquisition.

The matrix currently sets `S-07 / M1 = D` (observer cannot). `INV-007` flags this as unresolved.

**Recommendation:** allow it, and log the actor. A stop that requires the right credentials is not a
stop. Depends on `OP-013`.

---

### OP-029 — Mode of an unattended running experiment

**Severity:** S1 · **Status:** OPEN

`REQ-SES-008` keeps an experiment running when its user disconnects, and `REQ-SES-007` sends the
instrument to the safe state when the last user leaves. During an unattended experiment both apply and
there is no control holder at all.

**Question.** Is this M5 PROCEDURE with an empty authority slot, or a distinct mode **M8 UNATTENDED**
with its own row values? Who may take control of a running experiment when they connect — abort it,
observe it, or inherit it?

---

### OP-030 — Snapshot during stage motion

**Severity:** S3 · **Status:** ASSUMED

The matrix sets `C-04 / M4 = D` on image-quality grounds (motion blur). A user tracking a moving
sample, or debugging stage behaviour, may reasonably want it.

**SRS assumption:** disabled during commanded motion. Confirm or relax.

---

### OP-031 — Is "moving" a mode or a per-axis lock state?

**Severity:** S2 · **Status:** OPEN

M4 MOVING is modelled as a global mode. A CAN-bus stage may report motion per axis, in which case
controlling Y while X is moving is legitimate and the global mode is too coarse.

**Question.** Does the stage controller support concurrent independent axis motion? If yes, M4 should
collapse into a per-axis lock and the M4 column disappears.

---

### OP-032 — Lock for rotators

**Severity:** S3 · **Status:** OPEN

The published lock vocabulary is `stage_position`, `camera_parameters`, `objective`, `illumination`,
`filter_bank`, `io`, `expanse_state`, `cache`, `hook_registry`. Rotators (`REQ-OPT-003`) map to none of
these.

**Question.** Add a `rotator` lock, or fold rotators under `filter_bank`? Depends on `OP-014`
(what the rotators actually are).

---

## 6. How to close these

1. Work through §1 (conflicts) first. `OP-001` is **closed** (`DEC-001`); `OP-018` and `OP-023` remain.
   They change what gets built, not just how.
2. Then the S1 entries in §2 and §3. `OP-011`, `OP-004`, `OP-013` and `OP-010` shape the
   architecture and the safety story.
3. Record each decision in this file (append a **Decision** block; do not delete the question), then
   update the corresponding requirement in `SRS_V1.md` and remove its ***UNCLEAR*** marker in the
   next SRS version.
