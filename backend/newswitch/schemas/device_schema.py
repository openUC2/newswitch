"""Multi-device registry: one file, many device types.

The `type` field acts as a **discriminator**. Pydantic uses it to dispatch each
list entry to exactly one model instead of trying all of them, which keeps
error messages precise:

    devices.1.stage.axes.0.travel_um  -> Input should be greater than 0

instead of the usual union noise ("not valid under any of the given schemas").

Adding a device type takes three steps:
    1. subclass DeviceBase with a new `type: Literal[...]`
    2. add it to the `Device` union below
    3. nothing else -- registry, loader and JSON Schema pick it up automatically
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .camera_schema import CameraSchema


class DeviceBase(BaseModel):
    """Fields shared by every device type."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str = Field(description="Model designation")
    manufacturer: Optional[str] = Field(default=None, description="Vendor name")
    device_id: Optional[str] = Field(
        default=None, description="Identifier of the individual physical unit"
    )
    tags: list[str] = Field(default_factory=list)


class StageAxis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["x", "y", "z", "a", "b", "c"]
    travel_um: float = Field(gt=0, description="Usable travel range in micrometers")
    steps_per_um: float = Field(gt=0, description="Motor steps per micrometer")
    inverted: bool = Field(default=False, description="Flip the positive direction")


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


class FilterSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=0, description="Slot index on the wheel")
    label: str = Field(description="Filter designation, e.g. GFP-525/50")
    center_nm: Optional[float] = Field(default=None, gt=0)
    bandwidth_nm: Optional[float] = Field(default=None, gt=0)


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


# The discriminated union. CameraSchema already carries type="camera".
# `DeviceModel` is the bare union, usable as a return annotation; `Device` adds the
# discriminator and is what the registry field uses.
DeviceModel = Union[CameraSchema, StageDevice, LaserDevice, FilterWheelDevice]
Device = Annotated[DeviceModel, Field(discriminator="type")]

DEVICE_MODELS: dict[str, type[BaseModel]] = {
    "camera": CameraSchema,
    "stage": StageDevice,
    "laser": LaserDevice,
    "filterwheel": FilterWheelDevice,
}


def device_key(dev: DeviceModel) -> str:
    """Stable identifier of a device.

    CameraSchema predates DeviceBase and spells the field ``camera_id``; the
    other types use ``device_id``. Both are optional, so the name is the
    fallback.
    """
    return getattr(dev, "device_id", None) or getattr(dev, "camera_id", None) or dev.name


class DeviceRegistry(BaseModel):
    """Top-level object of a Devices.yml file."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1, description="Registry format version")
    setup: Optional[str] = Field(default=None, description="Name of the setup")
    devices: list[Device] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> "DeviceRegistry":
        seen: dict[str, int] = {}
        for i, dev in enumerate(self.devices):
            key = device_key(dev)
            if key in seen:
                raise ValueError(
                    f"devices[{i}]: duplicate identifier {key!r} (also at devices[{seen[key]}])"
                )
            seen[key] = i
        return self

    def by_type(self, type_: str) -> list[DeviceModel]:
        """All devices of one type, e.g. registry.by_type('camera')."""
        return [d for d in self.devices if d.type == type_]

    def get(self, key: str) -> DeviceModel:
        """Look up one device by device_id, falling back to name."""
        for dev in self.devices:
            if device_key(dev) == key or dev.name == key:
                return dev
        raise KeyError(f"no device with id or name {key!r}")


if __name__ == "__main__":
    import json

    print(json.dumps(DeviceRegistry.model_json_schema(), indent=2))
