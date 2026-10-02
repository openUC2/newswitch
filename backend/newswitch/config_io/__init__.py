"""Read, validate and write back ``newswitch-config.yaml``.

The file holds every device newswitch controls. This package turns it into one
dataclass per device type (see `devices`), fills in defaults, converts units, checks
references between devices, and writes runtime/firmware values back without touching
comments or layout.

Layout
------
* `devices`     -- device dataclasses, `NewswitchConfig`, `field_markers`
* `values`      -- `PhysVal`, `Trigger`, `Firmware` and the field validators
* `connection`  -- connection models (protocol + transport), shared-resource check
* `config_file` -- `load_config`, `ConfigFile` (apply_firmware / save)
* `validation`  -- jsonschema pass per device type, YAML schema export
* `references`  -- cross-device checks
* `writeback`   -- merge rules for writing back
* `document`    -- ruamel round-trip I/O, `ensure_persistent_copy`
* `units`       -- pint unit conversion
* `adapters`    -- dataclasses -> manager/protocol dataclasses

Typical use::

    from newswitch import config_io

    cfg_file = config_io.load_config(ImswitchConfig().config_file)
    for detector in cfg_file.config.detectors:
        ...
    cfg_file.save()
"""

from .config_file import ConfigFile, load_config, parse_tree
from .connection import Connection, check_shared_resources, resource_key, transport_of
from .devices import (
    DEVICE_TYPES,
    AxisConfig,
    ConnectedDevice,
    ControllerConfig,
    DetectorConfig,
    Device,
    DeviceBase,
    FilterConfig,
    LightsourceConfig,
    NewswitchConfig,
    ObjectiveConfig,
    RevolverConfig,
    StageConfig,
    field_markers,
)
from .document import ensure_persistent_copy
from .errors import ConfigError, ConfigWarning
from .validation import config_schema, export_schema
from .values import Firmware, PhysVal, Trigger

__all__ = [
    "DEVICE_TYPES",
    "AxisConfig",
    "ConfigError",
    "ConfigFile",
    "ConfigWarning",
    "ConnectedDevice",
    "Connection",
    "ControllerConfig",
    "DetectorConfig",
    "Device",
    "DeviceBase",
    "FilterConfig",
    "Firmware",
    "LightsourceConfig",
    "NewswitchConfig",
    "ObjectiveConfig",
    "PhysVal",
    "RevolverConfig",
    "StageConfig",
    "Trigger",
    "check_shared_resources",
    "config_schema",
    "ensure_persistent_copy",
    "export_schema",
    "field_markers",
    "load_config",
    "parse_tree",
    "resource_key",
    "transport_of",
]
