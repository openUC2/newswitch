# Proposal: one DSN in, one `microscope.yml` out

*2026-11-23, from bringing up `johannes-frame` (an openUC2 FRAME on a Pi). The reference for what a
description is stays [`backend/instruments/README.md`](../backend/instruments/README.md).*

## 1 · What we want

A microscope's optikit design (DSN) is **fully self-contained**: it says everything about that one
microscope. Generating from it gives exactly one `microscope.yml`, with the 3D models next to it:

```
optikit generate johannes-frame.dsn
  →  instruments/johannes-frame/microscope.yml     everything newswitch runs on
  →  instruments/johannes-frame/models/*.glb       what the viewer draws (referenced from it)
```

- **One source:** every fact about the microscope is in the DSN. `microscope.yml` is generated and
  committed, and nobody edits it by hand.
- **Deterministic:** the same DSN gives the same `microscope.yml`, byte for byte. There are no
  timestamps or dict-order effects, and every default is a stated rule.
- **The DSN is design only:** what the microscope is built as, in nominal values (travel, steps per
  µm, where the holder sits in the chassis, focus heights from the optics). Nothing measured on one
  copy goes into it, so one design describes every copy of it.
- **Calibration is newswitch's, stored once:** the small deviation of this copy from its design
  (the holder 48 / 1479 µm off its nominal place, say), kept in newswitch's own store per
  microscope and tied to the design's commit. It is not in the DSN and not in `microscope.yml`.
- Shared parts stay shared: the microscope's DSN *references* `frame-chassis.dsn`, `hat-plus.dsn`
  and the rest, and sets what is particular to it on them (`instantiation.inputs`), as it does today.

### 1.1 · Simulated, then calibrated, then ready

Every microscope goes through three stages, all from the same DSN:

1. **Simulated.** The generated `microscope.yml` runs with `simulate: everything`: stage, camera and
   sample are simulated from the design, the calibration slide included. Every routine runs
   unchanged, the calibration too: it homes, finds the simulated pinhole and centres it. This shows
   the design is consistent (light paths, ranges, the mark where the holder says) before any
   hardware exists.
2. **Calibrated.** On the real hardware the same routines measure where reality differs from the
   design's nominal values: the travel, the holder's mount, the focus per objective, the pixel
   scale, the offset between the objectives. Each stores the deviation from the design in
   newswitch's calibration store; the DSN and `microscope.yml` stay as they are.
3. **Ready.** From then on the microscope runs on those values. Homing gives the same reference after
   every start, so **a calibration is stored once** and holds until something changes: a holder put
   in differently, a part replaced, the design changed (a calibration belongs to one design commit).
   Re-checking is cheap (`calibrate_mount` takes about 40 s); storing it again only happens when it
   moved.

### 1.2 · Coordinates: every detector its own system, one graph

There is no global "image axis". Every **detector has a coordinate system of its own**: a camera
its columns and rows (and its colours), a point detector its scan, a thermometer one point. The
newswitch (and mikro) model ties them together through a **graph**: coordinate systems are nodes,
transformations are edges, and every sample is the hub everything is placed in:

```
detector:camera ──A·(pixel from the sensor's middle) + where it looks──▶ stage:stage ──mount──▶ sample:stage
detector:camera2 ─────────────── its own A, its own placement ─────────▶      ▲                    ▲
image:<id> ── its detector's placement when it was taken ───────────────────────────────────────────┘
slot:A1, well:B3 ── the holder's geometry ──────────────────────────────────────────────────────────┘
```

- **`stage`** is the stage's axes as the design states them, 0 where homing puts it.
- **`sample`** is the holder's frame: the mount says where the holder sits on the stage.
- **`detector:<name>`** goes to the stage by its own matrix A: how large a pixel is on the sample,
  and how the image is turned or mirrored against the stage. Two detectors meet only on the sample,
  never directly.
- **`image:<id>`** keeps its detector's placement from when it was taken, so a point in any image
  is a place to go back to.

**The graph is what gets simulated and then calibrated.** Its *shape* (which nodes and which edges)
follows from the design and never changes. Its *edge values* go through the stages of §1.1:

| Edge | Simulated (from the design) | Calibrated (this copy) |
|---|---|---|
| `detector → stage` (A) | predicted by tracing the optics: nominal pixel size | measured by moving the stage and watching the image (`calibrate_light_path`, also inside `calibrate_mount`): scale, rotation, mirroring |
| `stage → sample` (mount) | the holder's nominal place | the holder's real place (`calibrate_mount`) |
| focus, objective offsets | as the optics predict | measured per objective |
| `slot / well → sample` | the holder's geometry | (not calibrated: the library's) |

So a simulated run and a real one use the **same graph**, with different values on some edges.
Every routine (moving to a well, tiling, autofocus, the calibration itself) works on the graph,
and therefore runs unchanged in the twin and on the microscope. This is also why stage axes are
not image axes (§2.2): the stage's axes are a node of the design, while the turn between image and
stage is a calibrated edge.

## 2 · The DSN's parameters: what it has, what it needs, and why

### 2.1 What a DSN states today

An optikit DSN is a tree of components: primitives with their 3D models, designs referencing
designs, and assemblies with poses. Its `inputs` are the movable degrees of freedom (an actuator's
extension, with units and range). For newswitch, each part carries a `*.newswitch-device.yml`; the
generator merges them into one `_newswitch-config.yml`. By device type, that holds:

| Type | Parameters today |
|---|---|
| **axis** | `steps_per_um`, `pos` (min, max), `vel`, `homing_required`, the DSN input it moves (`optikit_dsn_variable`) |
| **stage** | its axes by name, `homing_order` |
| **controller** | name, maker, its `connections`: per peripheral a protocol and selectors (`id`, `subid`); a transport (`can`: interface, channel, bitrate) |
| **detector** | model, maker, pixel count and pitch, channels, exposure / frame rate / gain ranges, binning, trigger, tags (mono, global shutter, GigE) |
| **light source** | number of channels |
| **optics** | lenses and objectives as static models (STEP/GLB) with poses: geometry, no optical data |

That describes **what is there and how it is wired**. It is not yet enough to run, simulate or
calibrate the microscope.

### 2.2 What it needs in addition, in general

| Type | Needed | Why |
|---|---|---|
| **axis** | signed `steps_per_um` (which way is +); real travel; **homing**: direction, endstop polarity, speed, timeout, back-off; its address on the bus (CAN node, sub-axis) | homing and moving safely without per-microscope code; the sign fixes the stage frame the holder, camera and sample frames are stated in |
| **stage** | which motor axis moves the sample across (x, y) and which along the optical axis; their mechanical directions | names the variables (`stage.x`) and states the stage frame the holders sit in. **Not the image's axes**: see below |
| **controller** | per peripheral its address on that protocol (a CAN node id per satellite, not a serial id); which firmware image (env, release) each board runs | to talk to each node, and to check or flash its firmware on start |
| **light source** | which board and channel drives it, and how (laser channel, LED array); full scale (PWM range → power); spectrum (centre, width), maximum power | to switch it, to set a power in watts, to simulate what it excites |
| **detector** | colour filter (Bayer layout, channel bands), connection (USB3, GigE), readout (QE, noise, bit depth) | to decode images, to simulate it |
| **optics** | per lens and objective: focal length, NA, immersion, working distance; filters and dichroics with their curves; the **light path** (what follows what, epi or transmitted) and distances | pixel size and field of view without calibrating first; which light reaches which detector; simulation |
| **objective changer** | its slots (positions in steps) and which objective sits in each | to swap objectives by name; the offset between them is then only a calibration |
| **holders** | which holders the stage takes, their layout (slots, wells) and **nominal place** on the stage | sample coordinates (`slot:A1`, `well:B3`) from the design; calibration only corrects that place |
| **calibration target** | which calibration slide, in which slot, which mark on it is found, with which light and focus | one generic calibration routine for every design, driven by the description |
| **simulation** | what each sample looks like to the simulator, the calibration slide included | the digital twin: every routine runs before there is hardware (§1.1) |

**Stage axes are not image axes.** The design says how the *stage* moves: which motor is x, which
way is +, how far it goes. It does not say how the *image* lies on the stage: which way a pixel
row runs, whether the image is turned or mirrored, how large a pixel is on the sample. That
depends on how the camera, the mirrors and the tube are put together on this copy, and it is
**calibrated** (`calibrate_light_path`, `calibrate_mount`: move the stage, see where the image
goes). On `johannes-frame`, for instance, the image is turned by about 180° against the stage;
no design value says so, and none should. A nominal pixel size from the optics is fine as a
starting point for the simulation and for the search; the calibrated mapping is what is used.

Three reasons run through the table:

1. **Generation without hand edits.** Every line of `microscope.yml` must follow from the DSN by a
   fixed rule; a fact the DSN lacks is a line someone writes by hand, and then the DSN is no longer
   the source.
2. **Simulation first.** The digital twin needs optics (pixel size, light path), kinematics (axes,
   homing, travel) and samples; without them nothing can be tried before the hardware exists.
3. **Calibration only corrects.** A calibration stores the deviation from a nominal value (the holder
   off its place, focus off its height). There must be a nominal value in the design for it to
   correct; without one, calibration turns into describing the microscope by measuring it.

## 3 · What the DSN generates: `microscope.yml`, part by part

How optikit gets there is up to optikit. What matters is the result: one `microscope.yml` in the
format newswitch already reads (`newswitch/instrument/v0`, validated on load; the reference is
[`backend/instruments/README.md`](../backend/instruments/README.md)). Quantities carry their units
(`488 nm`, `50 mW`); a bare number is refused where a quantity is meant. Abridged from
`johannes-frame`:

```yaml
spec: newswitch/instrument/v0
name: johannes-frame                # the microscope's name: the agent and its data go by it

cubes:                              # every part, by name: what it is, and what about it can change
  laser:
    element: {kind: source, emits: laser, spectrum: {center: 488 nm, width: 2 nm}, max_power: 50 mW}
    tunes:                          # a variable set to a value: power, exposure, gain, ...
      power: {actuator: laser-0, initial: 0 mW, step: 1 mW, max: 50 mW}
  stage:
    element:
      kind: sample                  # where the sample is; simulations: what a simulated run draws
      simulation: gfp-beads
      simulations: {gfp-beads: {...}}
      holders:                      # what can be mounted on the stage (library entries), and where
        slides: {holder: heidstar-4-slide, mount: {x: 0 mm, y: 0 mm}}   # nominal place, from the design
      mounted: slides               # which one is on it at start
      calibration:                  # how the holder's real place is found: slide, slot, mark, settings
        {holder: slides, at: "slot:A1", slide: pinhole-slide, mark: "pinhole:B1", home: [Z, X, Y, A], values: {...}}
    moves:                          # a variable that moves: an axis of the stage
      x: {actuator: stg-x, along: x, initial: 0 um, min: 0 um, max: 105500 um, speed: 5000 um/s}
      z: {actuator: stg-z, along: axis, min: -6500 um, max: 0 um, ...}   # axis: along the optical axis
  objective:
    element: {kind: lens, f: 20 mm, na: 0.25, immersion: air, working_distance: 10 mm}   # placeholder
  dichroic:
    element: {kind: dichroic, curve: lp_500}       # a named curve of the library
  tube:
    element: {kind: lens, f: 200 mm}
  camera:
    element:
      kind: sensor
      axes: {x: {size: 3072, pitch: 2.4 um}, y: {size: 2048, pitch: 2.4 um}}
      colors: {r: {...}, g: {...}, b: {...}}       # a colour sensor: its channels' bands
    tunes:
      exposure: {initial: 100 ms, min: 1 ms, max: 10 s, step: 10 ms}

illumination:                       # the light path from the sources to the sample, element by element
  - {from: laser, to: dichroic}
  - {from: dichroic, via: reflect, to: objective}
  - {from: objective, to: stage, side: epi, field: 500 um}
detection:                          # and from the sample to each detector, with the distances
  - {from: stage, to: objective, distance: focus}
  - {from: objective, to: dichroic, distance: 100 mm}
  - {from: dichroic, via: transmit, to: tube, distance: 30 mm}
  - {from: tube, to: camera, distance: focus}

hardware:                           # how each variable reaches a device
  boards:
    uc2:
      transport: canopen            # how the board is reached: canopen (socketcan) or rest (serial)
      channel: can0
      node_x: 11                    # which CAN node drives what
      homing: {X: {direction: 1, polarity: 1, speed: 20000, timeout_ms: 30000, release: 0}}
      firmware: {release: ..., nodes: {11: {env: ..., version: ...}}}   # what each node must run
  actuators:                        # the names the cubes use, bound to a driver on a board
    stg-x: {driver: uc2.stepper, board: uc2, axis: X, steps_per_um: -3.2}
    laser-0: {driver: uc2.laser, board: uc2, channel: 0, pwm_max: 1023}
  cameras:
    camera: {protocol: usb3-vision, vendor: HikRobot, serial_number: "..."}

settings:                           # how this run behaves
  simulate: unwired                 # everything | unwired (simulate what has no hardware) | nothing
  image_dir: /tmp/newswitch/images

ui:                                 # the views the frontend shows (BSX bloks), optional
  bloks: {view-minimal: {file: ../views/minimal.bsx, default: true}}
```

What each section does:

| Section | What newswitch does with it |
|---|---|
| `cubes` | The parts. Each has an `element` (a source, lens, filter, dichroic, sensor or sample, with its optical data) and the variables it has: `tunes` (set a value), `moves` (an axis), `swaps` (a slot, as in a filter wheel). Every variable gets a control, a range and a start value. |
| `cubes.<sample>` | The stage: `moves` with `along: x / y / axis` and their travel; `holders` with their nominal `mount`; the `calibration` slide. The simulator draws its `simulations`. |
| `illumination`, `detection` | The light paths, one element after the other: which way light goes (`via: reflect / transmit`), epi or transmitted, with distances. From them newswitch traces the rays (optiland): pixel size, field of view, focus, which source reaches which detector. |
| `hardware.boards` | The controller: how it is reached, which node is which, how each axis homes, which firmware each node must run (checked and flashed on start). |
| `hardware.actuators` | Binds each variable's `actuator` name to a driver on a board, with what the driver needs (axis and steps per µm, channel, PWM full scale). |
| `hardware.cameras` | Which physical camera a sensor cube is: protocol, vendor, serial. |
| `settings` | How a run behaves: what to simulate, where files go. |
| `ui` | Which views the frontend shows. |

Everything here is **design**. What a real copy does differently (the image turned on the stage,
the holder off its nominal place, the pixel size as measured) is not written here; it is
calibrated, and kept in newswitch's calibration store (§1).

## 4 · What changes in newswitch

1. **A calibration store**, per microscope and per design (done, 2026-11-25:
   `newswitch/calibration/store.py`, `settings.calibration_dir/<name>.yml`, keyed by
   `Instrument.design_hash`): the holder's offset from its nominal mount and the image-to-stage
   mapping of each light path (which until then were kept in memory only, and lost at every
   start); focus offsets and the offset between the objectives to follow. It is applied on top of
   the description at start. `calibrate_mount` no longer writes the mount into `microscope.yml`.
2. **A CI check** generates every microscope from its DSN and fails on any diff to the committed
   `microscope.yml`. That check is what makes "deterministic" a guarantee.
3. **More calibration routines** beside `calibrate_mount` and `calibrate_light_path`: focus per
   objective, the offset between objectives. Same pattern: measure the deviation from the design,
   store it once.
4. Hand-written `microscope.yml` files keep working for instruments without a DSN.

## 5 · Open questions

- **Generator:** in optikit, a Go tool next to `generate-assm.sh`, or in newswitch, reading the
  DSN. In optikit is cleaner, since it owns the format.
- **Invalidation:** a calibration belongs to a design commit. When the design changes, is it voided
  as a whole, or only where the change touches it (a new holder voids the holder offset, not the
  focus)?
  For now (2026-11-25) as a whole: the store is of one `Instrument.design_hash`, and a store of
  another design is shown stale and not applied.
okay