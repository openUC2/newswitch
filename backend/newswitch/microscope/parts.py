"""The microscope newswitch runs: everything its description says it has, built once.

Data and functions, no object with behaviour. `build_microscope` builds the states and managers of an
instrument (a `Microscope` record). What a variable is reached through is what its actuator's driver
is; what has none is simulated or refused, as ``settings.simulate`` says.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

import newswitch.drivers.uc2.actuators  # noqa: F401 - makes the uc2.* drivers available
from newswitch import models, protocols, states
from newswitch.calibration.manager import CalibrationManager
from newswitch.calibration.states import CalibrationState
from newswitch.calibration.store import CalibrationStore
from newswitch.drivers.base import Driver, Report, build_driver
from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.drivers.uc2.rest_bus import UC2RestBus, UC2RestBusConfig
from newswitch.instrument import parts as instrument_parts
from newswitch.instrument.errors import SpecError
from newswitch.instrument.hardware import Hardware
from newswitch.instrument.spec import Drive, Instrument
from newswitch.models.devices import Detector
from newswitch.protocols import DetectorManager
from newswitch.protocols.io import IOManager
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.services.acquisition import AcquisitionManager
from newswitch.services.cache.local_cache import LocalCacheConfig, LocalCacheManager
from newswitch.services.expanse import ExpanseManager
from newswitch.services.hooks.manager import PythonHookManager
from newswitch.services.hooks.software_autofocus import software_autofocus_hook
from newswitch.services.io import LocalFileConfig, LocalFileIOManager
from newswitch.services.metadata import MetadataManager
from newswitch.services.optics import OpticsManager
from newswitch.services.space import SpaceManager
from newswitch.services.values import Values
from newswitch.settings import SIMULATED, Settings, Simulate
from newswitch.simulation import drivers as simulated_drivers
from newswitch.simulation.detector import SimulatedDetectorManager
from newswitch.simulation.uc2_bus import VirtualUC2Bus, VirtualUC2BusConfig
from newswitch.states.autofocus import AutofocusState
from newswitch.states.detector import DetectorState
from newswitch.states.io import IOState
from newswitch.states.optics import OpticsState
from newswitch.states.space import SpaceState
from newswitch.states.uc2 import UC2State
from newswitch.states.values import MoveState, SourceState, SwapState, TuneState

logger = logging.getLogger(__name__)

#: What a variable of this name on a detector is, to its detector's manager: what to set, and where
#: the detector says what it applied.
_DETECTOR_TUNES: dict[str, tuple[str, Callable[[Detector], Any]]] = {
    "exposure": ("exposure_ms", lambda detector: detector.current_exposure_ms),
    "gain": ("gain", lambda detector: detector.current_gain),
    "binning": ("binning", lambda detector: detector.binning()),
    "frame_rate": ("frame_rate", lambda detector: detector.current_frame_rate),
}


class DetectorTune:
    """A variable a detector's own manager applies, and says what it became."""

    def __init__(self, manager: DetectorManager, detector: str, tune: str) -> None:
        """The variable `tune` of `detector`, through `manager`."""
        self.manager = manager
        self.detector = detector
        self.argument, self.applied = _DETECTOR_TUNES[tune]

    def start(self, initial: Any) -> Any:  # noqa: ANN401 - whatever the variable holds
        """What the detector made of what it was described to start at."""
        detector = self.manager.get_detector_state(self.detector)
        applied = None if detector is None else self.applied(detector)
        return initial if applied is None else applied

    def set(self, value: Any, report: Any, task: Any = None) -> None:  # noqa: ANN401
        """Apply it, and report what the detector made of it."""
        detector = self.manager.update_detector(self.detector, **{self.argument: value})
        report(self.applied(detector))

    @classmethod
    def set_together(
        cls, targets: Iterable[tuple[Driver, Any, Report]], task: Any = None  # noqa: ANN401
    ) -> None:
        """One after the other: a detector applies each at once."""
        for driver, value, report in targets:
            driver.set(value, report, task)


def _driver_config(cls: type, options: Mapping[str, Any], where: str) -> Any:  # noqa: ANN401
    """The driver's config from what the description states.

    Raises:
        SpecError: An option is not one the driver has.
    """
    try:
        return cls(**options)
    except TypeError as exc:
        raise SpecError(f"hardware: {where}: {exc}") from exc


def bus_options(hardware: Hardware) -> dict[str, Any]:
    """What the bus of the board is built with: its options, and what its actuators say of it."""
    board = hardware.board
    assert board is not None
    options = dict(board.options)
    for actuator in hardware.actuators.values():
        if actuator.driver == "uc2.stepper" and {"axis", "steps_per_um"} <= set(actuator.options):
            axis = str(actuator.options["axis"]).lower()
            options[f"steps_per_um_{axis}"] = actuator.options["steps_per_um"]
        if actuator.driver == "uc2.turret" and "positions" in actuator.options:
            positions = actuator.options["positions"]
            if board.transport == "canopen":
                options["objective_slot_positions_steps"] = [
                    positions[s] for s in sorted(positions)
                ]
    return options


def build_uc2_bus(settings: Settings, instrument: Instrument, uc2_state: UC2State) -> UC2BusManager:
    """The bus of the board: simulated when everything is, virtual like the board when the rig runs
    as its twin, else REST or CANopen, as it says. Each is told the firmware the description names,
    which is no option of its link."""
    board = instrument.hardware.board
    assert board is not None
    if settings.simulate in ("everything", "debug"):
        return VirtualUC2Bus(state=uc2_state, firmware=board.firmware)
    if settings.simulate == "virtual":
        config = VirtualUC2BusConfig.from_board(bus_options(instrument.hardware), board.transport)
        return VirtualUC2Bus(state=uc2_state, config=config, firmware=board.firmware)
    logger.info("UC2 transport: %s", board.transport)
    options = bus_options(instrument.hardware)
    where = f"boards.{board.name}"
    if board.transport == "rest":
        options["serialport"] = board.resolved_port()
        config = _driver_config(UC2RestBusConfig, options, where)
        return UC2RestBus(state=uc2_state, config=config, firmware=board.firmware)
    options["port"] = board.resolved_port()
    config = _driver_config(UC2CanBusConfig, options, where)
    return UC2CanBus(state=uc2_state, config=config, firmware=board.firmware)


def build_detector_manager(
    settings: Settings,
    instrument: Instrument,
    detector_state: DetectorState,
    values: Any,  # noqa: ANN401 - what is built after it, and asked only once it runs
    step: Any,  # noqa: ANN401 - likewise
) -> DetectorManager:
    """Real cameras through uc2_cam_py, as the description wires them, else rendering from the optics.

    With ``simulate: everything`` or ``virtual`` a description's cameras are not opened. Without the extra "camera"
    (uc2_cam_py not importable) the optics stand in with a warning on ``unwired``, and it is an error
    on ``nothing``. A camera that cannot be opened is an error: startup fails.
    ``camera_debug_window`` opens uc2_cam_py's debug window per camera.
    """
    found = None if settings.simulate in SIMULATED else instrument_parts.cameras(instrument)
    if found:
        cameras, vendor_options = found
        try:
            from newswitch.drivers.uc2.uc2_detector import UC2DetectorManager
        except ImportError as exc:
            if settings.simulate == "nothing":
                # Someone looking at rendered images would take them for what the camera sees.
                raise SpecError(
                    f"{len(cameras)} camera(s) are wired and nothing is to be simulated, but "
                    f"uc2_cam_py cannot be imported ({exc}). Install the extra: uv sync --extra "
                    "camera"
                ) from exc
            logger.warning(
                "%d camera(s) configured, but uc2_cam_py cannot be imported (%s); "
                "rendering from the optics. Install the extra: uv sync --extra camera",
                len(cameras),
                exc,
            )
        else:
            return UC2DetectorManager(
                detector_state=detector_state,
                cameras=cameras,
                vendor_options=vendor_options,
                recording_dir=settings.camera_recording_dir,
                debug_window=settings.camera_debug_window,
            )
    return SimulatedDetectorManager(
        instrument=instrument,
        detector_state=detector_state,
        detectors=instrument_parts.detectors(instrument),
        values=values,
        step=step,
    )


def build_drivers(
    settings: Settings,
    instrument: Instrument,
    bus: Optional[UC2BusManager],
    detector: Optional[DetectorManager],
) -> dict[str, Driver]:
    """Which driver reaches each variable; what is in none of them is simulated."""
    drivers: dict[str, Driver] = {}
    for name, variable in instrument.variables.items():
        short = name.split(".", 1)[1]
        if detector is not None and variable.cube in instrument.detectors():
            if short in _DETECTOR_TUNES:
                drivers[name] = DetectorTune(detector, variable.cube, short)
            continue
        actuator = instrument.hardware.actuators.get(variable.actuator or "")
        if settings.simulate in ("everything", "debug") or actuator is None:
            continue
        drivers[name] = build_driver(actuator.driver, variable, actuator.options, {"bus": bus})
    return drivers


@dataclass
class Microscope:
    """Everything one microscope built; what it lacks is None."""

    move_state: MoveState
    swap_state: SwapState
    tune_state: TuneState
    source_state: SourceState
    detector_state: DetectorState
    uc2_state: UC2State
    io_state: IOState
    io: IOManager
    hook_state: states.HookState
    hooks: protocols.HookManager
    expanse_state: states.ExpanseState
    expanse: protocols.ExpanseManager
    calibration_state: CalibrationState
    calibration: protocols.CalibrationManager
    optics_state: OpticsState
    optics: protocols.OpticsManager
    metadata: protocols.MetadataManager
    space_state: SpaceState
    space: SpaceManager
    cache: protocols.CacheManager
    autofocus_state: AutofocusState
    uc2_bus: Optional[UC2BusManager]
    values: Optional[Values]
    detector: Optional[DetectorManager]
    acquisition: Optional[protocols.AcquisitionManager]


def build_microscope(settings: Settings, instrument: Optional[Instrument]) -> Microscope: # TODO: shis should be actually inside the startup hook and not called by a method of the run, lets class based patterns
    """Build everything `instrument` has.

    Args:
        settings: The app context: what to simulate, folders.
        instrument: What to run; None: no devices, the core only.

    Raises:
        SpecError: The description does not say how to reach something it has to.
    """
    if instrument is not None:
        check_wired(instrument, settings.simulate)
    logger.info(
        "Initializing a microscope with %s simulated: %s",
        settings.simulate,
        instrument.name if instrument is not None else "no devices",
    )

    move_state, swap_state, tune_state = MoveState(), SwapState(), TuneState()
    source_state = SourceState()
    detector_state = DetectorState()
    uc2_state = UC2State()

    uc2_bus = (
        build_uc2_bus(settings, instrument, uc2_state)
        if instrument is not None and instrument.hardware.boards
        else None
    )
    values: Optional[Values] = None
    detector = (
        build_detector_manager(
            settings,
            instrument,
            detector_state,
            lambda: values.snapshot(),
            lambda name, value: values.stepped(name, value),
        )
        if instrument is not None and (instrument.detectors() or instrument.probes())
        else None
    )
    if instrument is not None:
        values = Values(
            instrument,
            move_state,
            swap_state,
            tune_state,
            source_state,
            build_drivers(settings, instrument, uc2_bus, detector),
            unwired=simulated_drivers.unwired,
        )

    io_state = IOState()
    io = LocalFileIOManager(
        state=io_state, config=LocalFileConfig(base_path=str(settings.image_dir))
    )
    calibration_state = CalibrationState()
    calibration = CalibrationManager(
        calibration_state=calibration_state,
        instrument=instrument,
        store=None
        if instrument is None
        else CalibrationStore(settings.calibration_dir, instrument.name),
    )

    optics_state = OpticsState()
    optics = OpticsManager(
        state=optics_state,
        detector_state=detector_state,
        calibration=calibration,
        instrument=instrument,
        values=None if values is None else values.snapshot,
        roles=None if values is None else values.roles,
    )
    space_state = SpaceState()
    space = SpaceManager(
        state=space_state,
        values=values,
        optics=optics,
        detector_state=detector_state,
        calibration=calibration,
    )

    if isinstance(detector, SimulatedDetectorManager):
        # What it renders is on what each sample is mounted on now.
        detector.follow_mounts(
            lambda sample: (
                space_state.samples[sample].holder if sample in space_state.samples else None
            )
        )

    def refresh() -> None:
        """What the optics find, then where that puts every pixel."""
        optics.refresh()
        space.refresh()

    calibration.on_change = refresh
    if values is not None:
        values.on_change = refresh
    if detector is not None:
        detector.on_change = refresh
    refresh()

    hook_state = states.HookState()
    hooks = PythonHookManager(
        protocols.HookContext(
            values=values,
            detector_manager=detector,
            io_manager=io,
            optics_manager=optics,
        )
    )
    if values is not None and detector is not None and instrument_moves(instrument):
        # The software autofocus sweeps what focuses and reads the detector.
        hooks.register_hook(models.SoftwareAutofocusHook, software_autofocus_hook)

    expanse_state = states.ExpanseState()
    expanse = ExpanseManager(expanse=expanse_state)
    metadata = MetadataManager(space=space, optics=optics, detector_state=detector_state)
    cache = LocalCacheManager(LocalCacheConfig(base_path=str(settings.cache_dir)))

    acquisition = (
        AcquisitionManager(
            expanse_manager=expanse,
            detector_manager=detector,
            metadata_manager=metadata,
            optics_manager=optics,
            cache_manager=cache,
            space=space,
        )
        if detector is not None
        else None
    )

    return Microscope(
        move_state=move_state,
        swap_state=swap_state,
        tune_state=tune_state,
        source_state=source_state,
        detector_state=detector_state,
        uc2_state=uc2_state,
        io_state=io_state,
        io=io,
        hook_state=hook_state,
        hooks=hooks,
        expanse_state=expanse_state,
        expanse=expanse,
        calibration_state=calibration_state,
        calibration=calibration,
        optics_state=optics_state,
        optics=optics,
        metadata=metadata,
        space_state=space_state,
        space=space,
        cache=cache,
        autofocus_state=AutofocusState(),
        uc2_bus=uc2_bus,
        values=values,
        detector=detector,
        acquisition=acquisition,
    )


def check_wired(instrument: Instrument, simulate: Simulate) -> None:
    """Check that what is not to be simulated can be reached.

    With nothing to simulate, a variable with no driver has nothing to take it anywhere, and a
    detector with no camera nothing to deliver its images. A wire with a real end cannot be armed.

    Raises:
        SpecError: Something is not wired; every one is listed.
    """
    problems = [
        f"the probe {name}: no driver reads a probe yet, so it is simulated or nothing"
        for name in instrument.probes()
        if simulate not in SIMULATED
    ]
    if simulate == "nothing":
        problems += [
            f"{variable.name} has no wired actuator (hardware.actuators)"
            for variable in instrument.variables.values()
            if not instrument_parts.keeps_itself(instrument, variable.cube)
            and instrument.hardware.actuators.get(variable.actuator or "") is None
        ]
        problems += [
            f"the detector {name} has no camera (hardware.cameras)"
            for name in instrument.detectors()
            if name not in instrument.hardware.cameras
        ]
    if simulate == "unwired" and instrument.hardware.cameras:
        # One manager runs all the detectors: it would leave these out without a word.
        problems += [
            f"the detector {name} has no camera beside those that do: real and simulated "
            "detectors cannot run together yet"
            for name in instrument.detectors()
            if name not in instrument.hardware.cameras
        ]
    if simulate not in SIMULATED:
        # A rig really wired this way while the software steps too would move twice per plane.
        problems += [
            f"{drive.source} -> {drive.target}: no driver can arm this wire yet"
            for drive in instrument.drives
            if simulate == "nothing" or _is_real(instrument, drive)
        ]
    if problems:
        raise SpecError(f"{instrument.name}: {'; '.join(problems)}")


def _is_real(instrument: Instrument, drive: Drive) -> bool:
    """Whether either end of a wire is hardware, with what is unwired simulated."""
    target = instrument.variables.get(drive.target)
    return drive.sender[0] in instrument.hardware.cameras or (
        target is not None and target.actuator in instrument.hardware.actuators
    )


def instrument_moves(instrument: Instrument) -> bool:
    """Whether anything on `instrument` moves."""
    return any(variable.verb == "moves" for variable in instrument.variables.values())
