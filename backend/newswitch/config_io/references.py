"""Checks that span several devices: references between entries and shared resources.

A single entry is validated by its dataclass; everything here needs the whole file.

Every key one entry names of another is described by a `Reference` (see `references`),
so one loop finds all invalid entries: targets that do not exist, targets of the wrong
type, and targets claimed twice within the same group. A new kind of reference is one
more ``case`` in `references`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .connection import Connection, check_shared_resources
from .devices import ControllerConfig, Device, NewswitchConfig, StageConfig

#: Device types a controller may map: everything that is driven through hardware.
MAPPABLE = ("lightsource", "detector", "axis", "stage")


@dataclass(frozen=True)
class Reference:
    """One entry naming another by its key."""

    where: str
    """Location in the file, e.g. ``devices.xyz.axes.x``."""
    target: str
    """The key named there."""
    allowed: tuple[str, ...]
    """Device types the target may have."""
    is_error: bool
    """A missing or mistyped target is an error (else a warning)."""
    group: str
    """A target may appear only once per group, e.g. in only one stage."""


def references(key: str, device: Device) -> Iterator[Reference]:
    """Every reference a device makes to other devices.

    Args:
        key: The device's key.
        device: The device.

    Yields:
        One `Reference` per named key.
    """
    match device:
        case StageConfig():
            for direction, axis in device.axes.items():
                yield Reference(f"devices.{key}.axes.{direction}", axis, ("axis",), True, "stage")
        case ControllerConfig():
            for target in device.mapping:
                yield Reference(
                    f"devices.{key}.mapping.{target}", target, MAPPABLE, False, "controller mapping"
                )
        case _:
            pass


def check_references(config: NewswitchConfig) -> tuple[list[str], list[str]]:
    """Return every cross-device problem, one readable line each.

    Checked:

    * Stage axes name existing ``axis`` devices (error).
    * Controller mappings name existing lightsources, detectors, axes or stages (warning).
    * No axis is part of two stages, and no device is mapped by two controllers (error).
    * Controllers on one physical resource agree on its settings (error).

    Args:
        config: The validated configuration.

    Returns:
        ``(errors, warnings)``; both empty when everything is consistent.
    """
    errors: list[str] = []
    warnings: list[str] = []
    claimed_by: dict[tuple[str, str], list[str]] = {}

    for key, device in config.devices.items():
        for ref in references(key, device):
            claimed_by.setdefault((ref.group, ref.target), []).append(ref.where)
            target = config.devices.get(ref.target)
            if target is None:
                problem = f"{ref.where}: no device {ref.target!r}"
            elif target.type not in ref.allowed:
                problem = (
                    f"{ref.where}: {ref.target!r} is a {target.type}, "
                    f"expected {' or '.join(ref.allowed)}"
                )
            else:
                continue
            (errors if ref.is_error else warnings).append(problem)

    for (group, target), wheres in claimed_by.items():
        if len(wheres) > 1:
            errors.append(f"{target!r} appears in more than one {group}: {', '.join(wheres)}")

    connections: dict[str, Connection] = {
        key: controller.connection for key, controller in config.keyed(ControllerConfig).items()
    }
    try:
        check_shared_resources(connections)
    except ValueError as exc:
        errors.extend(f"shared resource: {line}" for line in str(exc).splitlines())

    return errors, warnings
