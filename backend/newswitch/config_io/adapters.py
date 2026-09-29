"""Translate config dataclasses into the dataclasses the managers work with, and back.

Direction config -> managers (at startup):

    ==================== ===================================================
    config               managers
    ==================== ===================================================
    `LightsourceConfig`  `Illumination` (slot = file order among lightsources)
    `DetectorConfig`     `Detector` (exposure ms -> s)
    `ObjectiveConfig`    `ObjectiveLens`, default slot from the turret
    `FilterConfig`       `Filter`, default slot from the filter wheel
    `StageConfig`        limits of `StageState` (axes x/y/z/a only, until an axis
                         manager exists)
    `ControllerConfig`   `SerialSettings` for the UC2 serial manager
    ==================== ===================================================

Each builder returns None when the file has no device of that kind, so the caller can
keep a manager's built-in defaults (the virtual microscope relies on that).

Direction managers -> config (at shutdown): `sync_runtime_state` copies the values the
software may change (exposure, gain, selected revolver positions, stage position) into
the configuration, from where `ConfigFile.save` writes them back.
"""

from __future__ import annotations

import glob
import logging
import math
from dataclasses import dataclass

from ..protocols.detector import CameraState, Colormap, Detector
from ..protocols.filter_bank import Filter, FilterBankState
from ..protocols.illumination import Illumination, IlluminationKind
from ..protocols.objective import ObjectiveLens, ObjectiveState
from ..protocols.stage import StageState
from .connection import SerialTransport, Uc2RestProtocol
from .devices import (
    FilterConfig,
    NewswitchConfig,
    ObjectiveConfig,
    RevolverConfig,
    StageConfig,
)
from .values import PhysVal

logger = logging.getLogger(__name__)

#: Slot of the pseudo filter standing for an empty filter-wheel position.
OPEN_FILTER_SLOT = 0

#: Intensity of a light source whose intensity cannot be set (``max_intensity: null``).
FIXED_INTENSITY = 100.0

_COLORMAPS = (Colormap.RED, Colormap.GREEN, Colormap.BLUE)


def _finite(value: float, fallback: float) -> float:
    """Return `value` if finite, else `fallback` (unset limits are +-inf)."""
    return value if math.isfinite(value) else fallback


# ---------------------------------------------------------------------------
# config -> managers
# ---------------------------------------------------------------------------


def illuminations(config: NewswitchConfig) -> list[Illumination] | None:
    """Build the illumination sources.

    The first source starts switched on at full intensity, the others off. A source
    without ``max_intensity`` has a fixed intensity (min = max).

    Args:
        config: The loaded configuration.

    Returns:
        One `Illumination` per light source, or None when there are none.
    """
    sources = config.lightsources
    if not sources:
        return None
    result = []
    for index, source in enumerate(sources):
        maximum = FIXED_INTENSITY if source.max_intensity is None else source.max_intensity
        minimum = maximum if source.max_intensity is None else 0.0
        result.append(
            Illumination(
                kind=IlluminationKind.LASER
                if source.coherence == "coherent"
                else IlluminationKind.LED,
                slot=index + 1,
                wavelength=source.wavelength,
                channel=source.channels,
                max_intensity=maximum,
                min_intensity=minimum,
                intensity=maximum if index == 0 else minimum,
                is_active=index == 0,
            )
        )
    return result


def detectors(config: NewswitchConfig) -> list[Detector] | None:
    """Build the detectors; exposure times are converted from ms to s.

    Values the file does not state keep the `Detector` defaults.

    Args:
        config: The loaded configuration.

    Returns:
        One `Detector` per detector, or None when there are none.
    """
    devices = config.detectors
    if not devices:
        return None
    defaults = Detector()
    result = []
    for index, device in enumerate(devices):
        width, height = device.pixelcount or (defaults.width, defaults.height)
        pitch = device.pixelpitch_xy
        exposure = device.exposure_time_ms
        gain = device.gain_db
        detector = Detector(
            slot=index + 1,
            name=device.name,
            width=width,
            height=height,
            is_active=True,
            current_colormap=_COLORMAPS[index % len(_COLORMAPS)],
            pixel_size_um=defaults.pixel_size_um if pitch is None else pitch[0],
        )
        if exposure is not None:
            if exposure.value is not None:
                detector.current_exposure_time = exposure.value / 1000.0
            detector.min_exposure_time = _finite(exposure.min / 1000.0, defaults.min_exposure_time)
            detector.max_exposure_time = _finite(exposure.max / 1000.0, defaults.max_exposure_time)
            if exposure.preset_vals:
                detector.preset_exposure_times = [v / 1000.0 for v in exposure.preset_vals]
        if gain is not None:
            if gain.value is not None:
                detector.current_gain = gain.value
            detector.min_gain = _finite(gain.min, defaults.min_gain)
            detector.max_gain = _finite(gain.max, defaults.max_gain)
        result.append(detector)
    return result


def _revolver_holding(config: NewswitchConfig, cls: type) -> RevolverConfig | None:
    """First revolver whose positions hold devices of `cls` (objective or filter)."""
    for revolver in config.revolvers:
        for ref in revolver.channels:
            if ref is not None and isinstance(config.devices[ref], cls):
                return revolver
    return None


def objective_lenses(config: NewswitchConfig) -> tuple[list[ObjectiveLens], int] | None:
    """Build the objective lenses and the slot selected at startup.

    Args:
        config: The loaded configuration.

    Returns:
        ``(lenses, default_slot)``, or None when there are no objectives. Without a
        turret, or when its selected position is empty, slot 1 is selected.
    """
    objectives = config.objectives
    if not objectives:
        return None
    lenses = [
        ObjectiveLens(
            slot=index + 1,
            name=objective.name,
            magnification=objective.magnification,
            numerical_aperture=objective.na,
            working_distance=objective.wd,
        )
        for index, objective in enumerate(objectives)
    ]
    turret = _revolver_holding(config, ObjectiveConfig)
    selected = None if turret is None else turret.selected_device_id
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
    devices = config.filters
    if not devices:
        return None
    result = [
        Filter(
            slot=index + 1,
            name=device.name,
            center_wavelength=device.wavelength,
            bandwidth=0.0 if device.bandwidth is None else device.bandwidth,
            transmission=device.transmission,
        )
        for index, device in enumerate(devices)
    ]
    wheel = _revolver_holding(config, FilterConfig)
    if wheel is None:
        return result, 1
    if None in wheel.channels:
        result.insert(0, Filter(slot=OPEN_FILTER_SLOT, name="Open"))
    selected = wheel.selected_device_id
    return result, OPEN_FILTER_SLOT if selected is None else config.slot_of(selected)


def apply_stage_limits(config: NewswitchConfig, stage_state: StageState) -> None:
    """Copy the travel (``pos.min``/``pos.max``) of the first stage into `stage_state`.

    Only finite limits of the axes x, y, z and a are applied; other axes are logged and
    skipped until an axis manager handles arbitrary axes.

    Args:
        config: The loaded configuration.
        stage_state: The shared stage state; modified in place.
    """
    stages = config.stages
    if not stages:
        return
    if len(stages) > 1:
        logger.warning("%d stages configured, only %r is used", len(stages), stages[0].device_id)
    for axis in stages[0].axes:
        if axis.pos is None:
            continue
        low, high = axis.pos.min, axis.pos.max
        match axis.label:
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
                logger.warning("stage axis %r is not supported yet, skipped", axis.label)


@dataclass
class SerialSettings:
    """Port and baud rate for the UC2 serial manager."""

    port: str
    baudrate: int


def serial_settings(config: NewswitchConfig) -> SerialSettings | None:
    """Serial settings of the first controller speaking uc2-rest over a serial port.

    A ``port_pattern`` is resolved to the first matching device path.

    Args:
        config: The loaded configuration.

    Returns:
        The settings, or None when no such controller exists or no port matches.
    """
    for controller in config.controllers:
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
            logger.warning("controller %r: no serial port found", controller.device_id)
            continue
        return SerialSettings(port=port, baudrate=transport.baudrate)
    return None


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


def _select(config: NewswitchConfig, revolver: RevolverConfig | None, slot: int) -> None:
    """Point `revolver.selected_channel` at the device that has `slot`.

    Args:
        config: The configuration.
        revolver: The revolver, or None.
        slot: Slot of the selected objective/filter; `OPEN_FILTER_SLOT` = empty position.
    """
    if revolver is None:
        return
    for position, ref in enumerate(revolver.channels):
        matches = (
            ref is None
            if slot == OPEN_FILTER_SLOT
            else (ref is not None and config.slot_of(ref) == slot)
        )
        if matches:
            revolver.selected_channel = position
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
    for index, device in enumerate(config.detectors):
        slot = index + 1
        runtime = next((d for d in camera_state.detectors if d.slot == slot), None)
        if runtime is None:
            continue
        where = f"devices.{device.device_id}"
        device.exposure_time_ms = _with_value(
            device.exposure_time_ms,
            runtime.current_exposure_time * 1000.0,
            "ms",
            f"{where}.exposure_time_ms",
        )
        device.gain_db = _with_value(device.gain_db, runtime.current_gain, "dB", f"{where}.gain_db")

    _select(config, _revolver_holding(config, ObjectiveConfig), objective_state.slot)
    _select(config, _revolver_holding(config, FilterConfig), filter_bank_state.current_slot)

    stages: list[StageConfig] = config.stages
    if stages:
        for axis in stages[0].axes:
            match axis.label:
                case "x":
                    position: float | None = stage_state.x
                case "y":
                    position = stage_state.y
                case "z":
                    position = stage_state.z
                case "a":
                    position = stage_state.a
                case _:
                    position = None
            if position is not None:
                axis.pos = _with_value(
                    axis.pos,
                    position,
                    "um",
                    f"devices.{stages[0].device_id}.axes.{axis.label}.pos",
                )
