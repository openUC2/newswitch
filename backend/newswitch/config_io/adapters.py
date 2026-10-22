"""Translate config dataclasses into the dataclasses the managers work with, and back.

Direction config -> managers (at startup):

    ==================== ===================================================
    config               managers
    ==================== ===================================================
    `LightsourceConfig`  `Illumination` (slot = file order among lightsources)
    `DetectorConfig`     `Detector` (exposure ms -> s; sensor, pitch, frame rate, binning)
    `ObjectiveConfig`    `ObjectiveLens`, default slot from the objective wheel
    `FilterConfig`       `Filter`, default slot from the filter wheel
    `StageConfig`        limits of `StageState` (directions x/y/z/a of the first
                         stage that is not a wheel, until an axis manager exists)
    `ControllerConfig`   `SerialSettings` for the UC2 serial manager
    `DetectorConfig` +   `Detector` with its camera fields, plus vendor options, for
    camera controller    the UC2 detector manager (detectors behind a gige-vision /
                         usb3-vision controller)
    ==================== ===================================================

A **wheel** is an axis whose ``pos`` presets are named after filters or objectives, e.g.
``preset_vals: {0: "null", 1000: flt-gfp}``; a name that is no such device (``"null"``)
marks an empty position, and ``pos.selected_index`` is the position in use.

Each builder returns None when the file has no device of that kind, so the caller can
keep a manager's built-in defaults (the virtual microscope relies on that).

Direction managers -> config (at shutdown): `sync_runtime_state` copies the values the
software may change (exposure, gain, selected wheel positions, stage position) into
the configuration, from where `ConfigFile.save` writes them back.
"""

from __future__ import annotations

import glob
import logging
import math
from dataclasses import dataclass
from typing import Any

from ..protocols.detector import CameraState, Colormap, Detector
from ..protocols.filter_bank import Filter, FilterBankState
from ..protocols.illumination import Illumination, IlluminationKind
from ..protocols.objective import ObjectiveLens, ObjectiveState
from ..protocols.stage import StageState
from .connection import GigEVisionProtocol, SerialTransport, Uc2RestProtocol, Usb3VisionProtocol
from .devices import (
    AxisConfig,
    ControllerConfig,
    DetectorConfig,
    DeviceBase,
    FilterConfig,
    NewswitchConfig,
    ObjectiveConfig,
    StageConfig,
)
from .errors import ConfigError
from .values import PhysVal

logger = logging.getLogger(__name__)

#: Slot of the pseudo filter standing for an empty filter-wheel position.
OPEN_FILTER_SLOT = 0

#: Upper end of every light source's intensity range (percent).
FULL_INTENSITY = 100.0

_COLORMAPS = (Colormap.RED, Colormap.GREEN, Colormap.BLUE)


def _finite(value: float, fallback: float) -> float:
    """Return `value` if finite, else `fallback` (unset limits are +-inf)."""
    return value if math.isfinite(value) else fallback


def _limit(value: float) -> float | None:
    """Return a limit if it is set (finite), else None."""
    return value if math.isfinite(value) else None


# ---------------------------------------------------------------------------
# Wheels and the motion stage
# ---------------------------------------------------------------------------


@dataclass
class Wheel:
    """An axis whose named positions hold filters or objectives."""

    key: str
    """Key of the axis."""
    axis: AxisConfig
    positions: list[str | None]
    """Key of the device at each preset position, None for an empty position."""
    values: list[float]
    """Axis position (um) of each preset."""

    @property
    def selected(self) -> int:
        """Position in use; the first one when none is selected."""
        assert self.axis.pos is not None
        index = self.axis.pos.selected_index
        return 0 if index is None else index


def wheel_holding(config: NewswitchConfig, cls: type[DeviceBase]) -> Wheel | None:
    """First axis whose ``pos`` presets name devices of `cls` (filters or objectives).

    Args:
        config: The loaded configuration.
        cls: `FilterConfig` or `ObjectiveConfig`.

    Returns:
        The wheel, or None when no axis holds such devices.
    """
    held = config.keyed(cls)
    for key, axis in config.keyed(AxisConfig).items():
        presets = None if axis.pos is None else axis.pos.preset_vals
        if not isinstance(presets, dict) or not any(name in held for name in presets.values()):
            continue
        positions = [name if name in held else None for name in presets.values()]
        return Wheel(key=key, axis=axis, positions=positions, values=list(presets))
    return None


def motion_stage(config: NewswitchConfig) -> tuple[str, StageConfig] | None:
    """The stage moving the sample: the first stage that has no wheel axis.

    Args:
        config: The loaded configuration.

    Returns:
        ``(key, stage)``, or None when every stage is a wheel (or there is none).
    """
    wheels = {
        wheel.key
        for wheel in (
            wheel_holding(config, FilterConfig),
            wheel_holding(config, ObjectiveConfig),
        )
        if wheel is not None
    }
    candidates = [
        (key, stage)
        for key, stage in config.keyed(StageConfig).items()
        if not wheels & set(stage.axes.values())
    ]
    if len(candidates) > 1:
        logger.warning("%d stages configured, only %r is used", len(candidates), candidates[0][0])
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# config -> managers
# ---------------------------------------------------------------------------


def illuminations(config: NewswitchConfig) -> list[Illumination] | None:
    """Build the illumination sources.

    Every source has the intensity range 0..`FULL_INTENSITY`. The first source starts
    switched on at full intensity, the others off. An unknown wavelength becomes 0.

    Args:
        config: The loaded configuration.

    Returns:
        One `Illumination` per light source, or None when there are none.
    """
    sources = config.lightsources
    if not sources:
        return None
    return [
        Illumination(
            kind=IlluminationKind.LASER if source.coherence == "coherent" else IlluminationKind.LED,
            slot=index + 1,
            wavelength=0.0 if source.wavelength is None else source.wavelength,
            channel=source.channels,
            max_intensity=FULL_INTENSITY,
            min_intensity=0.0,
            intensity=FULL_INTENSITY if index == 0 else 0.0,
            is_active=index == 0,
        )
        for index, source in enumerate(sources)
    ]


def detectors(config: NewswitchConfig) -> list[Detector] | None:
    """Build the detectors; exposure times are converted from ms to s.

    Values the file does not state keep the `Detector` defaults. The sensor resolution
    gives the image size as well; the managers replace both with what the device reports.

    Args:
        config: The loaded configuration.

    Returns:
        One `Detector` per detector, or None when there are none.
    """
    devices = config.keyed(DetectorConfig)
    if not devices:
        return None
    defaults = Detector()
    result = []
    for index, (key, device) in enumerate(devices.items()):
        width, height = device.pixelcount or (defaults.width, defaults.height)
        pitch = device.pixelpitch_xy
        size = device.pixelsize_xy
        exposure = device.exposure_time_ms
        gain = device.gain_db
        frame_rate = device.framerate_per_sec
        detector = Detector(
            slot=index + 1,
            name=device.name or defaults.name,
            width=width,
            height=height,
            is_active=True,
            current_colormap=_COLORMAPS[index % len(_COLORMAPS)],
            pixel_size_um=defaults.pixel_size_um if size is None else size[0],
            key=key,
            manufacturer=device.manufacturer,
            sensor_width=width,
            sensor_height=height,
            pixel_pitch_um=None if pitch is None else pitch[0],
            current_binning=device.binning,
        )
        if exposure is not None:
            if exposure.value is not None:
                detector.current_exposure_time = exposure.value / 1000.0
            detector.min_exposure_time = _finite(exposure.min / 1000.0, defaults.min_exposure_time)
            detector.max_exposure_time = _finite(exposure.max / 1000.0, defaults.max_exposure_time)
            presets = exposure.preset_values()  # dict: its keys, in file order
            if presets:
                detector.preset_exposure_times = [v / 1000.0 for v in presets]
        if gain is not None:
            if gain.value is not None:
                detector.current_gain = gain.value
            detector.min_gain = _finite(gain.min, defaults.min_gain)
            detector.max_gain = _finite(gain.max, defaults.max_gain)
        if frame_rate is not None:
            detector.current_frame_rate = frame_rate.value
            detector.min_frame_rate = _limit(frame_rate.min)
            detector.max_frame_rate = _limit(frame_rate.max)
        result.append(detector)
    return result


def objective_lenses(config: NewswitchConfig) -> tuple[list[ObjectiveLens], int] | None:
    """Build the objective lenses and the slot selected at startup.

    Args:
        config: The loaded configuration.

    Returns:
        ``(lenses, default_slot)``, or None when there are no objectives. Without an
        objective wheel, or when its selected position is empty, slot 1 is selected.
    """
    objectives = config.keyed(ObjectiveConfig)
    if not objectives:
        return None
    lenses = [
        ObjectiveLens(
            slot=index + 1,
            name=objective.name or key,
            magnification=objective.magnification,
            numerical_aperture=objective.na,
            working_distance=objective.wd,
        )
        for index, (key, objective) in enumerate(objectives.items())
    ]
    wheel = wheel_holding(config, ObjectiveConfig)
    selected = None if wheel is None else wheel.positions[wheel.selected]
    return lenses, 1 if selected is None else config.slot_of(selected)


def filters(config: NewswitchConfig) -> tuple[list[Filter], int] | None:
    """Build the filters and the slot selected at startup.

    An empty filter-wheel position is represented by an "Open" filter in slot
    `OPEN_FILTER_SLOT` (no filtering), which the filter bank needs to have something
    active.

    Args:
        config: The loaded configuration.

    Returns:
        ``(filters, default_slot)``, or None when there are no filters.
    """
    devices = config.keyed(FilterConfig)
    if not devices:
        return None
    result = [
        Filter(
            slot=index + 1,
            name=device.name or key,
            center_wavelength=0.0 if device.wavelength is None else device.wavelength,
            bandwidth=0.0 if device.bandwidth is None else device.bandwidth,
            transmission=device.transmission,
        )
        for index, (key, device) in enumerate(devices.items())
    ]
    wheel = wheel_holding(config, FilterConfig)
    if wheel is None:
        return result, 1
    if None in wheel.positions:
        result.insert(0, Filter(slot=OPEN_FILTER_SLOT, name="Open"))
    selected = wheel.positions[wheel.selected]
    return result, OPEN_FILTER_SLOT if selected is None else config.slot_of(selected)


def apply_stage_limits(config: NewswitchConfig, stage_state: StageState) -> None:
    """Copy the travel (``pos.min``/``pos.max``) of the motion stage into `stage_state`.

    Only finite limits of the directions x, y, z and a are applied; other directions are
    logged and skipped until an axis manager handles arbitrary axes.

    Args:
        config: The loaded configuration.
        stage_state: The shared stage state; modified in place.
    """
    found = motion_stage(config)
    if found is None:
        return
    for direction, axis in config.stage_axes(found[1]).items():
        if axis.pos is None:
            continue
        low, high = axis.pos.min, axis.pos.max
        match direction:
            case "x":
                stage_state.min_x = _finite(low, stage_state.min_x)
                stage_state.max_x = _finite(high, stage_state.max_x)
            case "y":
                stage_state.min_y = _finite(low, stage_state.min_y)
                stage_state.max_y = _finite(high, stage_state.max_y)
            case "z":
                stage_state.min_z = _finite(low, stage_state.min_z)
                stage_state.max_z = _finite(high, stage_state.max_z)
            case "a":
                stage_state.min_a = _finite(low, stage_state.min_a)
                stage_state.max_a = _finite(high, stage_state.max_a)
            case _:
                logger.warning("stage direction %r is not supported yet, skipped", direction)


@dataclass
class SerialSettings:
    """Port and baud rate for the UC2 serial manager."""

    port: str
    baudrate: int


def stage_speed(config: NewswitchConfig) -> float | None:
    """The motion stage's speed in um/s: the slowest of its axes' ``vel``, or None.

    What the virtual stage travels at, so a simulated move takes as long as a real one.
    """
    found = motion_stage(config)
    if found is None:
        return None
    speeds = [
        axis.vel.value
        for axis in config.stage_axes(found[1]).values()
        if axis.vel is not None and axis.vel.value
    ]
    return min(speeds) if speeds else None


def serial_settings(config: NewswitchConfig) -> SerialSettings | None:
    """Serial settings of the first controller speaking uc2-rest over a serial port.

    A ``port_pattern`` is resolved to the first matching device path. Simulated
    controllers are skipped.

    Args:
        config: The loaded configuration.

    Returns:
        The settings, or None when no such controller exists or no port matches.
    """
    for key, controller in config.keyed(ControllerConfig).items():
        connection = controller.connection
        if not isinstance(connection, Uc2RestProtocol):
            continue
        transport = connection.transport
        if not isinstance(transport, SerialTransport):
            continue
        port = transport.port
        if port is None and transport.port_pattern is not None:
            matches = sorted(glob.glob(transport.port_pattern))
            port = matches[0] if matches else None
        if port is None:
            logger.warning("controller %r: no serial port found", key)
            continue
        return SerialSettings(port=port, baudrate=transport.baudrate)
    return None


def _is_int(value: object) -> bool:
    """True for an int that is not a bool (YAML ``true`` must not count as 1)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _camera_problems(extras: dict[str, Any], where: str) -> list[str]:
    """Check the camera keys of a mapping entry (they are extras, so not validated on load).

    Args:
        extras: Further keys of the mapping entry.
        where: Location prefix for the messages.

    Returns:
        One message per invalid key.
    """
    problems = []
    serial = extras.get("serial_number")
    if serial is not None and (not isinstance(serial, str) or not serial):
        problems.append(f"{where}.serial_number: must be a non-empty string (quote numbers)")
    index = extras.get("index")
    if index is not None and (not _is_int(index) or index < 0):
        problems.append(f"{where}.index: must be an integer >= 0")
    buffer_size = extras.get("buffer_size")
    if buffer_size is not None and (not _is_int(buffer_size) or buffer_size < 2):
        problems.append(f"{where}.buffer_size: must be an integer >= 2")
    store = extras.get("store_image_data")
    if store is not None and not isinstance(store, bool):
        problems.append(f"{where}.store_image_data: must be true or false")
    options = extras.get("vendor_options")
    if options is not None and not isinstance(options, dict):
        problems.append(f"{where}.vendor_options: must be a mapping")
    return problems


def _set_camera(
    detector: Detector,
    connection: GigEVisionProtocol | Usb3VisionProtocol,
    extras: dict[str, Any],
) -> None:
    """Fill in how to open the camera behind a detector.

    Args:
        detector: The detector (from `detectors`); modified in place.
        connection: Connection of the controller the detector is mapped to.
        extras: Further keys of the detector's mapping entry (already checked).
    """
    serial = extras.get("serial_number")
    index = extras.get("index")
    if serial is None and index is None:  # fall back to the connection's selector
        serial = connection.serial_number
        index = connection.index if isinstance(connection, Usb3VisionProtocol) else None
    detector.connection_type = "GigE" if isinstance(connection, GigEVisionProtocol) else "USB3"
    detector.serial_number = serial
    detector.device_index = index
    detector.buffer_size = extras.get("buffer_size")
    detector.store_image_data = extras.get("store_image_data")


def cameras(
    config: NewswitchConfig,
) -> tuple[list[Detector], dict[int, dict[str, Any]]] | None:
    """Build the detectors to open as cameras, with their vendor options.

    A camera is a detector mapped by a controller whose connection is a camera link
    (``protocol: gige-vision`` or ``usb3-vision``); the camera library handles the
    transport. Other detectors are skipped with a warning.

    The vendor is the detector's ``manufacturer``, passed on unchanged: newswitch knows no
    vendor names, the camera library decides which it supports. The detector's mapping
    entry may carry these further keys:

    ``serial_number`` / ``index``
        Which camera to open (not both); without them the connection's selector is used,
        and without that the first camera.
    ``buffer_size``, ``store_image_data``
        Ring-buffer size in images, and whether every image is recorded to disk.
    ``vendor_options``
        Mapping of vendor-specific options, passed on unchanged. They are returned beside
        the detectors: a detector is shared state, these options are not.

    The slot is the detector's position among all detectors (as in `detectors`).

    Args:
        config: The loaded configuration.

    Returns:
        The camera detectors (`detectors` plus the camera fields) and the vendor options
        per slot, or None when there are no cameras.

    Raises:
        ConfigError: A mapping entry carries an invalid camera key.
    """
    controllers = config.keyed(ControllerConfig)
    keyed = config.keyed(DetectorConfig)
    result: list[Detector] = []
    vendor_options: dict[int, dict[str, Any]] = {}
    problems: list[str] = []
    for detector in detectors(config) or []:
        key = detector.key or ""
        found = config.controller_of(key)
        connection = None if found is None else controllers[found[0]].connection
        if found is None or not isinstance(connection, GigEVisionProtocol | Usb3VisionProtocol):
            logger.warning("detector %r is not mapped to a camera controller, skipped", key)
            continue
        controller_key, entry = found
        where = f"devices.{controller_key}.mapping.{key}"
        invalid = _camera_problems(entry.extras, where)
        if invalid:
            problems.extend(invalid)
            continue
        _set_camera(detector, connection, entry.extras)
        if detector.serial_number is not None and detector.device_index is not None:
            problems.append(
                f"{where}: serial_number and index both select the camera, give only one "
                f"(here or in the connection of {controller_key!r})"
            )
            continue
        detector.name = keyed[key].name or key
        result.append(detector)
        vendor_options[detector.slot] = dict(entry.extras.get("vendor_options") or {})
    if problems:
        raise ConfigError("invalid camera settings", problems)
    return (result, vendor_options) if result else None


# ---------------------------------------------------------------------------
# managers -> config
# ---------------------------------------------------------------------------


def _with_value(phys: PhysVal | None, value: float, unit: str, where: str) -> PhysVal | None:
    """Return `phys` with a new runtime value, or unchanged if the value is out of range.

    Args:
        phys: The configured physical value, or None (then one is created).
        value: The runtime value, already in `unit`.
        unit: Unit of the field.
        where: Location for the log message.

    Returns:
        The physical value to store.
    """
    if phys is None:
        return PhysVal(value=value, unit=unit)
    if not phys.min <= value <= phys.max:
        logger.warning(
            "%s: runtime value %s outside [%s, %s], not saved", where, value, phys.min, phys.max
        )
        return phys
    phys.value = value
    return phys


def _select(config: NewswitchConfig, wheel: Wheel | None, slot: int) -> None:
    """Turn `wheel` to the position holding the device that has `slot`.

    Sets ``pos.selected_index`` and moves ``pos.value`` to that preset.

    Args:
        config: The configuration.
        wheel: The wheel, or None.
        slot: Slot of the selected objective/filter; `OPEN_FILTER_SLOT` = empty position.
    """
    if wheel is None or wheel.axis.pos is None:
        return
    for position, ref in enumerate(wheel.positions):
        matches = (
            ref is None
            if slot == OPEN_FILTER_SLOT
            else (ref is not None and config.slot_of(ref) == slot)
        )
        if matches:
            wheel.axis.pos.selected_index = position
            wheel.axis.pos = _with_value(
                wheel.axis.pos, wheel.values[position], "um", f"devices.{wheel.key}.pos"
            )
            return


def sync_runtime_state(
    config: NewswitchConfig,
    camera_state: CameraState,
    objective_state: ObjectiveState,
    filter_bank_state: FilterBankState,
    stage_state: StageState,
) -> None:
    """Copy the values the software changes at runtime back into the configuration.

    Args:
        config: The configuration; modified in place.
        camera_state: Exposure (s) and gain per detector slot.
        objective_state: Selected objective slot.
        filter_bank_state: Selected filter slot.
        stage_state: Current stage position.
    """
    for index, (key, device) in enumerate(config.keyed(DetectorConfig).items()):
        slot = index + 1
        runtime = next((d for d in camera_state.detectors if d.slot == slot), None)
        if runtime is None:
            continue
        where = f"devices.{key}"
        device.exposure_time_ms = _with_value(
            device.exposure_time_ms,
            runtime.current_exposure_time * 1000.0,
            "ms",
            f"{where}.exposure_time_ms",
        )
        device.gain_db = _with_value(device.gain_db, runtime.current_gain, "dB", f"{where}.gain_db")

    _select(config, wheel_holding(config, ObjectiveConfig), objective_state.slot)
    _select(config, wheel_holding(config, FilterConfig), filter_bank_state.current_slot)

    found = motion_stage(config)
    if found is None:
        return
    positions = {"x": stage_state.x, "y": stage_state.y, "z": stage_state.z, "a": stage_state.a}
    for direction, axis_key in found[1].axes.items():
        axis = config.devices.get(axis_key)
        if direction not in positions or not isinstance(axis, AxisConfig):
            continue
        axis.pos = _with_value(axis.pos, positions[direction], "um", f"devices.{axis_key}.pos")
