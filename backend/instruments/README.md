# Instruments

An instrument is a folder: its description (`microscope.yml`) and the optics files it names.
**newswitch only ever reads it.** What it does is worked out from those when a server starts, ray
tracing with optiland, and kept in memory: nothing is written or cached, so a changed description
only takes a restart. What changes while it runs
(exposure, gain, positions) lives in its states and starts from each variable's `initial`.

```bash
NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just agent --url <server>   # or its folder
NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just dev                    # FastAPI and the frontend
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

Any lens on the way to a detector, and the sensor itself, can have moves: each is placed where its
moves put it before the route is traced. So a camera on a slide moves where it looks, a tube lens
moved along the axis refocuses, and a camera moved along it can undo what the stage took out of focus.
Across the axis, `x` and `y` are the sensor's, carried back along the light. A flat element (a filter,
a dichroic) moved changes nothing, and what moves on the illumination side is not traced.

A detector must tune its `exposure`. Anything else it does not tune is fixed: a PMT has no `binning`.
A tune called `power`, `exposure`, `gain`, `binning` or `frame_rate` is in mW, ms, dB, no unit or Hz.
A source's power goes up to its `max_power`, whatever else its tune states.

## What is on the stage

The sample holder is a cube like any other. Its `simulations` name what can be on it, at least one,
and its `simulation` says which is. That is what a simulated run draws, and what predictions assume
on real hardware too.

```yaml
stage:
  element:
    kind: sample
    simulation: gfp-beads   # which of its simulations is on it
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

**Several samples**: an instrument may hold more than one, each a cube of `kind: sample` with a
stage of its own (its moves) and light paths of its own (`dual-sample`). Each light detector sees
one sample at a time: the one whose detection route is open under the swaps as they are
(`Instrument.sample_of(detector, state)`), never two at once, and every sample is seen by some
detector, some way the swaps can be set; a source may light several. Each sample is a hub of its own in the coordinate graph (`sample:<cube>`, its stage
`stage:<cube>`, its holder's places `well:<cube>:B3`), with its own mount and mounting; a bare
`sample`, `stage` or `well:B3` in an action means the sample of the detector that looks, or of the
only one, and is refused when it could be either. An acquisition covers every sample its detectors
see: a place on "the sample" is that place on each, each sample sweeps its own focus (a named
`stack.variable` across samples is refused), and each record lands in its own sample's mikro space.
A probe beside one of several samples says which (`at.stage`, `reads.sample`).

**What it is mounted on**: `holders` names what the sample can be mounted on, from the library in
`newswitch/instrument/holders` (`slide-75x25`, `dish-35`, `plate-96`), and where each sits on this
stage: where its top left corner is (`mount: {x, y, rotation}`). `mounted` is the one it starts on.
The sample's frame is then the holder's, in micrometres from that corner, and a plate's wells are
places to go (`move_to` a `well:B3`). What is mounted changes with `mount_holder`: a new sample, with
none of the images taken. Without holders the sample's frame is the stage's. A simulated run draws
the beads on what is mounted (in every well of a plate); `truth.yml` may say it sits beside where its
`mount` says (`mount_offset_um`), which `register_mount` then has to correct.

```yaml
    holders:
      slide: {holder: slide-75x25, mount: {x: -37.5 mm, y: -12.5 mm}}   # its middle on the stage's 0
      plate: {holder: plate-96, mount: {x: -63.88 mm, y: -42.74 mm}}
    mounted: slide
```

**Probes**: a detector of no light is a probe, a cube of its own that says what it `measures`
(a quantity and its unit), where it is, and how a simulated one reads (`model`). It is either `at`
one point of a stage insert, in stage coordinates, so it moves with the stage and the sample (a
thermometer: placed by a BY_DIMENSION part from no axes onto x, y and z; `SpaceState.points` says
where that is on the sample), or it `reads` a grid of what its sample is mounted on: an electrode
array's electrodes, its `y` and `x`, placed straight onto the sample, since they are of the holder
and no stage move finds them. With `sampling`, each reading is a block of samples in time, an
axis `s`. A simulated one at a point reads the air (`model: air`: 22 °C unless `truth.yml` says
`air_temperature_c`), within its `noise`, once a second while live; one on a grid with
`model: spikes` reads the sample's cells, the beads the cameras draw, firing as its simulation's
`electrical` says, each electrode the more the nearer a cell is, plus its noise; while live it
streams how much each electrode swung in the last block, as an image. An acquisition that names a
probe keeps a record of its own, `(t, c, [s], plane, z, y, x)`. No driver reads a real one yet; a
probe whose grid is not on what is mounted reads nothing, and an acquisition of it is refused.

```yaml
  thermometer:
    element:
      kind: probe
      measures: {quantity: temperature, unit: degC}
      at: {x: 30 mm, y: 0 mm}                   # 3 cm from the section
      model: {kind: air, noise: 0.05}
  mea:
    element:
      kind: probe
      measures: {quantity: voltage, unit: uV}
      reads: {grid: electrode}                  # of what the sample is mounted on: an mea-60
      sampling: {rate: 20 kHz, block: 50 ms}
      model: {kind: spikes, noise: 5}
```

**Grids**: a holder names its places in `grids`, each rows and columns a pitch apart (`well` of a
plate, `electrode` of an electrode array). Every place is a system of the coordinate graph,
`<grid>:<cube>:<name>` (`well:stage:B3`, `electrode:stage:D5`), to `move_to`; a bare `electrode:D5`
is of the sample the camera sees.

The compiler covers every simulation when a server starts. Calibration needs something to correlate: on an empty slide its arithmetic gives a meaningless
pixel size, without an error. An epi source's light is drawn from the beads, also what a sample
reflects: a mirror is predicted right, but drawn dark.

Channels are not declared. A channel is a source whose light gets through a sample to a detector,
which the optics decide: the cubes, `illumination` and `detection` are the same for every sample, and
the sample's numbers say what comes out. Light lost in a detector's read noise is no channel.
Channels are found across every way the swaps can be set, each with the swaps that decide it: those
for which another slot makes its light no longer arrive, or come from another sample, or in another
band (a flip mirror, a filter). A swap that changes only how much arrives, an objective, decides
none. `Compiled.channels` lists them, and `newswitch.tools.check_instrument` prints them per
simulation; the acquisition planner offers each as a card, and a channel acquired sets its swaps.

Channel names are inferred too, from the light path alone, never from what is on the sample: the
source's lines, the side its light lands from, whether it is scanned, how much of the source's own
light the detection path lets through (next to none: fluorescence), the band it passes, and whether
the detector is a color one or times its photons. `newswitch/instrument/channel_names.yml` says what
that is called: its rules ("{dye} · {excitation}/{emission}" for what was emitted, "Brightfield
RGB", ...), the dyes known by their excitation and emission windows, and what to add when two
channels would share a name (the detector, then the sample, then the swaps). The code knows none of
these words: edit the file, and every channel of every instrument is named anew.

**Switches**: a `mirror` element reflects everything and lets nothing through; an edge leaving any
element other than a splitter or dichroic `via: reflect` carries no light. So a swap with a mirror
in one slot and an open filter in the other is a flip mirror: what goes on one way, or the other.
Where two paths meet at one, an edge leaving it says which one it carries on, by the cube the light
came in from (`came_from`); without that, what the mirror lets through from one path would be what
it reflects from the other. A detector a switch sends no light to is dark: placed nowhere, its image
only its noise, refused in a channel with a message that says what to switch.

```yaml
  selector:
    swaps:
      slot:
        initial: 1
        slots:
          1: {kind: filter, name: arm a}   # out of the way
          2: {kind: mirror, name: arm b}   # in the way
detection:
  - {from: selector, via: transmit, came_from: filter_wheel, to: port, distance: 30 mm}
  - {from: selector, via: reflect, came_from: objective_b, to: port, distance: 30 mm}
```

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

A detector has no width or height of its own: it delivers **axes**, each measuring a domain of the
sample (`space`, `spectrum`, `microtime`), in the unit of what delivers it. A camera's `y` and `x` are
its sensor's (µm of pitch, and they bin); a scan's are its scanner's (degrees, and they do not bin);
a stepped `z` is its wire's; a color camera's `c` its colors; FLIM's `m` its arrival-time bins. Of
every spatial axis with a size a part can be read (`set_window`): of a camera its region of interest,
of a scan the part scanned, at the same step. Where the pixels are on the sample is not the axes' to
say: the coordinate graph places them (`services/space.py`), so a turned sensor is turned there.

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
pile-up. A detector without `m` beside it keeps a record of its own, without it.

## How it runs

`settings` has every key, with no built-in defaults. Relative folders start at `backend/`, `db_path`
at the working directory.

```yaml
settings:
  simulate: everything               # everything | unwired | nothing, see "How it reaches hardware"
  db_path: arkitekt_agent.db         # state history and journal of the arkitekt agent
  image_dir: /tmp/newswitch/images   # where the file IO writes
  cache_dir: /tmp/newswitch/cache    # acquired frames; cleared on every start
  camera_recording_dir: data/recordings   # null: uc2_cam_py's own default
  camera_debug_window: true          # real cameras: a window each, acquiring from startup on
```

## What it shows

What the newswitch frontend shows lives in the description too, as BSX source, in its `ui` section;
left out, the frontend shows nothing there. It lists its `bloks` by name, each with its `bsx` (or a
`file` beside the description), a `description` (a view's starts with its tab label) and `default`
for the one shown first.

Every blok is one `<Blok kind="agent" context="panel" catalog="...">`, which says the catalog it is
written for. A `ui` blok is written for `newswitch`, the frontend's catalog, and the section's
`catalog` names the version of it the bloks were written against.

What Orkestrator shows (newswitch run as an agent) is not in the description: the agent's bloks ship
with newswitch (`newswitch/infra/ui/agent/`) and are the same on every microscope. A description
with an `agent_ui` section is refused. Those bloks bind variables by name, so a description follows
their convention: the stage is the cube `stage`, moving along `x`, `y` and `z` (`stage.x`, `stage.y`,
`stage.z`).

```yaml
ui:
  catalog: newswitch@10
  bloks:
    view-camera:
      description: 'Camera: the live image of the camera, and acquiring it.'
      default: true
      bsx: |
        <Blok kind="agent" context="panel" catalog="newswitch">
        <LiveView className="h-full" />
        </Blok>
```

A blok the catalog refuses, one written for another catalog, or one naming an action newswitch
does not have, stops the start.

## Which ones there are

| Instrument | What it is |
| --- | --- |
| `fake-microscope` | Two cameras behind a splitter, objectives and a filter wheel, with hidden errors to calibrate away. |
| `dual-camera` | Two cameras, each behind a filter of its own (BP 525/50, BP 625/50), seeing the sample at once. |
| `rgb-camera` | One color camera: every exposure gives an image per color. |
| `cam-test` | One simulated uc2_cam_py camera and nothing else. Without that library, the optics stand in, with a warning. |
| `he-microscope` | White light through an H&E-stained section, onto a color camera, with two objectives, and a thermometer on the stage insert 3 cm from the section. |
| `dual-sample` | Two samples, each on a stage of its own and seen through a light path of its own: GFP beads by fluorescence onto a mono camera, an H&E section in white light onto a color camera, a thermometer beside the section. |
| `switch-microscope` | Two samples, two cameras and two flip mirrors: the selector decides which sample the cameras see, the port which camera gets the light. Each setting that gets light through is a channel of its own. |
| `mea-microscope` | Cells on a 60-electrode array chip, by GFP fluorescence and in white light, while the array records their voltage at 20 kHz: the cells it records are the beads the camera draws. |
| `point-scanner` | A galvo, a pinhole and a PMT: a scan makes the image, of one plane of a volume. |
| `light-sheet` | A sheet from the side, whose positioner the camera's frames step, and a stage for x, y and z. |
| `flim` | A point scanner on a thin section, timing each photon against a pulsed laser. |

Each has a view of its own, as its first: `view.bsx` beside its description where it is not written
inside it, named by `file:` as the shared ones in `views/` are.

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

**When each is taken**: there is one clock, started with the acquisition. A channel is taken as the
plan says (`times`, `every_s`), or on its own: `every_s`, `start_s` and `times` of the channel; one
due at the same instant as another is taken in the same visit to each position. A probe that
samples time can `stream`: it records without pause from the start to the end, in its blocks, into
one record of its own (no position: what it reads stays under the sample wherever the stage goes).
A detector has one record, so one time axis: its channels are all taken at the same times.

```yaml
channels:
  - {name: gfp, detectors: [camera], set_to: {laser_488.power: 20.0}, every_s: 2.0, start_s: 4.0, times: 3}
  - {name: voltage, detectors: [mea], stream: true}
```

Every record's `t` is placed on its sample's clock, in seconds since that mounting (the sample's
`mounted_at`): mikro's sample space is `(t, z, y, x)` with that as its epoch, so a camera's image at
6 s and the array's sample at 6 s are one instant, and so are records of one mounting from other
acquisitions. A probe's own samples, `s`, are an INDEX whose time the registration states.

A channel sets what it says, and a source it does not name is off. It is stored in mikro (`just dev` starts
one), not in the local cache, and is refused before anything moves when a server has
no mikro. Each detector at each position becomes an `ArrayDataset` of its own, along its own axes,
each declared by type, of the type it delivers, placed in the space of the sample it was taken of (one
per mounting, with the mount from this microscope's stage space beside it):

- **Axes**: `t`, then `c`, then what it delivers beside space (`m`, the arrival time), then the plane
  `z`, then its space (`y`, `x`). A camera is `(t, c, z, y, x)`, a FLIM detector `(t, c, m, z, y, x)`,
  a thermometer `(t, c, plane, z, y, x)`: the plane it was read at is an INDEX, and it has one
  position along each of `z, y, x`, its point (what mikro calls a SCALAR dataset).
- **`c`**: each channel of the plan that names the detector, and a color camera one per color.
- **Anchors**: `c` has its label (with the unit, for what is not counted light) and, if light reached
  it, its light path; each `t, c, z` (a thermometer's `t, c, plane`) has every variable and when it
  was taken.
- **Placement**: its detector's route through the coordinate graph, as a BY_DIMENSION that names only
  what has a place: a camera's `(z, y, x)` onto the sample's, the middle of the image where the stage
  was; a thermometer's one position along `z, y, x` onto its point, so that every row reads an axis
  (mikro refuses a row that sends every input to one value); time, channels, arrival times and the
  plane a thermometer was read at nowhere. What a
  camera takes is kept as it took it: a splitter's mirrored arm is mirrored in its placement, not in
  its data. It counts as validated once the detector's light path is calibrated, and as inferred from
  the optics until then.

What cannot be one record is refused before anything moves: uneven planes, values out of a variable's
range, and a detector whose image size, or pixel size by more than 1%, differs between the channels
that name it. A plan with no detector that takes images has no image's middle to bring to a place
(its positions are what they set) and nothing that focuses (its stack names what moves). Images stay in memory until everything is taken, so an acquisition larger than
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
| `uc2.ledarray` | A source's power as the fill of the board's LED array (on a CAN master: the illumination board's RGB ring): its color scaled by the power's share of the `max`; none turns it off | `board`, `r`, `g`, `b` (0-255, default white) |
| `uc2.wheel` | A swap, by moving an axis | `board`, `axis`, `positions` per slot |
| `uc2.turret` | A swap, by the objective changer | `board`, `positions` per slot in steps on a `canopen` board; a `rest` board's firmware keeps its own |

A board with `allow_motion: false` refuses every motion command (moves, homing, the objective
changer) before anything is sent; stopping still works. `instruments/johannes-frame` uses it, with its
stage unwired, while its stage must not move.

On a HAT+ CAN master, `uc2.laser` channels 0-3 reach the laser satellite (node 20) and channel 4 the
illumination board's white LED (node 30); `uc2.ledarray` reaches that board's RGB ring.

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

### What the bus runs: its firmware

A board says which firmware it and its CAN nodes run: a release of
[`youseetoo/uc2-esp32`](https://github.com/youseetoo/uc2-esp32/releases) and the PlatformIO env of
each, which is the image the release publishes (`esp32_<env>.bin`). A node is an env (of the release),
or pinned to a build: `{env, version, release}`, where `version` is exactly what it reports (a release
image reports its tag; a development build `git describe`, `v2026.0.0-beta.4-13-ge86ebf3-t…`) and
`release` where an image of it is fetched from. `instruments/johannes-frame` pins every node to the
build it runs.

On every start on real hardware (not `simulate: everything`) a server reads what the board and each
node run and compares it with this (the background task `keep_firmware`). As `on_start` says, it
flashes what differs (`flash`, the default), only says so in `UC2State.last_error` (`check`), or
does nothing (`off`). Every image is fetched first and its own version, read off its app descriptor,
checked against the pin: an image that is not the pinned build is refused before anything is
written. `just uc2` and the action `update_firmware` do the same on demand.

```yaml
hardware:
  boards:
    uc2:
      transport: rest
      port_pattern: /dev/serial/by-id/usb-Silicon_Labs_CP2102*
      baudrate: 921600
      firmware:
        release: v2026.0.0-beta.4                    # a release (tag)
        on_start: flash                              # flash | check | off
        board: UC2_canopen_master_release            # the board on the port; left out: left alone
        nodes:                                       # CAN node id -> env, or a pinned build
          11: UC2_canopen_slave_motor_release_motX
          12: UC2_canopen_slave_motor_release_motY
          13: UC2_canopen_slave_motor_release_motZ
          30: {env: UC2_canopen_slave_led_release, version: v2026.0.0-beta.4-13-ge86ebf3-t20261102085646-pr133}
        # source: https://github.com/youseetoo/uc2-esp32/releases/download   (the default)
  actuators:
    stg-x: {driver: uc2.stepper, board: uc2, axis: X, steps_per_um: 3.2}
    stg-y: {driver: uc2.stepper, board: uc2, axis: Y, steps_per_um: 3.2}
    stg-z: {driver: uc2.stepper, board: uc2, axis: Z, steps_per_um: 3.2}
    led: {driver: uc2.laser, board: uc2, channel: 3, pwm_max: 1023}
```

```bash
just uc2 scan              # the board on the port and each CAN node: kind, image, version, build, MAC
just uc2 status            # ... against the description; on canopen also where the node map disagrees
just uc2 flash --dry-run   # what would be flashed, how, and from which URL
just uc2 flash             # flash it (asks first); --node 11, --no-board, --force, --full
just uc2 scan --no-description --port /dev/ttyUSB0 --baudrate 921600   # any board, no description
```

- The board on the port (the HAT+ master, a standalone board) is flashed over USB with esptool, the
  app alone at 0x10000: what it stored (NVS: node id, role, positions) is kept. `--full` writes the
  merged image at 0x0 instead, for a blank board; it resets NVS.
- A CAN satellite is updated over CAN, the app alone into its free OTA slot, after which it reboots
  into it (NVS kept): through the master (`rest`), or directly over SDO (`canopen`). It needs the
  bootloader already: flash a blank satellite over its own USB once.
- The order is the documented one: the board first, then each node. A board counts as updated once it
  reports the image of the env and the pinned version.
- `just uc2` opens the port itself: stop whatever holds it first. A running agent does the same with
  the actions `uc2_scan_nodes` and `update_firmware`, which hold the motion, swap, tune and galvo
  locks while the bus is down.
- The documented node ids (docs.openuc2.com) are motor A/X/Y/Z 10-13, laser 20, LED 30, galvo 40,
  GPIO 60; the canopen node map's defaults (`node_a: 14`, `node_led: 20`, `node_laser: 21`,
  `node_galvo: 30`) follow uc2canopen instead. `just uc2 status` says where they disagree with what
  answers.
