"""Load the device configuration into dataclasses and write changes back.

Typical use::

    from newswitch import config_io

    cfg_file = config_io.open_config(static, persistent, from_static=True)
    cfg = cfg_file.config
    for detector in cfg.detectors: ...

    cfg_file.apply_firmware("bigcamera42", {"exposure_time_ms": {"min": 0.02, "max": 1e4}})
    cfg.devices["bigcamera42"].exposure_time_ms.value = 30.0   # runtime change
    cfg_file.save()                    # into the persistent file; comments stay intact

The static file is never written: `open_config` reads it or the persistent file and always
saves into the persistent one.

Loading runs four stages and reports all problems of a stage together: top level,
jsonschema per device type, pydantic (defaults, units, field rules), and cross-device
references (errors fail, warnings are issued as `ConfigWarning`).
"""

from __future__ import annotations

import re
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .devices import Device, NewswitchConfig, field_markers
from .document import ensure_persistent_copy, read_tree, resolve_source, to_plain, write_tree
from .errors import ConfigError, ConfigWarning
from .references import check_references
from .validation import prepare_document, validate_document
from .values import PhysVal, in_unit
from .writeback import merge_fields, merge_phys_from_firmware

_CONFIG_ADAPTER = TypeAdapter(NewswitchConfig)
_DEVICE_ADAPTER: TypeAdapter[Device] = TypeAdapter(Device)
_PHYS_ADAPTER = TypeAdapter(PhysVal)
_VERSION = re.compile(r"v?(\d+)\.(\d+)")


def _format_validation_error(exc: ValidationError) -> list[str]:
    """Turn a pydantic error into ``path: message`` lines.

    The discriminator tag pydantic inserts after the device key (``devices.cam.detector.x``)
    is dropped, so paths match the file.

    Args:
        exc: The pydantic error.

    Returns:
        One line per error.
    """
    lines = []
    for err in exc.errors():
        loc = [str(part) for part in err["loc"]]
        if len(loc) >= 3 and loc[0] == "devices":
            del loc[2]
        lines.append(f"{'.'.join(loc) or '<root>'}: {err['msg']}")
    return lines


def _check_version(stated: str) -> None:
    """Warn when the file was written for another major/minor newswitch version.

    Args:
        stated: The file's ``newswitch_version``.
    """
    try:
        installed = version("newswitch")
    except PackageNotFoundError:
        return
    ours, theirs = _VERSION.match(installed), _VERSION.match(stated)
    if theirs is None:
        warnings.warn(f"newswitch_version {stated!r} is not a version", ConfigWarning, stacklevel=3)
    elif ours is not None and ours.groups() != theirs.groups():
        warnings.warn(
            f"config was written for newswitch {stated}, running {installed}",
            ConfigWarning,
            stacklevel=3,
        )


def _same_file(a: Path, b: Path) -> bool:
    """True when two paths name the same file (whether or not it exists yet)."""
    return a.resolve() == b.resolve()


def _dump(device: Any) -> dict[str, Any]:  # noqa: ANN401 - any device dataclass
    """Dump one device to a plain dict (python mode keeps inf and tuples).

    Args:
        device: A device dataclass.

    Returns:
        The dumped device.
    """
    return _DEVICE_ADAPTER.dump_python(device)


class ConfigFile:
    """A loaded configuration together with the YAML tree it came from."""

    def __init__(
        self,
        path: Path,
        tree: Any,  # noqa: ANN401 - a parsed document is Any
        config: NewswitchConfig,
        *,
        target: Path | None = None,
        protected: Path | None = None,
    ) -> None:
        """Wrap an already validated configuration.

        Args:
            path: File the configuration was read from.
            tree: ruamel round-trip tree of that file.
            config: The validated configuration.
            target: File `save` writes to; defaults to `path`.
            protected: File that must never be written (the static configuration).
        """
        self.path = path
        self.target = path if target is None else target
        self.protected = protected
        self.tree = tree
        self.config = config
        self._snapshot: dict[str, dict[str, Any]] = {
            key: _dump(device) for key, device in config.devices.items()
        }

    def apply_firmware(self, key: str, reported: dict[str, Any]) -> None:
        """Merge values a device reported about itself into the configuration.

        Only fields marked ``x_firmware`` are accepted. For ``"limits"`` fields
        ``value`` and ``selected_index`` stay user-owned; min/max/inc/preset_vals are
        taken over. Physical values may come in any compatible unit and are converted.
        An axis is a device of its own and reports under its own key.

        The device object in `config.devices` is replaced by a revalidated one, so
        call this before handing devices to the managers.

        Args:
            key: The device the values belong to.
            reported: ``{field: value}``; physical values as mappings of their members.

        Raises:
            KeyError: No such device.
            ConfigError: A field is not firmware-provided, or the merged result is invalid.
        """
        device = self.config.devices[key]
        data = _dump(device)
        problems: list[str] = []
        self._merge_into(data, field_markers(type(device)), reported, key, problems)
        if problems:
            raise ConfigError(f"firmware values for {key!r} rejected", problems)
        try:
            self.config.devices[key] = _DEVICE_ADAPTER.validate_python(data)
        except ValidationError as exc:
            raise ConfigError(
                f"firmware values for {key!r} are invalid", _format_validation_error(exc)
            ) from exc

    @staticmethod
    def _merge_into(
        data: dict[str, Any],
        markers: dict[str, dict[str, Any]],
        reported: dict[str, Any],
        where: str,
        problems: list[str],
    ) -> None:
        """Merge reported values into one dumped device.

        Args:
            data: Dumped device; modified in place.
            markers: `field_markers` of its class.
            reported: Values the firmware reported for it.
            where: Location prefix for problem messages.
            problems: Collects rejected fields.
        """
        for name, value in reported.items():
            marker = markers.get(name)
            if marker is None or "x_firmware" not in marker:
                problems.append(f"{where}.{name}: not a firmware-provided field")
                continue
            unit = marker.get("x_unit")
            if unit is None:
                data[name] = value
                continue
            raw = value if isinstance(value, dict) else {"value": value}
            try:
                converted = in_unit(unit)(_PHYS_ADAPTER.validate_python(raw))
            except ValidationError as exc:
                problems.extend(f"{where}.{name}.{line}" for line in _format_validation_error(exc))
                continue
            if converted is None:
                problems.append(f"{where}.{name}: unit {raw.get('unit')!r} not usable")
                continue
            dumped = _PHYS_ADAPTER.dump_python(converted)
            supplied = {k: dumped[k] for k in (*raw.keys(), "unit") if k in dumped}
            data[name] = merge_phys_from_firmware(data.get(name), supplied, marker["x_firmware"])

    def save(self, path: str | Path | None = None, *, backup: bool = True) -> Path:
        """Write runtime and firmware changes into the YAML file.

        The tree read from `path` is updated and written to `target` (see `writeback` for
        which fields are written). Every device is revalidated first, so an out-of-range
        runtime value is caught before anything is written.

        Args:
            path: Target file; defaults to `target`.
            backup: Keep the previous file as ``<name>.bak``.

        Returns:
            The path written to.

        Raises:
            ConfigError: A device no longer validates, or the target is the protected
                static configuration.
        """
        target = self.target if path is None else Path(path)
        if self.protected is not None and _same_file(target, self.protected):
            raise ConfigError(f"refusing to write the static configuration {str(target)!r}")
        current = {key: _dump(device) for key, device in self.config.devices.items()}
        problems: list[str] = []
        for key, data in current.items():
            try:
                _DEVICE_ADAPTER.validate_python(data)
            except ValidationError as exc:
                problems += [f"devices.{key}: {line}" for line in _format_validation_error(exc)]
        if problems:
            raise ConfigError("refusing to save an invalid configuration", problems)

        nodes = self.tree["devices"]
        for key, device in self.config.devices.items():
            merge_fields(nodes[key], field_markers(type(device)), self._snapshot[key], current[key])

        write_tree(self.tree, target, backup=backup)
        self._snapshot = current
        return target


def parse_tree(tree: Any, name: str = "<config>") -> NewswitchConfig:  # noqa: ANN401
    """Validate a parsed round-trip tree and build the configuration.

    Args:
        tree: Output of `document.read_tree`.
        name: File name used in error messages.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: Any validation stage failed; all problems of that stage are listed.
    """
    document, problems = prepare_document(to_plain(tree))
    problems += validate_document(document)
    if problems:
        raise ConfigError(f"{name} failed validation:", problems)
    try:
        config = _CONFIG_ADAPTER.validate_python(document)
    except ValidationError as exc:
        raise ConfigError(f"{name} failed validation:", _format_validation_error(exc)) from exc
    errors, notes = check_references(config)
    if errors:
        raise ConfigError(f"{name} has inconsistent references:", errors)
    for note in notes:
        warnings.warn(f"{name}: {note}", ConfigWarning, stacklevel=2)
    _check_version(config.newswitch_version)
    return config


def load_config(src: str | Path) -> ConfigFile:
    """Load and validate one configuration file; `ConfigFile.save` writes it back in place.

    Use `open_config` to run newswitch on a static/persistent pair.

    Args:
        src: Path of the file.

    Returns:
        The loaded file.

    Raises:
        ConfigError: The file is missing, unparseable or invalid.
    """
    path = resolve_source(src)
    tree = read_tree(path)
    return ConfigFile(path, tree, parse_tree(tree, path.name))


def open_config(static: str | Path, persistent: str | Path, *, from_static: bool) -> ConfigFile:
    """Load the device configuration newswitch runs on.

    The static file is never written. Changes are always saved into the persistent file:

    * ``from_static=True``: the static file is read; saving overwrites the persistent file.
    * ``from_static=False``: the persistent file is read (created as a copy of the static
      one if it does not exist yet) and saved back in place.

    Args:
        static: ``static_config_path`` from ``base_config.yaml``.
        persistent: ``persistent_config_path`` from ``base_config.yaml``.
        from_static: ``load_from_static_config_path`` from ``base_config.yaml``.

    Returns:
        The loaded file; `ConfigFile.save` writes into `persistent`.

    Raises:
        ConfigError: Both paths name the same file, or the file to read is missing,
            unparseable or invalid.
    """
    static, persistent = Path(static), Path(persistent)
    if _same_file(static, persistent):
        raise ConfigError(f"static and persistent configuration are the same file {str(static)!r}")
    path = resolve_source(static if from_static else ensure_persistent_copy(static, persistent))
    tree = read_tree(path)
    return ConfigFile(path, tree, parse_tree(tree, path.name), target=persistent, protected=static)
