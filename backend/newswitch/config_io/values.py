"""Value types used inside device entries: physical values, triggers, firmware info.

Physical values
---------------
A `PhysVal` is a number together with the limits the device allows for it::

    exposure_time_ms: {value: 25.0, min: 0.024, max: 10000.0, inc: 0.001, unit: ms}
    exposure_time_ms: 25.0          # shorthand for {value: 25.0}
    exposure_time_ms: null          # not stated -> None, may be read from the firmware

Each field declares the unit newswitch works in. Its metadata is attached with
`phys_meta` and its unit/sign rules with `in_unit`, `positive` and `non_negative`::

    exposure_time_ms: Annotated[
        PhysVal | None, AfterValidator(in_unit("ms")), AfterValidator(positive),
        phys_meta("ms", firmware="limits"),
    ] = None
"""

from __future__ import annotations

import dataclasses
import math
import sys
import warnings
from collections.abc import Callable
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, GetJsonSchemaHandler, model_validator
from pydantic.dataclasses import dataclass
from pydantic.fields import FieldInfo
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from .errors import ConfigWarning
from .units import conversion_factor

#: Shared configuration of every config dataclass: unknown keys are errors.
STRICT = ConfigDict(extra="forbid")

#: What the device may say about a field: everything, or only the limits.
FirmwareKind = Literal["full", "limits"]

EPS = sys.float_info.epsilon

#: Default of every `PhysVal` member except ``value``. A member equal to its default
#: carries no information and is not written back to the file.
PHYS_VAL_DEFAULTS: dict[str, Any] = {
    "min": -math.inf,
    "max": math.inf,
    "inc": EPS,
    "unit": "",
    "preset_vals": [],
}


@dataclass(kw_only=True, config=STRICT)
class PhysVal:
    """A physical value with its device limits.

    Only ``value`` may be changed by the software at runtime; it is written back to the
    file on shutdown. The other members describe what the device allows.
    """

    value: float | None = None
    min: float = -math.inf
    max: float = math.inf
    inc: float = Field(default=EPS, gt=0, description="Step size")
    unit: str = ""
    preset_vals: list[float] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_scalar(cls, data: Any) -> Any:  # noqa: ANN401 - raw input
        """Allow ``exposure_time_ms: 10.0`` as shorthand for ``{value: 10.0}``."""
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return {"value": float(data)}
        return data

    @model_validator(mode="after")
    def _check_limits(self) -> Self:
        if self.min > self.max:
            raise ValueError(f"min ({self.min}) must not exceed max ({self.max})")
        if self.value is not None and not self.min <= self.value <= self.max:
            raise ValueError(f"value {self.value} outside [{self.min}, {self.max}]")
        return self

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """Emit ``anyOf: [number, object]`` so the scalar shorthand validates too."""
        schema = handler(core_schema)
        return {
            "anyOf": [{"type": "number", "description": "Shorthand for {value: <number>}"}, schema],
            "description": "Physical value with its device limits",
        }

    def clamp(self, value: float) -> float:
        """Clamp `value` to [min, max] and snap it onto the increment grid.

        Args:
            value: The requested value.

        Returns:
            The closest value the device accepts.
        """
        value = min(max(value, self.min), self.max)
        if self.inc > EPS and math.isfinite(self.min):
            value = self.min + round((value - self.min) / self.inc) * self.inc
            if value > self.max:
                value -= self.inc
        return value

    def scaled(self, factor: float, unit: str) -> PhysVal:
        """Return a copy with every number multiplied by `factor` and a new unit.

        Args:
            factor: Positive conversion factor.
            unit: Unit of the result.

        Returns:
            The converted value.
        """
        return PhysVal(
            value=None if self.value is None else self.value * factor,
            min=self.min * factor,
            max=self.max * factor,
            inc=self.inc if self.inc == EPS else self.inc * factor,
            unit=unit,
            preset_vals=[v * factor for v in self.preset_vals],
        )


def in_unit(unit: str) -> Callable[[PhysVal | None], PhysVal | None]:
    """Build a validator that brings a `PhysVal` into `unit`.

    An empty unit is taken to mean `unit`. A compatible unit is converted. A unit that
    cannot be converted produces a `ConfigWarning`, and the field is dropped (None), so
    it falls back to what the firmware reports.

    Args:
        unit: The unit newswitch works in for this field.

    Returns:
        A function usable with `pydantic.AfterValidator`.
    """

    def convert(value: PhysVal | None) -> PhysVal | None:
        if value is None or value.unit == unit:
            return value
        if value.unit == "":
            return dataclasses.replace(value, unit=unit)
        try:
            factor = conversion_factor(value.unit, unit)
        except ValueError as exc:
            warnings.warn(f"{exc}; value dropped", ConfigWarning, stacklevel=2)
            return None
        return value.scaled(factor, unit)

    return convert


def positive(value: PhysVal | None) -> PhysVal | None:
    """Require ``value > 0`` when a value is set (use with `pydantic.AfterValidator`).

    Args:
        value: The validated physical value.

    Returns:
        `value` unchanged.

    Raises:
        ValueError: The value is zero or negative.
    """
    if value is not None and value.value is not None and value.value <= 0:
        raise ValueError(f"value must be > 0, got {value.value}")
    return value


def non_negative(value: PhysVal | None) -> PhysVal | None:
    """Require ``value >= 0`` when a value is set (use with `pydantic.AfterValidator`).

    Args:
        value: The validated physical value.

    Returns:
        `value` unchanged.

    Raises:
        ValueError: The value is negative.
    """
    if value is not None and value.value is not None and value.value < 0:
        raise ValueError(f"value must be >= 0, got {value.value}")
    return value


def phys_meta(unit: str, *, firmware: FirmwareKind | None = None, description: str = "") -> Any:  # noqa: ANN401 - FieldInfo
    """Field metadata of a physical value: its unit and what the firmware may provide.

    The markers end up in the exported JSON Schema as ``x_unit`` / ``x_firmware``, and
    `devices.field_markers` reads them back for the writer.

    Args:
        unit: The unit newswitch works in.
        firmware: ``"full"`` or ``"limits"`` if the device can report the field.
        description: Human-readable description.

    Returns:
        A pydantic `Field` to put into ``Annotated[...]``.
    """
    extra: dict[str, Any] = {"x_unit": unit}
    if firmware is not None:
        extra["x_firmware"] = firmware
    return Field(description=description, json_schema_extra=extra)


def firmware_meta(description: str = "") -> FieldInfo:
    """Field metadata of a plain (non-physical) field that the firmware can report.

    Args:
        description: Human-readable description.

    Returns:
        A pydantic `Field` to put into ``Annotated[...]``.
    """
    return Field(description=description, json_schema_extra={"x_firmware": "full"})


@dataclass(kw_only=True, config=STRICT)
class Trigger:
    """Trigger of a device. Omit it for free-running operation."""

    type: Literal["software", "hardware"]
    edge: Literal["rising", "falling"] | None = None
    level: float | None = None

    @model_validator(mode="after")
    def _check_software(self) -> Self:
        if self.type == "software" and (self.edge is not None or self.level is not None):
            raise ValueError("edge/level are only meaningful for hardware triggers")
        return self


@dataclass(kw_only=True, config=STRICT)
class Firmware:
    """Firmware running on a controller."""

    name: str
    version: str


PositiveInt = Annotated[int, Field(gt=0)]
PositiveFloat = Annotated[float, Field(gt=0)]

#: ``(x, y)`` pair of positive integers, written as ``[x, y]``.
IntPair = tuple[PositiveInt, PositiveInt]

#: A positive float for square geometry, or ``[x, y]`` for separate values.
FloatOrPair = PositiveFloat | tuple[PositiveFloat, PositiveFloat]


def as_pair(value: float | tuple[float, float]) -> tuple[float, float]:
    """Resolve a `FloatOrPair` into an explicit ``(x, y)`` pair.

    Args:
        value: A single float or a pair.

    Returns:
        ``(value, value)`` for a float, the pair unchanged otherwise.
    """
    if isinstance(value, tuple):
        return value
    return (value, value)
