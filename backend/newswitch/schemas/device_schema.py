"""Device registry schema: one file, many device types.

All device types -- camera included -- are ordinary subclasses of `DeviceBase`
and are dispatched by their `type` field. Adding a device type takes four
steps:

    1. subclass DeviceBase with a new `type: Literal[...]`
    2. add it to the `Device` union and to DEVICE_MODELS
    3. add a matching `@overload` to `loader.load_device`, so that
       `expect="<newtype>"` narrows to the new class instead of the union
    4. nothing else -- registry, validation and JSON Schema pick it up
       automatically

Step 3 is the only one a type checker will not remind you about: forget it and
the code still runs, `expect=` just stops narrowing for that one type.

Field conventions
-----------------
* A field WITHOUT a default is required.
* A field WITH a default (including ``None``) is optional.
* An omitted optional field is *not* filled in during validation. Where a
  fallback exists (pixelpitch y -> x, pixelsize -> pixelpitch) it is exposed as
  a read-only property -- `Vector2Float.effective_y`,
  `CameraDevice.effective_pixelsize_um` -- and the field itself stays ``None``,
  so a load/dump round-trip returns the document unchanged. Read the property
  wherever the resolved value is wanted.
* Cross-field rules (roi inside pixelcount, value inside its own min/max,
  unique identifiers) live in Pydantic only. JSON Schema constraints are
  constants and cannot refer to sibling fields.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# import numpy as np  # noqa: ERA001  -- needed for quantum_efficiency, see below


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class Bounded(BaseModel):
    """A numeric parameter together with the device limits that apply to it.

    Accepts a bare number as shorthand for ``{"value": <number>}``, so both of
    these are valid and equivalent::

        exposure_time_ms: 10.0
        exposure_time_ms: {value: 10.0}

    All members are optional, which covers every practical case:

    * ``{value: 10}``                       -- setting, limits unknown
    * ``{min: 0.024, max: 10000}``          -- capability only, no value chosen
    * ``{value: 10, min: 0.024, max: 1e4}`` -- both
    * ``null`` / omitted                    -- parameter not applicable
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    value: Optional[float] = Field(default=None, description="Current or default value")
    min: Optional[float] = Field(default=None, description="Smallest settable value")
    max: Optional[float] = Field(default=None, description="Largest settable value")
    increment: Optional[float] = Field(
        default=None,
        gt=0,
        description="Step size; settable values are min + n*increment",
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
            "description": "Numeric parameter with its device limits",
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
        """Show only the members that are set, so the repr stays readable."""
        parts = [f"{k}={v}" for k, v in self.model_dump(exclude_none=True).items()]
        return f"Bounded({', '.join(parts)})"


class Vector2Int(BaseModel):
    """Integer pair, both components required (e.g. pixel counts)."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(gt=0, description="Extent along x in pixels")
    y: int = Field(gt=0, description="Extent along y in pixels")


class Vector2Float(BaseModel):
    """Float pair where y may be omitted, meaning "same as x" (square geometry).

    ``y`` stays optional so the model says the same thing the document does:
    ``None`` means "not stated", which survives a load/dump round-trip
    unchanged. Read `effective_y` instead of `y` wherever the resolved value is
    wanted -- it is non-optional, so arithmetic type-checks without casts.
    """

    model_config = ConfigDict(extra="forbid")

    x: float = Field(gt=0, description="Value along x in micrometers")
    y: Optional[float] = Field(
        default=None,
        gt=0,
        description="Value along y in micrometers; omit for square geometry",
    )

    @property
    def effective_y(self) -> float:
        """Stated y, or x when the document left y out."""
        return self.y if self.y is not None else self.x

    @property
    def as_tuple(self) -> tuple[float, float]:
        """(x, effective_y) -- both components resolved."""
        return (self.x, self.effective_y)


class Trigger(BaseModel):
    """Trigger configuration. Omit the whole object for free-running mode."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["software", "hardware"]
    edge: Optional[Literal["rising", "falling"]] = None
    level: Optional[Literal["high", "low"]] = None

    @model_validator(mode="after")
    def _check_software(self) -> "Trigger":
        if self.type == "software" and (self.edge or self.level):
            raise ValueError("edge/level are only meaningful for hardware triggers")
        return self


class StageAxis(BaseModel):
    """One motorized axis of a stage."""

    model_config = ConfigDict(extra="forbid")

    label: Literal["x", "y", "z", "a", "b", "c"]
    travel_um: float = Field(gt=0, description="Usable travel range in micrometers")
    steps_per_um: float = Field(gt=0, description="Motor steps per micrometer")
    inverted: bool = Field(default=False, description="Flip the positive direction")


class FilterSlot(BaseModel):
    """One slot of a filter wheel."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=0, description="Slot index on the wheel")
    label: str = Field(description="Filter designation, e.g. GFP-525/50")
    center_nm: Optional[float] = Field(default=None, gt=0)
    bandwidth_nm: Optional[float] = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


class DeviceBase(BaseModel):
    """Fields shared by every device type."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str = Field(description="Model designation, e.g. MV-CA023-10UM")
    manufacturer: Optional[str] = Field(default=None, description="Vendor name")
    device_id: Optional[str] = Field(
        default=None, description="Identifier of the individual physical unit"
    )
    tags: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        """Stable identifier: device_id when present, otherwise the name."""
        return self.device_id or self.name


class CameraDevice(DeviceBase):
    """Imaging sensor."""

    type: Literal["camera"]

    # --- sensor geometry ------------------------------------------------
    pixelcount: Vector2Int = Field(description="Sensor resolution in pixels")
    pixelpitch_um: Vector2Float = Field(
        description="Center-to-center pixel distance; y defaults to x"
    )
    pixelsize_um: Optional[Vector2Float] = Field(
        default=None,
        description="Photosensitive area per pixel; omit when the datasheet "
        "gives none, then a fill factor of 1.0 is assumed",
    )
    channels: int = Field(default=1, ge=1, description="Color/spectral channels")

    # --- acquisition ----------------------------------------------------
    exposure_time_ms: Optional[Bounded] = Field(
        default=None, description="Integration time in ms, with device limits"
    )
    framerate_per_sec: Optional[Bounded] = Field(
        default=None, description="Frame rate in Hz, with device limits"
    )
    gain_db: Optional[Bounded] = Field(
        default=None, description="Analog gain in dB, with device limits"
    )
    binning: Literal[1, 2, 4] = 1
    roi: Optional[tuple[int, int, int, int]] = Field(
        default=None, description="Region of interest as (x, y, width, height)"
    )
    trigger: Optional[Trigger] = None

    # --- spectral response ----------------------------------------------
    # quantum_efficiency: Optional[np.ndarray] = None
    #
    # Enabling this requires ConfigDict(arbitrary_types_allowed=True) and a
    # custom serializer, and the field cannot be expressed in JSON Schema at
    # all -- which would break the jsonschema validation path and every
    # non-Python consumer. JSON-native alternative:
    #     qe_wavelength_nm: Optional[list[float]] = None
    #     qe_values: Optional[list[float]] = None   # 0.0 .. 1.0, same length

    @property
    def effective_pixelsize_um(self) -> Vector2Float:
        """Stated photosensitive area, or pixelpitch_um when none was given.

        The fallback is an *assumption* (fill factor 1.0), not a datasheet
        value -- which is exactly why `pixelsize_um` stays None in the model
        rather than being filled in during validation.
        """
        return self.pixelsize_um if self.pixelsize_um is not None else self.pixelpitch_um

    @model_validator(mode="after")
    def _check_roi(self) -> "CameraDevice":
        if self.roi is not None:
            x, y, w, h = self.roi
            if w <= 0 or h <= 0:
                raise ValueError("roi width and height must be positive")
            if x < 0 or y < 0:
                raise ValueError("roi origin must be non-negative")
            if x + w > self.pixelcount.x or y + h > self.pixelcount.y:
                raise ValueError("roi exceeds sensor pixelcount")
        return self

    @property
    def sensor_size_mm(self) -> tuple[float, float]:
        """Physical sensor extent (width, height) in millimeters."""
        return (
            self.pixelcount.x * self.pixelpitch_um.x / 1000.0,
            self.pixelcount.y * self.pixelpitch_um.effective_y / 1000.0,
        )

    @property
    def fill_factor(self) -> float:
        """Photosensitive area fraction per pixel (0.0 .. 1.0).

        Returns 1.0 when `pixelsize_um` was not stated -- see
        `effective_pixelsize_um`.
        """
        ps, pp = self.effective_pixelsize_um, self.pixelpitch_um
        return (ps.x * ps.effective_y) / (pp.x * pp.effective_y)


class StageDevice(DeviceBase):
    """Motorized positioning stage."""

    type: Literal["stage"]
    axes: list[StageAxis] = Field(min_length=1)
    max_speed_um_per_sec: Optional[float] = Field(default=None, gt=0)
    homing_required: bool = True

    @model_validator(mode="after")
    def _unique_axis_labels(self) -> "StageDevice":
        labels = [a.label for a in self.axes]
        if len(labels) != len(set(labels)):
            raise ValueError(f"duplicate axis labels: {labels}")
        return self


class LaserDevice(DeviceBase):
    """Single-wavelength illumination source."""

    type: Literal["laser"]
    wavelength_nm: float = Field(gt=0, le=20_000)
    max_power_mw: float = Field(gt=0)
    modulation: Literal["none", "analog", "digital"] = "none"
    shutter: bool = Field(default=False, description="Has a mechanical shutter")


class FilterWheelDevice(DeviceBase):
    """Motorized filter wheel."""

    type: Literal["filterwheel"]
    slots: list[FilterSlot] = Field(min_length=1)
    switch_time_ms: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _unique_positions(self) -> "FilterWheelDevice":
        positions = [s.position for s in self.slots]
        if len(positions) != len(set(positions)):
            raise ValueError(f"duplicate slot positions: {positions}")
        return self


class UnknownDevice(DeviceBase):
    """Placeholder for a device this version of the schema does not model.

    Unlike every other type it uses ``extra="allow"``, so whatever fields the
    entry carries are kept instead of rejected. They land in ``model_extra``
    and survive a load/dump round-trip, which means an older build can read,
    hold and rewrite a config containing devices it knows nothing about
    without destroying them.

    The trade-off: nothing inside such an entry is validated. Treat it as
    opaque payload, not as configuration you can act on.

    Note this only catches entries that literally say ``type: unknown``. An
    entry with ``type: spectrometer`` is still rejected by the discriminator --
    deliberately, because that error is what catches a typo like ``stagee``.
    See DeviceRegistry for how to opt into remapping instead.
    """

    model_config = ConfigDict(extra="allow")

    type: Literal["unknown"]
    kind: Optional[str] = Field(
        default=None,
        description="What the device actually is, if known, e.g. 'spectrometer'",
    )

    @property
    def payload(self) -> dict[str, Any]:
        """The unrecognized fields, as they appeared in the document."""
        return dict(self.model_extra or {})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# The discriminated union. Pydantic uses `type` to dispatch each list entry to
# exactly one model, which keeps error paths precise:
#     devices.1.stage.axes.0.travel_um -> Input should be greater than 0
# instead of the usual union noise ("not valid under any of the given schemas").
Device = Annotated[
    Union[CameraDevice, StageDevice, LaserDevice, FilterWheelDevice, UnknownDevice],
    Field(discriminator="type"),
]

DEVICE_MODELS: dict[str, type[DeviceBase]] = {
    "camera": CameraDevice,
    "stage": StageDevice,
    "laser": LaserDevice,
    "filterwheel": FilterWheelDevice,
    "unknown": UnknownDevice,
}


class DeviceRegistry(BaseModel):
    """Top-level object of a Devices.yml file."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True)

    schema_ref: Optional[str] = Field(
        default=None,
        alias="$schema",
        serialization_alias="$schema",
        description="Optional pointer to the schema file, for editor autocomplete",
    )
    version: int = Field(default=1, ge=1, description="Registry format version")
    setup: Optional[str] = Field(default=None, description="Name of the setup")
    devices: list[Device] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_keys(self) -> "DeviceRegistry":
        seen: dict[str, int] = {}
        for i, dev in enumerate(self.devices):
            if dev.key in seen:
                raise ValueError(
                    f"devices[{i}]: duplicate identifier {dev.key!r} "
                    f"(also at devices[{seen[dev.key]}])"
                )
            seen[dev.key] = i
        return self

    def by_type(self, type_: str) -> list[Device]:
        """All devices of one type, e.g. registry.by_type('camera')."""
        return [d for d in self.devices if d.type == type_]

    def get(self, key: str) -> Device:
        """Look up one device by device_id, falling back to name."""
        for dev in self.devices:
            if dev.key == key or dev.name == key:
                return dev
        raise KeyError(f"no device with id or name {key!r}")

    @staticmethod
    def demote_unknown_types(data: Any) -> Any:
        """Rewrite entries with an unrecognized ``type`` to ``type: unknown``.

        NOT applied automatically, and that is deliberate: it cannot tell an
        intentionally newer device type from a typo, so ``type: stagee`` would
        be silently accepted as an opaque placeholder instead of failing. Call
        it explicitly on the parsed dict when reading configs written by a
        newer version is worth that price::

            data = DeviceRegistry.demote_unknown_types(yaml.safe_load(text))
            registry = DeviceRegistry.model_validate(data)
        """
        if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
            return data

        devices = []
        for entry in data["devices"]:
            if (
                isinstance(entry, dict)
                and entry.get("type") is not None
                and entry["type"] not in DEVICE_MODELS
            ):
                entry = {**entry, "type": "unknown", "kind": entry["type"]}
            devices.append(entry)
        return {**data, "devices": devices}


if __name__ == "__main__":
    import json

    print(json.dumps(DeviceRegistry.model_json_schema(), indent=2))
