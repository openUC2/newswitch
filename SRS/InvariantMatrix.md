# GUI Operability Invariant Matrix — newswitch

**Document ID:** INVMAT
**Version:** 1.0 (draft)
**Date:** 2026-07-29
**Normative for:** `SRS_V1.md` → `IF-UI-005`, `IF-UI-010`, `NFR-USA-002`, `NFR-USA-003`
**Editable companion:** `DOC/InvariantMatrix.csv` (same content, spreadsheet-editable, one row per
GUI function)

---

## 1. Purpose

`basicRequirements.md` states: *"Only show GUI elements, which are really implemented and possible to
use in the current version of the microscope."*

That is a strong requirement and it cannot be satisfied by ad-hoc `disabled={…}` expressions scattered
through the frontend. This document defines, for **every GUI function**, the conditions under which it
is shown, enabled, disabled or hidden — so that the rule is stated once, reviewable by a
non-programmer, and testable.

"Invariant" here means: **these relationships hold in every version of the software.** Adding a
feature adds a row; it does not change the gating logic.

---

## 2. How to edit this document

1. Edit `DOC/InvariantMatrix.csv` in a spreadsheet (one row per GUI function, one column per mode), or
   edit the tables in §7 of this file directly. Keep the two in step.
2. Adding a GUI function → add a row. Fill **every** column: an empty cell is a defect, not a default.
3. Adding an operating mode → add a column **and** review every existing row.
4. Never delete a row for a removed feature — mark its status `RETIRED` so the history of the decision
   survives.
5. Any change here is a change to a normative document: log it in `DOC/CHANGELOG_KC.md`.

---

## 3. Cell values

| Code | Meaning | Rendered as |
|---|---|---|
| **A** | **Available** — control is shown and actionable | normal, interactive |
| **C** | **Confirm** — available, but activation requires an explicit confirmation step | normal + confirm dialog |
| **D** | **Disabled** — shown, not actionable, **with a stated reason** (`NFR-USA-003`) | greyed, tooltip gives cause |
| **V** | **View only** — a display element, never actionable | read-only indicator |
| **H** | **Hidden** — not rendered at all | absent from the DOM |

**D vs. H is the central distinction.**
*Hidden* means "this instrument can never do this" — the user must not learn the control exists.
*Disabled* means "not right now" — the user must be able to see it and understand why.

---

## 4. State variables

The mode of the GUI is a function of these variables. They are all backend-owned; the frontend derives
its rendering from them and holds no authority of its own.

| Var | Name | Values | Source |
|---|---|---|---|
| `conn` | Backend connection | `up` / `down` | frontend transport watchdog |
| `auth` | Control authority | `holder` / `observer` | backend session manager |
| `cap[f]` | Capability for function *f* | `supported` / `unsupported` | device capability descriptor (`REQ-DEV-003`) |
| `dev[s]` | Device status of subsystem *s* | `ready` / `absent` / `error` | device manager |
| `lock[l]` | Lock *l* | `free` / `self` / `other` | backend lock vocabulary |
| `act` | Current activity | `idle` / `live` / `moving` / `procedure` | backend |
| `safe` | Safe state | `normal` / `engaged` | backend |
| `val[x]` | Value-dependent visibility | e.g. light source on/off | device state |

---

## 5. Gate precedence — the invariant that governs all others

Every control is evaluated through this chain **in order**. The **first gate that fires wins**, and a
gate that hides always beats a gate that disables.

```
 G1  CAPABILITY   cap[f] = unsupported ................................ → H
 G2  PRESENCE     dev[s] = absent ..................................... → H
 G3  CONNECTION   conn = down ......................................... → D  (whole GUI, one banner)
 G4  SAFE STATE   safe = engaged ...................................... → D  (except recovery controls)
 G5  DEVICE ERROR dev[s] = error ...................................... → D  (except recovery controls)
 G6  AUTHORITY    auth = observer ..................................... → D
 G7  LOCK         lock[l] = other ..................................... → D
 G8  MODE         look up the matrix in §7 ............................ → A / C / D / H
 G9  VALUE        val[x] condition not met ............................ → H
     otherwise .......................................................... → A
```

**INV-001** — A control for an unsupported capability is **never** rendered, in any mode, for any user,
including the control-holding user. Capability gating precedes everything.

**INV-002** — A control that is rendered and enabled **shall** succeed when activated, or fail with a
device-reported error. It shall never fail because the GUI offered something the system could not do.

**INV-003** — A disabled control **shall** state its cause, and the cause **shall** be the gate that
fired: "no control authority", "held by <user>", "device not ready", "procedure running", "safe state
engaged", "connection lost".

**INV-004** — Hiding is a property of the *instrument*; disabling is a property of the *moment*. If a
control's visibility would change without a hardware or configuration change, it must be D, not H.

**INV-005** — Every display element (`V`) remains visible in every mode, including `conn = down`, where
it shows the last known value marked explicitly as stale.

**INV-006** — No control that commands motion or emission is `A` while `auth = observer`. There is no
exception, including for read-back or "preview" controls that internally command the device.

**INV-007** — The safe-state / stop-all control is reachable in every mode in which any device can be
active. It is the only control that may bypass gates G6–G8 ***UNCLEAR*** — see `OP-010` and `OP-028`
below.

**INV-008** — A procedure holds the locks of every subsystem it drives for its whole duration
(`REQ-PRC-022`); therefore during `act = procedure` the affected controls are disabled by G7, not by a
separate rule. G8 restates this only for readability.

---

## 6. Operating modes (matrix columns)

| Mode | Condition | Description |
|---|---|---|
| **M0 DISCONNECTED** | `conn = down` | No backend. GUI shows last known state, marked stale |
| **M1 OBSERVER** | `conn = up`, `auth = observer` | Connected, watching, no device authority |
| **M2 IDLE** | `auth = holder`, `act = idle` | Full control, nothing running |
| **M3 LIVE** | `auth = holder`, `act = live` | Live view running |
| **M4 MOVING** | `auth = holder`, `act = moving` | Commanded stage motion in progress |
| **M5 PROCEDURE** | `auth = holder`, `act = procedure` | Z-scan / stitch / time series / MDA / autofocus running |
| **M6 SAFE / ERROR** | `safe = engaged` or `dev[*] = error` | Safe state entered or unrecovered device error |
| **M7 CALIB-MANUAL** | `act = procedure`, manual calibration | Special: the procedure *requires* the user to drive the stage |

M7 exists because manual calibration (`REQ-PRC-011`) inverts the usual rule — a procedure is running,
yet stage control must remain with the user.

---

## 7. The matrix

### 7.1 Session and global

| # | GUI function | Lock | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S-01 | Backend connection indicator | — | V | V | V | V | V | V | V | V | IF-UI-004 |
| S-02 | Device connection indicators | — | V | V | V | V | V | V | V | V | IF-UI-003 |
| S-03 | Connected-user list | — | V | V | V | V | V | V | V | V | REQ-SES-011 |
| S-04 | Control-authority indicator | — | V | V | V | V | V | V | V | V | REQ-SES-011 |
| S-05 | Request control | — | H | A | H | H | H | H | D | H | REQ-SES-003 |
| S-06 | Release control | — | H | H | A | A | D | C | D | D | REQ-SES-012 |
| S-07 | Safe state / stop all | — | H | D | A | A | A | C | D | A | REQ-SAF-001 |
| S-08 | Acknowledge error / recover | — | H | D | H | H | H | H | A | H | REQ-DEV-005 |
| S-09 | Stale-state banner | — | V | H | H | H | H | H | H | H | INV-005 |

### 7.2 Devices

| # | GUI function | Lock | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D-01 | Device list / status | — | V | V | V | V | V | V | V | V | REQ-DEV-002 |
| D-02 | Initialise / start device | — | H | D | A | D | D | D | A | D | REQ-DEV-001 |
| D-03 | Stop device | — | H | D | C | C | D | D | D | D | REQ-DEV-001 |
| D-04 | Reload device configuration | — | H | D | C | D | D | D | C | D | REQ-DAT-002 |

### 7.3 Camera and imaging

| # | GUI function | Lock | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C-01 | Select live-view camera | `camera_parameters` | H | D | A | A | A | D | D | A | REQ-IMG-002 |
| C-02 | Start live view | `camera_parameters` | H | D | A | H | A | D | D | H | REQ-IMG-002 |
| C-03 | Stop live view | `camera_parameters` | H | D | H | A | A | D | D | A | REQ-IMG-002 |
| C-04 | Snapshot | `io` | H | D | A | A | D | D | D | A | REQ-IMG-004 |
| C-05 | Camera name | `camera_parameters` | H | D | A | A | A | D | D | D | REQ-CAM-001 |
| C-06 | Exposure time (slider + entry) | `camera_parameters` | H | D | A | A | A | D | D | A | REQ-CAM-002 |
| C-07 | Gain (slider + entry) | `camera_parameters` | H | D | A | A | A | D | D | A | REQ-CAM-003 |
| C-08 | Frame rate (slider + entry) | `camera_parameters` | H | D | A | A | A | D | D | A | REQ-CAM-004 |
| C-09 | Channel weighting | — | H | H | H | A | H | H | H | A | REQ-CAM-005 |
| C-10 | Live image canvas | — | V | V | H | V | V | V | H | V | REQ-IMG-002 |
| C-11 | Frame-drop / rate indicator | — | V | V | H | V | V | V | H | V | REQ-IMG-012 |
| C-12 | Video-plane (SFU) connection indicator | — | V | V | V | V | V | V | V | V | IF-CM-012 |

**Note on C-06…C-08:** these rows are subject to G1 per camera. A camera that cannot set frame rate
renders no C-08 control **for that camera**, while another camera in the same GUI may render it
(`REQ-CAM-007`).

### 7.4 Illumination

| # | GUI function | Lock | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L-01 | Light source on/off | `illumination` | H | D | A | A | A | D | D | A | REQ-LGT-001 |
| L-02 | Light source power (slider + entry) | `illumination` | H | D | A | A | A | D | D | A | REQ-LGT-002 |
| L-03 | Light source identity / wavelength | — | V | V | V | V | V | V | V | V | REQ-LGT-005 |
| L-04 | Emission indicator | — | V | V | V | V | V | V | V | V | NFR-SAF-003 |

**L-02 is additionally gated by G9:** hidden whenever the corresponding source is off
(`REQ-LGT-003`). This is the reference example of a value gate.

### 7.5 Stage

| # | GUI function | Lock | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| T-01 | Jog / step buttons (± per axis) | `stage_position` | H | D | A | A | A | D | D | A | REQ-STG-001 |
| T-02 | Position display (X/Y/Z) | — | V | V | V | V | V | V | V | V | REQ-STG-006 |
| T-03 | Absolute position entry + confirm | `stage_position` | H | D | A | A | D | D | D | A | REQ-STG-009 |
| T-04 | Home (separate menu) | `stage_position` | H | D | C | C | D | D | D | D | REQ-STG-004/005 |
| T-05 | Stop motion | `stage_position` | H | D | H | H | A | H | H | A | REQ-STG-011 |
| T-06 | Jog ↔ step mode switch | `stage_position` | H | D | A | A | D | D | D | A | REQ-STG-008 |
| T-07 | Step size (separate menu) | `stage_position` | H | D | A | A | D | D | D | A | REQ-STG-007 |
| T-08 | Velocity (separate menu) | `stage_position` | H | D | A | A | D | D | D | D | REQ-STG-007 |
| T-09 | Acceleration (separate menu) | `stage_position` | H | D | A | A | D | D | D | D | REQ-STG-007 |
| T-10 | Jerk (separate menu) | `stage_position` | H | D | A | A | D | D | D | D | REQ-STG-007 |
| T-11 | Travel-limit display | — | V | V | V | V | V | V | V | V | REQ-STG-010 |

**Per-axis G1:** an axis the controller does not expose renders no T-01 control for that axis
(`REQ-STG-003`). Likewise T-08…T-10 appear only for parameters the controller actually supports
(`REQ-STG-007`) — a controller without jerk control shows no jerk field, ever.

### 7.6 Optics

| # | GUI function | Lock | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| O-01 | Objective selection | `objective` | H | D | A | C | D | D | D | D | REQ-OPT-001 |
| O-02 | Filter selection | `filter_bank` | H | D | A | A | A | D | D | D | REQ-OPT-002 |
| O-03 | Rotator control | ***UNCLEAR*** `OP-012` | H | D | A | A | A | D | D | D | REQ-OPT-003 |
| O-04 | Light-path view | — | V | V | V | V | V | V | V | V | REQ-OPT-004 |

**O-01 is `C` in M3:** changing the objective during live view abruptly changes magnification, focus
and field of view. It is permitted, but confirmed.
**O-01/O-02 are `D` in M7:** calibration is objective- and filter-specific; changing either mid-run
invalidates the transform.

### 7.7 Procedures

| # | GUI function | Locks | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P-01 | Z-scan — configure | `stage_position`,`camera_parameters` | H | D | A | A | D | D | D | D | REQ-PRC-001 |
| P-02 | Z-scan — start | as P-01 | H | D | A | A | D | D | D | D | REQ-PRC-001 |
| P-03 | Autofocus — select measure | `camera_parameters` | H | D | A | A | D | D | D | D | REQ-PRC-003 |
| P-04 | Autofocus — start | `stage_position`,`camera_parameters` | H | D | A | A | D | D | D | D | REQ-PRC-003 |
| P-05 | Focus lock on/off | `stage_position` | H | D | A | A | D | D | D | D | REQ-PRC-005 |
| P-06 | Overview image — start | `stage_position`,`camera_parameters` | H | D | A | A | D | D | D | D | REQ-PRC-007 |
| P-07 | Calibration — manual mode | `stage_position`,`objective` | H | D | A | D | D | D | D | A | REQ-PRC-011 |
| P-08 | Calibration — automatic mode | `stage_position`,`objective` | H | D | A | D | D | D | D | H | REQ-PRC-011 |
| P-09 | Calibration — set landmark | `stage_position` | H | D | H | H | H | H | H | A | REQ-PRC-009 |
| P-10 | Calibration — accept / reject result | `objective` | H | D | H | H | H | H | H | A | REQ-PRC-012 |
| P-11 | XY stitching — configure & start | `stage_position`,`camera_parameters` | H | D | A | A | D | D | D | D | REQ-PRC-014 |
| P-12 | Time series — configure & start | `camera_parameters` | H | D | A | A | D | D | D | D | REQ-PRC-017 |
| P-13 | Sample-area definition | `stage_position` | H | D | A | A | D | D | D | D | REQ-PRC-018 |
| P-14 | Sample-area fine adjustment (power-up) | `stage_position` | H | D | A | D | D | D | D | D | REQ-PRC-019 |
| P-15 | Abort running procedure | — | H | D | H | H | H | A | D | A | REQ-PRC-020 |
| P-16 | Procedure progress display | — | V | V | H | H | H | V | V | V | REQ-PRC-021 |

**P-01…P-14 are `D`, not `H`, in M5.** A user who cannot start a second Z-scan while the first is
running must still be able to see that the function exists — per `INV-004`, the restriction is a
property of the moment.

### 7.8 Data and history

| # | GUI function | Lock | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| X-01 | Acquired-data viewer | — | V | V | V | V | V | V | V | V | REQ-DAT-001 |
| X-02 | Export / download dataset | `io` | H | A | A | A | A | A | A | A | REQ-DAT-006 |
| X-03 | Clear acquired data | `expanse_state` | H | D | C | D | D | D | D | D | REQ-DAT-005 |
| X-04 | Browse historical states | — | V | V | V | V | V | V | V | V | REQ-HIS-001 |
| X-05 | Re-apply a historical state | all device locks | H | D | C | D | D | D | D | D | REQ-HIS-003 |
| X-06 | Storage-capacity indicator | — | V | V | V | V | V | V | V | V | REQ-DAT-008 |

**X-02 is `A` in M1:** downloading data does not command the instrument, so an observer may do it.
This is the only device-adjacent function an observer can act on — confirm against `OP-004`.
**X-05 is `C` and ***UNCLEAR***:** re-applying a state may switch lasers on. Blocked on `OP-008` and
`OP-013`.

### 7.9 Diagnostics

| # | GUI function | Lock | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G-01 | Log viewer | — | V | A | A | A | A | A | A | A | REQ-LOG-001 |
| G-02 | Log level selection | — | H | D | A | A | A | A | A | A | REQ-LOG-004 |
| G-03 | Settings view (read) | — | V | V | V | V | V | V | V | V | REQ-DAT-002 |
| G-04 | Settings edit | — | H | D | C | D | D | D | D | D | REQ-DAT-002 |
| G-05 | Error / notification area | — | V | V | V | V | V | V | V | V | REQ-LOG-005 |

---

## 8. Capability keys

G1 requires the backend to state, per device instance, which functions it supports. This is the
capability descriptor of `REQ-DEV-003`. Minimum key set implied by the matrix:

| Subsystem | Capability keys |
|---|---|
| Camera | `exposure`, `gain`, `framerate`, `channel_weighting`, `roi`, `binning`, `trigger` — each with `readable`, `writable`, `min`, `max`, `step`, `unit` |
| Stage | per axis: `present`, `jog`, `absolute`, `home`, `velocity`, `acceleration`, `jerk`, `limit_min`, `limit_max`, `unit` |
| Illumination | per source: `switchable`, `power`, `min`, `max`, `unit`, `wavelength` |
| Objective | `slots`, `switchable`, per slot: `magnification`, `na`, `pixel_size` |
| Filter bank | per bank: `slots`, `switchable`, per slot: `name`, `band` |
| Rotator | `axes`, `absolute`, `continuous`, `min`, `max`, `unit` — ***UNCLEAR***, `OP-014` |

**INV-009** — The capability descriptor is the **only** source for G1. The frontend shall not infer
support from a device name, model string or hardcoded table.

**INV-010** — A capability descriptor shall report the *device's* limits, not the *GUI's* preferences
(`REQ-CAM-008`).

---

## 9. Open points arising from this matrix

| ID | Question | Affected cells |
|---|---|---|
| OP-028 | May the safe-state / stop-all control (S-07) be operated by an **observer** (`auth = observer`)? Physical-safety argument says yes; control-arbitration argument says no. `INV-007` currently says `D` in M1 | S-07 / M1 |
| OP-029 | During a procedure that outlives its user (`REQ-SES-008`), which mode applies — M5 with no holder, or a new mode M8 UNATTENDED? | all M5 cells |
| OP-030 | Is snapshot (C-04) permitted during stage motion (M4)? Currently `D` on image-quality grounds; a user tracking a moving sample may disagree | C-04 / M4 |
| OP-031 | Should M4 MOVING be a distinct mode at all, or is it a per-control lock state? A CAN-bus stage may report motion per axis, allowing Y control while X moves | all M4 cells |
| OP-032 | Are rotators (O-03) covered by the `filter_bank` lock or do they need their own lock in the backend vocabulary? | O-03 |

These are registered in `DOC/OpenPoints.md` §5 with full context and recommendations.

---

## 10. Verification

| Method | What it proves |
|---|---|
| **I** | Every GUI function in the implementation appears as a row here; no row is unimplemented and no control is unlisted |
| **T** | Automated test per row: force the mode, assert the rendered state matches the cell. This matrix is directly executable as a test table |
| **D** | `ACC-04` in `SRS_V1.md` §4.3 — a camera without frame-rate control shows no frame-rate control |

**Recommendation:** generate the frontend gating from `InvariantMatrix.csv` rather than hand-writing
it. The file is already the shape of a lookup table, and the backend already publishes the lock
vocabulary and (once `REQ-DEV-003` exists) the capability descriptors that G1 and G7 need.
