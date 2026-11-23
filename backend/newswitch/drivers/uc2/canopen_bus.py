"""CANopen backend for the UC2 bus, built on the ``uc2canopen`` library.

Preferred transport for openUC2 hardware (faster and multi-node). Each
physical board is a CAN node; this adapter owns the axis/peripheral →
node-id map and the micrometer ↔ step conversion. The blocking
``uc2canopen`` client is driven through its asyncio facade
(``uc2canopen.aio.AsyncUC2Client``), which runs SDO transfers off-loop and
bridges TPDO/heartbeat telemetry onto the event loop.

Requires the optional dependency ``uc2canopen>=0.2.0`` (install the
``uc2`` extra).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from newswitch.drivers.uc2 import canopen_sdo
from newswitch.drivers.uc2 import firmware as fw
from newswitch.drivers.uc2.event_broker import UC2EventBroker
from newswitch.instrument.hardware import Firmware
from newswitch.models.uc2 import (
    BusError,
    HomingChanged,
    MotionDone,
    NodeSeen,
    PositionUpdate,
    UC2Event,
    UC2Node,
)
from newswitch.states.uc2 import UC2State

if TYPE_CHECKING:  # pragma: no cover
    from uc2canopen.aio import AsyncUC2Client

logger = logging.getLogger(__name__)


@dataclass
class UC2CanBusConfig:
    """Configuration for the CANopen transport (node map, scaling, link)."""

    interface: Optional[str] = None  # "socketcan" | "waveshare" | None (auto)
    channel: Optional[str] = None  # SocketCAN interface, e.g. "can0"
    port: Optional[str] = None  # Waveshare USB-CAN-A serial port
    bitrate: int = 500_000
    sdo_timeout: float = 2.0
    # Default openUC2 node map (one motor board per axis).
    node_x: int = 11
    node_y: int = 12
    node_z: int = 13
    node_a: int = 14
    node_led: int = 20
    node_laser: int = 21
    node_galvo: int = 30
    # Sub-axis index on the node (0-based) for boards driving several motors.
    # With one motor board per axis (default node map) these stay 0.
    sub_x: int = 0
    sub_y: int = 0
    sub_z: int = 0
    sub_a: int = 0
    # Steps per micrometer (per degree for axis A). Must match the mechanics.
    steps_per_um_x: float = 1.0
    steps_per_um_y: float = 1.0
    steps_per_um_z: float = 1.0
    steps_per_deg_a: float = 1.0
    default_speed: float = 5000.0  # micrometers per second
    home_speed_steps: int = 15000
    home_direction: int = -1
    home_timeout_ms: int = 20000
    # How each axis homes, by axis (X, Y, Z, A): any of direction (-1 / +1), speed (steps/s),
    # timeout_ms, release (steps to back off from the endstop after touching it) and polarity
    # (0 normally low, 1 normally high). What an axis leaves out is the home_* above; release
    # and polarity, then, what the node holds. Written to the node before every homing.
    homing: dict[str, dict[str, int]] = field(default_factory=dict)
    move_timeout_s: float = 120.0
    reconnect_backoff_initial_s: float = 1.0
    reconnect_backoff_max_s: float = 30.0
    # False: every motion command (moves, homing, the objective changer) is refused before it
    # reaches the board; stopping still works. For a frame whose stage must not move.
    allow_motion: bool = True
    # Objective changer, realized as a motor node driving between calibrated
    # slot positions (steps). Index 0 = slot 1, index 1 = slot 2, ...
    objective_node: int = 15
    objective_sub: int = 0
    objective_slot_positions_steps: list[int] = field(default_factory=lambda: [0, 20000])
    objective_speed_steps: int = 20000


#: How long a move has to say it runs before it is taken to be over: one to where the motor is,
#: or too short to show between two broadcasts (they come every 0.1 s or so while it runs).
MOVE_START_S = 0.6

#: How long a homing has to say it started before its node's last homing status counts as its
#: own end: it broadcasts a change at once, its regular TPDO every half second.
START_GRACE_S = 2.0


class UC2CanBus:
    """UC2BusManager implementation speaking CANopen via uc2canopen."""

    state: UC2State
    has_port_board = False

    def __init__(
        self,
        state: UC2State,
        config: Optional[UC2CanBusConfig] = None,
        firmware: Optional[Firmware] = None,
    ) -> None:
        """Initialize the CAN transport with shared bus state (no I/O yet)."""
        self.state = state
        self.config = config or UC2CanBusConfig()
        self.firmware = firmware
        self._broker = UC2EventBroker()
        self._client: Optional["AsyncUC2Client"] = None
        self._connected = asyncio.Event()
        self._objective_slot = 1

    # -- mapping helpers ---------------------------------------------------------

    def node_for_axis(self, axis: str) -> int:
        """Return the CAN node id serving a stage axis."""
        nodes = {
            "X": self.config.node_x,
            "Y": self.config.node_y,
            "Z": self.config.node_z,
            "A": self.config.node_a,
        }
        return nodes[axis.upper()]

    def sub_for_axis(self, axis: str) -> int:
        """Return the sub-axis index of a stage axis on its node."""
        subs = {
            "X": self.config.sub_x,
            "Y": self.config.sub_y,
            "Z": self.config.sub_z,
            "A": self.config.sub_a,
        }
        return subs[axis.upper()]

    def axis_for_node(self, node_id: int, sub: int = 0) -> Optional[str]:
        """Return the stage axis served by a CAN (node id, sub-axis), if any."""
        for axis in ("X", "Y", "Z", "A"):
            if self.node_for_axis(axis) == node_id and self.sub_for_axis(axis) == sub:
                return axis
        return None

    def scale_for_axis(self, axis: str) -> float:
        """Return steps-per-micrometer (steps-per-degree for A) of an axis."""
        scales = {
            "X": self.config.steps_per_um_x,
            "Y": self.config.steps_per_um_y,
            "Z": self.config.steps_per_um_z,
            "A": self.config.steps_per_deg_a,
        }
        return scales[axis.upper()]

    def to_steps(self, axis: str, value: float) -> int:
        """Convert micrometers (degrees for A) into hardware steps."""
        return int(round(value * self.scale_for_axis(axis)))

    def to_units(self, axis: str, steps: float) -> float:
        """Convert hardware steps into micrometers (degrees for A)."""
        return steps / self.scale_for_axis(axis)

    def homing_for_axis(self, axis: str) -> dict[str, int]:
        """How an axis homes: its own settings over the home_* defaults."""
        own = {str(key).upper(): value for key, value in self.config.homing.items()}.get(
            axis.upper(), {}
        )
        unknown = set(own) - {"direction", "speed", "timeout_ms", "release", "polarity"}
        if unknown:
            raise ValueError(f"homing of axis {axis}: unknown {sorted(unknown)}")
        return {
            "direction": self.config.home_direction,
            "speed": self.config.home_speed_steps,
            "timeout_ms": self.config.home_timeout_ms,
            **own,
        }

    # -- lifecycle ------------------------------------------------------------------

    async def abackground(self) -> None:
        """Keep the CAN link alive: connect, pump events, reconnect with backoff.

        Transport errors never kill the agent — they surface as `BusError`
        events + `UC2State.last_error`, and the link is retried with
        exponential backoff (capped) until the task is cancelled.
        """
        backoff = self.config.reconnect_backoff_initial_s
        while True:
            try:
                await self._connect_and_pump()
                backoff = (
                    self.config.reconnect_backoff_initial_s
                )  # normal exit (never happens today, pump is endless)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.last_error = str(exc)
                self._broker.publish(BusError(message=str(exc)))
                logger.warning("UC2 CAN bus error: %s — reconnecting in %.0f s", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.config.reconnect_backoff_max_s)

    async def _connect_and_pump(self) -> None:
        """One connection lifetime: open the bus, translate events until failure."""
        try:
            from uc2canopen.aio import (
                AsyncUC2Client,
                HeartbeatEvent,
                HomingChangedEvent,
                MotorDoneEvent,
                MotorUpdateEvent,
            )
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "uc2canopen is not installed; install newswitch with the 'uc2' "
                "extra (uv pip install -e '.[uc2]') or pip install uc2canopen."
            ) from exc

        self._broker.bind_loop()
        client = await AsyncUC2Client.create(
            interface=self.config.interface,
            channel=self.config.channel,
            port=self.config.port,
            bitrate=self.config.bitrate,
            sdo_timeout=self.config.sdo_timeout,
        )
        self._client = client
        self.state.connected = True
        self.state.transport = "canopen"
        self._connected.set()
        logger.info("UC2 CAN bus connected (%r)", client.sync)

        try:
            async for event in client.events():
                if isinstance(event, MotorUpdateEvent):
                    axis = self.axis_for_node(event.node_id, event.axis)
                    if axis is not None:
                        self._broker.publish(
                            PositionUpdate(axis=axis, position=self.to_units(axis, event.position))
                        )
                elif isinstance(event, MotorDoneEvent):
                    axis = self.axis_for_node(event.node_id, event.axis)
                    if axis is not None:
                        self._broker.publish(
                            MotionDone(axis=axis, position=self.to_units(axis, event.position))
                        )
                elif isinstance(event, HomingChangedEvent):
                    axis = self.axis_for_node(event.node_id, event.axis)
                    if axis is not None:
                        self._broker.publish(HomingChanged(axis=axis, status=event.status))
                elif isinstance(event, HeartbeatEvent):
                    if event.node_id not in self.state.nodes_online:
                        self.state.nodes_online = sorted(
                            set(self.state.nodes_online) | {event.node_id}
                        )
                    self._broker.publish(NodeSeen(node_id=event.node_id, nmt_state=event.nmt_state))
        finally:
            self.state.connected = False
            self._connected.clear()
            self._client = None
            await client.aclose()

    def _may_move(self, what: str) -> None:
        """Refuse a motion command when the board's motion is disabled (``allow_motion: false``).

        Raises:
            PermissionError: It is.
        """
        if not self.config.allow_motion:
            raise PermissionError(
                f"{what}: motion is disabled on this board (allow_motion: false); nothing was sent"
            )

    async def _require_client(self, timeout: float = 30.0) -> "AsyncUC2Client":
        """Wait for the background connection and return the async client."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "UC2 CAN bus is not connected — the background task is not "
                "running, or the CAN adapter/hardware is unreachable "
                f"(last error: {self.state.last_error or 'none'})."
            ) from None
        assert self._client is not None
        return self._client

    # -- stage ---------------------------------------------------------------------

    async def amove_axis(
        self,
        axis: str,
        target: float,
        is_absolute: bool = False,
        speed: Optional[float] = None,
        acceleration: Optional[float] = None,
    ) -> float:
        """Move one axis (event-driven wait on the TPDO done edge)."""
        self._may_move("amove_axis")
        client = await self._require_client()
        speed_steps = int(abs((speed or self.config.default_speed) * self.scale_for_axis(axis)))
        steps = self.to_steps(axis, target)
        final_steps = await self._move_and_wait(
            client,
            node=self.node_for_axis(axis),
            sub=self.sub_for_axis(axis),
            steps=steps,
            speed=max(speed_steps, 1),
            acceleration=int(acceleration or 0),
            is_absolute=is_absolute,
        )
        return self.to_units(axis, final_steps)

    async def _move_and_wait(
        self,
        client: "AsyncUC2Client",
        node: int,
        sub: int,
        steps: int,
        speed: int,
        acceleration: int = 0,
        is_absolute: bool = True,
    ) -> int:
        """Start a move and return once it is over: where it went (absolute), or where the node
        says it is (relative).

        A node says it runs, and then that it stopped; a move to where it is, or one shorter than
        between two of its broadcasts, never says it runs. So: over once it was seen running and
        is not, or once it was not seen running within `MOVE_START_S`. (uc2canopen's own wait
        knows only the first, and waits out its timeout on the others.) Cancelled, the motor is
        stopped.
        """
        loop = asyncio.get_running_loop()
        await client.move(
            axis=sub,
            position=steps,
            speed=speed,
            acceleration=acceleration,
            is_absolute=is_absolute,
            node_id=node,
        )
        started = loop.time()
        seen_running = False
        try:
            while True:
                motor = client.sync._listener.get_motor(node, sub)  # noqa: SLF001 - TPDO cache
                running = bool(motor is not None and motor.seen and motor.running)
                if running:
                    seen_running = True
                elif seen_running or loop.time() - started > MOVE_START_S:
                    break
                if loop.time() - started > self.config.move_timeout_s:
                    raise TimeoutError(f"node {node} still moving after {self.config.move_timeout_s:.0f} s")
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            await asyncio.shield(client.stop(axis=sub, node_id=node))
            raise
        if is_absolute:
            return steps
        motor = client.sync._listener.get_motor(node, sub)  # noqa: SLF001
        return int(motor.position) if motor is not None else 0

    async def astop_axis(self, axis: str) -> None:
        """Stop one axis via the motor command word."""
        client = await self._require_client()
        await client.stop(axis=self.sub_for_axis(axis), node_id=self.node_for_axis(axis))

    async def ahome_axis(self, axis: str) -> None:
        """Home one axis, as its homing settings say, and wait for the homing-done status."""
        self._may_move("ahome_axis")
        client = await self._require_client()
        homing = self.homing_for_axis(axis)
        node, sub = self.node_for_axis(axis), self.sub_for_axis(axis)
        await self._write_homing(client, node, sub, homing)
        await client.home(
            axis=sub,
            speed=homing["speed"],
            direction=homing["direction"],
            timeout_ms=homing["timeout_ms"],
            node_id=node,
        )
        homed = await self._homed(client, node, sub, homing["timeout_ms"] / 1000.0 + 10.0)
        if not homed:
            raise RuntimeError(f"Homing axis {axis} failed or timed out")

    @staticmethod
    async def _homed(client: "AsyncUC2Client", node: int, sub: int, timeout: float) -> bool:
        """Whether the homing just started ends done (not timed out), as the node broadcasts it.

        A node keeps saying "done" of its last homing until the next one starts: so first its
        "homing", then its end. A homing that ends before its "homing" is seen (an axis that
        sits on its endstop) is taken from the status once `START_GRACE_S` passed.
        """
        homing, done, timed_out = 1, 2, 3
        loop = asyncio.get_running_loop()
        started = loop.time()
        seen_homing = False
        while loop.time() - started < timeout:
            motor = client.sync._listener.get_motor(node, sub)  # noqa: SLF001 - the TPDO cache
            status = None if motor is None or not motor.seen else motor.homing_status
            if status == homing:
                seen_homing = True
            elif status in (done, timed_out) and (
                seen_homing or loop.time() - started > START_GRACE_S
            ):
                return status == done
            await asyncio.sleep(0.05)
        return False

    @staticmethod
    async def _write_homing(
        client: "AsyncUC2Client", node: int, sub: int, homing: dict[str, int]
    ) -> None:
        """Write the endstop's polarity and the back-off to the node, where they are given."""
        from uc2canopen.od import OD

        sdo = client.sync._sdo  # noqa: SLF001 - uc2canopen has no call for these two
        if "polarity" in homing:
            await asyncio.to_thread(
                sdo.write_u8, node, OD.HOMING_ENDSTOP_POLARITY, sub + 1, homing["polarity"]
            )
        if "release" in homing:
            await asyncio.to_thread(
                sdo.write_i32, node, OD.HOMING_ENDSTOP_RELEASE, sub + 1, homing["release"]
            )

    async def aget_position(self, axis: str) -> float:
        """Read one axis position (TPDO cache preferred)."""
        client = await self._require_client()
        steps = await client.get_position(
            axis=self.sub_for_axis(axis), node_id=self.node_for_axis(axis)
        )
        return self.to_units(axis, steps)

    # -- bus / fleet --------------------------------------------------------------

    async def ascan_nodes(self, timeout: float = 3.0) -> list[UC2Node]:
        """The online CAN nodes (heard for `timeout` seconds), each asked what it runs."""
        client = await self._require_client()
        ids = sorted(await client.scan_nodes(timeout=timeout))
        self.state.nodes_online = sorted(set(self.state.nodes_online) | set(ids))

        def identities() -> list[UC2Node]:
            attached = canopen_sdo.attach(client.sync, self.config.sdo_timeout)
            try:
                return [
                    fw.wanting(
                        fw.node_from_scan(
                            {
                                "canId": can_id,
                                "statusStr": "online",
                                **canopen_sdo.read_identity(attached, can_id),
                            }
                        ),
                        self.firmware,
                    )
                    for can_id in ids
                ]
            finally:
                attached.detach()

        return await asyncio.to_thread(identities)

    async def aidentify(self) -> Optional[UC2Node]:
        """None: on socketcan no board is on a port, only CAN nodes."""
        return None

    # -- firmware ----------------------------------------------------------------

    async def aflash_board(self, image: "fw.FirmwareImage", report: "fw.Report") -> None:
        """No board is on a port of a CAN bus: flash a master over its own USB (transport rest)."""
        raise RuntimeError(
            "a canopen bus has no board on a port: flash the master over its USB (transport: rest)"
        )

    async def aflash_node(
        self, can_id: int, image: "fw.FirmwareImage", report: "fw.Report"
    ) -> None:
        """Send `image` to a node's OTA over SDO; it reboots into it."""
        client = await self._require_client()
        loop = asyncio.get_running_loop()
        data = await asyncio.to_thread(image.path.read_bytes)

        def progress(percent: int) -> None:
            loop.call_soon_threadsafe(report, f"sending {image.path.name}", percent)

        def send() -> None:
            attached = canopen_sdo.attach(client.sync, max(self.config.sdo_timeout, 5.0))
            try:
                canopen_sdo.flash_node(attached, can_id, data, progress)
            finally:
                attached.detach()

        await asyncio.to_thread(send)

    # -- objective changer ---------------------------------------------------------

    async def aobjective_move(self, slot: int) -> None:
        """Drive the objective motor node to the calibrated slot position."""
        self._may_move("aobjective_move")
        positions = self.config.objective_slot_positions_steps
        if not 1 <= slot <= len(positions):
            raise ValueError(f"Objective slot {slot} out of range 1..{len(positions)}")
        client = await self._require_client()
        await self._move_and_wait(
            client,
            node=self.config.objective_node,
            sub=self.config.objective_sub,
            steps=positions[slot - 1],
            speed=self.config.objective_speed_steps,
        )
        self._objective_slot = slot

    async def aobjective_home(self) -> None:
        """Home the objective motor node."""
        self._may_move("aobjective_home")
        client = await self._require_client()
        homed = await client.home_and_wait(
            axis=self.config.objective_sub,
            speed=self.config.home_speed_steps,
            direction=self.config.home_direction,
            timeout_ms=self.config.home_timeout_ms,
            node_id=self.config.objective_node,
            timeout=self.config.home_timeout_ms / 1000.0 + 10.0,
        )
        if not homed:
            raise RuntimeError("Homing the objective changer failed or timed out")
        self._objective_slot = 1

    async def aobjective_status(self) -> dict[str, Any]:
        """Return the last commanded objective slot and node position."""
        client = await self._require_client()
        position = await client.get_position(
            axis=self.config.objective_sub, node_id=self.config.objective_node
        )
        return {"slot": self._objective_slot, "position_steps": position}

    # -- illumination -----------------------------------------------------------------

    async def aset_laser(self, channel: int, value: int, node: Optional[int] = None) -> None:
        """Set a laser PWM channel on `node`, by default the laser node (the illumination board's
        white LED is a laser channel of its own node)."""
        client = await self._require_client()
        node_id = self.config.node_laser if node is None else node
        await client.laser_set(channel=channel, pwm=value, node_id=node_id)

    async def aled_fill(self, r: int, g: int, b: int) -> None:
        """Fill the LED matrix on the LED node."""
        client = await self._require_client()
        await client.led_fill(r=r, g=g, b=b, node_id=self.config.node_led)

    async def aled_off(self) -> None:
        """Turn the LED matrix off."""
        client = await self._require_client()
        await client.led_off(node_id=self.config.node_led)

    # -- galvo -----------------------------------------------------------------------

    async def agalvo_goto(self, x: int, y: int) -> None:
        """Issue a galvo GOTO via the command-word doorbell."""
        client = await self._require_client()
        await client.galvo_goto(x=x, y=y, node_id=self.config.node_galvo)

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
        """Configure and start a raster scan on the galvo node."""
        client = await self._require_client()
        await client.galvo_raster_scan(
            node_id=self.config.node_galvo,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            nx=nx,
            ny=ny,
            sample_period_us=pixel_dwell_us,
            enable_trigger=trigger_mode,
            bidirectional=bidirectional,
        )

    async def agalvo_stop(self) -> None:
        """Stop the galvo scan (CMD_STOP doorbell, never writes 0)."""
        client = await self._require_client()
        await client.galvo_stop(node_id=self.config.node_galvo)

    async def agalvo_status(self) -> dict[str, Any]:
        """Read decoded galvo status flags."""
        client = await self._require_client()
        return await client.galvo_status(node_id=self.config.node_galvo)

    # -- events -----------------------------------------------------------------------

    def subscribe(self) -> AsyncIterator[UC2Event]:
        """Yield typed UC2 events translated from CAN telemetry."""
        return self._broker.subscribe()
