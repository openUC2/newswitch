"""Checks that span several devices: references between entries and shared resources.

A single entry is validated by its dataclass; everything here needs the whole file.
"""

from __future__ import annotations

from .connection import (
    CanBusProtocol,
    CanOpenProtocol,
    Connection,
    Uc2RestProtocol,
    check_shared_resources,
    resource_key,
    transport_of,
)
from .devices import (
    CanOpenLaserBinding,
    CanOpenMotorBinding,
    ConnectedDevice,
    ControllerConfig,
    FilterConfig,
    NewswitchConfig,
    ObjectiveConfig,
    Uc2MasterAxisBinding,
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

    for stage in config.stages:
        connection = stage.connection_for_axes(config)
        bound = [axis for axis in stage.axes if axis.binding is not None]
        if bound and len(bound) != len(stage.axes):
            problems.append(f"devices.{stage.device_id}.axes: bind every axis or none")
        for index, axis in enumerate(stage.axes):
            binding = axis.binding
            if binding is None or connection is None:
                continue
            where = f"devices.{stage.device_id}.axes.{index}.binding"
            if isinstance(binding, CanOpenMotorBinding):
                if not isinstance(connection, (CanBusProtocol, CanOpenProtocol)):
                    problems.append(f"{where}: canopen binding requires a CAN connection")
                elif (
                    isinstance(connection, CanOpenProtocol)
                    and binding.node_id != connection.node_id
                ):
                    problems.append(f"{where}: node_id differs from the connection's node_id")
            elif isinstance(binding, Uc2MasterAxisBinding):
                if not isinstance(connection, Uc2RestProtocol):
                    problems.append(f"{where}: uc2-master binding requires a uc2-rest connection")
                elif axis.label in ("x", "y", "z", "a"):
                    expected = {"a": 0, "x": 1, "y": 2, "z": 3}[axis.label]
                    if binding.stepper_id != expected:
                        problems.append(
                            f"{where}.stepper_id: current UC2 serial driver uses {expected} "
                            f"for axis {axis.label!r}"
                        )
                else:
                    problems.append(
                        f"{where}: current UC2 serial driver cannot address {axis.label!r}"
                    )

    used_light_outputs: dict[tuple, str] = {}
    for source in config.lightsources:
        binding = source.binding
        if binding is None:
            continue
        connection = source.connection
        if connection is None and source.controller is not None:
            controller = devices.get(source.controller)
            if isinstance(controller, ControllerConfig):
                connection = controller.connection
        where = f"devices.{source.device_id}.binding"
        if not isinstance(connection, (CanBusProtocol, CanOpenProtocol)):
            problems.append(f"{where}: CAN light binding requires a CAN connection")
            continue
        if isinstance(connection, CanOpenProtocol) and binding.node_id != connection.node_id:
            problems.append(f"{where}: node_id differs from the connection's node_id")
        transport = transport_of(connection)
        assert transport is not None
        bus = resource_key(transport)
        node_key = (bus, binding.node_id)
        kind = "laser" if isinstance(binding, CanOpenLaserBinding) else "led-matrix"
        for address, other in used_light_outputs.items():
            if address[:2] == node_key and address[2] != kind:
                problems.append(f"{where}: CAN node {binding.node_id} is already used by {other}")
        output = binding.channel if isinstance(binding, CanOpenLaserBinding) else 0
        address = (*node_key, kind, output)
        if address in used_light_outputs:
            problems.append(
                f"{where}: CAN light output is already used by {used_light_outputs[address]}"
            )
        else:
            used_light_outputs[address] = source.device_id

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
