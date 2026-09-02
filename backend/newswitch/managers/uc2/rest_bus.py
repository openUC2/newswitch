"""JSON-over-serial backend for the UC2 bus, built on the ``uc2rest`` library.

Drop-in alternative to the CANopen transport for single-board (ESP32 master)
setups. The mature, blocking ``uc2rest`` client is reused as-is through its
asyncio facade (``uc2rest.aio.AsyncUC2Client``): blocking verbs run off-loop,
and the firmware's pattern-keyed serial events (``steppers``, ``home``,
``emergency``, ``message``) are translated into the shared typed event model.

Requires the optional dependency ``uc2-rest`` (install the ``uc2`` extra).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from rekuest_next import model

from newswitch.managers.uc2.event_broker import UC2EventBroker
from newswitch.protocols.uc2 import (
    BusError,
    ButtonPressed,
    EStopChanged,
    HomingChanged,
    MotionDone,
    PositionUpdate,
    UC2Event,
    UC2State,
)

if TYPE_CHECKING:  # pragma: no cover
    from uc2rest.aio import AsyncUC2Client

logger = logging.getLogger(__name__)

# Firmware stepper ids: A=0, X=1, Y=2, Z=3 (uc2rest convention).
STEPPER_ID_TO_AXIS = {0: "A", 1: "X", 2: "Y", 3: "Z"}


@model
@dataclass
class UC2RestBusConfig:
    """Configuration for the serial (uc2rest) transport."""

    serialport: Optional[str] = None  # None = autodetect
    baudrate: int = 115200
    identity: str = "UC2_Feather"
    device_id: Optional[str] = None
    require_master: bool = False
    # Steps per micrometer (per degree for axis A). Must match the mechanics.
    steps_per_um_x: float = 1.0
    steps_per_um_y: float = 1.0
    steps_per_um_z: float = 1.0
    steps_per_deg_a: float = 1.0  # TODO: How do we deal with additional axes?
    default_speed: float = 5000.0  # micrometers per second
    move_timeout_s: float = 120.0
    home_timeout_s: float = 30.0
    reconnect_backoff_initial_s: float = 1.0
    reconnect_backoff_max_s: float = 30.0
    # Minimum spacing of PositionUpdate events per axis; the firmware's
    # `steppers` stream can flood during fast moves.
    position_update_min_interval_s: float = 0.05


class UC2RestBus:
    """UC2BusManager implementation speaking the UC2-REST serial JSON protocol."""

    state: UC2State

    def __init__(self, state: UC2State, config: Optional[UC2RestBusConfig] = None) -> None:
        """Initialize the serial transport with shared bus state (no I/O yet)."""
        self.state = state
        self.config = config or UC2RestBusConfig()
        self._broker = UC2EventBroker()
        self._client: Optional["AsyncUC2Client"] = None
        self._connected = asyncio.Event()
        self._last_position_publish: dict[str, float] = {}

    # -- mapping helpers -----------------------------------------------------------

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

    # -- lifecycle -------------------------------------------------------------------

    async def abackground(self) -> None:
        """Keep the serial link alive: connect, pump events, reconnect with backoff.

        Transport errors never kill the agent — they surface as `BusError`
        events + `UC2State.last_error`, and the link is retried with
        exponential backoff (capped) until the task is cancelled.
        """
        backoff = self.config.reconnect_backoff_initial_s
        while True:
            try:
                await self._connect_and_pump()
                backoff = self.config.reconnect_backoff_initial_s
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.last_error = str(exc)
                self._broker.publish(BusError(message=str(exc)))
                logger.warning("UC2 serial bus error: %s — reconnecting in %.0f s", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.config.reconnect_backoff_max_s)

    def _publish_position_throttled(self, axis: str, position: float) -> None:
        """Publish a PositionUpdate, rate-limited per axis."""
        now = asyncio.get_running_loop().time()
        last = self._last_position_publish.get(axis, 0.0)
        if now - last >= self.config.position_update_min_interval_s:
            self._last_position_publish[axis] = now
            self._broker.publish(PositionUpdate(axis=axis, position=position))

    async def _connect_and_pump(self) -> None:
        """One connection lifetime: open the serial link, translate events until failure."""
        try:
            from uc2rest.aio import (
                AsyncUC2Client,
                EmergencyEvent,
                HomeEvent,
                MessageEvent,
                SteppersEvent,
            )
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "uc2rest is not installed; install newswitch with the 'uc2' "
                "extra (uv pip install -e '.[uc2]') or pip install uc2-rest."
            ) from exc

        self._broker.bind_loop()
        client = await AsyncUC2Client.create(
            serialport=self.config.serialport,
            baudrate=self.config.baudrate,
            identity=self.config.identity,
            device_id=self.config.device_id,
            requireMaster=self.config.require_master,
        )
        if not client.is_connected:
            # uc2rest degrades to a MockSerial dummy when no board answers;
            # treat that as a connection failure so the backoff loop keeps
            # retrying until the hardware (re)appears.
            await client.aclose()
            raise RuntimeError(
                "no UC2 board answered on the serial port "
                f"(port={self.config.serialport or 'auto'}, "
                f"baud={self.config.baudrate}) — got the mock fallback"
            )

        self._client = client
        self.state.connected = True
        self.state.transport = "rest"
        try:
            info = await client.get_firmware_info()
            self.state.firmware = str(info) if info else ""
        except Exception:  # firmware info is best-effort
            logger.debug("Could not read firmware info", exc_info=True)
        self._connected.set()
        logger.info("UC2 serial bus connected (port=%s)", self.config.serialport)

        try:
            async for event in client.events():
                if isinstance(event, SteppersEvent):
                    for stepper in event.steppers:
                        axis = STEPPER_ID_TO_AXIS.get(stepper.get("stepperid", -1))
                        position = stepper.get("position")
                        if axis is not None and position is not None:
                            self._publish_position_throttled(axis, self.to_units(axis, position))
                elif isinstance(event, HomeEvent):
                    axis = str(event.data.get("axis", "")).upper() or "X"
                    is_homed = bool(event.data.get("isHomed", event.data.get("state", 0)))
                    self._broker.publish(HomingChanged(axis=axis, status=2 if is_homed else 1))
                elif isinstance(event, EmergencyEvent):
                    active = bool(event.data.get("active", 1))
                    self.state.estop_active = active
                    self._broker.publish(EStopChanged(active=active))
                elif isinstance(event, MessageEvent):
                    self._broker.publish(
                        ButtonPressed(
                            key=str(event.key) if event.key is not None else None, data=event.data
                        )
                    )
        finally:
            self.state.connected = False
            self._connected.clear()
            self._client = None
            await client.aclose()

    async def _require_client(self, timeout: float = 30.0) -> "AsyncUC2Client":
        """Wait for the background connection and return the async client."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "UC2 serial bus is not connected — the background task is not "
                "running, or no UC2 board answered on the serial port "
                f"(last error: {self.state.last_error or 'none'})."
            ) from None
        assert self._client is not None
        return self._client

    # -- stage -----------------------------------------------------------------------

    async def amove_axis(
        self,
        axis: str,
        target: float,
        is_absolute: bool = False,
        speed: Optional[float] = None,
        acceleration: Optional[float] = None,
    ) -> float:
        """Move one axis; the firmware-blocking wait runs in a worker thread."""
        client = await self._require_client()
        speed_steps = int(abs((speed or self.config.default_speed) * self.scale_for_axis(axis)))
        await client.move_axis(
            axis=axis.upper(),
            steps=self.to_steps(axis, target),
            speed=max(speed_steps, 1),
            acceleration=int(acceleration) if acceleration else None,
            is_absolute=is_absolute,
            is_blocking=True,
            timeout=self.config.move_timeout_s,
        )
        position = await self.aget_position(axis)
        self._broker.publish(MotionDone(axis=axis.upper(), position=position))
        return position

    async def astop_axis(self, axis: str) -> None:
        """Stop one axis."""
        client = await self._require_client()
        await client.stop(axis=axis.upper())

    async def ahome_axis(self, axis: str) -> None:
        """Home one axis (blocking wait off-loop)."""
        client = await self._require_client()
        await client.home_axis(
            axis=axis.upper(), is_blocking=True, timeout=self.config.home_timeout_s
        )

    async def aget_position(self, axis: str) -> float:
        """Read one axis position from the firmware position table."""
        client = await self._require_client()
        axis_index = {"A": 0, "X": 1, "Y": 2, "Z": 3}[axis.upper()]
        # get_position itself indexes the firmware reply, which degrades to
        # non-list values on mock/absent hardware — treat any failure as 0.
        try:
            positions = await client.get_positions()
            steps = positions[axis_index]
        except (TypeError, IndexError, KeyError):
            steps = 0.0
        return self.to_units(axis, steps)

    # -- bus / fleet --------------------------------------------------------------

    async def ascan_nodes(self, timeout: float = 3.0) -> list[int]:
        """Ask the master firmware for reachable CAN devices."""
        client = await self._require_client()
        try:
            devices = await client.can_scan()
        except Exception as exc:
            logger.warning("CAN scan via master failed: %s", exc)
            return []
        nodes: list[int] = []
        if isinstance(devices, (list, tuple)):
            for device in devices:
                if isinstance(device, int):
                    nodes.append(device)
                elif isinstance(device, dict) and "canId" in device:
                    nodes.append(int(device["canId"]))
        self.state.nodes_online = sorted(set(self.state.nodes_online) | set(nodes))
        return sorted(nodes)

    # -- objective changer ---------------------------------------------------------

    async def aobjective_move(self, slot: int) -> None:
        """Move the objective slider to a slot via the firmware objective module."""
        client = await self._require_client()
        await client.objective_move(slot=slot, is_blocking=True)

    async def aobjective_home(self) -> None:
        """Home the objective slider."""
        client = await self._require_client()
        await client.objective_home(is_blocking=True)

    async def aobjective_status(self) -> dict[str, Any]:
        """Read the objective slider status from the firmware."""
        client = await self._require_client()
        status = await client.objective_status()
        return status if isinstance(status, dict) else {"raw": status}

    # -- illumination -------------------------------------------------------------------

    async def aset_laser(self, channel: int, value: int) -> None:
        """Set a laser/LED PWM channel."""
        client = await self._require_client()
        await client.set_laser(channel=channel, value=value)

    async def aled_fill(self, r: int, g: int, b: int) -> None:
        """Fill the LED matrix with one colour."""
        client = await self._require_client()
        await client.led_fill(r=r, g=g, b=b)

    async def aled_off(self) -> None:
        """Turn the LED matrix off."""
        client = await self._require_client()
        await client.led_off()

    # -- galvo -------------------------------------------------------------------------

    async def agalvo_goto(self, x: int, y: int) -> None:
        """Move the galvo to an absolute XY position."""
        client = await self._require_client()
        await client.galvo_goto(x=x, y=y)

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
        """Configure and start a raster scan via /galvo_act."""
        client = await self._require_client()
        await client.galvo_scan(
            nx=nx,
            ny=ny,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )

    async def agalvo_stop(self) -> None:
        """Stop the galvo scan (stop code, qid-echo handled by uc2rest)."""
        client = await self._require_client()
        await client.galvo_stop()

    async def agalvo_status(self) -> dict[str, Any]:
        """Read the galvo status."""
        client = await self._require_client()
        status = await client.galvo_status()
        return status if isinstance(status, dict) else {"raw": status}

    # -- events -----------------------------------------------------------------------

    def subscribe(self) -> AsyncIterator[UC2Event]:
        """Yield typed UC2 events translated from serial telemetry."""
        return self._broker.subscribe()
