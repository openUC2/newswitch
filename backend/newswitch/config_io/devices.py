"""Device dataclasses: the interface between ``newswitch-config.yaml`` and newswitch.

Every device type is a pydantic dataclass -- a real `dataclasses.dataclass` that also
validates, fills in defaults and exports a JSON Schema from the same definition. The
entry's ``type`` key selects the class:

    ============ ==================== ==================================
    type         class                manager
    ============ ==================== ==================================
    lightsource  `LightsourceConfig`  Illumination
    detector     `DetectorConfig`     Detector
    controller   `ControllerConfig`   (none yet)
    stage        `StageConfig`        Stage (axes: `AxisConfig`)
    objective    `ObjectiveConfig`    ObjectiveLens
    revolver     `RevolverConfig`     FilterBank / Objective turret
    filter       `FilterConfig`       Filter
    ============ ==================== ==================================

Field conventions
-----------------
* A field without a default is required; ``steps_per_um`` is required but may be null.
* Fields the device firmware can report carry ``x_firmware`` in their metadata
  (``"full"``, or ``"limits"`` for physical values whose ``value`` stays user-owned).
* The mapping key of an entry is its ``device_id``; the loader fills it in.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self, TypeVar, Union

from pydantic import AfterValidator, Field, model_validator
from pydantic.dataclasses import dataclass

from .connection import Connection
from .values import (
    STRICT,
    FloatOrPair,
    Firmware,
    IntPair,
    PhysVal,
    PositiveFloat,
    PositiveInt,
    Trigger,
    as_pair,
    firmware_meta,
    in_unit,
    non_negative,
    phys_meta,
    positive,
)

SpectralShape = Literal["gauss", "tophat"]
AxisLabel = Literal["x", "y", "z", "a", "rx", "ry", "rz"]


# ---------------------------------------------------------------------------
# Common bases
# ---------------------------------------------------------------------------


@dataclass(kw_only=True, config=STRICT)
class DeviceBase:
    """Fields shared by every device type."""

    name: str = Field(description="Model designation")
    device_id: str = Field(description="Unique identifier; equals the entry's mapping key")
    manufacturer: Annotated[str | None, firmware_meta("Vendor name")] = None
    tags: list[str] = Field(default_factory=list, description="Free-form labels")


@dataclass(kw_only=True, config=STRICT)
class ConnectedDevice(DeviceBase):
    """A device reached either through its own connection or through a controller."""

    connection: Connection | None = Field(
        default=None, description="Own connection; required when no controller is given"
    )
    controller: str | None = Field(
        default=None, description="device_id of the controller this device is attached to"
    )

    @model_validator(mode="after")
    def _connection_or_controller(self) -> Self:
        if self.connection is None and self.controller is None:
            raise ValueError("needs either 'connection' or 'controller'")
        if self.connection is not None and self.controller is not None:
            raise ValueError("'connection' and 'controller' are mutually exclusive")
        return self


# ---------------------------------------------------------------------------
# Device types
# ---------------------------------------------------------------------------


@dataclass(kw_only=True, config=STRICT)
class ControllerConfig(DeviceBase):
    """Controller board (e.g. UC2 mainboard) that other devices are attached to."""

    type: Literal["controller"] = "controller"
    connection: Connection = Field(description="Connection to the controller")
    firmware: Firmware = Field(description="Firmware running on the controller")


@dataclass(kw_only=True, config=STRICT)
class LightsourceConfig(ConnectedDevice):
    """Illumination source (LED, laser, ...)."""

    type: Literal["lightsource"] = "lightsource"
    wavelength: PositiveFloat = Field(description="Wavelength in nm")
    bandwidth: PositiveFloat | None = Field(default=None, description="Bandwidth in nm")
    spec_shape: SpectralShape | None = Field(default=None, description="Spectral shape")
    channels: Annotated[PositiveInt, firmware_meta("Number of color/spectral channels")] = 1
    max_intensity: float | None = Field(
        default=None, ge=0, description="Maximum intensity; None means not settable"
    )
    coherence: Literal["coherent", "incoherent", "partial"] = "incoherent"
    polarization: Literal["s", "p", "random"] = "random"
    trigger: Trigger | None = None


@dataclass(kw_only=True, config=STRICT)
class DetectorConfig(ConnectedDevice):
    """Camera or single-diode detector."""

    type: Literal["detector"] = "detector"
    pixelcount: Annotated[IntPair | None, firmware_meta("Sensor resolution [x, y]")] = None
    pixelpitch_um: Annotated[
        FloatOrPair | None, firmware_meta("Center-to-center pixel distance in um")
    ] = None
    pixelsize_um: Annotated[
        FloatOrPair | None, firmware_meta("Photosensitive width per pixel in um; <= pitch")
    ] = None
    channels: Annotated[PositiveInt, firmware_meta("Number of color/spectral channels")] = 1
    exposure_time_ms: Annotated[
        PhysVal | None,
        AfterValidator(in_unit("ms")),
        AfterValidator(positive),
        phys_meta("ms", firmware="limits", description="Integration time"),
    ] = None
    framerate_per_sec: Annotated[
        PhysVal | None,
        AfterValidator(in_unit("Hz")),
        AfterValidator(positive),
        phys_meta("Hz", firmware="limits", description="Frame rate"),
    ] = None
    gain_db: Annotated[
        PhysVal | None,
        AfterValidator(in_unit("dB")),
        AfterValidator(non_negative),
        phys_meta("dB", firmware="limits", description="Analog gain"),
    ] = None
    binning: Annotated[Literal[1, 2, 4], firmware_meta("Symmetric hardware binning")] = 1
    trigger: Trigger | None = None

    @model_validator(mode="after")
    def _pixelsize_within_pitch(self) -> Self:
        if self.pixelsize_um is not None and self.pixelpitch_um is not None:
            size, pitch = as_pair(self.pixelsize_um), as_pair(self.pixelpitch_um)
            if size[0] > pitch[0] or size[1] > pitch[1]:
                raise ValueError(f"pixelsize_um {size} exceeds pixelpitch_um {pitch}")
        return self

    @property
    def pixelpitch_xy(self) -> tuple[float, float] | None:
        """Pixel pitch as an explicit ``(x, y)`` pair, None when not known."""
        return None if self.pixelpitch_um is None else as_pair(self.pixelpitch_um)

    @property
    def pixelsize_xy(self) -> tuple[float, float] | None:
        """Photosensitive pixel size as ``(x, y)``; falls back to the pitch when not stated."""
        if self.pixelsize_um is not None:
            return as_pair(self.pixelsize_um)
        return self.pixelpitch_xy

    @property
    def sensor_size_mm(self) -> tuple[float, float] | None:
        """Physical sensor extent (width, height) in mm, None when not known."""
        pitch = self.pixelpitch_xy
        if self.pixelcount is None or pitch is None:
            return None
        return (self.pixelcount[0] * pitch[0] / 1000.0, self.pixelcount[1] * pitch[1] / 1000.0)


@dataclass(kw_only=True, config=STRICT)
class AxisConfig:
    """One motorized axis of a stage (no ``type`` key; only valid inside a stage)."""

    label: AxisLabel = Field(description="Direction of the axis")
    steps_per_um: Annotated[
        PositiveFloat | None, firmware_meta("Motor steps per um; null for a servo stage")
    ]
    homing_required: Annotated[bool, firmware_meta("Axis must be homed before use")]
    inverted: bool = False
    pos: Annotated[
        PhysVal | None,
        AfterValidator(in_unit("um")),
        phys_meta("um", firmware="full", description="Position; min/max give the travel"),
    ] = None
    vel: Annotated[
        PhysVal | None,
        AfterValidator(in_unit("um/s")),
        AfterValidator(positive),
        phys_meta("um/s", firmware="full", description="Velocity"),
    ] = None
    acc: Annotated[
        PhysVal | None,
        AfterValidator(in_unit("um/s**2")),
        AfterValidator(positive),
        phys_meta("um/s**2", firmware="full", description="Acceleration"),
    ] = None
    jerk: Annotated[
        PhysVal | None,
        AfterValidator(in_unit("um/s**3")),
        AfterValidator(positive),
        phys_meta("um/s**3", firmware="full", description="Jerk"),
    ] = None


@dataclass(kw_only=True, config=STRICT)
class StageConfig(ConnectedDevice):
    """Motorized stage made of one or more axes."""

    type: Literal["stage"] = "stage"
    axes: list[AxisConfig] = Field(min_length=1, description="Axes of the stage")

    @model_validator(mode="after")
    def _unique_labels(self) -> Self:
        labels = [axis.label for axis in self.axes]
        if len(labels) != len(set(labels)):
            raise ValueError(f"duplicate axis labels: {labels}")
        return self

    def axis(self, label: AxisLabel) -> AxisConfig | None:
        """Return the axis with `label`, or None when the stage has no such axis.

        Args:
            label: Axis label, e.g. ``"x"``.

        Returns:
            The matching axis or None.
        """
        for axis in self.axes:
            if axis.label == label:
                return axis
        return None


@dataclass(kw_only=True, config=STRICT)
class ObjectiveConfig(DeviceBase):
    """Objective lens (passive; mounted in a revolver)."""

    type: Literal["objective"] = "objective"
    magnification: PositiveFloat = Field(description="Magnification")
    na: PositiveFloat = Field(description="Numerical aperture")
    wd: PositiveFloat = Field(description="Working distance in mm")


@dataclass(kw_only=True, config=STRICT)
class FilterConfig(DeviceBase):
    """Optical filter (passive; mounted in a revolver)."""

    type: Literal["filter"] = "filter"
    wavelength: PositiveFloat = Field(description="Center wavelength in nm")
    bandwidth: PositiveFloat | None = Field(default=None, description="Bandwidth in nm")
    spec_shape: SpectralShape | None = Field(default=None, description="Spectral shape")
    transmission: float = Field(default=1.0, ge=0.0, le=1.0, description="Peak transmission")


@dataclass(kw_only=True, config=STRICT)
class RevolverConfig(ConnectedDevice):
    """Filter wheel or objective turret holding objectives or filters."""

    type: Literal["revolver"] = "revolver"
    channels: list[str | None] = Field(
        min_length=1,
        description="device_id of the objective/filter at each position; null = empty",
    )
    selected_channel: Annotated[
        int, Field(ge=0), firmware_meta("Position (0-based index into channels) in use")
    ] = 0

    @model_validator(mode="after")
    def _selected_in_range(self) -> Self:
        if self.selected_channel >= len(self.channels):
            raise ValueError(
                f"selected_channel {self.selected_channel} out of range "
                f"(revolver has {len(self.channels)} positions)"
            )
        return self

    @property
    def selected_device_id(self) -> str | None:
        """device_id at the selected position, None when that position is empty."""
        return self.channels[self.selected_channel]


# ---------------------------------------------------------------------------
# Whole file
# ---------------------------------------------------------------------------

Device = Annotated[
    Union[
        LightsourceConfig,
        DetectorConfig,
        ControllerConfig,
        StageConfig,
        ObjectiveConfig,
        RevolverConfig,
        FilterConfig,
    ],
    Field(discriminator="type"),
]

#: ``type`` key -> dataclass.
DEVICE_TYPES: dict[str, type[DeviceBase]] = {
    "lightsource": LightsourceConfig,
    "detector": DetectorConfig,
    "controller": ControllerConfig,
    "stage": StageConfig,
    "objective": ObjectiveConfig,
    "revolver": RevolverConfig,
    "filter": FilterConfig,
}

T = TypeVar("T", bound=DeviceBase)


@dataclass(kw_only=True, config=STRICT)
class NewswitchConfig:
    """Top level of ``newswitch-config.yaml``."""

    newswitch_version: str = Field(description="newswitch version the file was written for")
    devices: dict[str, Device] = Field(description="All devices, keyed by device_id")

    @model_validator(mode="after")
    def _keys_are_device_ids(self) -> Self:
        for key, device in self.devices.items():
            if device.device_id != key:
                raise ValueError(f"devices.{key}: device_id {device.device_id!r} != key {key!r}")
        return self

    def of_type(self, cls: type[T]) -> list[T]:
        """All devices of one class, in file order.

        Args:
            cls: A device dataclass, e.g. `DetectorConfig`.

        Returns:
            The matching devices.
        """
        return [device for device in self.devices.values() if isinstance(device, cls)]

    def slot_of(self, device_id: str) -> int:
        """1-based position of a device among the devices of its type, in file order.

        Args:
            device_id: The device.

        Returns:
            The slot number used by the managers.

        Raises:
            KeyError: No such device.
        """
        device = self.devices[device_id]
        same_type = [d.device_id for d in self.devices.values() if type(d) is type(device)]
        return same_type.index(device_id) + 1

    @property
    def lightsources(self) -> list[LightsourceConfig]:
        """All light sources, in file order."""
        return self.of_type(LightsourceConfig)

    @property
    def detectors(self) -> list[DetectorConfig]:
        """All detectors, in file order."""
        return self.of_type(DetectorConfig)

    @property
    def controllers(self) -> list[ControllerConfig]:
        """All controllers, in file order."""
        return self.of_type(ControllerConfig)

    @property
    def stages(self) -> list[StageConfig]:
        """All stages, in file order."""
        return self.of_type(StageConfig)

    @property
    def objectives(self) -> list[ObjectiveConfig]:
        """All objectives, in file order."""
        return self.of_type(ObjectiveConfig)

    @property
    def revolvers(self) -> list[RevolverConfig]:
        """All revolvers, in file order."""
        return self.of_type(RevolverConfig)

    @property
    def filters(self) -> list[FilterConfig]:
        """All filters, in file order."""
        return self.of_type(FilterConfig)


def field_markers(cls: type[Any]) -> dict[str, dict[str, Any]]:
    """Read the ``x_unit`` / ``x_firmware`` markers of a config dataclass.

    Args:
        cls: A device dataclass or `AxisConfig`.

    Returns:
        ``{field_name: {"x_unit": ..., "x_firmware": ...}}`` for every marked field.
    """
    markers: dict[str, dict[str, Any]] = {}
    for name, info in cls.__pydantic_fields__.items():
        extra = info.json_schema_extra
        if isinstance(extra, dict):
            found = {k: v for k, v in extra.items() if k in ("x_unit", "x_firmware")}
            if found:
                markers[name] = found
    return markers
