# Software Requirements Specification — newswitch

**Document ID:** SRS_V1
**Version:** 1.0 (draft)
**Date:** 2026-07-29
**Status:** DRAFT — for review. Contains open points, see `DOC/OpenPoints.md`
**Standard basis:** ISO/IEC/IEEE 29148:2018 clause 9.6 (outline), ISO/IEC 25010:2023 (quality model).
Method described in `DOC/SRS_STANDARD.md`.

---

## Reading rules for this document

| Marker | Meaning |
|---|---|
| **shall** | binding requirement |
| **should** | recommendation / goal, not binding |
| **may** | permitted, optional |
| ***UNCLEAR*** | content that is required in the SRS but cannot yet be specified. Every occurrence has an entry in `DOC/OpenPoints.md` with the ID `OP-nnn` |
| `/D/` | inherited from `basicRequirements.md`: subject to further discussion |

**Requirement identifier scheme**

```
REQ-<AREA>-<nnn>    functional requirement
NFR-<CHAR>-<nnn>    non-functional requirement (CHAR = ISO 25010 characteristic)
CON-<AREA>-<nnn>    design constraint (imposed, not negotiable)
IF-<AREA>-<nnn>     interface requirement
```

**Column legend**

- **P** — Priority: `M` = MVP, `S` = should (v1), `C` = could (later), `W` = out of scope for now
- **Src** — Source: `BR` = `basicRequirements.md`, `IR` = `InitReview.md`, `DER` = derived by analysis
- **V** — Verification method: `I` inspection, `A` analysis, `D` demonstration, `T` test

---

# 1. Introduction

## 1.1 Purpose

This document specifies the requirements for **newswitch**, the control software for an open UC2
microscope. It defines the required functionality, the external interfaces, the performance and
quality attributes, and the constraints imposed on the implementation.

The document is the contract between the requester and the development team, and the basis for
acceptance testing. It describes the **target state**; the *implemented* state as of 2026-07-29 is
described separately in `DOC/InitReview.md` and is referred to here as **Version 1.0**.

## 1.2 Scope

**Product name:** newswitch

**In scope:**

- Backend software controlling microscope hardware (cameras, stages, light sources, objectives,
  filters, rotators) running on a Raspberry Pi 5.
- Frontend web application for operating the microscope from a browser.
- The communication layer between the two.
- Simulated ("virtual") device implementations enabling full operation without hardware.
- Acquisition procedures: Z-scan, autofocus, focus lock, overview imaging, calibration, XY stitching,
  time series.

**Out of scope:**

- Firmware of the UC2 electronics, the ESP32 synchronisation hat and the CAN bus motor controllers.
- Camera vendor SDKs (HIKROBOT, DAHENG) — consumed as third-party binaries.
- Image analysis beyond what is required to drive autofocus, focus lock and calibration.
- Any medical or diagnostic use. newswitch is **not** a medical device; IEC 62304 does not apply.
- User account administration beyond session-level identification (see `OP-004`).

## 1.3 Product overview

### 1.3.1 Product perspective

newswitch is a client–server system. The backend runs on the instrument (Raspberry Pi 5, Docker
container) and owns all hardware. The frontend runs in a browser on an operator machine and holds no
hardware authority of its own — it is a view onto, and a command source for, backend-held state.

```
        Operator machine (browser)                    Instrument (Raspberry Pi 5)
┌──────────────────────────────────────┐      ┌────────────────────────────────────────┐
│  newswitch frontend                  │      │  newswitch backend (Docker)            │
│  React 19 / Vite / TypeScript        │      │  Python, FastAPI, rekuest-next agent   │
│                                      │      │                                        │
│  ┌ control plane  ─────────────────┐ │ WS   │  routines/  ── composite procedures     │
│  │ actions, state sync, locks      │◄┼──────┼─►managers/  ── device implementations   │
│  └─────────────────────────────────┘ │      │  protocols/ ── interfaces + @state      │
│  ┌ video plane ────────────────────┐ │ RTC  │  broadcasters/ ── I420 + LiveKit publish│
│  │ livekit-client → <video>        │◄┼──────┼─  uc2_devices/ ── SDK drivers + native  │
│  └─────────────────────────────────┘ │      │                   ring buffer (C/C++)   │
│  ┌ bulk data plane ────────────────┐ │ HTTP │                                        │
│  │ acquired frames (Zarr chunks)   │◄┼──────┼─  local Zarr store                      │
│  └─────────────────────────────────┘ │      │                                        │
│  ┌ file plane ─────────────────────┐ │ HTTP │                                        │
│  │ exported PNG / TIFF             │◄┼──────┼─  local file store                      │
│  └──────────────────────────────────┘│      └──────────┬─────────────────────────────┘
└──────────────────────────────────────┘                 │ USB3 / GigE │ CAN │ GPIO
                                                    cameras   stages   ESP32 sync hat
```

The video plane is **not** a direct socket between the two halves: the backend publishes into a
**LiveKit server (SFU)**, which fans the stream out to every subscribing client (`IF-CM-005` …
`IF-CM-011`). The SFU is an additional deployed component, co-located with or adjacent to the
instrument.

### 1.3.2 Product functions

Summary of the principal capabilities (detailed in §3.2):

| Group | Capability |
|---|---|
| Session | Connect, show connection health, arbitrate exclusive device control among multiple users |
| Devices | Enumerate, initialise, start and stop the configured devices; report their real capabilities |
| Imaging | Live view of one selected camera; snapshot capture and download; multi-camera operation |
| Camera control | Exposure, gain, frame rate, channel weighting — restricted to what each camera supports |
| Illumination | On/off and power per light source |
| Stage | Jog and step motion in X/Y/Z, homing, absolute positioning, motion parameters |
| Optics | Objective selection, filter selection, rotator control |
| Procedures | Z-scan, autofocus, focus lock, overview image, calibration, XY stitching, time series |
| Data | Persist acquired frames with metadata; export to the operator machine |
| History | Record and revisit historical microscope states |
| Diagnostics | Structured logging at fatal/error/warning/info/debug level |

### 1.3.3 User characteristics

| User class | Description | Implications |
|---|---|---|
| **Operator** | Scientist running experiments. Domain expert in microscopy, not in software. Primary user | GUI must expose only usable controls; physical units and terminology must match lab practice |
| **Developer** | Builds and extends newswitch | Needs simulated devices, structured logs, generated API client |
| **Alpha/beta tester** | Runs the software against real and virtual hardware to find defects | Needs reproducible states, clear error reporting, changelog |
| **Commissioning engineer** | Sets up a new instrument: defines travel limits, calibrates stages | Needs configuration files and manual calibration modes |

The document audience is **developers and alpha/beta testers** (BR §Scope and Context).

### 1.3.4 Limitations

| ID | Limitation |
|---|---|
| LIM-01 | Backend must run on Raspberry Pi 5 class hardware — limited CPU, no discrete GPU. This bounds the achievable software encoding and image processing throughput |
| LIM-02 | Sustained camera data rate up to 500 MB/s (BR §Cameras) exceeds practical Python-level per-frame handling; frame data must remain below the Python layer |
| LIM-03 | The existing architecture and package design **must not be changed** (BR §Base architectural setup) |
| LIM-04 | Motorised stages and lasers can cause physical damage and eye injury; software fail-safe behaviour is required, but software is not a substitute for hardware interlocks |
| LIM-05 | The instrument is assumed to sit on an isolated lab network. Requirements assume no hostile network |

## 1.4 Definitions, acronyms and abbreviations

| Term | Definition |
|---|---|
| **Action** | A backend function published to the frontend via rekuest-next and invocable from the GUI |
| **Capability descriptor** | Machine-readable statement of what a concrete device instance can actually do (see §3.2.2) |
| **Expanse** | The backend's model of the acquired data space (frames and their positions) |
| **Invariant matrix** | Matrix defining which GUI functions are available in which system state; see `DOC/InvariantMatrix.md` |
| **Kube** | Modelled optical element in the light path (objective, filter, dichroic, detector, …) |
| **Lock** | Named backend mutex guarding a state region; lock vocabulary is published to the frontend |
| **Ring buffer** | Native (C/C++) circular frame buffer, one per camera, source for all frame consumers |
| **Slot** | Index identifying a device instance within its subsystem (e.g. detector slot 0) |
| **State** | Backend dataclass, synchronised to the frontend via snapshot + JSON-patch deltas |
| **Virtual device** | Simulated device implementation, selectable instead of hardware |
| CAN | Controller Area Network (openCAN stage control bus) |
| MDA | Multidimensional acquisition |
| SFU | Selective Forwarding Unit (video routing server) |
| UC2 | "You. See. Too." open-source modular microscope project |

---

# 2. References

| Ref | Document |
|---|---|
| [R1] | `DOC/basicRequirements.md` — Software requirements document for newswitch, v0.1, C. Karras, 2026-07-29 |
| [R2] | `DOC/InitReview.md` — newswitch Initial Architecture Review, 2026-07-29 |
| [R3] | `DOC/SRS_STANDARD.md` — SRS method and standards research |
| [R4] | ISO/IEC/IEEE 29148:2018 — Requirements engineering |
| [R5] | ISO/IEC 25010:2023 — SQuaRE product quality model |
| [R6] | openUC2 code base — https://github.com/openUC2 |
| [R7] | UC2_HikPy — https://github.com/openUC2/UC2_HikPy |
| [R8] | `DOC/InvariantMatrix.md` — GUI operability invariant matrix |
| [R9] | `DOC/OpenPoints.md` — register of open questions |

---

# 3. Specific requirements

## 3.1 External interfaces

### 3.1.1 User interfaces

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| IF-UI-001 | The frontend **shall** run in a Chrome browser without installation of native components | M | BR | D |
| IF-UI-002 | The frontend **shall** be operable on Linux (x86), Windows (x86), macOS and Raspberry Pi OS (ARM) | S | BR | D |
| IF-UI-003 | The GUI **shall** display the connection status of every configured device | M | BR | D |
| IF-UI-004 | The GUI **shall** display the connection status between frontend and backend | M | BR | D |
| IF-UI-005 | The GUI **shall** display only those controls that are implemented **and** supported by the currently connected hardware; unsupported controls **shall** be absent, not merely disabled | M | BR | D |
| IF-UI-006 | Every device control **shall** be bidirectionally synchronised: a change made in the GUI is reflected in the device, and a change of device state originating elsewhere is reflected in the GUI within `NFR-PER-004` | M | BR | T |
| IF-UI-007 | Continuous numeric parameters **shall** be settable both by slider and by numerical entry field, with both representations always consistent | M | BR | D |
| IF-UI-008 | Every numeric control **shall** display its physical unit | M | DER | I |
| IF-UI-009 | The GUI **shall** indicate, per control, whether the current user holds the lock required to operate it | S | IR | D |
| IF-UI-010 | GUI availability per system state **shall** follow `DOC/InvariantMatrix.md` [R8] | M | DER | I |
| IF-UI-011 | The GUI language **shall** be English | S | DER | I |

### 3.1.2 Hardware interfaces

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| IF-HW-001 | The backend **shall** support HIKROBOT cameras via the vendor SDK, using the driver layer of [R7] | M | BR | T |
| IF-HW-002 | The backend **shall** support DAHENG cameras via the vendor SDK | S | BR | T |
| IF-HW-003 | The backend **shall** control stages over CAN bus using the openCAN protocol | M | BR | T |
| IF-HW-004 | The backend **shall** control rotators, filter units and the objective changer | S | BR | T |
| IF-HW-005 | Where devices require synchronised timing, synchronisation **shall** be delegated to the ESP32 hat of the Raspberry Pi rather than implemented in host software | S | BR | A |
| IF-HW-006 | ***UNCLEAR*** — the electrical/logical interface of the ESP32 synchronisation hat (trigger lines, protocol, which devices participate) is not specified. See `OP-012` | M | DER | — |
| IF-HW-007 | Serial device access **shall** be configurable (port, baud rate) and **shall not** rely on hardcoded device paths | M | IR §3.1 | I |

### 3.1.3 Software interfaces

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| IF-SW-001 | The backend **shall** publish its action, state and lock schemas over HTTP for build-time client generation | M | IR §4.1 | T |
| IF-SW-002 | The frontend API client **shall** be generated from the running backend; hand-editing generated modules **shall not** occur | M | IR §4.1 | I |
| IF-SW-003 | A drift check **shall** fail the build if the committed generated client differs from the client regenerated against the backend | M | IR §6 | T |
| IF-SW-004 | Acquired image data **shall** be exposed as Zarr v3 chunks over HTTP, not through the control channel | M | IR §2 | T |
| IF-SW-005 | The backend **shall** provide a virtual implementation of every device subsystem, selectable without hardware present | M | BR | T |
| IF-SW-006 | Selection of virtual vs. hardware implementation **shall** be configurable **per subsystem**, not by a single global flag | S | IR §5.2-6 | T |

### 3.1.4 Communication interfaces

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| IF-CM-001 | Control-plane communication **shall** use rekuest-next over WebSocket | M | BR | I |
| IF-CM-002 | Bulk and file transfer **shall** use FastAPI HTTP endpoints | M | BR | I |
| IF-CM-003 | Frontend and backend **shall** each run a watchdog on the connection to the other, and **shall** detect loss of the peer within `NFR-REL-001` | M | BR | T |
| IF-CM-004 | WebSocket endpoint URLs **shall** be derived from one declared WebSocket base configuration value; HTTP and WS bases **shall not** be mixed | M | IR §4.4 | I |
| IF-CM-005 | The live-video transport **shall** be WebRTC, using LiveKit as SFU and client SDK, per the pipeline of [R1] §Image handling. *(Decided 2026-07-29, `OP-001`; supersedes the H.264/Zstd WebSocket transport of Version 1.0)* | M | BR, DEC-001 | D |
| IF-CM-006 | Cross-origin policy **shall** be configurable; the wildcard-origin + credentials combination of Version 1.0 **shall not** be the default in a deployed configuration | S | IR §5.3-18 | I |
| IF-CM-007 | Live frames **shall** be sourced from the camera ring buffer, then decimated, downscaled and converted Mono8 → I420 before encoding | M | BR | T |
| IF-CM-008 | Converted frames **shall** be handed to the LiveKit SDK via `rtc.VideoSource.capture_frame()`; VP8 encoding, congestion control (GCC / transport-cc) and pacing **shall** be performed by the SDK and **shall not** be reimplemented | M | BR | I |
| IF-CM-009 | A LiveKit server **shall** be deployed with the instrument and **shall** fan out one published stream to N subscribing clients | M | BR | D |
| IF-CM-010 | The frontend **shall** subscribe with `livekit-client` and render the received track into a `<video>` element via `srcObject` | M | BR | D |
| IF-CM-011 | LiveKit server address, room naming and access-token issuing **shall** be configurable and **shall not** be hardcoded | M | DER | I |
| IF-CM-012 | Loss of the video plane **shall not** affect the control plane; the GUI **shall** remain operable with the live view unavailable, and **shall** report the video connection state separately | M | DER | T |

## 3.2 Functions

### 3.2.1 Session, connection and control arbitration

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-SES-001 | The backend **shall** accept simultaneous connections from multiple users to one microscope | M | BR | T |
| REQ-SES-002 | At most one connected user **shall** hold device control authority at any time | M | BR | T |
| REQ-SES-003 | Control authority **shall** be granted on a first-come-first-served basis from an ordered list of connected users | M | BR | T |
| REQ-SES-004 | Users without control authority **shall** be able to observe all state and live view, but **shall not** be able to invoke any device-modifying action | M | BR | T |
| REQ-SES-005 | On loss of connection to the controlling user, the GUI of that user **shall** be disabled and **shall** display an explicit statement that control has been lost | M | BR | D |
| REQ-SES-006 | On loss of connection to the controlling user, control authority **shall** pass to the next user in the list | M | BR | T |
| REQ-SES-007 | If no further user remains, the microscope **shall** enter the safe state defined in `REQ-SAF-001` immediately | M | BR | T |
| REQ-SES-008 | `REQ-SES-005` … `REQ-SES-007` **shall not** apply while a long-running experiment (time series, stitching, Z-scan, MDA) is executing; such an experiment **shall** run to completion regardless of user connection state | M | BR | T |
| REQ-SES-009 | On completion of an experiment that outlived its initiating user, the system **shall** enter the safe state if no user is then connected | M | DER | T |
| REQ-SES-010 | The system **shall** identify users ***UNCLEAR*** — no authentication or user-identification mechanism is specified. See `OP-004` | M | DER | — |
| REQ-SES-011 | Control authority **shall** be visible to all connected users, including the identity of the current holder | S | DER | D |
| REQ-SES-012 | A voluntary hand-over of control by the holding user **shall** be possible | C | DER | D |

### 3.2.2 Device lifecycle and capability reporting

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-DEV-001 | The system **shall** implement and start the configured devices at backend start-up | M | BR | T |
| REQ-DEV-002 | The system **shall** report, per device, whether it is present, initialised, and available for use | M | BR | T |
| REQ-DEV-003 | Each device manager **shall** publish a **capability descriptor** enumerating the parameters it actually supports, the settable range and step of each, and whether each is readable, writable, or both | M | DER (BR §Camera settings, §Stages) | T |
| REQ-DEV-004 | The frontend **shall** construct device control panels from the capability descriptor, so that an unsupported parameter is never rendered | M | DER | T |
| REQ-DEV-005 | Failure of one device to initialise **shall not** prevent the remaining devices or the backend from starting | M | DER | T |
| REQ-DEV-006 | The system **shall** release all device handles on shutdown, including camera SDK handles | M | IR §5.2-8 | T |
| REQ-DEV-007 | An import or initialisation failure in a hardware driver **shall not** prevent operation in virtual mode | M | IR §7.1 | T |
| REQ-DEV-008 | A missing or unreadable device settings file at an explicitly configured path **shall** be reported as an error and **shall not** silently yield an empty device set | M | IR §5.3-12 | T |

### 3.2.3 Imaging and live view

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-IMG-001 | The system **shall** support operation of multiple cameras simultaneously | M | BR | T |
| REQ-IMG-002 | The live view **shall** display exactly one camera at a time, selectable by the user | M | BR | D |
| REQ-IMG-003 | Switching the live-view camera **shall not** interrupt acquisition on the other cameras | S | DER | T |
| REQ-IMG-004 | The system **shall** provide a snapshot function capturing the current view of the selected camera | M | BR | D |
| REQ-IMG-005 | A snapshot **shall** be transferred to the operator machine immediately upon capture, without a further user action | M | BR | D |
| REQ-IMG-006 | The snapshot file format, bit depth and embedded metadata **shall** be ***UNCLEAR*** — not specified. See `OP-002` | M | DER | — |
| REQ-IMG-007 | Each camera **shall** feed a dedicated ring buffer that serves as the single source for all frame consumers (live streaming, download, local storage) | M | BR | T |
| REQ-IMG-008 | Frame hand-over from camera to ring buffer **shall** occur at C/C++ level; frame payloads **shall not** traverse the Python layer on the sustained path | M | BR | I, A |
| REQ-IMG-009 | The ring buffer **shall** expose to Python: a settings structure, `read_image`, and `read_latest_image`, each with a flag selecting whether metadata is returned | M | BR | T |
| REQ-IMG-010 | The live-view pipeline **shall** decimate and downscale frames as required to meet the link and client budget, without altering the data written to storage | M | BR | T |
| REQ-IMG-011 | The live acquisition loop **shall** pace itself against the configured exposure time and **shall not** busy-spin when no detector is active | M | IR §5.2-9 | T |
| REQ-IMG-012 | Ring-buffer overrun (producer faster than consumer) **shall** drop the oldest frames and **shall** report the drop count; it **shall not** block acquisition | S | DER | T |

### 3.2.4 Camera settings

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-CAM-001 | The system **shall** expose, per camera, a user-assignable name | M | BR | D |
| REQ-CAM-002 | The system **shall** allow setting exposure time in ms, via slider and numerical entry | M | BR | D |
| REQ-CAM-003 | The system **shall** allow setting gain in dB, via slider and numerical entry | M | BR | D |
| REQ-CAM-004 | The system **shall** allow setting frame rate in 1/s, via slider and numerical entry | M | BR | D |
| REQ-CAM-005 | The system **shall** allow setting channel weighting, affecting the live viewer only and never the stored data | S | BR | T |
| REQ-CAM-006 | The semantics of "channel weighting" **shall** be ***UNCLEAR*** — see `OP-003` | S | DER | — |
| REQ-CAM-007 | A camera parameter that the connected camera does not support **shall not** be rendered in the GUI for that camera | M | BR | D |
| REQ-CAM-008 | Parameter limits (min, max, step) **shall** be taken from the device, not hardcoded in the frontend | M | DER | T |
| REQ-CAM-009 | A rejected parameter value **shall** cause the GUI to revert to the device-reported value and to report the rejection to the user | M | DER | T |

### 3.2.5 Light sources

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-LGT-001 | The system **shall** allow switching each light source on and off | M | BR | D |
| REQ-LGT-002 | The system **shall** allow setting the power of each light source via slider and numerical entry | M | BR | D |
| REQ-LGT-003 | The power control of a light source **shall** be hidden while that source is off | M | BR | D |
| REQ-LGT-004 | Light sources **shall** be switched off when the system enters the safe state | M | DER | T |
| REQ-LGT-005 | The system **shall** display the wavelength/identity of each light source | S | DER | D |
| REQ-LGT-006 | Laser-class light sources **shall** require ***UNCLEAR*** — no interlock, warm-up, or emission-warning requirement is specified. See `OP-013` | M | DER | — |

### 3.2.6 Stages

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-STG-001 | The system **shall** provide directional motion buttons for positive and negative direction of each axis | M | BR | D |
| REQ-STG-002 | The system **shall** support X, Y and Z axes | M | BR | D |
| REQ-STG-003 | Axes that are not usable on the connected hardware **shall not** be rendered | M | BR | D |
| REQ-STG-004 | The system **shall** provide a home function | M | BR | D |
| REQ-STG-005 | The home control **shall not** be placed at the centre of the directional control cluster; it **shall** reside in a separate menu | M | BR | I |
| REQ-STG-006 | The system **shall** display the current position of all axes | M | BR | D |
| REQ-STG-007 | The system **shall** allow setting step size, velocity, acceleration and jerk via numerical entry in a separate menu, restricted to those parameters the controller actually supports | M | BR | D |
| REQ-STG-008 | The system **shall** allow switching between jogging and stepping modes | M | BR | D |
| REQ-STG-009 | The system **shall** accept absolute target positions by numerical entry; on confirmation the respective axis **shall** move to that position | M | BR | T |
| REQ-STG-010 | Stage motion **shall** be confined to the configured travel limits; a commanded position outside the limits **shall** be rejected with a message and **shall not** be executed | M | DER (BR §Algorithms) | T |
| REQ-STG-011 | The system **shall** stop stage motion when entering the safe state | M | DER | T |
| REQ-STG-012 | Stage position updates **shall** be reflected in the GUI within `NFR-PER-004` during motion | M | DER | T |
| REQ-STG-013 | The GUI **shall** apply optimistic position feedback during commanded motion, and **shall** reconcile with the device-reported position on completion | S | IR §3.2 | T |

### 3.2.7 Objectives, filters and further optics

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-OPT-001 | The system **shall** allow selection of the objective by slot | M | BR/IR | D |
| REQ-OPT-002 | The system **shall** allow selection of the filter by slot within each filter bank | M | BR/IR | D |
| REQ-OPT-003 | The system **shall** control rotators | S | BR | T |
| REQ-OPT-004 | The system **shall** display the currently active light path, including objective, filters, dichroics and detector | S | IR §4.3 | D |
| REQ-OPT-005 | Objective change **shall** update the pixel-size metadata used for stage-to-image mapping | M | DER | T |
| REQ-OPT-006 | The number and specification of objective slots, filter slots and rotator axes **shall** be ***UNCLEAR*** — hardware inventory not specified. See `OP-014` | M | DER | — |

### 3.2.8 Procedures

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-PRC-001 | The system **shall** provide a **Z-scan**: move to a series of Z positions and record an image at each, with movement and exposure synchronised | M | BR | T |
| REQ-PRC-002 | The Z-scan **shall** be parameterised by start, stop and step, or by centre, range and step | M | DER | D |
| REQ-PRC-003 | The system **shall** provide **autofocus** with a user-selectable focus measure | M | BR | T |
| REQ-PRC-004 | The available focus measures **shall** be ***UNCLEAR*** — see `OP-005` | M | DER | — |
| REQ-PRC-005 | The system **shall** provide **focus lock**: continuous maintenance of focus during other operations | S | BR | T |
| REQ-PRC-006 | The focus-lock sensing principle and actuator **shall** be ***UNCLEAR*** — see `OP-006` | S | DER | — |
| REQ-PRC-007 | The system **shall** record an **overview image** of the sample | S | BR | D |
| REQ-PRC-008 | The overview image **may** be acquired with a second camera | S | BR | D |
| REQ-PRC-009 | The system **shall** provide **microscope calibration**: move to several points, record landmarks, and derive the stage-to-image transform | M | BR | T |
| REQ-PRC-010 | Calibration **shall** use an affine transform | M | BR | I |
| REQ-PRC-011 | Calibration **shall** offer both a manual and an automatic mode | M | BR | D |
| REQ-PRC-012 | Calibration **shall** report a residual error, and **shall** reject a calibration whose residual exceeds a configured threshold | S | DER | T |
| REQ-PRC-013 | The calibration result **shall** persist across restarts | M | DER | T |
| REQ-PRC-014 | The system **shall** provide an **XY stitching** mode acquiring a tiled region | M | BR | T |
| REQ-PRC-015 | XY stitching **shall** apply focus lock during acquisition | S | BR | T |
| REQ-PRC-016 | Tile overlap and blending method for stitching **shall** be ***UNCLEAR*** — see `OP-007` | M | DER | — |
| REQ-PRC-017 | The system **shall** provide **time series** acquisition at a configurable interval and count/duration | M | BR | T |
| REQ-PRC-018 | The system **shall** support determination of the potential sample area; coarse XY boundaries **shall** be set manually during commissioning and stored in the device `settings.json` | M | BR | T |
| REQ-PRC-019 | Fine adjustment of the sample area **shall** be optionally performed at system power-up | S | BR | D |
| REQ-PRC-020 | Every procedure **shall** be abortable by the controlling user, leaving the system in a defined state | M | DER | T |
| REQ-PRC-021 | Every procedure **shall** report progress (current step / total steps) to all connected users | M | DER | D |
| REQ-PRC-022 | Procedures **shall** acquire the locks of every subsystem they drive, for their whole duration | M | IR §3.2 | T |
| REQ-PRC-023 | A procedure that fails mid-run **shall** report the failure, retain already-acquired data, and return the system to a safe, idle state | M | DER | T |

### 3.2.9 Historical states

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-HIS-001 | The system **shall** retain historical states of the microscope and make them available to the user | M | BR | D |
| REQ-HIS-002 | A historical state **shall** include the full device configuration in force at that time | M | DER | T |
| REQ-HIS-003 | Retention depth, persistence across restart, and whether a historical state can be re-applied to the instrument **shall** be ***UNCLEAR*** — see `OP-008` | M | DER | — |

### 3.2.10 Data management

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-DAT-001 | Acquired frames **shall** be written to a local store with their acquisition metadata (light path, objective, filters, illumination, exposure, gain, stage position, timestamp) | M | IR §3.4 | T |
| REQ-DAT-002 | The base microscope settings **shall** be defined in a single, structured JSON file on the instrument | M | BR | I |
| REQ-DAT-003 | The settings file **shall** carry a schema version | S | DER | I |
| REQ-DAT-004 | Paths to settings and data **shall** be resolved independently of the process working directory | M | IR §5.3-12 | T |
| REQ-DAT-005 | The distinction between volatile cache (cleared on restart) and durable acquired data **shall** be explicit, and durable data **shall not** be deleted on restart | M | IR §3.4 | T |
| REQ-DAT-006 | The system **shall** export acquired data to the operator machine in ***UNCLEAR*** formats — see `OP-002` | M | DER | — |
| REQ-DAT-007 | The storage layer **shall** support multi-channel and volumetric data without a change to its dimensional contract | S | IR §3.4 | T |
| REQ-DAT-008 | Behaviour on exhaustion of instrument storage **shall** be ***UNCLEAR*** — see `OP-009` | M | DER | — |

### 3.2.11 Logging and diagnostics

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-LOG-001 | The backend **shall** provide logging at the levels fatal, error, warning, info and debug | M | BR | D |
| REQ-LOG-002 | The logging facility **shall** be implemented as a tool in the top-level structure of the backend and be usable by every layer | M | BR | I |
| REQ-LOG-003 | Every log record **shall** carry timestamp, level, source module and, where applicable, the user and device concerned | S | DER | I |
| REQ-LOG-004 | The log level **shall** be configurable at start-up without a code change | M | DER | D |
| REQ-LOG-005 | Errors that affect the user **shall** be surfaced in the GUI, not only in the log | M | DER | D |
| REQ-LOG-006 | Changes to the software **shall** be recorded in a changelog | M | BR | I |

### 3.2.12 Safe state

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| REQ-SAF-001 | The system **shall** define a **safe state** in which all light sources are off and all stage motion is stopped | M | DER (BR §Logged in users) | T |
| REQ-SAF-002 | The system **shall** enter the safe state on: loss of the last connected user (outside a running experiment), backend shutdown, and unrecoverable device error | M | BR/DER | T |
| REQ-SAF-003 | Entry into the safe state **shall** be logged at warning level or higher, with the triggering cause | M | DER | T |
| REQ-SAF-004 | Whether the safe state additionally requires stopping cameras, retracting the objective, or homing any axis **shall** be ***UNCLEAR*** — see `OP-010` | M | DER | — |

## 3.3 Usability requirements

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-USA-001 | An operator familiar with microscopy **shall** be able to perform a live view, a stage move and a snapshot without written instructions | M | DER | D |
| NFR-USA-002 | The GUI **shall** never present a control whose activation cannot succeed in the current system state — see `DOC/InvariantMatrix.md` | M | BR | I |
| NFR-USA-003 | The state of every control **shall** be attributable: where a control is unavailable, the GUI **shall** indicate why (no control authority, lock held, device absent, procedure running) | S | DER | D |
| NFR-USA-004 | Destructive or long-running operations **shall** require explicit confirmation | S | DER | D |
| NFR-USA-005 | Terminology and units in the GUI **shall** follow microscopy practice: ms, dB, 1/s, µm | M | DER | I |

## 3.4 Performance requirements

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-PER-001 | The system **shall** sustain a camera data rate of 500 MB/s at the ring buffer without frame loss | M | BR | T |
| NFR-PER-002 | Whether 500 MB/s is per camera or aggregate, and for how long it must be sustained, is ***UNCLEAR*** — see `OP-011` | M | DER | — |
| NFR-PER-003 | Live-view glass-to-glass latency **shall** be ≤ ***UNCLEAR*** ms — no target specified; see `OP-015`. The transport is now fixed (`DEC-001`), but the target still determines the encoder operating point (resolution, frame rate, decimation) | M | DER | — |
| NFR-PER-009 | VP8 encoding of the live view **shall not** consume more than ***UNCLEAR*** % of the Raspberry Pi 5 CPU budget, leaving acquisition unaffected; see `OP-015` and `ASM-08` | M | DEC-001 | T |
| NFR-PER-004 | A device state change **shall** be reflected in the GUI of all connected users within 200 ms of the backend observing it | S | DER | T |
| NFR-PER-005 | A user command **shall** produce visible GUI feedback within 100 ms, independently of command completion time | S | DER | T |
| NFR-PER-006 | The live-view pipeline **shall** degrade by reducing frame rate and resolution, never by growing an unbounded queue | M | DER | T |
| NFR-PER-007 | Backend CPU load with no acquisition running **shall** not exceed 5 % of one core on the target hardware | S | IR §5.2-9 | T |
| NFR-PER-008 | The system **shall** support at least ***UNCLEAR*** concurrent connected users — see `OP-016` | S | DER | — |

## 3.5 Logical database requirements

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-DB-001 | Acquired image data **shall** be stored in a chunked, browser-readable array format supporting partial reads | M | IR §2 | I |
| NFR-DB-002 | Image data and its metadata **shall** be stored together such that a frame cannot be read without its acquisition context | M | DER | T |
| NFR-DB-003 | Instrument configuration **shall** be stored in one structured JSON document, human-readable and version-controlled at the site | M | BR | I |
| NFR-DB-004 | Data retention policy on the instrument **shall** be ***UNCLEAR*** — see `OP-009` | S | DER | — |

## 3.6 Design constraints

These are imposed by [R1] §Base architectural setup and §Development rules. They are **not**
negotiable within this SRS version.

| ID | Constraint | P | Src | V |
|---|---|---|---|---|
| CON-ARC-001 | The system **shall** be split into a backend and a frontend | M | BR | I |
| CON-ARC-002 | The basic design and architecture of the newswitch package present as of 2026-07-28 **shall not** be changed | M | BR | I |
| CON-ARC-002-E1 | **Exemption to CON-ARC-002**, granted 2026-07-29 (`DEC-001`): the live-video transport **may** be replaced by the LiveKit/WebRTC design of `IF-CM-005` … `IF-CM-012`. This is the only exemption in force; all other subsystems remain frozen | M | DEC-001 | I |
| CON-ARC-003 | The backend **shall** be written mostly in Python; image handling **shall** be written in C/C++ | M | BR | I |
| CON-ARC-004 | The backend **shall** be layered: routines → managers → protocols (states) and devices | M | BR | I |
| CON-ARC-005 | The backend **shall** use dependency injection with a protocol-based device abstraction | M | BR | I |
| CON-ARC-006 | The backend **shall** run on a Raspberry Pi 5 in a Docker container | M | BR | D |
| CON-ARC-007 | The frontend **shall** be a React / Vite / TypeScript application | M | BR | I |
| CON-ARC-008 | Communication **shall** be structured after rekuest-next, with FastAPI for lightweight data transfer | M | BR | I |
| CON-ARC-009 | Purely simulated devices **shall** be available for every subsystem | M | BR | T |
| CON-DEV-001 | C/C++ sources of a sub-project **shall** reside in `<subprojectName>/core/src` and `<subprojectName>/core/include` | M | BR | I |
| CON-DEV-002 | C/C++ **shall** be built with CMake | M | BR | I |
| CON-DEV-003 | C/C++ functions **shall** be bound to Python with pybind11 | M | BR | I |
| CON-DEV-004 | Python code **shall** use snake_case; C/C++ code **shall** use camelCase | M | BR | I |
| CON-DEV-005 | `getattr` **shall not** be used in Python code | M | BR | I |
| CON-DEV-006 | Changes **shall** be logged in a changelog | M | BR | I |

## 3.7 Software system attributes

Organised by the nine ISO/IEC 25010:2023 characteristics [R5].

### 3.7.1 Functional suitability

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-FUN-001 | Every action published by the backend **shall** be reachable from the GUI, or **shall** be explicitly documented as internal | S | DER | I |
| NFR-FUN-002 | The virtual microscope **shall** implement the same action set as the hardware microscope, so that any workflow can be rehearsed without hardware | M | BR | T |

### 3.7.2 Reliability

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-REL-001 | Loss of the peer connection **shall** be detected by both watchdogs within 5 s | M | BR/DER | T |
| NFR-REL-002 | The frontend **shall** reconnect automatically with backoff, and **shall** resynchronise full state on reconnection | M | IR §4.2 | T |
| NFR-REL-003 | A running experiment **shall** survive loss of all frontend connections | M | BR | T |
| NFR-REL-004 | The backend **shall** restart cleanly after an abnormal termination, with no leaked device handles | M | IR §5.2-8 | T |
| NFR-REL-005 | Failure of one subsystem **shall not** propagate to unrelated subsystems | M | DER | T |

### 3.7.3 Security

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-SEC-001 | File-serving endpoints **shall** confine every request to the configured base directory; path traversal outside it **shall** be rejected | M | IR §5.2-10 | T |
| NFR-SEC-002 | Allowed origins **shall** be configurable and **shall** default to a closed list in deployed configurations | S | IR §5.3-18 | I |
| NFR-SEC-003 | The authentication and authorisation model **shall** be ***UNCLEAR*** — see `OP-004` | M | DER | — |

### 3.7.4 Maintainability

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-MNT-001 | Device drivers **shall** depend on no framework or transport type | M | IR §3.1 | I |
| NFR-MNT-002 | The composition root **shall** allow a new subsystem to be added without editing positionally-aligned structures in more than one place | S | IR §5.2-5 | I |
| NFR-MNT-003 | No source file **should** exceed 800 lines; files above this **shall** carry a documented reason | C | IR §4.2, §4.3 | I |
| NFR-MNT-004 | Lint and format checks **shall** pass on every commit | M | IR §6 | T |
| NFR-MNT-005 | Documentation **shall not** describe components that are absent from the tree | M | IR §5.1-3 | I |
| NFR-MNT-006 | The backend test suite **shall** be runnable without hardware present | M | IR §5.1 | T |
| NFR-MNT-007 | Dead code **shall** be removed rather than retained | S | IR §5.3-14 | I |

### 3.7.5 Flexibility (portability, scalability)

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-FLX-001 | Adding a new camera vendor **shall** require implementing the driver interface only, with no change to managers, routines or frontend | M | DER | A |
| NFR-FLX-002 | All site-specific values (ports, baud rates, paths, travel limits) **shall** reside in configuration, not in source | M | IR §3.1 | I |
| NFR-FLX-003 | The frontend **shall** operate against a backend on a different host, addressed by configuration | M | DER | D |

### 3.7.6 Interaction capability

Covered by §3.3.

### 3.7.7 Compatibility

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-CMP-001 | The generated frontend client **shall** correspond exactly to the backend schema of the same commit | M | IR §4.1 | T |
| NFR-CMP-002 | Stored data **shall** be readable by standard tooling for the chosen array format without newswitch | S | DER | D |

### 3.7.8 Performance efficiency

Covered by §3.4.

### 3.7.9 Safety

| ID | Requirement | P | Src | V |
|---|---|---|---|---|
| NFR-SAF-001 | Loss of software control **shall** result in the safe state (`REQ-SAF-001`), never in continued unattended motion or emission | M | BR | T |
| NFR-SAF-002 | Commanded stage motion **shall** be bounded by configured soft limits at the backend, independently of any frontend validation | M | DER | T |
| NFR-SAF-003 | The GUI **shall** indicate clearly whenever any light source is emitting | S | DER | D |
| NFR-SAF-004 | Hazard analysis for laser emission and stage motion **shall** be ***UNCLEAR*** — no hazard analysis exists. See `OP-013` | M | DER | — |

## 3.8 Supporting information

The invariant matrix defining GUI operability per system state is maintained separately as
`DOC/InvariantMatrix.md` [R8] and is normative for `IF-UI-005`, `IF-UI-010` and `NFR-USA-002`.

---

# 4. Verification

## 4.1 Verification methods

Per `DOC/SRS_STANDARD.md` §7: **I** inspection, **A** analysis, **D** demonstration, **T** test.
The method for each requirement is given in the **V** column of §3.

## 4.2 Verification levels

| Level | Scope | Environment |
|---|---|---|
| **V1 — Unit** | Individual managers, protocols, ring buffer, client stores | CI, no hardware |
| **V2 — Integration (virtual)** | Full backend + frontend against virtual devices | CI, no hardware |
| **V3 — Integration (hardware)** | Full system against real cameras, stages, light sources | Instrument bench |
| **V4 — Acceptance** | Operator-run scenarios end to end | Instrument, with operator |

## 4.3 Acceptance scenarios

| ID | Scenario | Covers |
|---|---|---|
| ACC-01 | Start backend in virtual mode, connect, live view, change exposure/gain, snapshot, verify file arrives | REQ-DEV-001, REQ-IMG-002/004/005, REQ-CAM-002/003 |
| ACC-02 | Two browsers connect; verify only the first can control; disconnect the first; verify the second gains control | REQ-SES-001…006 |
| ACC-03 | Start a time series; disconnect all users; verify the series completes; verify safe state afterwards | REQ-SES-008/009, REQ-SAF-002 |
| ACC-04 | Connect a camera lacking frame-rate control; verify the frame-rate control is absent from the GUI | IF-UI-005, REQ-CAM-007 |
| ACC-05 | Command a stage position beyond the travel limit; verify rejection and message | REQ-STG-010, NFR-SAF-002 |
| ACC-06 | Run calibration in manual and automatic mode; restart backend; verify calibration persists | REQ-PRC-009…013 |
| ACC-07 | Sustain the specified camera data rate for the specified duration; verify zero frame loss | NFR-PER-001 |
| ACC-08 | Pull the network cable; verify both watchdogs fire, GUI reports loss, safe state entered | IF-CM-003, REQ-SES-005/007, NFR-REL-001 |
| ACC-09 | Run Z-scan and XY stitching; verify data and metadata completeness | REQ-PRC-001, REQ-PRC-014, REQ-DAT-001 |
| ACC-10 | Regenerate the frontend client against the running backend; verify no diff | IF-SW-003, NFR-CMP-001 |

---

# 5. Appendices

## Appendix A — Assumptions and dependencies

| ID | Assumption |
|---|---|
| ASM-01 | The instrument operates on a trusted, isolated laboratory network |
| ASM-02 | Camera vendor SDKs are available and licensed for the target ARM platform |
| ASM-03 | Stage controller firmware exposes the parameters (velocity, acceleration, jerk) referenced in §3.2.6 |
| ASM-04 | The operator machine and the instrument have sufficient network bandwidth for the chosen live-view codec |
| ASM-05 | Only one microscope is controlled by one backend instance |
| ASM-06 | Physical laser safety (enclosure, interlocks, eyewear) is handled outside the software |
| ASM-07 | The network between instrument, LiveKit server and operator machine permits WebRTC media transport (UDP; ICE/STUN as required). If only TCP is permitted, a TURN server becomes an additional dependency |
| ASM-08 | Software VP8 encoding at the target live-view resolution and frame rate fits within the Raspberry Pi 5 CPU budget alongside acquisition. **To be confirmed by measurement** — see `T-041` in `DOC/MVP_TASKS.md` |

| ID | Dependency |
|---|---|
| DEP-01 | rekuest-next — control plane framework |
| DEP-02 | FastAPI / uvicorn |
| DEP-03 | pybind11, CMake, scikit-build-core — native layer |
| DEP-04 | HIKROBOT MVS SDK, DAHENG SDK |
| DEP-05 | Zarr v3 / zarrita |
| DEP-06 | React 19, Vite, react-three-fiber |
| DEP-07 | openUC2 upstream projects [R6], [R7] |
| DEP-08 | **LiveKit server (SFU), LiveKit Python SDK and `livekit-client`** — confirmed by `DEC-001`. A deployed server component, not only a library |
| DEP-09 | libvpx (VP8) encoding on the Raspberry Pi 5 — software encode, no hardware VP8 encoder on this platform |

## Appendix B — Acronyms and abbreviations

See §1.4.

## Appendix C — Traceability

### C.1 basicRequirements.md → SRS

| [R1] section | Requirements |
|---|---|
| General setup rule | CON-ARC-001…009 |
| General GUI features | IF-UI-003…006, IF-UI-010, REQ-HIS-001 |
| Devices | REQ-DEV-001…008, REQ-IMG-001 |
| Imaging | REQ-IMG-002, REQ-IMG-004, REQ-IMG-005 |
| Camera settings | REQ-CAM-001…009 |
| Light sources | REQ-LGT-001…006 |
| Stages | REQ-STG-001…013 |
| Algorithms / Procedures | REQ-PRC-001…023 |
| Backend/Frontend interaction | REQ-SES-001…012, IF-CM-003 |
| Used devices | IF-HW-001…006, NFR-PER-001 |
| Development and debugging rules | REQ-LOG-001…006, CON-DEV-001…006 |
| Base architectural setup | CON-ARC-001…009, REQ-IMG-007…010, IF-CM-005 |

### C.2 InitReview.md findings → SRS

| [R2] finding | Requirement |
|---|---|
| 5.1-1 backend does not import | NFR-MNT-006, REQ-DEV-007 |
| 5.1-2 no concrete camera driver | IF-HW-001, NFR-FUN-002 |
| 5.1-3 native layer gone but referenced | REQ-IMG-007…009, NFR-MNT-005 |
| 5.2-5 composition root | NFR-MNT-002 |
| 5.2-6 partial hardware abstraction | IF-SW-006 |
| 5.2-8 shutdown never called | REQ-DEV-006, NFR-REL-004 |
| 5.2-9 unbounded live loops | REQ-IMG-011, NFR-PER-007 |
| 5.2-10 path traversal | NFR-SEC-001 |
| 5.2-11 live-view URLs | IF-CM-004 |
| 5.3-12 settings path fragility | REQ-DEV-008, REQ-DAT-004 |
| 5.3-15 lint/format regression | NFR-MNT-004 |
| 5.3-18 CORS | NFR-SEC-002, IF-CM-006 |

### C.3 Requirements with unresolved open points

`IF-HW-006`, `REQ-SES-010`, `REQ-IMG-006`, `REQ-CAM-006`, `REQ-LGT-006`, `REQ-OPT-006`,
`REQ-PRC-004`, `REQ-PRC-006`, `REQ-PRC-016`, `REQ-HIS-003`, `REQ-DAT-006`, `REQ-DAT-008`,
`REQ-SAF-004`, `NFR-PER-002`, `NFR-PER-003`, `NFR-PER-008`, `NFR-DB-004`, `NFR-SEC-003`,
`NFR-SAF-004` → see `DOC/OpenPoints.md`.

## Appendix D — Decision log

Decisions taken on open points, in force for this SRS version. Each closes an entry in
`DOC/OpenPoints.md`; the question itself is retained there for the record.

| ID | Date | Decision | Closes | Consequences |
|---|---|---|---|---|
| **DEC-001** | 2026-07-29 | The live-video transport is **LiveKit / WebRTC / VP8** with an SFU, per `basicRequirements.md` §Image handling. The architecture-freeze rule `CON-ARC-002` is **exceptionally waived** for this subsystem only | `OP-001` | `IF-CM-005` … `IF-CM-012` become binding. `CON-ARC-002-E1` records the exemption. The existing H.264/Zstd WebSocket broadcaster is superseded. A LiveKit server becomes a deployed component (`DEP-08`). New assumptions `ASM-07` (UDP/ICE reachability) and `ASM-08` (software VP8 fits the Pi CPU budget) require confirmation |

---

*End of SRS_V1 draft.*
