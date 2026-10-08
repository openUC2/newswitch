## Device Connection Reference

Reference for the connection models in `connection.py`. Every device connection consists of a **protocol** (what is spoken) and, where applicable, a **transport** (over which medium the bytes travel). A connection may be defined inline or once under top-level `connections` and referenced by name from several devices:

```yaml
connections:
  main-can:
    protocol: can-bus
    transport: {type: can, interface: socketcan, channel: can0, bitrate: 500000}
devices:
  laser-488:
    type: lightsource
    name: 488 nm laser
    wavelength: 488
    connection: main-can
    binding: {type: canopen-laser, node_id: 21, channel: 0}
```

```yaml
connection:
  protocol: <protocol name>
  <protocol properties>        # flat, next to `protocol`
  transport:
    type: <transport type>
    <transport properties>
```

Properties without a default are **required**. Unknown properties are rejected (`extra: forbid`).

---

### 1. Overview: Allowed Protocol / Transport Combinations

| Protocol | `serial` | `rs422` | `rs485` | `http` | `tcp` | `can` | `i2c` | Transport handled by SDK |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `uc2-rest` | ✓ | ✓ | – | ✓ | ✓ | – | – | – |
| `canopen` | – | – | – | – | – | ✓ | – | – |
| `can-bus` | – | – | – | – | – | ✓ | – | – |
| `modbus` | ✓ | ✓ | ✓ | – | ✓ | – | – | – |
| `register-map` | – | – | – | – | – | – | ✓ | – |
| `gige-vision` | – | – | – | – | – | – | – | ✓ |
| `usb3-vision` | – | – | – | – | – | – | – | ✓ |

---

### 2. Protocols

#### 2.1 `uc2-rest`

JSON command protocol of openUC2 controllers (ESP32 firmware).

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `protocol` | `"uc2-rest"` | – | Discriminator. |
| `response_timeout` | `float` (s) | `2.0` | Maximum time to wait for the controller's answer to a command. Independent of the transport's read timeout. |
| `retries` | `int` | `1` | Number of repetitions if a command gets no valid answer. |
| `transport` | `serial` \| `rs422` \| `http` \| `tcp` | *required* | Underlying transport. |

#### 2.2 `canopen`

CANopen device (node) on a CAN bus.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `protocol` | `"canopen"` | – | Discriminator. |
| `node_id` | `int`, 1–127 | *required* | CANopen node ID; unique per bus, used to derive the COB-IDs. |
| `eds_file` | `path` \| `null` | `null` | EDS/DCF file describing the device's object dictionary. |
| `sdo_timeout` | `float` (s) | `0.5` | Timeout for SDO (service data object) transfers. |
| `heartbeat_period_ms` | `int` \| `null` | `null` | Expected heartbeat interval of the node; `null` disables monitoring. |
| `transport` | `can` | `can` with defaults | CAN bus the node is attached to. |

For a stage whose axes reside on different CANopen nodes, use `can-bus` on the
stage instead of assigning a single `node_id` to the whole stage. Each axis then
has a `binding` with its own `node_id` and `sub_axis`. The same bus can also
serve light sources, whose bindings identify the laser or LED node.

#### `can-bus`

Shared CAN transport for devices on the same bus. It has no device-level `node_id`;
axis and light-source bindings identify their respective CANopen nodes.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `protocol` | `"can-bus"` | – | Discriminator. |
| `transport` | `can` | `can` with defaults | Shared CAN interface and bitrate. |

#### 2.3 `modbus`

Modbus RTU/ASCII on serial lines (typically RS485 multidrop) or Modbus TCP.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `protocol` | `"modbus"` | – | Discriminator. |
| `unit_id` | `int`, 0–255 (1–247 on serial lines) | *required* | Slave / unit address of the device. |
| `framing` | `"rtu"` \| `"ascii"` \| `"mbap"` \| `null` | `null` | Frame format. `null` selects `mbap` on `tcp` and `rtu` otherwise. `mbap` requires `tcp`. |
| `response_timeout` | `float` (s) | `0.5` | Maximum time to wait for the slave's response. |
| `retries` | `int` | `2` | Number of repetitions on timeout or CRC error. |
| `transport` | `rs485` \| `rs422` \| `serial` \| `tcp` | *required* | Underlying transport. |

#### 2.4 `register-map`

Generic register read/write devices (sensors, DACs, IO expanders, …).

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `protocol` | `"register-map"` | – | Discriminator. |
| `register_width` | `8` \| `16` | `8` | Width of the register address in bits. |
| `byte_order` | `"big"` \| `"little"` | `"big"` | Byte order of multi-byte register values. |
| `register_file` | `path` \| `null` | `null` | Optional register description file (comparable to an EDS). |
| `retries` | `int` | `2` | Number of repetitions of a failed transfer. |
| `transport` | `i2c` | *required* | Underlying bus (SPI may be added later). |

#### 2.5 `gige-vision`

GigE Vision camera. Transport is managed by the camera SDK; the properties select the device.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `protocol` | `"gige-vision"` | – | Discriminator. |
| `serial_number` | `str` \| `null` | `null` | Camera serial number (selector). |
| `ip` | `str` \| `null` | `null` | Camera IP address (selector). |
| `mac` | `str` \| `null` | `null` | Camera MAC address (selector). |
| `user_defined_name` | `str` \| `null` | `null` | User-assigned device name stored in the camera (selector). |
| `packet_size` | `int` \| `null` | `null` | Stream packet size in bytes (e.g. `9000` for jumbo frames); `null` uses the SDK default. |

#### 2.6 `usb3-vision`

USB3 Vision camera. Transport is managed by the camera SDK; the properties select the device.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `protocol` | `"usb3-vision"` | – | Discriminator. |
| `serial_number` | `str` \| `null` | `null` | Camera serial number (selector). |
| `user_defined_name` | `str` \| `null` | `null` | User-assigned device name stored in the camera (selector). |
| `index` | `int` \| `null` | `null` | Enumeration index; fallback only, not stable across reboots. |

---

### 3. Transports

#### 3.1 Common UART Settings (`serial`, `rs422`, `rs485`)

Shared by all UART-based transports. At least one selector (`port`, `port_pattern`, `vid`, `serial_number`) is required.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `port` | `str` \| `null` | `null` | Explicit device path, e.g. `/dev/ttyUSB0`, `COM3`, `/dev/serial/by-id/...` (selector). |
| `port_pattern` | `str` \| `null` | `null` | Glob pattern matched against device paths, e.g. `/dev/serial/by-id/*CP2102*` (selector). |
| `vid` | `int` \| `null` | `null` | USB vendor ID of the adapter (selector). |
| `pid` | `int` \| `null` | `null` | USB product ID of the adapter (selector, used together with `vid`). |
| `serial_number` | `str` \| `null` | `null` | USB serial number of the adapter (selector). |
| `baudrate` | `int` | `115200` | Line speed in baud. |
| `bytesize` | `5` \| `6` \| `7` \| `8` | `8` | Data bits per character. |
| `parity` | `"N"` \| `"E"` \| `"O"` \| `"M"` \| `"S"` | `"N"` | Parity: none, even, odd, mark, space. |
| `stopbits` | `1` \| `1.5` \| `2` | `1` | Number of stop bits. |
| `timeout` | `float` (s) | `1.0` | Read timeout. Per-user setting (may differ between devices sharing a port). |
| `write_timeout` | `float` (s) \| `null` | `1.0` | Write timeout; `null` blocks indefinitely. Per-user setting. |
| `rtscts` | `bool` | `false` | Hardware flow control via RTS/CTS. Not allowed on `rs485`. |

#### 3.2 `serial`

USB-UART / RS232 / TTL, e.g. a directly attached ESP32. Includes all common UART settings (3.1).

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `type` | `"serial"` | – | Discriminator. |
| `reset_on_connect` | `bool` | `false` | Toggle DTR/RTS on open to reset the microcontroller (ESP32). |
| `boot_delay` | `float` (s) | `0.0` | Time to wait after opening before the first command (firmware boot). |

#### 3.3 `rs422`

Differential, full-duplex UART via an RS422 adapter. Includes all common UART settings (3.1); no additional properties.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `type` | `"rs422"` | – | Discriminator. |

#### 3.4 `rs485`

Differential, half-duplex, multidrop UART via an RS485 adapter. Includes all common UART settings (3.1); `rtscts` must be `false`.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `type` | `"rs485"` | – | Discriminator. |
| `direction_control` | `"auto"` \| `"kernel"` \| `"software"` | `"auto"` | Who switches the transceiver between TX and RX: the adapter itself, the Linux driver (`TIOCSRS485`), or pyserial from Python (timing not guaranteed). |
| `rts_level_for_tx` | `bool` | `true` | RTS level while transmitting (`kernel` / `software` mode). |
| `rts_level_for_rx` | `bool` | `false` | RTS level while receiving (`kernel` / `software` mode). |
| `delay_before_tx` | `float` (s) \| `null` | `null` | Delay between switching to TX and sending the first byte. |
| `delay_before_rx` | `float` (s) \| `null` | `null` | Delay between the last sent byte and switching back to RX. |
| `echo` | `bool` | `false` | Adapter echoes its own transmitted bytes; the driver discards them. |

#### 3.5 `http`

HTTP(S) connection, e.g. uc2-rest over Wi-Fi/Ethernet.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `type` | `"http"` | – | Discriminator. |
| `host` | `str` | *required* | IP address or hostname, including mDNS names like `uc2-stage.local`. |
| `port` | `int` \| `null` | `null` | TCP port; `null` means 80 for `http`, 443 for `https`. |
| `scheme` | `"http"` \| `"https"` | `"http"` | URL scheme. |
| `base_path` | `str` | `""` | Path prefix for all requests, e.g. `/api/v1`. Per-user setting. |
| `timeout` | `float` (s) | `5.0` | Request timeout. Per-user setting. |
| `verify_ssl` | `bool` | `true` | Verify the TLS certificate (`https` only). |
| `token` | `secret str` \| `null` | `null` | Bearer token for authentication; hidden in logs and `repr`. Per-user setting. |
| `ws_path` | `str` \| `null` | `null` | Optional WebSocket path for pushed events/status. Per-user setting. |

#### 3.6 `tcp`

Raw TCP socket.

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `type` | `"tcp"` | – | Discriminator. |
| `host` | `str` | *required* | IP address or hostname. |
| `port` | `int`, 1–65535 | *required* | TCP port. |
| `timeout` | `float` (s) | `5.0` | Connect/read timeout. Per-user setting. |
| `terminator` | `str` | `"\n"` | Message delimiter for line-based framing. |
| `keepalive` | `bool` | `true` | Enable TCP keepalive on the socket. |

#### 3.7 `can`

CAN bus interface (based on `python-can`).

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `type` | `"can"` | – | Discriminator. |
| `interface` | `"socketcan"` \| `"waveshare"` \| `"pcan"` \| `"kvaser"` \| `"slcan"` \| `"gs_usb"` \| `"virtual"` | `"socketcan"` | CAN adapter type. |
| `channel` | `str` | `"can0"` | Bus channel, e.g. `can0`, `PCAN_USBBUS1`, or a serial port for `slcan`. |
| `port` | `str` \| `null` | `null` | USB serial port for `waveshare`; required with that interface. |
| `bitrate` | `int` | `500000` | Bus bitrate in bit/s (typically 125k, 250k, 500k, 1M). Must be identical for all devices on the bus. |

#### 3.8 `i2c`

I2C bus plus slave address. The bus speed is not configurable from Linux user space (on a Raspberry Pi: `dtparam=i2c_arm_baudrate=...` in `config.txt`).

| Property | Type / Allowed values | Default | Description |
|---|---|---|---|
| `type` | `"i2c"` | – | Discriminator. |
| `bus` | `int` | `1` | Bus number, i.e. `/dev/i2c-<bus>`. |
| `address` | `int`, 0x03–0x77 (7-bit) or 0–0x3FF (10-bit) | *required* | Slave address; hex notation (`0x48`) works in YAML. Per-user setting. |
| `ten_bit` | `bool` | `false` | Use 10-bit addressing. |
| `force` | `bool` | `false` | Access the address even if a kernel driver has claimed it. Per-user setting. |

---

### 4. Shared Resources

Devices whose transports resolve to the same physical resource share one opened handle. `check_shared_resources()` requires all devices on a resource to use the same protocol and identical resource-defining settings; only *per-user* settings may differ.

| Transport | Resource key | Per-user settings (may differ) |
|---|---|---|
| `serial`, `rs422`, `rs485` | `("uart", port \| port_pattern \| (vid, pid, serial_number))` | `timeout`, `write_timeout` |
| `http` | `("http", scheme, host, port)` | `timeout`, `token`, `base_path`, `ws_path` |
| `tcp` | `("tcp", host, port)` | `timeout` |
| `can` | `("can", interface, channel)` | – |
| `i2c` | `("i2c", bus)` | `address`, `force` |
