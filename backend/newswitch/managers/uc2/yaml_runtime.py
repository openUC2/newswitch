"""Resolve controller mappings into UC2 drivers, without opening hardware at startup.

Application addresses (axis directions, light slots) are separate from wire addresses.
Only documented master-level Serial calls and direct UC2 CANopen are supported.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import math
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator
from functools import partial

from newswitch.config_io import NewswitchConfig
from newswitch.config_io.connection import (
    CanOpenProtocol,
    CanTransport,
    Connection,
    SerialTransport,
    Uc2RestProtocol,
    resource_key,
)
from newswitch.config_io.devices import (
    AxisConfig,
    ControllerConfig,
    MappingEntry,
    LightsourceConfig,
)
from newswitch.config_io import adapters
from newswitch.protocols.illumination import Illumination, IlluminationKind, IlluminationState
from rekuest_next.state.lock import acquired_locks
from newswitch.protocols.uc2 import (
    UC2State,
    UC2Event,
    PositionUpdate,
    MotionDone,
    HomingChanged,
    EStopChanged,
)
from .canopen_bus import UC2CanBus, UC2CanBusConfig
from .rest_bus import UC2RestBus, UC2RestBusConfig
from .event_broker import UC2EventBroker
from .stage_manager import UC2StageConfig
from .illumination_manager import UC2IlluminationConfig

HardwareBus = UC2CanBus | UC2RestBus
logger = logging.getLogger(__name__)
SERIAL_AXES = {0: "A", 1: "X", 2: "Y", 3: "Z"}
MATRICES = {"serial-led-matrix", "canopen-led-matrix"}


@dataclass
class AxisRoute:
    """One logical direction, its physical driver axis, and its YAML settings."""

    bus: HardwareBus
    config: AxisConfig
    hardware_axis: str
    homed: bool = False


@dataclass
class LightRoute:
    """One logical light source and its controller address."""

    bus: HardwareBus
    config: LightsourceConfig
    binding: MappingEntry

    @property
    def pwm_max(self) -> int:
        """Expose a concrete output range after checking the optional schema field."""
        if self.binding.type in MATRICES:
            return 255
        maximum = self.binding.pwm_max
        if maximum is None:
            raise ValueError("A PWM light mapping requires pwm_max")
        return maximum


def _serial_port(transport: SerialTransport) -> str:
    """Do not silently select a different board when a selector is ambiguous."""
    if transport.port:
        return transport.port
    if transport.port_pattern:
        matches = sorted(glob.glob(transport.port_pattern))
    else:
        from serial.tools import list_ports

        matches = [
            p.device
            for p in list_ports.comports()
            if (transport.vid is None or p.vid == transport.vid)
            and (transport.pid is None or p.pid == transport.pid)
            and (transport.serial_number is None or p.serial_number == transport.serial_number)
        ]
    if len(matches) != 1:
        raise ValueError(
            f"Serial selector must match exactly one port, found {matches}; use an explicit port"
        )
    return matches[0]


class YamlUC2Bus:
    """Pool used connections and route commands/events per configured device."""

    def __init__(
        self,
        config: NewswitchConfig,
        state: UC2State,
        illumination_state: IlluminationState | None = None,
    ) -> None:
        """Validate the hardware plan before creating any connection tasks."""
        self.state = state
        self.illumination_state = illumination_state
        self.buses: dict[tuple, HardwareBus] = {}
        self._connections: dict[tuple, Connection] = {}
        self.axes: dict[str, AxisRoute] = {}
        self.lights: dict[int, LightRoute] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._broker = UC2EventBroker()
        self._outputs: dict[tuple, set[tuple[str, int, int]]] = {}
        if adapters.wheel_holding(config, adapters.FilterConfig) or adapters.wheel_holding(
            config, adapters.ObjectiveConfig
        ):
            raise ValueError(
                "Hardware wheel mappings are not supported by this stage/light integration"
            )
        if len(config.stages) > 1:
            raise ValueError("The current stage API supports one motion stage")
        stage = config.stages[0] if config.stages else None
        mapped_axes = set(stage.axes.values()) if stage else set()
        unused_axes = set(config.keyed(AxisConfig)) - mapped_axes
        if unused_axes:
            raise ValueError(f"Axes are not part of the motion stage: {sorted(unused_axes)}")
        for direction, key in stage.axes.items() if stage else []:
            label = direction.upper()
            if label not in ("X", "Y", "Z", "A"):
                raise ValueError(
                    f"Axis {direction}: this integration supports linear X/Y/Z/A; rotary units need a separate model"
                )
            if label in self.axes:
                raise ValueError(f"Duplicate logical axis direction {label}")
            axis = config.devices[key]
            if not isinstance(axis, AxisConfig):
                raise ValueError(f"Stage direction {direction} must reference an axis, got {key}")
            if axis.steps_per_um is None:
                raise ValueError(f"Axis {key} requires steps_per_um for a stepper driver")
            if axis.jerk is not None:
                raise ValueError(f"Axis {key}: UC2 drivers do not support jerk")
            bus, entry = self._route(config, key, "motor")
            hardware_axis = SERIAL_AXES[entry.id] if isinstance(bus, UC2RestBus) else label
            if any(r.bus is bus and r.hardware_axis == hardware_axis for r in self.axes.values()):
                raise ValueError(f"Axis {key}: physical motor is already assigned")
            if isinstance(bus, UC2CanBus):
                if axis.homing_endstop_polarity is not None:
                    raise ValueError(f"Axis {key}: CAN homing does not accept a polarity override")
                setattr(bus.config, f"node_{label.lower()}", entry.id)
                setattr(bus.config, f"sub_{label.lower()}", entry.subid)
            scale_field = (
                "steps_per_deg_a"
                if hardware_axis == "A"
                else f"steps_per_um_{hardware_axis.lower()}"
            )
            setattr(bus.config, scale_field, axis.steps_per_um)
            self.axes[label] = AxisRoute(bus, axis, hardware_axis)
            self._locks[label] = asyncio.Lock()
        for slot, (key, source) in enumerate(config.keyed(LightsourceConfig).items(), 1):
            if source.trigger is not None or source.pulse_length is not None:
                raise ValueError(f"Light {key}: triggering/pulse configuration is not supported")
            bus, entry = self._route(config, key, "light")
            if source.channels != (3 if entry.type in MATRICES else 1):
                raise ValueError(
                    f"Light {key}: use 3 color channels for an RGB matrix and 1 for a PWM output"
                )
            self.lights[slot] = LightRoute(bus, source, entry)
        if sum(r.binding.type in MATRICES for r in self.lights.values()) > 1:
            raise ValueError("The RGB matrix API supports one matrix per microscope")
        for bus in self.buses.values():
            if isinstance(bus, UC2CanBus):
                bus.config.configured_axes = [
                    label for label, route in self.axes.items() if route.bus is bus
                ]
        self.stage_config = UC2StageConfig(
            axes=list(self.axes),
            registered_step_sizes=stage.registered_step_sizes if stage else [10.0],
            home_axes=[s.upper() for s in stage.homing_order]
            if stage and stage.homing_order is not None
            else list(self.axes),
            home_parallel=bool(stage and stage.homing_order is None),
            axis_speeds={
                label: r.config.vel.value
                for label, r in self.axes.items()
                if r.config.vel and r.config.vel.value is not None
            },
            axis_accelerations={
                label: r.config.acc.value
                for label, r in self.axes.items()
                if r.config.acc and r.config.acc.value is not None
            },
        )
        self.illumination_config = UC2IlluminationConfig(
            sources=[
                Illumination(
                    slot=slot,
                    channel=slot,
                    kind=IlluminationKind.LASER
                    if r.config.coherence == "coherent"
                    else IlluminationKind.LED,
                    wavelength=r.config.wavelength or 0,
                    intensity=0,
                    min_intensity=0,
                    max_intensity=100,
                    is_active=False,
                )
                for slot, r in self.lights.items()
            ],
            logical_channels=True,
            pwm_by_slot={slot: r.pwm_max for slot, r in self.lights.items()},
        )

    def _route(
        self, config: NewswitchConfig, key: str, kind: str
    ) -> tuple[HardwareBus, MappingEntry]:
        found = config.controller_of(key)
        if found is None:
            raise ValueError(f"Device {key} has no controller mapping")
        controller_key, entry = found
        controller = config.devices[controller_key]
        assert isinstance(controller, ControllerConfig)
        connection = controller.connection
        if isinstance(connection, Uc2RestProtocol):
            allowed = {"serial-motor"} if kind == "motor" else {"serial-laser", "serial-led-matrix"}
            if entry.type not in allowed:
                raise ValueError(
                    f"Device {key}: {entry.type} over uc2-rest has no defined master-ID mapping; use {sorted(allowed)} for the known Serial API"
                )
            if entry.subid != 0:
                raise ValueError(
                    f"Device {key}: Serial master commands use id only; subid must be 0"
                )
            if entry.id not in SERIAL_AXES:
                raise ValueError(f"Device {key}: UC2 Serial motor/light id must be 0..3")
            namespace = (
                "motor" if kind == "motor" else ("matrix" if entry.type in MATRICES else "laser")
            )
            if namespace == "matrix" and entry.id != 0:
                raise ValueError(f"Device {key}: the single Serial matrix uses placeholder id 0")
        elif isinstance(connection, CanOpenProtocol):
            allowed = (
                {"canopen-motor"} if kind == "motor" else {"canopen-laser", "canopen-led-matrix"}
            )
            if entry.type not in allowed:
                raise ValueError(
                    f"Device {key}: mapping {entry.type} is incompatible with direct CAN/{kind}"
                )
            if not 1 <= entry.id <= 127:
                raise ValueError(f"Device {key}: direct CAN node id must be 1..127")
            if kind == "light" and entry.subid > 254:
                raise ValueError(
                    f"Device {key}: light subid must be 0..254 for CANopen subindex channel+1"
                )
            if kind == "motor" and not 0 <= entry.subid <= 3:
                raise ValueError(f"Device {key}: motor subid must be 0..3")
            if entry.type == "canopen-led-matrix" and entry.subid != 0:
                raise ValueError(f"Device {key}: matrix commands do not use subid")
            # A CAN node has one firmware role: do not mix motor/laser/matrix nodes.
            namespace = (
                "motor" if kind == "motor" else ("matrix" if entry.type in MATRICES else "laser")
            )
        else:
            raise ValueError(f"Device {key}: unsupported hardware protocol {connection.protocol}")
        if (
            entry.type not in MATRICES
            and kind == "light"
            and (entry.pwm_max is None or entry.pwm_max > 65535)
        ):
            raise ValueError(f"Device {key}: PWM maximum must be in 1..65535")
        bus = self._bus_for(connection)
        resource = next(key for key, candidate in self.buses.items() if candidate is bus)
        used = self._outputs.setdefault(resource, set())
        address = (namespace, entry.id, entry.subid)
        if address in used:
            raise ValueError(
                f"Device {key}: output {address} is already mapped on this physical connection"
            )
        if isinstance(connection, CanOpenProtocol) and any(
            nid == entry.id and ns != namespace for ns, nid, _ in used
        ):
            raise ValueError(f"Device {key}: CAN node {entry.id} has conflicting device roles")
        used.add(address)
        return bus, entry

    def _bus_for(self, connection: Connection) -> HardwareBus:
        if not isinstance(connection, (Uc2RestProtocol, CanOpenProtocol)):
            raise ValueError("Hardware requires UC2 Serial or CANopen")
        t = connection.transport
        if isinstance(connection, Uc2RestProtocol):
            if not isinstance(t, SerialTransport):
                raise ValueError("UC2-REST runtime currently supports Serial only")
            # Pool by the resolved physical port, not by the selector spelling.
            t = t.model_copy(
                update={
                    "port": _serial_port(t),
                    "port_pattern": None,
                    "vid": None,
                    "pid": None,
                    "serial_number": None,
                }
            )
            connection = connection.model_copy(update={"transport": t})
        key = resource_key(t)
        if key is None:
            raise ValueError("Hardware connections must identify a physical resource")
        if key in self.buses:
            if self._connections[key] != connection:
                raise ValueError("Controllers sharing one connection disagree on protocol settings")
            return self.buses[key]
        if isinstance(connection, Uc2RestProtocol):
            if not isinstance(t, SerialTransport):
                raise ValueError("UC2-REST runtime currently supports Serial only")
            if (
                (t.bytesize, t.parity, t.stopbits, t.rtscts) != (8, "N", 1, False)
                or t.reset_on_connect
                or t.boot_delay
            ):
                raise ValueError(
                    "UC2 Serial requires 8N1 without flow control, explicit reset or boot delay"
                )
            if (
                t.timeout != 1
                or t.write_timeout != 1
                or connection.response_timeout != 2
                or connection.retries != 1
            ):
                raise ValueError(
                    "UC2 Serial timing uses client defaults; configure movement/homing deadlines per axis"
                )
            bus = UC2RestBus(UC2State(), UC2RestBusConfig(serialport=t.port, baudrate=t.baudrate))
        else:
            if not isinstance(t, CanTransport):
                raise ValueError("Direct CANopen requires a CAN transport")
            if connection.eds_file or connection.heartbeat_period_ms:
                raise ValueError("UC2 CAN runtime does not consume EDS/heartbeat overrides")
            if t.interface not in ("socketcan", "waveshare"):
                raise ValueError(f"UC2 CAN runtime does not support {t.interface}")
            bus = UC2CanBus(
                UC2State(),
                UC2CanBusConfig(
                    interface=t.interface,
                    channel=t.channel,
                    port=t.port,
                    bitrate=t.bitrate,
                    sdo_timeout=connection.sdo_timeout,
                ),
            )
        bus.on_connected = partial(self._reset_outputs, bus)
        self.buses[key] = bus
        self._connections[key] = connection
        return bus

    def _axis(self, axis: str) -> AxisRoute:
        try:
            return self.axes[axis.upper()]
        except KeyError as exc:
            raise ValueError(f"Axis {axis} is not configured") from exc

    async def amove_axis(
        self,
        axis: str,
        target: float,
        is_absolute: bool = False,
        speed: float | None = None,
        acceleration: float | None = None,
    ) -> float:
        """Enforce YAML limits before a command; serialize each axis until completion."""
        route = self._axis(axis)
        if any(bus.state.estop_active for bus in self.buses.values()):
            raise RuntimeError("Emergency stop is active")
        cfg = route.config
        async with self._locks[axis.upper()]:
            if cfg.homing_required and not route.homed:
                raise ValueError(f"Axis {axis} must be homed before moving")
            if speed is None:
                speed = (
                    cfg.vel.value
                    if cfg.vel and cfg.vel.value is not None
                    else route.bus.config.default_speed
                )
            if acceleration is None and cfg.acc:
                acceleration = cfg.acc.value
            if not math.isfinite(target) or not math.isfinite(speed) or speed <= 0:
                raise ValueError("Target and positive speed must be finite")
            if acceleration is not None and (not math.isfinite(acceleration) or acceleration <= 0):
                raise ValueError("Acceleration must be finite and positive")
            destination = target if is_absolute else await self.aget_position(axis) + target
            if cfg.pos and not cfg.pos.min <= destination <= cfg.pos.max:
                raise ValueError(f"Axis {axis}: target {destination} outside YAML travel limits")
            if cfg.vel and not cfg.vel.min <= speed <= cfg.vel.max:
                raise ValueError(f"Axis {axis}: speed outside YAML limits")
            if (
                acceleration is not None
                and cfg.acc
                and not cfg.acc.min <= acceleration <= cfg.acc.max
            ):
                raise ValueError(f"Axis {axis}: acceleration outside YAML limits")
            sign = -1 if cfg.inverted else 1
            scale = route.bus.scale_for_axis(route.hardware_axis)
            try:
                result = await route.bus.amove_axis(
                    route.hardware_axis,
                    target * sign,
                    is_absolute=is_absolute,
                    speed=speed,
                    acceleration=acceleration * scale if acceleration is not None else None,
                    timeout=cfg.move_timeout_s,
                )
            except BaseException:
                route.homed = False
                await self._abort(route)
                raise
            return result * sign

    async def _abort(self, route: AxisRoute) -> None:
        """Attempt a bounded stop without masking the original movement error."""
        try:
            await asyncio.shield(
                asyncio.wait_for(route.bus.astop_axis(route.hardware_axis), timeout=3)
            )
        except Exception:
            logger.exception("Stopping axis after failed command also failed")

    async def astop_axis(self, axis: str) -> None:
        """Stop is never queued behind a running movement."""
        route = self._axis(axis)
        route.homed = False
        await route.bus.astop_axis(route.hardware_axis)

    async def ahome_axis(self, axis: str) -> None:
        """Apply configured homing parameters; only mark homed on confirmed success."""
        route = self._axis(axis)
        if any(bus.state.estop_active for bus in self.buses.values()):
            raise RuntimeError("Emergency stop is active")
        cfg = route.config
        async with self._locks[axis.upper()]:
            route.homed = False
            direction = cfg.homing_direction
            if direction is not None and cfg.inverted:
                direction = -direction
            try:
                if isinstance(route.bus, UC2CanBus):
                    await route.bus.ahome_axis(
                        route.hardware_axis,
                        speed_steps=cfg.homing_speed_steps,
                        direction=direction,
                        timeout_ms=cfg.homing_timeout_ms,
                    )
                else:
                    await route.bus.ahome_axis(
                        route.hardware_axis,
                        timeout=cfg.homing_timeout_ms / 1000
                        if cfg.homing_timeout_ms is not None
                        else None,
                        speed_steps=cfg.homing_speed_steps,
                        direction=direction,
                        endstop_polarity=cfg.homing_endstop_polarity,
                    )
            except BaseException:
                await self._abort(route)
                raise
            route.homed = True

    async def aget_position(self, axis: str) -> float:
        """Read physical feedback in logical coordinates, including inversion."""
        route = self._axis(axis)
        value = await route.bus.aget_position(route.hardware_axis)
        if not math.isfinite(value):
            raise RuntimeError(f"Axis {axis}: invalid reported position")
        return -value if route.config.inverted else value

    async def aset_laser(self, channel: int, value: int) -> None:
        """Logical application slots select devices; mappings select real outputs."""
        route = self.lights.get(channel)
        if route is None:
            raise ValueError(f"Light slot {channel} is not configured")
        binding = route.binding
        maximum = route.pwm_max
        if not isinstance(value, int) or not 0 <= value <= maximum:
            raise ValueError(f"Light {channel}: PWM must be an integer in 0..{maximum}")
        if binding.type in MATRICES:
            await self._matrix_fill(route, value, value, value)
        elif isinstance(route.bus, UC2CanBus):
            await route.bus.aset_laser(binding.subid, value, node_id=binding.id)
        else:
            await route.bus.aset_laser(binding.id, value)

    async def _matrix_fill(self, route: LightRoute, r: int, g: int, b: int) -> None:
        if isinstance(route.bus, UC2CanBus):
            await route.bus.aled_fill(r, g, b, node_id=route.binding.id)
        else:
            await route.bus.aled_fill(r, g, b)

    def _matrix(self) -> LightRoute:
        for route in self.lights.values():
            if route.binding.type in MATRICES:
                return route
        raise ValueError("No LED matrix is configured")

    async def aled_fill(self, r: int, g: int, b: int) -> None:
        """The existing matrix API addresses one configured RGB matrix."""
        if any(not isinstance(v, int) or not 0 <= v <= 255 for v in (r, g, b)):
            raise ValueError("RGB values must be integers in 0..255")
        await self._matrix_fill(self._matrix(), r, g, b)

    async def aled_off(self) -> None:
        """Use the physical matrix off command."""
        route = self._matrix()
        if isinstance(route.bus, UC2CanBus):
            await route.bus.aled_off(node_id=route.binding.id)
        else:
            await route.bus.aled_off()

    async def ascan_nodes(self, timeout: float = 3.0) -> list[int]:
        """Aggregate nodes; duplicate node numbers on separate buses are indistinguishable in UC2State."""
        results = await asyncio.gather(*(b.ascan_nodes(timeout) for b in self.buses.values()))
        return sorted({nid for result in results for nid in result})

    async def _reset_outputs(self, bus: HardwareBus) -> None:
        """Reset outputs and reference status before exposing a new connection."""
        for route in self.axes.values():
            if route.bus is bus:
                route.homed = False
        entries = [route.binding for route in self.lights.values() if route.bus is bus]
        if isinstance(bus, UC2CanBus):
            can_client = bus._client
            assert can_client is not None
            for entry in entries:
                if entry.type in MATRICES:
                    await can_client.led_off(node_id=entry.id)
                else:
                    await can_client.laser_set(channel=entry.subid, pwm=0, node_id=entry.id)
        else:
            serial_client = bus._client
            assert serial_client is not None
            for entry in entries:
                if entry.type in MATRICES:
                    await serial_client.led_off()
                else:
                    await serial_client.set_laser(channel=entry.id, value=0)

        if self.illumination_state is not None:
            with acquired_locks("illumination"):
                for slot, route in self.lights.items():
                    if route.bus is bus:
                        source = next(
                            s for s in self.illumination_state.illuminations if s.slot == slot
                        )
                        source.intensity = 0
                        source.is_active = False

    async def _forward(self, bus: HardwareBus) -> None:
        async for event in bus.subscribe():
            if isinstance(event, (PositionUpdate, MotionDone, HomingChanged)):
                matches = [
                    (label, route)
                    for label, route in self.axes.items()
                    if route.bus is bus and route.hardware_axis == event.axis.upper()
                ]
                if not matches:
                    continue
                label, route = matches[0]
                event = replace(event, axis=label)
                if isinstance(event, (PositionUpdate, MotionDone)) and route.config.inverted:
                    event = replace(event, position=-event.position)
            if isinstance(event, EStopChanged):
                event = EStopChanged(active=any(b.state.estop_active for b in self.buses.values()))
                if event.active:
                    for route in self.axes.values():
                        route.homed = False
            self._broker.publish(event)

    async def _mirror_state(self) -> None:
        while True:
            states = [b.state for b in self.buses.values()]
            self.state.connected = bool(states) and all(s.connected for s in states)
            self.state.transport = "+".join(sorted({s.transport for s in states}))
            self.state.firmware = "; ".join(s.firmware for s in states if s.firmware)
            self.state.last_error = "; ".join(s.last_error for s in states if s.last_error)
            self.state.nodes_online = sorted({nid for s in states for nid in s.nodes_online})
            self.state.estop_active = any(s.estop_active for s in states)
            for route in self.axes.values():
                if not route.bus.state.connected:
                    route.homed = False
            await asyncio.sleep(0.1)

    async def abackground(self) -> None:
        """Own all pooled driver tasks and translated event subscriptions."""
        self._broker.bind_loop()
        async with asyncio.TaskGroup() as group:
            for bus in self.buses.values():
                group.create_task(self._forward(bus))
                group.create_task(bus.abackground())
            group.create_task(self._mirror_state())

    def subscribe(self) -> AsyncIterator[UC2Event]:
        """Subscribe to hardware events expressed in logical axis coordinates."""
        return self._broker.subscribe()

    async def aobjective_move(self, slot: int) -> None:
        """Reject commands without a configured objective actuator."""
        raise ValueError("No hardware objective actuator is configured")

    async def aobjective_home(self) -> None:
        """Reject commands without a configured objective actuator."""
        raise ValueError("No hardware objective actuator is configured")

    async def aobjective_status(self) -> dict[str, Any]:
        """Reject commands without a configured objective actuator."""
        raise ValueError("No hardware objective actuator is configured")

    async def agalvo_goto(self, x: int, y: int) -> None:
        """Reject commands without a configured galvo binding."""
        raise ValueError("No hardware galvo is configured")

    async def agalvo_raster(
        self,
        x_min: int,
        x_max: int,
        y_min: int,
        y_max: int,
        nx: int,
        ny: int,
        pixel_dwell_us: int = 1,
        trigger_mode: int = 1,
        bidirectional: bool = False,
    ) -> None:
        """Reject commands without a configured galvo binding."""
        raise ValueError("No hardware galvo is configured")

    async def agalvo_stop(self) -> None:
        """Reject commands without a configured galvo binding."""
        raise ValueError("No hardware galvo is configured")

    async def agalvo_status(self) -> dict[str, Any]:
        """Reject commands without a configured galvo binding."""
        raise ValueError("No hardware galvo is configured")
