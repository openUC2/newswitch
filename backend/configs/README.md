# Device configuration

newswitch reads **one** YAML file describing every device. The code lives in
`backend/newswitch/config_io/`; this folder holds the files and the generated schema.

| Location | Purpose |
| --- | --- |
| `configs/newswitch-config.yaml` | Static device configuration (example setup); newswitch never writes it |
| `configs/newswitch-config.persistent.yaml` | Persistent configuration: receives every change (git-ignored) |
| `configs/camTest_config.yaml`, `configs/camTest.json` | One simulated uc2_cam_py camera and the base-config overrides to boot it (see "Cameras") |
| `configs/schemas/newswitch-config.schema.yaml` | JSON Schema (Draft 2020-12) as YAML, generated from the dataclasses |
| `newswitch/config_io/devices.py` | One dataclass per device type — the source of truth |
| `newswitch/config_io/values.py` | `PhysVal`, `Trigger`, `Firmware` |
| `newswitch/config_io/connection.py` | Controller connections, see `backend/docs/connection-reference.md` |
| `newswitch/config_io/references.py` | Cross-device checks (stage axes, controller mappings) |
| `newswitch/config_io/config_file.py` | `open_config`, `load_config`, `ConfigFile.apply_firmware` / `save` |
| `newswitch/config_io/adapters.py` | Config dataclasses → manager dataclasses and back |

```bash
cd backend
uv run python -m newswitch.config_io                  # validate + list the configured devices
uv run python -m newswitch.config_io configs/other.yaml  # any other file
uv run python -m newswitch.config_io --export-schema  # regenerate the schema after model changes
```

## Static and persistent file

Both are set in `backend/base_config.yaml`; bare names resolve against this folder
(`config_dir`). On the command line paths are used as given. Only `.yaml`/`.yml` are read.

- `static_config_path` is the initial configuration. **newswitch never writes it.**
- `persistent_config_path` receives every change (runtime values, firmware reports).
- `load_from_static_config_path: true`: the static file is read; on shutdown the persistent
  file is overwritten with it plus the changes.
- `load_from_static_config_path: false`: the persistent file is read and written back in
  place. If it does not exist yet, it is created as a copy of the static file.

## Layout

```yaml
newswitch_version: v1.0.2
devices:
  <key>:                  # identifies the device; name defaults to it
    type: <type>
    name: ...
    ...
```

All keys are snake_case. Device entries may carry further keys newswitch does not know
(e.g. `optikit_dsn_variable`); they are kept in `extras` and never validated. Everything
nested (physical values, `trigger`, `firmware`, `connection`) still rejects unknown keys,
and so does the top level.

| `type` | Dataclass | Manager | Notes |
| --- | --- | --- | --- |
| `lightsource` | `LightsourceConfig` | Illumination | `wavelength: null` = unknown |
| `detector` | `DetectorConfig` | Detector | exposure in ms (manager works in s) |
| `controller` | `ControllerConfig` | — | `connection` + `mapping`; `firmware` optional |
| `stage` | `StageConfig` | Stage | `axes:` direction → key of an `axis` |
| `axis` | `AxisConfig` | Stage axis | one motor; `steps_per_um` required (`null` = servo) |
| `objective` | `ObjectiveConfig` | ObjectiveLens | passive, may sit in a wheel |
| `filter` | `FilterConfig` | Filter | passive, may sit in a wheel |

Every type has `name`, `manufacturer` and `tags`. **Slots** are numbered 1, 2, … per type
in file order.

## Controllers and mapping

Only controllers know how to reach hardware. Their `mapping` assigns the other devices
by key and gives their address on the controller:

```yaml
  my-hat-board-via-can:
    type: controller
    connection:
      protocol: canopen
      transport: {type: can, interface: socketcan, channel: can0, bitrate: 500000}
    mapping:
      top-illumination-LED: {type: canopen-laser, id: 21, subid: 0, pwm_max: 1023}
      my-second-axis: {type: canopen-motor, id: 22}
```

- `type` (free text) is the kind of link on the controller; `id` is the CAN node id or the
  id of the UC2-REST nomenclature; `subid` defaults to 0.
- `pwm_max` is required when `type` contains `laser` or `pwm`, and must be absent otherwise.
- `(id, subid)` is unique per controller, and a device is mapped by one controller only.
- Mapping targets are lightsources, detectors, axes and stages. A key naming no such
  device gives a warning; the file still loads.
- Further keys (e.g. `serial_number`, `index`) are allowed in a mapping entry.
- CAN controllers speak `canopen`. For tests and development there is
  `protocol: simulated` with `transport: {type: simulated}`, which opens no hardware.

## Cameras

A detector mapped by a controller with `protocol: gige-vision` or `usb3-vision` is a camera.
On real hardware (`use_virtual_microscope: false` in `base_config.yaml`) newswitch opens it
through the camera library uc2_cam_py (extra `camera`, `uv sync --extra camera`); the
virtual microscope keeps its simulated detector.

```yaml
  my-usb3-camera-controll:
    type: controller
    connection: {protocol: usb3-vision}
    mapping:
      bigcamera42:
        type: usb3-vision-camera
        id: 0
        serial_number: "00F12345678"   # or index: 0; neither = the first camera
        buffer_size: 16                # images in the ring buffer
        store_image_data: true         # record every acquired image
        vendor_options: {}             # passed to the vendor unchanged

  bigcamera42:
    type: detector
    manufacturer: HikRobot             # the vendor, as uc2_cam_py names it
    exposure_time_ms: {value: 25.0}
    gain_db: {value: 0.0}
    framerate_per_sec: {value: 30.0}
    binning: 1
```

- The vendor is the detector's `manufacturer`, passed on unchanged (case does not matter);
  uc2_cam_py rejects one it does not know and lists the ones it has. Without a
  manufacturer uc2_cam_py's default vendor is used.
- `serial_number` or `index` select the camera (not both); without them the connection's
  `serial_number`/`index` are used. Quote numeric serial numbers.
- `buffer_size`, `store_image_data` and `vendor_options` are optional; unset values keep
  uc2_cam_py's defaults (recording is on by default). Recordings (`.uc2rb` plus a `.json`
  sidecar, one file per acquisition session) go to `camera_recording_dir` of
  `base_config.yaml`.
- After opening, the configured `value`s of exposure, gain and frame rate and the binning are
  written to the camera. The limits the camera reports replace the configured ones in the
  running detector.
- `camTest_config.yaml` is a simulated camera (`manufacturer: Simulated`) for trying it
  out without hardware: `NEWSWITCH_CONFIG=configs/camTest.json uvicorn main:app`.

## Stages, axes and wheels

```yaml
  just-some-boring-stage:
    type: stage
    homing_order: [z, x]      # optional; null = home all axes in parallel
    axes:
      x: my-first-axis
      z: my-second-axis
```

Every `axes` entry must name an existing `axis` device, and an axis belongs to one stage
only; both are errors otherwise. A set `homing_order` lists every direction exactly once.
The directions x, y, z and a of the first stage that is not a wheel feed the stage manager.

A **filter or objective wheel** is a stage with one axis whose `pos` presets name the
filters or objectives; a name that is no such device (`"null"`) is an empty position:

```yaml
  my-filter-wheel-axis:
    type: axis
    steps_per_um: 8.0
    pos:
      preset_vals: {0: "null", 1000: flt-gfp, 2000: flt-tritc}
      selected_index: 0
```

The selected position at startup is `selected_index`; on shutdown the position in use is
written back there (and as `pos.value`).

## Physical values

Exposure, frame rate, gain and the axis values `pos`/`vel`/`acc`/`jerk` are `PhysVal`s:

```yaml
exposure_time_ms: {value: 25.0, min: 0.024, max: 10000.0, inc: 0.001, unit: ms, preset_vals: [1, 10]}
exposure_time_ms: 25.0      # shorthand for {value: 25.0}
exposure_time_ms: {value: 10.0, preset_vals: {1: short, 10: long}, selected_index: 1}
```

Defaults: `min: -.inf`, `max: .inf`, `inc: eps`, `unit: ""`, `preset_vals: null`,
`selected_index: null`. An empty unit means the field's unit (`ms`, `Hz`, `dB`, `um`,
`um/s`, `um/s**2`, `um/s**3`). Another compatible unit is converted (pint), presets
included; an unusable one raises a `ConfigWarning` and the value is dropped. Only `value`
and `selected_index` are changed by the software.

`preset_vals` is a list of numbers or a mapping number -> name (the names are labels, or
device keys on a wheel axis). `selected_index` picks one of them, 0-based in file order; it
must be smaller than the number of presets and stays `null` when there are none. The
detector gets the preset values only (names are not passed on).

## Validation

Loading reports every problem of a stage at once, each with its path:

1. top level (`newswitch_version`, `devices`),
2. jsonschema against the entry's own type (`devices.cam.pixelcount.0: -5 is less than …`,
   `devices.hat.connection.protocol: 'can-bus' is not a known protocol …`),
3. pydantic: defaults, unit conversion, per-device rules (value within min/max, pixel size ≤
   pitch, homing order, unique address per controller, `pwm_max`, …),
4. references: stage axes exist and are axes, nothing is claimed twice, controllers on
   one serial port/bus agree on its settings (errors); mapping keys without a mappable
   device (warning).

## Writing back

`ConfigFile.save()` writes into the persistent file with ruamel.yaml, so comments, order,
flow style and further keys stay; the previous file is kept as `*.bak` (git-ignored).

- Fields marked `x_firmware` in the schema may be reported by the device
  (`ConfigFile.apply_firmware`). For exposure/frame rate/gain only limits are taken over;
  the `value` stays yours.
- A changed field is written; a missing one is added only when it carries information.
  Plain defaults are never written.
- A physical value written as scalar or `null` becomes a mapping.

The app's shutdown hook writes exposure, gain, wheel positions and stage position back.
