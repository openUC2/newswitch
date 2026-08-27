"""Common error base for every config loader in this package.

`DeviceConfigError` derives from `ConfigError`, so a caller that does not care which
loader it went through can write::

    try:
        registry = load_config(path)
    except ConfigError as exc:
        ...

`load_config`, `load_device` and `dump_config` raise `ConfigError` itself; the
lower-level `load_devices` and `dump_devices` raise `DeviceConfigError`. Note that
`schema_io.SchemaFormatError` is deliberately *not* part of this hierarchy -- it
reports an unusable *schema* file, not a bad configuration.

The base lives in its own module rather than in one of the io modules, because both
`device_io` and `loader` need it and importing it from either would create a cycle.
`ConfigError` derives from `ValueError`, which is what the loaders raised before.
"""

from __future__ import annotations


class ConfigError(ValueError):
    """Raised when a configuration document does not satisfy its schema."""
