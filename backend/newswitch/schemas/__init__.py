"""Schema-checked import and export of device configurations (JSON or YAML).

Layout
------
* `bounded`        -- `Bounded`: a numeric parameter carrying its own min/max/increment
* `camera_schema`  -- `CameraSchema` and its sub-models
* `device_schema`  -- the other device types, the discriminated union, `DeviceRegistry`
* `document`       -- file parsing/writing and path resolution via `newswitch.config`
* `camera_io`      -- camera-only loader, writer and schema exporter
* `device_io`      -- registry loader, per-type validator, writer, schema exporter
* `loader`         -- `load_config` / `load_device`: one entry point for every layout

Typical use::

    from newswitch.schemas import load_config, load_device, dump_config

    registry = load_config("Devices.yml")          # 5 devices
    registry = load_config("hik_mv_ca023_10um")    # single-device file, 1 entry
    cam = load_device("Devices.yml", "hik-mv-ca023-001", expect="camera")
    dump_config(registry, "data/Devices.backup.yml")

Bare names are resolved against the managed config directory (see
`newswitch.config.Paths`), explicit paths are used as given. Every loader raises
`ConfigError`; `CameraConfigError` and `DeviceConfigError` are subclasses of it.
"""

from .bounded import Bounded
from .camera_io import (
    CameraConfigError,
    dump_camera,
    export_json_schema as export_camera_schema,
    load_camera,
    schema_errors,
)
from .camera_schema import CameraSchema, Trigger, Vector2Float, Vector2Int
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
    Device,
    DeviceBase,
    DeviceModel,
    DeviceRegistry,
    FilterWheelDevice,
    LaserDevice,
    StageAxis,
    StageDevice,
    device_key,
)
from .document import read_document, write_document
from .errors import ConfigError
from .loader import dump_config, load_config, load_device

__all__ = [
    # models
    "Bounded",
    "CameraSchema",
    "Trigger",
    "Vector2Int",
    "Vector2Float",
    "DeviceBase",
    "StageAxis",
    "StageDevice",
    "LaserDevice",
    "FilterWheelDevice",
    "Device",
    "DeviceModel",
    "DeviceRegistry",
    "DEVICE_MODELS",
    "device_key",
    # one entry point for any layout
    "load_config",
    "load_device",
    "dump_config",
    # type-specific entry points
    "load_camera",
    "dump_camera",
    "schema_errors",
    "load_devices",
    "dump_devices",
    "validate_registry",
    "describe",
    # documents and schema export
    "read_document",
    "write_document",
    "export_camera_schema",
    "export_devices_schema",
    # errors
    "ConfigError",
    "CameraConfigError",
    "DeviceConfigError",
]
