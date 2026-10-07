# Device configuration

newswitch reads **one** YAML file describing every device: `newswitch-config.yaml`.
The code lives in `backend/newswitch/config_io/`; this folder holds the file and its
generated schema.

| Location | Purpose |
| --- | --- |
| `Configs/newswitch-config.yaml` | The device configuration (example setup) |
| `Configs/schemas/newswitch-config.schema.yaml` | JSON Schema (Draft 2020-12) as YAML, generated from the dataclasses |
| `newswitch/config_io/devices.py` | One dataclass per device type — the source of truth |
| `newswitch/config_io/values.py` | `PhysVal`, `Trigger`, `Firmware` |
| `newswitch/config_io/connection.py` | Connection models, see `backend/docs/connection-reference.md` |
| `newswitch/config_io/config_file.py` | `load_config`, `ConfigFile.apply_firmware` / `save` |
| `newswitch/config_io/adapters.py` | Config dataclasses → manager dataclasses and back |

```bash
cd backend
uv run python -m newswitch.config_io                  # validate + list the configured devices
uv run python -m newswitch.config_io Configs/other.yaml  # any other file
uv run python -m newswitch.config_io --export-schema  # regenerate the schema after model changes
```

Which file is read is set in `backend/base_config.yaml`: `static_config_path` or, with
`load_from_static_config_path: false`, `persistent_config_path` (created as a copy of the
static file on first start). Bare names there resolve against this folder (`config_dir`);
on the command line paths are used as given. Only `.yaml`/`.yml` are read.

## Layout

```yaml
newswitch_version: v1.0.2
connections:
  main-can:              # optional named connection shared by multiple devices
    protocol: can-bus
    transport: {type: can, interface: socketcan, channel: can0, bitrate: 500000}
devices:
  <device_id>:            # the mapping key IS the device_id (a device_id: key is optional
    type: <type>          # and must then equal the key)
    name: ...
    ...
```

All keys are snake_case. Unknown keys are errors, so typos fail loudly.

| `type` | Dataclass | Manager | Notes |
| --- | --- | --- | --- |
| `lightsource` | `LightsourceConfig` | Illumination | |
| `detector` | `DetectorConfig` | Detector | exposure in ms (manager works in s) |
| `controller` | `ControllerConfig` | — | needs `connection` + `firmware` |
| `stage` | `StageConfig` | Stage | `axes:` list of `AxisConfig` (no `type`) |
| `objective` | `ObjectiveConfig` | ObjectiveLens | passive, sits in a revolver |
| `revolver` | `RevolverConfig` | Filter bank / objective turret | `channels:` device_ids or `null` |
| `filter` | `FilterConfig` | Filter | passive, sits in a revolver |

**Slots** are numbered 1, 2, … per type in file order. A revolver's `channels` maps its
positions to those devices; `selected_channel` is a 0-based position.

**Connection or controller:** lightsources, detectors, revolvers and stages need exactly
one of `connection:` (inline link or name from `connections`) or
`controller: <device_id>` (attached to a controller). Multiple devices can refer
to the same named connection; the bus settings then appear only once.

## Stage axis wiring

`AxisConfig.binding` identifies the motor behind each axis. On a UC2 master reached by
`uc2-rest`, use `{type: uc2-master, stepper_id: 1}` for X, 2 for Y, 3 for Z, and 0 for A.
Those IDs reflect the current serial driver. For direct CANopen, define a named
connection with `protocol: can-bus`, let the stage refer to it, then give each axis a
`{type: canopen-motor, node_id: 11, sub_axis: 0}` binding. `sub_axis` is zero-based and is
0 for boards with one motor. `steps_per_um` converts travel to motor steps.
For a bound rotary axis (`a`, `rx`, `ry`, `rz`), use `steps_per_um: null` and
`steps_per_deg` instead.
The current `pos`/`vel`/`acc`/`jerk` fields still use linear units; rotary
motion values need a separate unit model before they can configure the driver.

If bindings are supplied, every axis in the stage must have one. Duplicate motor
addresses are rejected. `homing_order` controls the mechanically safe sequence;
per-axis `homing_speed_steps`, `homing_direction`, and `homing_timeout_ms` describe
the homing command. See `uc2-canopen-stage.example.yaml` for a direct CAN example.
These fields define the config contract; wiring them into the newer UC2 bus managers
on `main` is separate integration work.
`uc2-serial-stage.example.yaml` is a standalone serial example with explicit
X/Y/Z/A axis names and stepper IDs plus laser channels and the LED matrix;
`uc2-canopen-stage.example.yaml` shows the corresponding direct-CAN addresses.
For a Waveshare USB-CAN-A adapter, set `interface: waveshare` and its USB `port`
under the CAN transport instead of the SocketCAN `channel`.

## Light-source wiring

On a UC2 serial master, a laser uses
`{type: uc2-master-laser, channel: 1, pwm_max: 1023}` and refers to the
master through `controller`. A second laser can use channel 2. The matrix uses
`{type: uc2-master-led-matrix}` because the current `led_fill` / `led_off`
commands do not take a channel. These bindings do not expose any downstream
CAN node IDs behind the serial master.

Laser channels and the LED matrix can refer to the same named `can-bus`
connection as the stage. A laser uses `{type: canopen-laser, node_id: 21, channel: 0, pwm_max: 1023}`;
another channel on that node uses `channel: 1`. The LED matrix uses
`{type: canopen-led-matrix, node_id: 20}`. The `channel` in a laser binding is the
output number in the CAN laser command; the connection's `transport.channel`
names the host CAN interface. A broadband/RGB LED may use `wavelength: 0`.
Duplicate light outputs and a laser/LED collision on one node are rejected.
The example `uc2-canopen-stage.example.yaml` shows the shared bus and all three
light sources. The runtime adapter still needs to consume these bindings and
share the bus client.

## Physical values

Exposure, frame rate, gain and the axis values `pos`/`vel`/`acc`/`jerk` are `PhysVal`s:

```yaml
exposure_time_ms: {value: 25.0, min: 0.024, max: 10000.0, inc: 0.001, unit: ms, preset_vals: [1, 10]}
exposure_time_ms: 25.0      # shorthand for {value: 25.0}
```

Defaults: `min: -.inf`, `max: .inf`, `inc: eps`, `unit: ""`, `preset_vals: []`. An empty unit
means the field's unit (`ms`, `Hz`, `dB`, `um`, `um/s`, `um/s**2`, `um/s**3`). Another
compatible unit is converted (pint); an unusable one raises a `ConfigWarning` and the value
is dropped. Only `value` is changed by the software.

## Validation

`load_config()` reports every problem of a stage at once, each with its path:

1. top level and `device_id` keys,
2. jsonschema against the entry's own type (`devices.cam.pixelcount.0: -5 is less than …`),
3. pydantic: defaults, unit conversion, per-device rules (value within min/max, pixel size ≤
   pitch, unique axis labels, …),
4. references: `controller` exists and is a controller, revolver channels are existing
   objectives *or* filters and each is mounted only once, shared serial ports/buses agree.

## Writing back

`ConfigFile.save()` writes into the original file with ruamel.yaml, so comments, order and
flow style stay; the previous file is kept as `*.bak` (git-ignored).

- Fields marked `x_firmware` in the schema may be reported by the device
  (`ConfigFile.apply_firmware`). For exposure/frame rate/gain only limits are taken over;
  the `value` stays yours.
- A changed field is written; a missing one is added only when it carries information.
  Plain defaults are never written.
- A physical value written as scalar or `null` becomes a mapping.

The app's shutdown hook writes exposure, gain, revolver positions and stage position back.
