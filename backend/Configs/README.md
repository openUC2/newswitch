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
one of `connection:` (own link) or `controller: <device_id>` (attached to a controller).

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
