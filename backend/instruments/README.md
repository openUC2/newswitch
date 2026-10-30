# Instruments

An instrument is a folder: its description (`microscope.yml`), the optics files it names, and what
the compiler found (`compiled.json`). **newswitch only ever reads it.** What changes while it runs
(exposure, gain, positions) lives in its states and starts from each variable's `initial`.

```bash
NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just dev   # or its folder
```

`NEWSWITCH_CONFIG` is the only thing that picks a microscope (the root `.env` and the Dockerfile
default it to the fake one). There is no other file: everything about it is in its description.

The description is validated when it is loaded (`Instrument` in `newswitch/instrument/spec.py`,
pydantic dataclasses all the way down): an unknown key, a value of the wrong type or unit, or a missing one stops
the start, and every problem is listed with its path in the file. A quantity is a string with its
unit (`488 nm`, `50 mW`) or a bare number in the unit newswitch keeps it in (nm, mm, um, mW).

## What the server controls

`parts` says what has a control, in which role, and by which slot. Nothing is inferred from the
optics: a sensor or source without a slot is an error, and a swap or a move with no role has no
control and stays at its `initial`.

```yaml
parts:
  stage: stage                       # the cube holding the sample; left out: nothing moves it
  objective: {swap: objective.slot, reference_tube: 200 mm}  # what magnification is stated against
  filters: {swap: filter-wheel.slot}
  sources:                           # by slot, counting from 1
    1: {cube: laser-488, full_intensity: 100.0}  # its intensity runs from 0 to this
  detectors:
    1: {cube: camera-a, frame_rate: 30 Hz}       # how often it streams
```

A source's `power` and a sensor's `exposure`, `gain` and `binning` are tunes every such cube must have.

## How it runs

`settings` has every key, with no built-in defaults. Relative folders start at `backend/`, `db_path`
at the working directory.

```yaml
settings:
  use_virtual_microscope: true       # false: the real hardware of the `hardware` section
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
  catalog: newswitch@2
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

## How it reaches hardware

`settings.use_virtual_microscope` says whether a run is simulated. A simulated
run ignores the `hardware` section apart from a board giving it the UC2 actions, on a virtual bus;
a real one refuses to start until everything with a control is wired.

The cubes name their actuators; `hardware` says what those names are wired to. It is not part of
the digest, so rewiring outdates no compiled table.

| Key | Means |
| --- | --- |
| `boards.<name>` | The one UC2 board: `transport` (`rest`, `canopen`), `port` or `port_pattern` (neither: autodetect), `stage` (options of `UC2StageConfig` but its axes), and any other option of `UC2RestBusConfig` or `UC2CanBusConfig`. |
| `actuators.<name>` | What a variable's `actuator` is: `board`, and `axis` (a stage move, on the axis of its name; a filter wheel), `channel` and `pwm_max` (a source's power), `positions` per slot (a filter wheel, on its axis; an objective changer on a `canopen` board, in steps; a `rest` board's firmware keeps its own). |
| `cameras.<cube>` | The camera behind a sensor: `protocol` (`usb3-vision`, `gige-vision`), `vendor` as uc2_cam_py names it, `serial_number` or `index` (neither: the first), `buffer_size`, `store_image_data`, `vendor_options` (passed on unchanged). |

A tube lens's focus and the like have no control in the server, and need no wire.

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
      steps_per_um_x: 3.2
      steps_per_um_y: 3.2
      steps_per_um_z: 3.2
      steps_per_deg_a: 1.0
      default_speed: 5000.0
      move_timeout_s: 120.0
      home_timeout_s: 30.0
      stage:
        home_axes: [Z, X, Y]
        registered_step_sizes: [10.0, 100.0, 1000.0, 10000.0]
        default_speed: 5000.0
  actuators:
    stg-x: {board: uc2, axis: X}
    stg-y: {board: uc2, axis: Y}
    stg-z: {board: uc2, axis: Z}
    laser-488: {board: uc2, channel: 1, pwm_max: 1023}
    laser-635: {board: uc2, channel: 2, pwm_max: 1023}
    led: {board: uc2, channel: 3, pwm_max: 1023}
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
      steps_per_um_x: 3.2
      steps_per_um_y: 3.2
      steps_per_um_z: 3.2
      steps_per_deg_a: 1.0
      default_speed: 5000.0
      home_speed_steps: 15000
      home_direction: -1
      home_timeout_ms: 20000
      move_timeout_s: 120.0
      stage:
        home_axes: [Z, X, Y]
        registered_step_sizes: [10.0, 100.0, 1000.0, 10000.0]
        default_speed: 5000.0
  actuators:
    stg-x: {board: uc2, axis: X}
    stg-y: {board: uc2, axis: Y}
    stg-z: {board: uc2, axis: Z}
    laser-488: {board: uc2, channel: 0, pwm_max: 1023}
    laser-635: {board: uc2, channel: 1, pwm_max: 1023}
    led: {board: uc2, channel: 2, pwm_max: 1023}
```
