"""A parameter that carries its own limits.

Design decision
---------------
Limits are modelled as a **nested object**, not as sibling tags:

    exposure_time_ms:
      value: 10.0
      min: 0.024
      max: 10000.0
      increment: 0.001

rather than::

    exposure_time_ms: 10.0
    exposure_time_ms_min: 0.024
    exposure_time_ms_max: 10000.0

The nested form is one reusable model instead of three flat fields per
parameter, so the "value must lie between min and max" rule is written once
and applies everywhere.

To keep the common case short, a **bare scalar is accepted as shorthand** for
``{"value": <scalar>}``. Both of these are valid and equivalent:

    exposure_time_ms: 10.0
    exposure_time_ms: {value: 10.0}

Note what JSON Schema can and cannot do here. ``minimum``/``maximum`` in the
schema are *global* constants — they cannot refer to another field of the same
document. "value within this device's own min/max" is therefore a cross-field
rule and lives in Pydantic only.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Bounded(BaseModel):
    """A numeric parameter together with the device limits that apply to it.

    All four members are optional, which covers every practical case:

    * ``{value: 10}``                       -- setting, limits unknown
    * ``{min: 0.024, max: 10000}``          -- capability only, no default set
    * ``{value: 10, min: 0.024, max: 1e4}`` -- both
    * ``null`` / omitted                    -- parameter not applicable
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    value: Optional[float] = Field(default=None, description="Current or default value")
    min: Optional[float] = Field(default=None, description="Smallest settable value")
    max: Optional[float] = Field(default=None, description="Largest settable value")
    increment: Optional[float] = Field(
        default=None, gt=0, description="Step size; settable values are min + n*increment"
    )
    unit: Optional[str] = Field(
        default=None, description="Override for the unit implied by the field name"
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_scalar(cls, data: Any) -> Any:
        """Allow ``exposure_time_ms: 10.0`` as shorthand for ``{value: 10.0}``."""
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return {"value": float(data)}
        return data

    @model_validator(mode="after")
    def _check_consistency(self) -> "Bounded":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min ({self.min}) must not exceed max ({self.max})")

        if self.value is not None:
            if self.min is not None and self.value < self.min:
                raise ValueError(f"value {self.value} below min {self.min}")
            if self.max is not None and self.value > self.max:
                raise ValueError(f"value {self.value} above max {self.max}")

            if self.increment is not None:
                base = self.min if self.min is not None else 0.0
                steps = (self.value - base) / self.increment
                if not math.isclose(steps, round(steps), abs_tol=1e-9):
                    raise ValueError(
                        f"value {self.value} is not on the {self.increment} grid starting at {base}"
                    )
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):  # noqa: ANN001
        """Emit ``anyOf: [number, object]`` so the shorthand validates too."""
        schema = handler(core_schema)
        schema = handler.resolve_ref_schema(schema)
        return {
            "anyOf": [
                {"type": "number", "description": "Shorthand for {value: <number>}"},
                dict(schema),
            ],
            "description": cls.__doc__.splitlines()[0] if cls.__doc__ else None,
        }

    def clamp(self, value: float) -> float:
        """Clamp to [min, max] and snap onto the increment grid."""
        base = self.min if self.min is not None else 0.0
        if self.min is not None:
            value = max(value, self.min)
        if self.max is not None:
            value = min(value, self.max)
        if self.increment is not None:
            value = base + round((value - base) / self.increment) * self.increment
            if self.max is not None and value > self.max:
                value -= self.increment
        return value

    def supports(self, value: float) -> bool:
        """True if `value` can be set exactly."""
        try:
            Bounded(value=value, min=self.min, max=self.max, increment=self.increment)
        except ValueError:
            return False
        return True

    def __repr__(self) -> str:
        parts = [f"{k}={v}" for k, v in self.model_dump(exclude_none=True).items()]
        return f"Bounded({', '.join(parts)})"
