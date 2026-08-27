"""One entry point for every config layout.

`device_io` expects one specific document shape: a registry with a ``devices`` key.
In practice a caller has a file and wants the devices in it, without caring whether
that file describes a single device (``hik_mv_ca023_10um.yaml``) or a whole setup
(``Devices.yml``), and without caring whether it is JSON or YAML.

`load_config()` normalizes all of those to the same result — a `DeviceRegistry`:

    ================================= ==================================================
    Document                          Handling
    ================================= ==================================================
    ``dict`` with a ``devices`` key   multi-device file, used as-is
    ``list``                          bare device list, treated as ``{"devices": [...]}``
    ``dict`` without ``devices``      single device, wrapped into a one-entry registry
    anything else                     ConfigError
    ================================= ==================================================

Every device type spells out its own ``type:``, cameras included -- `CameraDevice.type`
is a required discriminator with no default. A single-device document that omits the
key is wrapped as `DEFAULT_DEVICE_TYPE`, i.e. an opaque `UnknownDevice`: its contents
are preserved but nothing in it is validated. Note the asymmetry that follows from
this -- a *misspelled* ``type: stagee`` is rejected by the discriminator, while an
*omitted* ``type`` is silently accepted. A document that carries both ``devices`` and
``name`` counts as a registry.

Validation is unchanged and still runs in two layers: the per-type jsonschema pass
from `device_io` for structure, then Pydantic for the cross-field rules. Errors of a
wrapped single-device file are reported without the ``devices[0]`` prefix, so they
read the way the file looks.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, Optional, Union, overload

from pydantic import BaseModel, ValidationError

from .device_io import dump_devices, validate_registry
from .device_schema import (
    DEVICE_MODELS,
    CameraDevice,
    Device,
    DeviceRegistry,
    FilterWheelDevice,
    LaserDevice,
    StageDevice,
    UnknownDevice,
)
from .document import read_document
from .errors import ConfigError

# No device model defaults its `type`, so a single-device file that omits the key
# cannot be dispatched. It becomes an opaque UnknownDevice rather than a guess.
DEFAULT_DEVICE_TYPE = "unknown"

_INDEX_PREFIX = re.compile(r"^devices\[0\]\.?")


def _unwrap_error(message: str) -> str:
    """Strip the ``devices[0]`` prefix a wrapped single-device file would produce.

    Args:
        message: One entry of `validate_registry`'s result.

    Returns:
        The message as it would read for a single-device file.
    """
    stripped = _INDEX_PREFIX.sub("", message)
    return f"<root>{stripped}" if stripped.startswith(":") else stripped


def normalize_document(data: Any) -> tuple[dict[str, Any], bool]:  # noqa: ANN401 - parsed doc
    """Bring any supported document shape into registry form.

    Args:
        data: Parsed document, as returned by `read_document`.

    Returns:
        A ``(registry_document, was_wrapped)`` pair. ``was_wrapped`` is True when the
        input described a single device and had to be put into a ``devices`` list.

    Raises:
        ConfigError: The document is neither a mapping nor a list.
    """
    if isinstance(data, list):
        return {"devices": data}, False

    if not isinstance(data, dict):
        raise ConfigError(
            f"expected a mapping or a list at the top level, got {type(data).__name__}"
        )

    if "devices" in data:
        return data, False

    entry = dict(data)
    entry.setdefault("type", DEFAULT_DEVICE_TYPE)
    return {"devices": [entry]}, True


def load_config(src: str | Path, *, strict_schema: bool = True) -> DeviceRegistry:
    """Load any device config file and return it as a validated registry.

    Args:
        src: Bare config name (``"Devices"``, ``"Devices.yml"``) resolved against the
            managed config directory, or an explicit path.
        strict_schema: Run the jsonschema pass first, so *all* structural problems are
            reported together instead of only the first Pydantic failure.

    Returns:
        The validated registry. A single-device file yields a one-entry registry.

    Raises:
        ConfigError: The file cannot be read, or the content fails validation.
    """
    document, wrapped = normalize_document(read_document(src))
    name = Path(src).name

    if strict_schema:
        errors = validate_registry(document)
        if wrapped:
            errors = [_unwrap_error(err) for err in errors]
        if errors:
            joined = "\n  - ".join(errors)
            raise ConfigError(f"{name} failed validation:\n  - {joined}")

    try:
        return DeviceRegistry.model_validate(document)
    except ValidationError as exc:
        raise ConfigError(f"{name}: {exc}") from exc


# `expect` already names the type the caller requires, so it may as well carry that
# type statically instead of only raising at runtime. One overload per entry of
# DEVICE_MODELS, then a fallback for everything else: a variable of type `str`, or an
# unknown name such as `expect="spectrometer"`, matches none of the literals and keeps
# the union as its return type.
@overload
def load_device(
    src: str | Path,
    key: Optional[str] = None,
    *,
    expect: Literal["camera"],
    strict_schema: bool = True,
) -> CameraDevice: ...


@overload
def load_device(
    src: str | Path,
    key: Optional[str] = None,
    *,
    expect: Literal["stage"],
    strict_schema: bool = True,
) -> StageDevice: ...


@overload
def load_device(
    src: str | Path,
    key: Optional[str] = None,
    *,
    expect: Literal["laser"],
    strict_schema: bool = True,
) -> LaserDevice: ...


@overload
def load_device(
    src: str | Path,
    key: Optional[str] = None,
    *,
    expect: Literal["filterwheel"],
    strict_schema: bool = True,
) -> FilterWheelDevice: ...


@overload
def load_device(
    src: str | Path,
    key: Optional[str] = None,
    *,
    expect: Literal["unknown"],
    strict_schema: bool = True,
) -> UnknownDevice: ...


@overload
def load_device(
    src: str | Path,
    key: Optional[str] = None,
    *,
    expect: Optional[str] = None,
    strict_schema: bool = True,
) -> Device: ...


def load_device(
    src: str | Path,
    key: Optional[str] = None,
    *,
    expect: Optional[str] = None,
    strict_schema: bool = True,
) -> Device:
    """Load exactly one device, from a single-device file or out of a registry.

    Args:
        src: Bare config name or an explicit path.
        key: ``device_id`` or name of the wanted device. May be omitted
            when the file holds exactly one device.
        expect: Device type the caller requires, e.g. ``"camera"``. Passed as a
            literal it also narrows the return type, so the type-specific fields
            are reachable without an `isinstance` check.
        strict_schema: Passed through to `load_config`.

    Returns:
        The matching device model.

    Raises:
        ConfigError: The file holds several devices and no `key` was given, the `key`
            is unknown, or the device is not of the expected type.
    """
    registry = load_config(src, strict_schema=strict_schema)
    name = Path(src).name
    available = [dev.key for dev in registry.devices]

    if key is None:
        if len(registry.devices) != 1:
            raise ConfigError(
                f"{name} holds {len(registry.devices)} devices, pass one of: "
                f"{', '.join(available) or '<none>'}"
            )
        device = registry.devices[0]
    else:
        try:
            device = registry.get(key)
        except KeyError as exc:
            raise ConfigError(
                f"{name}: no device {key!r}; available: {', '.join(available) or '<none>'}"
            ) from exc

    if expect is not None:
        if expect not in DEVICE_MODELS:
            raise ConfigError(
                f"unknown device type {expect!r} (known: {', '.join(sorted(DEVICE_MODELS))})"
            )
        if device.type != expect:
            raise ConfigError(f"{name}: {device.key!r} is a {device.type}, expected a {expect}")

    return device


def dump_config(obj: Union[DeviceRegistry, BaseModel], dest: str | Path) -> Path:
    """Store a registry or a single device as .json or .yaml.

    Args:
        obj: A `DeviceRegistry`, or a single device model.
        dest: Bare name (written into the config dir) or an explicit path. The suffix
            picks the format.

    Returns:
        The path written to.

    Raises:
        ConfigError: Unsupported file type, or `obj` is not a storable model.
    """
    if isinstance(obj, DeviceRegistry):
        return dump_devices(obj, dest)
    if isinstance(obj, BaseModel) and getattr(obj, "type", None) in DEVICE_MODELS:
        # Non-camera devices have no single-device writer of their own; a one-entry
        # registry keeps the file loadable by load_config().
        return dump_devices(DeviceRegistry(devices=[obj]), dest)  # type: ignore[list-item]
    raise ConfigError(f"cannot store {type(obj).__name__}: not a device or registry")
