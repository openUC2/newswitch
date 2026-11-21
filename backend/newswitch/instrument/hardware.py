"""How an instrument's optics reach real hardware: the ``hardware`` section of its description.

The cubes say what the microscope is and name their actuators; this section says which driver reaches
each, and with what, so an actuator a cube names has to be here. An actuator's other keys are its
driver's to check. It is no part of what the compiler looks at, and a variable that names no actuator
is simulated or refused, as ``settings.simulate`` says::

    hardware:
      boards:
        uc2:
          transport: rest        # rest | canopen
          port: /dev/ttyUSB0     # or port_pattern; neither: autodetect
          baudrate: 921600       # any other option of UC2RestBusConfig / UC2CanBusConfig
          firmware:              # what it runs (`Firmware`): checked, and flashed, on start
            release: v2026.0.0-beta.4                 # a release of youseetoo/uc2-esp32
            board: UC2_canopen_master_release         # the env of the board on the port
            nodes:                                    # CAN node id -> env, or a pinned build
              11: UC2_canopen_slave_motor_release_motX
              12: {env: UC2_canopen_slave_motor_release_motY, version: v2026.0.0-beta.4-9-g3c86acd}
      actuators:
        stg-x: {driver: uc2.stepper, board: uc2, axis: X, steps_per_um: 3.2}
        wheel: {driver: uc2.wheel, board: uc2, axis: A, positions: {1: 0.0, 2: 120.0}}
        turret: {driver: uc2.turret, board: uc2}
        laser-dac: {driver: uc2.laser, board: uc2, channel: 1, pwm_max: 1023}
      cameras:                   # by the cube of the sensor
        camera_a: {protocol: usb3-vision, vendor: HikRobot, serial_number: "00F1"}
"""

from __future__ import annotations

import glob
import os
from collections.abc import Mapping
from dataclasses import field
from typing import Annotated, Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic.dataclasses import dataclass
from pydantic_core import ArgsKwargs

from newswitch.instrument.errors import SpecError, problems_of

#: Unknown keys are errors. The fields are strict types too: a value is what it says, so a serial
#: number is quoted, and ``true`` is no channel. (``strict=True`` here would refuse nested mappings.)
STRICT = ConfigDict(extra="forbid")

#: How a camera is reached, and what uc2_cam_py calls that.
CAMERA_PROTOCOLS = {"usb3-vision": "USB3", "gige-vision": "GigE"}

_BOARD_FIELDS = {"name", "transport", "port", "port_pattern", "firmware", "options"}

#: Where the releases of the UC2 firmware are: ``<source>/<release>/esp32_<env>[_merged].bin``.
FIRMWARE_SOURCE = "https://github.com/youseetoo/uc2-esp32/releases/download"
_ACTUATOR_FIELDS = {"name", "driver", "board", "options"}


def _named(entries: Any) -> Any:  # noqa: ANN401 - raw input of any shape
    """Entries keyed by name, each told its name."""
    if not isinstance(entries, Mapping):
        return entries
    return {
        name: {**entry, "name": name} if isinstance(entry, Mapping) else entry
        for name, entry in entries.items()
    }


def _pinned(value: Any) -> Any:  # noqa: ANN401 - raw input of any shape
    """An env alone (``UC2_canopen_master_release``) is a pin of that env."""
    return {"env": value} if isinstance(value, str) else value


@dataclass(frozen=True, config=STRICT)
class FirmwarePin:
    """What one board runs: the env of its image, and which build of it.

    ``version`` is what the board reports when it runs that build: a release image reports its tag
    (``v2026.0.0-beta.4``), a development build what ``git describe`` said
    (``v2026.0.0-beta.4-13-ge86ebf3-t20261102085646``). ``release`` is where an image of it is
    fetched from. Both default to the firmware's ``release``.
    """

    env: str = Field(description="The PlatformIO env, the image's name: esp32_<env>.bin")
    version: str | None = Field(
        default=None, description="The version it reports; default: release"
    )
    release: str | None = Field(
        default=None, description="Where it is fetched from; default: release"
    )


@dataclass(frozen=True, config=STRICT)
class Firmware:
    """What a board and the CAN nodes behind it run: a release of the UC2 firmware, and the
    PlatformIO env (the image) of each, pinned to a build when it is not the release's.

    An env is the name of the release's image, ``esp32_<env>.bin``: ``UC2_canopen_master_release``
    for the HAT+ master, ``UC2_canopen_slave_motor_release_motX`` for the X motor satellite.
    ``on_start`` says what a server does when it starts on real hardware: flash what does not run
    what is pinned (``flash``), only say so (``check``), or nothing (``off``).
    """

    release: str = Field(description="A release (tag) of the firmware, e.g. v2026.0.0-beta.4")
    board: FirmwarePin | None = Field(
        default=None, description="The board on the port; None: it is left as it is"
    )
    nodes: dict[StrictInt, FirmwarePin] = Field(
        default_factory=dict, description="Each CAN node, by its node id"
    )
    source: str = Field(
        default=FIRMWARE_SOURCE,
        description="Where releases are: <source>/<release>/esp32_<env>[_merged].bin",
    )
    on_start: Literal["flash", "check", "off"] = Field(
        default="flash", description="On a server's start: flash, check, or leave the bus alone"
    )

    @model_validator(mode="before")
    @classmethod
    def _envs_are_pins(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        # A mapping when read from a description; ArgsKwargs when built in code.
        given = data.kwargs if isinstance(data, ArgsKwargs) else data
        if not isinstance(given, Mapping):
            return data
        found = dict(given)
        if "board" in found:
            found["board"] = _pinned(found["board"])
        if isinstance(found.get("nodes"), Mapping):
            found["nodes"] = {key: _pinned(value) for key, value in found["nodes"].items()}
        return ArgsKwargs(data.args, found) if isinstance(data, ArgsKwargs) else found

    def pin_for(self, can_id: int | None) -> FirmwarePin | None:
        """What the board on the port (`can_id` None) or a CAN node is pinned to, if anything."""
        return self.board if can_id is None else self.nodes.get(can_id)

    def version_of(self, pin: FirmwarePin) -> str:
        """The version a board running `pin` reports."""
        return pin.version or self.release_of(pin)

    def release_of(self, pin: FirmwarePin) -> str:
        """The release an image of `pin` is fetched from."""
        return pin.release or self.release


@dataclass(frozen=True, config=STRICT)
class Board:
    """A UC2 board: its link, what it runs, and the options its bus and stage are built with."""

    name: str
    transport: Literal["rest", "canopen"]
    port: str | None = None
    port_pattern: str | None = None
    firmware: Firmware | None = None
    options: dict[str, Any] = field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _rest_are_driver_options(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        # The driver's config checks them when the bus is built, on real hardware only.
        if not isinstance(data, Mapping):
            return data
        known = {key: value for key, value in data.items() if key in _BOARD_FIELDS}
        return {**known, "options": {k: v for k, v in data.items() if k not in _BOARD_FIELDS}}

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.port is not None and self.port_pattern is not None:
            raise ValueError("port and port_pattern both name the port, give only one")
        return self

    def resolved_port(self) -> str | None:
        """The port to open: the stated one, or the first the pattern matches; None: autodetect.
        A link (``/dev/serial/by-id/…``) is followed to its device, which is what the serial
        libraries list and open."""
        if self.port is not None or self.port_pattern is None:
            return None if self.port is None else os.path.realpath(self.port)
        matches = sorted(glob.glob(self.port_pattern))
        return os.path.realpath(matches[0]) if matches else None


@dataclass(frozen=True, config=STRICT)
class Actuator:
    """Which driver an actuator's name means, and what it needs."""

    name: str
    driver: str
    board: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _rest_are_driver_options(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        # The driver's config checks them when the driver is built.
        if not isinstance(data, Mapping):
            return data
        known = {key: value for key, value in data.items() if key in _ACTUATOR_FIELDS}
        return {**known, "options": {k: v for k, v in data.items() if k not in _ACTUATOR_FIELDS}}


@dataclass(frozen=True, config=STRICT)
class Camera:
    """How to open the camera behind a sensor."""

    protocol: Literal["usb3-vision", "gige-vision"]
    vendor: str | None = None
    serial_number: Annotated[str, Field(min_length=1)] | None = None
    index: Annotated[StrictInt, Field(ge=0)] | None = None
    buffer_size: Annotated[StrictInt, Field(ge=2)] | None = None
    store_image_data: StrictBool | None = None
    vendor_options: dict[str, Any] = field(default_factory=dict)

    @model_validator(mode="after")
    def _one_selector(self) -> Self:
        if self.serial_number is not None and self.index is not None:
            raise ValueError("serial_number and index both select the camera, give only one")
        return self


@dataclass(frozen=True, config=STRICT)
class Hardware:
    """The whole section."""

    boards: dict[str, Board] = field(default_factory=dict)
    actuators: dict[str, Actuator] = field(default_factory=dict)
    cameras: dict[str, Camera] = field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _name_entries(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        if not isinstance(data, Mapping):
            return data
        named = {key: _named(data[key]) for key in ("boards", "actuators") if key in data}
        return {**data, **named}

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.boards) > 1:
            raise ValueError(f"boards: newswitch drives one board, not {sorted(self.boards)}")
        for actuator in self.actuators.values():
            if actuator.board is not None and actuator.board not in self.boards:
                raise ValueError(f"actuators.{actuator.name}: names no board {actuator.board!r}")
        return self

    @property
    def board(self) -> Board | None:
        """The board everything goes through; there is one bus."""
        return next(iter(self.boards.values()), None)


_HARDWARE = TypeAdapter(Hardware)


def parse(spec: Mapping[str, Any] | None) -> Hardware:
    """A ``hardware`` section on its own; an empty one when there is none.

    Raises:
        SpecError: It contradicts itself; every problem is listed.
    """
    try:
        return _HARDWARE.validate_python(spec or {})
    except ValidationError as exc:
        raise SpecError("hardware: " + "; ".join(problems_of(exc))) from exc
