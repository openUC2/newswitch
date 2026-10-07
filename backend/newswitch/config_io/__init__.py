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
* `document`    -- ruamel round-trip I/O and path resolution
* `units`       -- pint unit conversion
* `adapters`    -- dataclasses -> manager/protocol dataclasses

Typical use::

    from newswitch import config_io

    cfg_file = config_io.load_config()      # managed newswitch-config.yaml
    for detector in cfg_file.config.detectors:
        ...
    cfg_file.save()
"""

from .config_file import ConfigFile, load_config, parse_tree
from .connection import Connection, check_shared_resources, resource_key, transport_of
from .devices import (
    DEVICE_TYPES,
    AxisConfig,
    CanOpenLaserBinding,
    CanOpenLedMatrixBinding,
    CanOpenMotorBinding,
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
    Uc2MasterAxisBinding,
    Uc2MasterLaserBinding,
    Uc2MasterLedMatrixBinding,
    field_markers,
)
from .document import DEFAULT_CONFIG_NAME
from .errors import ConfigError, ConfigWarning
from .validation import config_schema, export_schema
from .values import Firmware, PhysVal, Trigger

__all__ = [
    "DEFAULT_CONFIG_NAME",
    "DEVICE_TYPES",
    "AxisConfig",
    "CanOpenLaserBinding",
    "CanOpenLedMatrixBinding",
    "CanOpenMotorBinding",
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
    "Uc2MasterAxisBinding",
    "Uc2MasterLaserBinding",
    "Uc2MasterLedMatrixBinding",
    "Trigger",
    "check_shared_resources",
    "config_schema",
    "export_schema",
    "field_markers",
    "load_config",
    "parse_tree",
    "resource_key",
    "transport_of",
]
