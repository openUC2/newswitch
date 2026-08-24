# Device Configuration Schemas

Pydantic-backed schemas for describing devices (sensor geometry, identity,
acquisition settings), plus an importer that reads and validates **JSON or
YAML** files against them.

The code lives in `backend/newswitch/schemas/`; this folder holds the sample
configs and the exported JSON Schemas it works on.

## Where things are

| Location | Purpose |
| --- | --- |
| `newswitch/schemas/camera_schema.py` | The `CameraSchema` model and its sub-models |
| `newswitch/schemas/camera_io.py` | Camera-only loader, validator, writer, schema exporter |
| `newswitch/schemas/bounded.py` | `Bounded`: a numeric parameter with its own min/max/increment |
| `newswitch/schemas/document.py` | File parsing/writing and path resolution |
| `newswitch/schemas/loader.py` | `load_config` / `load_device`: one entry point for any layout |
| `newswitch/config.py` | Which folders configs, schemas, data and logs live in |
| `Configs/schemas/camera.schema.json` | Exported Draft 2020-12 JSON Schema (generated) |
| `Configs/hik_mv_ca023_10um.json` | Example: HIKROBOT MV-CA023-10UM |
| `Configs/hik_mv_ca023_10um.yaml` | Same example in YAML |
| `example_schemas.py` | Runnable tour of the whole API |
| `tests/test_*.py` | Unit tests for each of the modules above |

Dependencies (pydantic, jsonschema, pyyaml, pydantic-settings, platformdirs) are
declared in `backend/pyproject.toml`; `uv sync` installs them.

## Quick start

```bash
cd backend

uv run python example_schemas.py            # the full tour, load -> inspect -> store
uv run python -m newswitch.schemas hik_mv_ca023_10um Devices.yml
# setup: - (v1)
#   [camera     ] hik-mv-ca023-001       1920x1200 px, 19.2x12.0 mm
# setup: openUC2-bench-01 (v1)
#   ...
```

```python
from newswitch.schemas import load_config, load_device, dump_config

# One call for either layout -- always a DeviceRegistry.
reg = load_config("Devices.yml")            # 5 devices
reg = load_config("hik_mv_ca023_10um")      # single-device file -> 1 entry

# One call for a single device, from either kind of file.
cam = load_device("hik_mv_ca023_10um", expect="camera")
cam = load_device("Devices.yml", "hik-mv-ca023-001")

print(cam.sensor_size_mm)                   # (19.2, 12.0)
print(cam.pixelpitch_um.y)                  # 10.0  <- derived from x

dump_config(cam, "data/out.json")           # round-trip to either format
```

The camera-only entry points are still there when a file must be a camera:

```python
from newswitch.schemas import load_camera, dump_camera, export_camera_schema

cam = load_camera("hik_mv_ca023_10um.yaml")
dump_camera(cam, "data/out.yaml")
export_camera_schema()                      # regenerate Configs/schemas/camera.schema.json
```

## Where files are looked up

Paths go through `newswitch.config.Paths`, so callers name a config instead of
building a path:

| Argument | Resolves to |
| --- | --- |
| `"Devices.yml"` | `<config_dir>/Devices.yml` |
| `"Devices"` | the first of `.yaml`, `.yml`, `.json` that exists in `<config_dir>` |
| `"data/out.json"`, `Path("/etc/...")` | used exactly as given |

`config_dir` defaults to this folder and is overridable with
`NEWSWITCH_CONFIG_DIR` (likewise `NEWSWITCH_SCHEMA_DIR`, `NEWSWITCH_DATA_DIR`,
`NEWSWITCH_LOG_DIR`). Writing follows the same rules, so `dump_config(reg,
"backup.yml")` lands in the config directory.

## Single file, several layouts

`load_config()` accepts every shape a device file occurs in and always returns a
`DeviceRegistry`:

| Document | Handling |
| --- | --- |
| mapping with a `devices:` key | multi-device file, as-is |
| a bare list | treated as `devices:` |
| mapping without `devices:` | single device, wrapped into a one-entry registry |

A single-device file without a `type:` key is read as a camera — that is why
`hik_mv_ca023_10um.yaml` works unchanged. Any other device type has to spell out
its `type:`. Errors of a wrapped file are reported without the `devices[0]`
prefix, so they read the way the file looks.

## Required vs. optional

In Pydantic the **default value** decides: a field without a default is
required, a field with a default (including `None`) is optional.
`Optional[X]` alone only makes a field *nullable*, not optional.

**Required:** `name`, `pixelcount.x`, `pixelcount.y`, `pixelpitch_um.x`
Everything else is optional.

> Note on `camera_id` and `exposure_time_ms`: these were required in the
> earlier standalone example. Here they are optional, because this file
> describes a camera *model* — the HIK example carries no serial number, and
> exposure is a runtime setting rather than a device property. Move them back
> to required by simply removing their defaults.

## Field reference

### Tooling

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `$schema` | `str` | `None` | Optional path/URL to `camera.schema.json`. Editors like VS Code use it for autocomplete and inline validation. |

### Identity

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | **required** | Model designation, e.g. `MV-CA023-10UM`. |
| `manufacturer` | `str \| None` | `None` | Vendor name, e.g. `HIK ROBOTICS`. |
| `camera_id` | `str \| None` | `None` | Identifier of the individual physical unit (serial number, device path). |

### Sensor geometry

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `pixelcount.x` | `int > 0` | **required** | Sensor resolution along x, in pixels. |
| `pixelcount.y` | `int > 0` | **required** | Sensor resolution along y, in pixels. |
| `pixelpitch_um.x` | `float > 0` | **required** | Center-to-center pixel distance along x, in µm. |
| `pixelpitch_um.y` | `float > 0` | `= x` | Pitch along y. **Omit it for square pixels** — it is filled with `x`. |
| `pixelsize_um.x` | `float > 0` | `= pixelpitch_um.x` | Photosensitive width per pixel, in µm. Smaller than the pitch when there is dead space between pixels. |
| `pixelsize_um.y` | `float > 0` | `= pixelsize_um.x` | Photosensitive height per pixel. Note the fallback is `pixelsize_um.x`, not `pixelpitch_um.y`. |
| `channels` | `int >= 1` | `1` | Number of color/spectral channels. `1` = monochrome, `3` = RGB. |

If the whole `pixelsize_um` object is omitted, it is copied from
`pixelpitch_um` (both components) — i.e. a fill factor of 1.0.

### Acquisition

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `exposure_time_ms` | `Bounded` | `None` | Integration time in ms. Bare number or `{value, min, max, increment}` — see "Min/max limits" below. |
| `framerate_per_sec` | `Bounded` | `None` | Frame rate in Hz, same two forms. |
| `gain_db` | `Bounded` | `None` | Analog gain in dB, same two forms. |
| `binning` | `1 \| 2 \| 4` | `1` | Symmetric hardware binning factor. |
| `roi` | `[int, int, int, int]` | `None` | Region of interest as `(x, y, width, height)` in pixels. Validated against `pixelcount`. |
| `tags` | `list[str]` | `[]` | Free-form labels, e.g. `monochrome`, `global-shutter`, `gige`. |

### Trigger

Omit the whole `trigger` object for free-running acquisition (default `None`).

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `trigger.type` | `"software" \| "hardware"` | **required within `trigger`** | Trigger source. |
| `trigger.edge` | `"rising" \| "falling"` | `None` | Signal edge the exposure starts on. Hardware triggers only. |
| `trigger.level` | `"high" \| "low"` | `None` | Active level for level-sensitive triggering. Hardware triggers only. |

Setting `edge` or `level` together with `type: software` is rejected — assumed
to be a configuration mistake. Drop the `_check_software` validator in
`camera_schema.py` if your hardware allows that combination.

### Quantum efficiency (commented out)

`quantum_efficiency: Optional[np.ndarray]` is present but disabled in
`camera_schema.py`. A raw `np.ndarray` requires
`ConfigDict(arbitrary_types_allowed=True)` plus a custom serializer, and it
**cannot be expressed in JSON Schema at all**, which would break the
jsonschema validation path and any non-Python consumer.

The JSON-native alternative sketched in the file is a pair of parallel lists:

```python
qe_wavelength_nm: Optional[list[float]] = None
qe_values: Optional[list[float]] = None   # 0.0 .. 1.0, same length
```

Convert to numpy at the call site with `np.asarray(cam.qe_values)`.

## Derived properties

| Property | Description |
| --- | --- |
| `sensor_size_mm` | `(width, height)` in mm, from `pixelcount * pixelpitch_um`. |
| `fill_factor` | `(pixelsize.x * pixelsize.y) / (pitch.x * pitch.y)`, range 0–1. |

## Validation layers

The importer runs two passes, which catch different things:

1. **`jsonschema`** against the exported schema — reports *all* structural
   errors at once (missing keys, wrong types, out-of-range values, unknown
   keys), without building an object.
2. **Pydantic** — coerces types, applies defaults, and runs the cross-field
   rules (`roi` inside `pixelcount`, software-trigger check).

Cross-field rules and derived defaults live **only** in layer 2. A tool that
validates against `camera.schema.json` alone will accept an oversized `roi`
and will not fill in `pixelpitch_um.y`.

```python
from newswitch.schemas import read_document, schema_errors
for err in schema_errors(read_document("broken.yaml")):
    print(err)
# <root>: 'name' is a required property
# pixelpitch_um.x: -1 is less than or equal to the minimum of 0
# binning: 3 is not one of [1, 2, 4]
```

Unknown keys are rejected (`extra="forbid"`) so typos like `pixelcont` fail
loudly instead of being silently ignored. Relax with `extra="ignore"` if you
need forward compatibility with newer config files.

## YAML instead of JSON

Yes — and it needs no separate schema. YAML 1.2 is a superset of JSON, so
`yaml.safe_load` returns the same plain dicts that `json.loads` does, and the
identical `CameraSchema` / `camera.schema.json` validates both.
`load_camera()` picks the parser from the file extension.

Practical differences:

| | JSON | YAML |
| --- | --- | --- |
| Comments | no | yes |
| Human editing | verbose | compact |
| Editor schema support | native via `$schema` | via YAML extension + schema mapping |
| Parser in stdlib | yes | no (`pyyaml`) |
| Ambiguity risk | low | `1.0` vs `1`, `on`/`yes` as booleans, indentation errors |

For hand-maintained device descriptions YAML is usually the better choice, if
only for the comments. Always use `yaml.safe_load`, never `yaml.load` —
the latter can instantiate arbitrary Python objects from the file.

TOML (`tomllib`, stdlib since Python 3.11) is a third option: less ambiguous
than YAML, comments supported, but nested structures are more awkward.

---

# Multi-device files (`Devices.yml`)

A setup usually holds more than cameras. `Devices.yml` is a single file with a
list of mixed device types, each validated against its own schema.

## Additional files

| File | Purpose |
| --- | --- |
| `newswitch/schemas/device_schema.py` | `DeviceBase`, the device types, the `Device` union, `DeviceRegistry` |
| `newswitch/schemas/device_io.py` | Loader and per-type validator |
| `Configs/schemas/devices.schema.json` | Exported Draft 2020-12 schema for the whole registry (generated) |
| `Configs/Devices.yml` | Example setup: 2 cameras, stage, laser, filter wheel |
| `Configs/Devices_broken.yml` | Deliberately broken, to show the error output |

```bash
uv run python -m newswitch.schemas Devices.yml
# setup: openUC2-bench-01 (v1)
#   [camera     ] hik-mv-ca023-001       1920x1200 px, 19.2x12.0 mm
#   [stage      ] stage-xy-001           axes x/y/z
#   ...
```

## The discriminator

Every device carries a `type` field with a `Literal` value. Pydantic uses it to
dispatch each list entry to exactly one model:

```python
Device = Annotated[
    Union[CameraSchema, StageDevice, LaserDevice, FilterWheelDevice],
    Field(discriminator="type"),
]

class DeviceRegistry(BaseModel):
    version: int = 1
    setup: Optional[str] = None
    devices: list[Device] = Field(default_factory=list)
```

Without the discriminator Pydantic tries every branch and reports the failures
of all of them. With it, errors point straight at the field:

```
devices.0.stage.axes.0.travel_um  ->  Input should be greater than 0
```

## Why not validate the whole file with jsonschema directly

A mixed list becomes `oneOf` in JSON Schema. A plain validator then dumps one
error block per branch, each ending in *"is not valid under any of the given
schemas"* and echoing the entire offending object. On `Devices_broken.yml` that
produces 4 unusable top-level errors.

`validate_registry()` in `device_io.py` reads the `type` field **first** and
validates the entry against only that sub-schema:

```python
TYPE_VALIDATORS = {
    name: Draft202012Validator(model.model_json_schema())
    for name, model in DEVICE_MODELS.items()
}
```

Result on the same file:

```
devices[0].pixelcount: 'y' is a required property
devices[0].pixelcount.x: -5 is less than or equal to the minimum of 0
devices[0].binning: 3 is not one of [1, 2, 4]
devices[0]: Additional properties are not allowed ('colour' was unexpected)
devices[1].axes: [] should be non-empty
devices[2]: unknown type 'spectrometer' (known: camera, filterwheel, laser, stage)
devices[3]: missing 'type' discriminator
```

Each model's `model_json_schema()` is self-contained (it carries its own
`$defs`), so no `$ref` resolution across files is needed.

## Registry API

```python
from newswitch.schemas import load_devices

reg = load_devices("Devices.yml")   # or load_config(), which also takes single-device files
reg.by_type("camera")            # [CameraSchema, CameraSchema]
reg.get("laser-488-001")         # lookup by device_id, falls back to name
reg.devices[0].sensor_size_mm    # camera-specific properties stay available
```

Static type checkers narrow the union correctly after a `dev.type == "camera"`
check, so `dev.pixelcount` is only accessible where it exists.

## Device types

Common to all (`DeviceBase`): `name` (required), `manufacturer`, `device_id`,
`tags`. Cameras use `camera_id` instead of `device_id` — `device_key()` in
`device_schema.py` papers over that difference.

| Type | Fields beyond the common ones |
| --- | --- |
| `camera` | see the camera field reference above |
| `stage` | `axes[]` (`label` x–c, `travel_um`, `steps_per_um`, `inverted`), `max_speed_um_per_sec`, `homing_required` |
| `laser` | `wavelength_nm`, `max_power_mw`, `modulation` (`none`/`analog`/`digital`), `shutter` |
| `filterwheel` | `slots[]` (`position`, `label`, `center_nm`, `bandwidth_nm`), `switch_time_ms` |

Cross-field rules enforced by Pydantic only (not by the JSON Schema): unique
axis labels, unique filter slot positions, unique device identifiers across the
whole registry.

## Adding a device type

1. Subclass `DeviceBase` with a new `type: Literal["..."]`.
2. Add the class to the `Device` union and to `DEVICE_MODELS`.
3. Done — registry, loader, error reporting and the exported JSON Schema pick
   it up automatically.

## Single-device files still work

`load_camera()` is unchanged. `CameraSchema.type` has a default of
`"camera"`, so `hik_mv_ca023_10um.yaml` validates without the field, while the
same model works as a union member where `type` is present. `load_config()` uses
the same default when it wraps a single-device file, and `load_device()` reads
either kind of file:

```python
load_device("hik_mv_ca023_10um")                  # from a single-device file
load_device("Devices.yml", "hik-mv-ca023-001")    # from the registry
```

---

# Min/max limits for a parameter

## Recommendation: nested, with scalar shorthand

Sibling tags (`exposure_time_ms`, `exposure_time_ms_min`, `exposure_time_ms_max`)
are flat and readable, but they scale badly:

* three fields per parameter, and nothing in the schema ties them together
* the rule "value lies between min and max" has to be written once **per
  parameter** instead of once in total
* adding `increment` or `unit` later means touching every parameter again
* a typo like `exposure_time_ms_mim` becomes a new top-level key rather than an
  error inside a known object

The nested form is one reusable model, `Bounded` (see `bounded.py`):

```yaml
exposure_time_ms:
  value: 10.0
  min: 0.024
  max: 10000.0
  increment: 0.001
```

The usual objection to nesting is verbosity, so `Bounded` also accepts a **bare
number as shorthand** for `{value: <number>}`:

```yaml
exposure_time_ms: 10.0        # equivalent to {value: 10.0}
```

Both forms validate in **both** layers. `Bounded.__get_pydantic_json_schema__`
emits `anyOf: [number, object]`, so the jsonschema pass accepts the scalar too —
without that override the shorthand would pass Pydantic and fail jsonschema.

All four members are optional, which covers every case that occurs in practice:

| Content | Meaning |
| --- | --- |
| `{value: 10}` or `10` | a setting; limits unknown or irrelevant |
| `{min: 0.024, max: 10000}` | pure capability, no value chosen |
| `{value: 10, min: 0.024, max: 10000}` | both |
| omitted / `null` | parameter not applicable to this device |

## Fields of `Bounded`

| Field | Description |
| --- | --- |
| `value` | Current or default value |
| `min` | Smallest settable value |
| `max` | Largest settable value |
| `increment` | Step size; settable values are `min + n * increment` |
| `unit` | Override for the unit implied by the field name |

`increment` is worth carrying. GenICam devices silently snap a non-representable
value to the nearest grid point, so a config that asks for 10.0005 ms quietly
becomes 10.0 ms. `Bounded.supports()` catches that up front, `Bounded.clamp()`
performs the snap deliberately.

```python
e = cam.exposure_time_ms
e.clamp(1e6)          # 10000.0   -> clamped to max
e.clamp(10.00047)     # 10.0      -> snapped to the 0.001 grid
e.supports(10.0005)   # False
```

## What JSON Schema can and cannot express here

`minimum`/`maximum` in JSON Schema are **global constants**. They cannot refer
to another field of the same document, so "value must lie inside *this device's*
min/max" is a cross-field rule and lives in Pydantic only:

```
Bounded(value=20000, min=0.024, max=10000)
  -> value 20000.0 above max 10000.0
```

This is the same split as elsewhere in this project: the exported
`camera.schema.json` checks structure and types, Pydantic checks relations.
Consumers in other languages get the structure for free but must re-implement
the relation — three lines, and worth doing.

Note that the previous hard-coded `Field(gt=0, le=10_000)` on
`exposure_time_ms` is now **gone**, deliberately. A global ceiling in the schema
is wrong once each device brings its own limits; a 10 s cap is nonsense for a
long-exposure astro sensor.

## The larger question: limits and value in the same object?

They have different lifecycles:

| | Limits | Value |
| --- | --- | --- |
| Source | datasheet, or queried from the SDK | user, experiment, GUI |
| Changes | with the hardware model | every acquisition |
| Scope | shared by all units of that model | per unit, per run |

Keeping them together (as above) gives locality — everything about exposure in
one place — and is the right call for a device *description*. If you later find
yourself diffing two setups' settings, or reusing one limits block across five
identical cameras, split them:

```yaml
limits:                       # static, from the datasheet
  exposure_time_ms: {min: 0.024, max: 10000.0, increment: 0.001}
  gain_db: {min: 0.0, max: 23.98, increment: 0.01}

settings:                     # runtime, per experiment
  exposure_time_ms: 10.0
  gain_db: 0.0
```

`Bounded` serves both layouts unchanged — in the split form you simply never
populate `value` in the `limits` block.

## Static limits are a cache, not the truth

For GenICam-based SDKs (HIKROBOT MVS, IDS peak, Basler pylon) min/max/increment
are **queryable at runtime and are dynamic**: the maximum exposure depends on
the current frame rate, the gain range depends on the pixel format, and enabling
an ROI shifts both. A number written into a YAML file is a snapshot of one
configuration.

So treat the file limits as a fallback for offline work and UI slider bounds,
and re-query on connect:

```python
node = nodemap.FindNode("ExposureTime")
live = Bounded(min=node.Minimum(), max=node.Maximum(), increment=node.Increment())
if not live.supports(cam.exposure_time_ms.value):
    log.warning("configured exposure not settable, snapping to %s",
                live.clamp(cam.exposure_time_ms.value))
```

That also gives you a cheap consistency check: if the queried limits disagree
with the file, either the file is stale or the wrong device is connected.
