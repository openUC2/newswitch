"""Checks that span several devices: references between entries and shared resources.

A single entry is validated by its dataclass; everything here needs the whole file.
"""

from __future__ import annotations

from .connection import Connection, check_shared_resources
from .devices import (
    ConnectedDevice,
    ControllerConfig,
    FilterConfig,
    NewswitchConfig,
    ObjectiveConfig,
)


def check_references(config: NewswitchConfig) -> list[str]:
    """Return every cross-device problem, one readable line each (empty list = fine).

    Checked:

    * ``controller`` names an existing device of type ``controller``.
    * Revolver ``channels`` name existing objectives or filters, a revolver holds only
      one of the two kinds, and no objective/filter sits in two positions.
    * Devices with their own connection agree on shared physical resources.

    Args:
        config: The validated configuration.

    Returns:
        The problems found.
    """
    problems: list[str] = []
    devices = config.devices

    for device_id, device in devices.items():
        if isinstance(device, ConnectedDevice) and device.controller is not None:
            target = devices.get(device.controller)
            if target is None:
                problems.append(f"devices.{device_id}.controller: no device {device.controller!r}")
            elif not isinstance(target, ControllerConfig):
                problems.append(
                    f"devices.{device_id}.controller: {device.controller!r} is not a controller"
                )

    mounted_in: dict[str, str] = {}
    for revolver in config.revolvers:
        kinds: set[str] = set()
        for position, ref in enumerate(revolver.channels):
            if ref is None:
                continue
            where = f"devices.{revolver.device_id}.channels.{position}"
            target = devices.get(ref)
            if target is None:
                problems.append(f"{where}: no device {ref!r}")
                continue
            if isinstance(target, ObjectiveConfig):
                kinds.add("objective")
            elif isinstance(target, FilterConfig):
                kinds.add("filter")
            else:
                problems.append(f"{where}: {ref!r} is neither an objective nor a filter")
                continue
            if ref in mounted_in:
                problems.append(f"{where}: {ref!r} is already mounted in {mounted_in[ref]}")
            else:
                mounted_in[ref] = f"{revolver.device_id}.channels.{position}"
        if len(kinds) > 1:
            problems.append(f"devices.{revolver.device_id}.channels: mixes objectives and filters")

    connections: dict[str, Connection] = {}
    for device_id, device in devices.items():
        if isinstance(device, ControllerConfig):
            connections[device_id] = device.connection
        elif isinstance(device, ConnectedDevice) and device.connection is not None:
            connections[device_id] = device.connection
    try:
        check_shared_resources(connections)
    except ValueError as exc:
        problems.extend(f"shared resource: {line}" for line in str(exc).splitlines())

    return problems
