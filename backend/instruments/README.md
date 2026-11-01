# Instruments

An instrument is a folder: its description (`microscope.yml`) and the optics files it names.
**newswitch only ever reads it.** What it does is worked out from those when a server starts, ray
tracing with optiland, and kept in memory: nothing is written or cached, so a changed description
only takes a restart. What changes while it runs
(exposure, gain, positions) lives in its states and starts from each variable's `initial`.

```bash
NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just dev   # or its folder
```

`NEWSWITCH_CONFIG` is the only thing that picks a microscope (the root `.env` and the Dockerfile
default it to the fake one). There is no other file: everything about it is in its description.

The description is validated when it is loaded (`Instrument` in `newswitch/instrument/spec.py`,
pydantic dataclasses all the way down): an unknown key, a value of the wrong type or unit, or a missing one stops
the start, and every problem is listed with its path in the file. A quantity is a string with its
unit (`488 nm`, `50 mW`): a bare number is refused where a quantity is meant.

## What the server controls

Everything that can change, and nothing has to be told what it is for. Every variable has a control;
sources and detectors are found from what the cubes hold; and what a variable does is measured by
nudging it (`newswitch/instrument/roles.py`):

| Question | Found from |
| --- | --- |
| What moves the view sideways? | Moves that change where a detector looks, each along its `along` |
| What focuses? | Moves that change how sharp the image is, and not how large |
| What changes the pixel size? | What changes the image's scale |

A routine that needs one of these and finds none or several refuses and lists them, so a second focus
motor stops an autofocus rather than changing which motor it drives. The call can name the one it means.

A detector must tune its `exposure`. Anything else it does not tune is fixed: a PMT has no `binning`.
A tune called `power`, `exposure`, `gain`, `binning` or `frame_rate` is in mW, ms, dB, no unit or Hz.
A source's power goes up to its `max_power`, whatever else its tune states.

## What is on the stage

The sample holder is a cube like any other. Its `simulations` name what can be on it, at least one,
and `settings.simulation` picks which is. That is what a simulated run draws, and what predictions
assume on real hardware too.

```yaml
stage:
  element:
    kind: sample
    simulations:
      gfp-beads:
        fluorophore: {excitation: 488 nm, excitation_width: 20 nm, emission: 515 nm, emission_width: 25 nm, quantum_yield: 0.02}
        transmit: 0.9   # light going straight through (transmitted light)
        reflect: 0.001  # light coming back the way it came (epi)
        pattern: {beads: 3600, radius: 10 um, depth: 4 um}   # what is drawn: random beads
      empty-slide:      # no fluorophore: it emits nothing
        transmit: 0.95
        reflect: 0.001
        pattern: {beads: 0, radius: 10 um, depth: 4 um}
```

The compiler covers every simulation when a server starts. Calibration needs something to correlate: on an empty slide its arithmetic gives a meaningless
pixel size, without an error. An epi source's light is drawn from the beads, also what a sample
reflects: a mirror is predicted right, but drawn dark.

Channels are not declared. A channel is a source whose light gets through the sample to a detector,
which the optics decide: the cubes, `illumination` and `detection` are the same for every sample, and
the sample's numbers say what comes out. Light lost in a detector's read noise is no channel.
`Compiled.channels` lists them for a state, and
`newswitch.tools.check_instrument` prints them per simulation.

## What drives what

A part is an element, and the hardware signals it has: what it sends (`out`, each with the `axes` its
events walk through) and what it accepts (`in`). A cube states them itself, or names an entry of the
components library (`newswitch/instrument/components/`), which states both.

```yaml
camera:
  component: generic-camera-512   # instead of element and signals
  tunes: {...}
stage:
  element: {...}
  signals:
    in: [z]                       # an input named after a move steps that move
```

`drives` connects a sent signal to an accepted one. All of this is checked when the description is
parsed: an unknown component, a signal a part does not have, or a wire that cannot work stops the start.

```yaml
drives:
  - {from: galvo.pixel, to: pmt.sample}             # the scan makes the detector's image
  - {from: laser_488.sync, to: spad.sync}           # arrival times are measured from the pulse
  - {from: camera.frame, to: stage.z, by: 0.5 um}   # each frame steps the stage
  - {from: camera.exposing, to: laser_488.power}    # declared only: nothing executes this yet
```

This is not the `hardware` section: `hardware` says how a name reaches a board, and `drives` what the
parts do to each other, which is also what the compiler reads.

**A logical detector** is a physical detector and what is wired to it, and what it delivers is its
axes. Nothing declares them: they follow from its parts and wires, and
`newswitch.tools.check_instrument` prints them. An acquisition only loops over what a detector does
not deliver.

| Detector | Delivers | From |
| --- | --- | --- |
| A camera | `y, x` | its sensor |
| A color camera | `c, y, x` | its `colors` and sensor |
| A point detector and a scan | `y, x` | the scan |
| The same, timing its photons | `m, y, x` | its `microtime` axis, and the scan |
| Whatever a wire steps the stage for | `z`, and the above | `frame -> stage.z`, with a size per acquisition |

A stack whose z a detector delivers is one sweep per stream: the routine brings the stage to the first
plane, and the wire does the rest. So its plane spacing has to be the wire's `by`, its detector takes
the stack alone, nothing can run between its planes (`z_hooks`), and its planes have to be within the
stage's travel. All of that is refused before anything moves. A live view never steps the stage.

Real hardware refuses every wire for now, and any point detector: cameras run free, with no trigger,
and nothing reads a point detector. All of this runs in simulation only.

## Scanners, light sheets and FLIM

**A point scanner** has a `scanner` with `axes` of `size` and `step` (the optical angle, not the
mirror's, which is half of it), a `pinhole`, and a `point_detector` wired to the scan. The pixel size
follows from a thin-lens ray along the illumination route from the scanner to the sample, so every
edge on it needs a `distance`, every lens its `f`, and the last lens its `na`. A point detector's
`exposure` is the time to scan a frame. The sample is flat, so the pinhole rejects nothing: moving z
only blurs.

**A light sheet** is an illumination edge into the sample with `side: orthogonal` and `along: x` or
`y`, from a lens with an `na`, which alone says how thin the sheet is and how far it reaches (a Gaussian
beam). It only gives a fluorescence channel. The image fades along `along`, and a flat sample goes dark
as it leaves the sheet, which is all a flat sample can show: a stack does not slice through a volume.
Scanned beams, tilted sheets and two sheets for one source are not modelled.

**FLIM** is a `point_detector` with `axes: {microtime: {size, step}}`, a wire to its `sync` from a
source with a `repetition`, a window that fits in a pulse period, and a `lifetime` on every simulation's
fluorophore. An acquisition's dataset then has the axes `(t, c, m, z, y, x)`, and what expects one image
(a live view) gets the sum over `m`. One lifetime holds everywhere, with no instrument response or
pile-up. Detectors with and without `m` cannot share a dataset.

## How it runs

`settings` has every key, with no built-in defaults. Relative folders start at `backend/`, `db_path`
at the working directory.

```yaml
settings:
  simulate: everything               # everything | unwired | nothing, see "How it reaches hardware"
  simulation: gfp-beads              # which of the holder's `simulations` is on it
  db_path: arkitekt_agent.db         # state history and journal of the arkitekt agent
  image_dir: /tmp/newswitch/images   # where the file IO writes
  cache_dir: /tmp/newswitch/cache    # acquired frames; cleared on every start
  camera_recording_dir: data/recordings   # null: uc2_cam_py's own default
  camera_debug_window: true          # real cameras: a window each, acquiring from startup on
```

## What it shows

The bloks live in the description too, as BSX source, and come from nowhere else. Its `ui` section
is what the frontend shows, its `agent_ui` section what Orkestrator shows; a section left out shows
nothing. Each states the `catalog` it is written against and its `bloks` by name, each blok with its
`bsx`, a `description` (a view's starts with its tab label) and `default` for the one shown first.

```yaml
ui:
  catalog: newswitch@6
  bloks:
    view-camera:
      description: 'Camera: the live image of the camera, and acquiring it.'
      default: true
      bsx: |
        <Html>
        <LiveView className="h-full" />
        </Html>
```

A blok the catalog refuses, or one naming an action this microscope does not have, stops the start.

## Which ones there are

| Instrument | What it is |
| --- | --- |
| `fake-microscope` | Two cameras behind a splitter, objectives and a filter wheel, with hidden errors to calibrate away. |
| `dual-camera` | Two cameras, each behind a filter of its own (BP 525/50, BP 625/50), seeing the sample at once. |
| `rgb-camera` | One color camera: every exposure gives an image per color. |
| `cam-test` | One simulated uc2_cam_py camera and nothing else. Without that library, the optics stand in, with a warning. |
| `he-microscope` | White light through an H&E-stained section, onto a color camera, with two objectives. |
| `point-scanner` | A galvo, a pinhole and a PMT: a scan makes the image, of one plane of a volume. |
| `light-sheet` | A sheet from the side, whose positioner the camera's frames step, and a stage for x, y and z. |
| `flim` | A point scanner on a thin section, timing each photon against a pulsed laser. |

All of these simulate everything. Only `cam-test` states hardware that exists; the others' `hardware`
sections are example wiring with made-up boards, axes and `steps_per_um`, and say so, for a real rig
to replace. `fake-microscope` has no actuator on its tube lens, as a board's X, Y, Z and A are taken.

`expected-failures/` holds what must not work, and is tested:

| Folder | What is in it |
| --- | --- |
| `refused/` | A description with one mistake, each with `# expected:` lines saying what must be said about it (`tests/test_expected_failures.py`). A new way of being refused is one more file. |
| `motors/` | A working description whose motor misbehaves: it loses commands, stalls, ends short or drifts. `test.faulty` is a driver only `tests/test_motor_faults.py` registers, so these cannot be run on a server. |

A sample is never flat: its `pattern` states its `depth`, and it is the one law for all of them. What
is seen is the part of the sample nearest the plane the light makes of it: where a sheet is, or else
where the objective focuses. So a thin section, like an H&E slide, leaves focus when the stage moves.
In a volume, the stage carries another plane there, just as sharp: under a sheet, it is the sheet's
distance from focus that says how sharp a plane is, so that is found to be what focuses. A scan
sections a volume by itself, so nothing focuses it, autofocus says so, and a stack sweeps the stage.

| Instrument | Sample | Stage z | What focuses | A stack sweeps |
| --- | --- | --- | --- | --- |
| Widefield, `flim`, `he-microscope` | A thin section | Leaves focus | The stage | The stage |
| `light-sheet` | A volume | Another plane, as sharp | The sheet | The sheet, stepped by the camera; or the stage, named |
| `point-scanner` | A volume | Another plane, as sharp | Nothing | The stage |

Whichever swept, a plane's z in a dataset is where it is in the sample: a sheet sweep has a negative
step, so that a bead has one z. A sheet sweep stays sharp only near the objective's focus, as the
objective stays still; beyond that it takes sweeping the stage, or something following the sheet.

`stains` are what takes up light, of some colors more than others (`center`, `width`, `darkens`), with
a `pattern` of their own:

```yaml
he-section:
  transmit: 0.9
  reflect: 1.0e-6
  pattern: {beads: 0, radius: 5 um, depth: 4 um}
  stains:
    hematoxylin:
      center: 590 nm
      width: 220 nm
      darkens: 0.9
      pattern: {beads: 50000, radius: 4 um, depth: 4 um}
```

The live view shows the mean of a color camera's bands; an acquisition keeps each as a channel.

A color camera states its bands on its sensor, by name:

```yaml
element:
  kind: sensor
  axes: {x: {size: 512, pitch: 6.5 um}, y: {size: 512, pitch: 6.5 um}}
  colors:
    r: {center: 620 nm, width: 70 nm}
    g: {center: 530 nm, width: 70 nm}
    b: {center: 460 nm, width: 70 nm}
```

## Where an acquisition goes

An acquisition is a plan over variables: every channel, on every plane, at every position, every time.

```yaml
channels:
  - {name: gfp, detectors: [camera], set_to: {laser_488.power: 5.0, filter_wheel.slot: 2, camera.exposure: 100.0}}
  - {name: red, detectors: [camera], set_to: {led_625.power: 2.0e-5, filter_wheel.slot: 3, camera.exposure: 400.0}}
positions:
  - {set_to: {stage.x: 0.0, stage.y: 0.0}}
  - {set_to: {stage.x: 500.0, stage.y: 0.0}}
stack: {offsets: [-1.0, -0.5, 0.0, 0.5, 1.0]}  # variable: piezo.z, if several things focus
times: 10
every_s: 60.0
```

A channel sets what it says, and a source it does not name is off. It is stored in mikro (`just mikro`,
then `just dev-mikro`), not in the local cache, and is refused before anything moves when a server has
no mikro. Each position becomes one `ArrayDataset` of `(t, c, z, y, x)`, of the type its sensors
deliver, placed in a stage space shared by this microscope:

- **`c`**: each detector of a channel is a channel of the dataset, and a color camera one per color. A
  detector whose image comes out mirrored (a splitter's reflected arm) is turned back, so every channel
  shows the sample the same way round.
- **Anchors**: `c` has its label and light path; each `t, c, z` has every variable and when the image
  was taken.
- **Placement**: the middle of the image is where the stage was. It counts as validated once every
  detector's light path is calibrated, and as inferred from the optics until then.

An array is regular, so what cannot be one is refused before anything moves: uneven planes, values out
of a variable's range, and detectors that disagree on image size or on pixel size by more than 1% under
what their channels set. Images stay in memory until everything is taken, so an acquisition larger than
the free memory is refused too, and stopping one part way keeps nothing.

## How it reaches hardware

`settings.simulate` says what has no hardware:

| Value | Means |
| --- | --- |
| `everything` | Run a description dry: its `hardware` section opens nothing, apart from a board giving it the UC2 actions on a virtual bus. |
| `unwired` | What the section wires is real, the rest simulated: a real camera beside a simulated stage. Detectors are all real or all simulated, and without `uc2_cam_py` the optics stand in, with a warning. |
| `nothing` | What the section does not wire stops the start, and every such thing is listed. So does a wired camera without `uc2_cam_py`: nothing here shows a rendered image in its place. |

The cubes name their actuators; `hardware` says which driver reaches each, and with what. An actuator
a cube names has to be declared there, or the description is refused; a variable can also name none,
which `simulate: nothing` refuses.

| Key | Means |
| --- | --- |
| `boards.<name>` | The one UC2 board: `transport` (`rest`, `canopen`), `port` or `port_pattern` (neither: autodetect), and any other option of `UC2RestBusConfig` or `UC2CanBusConfig`. |
| `actuators.<name>` | What a variable's `actuator` is: its `driver`, and what that driver takes. |
| `cameras.<cube>` | The camera behind a sensor: `protocol` (`usb3-vision`, `gige-vision`), `vendor` as uc2_cam_py names it, `serial_number` or `index` (neither: the first), `buffer_size`, `store_image_data`, `vendor_options` (passed on unchanged). |

| Driver | Moves | Takes |
| --- | --- | --- |
| `uc2.stepper` | A move, on one axis of the board | `board`, `axis`, `steps_per_um` (required: a wrong guess moves the sample somewhere else) |
| `uc2.laser` | A source's power; its tune must state a `max`, the board's full scale | `board`, `channel`, `pwm_max` |
| `uc2.wheel` | A swap, by moving an axis | `board`, `axis`, `positions` per slot |
| `uc2.turret` | A swap, by the objective changer | `board`, `positions` per slot in steps on a `canopen` board; a `rest` board's firmware keeps its own |

Others can be added: `register_driver` in `newswitch/drivers/base.py`. A wire in `drives` has no driver
that can arm it yet, so one whose ends are real is refused.

### UC2 master over USB serial

Bench-validated 2026-07 against firmware `UC2_canopen_master` V2.0, at 921600 baud. This also covers
the CAN-HAT master: the host talks serial JSON to the master, which bridges to its CAN slaves. Without
a `port` it is autodetected; `require_master` keeps that from picking a slave board. `steps_per_um`
3.2 is 0.3125 um/step, the openUC2 default lead screw: adjust it per machine.

```yaml
hardware:
  boards:
    uc2:
      transport: rest
      port: /dev/cu.SLAB_USBtoUART
      baudrate: 921600
      identity: UC2_Feather
      require_master: true
      steps_per_deg_a: 1.0
      default_speed: 5000.0
      move_timeout_s: 120.0
      home_timeout_s: 30.0
  actuators:
    stg-x: {driver: uc2.stepper, board: uc2, axis: X, steps_per_um: 3.2}
    stg-y: {driver: uc2.stepper, board: uc2, axis: Y, steps_per_um: 3.2}
    stg-z: {driver: uc2.stepper, board: uc2, axis: Z, steps_per_um: 3.2}
    laser_488: {driver: uc2.laser, board: uc2, channel: 1, pwm_max: 1023}
    laser-635: {driver: uc2.laser, board: uc2, channel: 2, pwm_max: 1023}
    led: {driver: uc2.laser, board: uc2, channel: 3, pwm_max: 1023}
```

### CANopen directly

For a SocketCAN Pi setup, `interface: socketcan` with `channel: can0`; for a Waveshare USB-CAN-A
adapter, `interface: waveshare` with the device path as `port`.

```yaml
hardware:
  boards:
    uc2:
      transport: canopen
      interface: socketcan
      channel: can0
      bitrate: 500000
      sdo_timeout: 2.0
      node_x: 11
      node_y: 12
      node_z: 13
      node_a: 14
      node_led: 20
      node_laser: 21
      node_galvo: 30
      steps_per_deg_a: 1.0
      default_speed: 5000.0
      home_speed_steps: 15000
      home_direction: -1
      home_timeout_ms: 20000
      move_timeout_s: 120.0
  actuators:
    stg-x: {driver: uc2.stepper, board: uc2, axis: X, steps_per_um: 3.2}
    stg-y: {driver: uc2.stepper, board: uc2, axis: Y, steps_per_um: 3.2}
    stg-z: {driver: uc2.stepper, board: uc2, axis: Z, steps_per_um: 3.2}
    laser_488: {driver: uc2.laser, board: uc2, channel: 0, pwm_max: 1023}
    laser-635: {driver: uc2.laser, board: uc2, channel: 1, pwm_max: 1023}
    led: {driver: uc2.laser, board: uc2, channel: 2, pwm_max: 1023}
```
