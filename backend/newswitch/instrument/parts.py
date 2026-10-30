"""An instrument as what the server runs on: the models its managers and states take.

The counterpart of `newswitch.config_io.adapters`, with the same names, for a microscope described
by its optical elements.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from newswitch.config_io import BlokEntry, UiConfig
from newswitch.instrument.spec import Cube, Instrument, Variable
from newswitch.models.devices import Detector, Filter, Illumination, IlluminationKind, ObjectiveLens
from newswitch.states.detector import CameraState
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.illumination import IlluminationState
from newswitch.states.objective import ObjectiveState
from newswitch.states.stage import StageState

#: Every source's intensity runs from 0 to this, as in `config_io.adapters.FULL_INTENSITY`.
FULL_INTENSITY = 100.0
#: The tube lens an objective's magnification is conventionally stated against, in millimetres.
#: What it really magnifies depends on the detector's own tube lens: see `predict.Answer`.
REFERENCE_TUBE_MM = 200.0
#: How often a detector streams unless told otherwise; rendering as fast as possible uses a core.
DEFAULT_FRAME_RATE = 30.0


def _swap_of(instrument: Instrument, kind: str) -> tuple[Cube, Variable] | None:
    """The cube that swaps elements of `kind`, and its variable."""
    for cube in instrument.cubes.values():
        for variable in cube.variables.values():
            if variable.verb == "swaps" and variable.slots:
                if next(iter(variable.slots.values())).kind == kind:
                    return cube, variable
    return None


def has_stage(instrument: Instrument) -> bool:
    """Whether something moves the sample."""
    return any(
        variable.verb == "moves"
        for variable in instrument.cubes[instrument.sample_cube()].variables.values()
    )


def has_objective(instrument: Instrument) -> bool:
    """Whether there are objectives to choose from."""
    return _swap_of(instrument, "lens") is not None


def has_filters(instrument: Instrument) -> bool:
    """Whether there are filters to choose from."""
    return _swap_of(instrument, "filter") is not None


def sensor_size(instrument: Instrument) -> tuple[int, int]:
    """The (width, height) of the sensors, read off their axes.

    Raises:
        ValueError: They differ: a virtual detector has one size for all its sensors.
    """
    sizes = set()
    for name in instrument.detectors():
        element = instrument.cubes[name].element
        assert element is not None
        axes = element.properties["axes"]
        sizes.add((axes["x"]["size"], axes["y"]["size"]))
    if len(sizes) != 1:
        raise ValueError(f"{instrument.name}: its sensors differ in size: {sorted(sizes)}")
    return next(iter(sizes))


def illuminations(instrument: Instrument) -> list[Illumination] | None:
    """One `Illumination` per source, its intensity the initial share of its maximum power."""
    found = []
    for slot, name in enumerate(instrument.sources(), start=1):
        cube = instrument.cubes[name]
        element = cube.element
        assert element is not None
        power = cube.variables["power"].initial
        found.append(
            Illumination(
                kind=IlluminationKind.LASER
                if element.properties.get("coherent")
                else IlluminationKind.LED,
                slot=slot,
                wavelength=element.properties["wavelength"],
                channel=slot,
                max_intensity=FULL_INTENSITY,
                min_intensity=0.0,
                # A source that starts off comes on at full, not at the 0 it is off at.
                intensity=FULL_INTENSITY * power / element.properties["max_power"]
                if power > 0.0
                else FULL_INTENSITY,
                is_active=power > 0.0,
            )
        )
    return found or None


def objective_lenses(instrument: Instrument) -> tuple[list[ObjectiveLens], int] | None:
    """The objectives, and the slot in use."""
    found = _swap_of(instrument, "lens")
    if found is None:
        return None
    _, variable = found
    assert variable.slots is not None
    return (
        [
            ObjectiveLens(
                slot=slot,
                name=element.properties.get("name", f"f{element.properties['f']:g}"),
                magnification=REFERENCE_TUBE_MM / element.properties["f"],
                numerical_aperture=element.properties["na"],
                working_distance=element.properties.get("working_distance", 0.0),
            )
            for slot, element in variable.slots.items()
        ],
        variable.initial,
    )


def filters(instrument: Instrument) -> tuple[list[Filter], int] | None:
    """The filters, and the slot in use."""
    found = _swap_of(instrument, "filter")
    if found is None:
        return None
    _, variable = found
    assert variable.slots is not None
    return (
        [
            Filter(
                slot=slot,
                name=element.properties.get("name", f"Slot {slot}"),
                center_wavelength=element.properties.get("center", 0.0),
                bandwidth=element.properties.get("width", 0.0),
                transmission=element.properties.get("transmission", 1.0),
            )
            for slot, element in variable.slots.items()
        ],
        variable.initial,
    )


def detectors(instrument: Instrument) -> list[Detector] | None:
    """One `Detector` per sensor, all active. Its sizes come from the sensor's axes."""
    found = []
    for slot, name in enumerate(instrument.detectors(), start=1):
        cube = instrument.cubes[name]
        element = cube.element
        assert element is not None
        axes = element.properties["axes"]
        found.append(
            Detector(
                slot=slot,
                name=name,
                key=name,
                width=axes["x"]["size"],
                height=axes["y"]["size"],
                sensor_width=axes["x"]["size"],
                sensor_height=axes["y"]["size"],
                is_active=True,
                pixel_size_um=axes["x"]["pitch"],
                current_exposure_time=cube.variables["exposure"].initial / 1000.0,
                current_gain=cube.variables["gain"].initial,
                current_binning=cube.variables["binning"].initial,
                current_frame_rate=DEFAULT_FRAME_RATE,
            )
        )
    return found or None


def apply_stage_limits(instrument: Instrument, stage_state: StageState) -> None:
    """Copy each move's travel into `stage_state`."""
    stage = instrument.cubes[instrument.sample_cube()]
    for short, variable in stage.variables.items():
        if variable.verb != "moves":
            continue
        if variable.minimum is not None:
            setattr(stage_state, f"min_{short}", variable.minimum)
        if variable.maximum is not None:
            setattr(stage_state, f"max_{short}", variable.maximum)


def stage_speed(instrument: Instrument) -> float | None:
    """How fast the simulated stage travels, in um/s: its slowest move; None if none says."""
    stage = instrument.cubes[instrument.sample_cube()]
    speeds = [
        variable.speed
        for variable in stage.variables.values()
        if variable.verb == "moves" and variable.speed
    ]
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
    stage = instrument.sample_cube()
    for short in ("x", "y", "z"):
        if f"{stage}.{short}" in state:
            state[f"{stage}.{short}"] = getattr(stage_state, short)

    found = _swap_of(instrument, "lens")
    if found is not None:
        state[found[1].name] = objective_state.slot
    found = _swap_of(instrument, "filter")
    if found is not None:
        state[found[1].name] = filter_bank_state.current_slot

    for slot, name in enumerate(instrument.sources(), start=1):
        element = instrument.cubes[name].element
        assert element is not None
        source = illumination_state.get_illumination_by_slot(slot)
        share = source.intensity / source.max_intensity if source.is_active else 0.0
        state[f"{name}.power"] = share * element.properties["max_power"]

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
    from newswitch.instrument.predict import Compiled

    table = Compiled.load(instrument)

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


def ui_config(instrument: Instrument, catalog: str) -> UiConfig:
    """The built-in views the description names, as bloks; the first is the default.

    Raises:
        ValueError: It names a view there is none of.
    """
    from newswitch.bloks import fluorescence, minimal, stage_view

    makers: dict[str, tuple[str, Callable[[bool], BlokEntry]]] = {
        "fluorescence": (
            fluorescence.NAME,
            lambda default: fluorescence.blok(
                has_filters=has_filters(instrument), has_objectives=has_objective(instrument)
            ),
        ),
        "stage": (stage_view.NAME, stage_view.blok),
        "minimal": (minimal.NAME, minimal.blok),
    }
    bloks = {}
    for index, view in enumerate(instrument.views):
        if view not in makers:
            raise ValueError(f"{instrument.name} names no view {view!r}; it has {sorted(makers)}")
        name, make = makers[view]
        bloks[name] = make(index == 0)
    return UiConfig(catalog=catalog, bloks=bloks)
