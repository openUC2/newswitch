# Changelog from C.Karras

## Version: 1.2   29.07.26 — DEC-001: live-video transport decided

Documentation only. **No source code was changed.**

### Decision
- **`DEC-001` — the live-video transport is LiveKit / WebRTC / VP8 with an SFU**, per
  `basicRequirements.md` §Image handling. The architecture-freeze rule `CON-ARC-002` is
  **exceptionally waived for this subsystem only**; all other subsystems remain frozen.
- Closes `OP-001` (was the highest-severity CONFLICT in the register).

### Changed — `DOC/SRS_V1.md`
- `IF-CM-005` rewritten from ***UNCLEAR*** to a binding requirement; new `IF-CM-007` … `IF-CM-012`
  specify the I420 conversion, the `capture_frame()` publish path, the SFU deployment, the
  `livekit-client` subscriber, token/room configurability, and independence of the video plane from
  the control plane.
- New `CON-ARC-002-E1` records the freeze exemption explicitly.
- New `NFR-PER-009` (VP8 encode CPU budget); `NFR-PER-003` notes that the latency target now sets the
  encoder operating point.
- System-topology diagram updated: the video plane goes through an SFU, not a direct socket.
- New `ASM-07` (WebRTC needs UDP/ICE reachability), `ASM-08` (software VP8 fits the Pi 5 budget —
  unproven), `DEP-08` confirmed, `DEP-09` (libvpx) added.
- **New Appendix D — Decision log.** All future decisions are recorded there.

### Changed — `DOC/OpenPoints.md`
- `OP-001` marked ✅ CLOSED with a full Decision block; the original analysis is retained per the
  register's own rule.
- `OP-004` (user identity) **raised in priority** — LiveKit rooms are token-authenticated, so video
  now depends on identity.
- `OP-015` (latency target) **raised in priority** — the transport is fixed, the operating point is not.
- `OP-023` annotated: `DEC-001` establishes the precedent that freeze exemptions are granted
  individually, named and recorded.

### Changed — `DOC/MVP_TASKS.md`
- LiveKit removed from the not-in-MVP list; it is now MVP scope.
- **New tasks:** `T-039` (VP8 encode feasibility spike on the Pi 5), `T-047` (deploy the LiveKit
  server), `T-048` (access tokens and room model), `T-049` (frontend `livekit-client` subscriber),
  `T-077` (retire the superseded H.264/Zstd path — *after* the replacement is proven on hardware).
- `T-041` rewritten as a publish pipeline into the SFU; `T-019` reduced to deleting the dead
  live-view URL conventions rather than unifying them.
- Critical path redrawn: three parallel tracks; `T-060` (user identity) pulled forward out of Phase 5.
- Totals: 54 → 59 tasks, ~34 → ~37 person-weeks, ~20–24 → ~21–26 calendar weeks.

### Changed — `DOC/InvariantMatrix.md` / `.csv`
- New row `C-12` — video-plane (SFU) connection indicator, visible in every mode. The video plane can
  now fail independently of the control plane (`IF-CM-012`), and the GUI must say so. 60 → 61 rows.

### Open and now urgent
`OP-015` (latency target) and `OP-004` (user identity) both rose as a direct consequence of this
decision and should be answered before Phase 3 starts. `ASM-08` — software VP8 on a Pi 5 alongside
acquisition — is unproven and is what `T-039` exists to establish, early.

## Version: 1.1   29.07.26 — Requirements engineering pass

Documentation only. **No source code was changed.**

### Added
- `DOC/SRS_STANDARD.md` — research findings on how to set up a proper SRS: standards landscape
  (ISO/IEC/IEEE 29148:2018 as primary, ISO/IEC 25010:2023 for quality attributes), the prescribed SRS
  outline, well-formed-requirement syntax, the nine individual and five set-level requirement quality
  characteristics, requirement attributes, verification methods, and the identifier scheme adopted here.
- `DOC/SRS_V1.md` — draft SRS structured per 29148 clause 9.6. ~180 requirements across functional,
  interface, usability, performance, data, constraint and quality sections, each with priority, source
  and verification method. Includes a verification chapter with ten acceptance scenarios
  (`ACC-01` … `ACC-10`) and a traceability appendix mapping `basicRequirements.md` sections and
  `InitReview.md` findings onto requirement IDs.
- `DOC/OpenPoints.md` — register of 32 open points from the SRS draft, by severity (S1–S3) and status
  (OPEN / ASSUMED / CONFLICT). Three are conflicts between source documents: live-video transport
  (`OP-001`), cache-vs-durable-data (`OP-018`), and the boundary of the architecture freeze (`OP-023`).
- `DOC/InvariantMatrix.md` — GUI operability invariant matrix: eight-gate precedence chain, ten
  invariants, eight operating modes, per-function availability for 60 GUI functions. Normative for the
  rule that only usable controls may be shown.
- `DOC/InvariantMatrix.csv` — spreadsheet-editable companion with the same 60 rows; intended as the
  source for generated frontend gating and as a directly executable test table.
- `DOC/MVP_TASKS.md` — 54 tasks in seven phases from the current tree to an MVP, with dependencies,
  effort estimates, definition of done per task, critical path, an explicit not-in-MVP list, and the
  ten decisions that must precede implementation.

### Notes
- Every ***UNCLEAR*** marker in `SRS_V1.md` has a matching `OP-nnn` entry in `OpenPoints.md`. No open
  question was resolved by invention.
- `DOC/basicRequirements.md` and `DOC/InitReview.md` were read as inputs and left unmodified, per
  `DOC/TODOS.md`.
- Highest-priority decisions before implementation starts: `OP-023` (scope of the architecture freeze)
  and `OP-011` (500 MB/s — per camera or aggregate). Both change what gets built, not just how.

## Version: 1.0   28.07.26
- Initial draft
- serves as original for all future versions
- basic design decisicions, that can be concluded from the current structure shall not be changed. What this means is written in ***General setup rule*** fo the SRS.md
