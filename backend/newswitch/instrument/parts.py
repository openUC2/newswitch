"""An instrument as what the server runs on: the models its managers and states take."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from newswitch.instrument.compiler import compile_instrument
from newswitch.instrument.errors import SpecError
from newswitch.instrument.hardware import CAMERA_PROTOCOLS, Actuator
from newswitch.instrument.spec import Instrument, Move, Sensor, Swap, Variable
from newswitch.instrument.tracing import scan_um_per_degree
from newswitch.models.devices import (
    Detector,
    DetectorAxis,
    Filter,
    Illumination,
    IlluminationKind,
    ObjectiveLens,
)
from newswitch.states.detector import CameraState
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.illumination import IlluminationState
from newswitch.states.objective import ObjectiveState
from newswitch.states.stage import StageState


def stage_moves(instrument: Instrument) -> dict[str, Move]:
    """What moves the sample, by the stage's axis names."""
    stage = instrument.parts.stage
    return {} if stage is None else instrument.cubes[stage].moves


def objective_swap(instrument: Instrument) -> Swap | None:
    """The swap that changes objectives."""
    objective = instrument.parts.objective
    return None if objective is None else instrument.variables[objective.swap]


def filter_swap(instrument: Instrument) -> Swap | None:
    """The swap that changes filters."""
    filters = instrument.parts.filters
    return None if filters is None else instrument.variables[filters.swap]


def sensor_size(instrument: Instrument) -> tuple[int, int]:
    """The (width, height) of the images of the detectors, read off their axes.

    Raises:
        ValueError: They differ: a virtual detector has one size for all its sensors.
    """
    sizes = set()
    for name in instrument.detectors():
        *_, axis_y, axis_x = instrument.detector_axes(name)
        sizes.add((axis_x.size, axis_y.size))
    if len(sizes) != 1:
        raise ValueError(f"{instrument.name}: its sensors differ in size: {sorted(sizes)}")
    return next(iter(sizes))


def illuminations(instrument: Instrument) -> list[Illumination] | None:
    """One `Illumination` per source, its intensity the initial share of its maximum power."""
    found = []
    for slot, part in sorted(instrument.parts.sources.items()):
        cube = instrument.cubes[part.cube]
        element = cube.element
        assert element is not None
        power = cube.variables["power"].initial
        found.append(
            Illumination(
                kind=IlluminationKind.LASER if element.coherent else IlluminationKind.LED,
                slot=slot,
                wavelength=element.wavelength,
                key=part.cube,
                channel=slot,
                max_intensity=part.full_intensity,
                min_intensity=0.0,
                # A source that starts off comes on at full, not at the 0 it is off at.
                intensity=part.full_intensity * power / element.max_power
                if power > 0.0
                else part.full_intensity,
                is_active=power > 0.0,
            )
        )
    return found or None


def objective_lenses(instrument: Instrument) -> tuple[list[ObjectiveLens], int] | None:
    """The objectives, and the slot in use."""
    variable = objective_swap(instrument)
    if variable is None:
        return None
    assert instrument.parts.objective is not None
    reference_tube = instrument.parts.objective.reference_tube
    return (
        [
            ObjectiveLens(
                slot=slot,
                name=element.name or f"f{element.f:g}",
                magnification=reference_tube / element.f,
                numerical_aperture=element.na,
                working_distance=element.working_distance or 0.0,
            )
            for slot, element in variable.slots.items()
        ],
        variable.initial,
    )


def filters(instrument: Instrument) -> tuple[list[Filter], int] | None:
    """The filters, and the slot in use."""
    variable = filter_swap(instrument)
    if variable is None:
        return None
    return (
        [
            Filter(
                slot=slot,
                name=element.name or f"Slot {slot}",
                center_wavelength=element.center or 0.0,
                bandwidth=element.width or 0.0,
                transmission=element.transmission,
            )
            for slot, element in variable.slots.items()
        ],
        variable.initial,
    )


def detectors(instrument: Instrument) -> list[Detector] | None:
    """One `Detector` per sensor, all active. Its sizes come from the sensor's axes."""
    found = []
    for slot, part in sorted(instrument.parts.detectors.items()):
        name = part.cube
        cube = instrument.cubes[name]
        element = cube.element
        assert element is not None
        delivered = instrument.detector_axes(name)
        *_, axis_y, axis_x = delivered
        scanner = instrument.scanner_of(name)
        found.append(
            Detector(
                slot=slot,
                name=name,
                key=name,
                width=axis_x.size,
                height=axis_y.size,
                sensor_width=axis_x.size,
                sensor_height=axis_y.size,
                is_active=True,
                pixel_size_um=axis_x.step
                if scanner is None
                else abs(
                    axis_x.step
                    * scan_um_per_degree(instrument, scanner, instrument.initial_state())
                ),
                colors=list(element.colors) if isinstance(element, Sensor) else [],
                axes=[
                    DetectorAxis(axis.name, axis.size, axis.step, axis.delivered_by)
                    for axis in delivered
                ],
                current_exposure_time=cube.variables["exposure"].initial / 1000.0,
                current_gain=cube.variables["gain"].initial,
                current_binning=cube.variables["binning"].initial,
                current_frame_rate=part.frame_rate,
            )
        )
    return found or None


def cameras(instrument: Instrument) -> tuple[list[Detector], dict[int, dict[str, Any]]] | None:
    """The detectors to open as cameras, with their vendor options by slot.

    The vendor is passed on unchanged: newswitch knows no vendor names, the camera library decides
    which it supports. None when the description wires no camera.
    """
    found = []
    vendor_options: dict[int, dict[str, Any]] = {}
    for detector in detectors(instrument) or []:
        camera = instrument.hardware.cameras.get(detector.name)
        if camera is None:
            continue
        detector.manufacturer = camera.vendor
        detector.connection_type = CAMERA_PROTOCOLS[camera.protocol]
        detector.serial_number = camera.serial_number
        detector.device_index = camera.index
        detector.buffer_size = camera.buffer_size
        detector.store_image_data = camera.store_image_data
        found.append(detector)
        vendor_options[detector.slot] = dict(camera.vendor_options)
    return (found, vendor_options) if found else None


def _wired(instrument: Instrument, variable: Variable) -> Actuator | None:
    return instrument.hardware.actuators.get(variable.actuator or "")


def stage_axes(instrument: Instrument) -> list[str]:
    """The board's axes the sample moves along."""
    return [
        actuator.axis
        for variable in stage_moves(instrument).values()
        if (actuator := _wired(instrument, variable)) is not None and actuator.axis is not None
    ]


def source_channel(instrument: Instrument, source: str) -> Actuator | None:
    """What a source's power is wired to."""
    return _wired(instrument, instrument.cubes[source].variables["power"])


def objective_actuator(instrument: Instrument) -> Actuator | None:
    """What changes the objectives."""
    swap = objective_swap(instrument)
    return None if swap is None else _wired(instrument, swap)


def filter_actuator(instrument: Instrument) -> Actuator | None:
    """What changes the filters."""
    swap = filter_swap(instrument)
    return None if swap is None else _wired(instrument, swap)


def check_wired(instrument: Instrument) -> None:
    """Check real hardware can run what the server has a control for.

    A move or swap that has no control (a tube lens's focus) stays where it is, and needs no wire.

    Raises:
        SpecError: A control's actuator or a sensor's camera is not wired; every one is listed.
    """
    controlled: list[Variable] = list(stage_moves(instrument).values())
    controlled += [instrument.cubes[name].variables["power"] for name in instrument.sources()]
    for swap in (objective_swap(instrument), filter_swap(instrument)):
        if swap is not None:
            controlled.append(swap)
    problems = [
        f"{variable.name} has no wired actuator (hardware.actuators)"
        for variable in controlled
        if _wired(instrument, variable) is None
    ]
    problems += [
        f"the sensor {name} has no camera (hardware.cameras)"
        for name in instrument.detectors()
        if name not in instrument.hardware.cameras
    ]
    for name in instrument.sources():
        actuator = source_channel(instrument, name)
        if actuator is not None and actuator.channel is None:
            problems.append(f"{name}.power: its actuator {actuator.name} has no channel")
    pwm_max = {
        actuator.pwm_max
        for name in instrument.sources()
        if (actuator := source_channel(instrument, name)) is not None
        and actuator.pwm_max is not None
    }
    if len(pwm_max) > 1:
        problems.append(f"its sources share one pwm_max on a board, not {sorted(pwm_max)}")
    wheel = filter_swap(instrument)
    if wheel is not None and (actuator := _wired(instrument, wheel)) is not None:
        slots = sorted(wheel.slots)
        if actuator.axis is None or sorted(actuator.positions or {}) != slots:
            problems.append(
                f"{wheel.name}: its actuator {actuator.name} needs an axis and a position "
                f"for each of the slots {slots}"
            )
        elif slots != list(range(1, len(slots) + 1)):
            problems.append(f"{wheel.name}: a wired wheel's slots count from 1, not {slots}")
    board = instrument.hardware.board
    turret = objective_actuator(instrument)
    if (
        board is not None
        and turret is not None
        and turret.positions is not None
        and board.transport != "canopen"
    ):
        problems.append(
            f"{turret.name}: only a canopen board takes positions, a {board.transport} board's "
            "firmware keeps its own"
        )
    # A rig really wired this way while the software steps too would move twice per plane.
    problems += [
        f"{drive.source} -> {drive.target}: no driver can arm this wire yet"
        for drive in instrument.drives
    ]
    if problems:
        raise SpecError(f"{instrument.name} cannot run on real hardware: " + "; ".join(problems))


def apply_stage_limits(instrument: Instrument, stage_state: StageState) -> None:
    """Copy each move's travel into `stage_state`."""
    for short, variable in stage_moves(instrument).items():
        if variable.min is not None:
            setattr(stage_state, f"min_{short}", variable.min)
        if variable.max is not None:
            setattr(stage_state, f"max_{short}", variable.max)


def stage_speed(instrument: Instrument) -> float | None:
    """How fast the simulated stage travels, in um/s: its slowest move; None if none says."""
    speeds = [variable.speed for variable in stage_moves(instrument).values() if variable.speed]
    return min(speeds) if speeds else None


def runtime_state(
    instrument: Instrument,
    camera_state: CameraState,
    stage_state: StageState,
    objective_state: ObjectiveState,
    illumination_state: IlluminationState,
    filter_bank_state: FilterBankState,
) -> dict[str, Any]:
    """What the running microscope is set to, in the description's names.

    The one place where the two meet. What has no control in the server (a tube lens's focus) stays
    at its initial value.
    """
    state = instrument.initial_state()
    for short, variable in stage_moves(instrument).items():
        state[variable.name] = getattr(stage_state, short)

    swap = objective_swap(instrument)
    if swap is not None:
        state[swap.name] = objective_state.slot
    swap = filter_swap(instrument)
    if swap is not None:
        state[swap.name] = filter_bank_state.current_slot

    for slot, part in sorted(instrument.parts.sources.items()):
        name = part.cube
        element = instrument.cubes[name].element
        assert element is not None
        source = illumination_state.get_illumination_by_slot(slot)
        share = source.intensity / source.max_intensity if source.is_active else 0.0
        state[f"{name}.power"] = share * element.max_power

    for detector in camera_state.detectors:
        name = instrument.detectors()[detector.slot - 1]
        state[f"{name}.exposure"] = detector.current_exposure_time * 1000.0
        state[f"{name}.gain"] = detector.current_gain
        state[f"{name}.binning"] = detector.current_binning
    return state


def nominal_pixel_scale(
    instrument: Instrument,
    camera_state: CameraState,
    stage_state: StageState,
    objective_state: ObjectiveState,
    illumination_state: IlluminationState,
    filter_bank_state: FilterBankState,
) -> Callable[[int], tuple[float, float, float, float]]:
    """What the design predicts a detector's pixels are, for images no calibration covers.

    The server's objective has one magnification, but what is magnified depends on each detector's
    own tube lens, which only the instrument knows. The result takes a detector's slot, and gives
    its micrometres per pixel in x and y, and its field of view. Those are in the terms of a
    calibration, how far the stage moves to shift the image by a pixel, with the opposite sign of
    `predict.Answer.pixel_to_stage`, which sample point a pixel sees: an image must not flip when
    it gets calibrated.
    """
    table = compile_instrument(instrument)

    def scale(detector_slot: int) -> tuple[float, float, float, float]:
        state = runtime_state(
            instrument,
            camera_state,
            stage_state,
            objective_state,
            illumination_state,
            filter_bank_state,
        )
        answer = table.answer(instrument.detectors()[detector_slot - 1], state)
        return (
            -answer.pixel_to_stage[0][0],
            -answer.pixel_to_stage[1][1],
            answer.field_of_view_um[0],
            answer.field_of_view_um[1],
        )

    return scale
