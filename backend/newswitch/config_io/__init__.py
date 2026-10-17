"""Read, validate and write back the device configuration (``newswitch-config.yaml``).

The file holds every device newswitch controls. This package turns it into one
dataclass per device type (see `devices`), fills in defaults, converts units, checks
references between devices, and writes runtime/firmware values back without touching
comments or layout.

There are two files (see ``backend/base_config.yaml``): the static configuration, which
newswitch never writes, and the persistent one, which receives every change.
`open_config` reads the one selected by ``load_from_static_config_path`` and saves to the
persistent file.

Layout
------
* `devices`     -- device dataclasses, `MappingEntry`, `NewswitchConfig`, `field_markers`
* `values`      -- `PhysVal`, `Trigger`, `Firmware` and the field validators
* `connection`  -- controller connection models (protocol + transport), shared resources
* `config_file` -- `open_config`, `load_config`, `ConfigFile` (apply_firmware / save)
* `validation`  -- jsonschema pass per device type, YAML schema export
* `references`  -- cross-device checks (stage axes, controller mappings)
* `writeback`   -- merge rules for writing back
* `document`    -- ruamel round-trip I/O, `ensure_persistent_copy`
* `units`       -- pint unit conversion
* `adapters`    -- dataclasses -> manager/protocol dataclasses

Typical use::

    from newswitch import config_io

    cfg_file = config_io.open_config(static, persistent, from_static=False)
    for detector in cfg_file.config.detectors:
        ...
    cfg_file.save()   # always into the persistent file
"""

from .config_file import ConfigFile, load_config, open_config, parse_tree
from .connection import Connection, check_shared_resources, resource_key, transport_of
from .devices import (
    DEVICE_TYPES,
    AxisConfig,
    ControllerConfig,
    DetectorConfig,
    Device,
    DeviceBase,
    FilterConfig,
    LightsourceConfig,
    MappingEntry,
    NewswitchConfig,
    ObjectiveConfig,
    StageConfig,
    field_markers,
)
from .document import ensure_persistent_copy
from .errors import ConfigError, ConfigWarning
from .references import Reference, check_references, references
from .validation import config_schema, export_schema
from .values import Firmware, PhysVal, Trigger

__all__ = [
    "DEVICE_TYPES",
    "AxisConfig",
    "ConfigError",
    "ConfigFile",
    "ConfigWarning",
    "Connection",
    "ControllerConfig",
    "DetectorConfig",
    "Device",
    "DeviceBase",
    "FilterConfig",
    "Firmware",
    "LightsourceConfig",
    "MappingEntry",
    "NewswitchConfig",
    "ObjectiveConfig",
    "PhysVal",
    "Reference",
    "StageConfig",
    "Trigger",
    "check_references",
    "check_shared_resources",
    "config_schema",
    "ensure_persistent_copy",
    "export_schema",
    "field_markers",
    "load_config",
    "open_config",
    "parse_tree",
    "references",
    "resource_key",
    "transport_of",
]
