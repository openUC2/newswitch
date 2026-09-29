"""Device connection models (see ``backend/docs/connection-reference.md``).

Layout (flat protocol properties, nested transport)::

    connection:
      protocol: <name>
      <protocol properties>
      transport:
        type: <name>
        <transport properties>
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Self, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    WithJsonSchema,
    model_validator,
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


STOPBITS = (1, 1.5, 2)


def _check_stopbits(value: float) -> float:
    """Allow only the stop-bit counts a UART supports (1, 1.5, 2).

    `Literal[1, 1.5, 2]` would express this more directly, but float values are not
    permitted in `Literal` (PEP 586).

    Args:
        value: The configured number of stop bits.

    Returns:
        `value` unchanged.

    Raises:
        ValueError: Any other value.
    """
    if value not in STOPBITS:
        raise ValueError(f"stopbits must be one of {STOPBITS}, got {value}")
    return value


StopBits = Annotated[
    float,
    AfterValidator(_check_stopbits),
    WithJsonSchema({"type": "number", "enum": list(STOPBITS)}),
]


# =====================================================================
# Transports
# =====================================================================


class _UartSettings(_Base):
    """Settings shared by all UART-based transports (TTL/RS232, RS422, RS485)."""

    # selector: explicit port or matching criteria
    port: str | None = None  # "/dev/ttyUSB0", "COM3", "/dev/serial/by-id/..."
    port_pattern: str | None = None  # glob, e.g. "/dev/serial/by-id/*CP2102*"
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None

    # line settings
    baudrate: int = 115200
    bytesize: Literal[5, 6, 7, 8] = 8
    parity: Literal["N", "E", "O", "M", "S"] = "N"
    stopbits: StopBits = 1
    timeout: float = 1.0
    write_timeout: float | None = 1.0
    rtscts: bool = False

    @model_validator(mode="after")
    def _need_selector(self) -> Self:
        if not any([self.port, self.port_pattern, self.vid, self.serial_number]):
            raise ValueError(
                f"{type(self).__name__} needs port, port_pattern, vid or serial_number"
            )
        return self


class SerialTransport(_UartSettings):
    """USB-UART / RS232 / TTL, e.g. a directly attached ESP32."""

    type: Literal["serial"] = "serial"
    reset_on_connect: bool = False  # toggle DTR/RTS -> ESP32 reset
    boot_delay: float = 0.0  # seconds to wait after open


class Rs422Transport(_UartSettings):
    """Differential, full-duplex UART via an RS422 adapter.

    Same line settings as serial, but no DTR/RTS-based MCU reset:
    those lines are not wired to the target on an RS422 link.
    """

    type: Literal["rs422"] = "rs422"


class Rs485Transport(_UartSettings):
    """Differential, half-duplex, multidrop UART via an RS485 adapter.

    Half duplex means the driver direction must be switched between
    transmit and receive:
      auto     -> the adapter switches by itself (most USB-RS485 adapters)
      kernel   -> Linux driver toggles RTS (TIOCSRS485, e.g. UART + transceiver on a Pi)
      software -> pyserial toggles RTS from Python (timing not guaranteed)
    """

    type: Literal["rs485"] = "rs485"
    direction_control: Literal["auto", "kernel", "software"] = "auto"
    rts_level_for_tx: bool = True
    rts_level_for_rx: bool = False
    delay_before_tx: float | None = None  # seconds
    delay_before_rx: float | None = None  # seconds
    echo: bool = False  # adapter echoes own TX bytes -> driver discards them

    @model_validator(mode="after")
    def _no_hw_flow_control(self) -> Self:
        if self.rtscts:
            raise ValueError("rtscts is not available on RS485 (RTS is used for direction control)")
        return self


class HttpTransport(_Base):
    """HTTP(S) connection, e.g. uc2-rest over Wi-Fi/Ethernet."""

    type: Literal["http"] = "http"
    host: str  # IP or mDNS name ("uc2-abc.local")
    port: int | None = None  # None -> 80/443 depending on scheme
    scheme: Literal["http", "https"] = "http"
    base_path: str = ""
    timeout: float = 5.0
    verify_ssl: bool = True
    token: SecretStr | None = None
    ws_path: str | None = None  # optional push channel


class TcpTransport(_Base):
    """Raw TCP socket."""

    type: Literal["tcp"] = "tcp"
    host: str
    port: int = Field(ge=1, le=65535)
    timeout: float = 5.0
    terminator: str = "\n"
    keepalive: bool = True


class CanTransport(_Base):
    """CAN bus interface (based on python-can)."""

    type: Literal["can"] = "can"
    interface: Literal["socketcan", "pcan", "kvaser", "slcan", "gs_usb", "virtual"] = "socketcan"
    channel: str = "can0"
    bitrate: int = 500_000


class I2cTransport(_Base):
    """I2C bus + slave address (the address is part of the I2C link layer).

    Bus speed is not configurable from user space on Linux; on a Raspberry Pi
    it is set in config.txt (dtparam=i2c_arm_baudrate=...).
    """

    type: Literal["i2c"] = "i2c"
    bus: int = 1  # /dev/i2c-<bus>
    address: int = Field(ge=0, le=0x3FF)
    ten_bit: bool = False
    force: bool = False  # access even if a kernel driver claims the address

    @model_validator(mode="after")
    def _check_address(self) -> Self:
        if not self.ten_bit and not 0x03 <= self.address <= 0x77:
            raise ValueError(f"7-bit I2C address must be 0x03..0x77, got {self.address:#04x}")
        return self


Transport = Union[
    SerialTransport,
    Rs422Transport,
    Rs485Transport,
    HttpTransport,
    TcpTransport,
    CanTransport,
    I2cTransport,
]


# =====================================================================
# Protocols (protocol properties live flat next to `protocol`)
# =====================================================================


class Uc2RestProtocol(_Base):
    """JSON command protocol of openUC2 controllers (ESP32 firmware)."""

    protocol: Literal["uc2-rest"] = "uc2-rest"
    response_timeout: float = 2.0
    retries: int = 1
    transport: Annotated[
        Union[SerialTransport, Rs422Transport, HttpTransport, TcpTransport],
        Field(discriminator="type"),
    ]


class CanOpenProtocol(_Base):
    """CANopen device (node) on a CAN bus."""

    protocol: Literal["canopen"] = "canopen"
    node_id: int = Field(ge=1, le=127)
    eds_file: Path | None = None
    sdo_timeout: float = 0.5
    heartbeat_period_ms: int | None = None
    transport: CanTransport = CanTransport()


class RegisterMapProtocol(_Base):
    """Register read/write devices (sensors, DACs, IO expanders, ...)."""

    protocol: Literal["register-map"] = "register-map"
    register_width: Literal[8, 16] = 8  # width of the register address
    byte_order: Literal["big", "little"] = "big"
    register_file: Path | None = None  # optional register description (like an EDS)
    retries: int = 2
    transport: I2cTransport  # later: Union[I2cTransport, SpiTransport] + discriminator


class ModbusProtocol(_Base):
    """Modbus RTU/ASCII on serial lines (typically RS485 multidrop) or Modbus TCP."""

    protocol: Literal["modbus"] = "modbus"
    unit_id: int = Field(ge=0, le=255)  # slave address; 1..247 on serial lines
    framing: Literal["rtu", "ascii", "mbap"] | None = None  # None -> mbap on tcp, rtu otherwise
    response_timeout: float = 0.5
    retries: int = 2
    transport: Annotated[
        Union[Rs485Transport, Rs422Transport, SerialTransport, TcpTransport],
        Field(discriminator="type"),
    ]

    @model_validator(mode="after")
    def _check(self) -> Self:
        is_tcp = isinstance(self.transport, TcpTransport)
        if self.framing == "mbap" and not is_tcp:
            raise ValueError("framing 'mbap' (Modbus TCP) requires a tcp transport")
        if not is_tcp and not 1 <= self.unit_id <= 247:
            raise ValueError("unit_id on serial lines must be 1..247")
        return self


class GigEVisionProtocol(_Base):
    """GigE Vision camera; the transport is managed by the camera SDK."""

    protocol: Literal["gige-vision"] = "gige-vision"
    serial_number: str | None = None
    ip: str | None = None
    mac: str | None = None
    user_defined_name: str | None = None
    packet_size: int | None = None


class Usb3VisionProtocol(_Base):
    """USB3 Vision camera; the transport is managed by the camera SDK."""

    protocol: Literal["usb3-vision"] = "usb3-vision"
    serial_number: str | None = None
    user_defined_name: str | None = None
    index: int | None = None


Connection = Annotated[
    Union[
        Uc2RestProtocol,
        CanOpenProtocol,
        ModbusProtocol,
        RegisterMapProtocol,
        GigEVisionProtocol,
        Usb3VisionProtocol,
    ],
    Field(discriminator="protocol"),
]


# =====================================================================
# Helpers
# =====================================================================


def transport_of(connection: Connection) -> Transport | None:
    """Return the transport of a connection, or None when the SDK handles it.

    Args:
        connection: Any connection model.

    Returns:
        The transport model; None for GigE Vision and USB3 Vision.
    """
    match connection:
        case Uc2RestProtocol() | CanOpenProtocol() | ModbusProtocol() | RegisterMapProtocol():
            return connection.transport
    return None


def resource_key(t: Transport) -> tuple:
    """Key identifying the physical resource behind a transport.

    Devices with the same key share one opened resource (pool it).
    Note: CAN bitrate and I2C address are deliberately NOT part of the key.

    Args:
        t: The transport.

    Returns:
        A hashable tuple, e.g. ``("uart", "/dev/ttyUSB0")``.
    """
    match t:
        case SerialTransport() | Rs422Transport() | Rs485Transport():
            return ("uart", t.port or t.port_pattern or (t.vid, t.pid, t.serial_number))
        case CanTransport():
            return ("can", t.interface, t.channel)
        case I2cTransport():
            return ("i2c", t.bus)
        case HttpTransport():
            return ("http", t.scheme, t.host, t.port)
        case TcpTransport():
            return ("tcp", t.host, t.port)
    raise TypeError(f"unknown transport {t!r}")


# Fields that may differ between users of the same resource.
# Everything else in a transport defines the resource and must be identical.
PER_USER_FIELDS = {"timeout", "write_timeout", "address", "force", "token", "base_path", "ws_path"}


def check_shared_resources(connections: Mapping[str, Connection]) -> dict[tuple, list[str]]:
    """Group devices by physical resource and report inconsistent sharing.

    Args:
        connections: ``device_id -> connection`` for every device that has its own
            connection (devices behind a controller are not listed).

    Returns:
        ``{resource_key: [device_ids]}`` for every resource in use.

    Raises:
        ValueError: Devices on one resource disagree on resource-defining settings
            (e.g. baudrate, bitrate, adapter type) or speak different protocols. The
            message holds one line per conflict.
    """
    groups: dict[tuple, list[tuple[str, Connection, Transport]]] = {}
    for device_id, connection in connections.items():
        transport = transport_of(connection)
        if transport is not None:
            groups.setdefault(resource_key(transport), []).append(
                (device_id, connection, transport)
            )

    errors = []
    for key, members in groups.items():
        first_id, first_conn, first_t = members[0]
        ref_t = first_t.model_dump(exclude=PER_USER_FIELDS)
        for other_id, other_conn, other_t in members[1:]:
            if other_conn.protocol != first_conn.protocol:
                errors.append(
                    f"{key}: '{first_id}' speaks {first_conn.protocol}, "
                    f"'{other_id}' speaks {other_conn.protocol}"
                )
            t = other_t.model_dump(exclude=PER_USER_FIELDS)
            diff = {k for k in ref_t.keys() | t.keys() if ref_t.get(k) != t.get(k)}
            if diff:
                errors.append(f"{key}: '{first_id}' and '{other_id}' disagree on {sorted(diff)}")
    if errors:
        raise ValueError("\n".join(errors))
    return {k: [device_id for device_id, _, _ in v] for k, v in groups.items()}
