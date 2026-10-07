"""Load ``newswitch-config.yaml`` into dataclasses and write changes back.

Typical use::

    from newswitch import config_io

    cfg_file = config_io.load_config(ImswitchConfig().config_file)
    cfg = cfg_file.config
    for detector in cfg.detectors: ...

    cfg_file.apply_firmware("bigcamera42", {"exposure_time_ms": {"min": 0.02, "max": 1e4}})
    cfg.devices["bigcamera42"].exposure_time_ms.value = 30.0   # runtime change
    cfg_file.save()                                            # comments stay intact

Loading runs four stages and reports all problems of a stage together: top level and
``device_id`` keys, jsonschema per device type, pydantic (defaults, units, field rules),
and cross-device references.
"""

from __future__ import annotations

import re
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .devices import AxisConfig, Device, NewswitchConfig, StageConfig, field_markers
from .document import read_tree, resolve_source, to_plain, write_tree
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

    def __init__(self, path: Path, tree: Any, config: NewswitchConfig) -> None:  # noqa: ANN401
        """Wrap an already validated configuration.

        Args:
            path: File the configuration was read from and is saved to.
            tree: ruamel round-trip tree of that file.
            config: The validated configuration.
        """
        self.path = path
        self.tree = tree
        self.config = config
        self._snapshot: dict[str, dict[str, Any]] = {
            key: _dump(device) for key, device in config.devices.items()
        }

    def apply_firmware(self, device_id: str, reported: dict[str, Any]) -> None:
        """Merge values a device reported about itself into the configuration.

        Only fields marked ``x_firmware`` are accepted. For ``"limits"`` fields the
        ``value`` stays user-owned; min/max/inc/preset_vals are taken over. Physical
        values may come in any compatible unit and are converted. Stage axes are
        addressed by label: ``{"axes": {"x": {"vel": {"max": 1e4}}}}``.

        The device object in `config.devices` is replaced by a revalidated one, so
        call this before handing devices to the managers.

        Args:
            device_id: The device the values belong to.
            reported: ``{field: value}``; physical values as mappings of their members.

        Raises:
            KeyError: No such device.
            ConfigError: A field is not firmware-provided, or the merged result is invalid.
        """
        device = self.config.devices[device_id]
        data = _dump(device)
        problems: list[str] = []

        axes_reported = reported.get("axes")
        top_level = {k: v for k, v in reported.items() if k != "axes"}
        self._merge_into(data, field_markers(type(device)), top_level, device_id, problems)

        if axes_reported is not None:
            if not isinstance(device, StageConfig) or not isinstance(axes_reported, dict):
                problems.append(f"{device_id}.axes: only stages have axes")
            else:
                axis_markers = field_markers(AxisConfig)
                for label, values in axes_reported.items():
                    index = next(
                        (i for i, axis in enumerate(device.axes) if axis.label == label), None
                    )
                    if index is None:
                        problems.append(f"{device_id}.axes.{label}: stage has no such axis")
                        continue
                    where = f"{device_id}.axes.{label}"
                    self._merge_into(data["axes"][index], axis_markers, values, where, problems)

        if problems:
            raise ConfigError(f"firmware values for {device_id!r} rejected", problems)
        try:
            self.config.devices[device_id] = _DEVICE_ADAPTER.validate_python(data)
        except ValidationError as exc:
            raise ConfigError(
                f"firmware values for {device_id!r} are invalid", _format_validation_error(exc)
            ) from exc

    @staticmethod
    def _merge_into(
        data: dict[str, Any],
        markers: dict[str, dict[str, Any]],
        reported: dict[str, Any],
        where: str,
        problems: list[str],
    ) -> None:
        """Merge reported values into one dumped device or axis.

        Args:
            data: Dumped device or axis; modified in place.
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
        """Write runtime and firmware changes back into the YAML file.

        See `writeback` for which fields are written. Every device is revalidated first,
        so an out-of-range runtime value is caught before anything is written.

        Args:
            path: Target file; defaults to the file the configuration was loaded from.
            backup: Keep the previous file as ``<name>.bak``.

        Returns:
            The path written to.

        Raises:
            ConfigError: A device no longer validates.
        """
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
            old, new, node = self._snapshot[key], current[key], nodes[key]
            merge_fields(node, field_markers(type(device)), old, new)
            if isinstance(device, StageConfig):
                axis_markers = field_markers(AxisConfig)
                for index, axis_node in enumerate(node["axes"]):
                    merge_fields(axis_node, axis_markers, old["axes"][index], new["axes"][index])

        target = self.path if path is None else Path(path)
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
    problems = check_references(config)
    if problems:
        raise ConfigError(f"{name} has inconsistent references:", problems)
    _check_version(config.newswitch_version)
    return config


def load_config(src: str | Path) -> ConfigFile:
    """Load and validate the configuration file.

    Args:
        src: Path of the file (`newswitch.app.ImswitchConfig.config_file`).

    Returns:
        The loaded file, ready to be read by the managers and saved back.

    Raises:
        ConfigError: The file is missing, unparseable or invalid.
    """
    path = resolve_source(src)
    tree = read_tree(path)
    return ConfigFile(path, tree, parse_tree(tree, path.name))
