"""Schema-checked import and export of device configurations (JSON or YAML).

Layout
------
* `device_schema` -- `Bounded` and the other building blocks, every device model,
  the discriminated `Device` union, `DEVICE_MODELS`, `DeviceRegistry`
* `document`      -- config file parsing/writing and path resolution via
  `newswitch.config`
* `device_io`     -- registry loader, per-type validator, writer, schema exporter
* `schema_io`     -- JSON Schema read/write in either format, Pydantic export, and a
  validator whose ``$ref`` resolution understands YAML
* `loader`        -- `load_config` / `load_device`: one entry point for every layout

Typical use::

    from newswitch.schemas import load_config, load_device, dump_config

    registry = load_config("Devices.yml")          # 5 devices
    registry = load_config("hik_mv_ca023_10um")    # single-device file, 1 entry
    cam = load_device("Devices.yml", "hik-mv-ca023-001", expect="camera")
    dump_config(registry, "data/Devices.backup.yml")

Bare names are resolved against the managed config directory (see
`newswitch.config.Paths`), explicit paths are used as given. `load_config`,
`load_device` and `dump_config` raise `ConfigError`; the lower-level `load_devices`
and `dump_devices` raise `DeviceConfigError`.
"""

from .device_io import (
    DeviceConfigError,
    describe,
    dump_devices,
    export_json_schema as export_devices_schema,
    load_devices,
    validate_registry,
)
from .device_schema import (
    DEVICE_MODELS,
    Bounded,
    CameraDevice,
    Device,
    DeviceBase,
    DeviceRegistry,
    FilterSlot,
    FilterWheelDevice,
    LaserDevice,
    StageAxis,
    StageDevice,
    Trigger,
    UnknownDevice,
    Vector2Float,
    Vector2Int,
)
from .document import read_document, write_document
from .errors import ConfigError
from .loader import dump_config, load_config, load_device
from .schema_io import (
    SchemaFormatError,
    build_validator,
    convert,
    dump_any,
    export_schema,
    load_any,
)

__all__ = [
    # building blocks
    "Bounded",
    "Trigger",
    "Vector2Int",
    "Vector2Float",
    "StageAxis",
    "FilterSlot",
    # device models
    "DeviceBase",
    "CameraDevice",
    "StageDevice",
    "LaserDevice",
    "FilterWheelDevice",
    "UnknownDevice",
    "Device",
    "DeviceRegistry",
    "DEVICE_MODELS",
    # one entry point for any layout
    "load_config",
    "load_device",
    "dump_config",
    # registry-specific entry points
    "load_devices",
    "dump_devices",
    "validate_registry",
    "describe",
    # documents and schema export
    "read_document",
    "write_document",
    "export_devices_schema",
    "export_schema",
    "load_any",
    "dump_any",
    "convert",
    "build_validator",
    # errors
    "ConfigError",
    "DeviceConfigError",
    "SchemaFormatError",
]
