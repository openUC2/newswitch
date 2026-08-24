"""Common error base for every config loader in this package.

`CameraConfigError` and `DeviceConfigError` both derive from `ConfigError`, so a
caller that does not care which loader it went through can write::

    try:
        registry = load_config(path)
    except ConfigError as exc:
        ...

The base lives in its own module rather than in one of the io modules, because both
of them plus `loader` need it and importing it from either would create a cycle.
`ConfigError` derives from `ValueError`, which is what the loaders raised before.
"""

from __future__ import annotations


class ConfigError(ValueError):
    """Raised when a configuration document does not satisfy its schema."""
