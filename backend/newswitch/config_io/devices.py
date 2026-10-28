"""Device dataclasses: the interface between ``newswitch-config.yaml`` and newswitch.

Every device type is a pydantic dataclass -- a real `dataclasses.dataclass` that also
validates, fills in defaults and exports a JSON Schema from the same definition. The
entry's ``type`` key selects the class:

    ============ ==================== ==========================================
    type         class                used for
    ============ ==================== ==========================================
    lightsource  `LightsourceConfig`  Illumination
    detector     `DetectorConfig`     Detector
    controller   `ControllerConfig`   connection + mapping of the devices behind it
    stage        `StageConfig`        Stage: axes grouped by direction
    axis         `AxisConfig`         one motor; also a filter/objective wheel
    objective    `ObjectiveConfig`    ObjectiveLens
    filter       `FilterConfig`       Filter
    ============ ==================== ==========================================

Field conventions
-----------------
* A field without a default is required; ``steps_per_um`` is required but may be null.
* Fields the device firmware can report carry ``x_firmware`` in their metadata
  (``"full"``, or ``"limits"`` for physical values whose ``value`` stays user-owned).
* The mapping key of an entry identifies the device; ``name`` defaults to it.
* Only a controller knows how to reach hardware: its ``connection`` and its ``mapping``
  (device key -> address on that controller). The other devices carry no connection data.
* Device entries and mapping entries accept further keys. They are kept in ``extras`` and
  are not validated.
* A filter or objective wheel is a stage with one axis whose ``pos`` presets name the
  filters/objectives: ``preset_vals: {0: "null", 1000: flt-gfp}`` (``"null"`` = empty).
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any, Literal, Self, TypeVar, Union

from pydantic import AfterValidator, ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass
from pydantic.json_schema import SkipJsonSchema

from .connection import Connection
from .values import (
    STRICT,
    Firmware,
    FloatOrPair,
    IntPair,
    NonNegativeInt,
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

#: Configuration of device and mapping entries: further keys are allowed (see `_Extensible`).
OPEN = ConfigDict(extra="ignore")

#: Words in a mapping ``type`` marking a device on a PWM output (then ``pwm_max`` is needed).
PWM_TYPE_WORDS = ("laser", "pwm")


# ---------------------------------------------------------------------------
# Common bases
# ---------------------------------------------------------------------------


@dataclass(kw_only=True, config=OPEN)
class _Extensible:
    """Base of entries that accept further keys; those are collected in `extras`."""

    extras: SkipJsonSchema[dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_extras(cls, data: Any) -> Any:  # noqa: ANN401 - raw input
        """Move every key that is not a field into ``extras``."""
        if not isinstance(data, dict):
            return data
        known = {field.name for field in dataclasses.fields(cls)}
        further = {key: value for key, value in data.items() if key not in known}
        if not further:
            return data
        kept = {key: value for key, value in data.items() if key in known}
        return {**kept, "extras": {**kept.get("extras", {}), **further}}


@dataclass(kw_only=True, config=OPEN)
class DeviceBase(_Extensible):
    """Fields shared by every device type."""

    name: str | None = Field(default=None, description="Display name; defaults to the key")
    manufacturer: Annotated[str | None, firmware_meta("Vendor name")] = None
    tags: list[str] = Field(default_factory=list, description="Free-form labels")


# ---------------------------------------------------------------------------
# Controller and its mapping
# ---------------------------------------------------------------------------


@dataclass(kw_only=True, config=OPEN)
class MappingEntry(_Extensible):
    """Address of one device on its controller."""

    type: str = Field(description="Kind of link on the controller, e.g. canopen-motor")
    id: NonNegativeInt = Field(description="CAN node id, or the id in the UC2-REST nomenclature")
    subid: NonNegativeInt = Field(default=0, description="Sub-address below id (CAN sub id)")
    pwm_max: PositiveInt | None = Field(
        default=None, description="Largest PWM value; required for PWM outputs, else null"
    )

    @property
    def is_pwm(self) -> bool:
        """True when ``type`` names a PWM output (it contains "laser" or "pwm")."""
        kind = self.type.lower()
        return any(word in kind for word in PWM_TYPE_WORDS)

    @property
    def address(self) -> tuple[int, int]:
        """``(id, subid)``; unique per controller."""
        return (self.id, self.subid)

    @model_validator(mode="after")
    def _pwm_max_matches_type(self) -> Self:
        if self.is_pwm and self.pwm_max is None:
            raise ValueError(f"type {self.type!r} is a PWM output and needs pwm_max")
        if not self.is_pwm and self.pwm_max is not None:
            raise ValueError(
                f"pwm_max is only valid for PWM outputs (type containing "
                f"{' or '.join(PWM_TYPE_WORDS)}), not for {self.type!r}"
            )
        return self


@dataclass(kw_only=True, config=OPEN)
class ControllerConfig(DeviceBase):
    """Controller board (e.g. UC2 mainboard): the only device with a connection."""

    type: Literal["controller"] = "controller"
    connection: Connection = Field(description="How the controller is reached")
    firmware: Firmware = Field(
        default_factory=Firmware, description="Firmware running on the controller"
    )
    mapping: dict[str, MappingEntry] = Field(
        description="Key of a device in this file -> its address on this controller"
    )

    @model_validator(mode="after")
    def _unique_addresses(self) -> Self:
        used: dict[tuple[int, int], list[str]] = {}
        for key, entry in self.mapping.items():
            used.setdefault(entry.address, []).append(key)
        clashes = [
            f"id {address[0]}/subid {address[1]} is used by {', '.join(keys)}"
            for address, keys in used.items()
            if len(keys) > 1
        ]
        if clashes:
            raise ValueError("mapping: " + "; ".join(clashes))
        return self


# ---------------------------------------------------------------------------
# Device types
# ---------------------------------------------------------------------------


@dataclass(kw_only=True, config=OPEN)
class LightsourceConfig(DeviceBase):
    """Illumination source (LED, laser, ...)."""

    type: Literal["lightsource"] = "lightsource"
    wavelength: PositiveFloat | None = Field(default=None, description="Wavelength in nm")
    bandwidth: PositiveFloat | None = Field(default=None, description="Bandwidth in nm")
    spec_shape: SpectralShape | None = Field(default=None, description="Spectral shape")
    channels: Annotated[PositiveInt, firmware_meta("Number of color/spectral channels")] = 1
    coherence: Literal["coherent", "incoherent", "partial"] = "incoherent"
    pulse_length: PositiveFloat | None = Field(
        default=None, description="Pulse length; null = continuous wave"
    )
    pulse_length_unit: str | None = Field(
        default=None, description="Unit of pulse_length; ignored without pulse_length"
    )
    polarization: Literal["s", "p", "random"] = "random"
    trigger: Trigger | None = None


@dataclass(kw_only=True, config=OPEN)
class DetectorConfig(DeviceBase):
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


@dataclass(kw_only=True, config=OPEN)
class AxisConfig(DeviceBase):
    """One motorized axis; a stage names it under a direction."""

    type: Literal["axis"] = "axis"
    steps_per_um: Annotated[
        PositiveFloat | None, firmware_meta("Motor steps per um; null for a servo axis")
    ]
    inverted: bool = Field(default=False, description="Axis runs in the opposite direction")
    homing_required: Annotated[bool, firmware_meta("Axis must be homed before use")] = False
    pos: Annotated[
        PhysVal | None,
        AfterValidator(in_unit("um")),
        phys_meta(
            "um",
            firmware="full",
            description="Position; min/max give the travel, named presets the wheel slots",
        ),
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


@dataclass(kw_only=True, config=OPEN)
class StageConfig(DeviceBase):
    """Motorized stage: axis devices grouped by direction."""

    type: Literal["stage"] = "stage"
    axes: dict[str, str] = Field(
        min_length=1, description="Direction (e.g. x) -> key of an axis device"
    )
    homing_order: list[str] | None = Field(
        default=None, description="Directions in homing order; null = home all in parallel"
    )

    @model_validator(mode="after")
    def _homing_order_lists_every_axis(self) -> Self:
        order = self.homing_order
        if order is not None and (len(order) != len(set(order)) or set(order) != set(self.axes)):
            raise ValueError(
                f"homing_order {order} must list every axis of the stage "
                f"({', '.join(self.axes)}) exactly once"
            )
        return self


@dataclass(kw_only=True, config=OPEN)
class ObjectiveConfig(DeviceBase):
    """Objective lens (passive; may sit in a wheel)."""

    type: Literal["objective"] = "objective"
    magnification: PositiveFloat = Field(description="Magnification")
    na: PositiveFloat = Field(description="Numerical aperture")
    wd: PositiveFloat = Field(description="Working distance in mm")


@dataclass(kw_only=True, config=OPEN)
class FilterConfig(DeviceBase):
    """Optical filter (passive; may sit in a wheel)."""

    type: Literal["filter"] = "filter"
    wavelength: PositiveFloat | None = Field(default=None, description="Center wavelength in nm")
    bandwidth: PositiveFloat | None = Field(default=None, description="Bandwidth in nm")
    spec_shape: SpectralShape | None = Field(default=None, description="Spectral shape")
    transmission: float = Field(default=1.0, ge=0.0, le=1.0, description="Peak transmission")


# ---------------------------------------------------------------------------
# Whole file
# ---------------------------------------------------------------------------

Device = Annotated[
    Union[
        LightsourceConfig,
        DetectorConfig,
        ControllerConfig,
        StageConfig,
        AxisConfig,
        ObjectiveConfig,
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
    "axis": AxisConfig,
    "objective": ObjectiveConfig,
    "filter": FilterConfig,
}

T = TypeVar("T", bound=DeviceBase)


@dataclass(kw_only=True, config=STRICT)
class BlokEntry:
    """A blok of the ``ui`` section: its BSX source, exactly as the frontend gets it."""

    bsx: str = Field(description="The blok's tree as BSX source")
    description: str | None = Field(
        default=None, description="Shown in the bottom bar; a view's starts with its tab label"
    )
    default: bool = Field(
        default=False, description="The blok shown first (per context: its root, <Html> or <Scene>)"
    )


@dataclass(kw_only=True, config=STRICT)
class UiConfig:
    """A UI section (``ui``, ``agent_ui``): the bloks, and the catalog they are written against."""

    catalog: str = Field(
        pattern=r"^[A-Za-z0-9_-]+@[A-Za-z0-9_.-]+$",
        description="The catalog the bloks were written against, as <name>@<version>",
    )
    bloks: dict[str, BlokEntry] = Field(description="The bloks, keyed by name")


@dataclass(kw_only=True, config=STRICT)
class NewswitchConfig:
    """Top level of ``newswitch-config.yaml``."""

    newswitch_version: str = Field(description="newswitch version the file was written for")
    devices: dict[str, Device] = Field(description="All devices, keyed by their identifier")
    assets: dict[str, str] = Field(
        default_factory=dict,
        description="Files the bloks read as self.assets.<name>, relative to newswitch/",
    )
    ui: UiConfig | None = Field(
        default=None,
        description="The bloks the newswitch frontend shows (FastAPI mode), in its catalog",
    )
    agent_ui: UiConfig | None = Field(
        default=None,
        description="The bloks Orkestrator shows (agent mode), in its standard catalog",
    )

    @model_validator(mode="after")
    def _name_defaults_to_key(self) -> Self:
        for key, device in self.devices.items():
            if device.name is None:
                device.name = key
        return self

    def keyed(self, cls: type[T]) -> dict[str, T]:
        """All devices of one class with their keys, in file order.

        Args:
            cls: A device dataclass, e.g. `DetectorConfig`.

        Returns:
            ``{key: device}`` for the matching devices.
        """
        return {key: device for key, device in self.devices.items() if isinstance(device, cls)}

    def of_type(self, cls: type[T]) -> list[T]:
        """All devices of one class, in file order.

        Args:
            cls: A device dataclass, e.g. `DetectorConfig`.

        Returns:
            The matching devices.
        """
        return list(self.keyed(cls).values())

    def slot_of(self, key: str) -> int:
        """1-based position of a device among the devices of its type, in file order.

        Args:
            key: The device.

        Returns:
            The slot number used by the managers.

        Raises:
            KeyError: No such device.
        """
        same_type = list(self.keyed(type(self.devices[key])))
        return same_type.index(key) + 1

    def stage_axes(self, stage: StageConfig) -> dict[str, AxisConfig]:
        """Resolve a stage's directions to its axis devices.

        Args:
            stage: A stage of this configuration.

        Returns:
            ``{direction: axis}``; directions naming no axis device are left out (a loaded
            configuration has none, see `references.check_references`).
        """
        axes = self.keyed(AxisConfig)
        return {direction: axes[key] for direction, key in stage.axes.items() if key in axes}

    def controller_of(self, key: str) -> tuple[str, MappingEntry] | None:
        """The controller a device is mapped to, with its address there.

        Args:
            key: The device.

        Returns:
            ``(controller key, mapping entry)``, or None when no controller maps it.
        """
        for controller_key, controller in self.keyed(ControllerConfig).items():
            entry = controller.mapping.get(key)
            if entry is not None:
                return controller_key, entry
        return None

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
    def axes(self) -> list[AxisConfig]:
        """All axes, in file order."""
        return self.of_type(AxisConfig)

    @property
    def objectives(self) -> list[ObjectiveConfig]:
        """All objectives, in file order."""
        return self.of_type(ObjectiveConfig)

    @property
    def filters(self) -> list[FilterConfig]:
        """All filters, in file order."""
        return self.of_type(FilterConfig)


def field_markers(cls: type[Any]) -> dict[str, dict[str, Any]]:
    """Read the ``x_unit`` / ``x_firmware`` markers of a config dataclass.

    Args:
        cls: A device dataclass.

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
