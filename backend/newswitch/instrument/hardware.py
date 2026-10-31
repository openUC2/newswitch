"""How an instrument's optics reach real hardware: the ``hardware`` section of its description.

The cubes say what the microscope is and name their actuators; this section says what those names
are wired to. It is read only with ``use_virtual_microscope: false``, and is no part of what the
compiler looks at::

    hardware:
      boards:
        uc2:
          transport: rest        # rest | canopen
          port: /dev/ttyUSB0     # or port_pattern; neither: autodetect
          baudrate: 921600
          steps_per_um_x: 3.2    # any other option of UC2RestBusConfig / UC2CanBusConfig
          stage: {home_axes: [Z, X, Y]}  # any option of UC2StageConfig but its axes
      actuators:
        stg-x: {board: uc2, axis: X}
        wheel: {board: uc2, axis: A, positions: {1: 0.0, 2: 120.0}}
        turret: {board: uc2, positions: {1: 0, 2: 20000}}
        laser-dac: {board: uc2, channel: 1, pwm_max: 1023}
      cameras:                   # by the cube of the sensor
        camera_a: {protocol: usb3-vision, vendor: HikRobot, serial_number: "00F1"}
"""

from __future__ import annotations

import glob
from collections.abc import Mapping
from dataclasses import field
from typing import Annotated, Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic.dataclasses import dataclass

from newswitch.instrument.errors import SpecError, problems_of

#: Unknown keys are errors. The fields are strict types too: a value is what it says, so a serial
#: number is quoted, and ``true`` is no channel. (``strict=True`` here would refuse nested mappings.)
STRICT = ConfigDict(extra="forbid")

#: How a camera is reached, and what uc2_cam_py calls that.
CAMERA_PROTOCOLS = {"usb3-vision": "USB3", "gige-vision": "GigE"}

_BOARD_FIELDS = {"name", "transport", "port", "port_pattern", "options", "stage"}


def _named(entries: Any) -> Any:  # noqa: ANN401 - raw input of any shape
    """Entries keyed by name, each told its name."""
    if not isinstance(entries, Mapping):
        return entries
    return {
        name: {**entry, "name": name} if isinstance(entry, Mapping) else entry
        for name, entry in entries.items()
    }


@dataclass(frozen=True, config=STRICT)
class Board:
    """A UC2 board: its link, and the options its bus and stage are built with."""

    name: str
    transport: Literal["rest", "canopen"]
    port: str | None = None
    port_pattern: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    stage: dict[str, Any] = field(default_factory=dict)

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
        if "axes" in self.stage:
            raise ValueError("stage.axes: the stage's axes come from its actuators")
        return self

    def resolved_port(self) -> str | None:
        """The port to open: the stated one, or the first the pattern matches; None: autodetect."""
        if self.port is not None or self.port_pattern is None:
            return self.port
        matches = sorted(glob.glob(self.port_pattern))
        return matches[0] if matches else None


@dataclass(frozen=True, config=STRICT)
class Actuator:
    """What an actuator's name is wired to."""

    name: str
    board: str
    axis: str | None = None
    channel: StrictInt | None = None
    pwm_max: StrictInt | None = None
    positions: dict[StrictInt, StrictFloat] | None = None  # by slot


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
            if actuator.board not in self.boards:
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
