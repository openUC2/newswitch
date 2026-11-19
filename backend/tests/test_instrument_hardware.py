"""How a description reaches real hardware: its ``hardware`` section, and what is built from it."""

from __future__ import annotations

import re
import shutil
import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from newswitch.drivers.base import Simulated, SimulatedMove
from newswitch.drivers.simulated_detector import SimulatedDetectorManager
from newswitch.drivers.uc2.actuators import Laser, Stepper, Turret, Wheel
from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.drivers.uc2.rest_bus import UC2RestBus, UC2RestBusConfig
from newswitch.drivers.uc2.virtual_bus import VirtualUC2Bus
from newswitch.instrument import hardware, parts, spec
from newswitch.microscope.parts import build_drivers, build_microscope, build_uc2_bus, bus_options
from newswitch.settings import Settings
from newswitch.states.uc2 import UC2State
from newswitch.infra.export_schemas import REFERENCE_INSTRUMENT
from tests.conftest import registry_names, run_settings, wired_only

README = Path(__file__).parent.parent / "instruments" / "README.md"


@pytest.fixture
def real(tmp_path: Path) -> Settings:
    """Real hardware, with every folder under `tmp_path` and no debug window."""
    return run_settings(tmp_path, simulate="nothing")


@pytest.fixture
def wired(tmp_path: Path) -> Settings:
    """What is wired is real, for what is about actuators: no camera library is needed for those."""
    return run_settings(tmp_path, simulate="unwired")


def rewired(tmp_path: Path, **changes: Any) -> spec.Instrument:  # noqa: ANN401
    """The reference microscope with `changes` to its ``hardware`` section (None: removed)."""
    copy = tmp_path / "instrument"
    shutil.copytree(REFERENCE_INSTRUMENT, copy)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    for key, value in changes.items():
        if value is None:
            data["hardware"].pop(key)
        else:
            data["hardware"][key] = value
    wired_only(data, **{"actuators": {}, **data["hardware"]})
    path.write_text(yaml.safe_dump(data))
    return spec.load(copy)


def actuators(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    """The reference microscope's actuators with `changes`; None removes one."""
    data = yaml.safe_load((REFERENCE_INSTRUMENT / spec.DESCRIPTION).read_text())
    wired = {**data["hardware"]["actuators"], **changes}
    return {name: actuator for name, actuator in wired.items() if actuator is not None}


# --- what the section says


@pytest.mark.parametrize(
    "section, finding",
    [
        ({"boards": {"uc2": {"transport": "bluetooth"}}}, "bluetooth"),
        ({"boards": {"a": {"transport": "rest"}, "b": {"transport": "rest"}}}, "one board"),
        ({"boards": {"uc2": {"transport": "rest", "port": "a", "port_pattern": "b"}}}, "only one"),
        ({"actuators": {"stg-x": {"driver": "uc2.stepper", "board": "nope"}}}, "no board 'nope'"),
        ({"actuators": {"stg-x": {"board": "uc2", "axis": "X"}}}, "driver"),
        ({"cameras": {"cam": {"protocol": "firewire"}}}, "firewire"),
        ({"cameras": {"cam": {"protocol": "usb3-vision", "serial_number": 12}}}, "serial_number"),
        ({"cameras": {"cam": {"protocol": "usb3-vision", "index": -1}}}, "index"),
        ({"cameras": {"cam": {"protocol": "usb3-vision", "buffer_size": 1}}}, "buffer_size"),
        (
            {"cameras": {"cam": {"protocol": "usb3-vision", "serial_number": "a", "index": 0}}},
            "both select",
        ),
        ({"wires": {}}, "wires"),
    ],
)
def test_a_section_that_contradicts_itself_is_refused(
    section: dict[str, Any], finding: str
) -> None:
    """With what is wrong, and where."""
    with pytest.raises(spec.SpecError, match=finding):
        hardware.parse(section)


def test_no_section_is_nothing_wired() -> None:
    """Which a simulated microscope needs no more than that."""
    parsed = hardware.parse(None)
    assert parsed.board is None and not parsed.actuators and not parsed.cameras


@pytest.mark.parametrize(
    "changes, finding",
    [
        (
            {"actuators": actuators(ghost={"driver": "uc2.stepper", "board": "uc2", "axis": "X"})},
            "no variable has",
        ),
        ({"cameras": {"nope": {"protocol": "usb3-vision"}}}, "no sensor 'nope'"),
    ],
)
def test_it_must_name_what_the_description_has(
    tmp_path: Path, changes: dict[str, Any], finding: str
) -> None:
    """Told when the description is loaded, simulated or not."""
    with pytest.raises(spec.SpecError, match=finding):
        rewired(tmp_path, **changes)


def test_a_port_pattern_finds_the_port(tmp_path: Path) -> None:
    """The first that matches; what matches nothing is left to autodetection."""
    (tmp_path / "ttyACM1").touch()
    (tmp_path / "ttyACM0").touch()
    board = hardware.Board(name="uc2", transport="rest", port_pattern=str(tmp_path / "ttyACM*"))
    assert board.resolved_port() == str(tmp_path / "ttyACM0")
    assert (
        hardware.Board(
            name="uc2", transport="rest", port_pattern=str(tmp_path / "no*")
        ).resolved_port()
        is None
    )


@pytest.mark.parametrize(
    "block", re.findall(r"```yaml\n(hardware:.*?)```", README.read_text(), re.DOTALL)
)
def test_the_documented_setups_are_what_the_drivers_take(block: str) -> None:
    """The bench-validated values in instruments/README.md still reach a bus config."""
    parsed = hardware.parse(yaml.safe_load(block)["hardware"])
    board = parsed.board
    assert board is not None
    config = UC2RestBusConfig if board.transport == "rest" else UC2CanBusConfig
    built = config(**bus_options(parsed))
    assert built.steps_per_um_x == pytest.approx(3.2)
    assert [a.options["channel"] for a in parsed.actuators.values() if "channel" in a.options]


# --- simulated


def test_simulated_a_board_is_a_virtual_bus(tmp_path: Path) -> None:
    """Its UC2 actions work without one being there, and nothing else needs wiring."""
    settings = run_settings(tmp_path)
    instrument = rewired(tmp_path, actuators=None, cameras=None)
    assert "UC2State" in registry_names(instrument)[0]
    built = build_microscope(settings, instrument)
    assert isinstance(built.uc2_bus, VirtualUC2Bus)


# --- real hardware


def test_an_actuator_that_is_named_must_be_declared(tmp_path: Path) -> None:
    """A mistyped name would otherwise go unnoticed until a real run, or for good if simulated."""
    data = yaml.safe_load((REFERENCE_INSTRUMENT / spec.DESCRIPTION).read_text())
    data["cubes"]["stage"]["moves"]["z"]["actuator"] = "stg-zz"
    del data["hardware"]["actuators"]["stg-z"]
    copy = tmp_path / "instrument"
    shutil.copytree(REFERENCE_INSTRUMENT, copy)
    (copy / spec.DESCRIPTION).write_text(yaml.safe_dump(data))
    with pytest.raises(spec.SpecError, match="stage.z: hardware.actuators has no 'stg-zz'"):
        spec.load(copy)


def test_every_control_must_be_wired(tmp_path: Path, real: Settings) -> None:
    """Everything missing is said at once, before anything talks to a board."""
    instrument = rewired(
        tmp_path, actuators=actuators(**{"stg-x": None, "laser-dac": None}), cameras=None
    )
    with pytest.raises(spec.SpecError) as info:
        build_microscope(real, instrument)
    for finding in ("stage.x", "laser_488.power", "the detector camera"):
        assert finding in str(info.value)


def test_a_wheel_needs_its_positions(tmp_path: Path, wired: Settings) -> None:
    """One position per slot, or some slot would drive the wheel nowhere."""
    instrument = rewired(
        tmp_path,
        actuators=actuators(
            wheel={"driver": "uc2.wheel", "board": "uc2", "axis": "A", "positions": {1: 0.0}}
        ),
    )
    with pytest.raises(spec.SpecError, match="a position for each of the slots"):
        build_microscope(wired, instrument)


def test_each_source_has_its_own_pwm_scale(tmp_path: Path, wired: Settings) -> None:
    """Each has a driver of its own, so differing ones drive each source at its own power."""
    instrument = rewired(
        tmp_path,
        actuators=actuators(
            **{"led-dac": {"driver": "uc2.laser", "board": "uc2", "channel": 2, "pwm_max": 255}}
        ),
    )
    built = build_microscope(wired, instrument)
    assert built.values.drivers["laser_488.power"].config.pwm_max == 1023
    assert built.values.drivers["led_625.power"].config.pwm_max == 255


def test_a_power_with_no_max_has_no_full_scale(tmp_path: Path, wired: Settings) -> None:
    """A board's counts are a share of something: the description has to say of what."""

    def change(data: dict[str, Any]) -> None:
        data["cubes"]["laser_488"]["tunes"]["power"].pop("max")

    with pytest.raises(spec.SpecError, match="a laser's power needs a max"):
        build_microscope(wired, spec.load(edited(tmp_path, change)))


def test_a_rest_board_keeps_its_own_objective_positions(tmp_path: Path, wired: Settings) -> None:
    """Saying them would be ignored, so it is refused."""
    instrument = rewired(tmp_path, boards={"uc2": {"transport": "rest"}})
    with pytest.raises(spec.SpecError, match="only a canopen board takes positions"):
        build_microscope(wired, instrument)


def test_an_option_the_driver_does_not_have_is_refused(tmp_path: Path, real: Settings) -> None:
    """A misspelled option is an error, not ignored."""
    instrument = rewired(tmp_path, boards={"uc2": {"transport": "canopen", "bitrte": 500000}})
    with pytest.raises(spec.SpecError, match="bitrte"):
        build_microscope(real, instrument)


def test_a_board_has_no_stage_of_its_own(tmp_path: Path, real: Settings) -> None:
    """What moves is what its actuators say: a ``stage`` is an option no bus has."""
    instrument = rewired(
        tmp_path,
        boards={"uc2": {"transport": "canopen", "stage": {"home_axes": ["Z", "X", "Y"]}}},
    )
    with pytest.raises(spec.SpecError, match="stage"):
        build_microscope(real, instrument)


def test_what_is_not_wired_can_be_simulated_beside_what_is(tmp_path: Path) -> None:
    """``simulate: unwired`` takes a real stepper beside a simulated stage axis."""
    instrument = rewired(
        tmp_path,
        actuators={
            "stg-x": {"driver": "uc2.stepper", "board": "uc2", "axis": "X", "steps_per_um": 3.2}
        },
        cameras=None,
    )
    built = build_microscope(run_settings(tmp_path, simulate="unwired"), instrument)
    assert isinstance(built.uc2_bus, UC2CanBus)
    assert isinstance(built.values.drivers["stage.x"], Stepper)
    assert isinstance(built.values.drivers["stage.y"], SimulatedMove)
    assert isinstance(built.detector, SimulatedDetectorManager)


def test_it_runs_on_what_the_description_wires(wired: Settings) -> None:
    """Every variable gets its UC2 driver, configured from the section and the optics."""
    built = build_microscope(wired, spec.load(REFERENCE_INSTRUMENT))

    assert isinstance(built.uc2_bus, UC2CanBus)
    assert built.uc2_bus.config.channel == "can0"
    assert built.uc2_bus.config.steps_per_um_x == pytest.approx(3.2)
    assert built.uc2_bus.config.objective_slot_positions_steps == [0, 20000]

    drivers = built.values.drivers
    for name, axis in (("stage.x", "X"), ("stage.y", "Y"), ("stage.z", "Z")):
        assert isinstance(drivers[name], Stepper)
        assert drivers[name].config.axis == axis
        assert drivers[name].config.steps_per_um == pytest.approx(3.2)
    assert built.move_state.moves["stage"]["x"].maximum == 50000.0

    lasers = drivers["laser_488.power"], drivers["led_625.power"]
    assert all(isinstance(laser, Laser) for laser in lasers)
    assert [(laser.config.channel, laser.config.pwm_max) for laser in lasers] == [
        (1, 1023),
        (2, 1023),
    ]
    sources = built.source_state.sources.values()
    assert [s.wavelength for s in sources] == [488.0, 625.0]
    assert not any(s.on for s in sources)  # nothing turned them on yet

    assert isinstance(drivers["objective.slot"], Turret)
    swaps = built.swap_state.swaps
    assert [lens.label for lens in swaps["objective"]["slot"].options] == [
        "f20 NA 0.25",
        "f10 NA 0.4",
    ]

    assert isinstance(drivers["filter_wheel.slot"], Wheel)
    assert drivers["filter_wheel.slot"].config.axis == "A"
    assert drivers["filter_wheel.slot"].config.positions == {1: 0.0, 2: 120.0}
    assert [f.label for f in swaps["filter_wheel"]["slot"].options] == ["Open", "BP 525/50"]


def test_a_rest_board_opens_its_port(tmp_path: Path, real: Settings) -> None:
    """Its port goes where the rest bus takes it, with its other options."""
    instrument = rewired(
        tmp_path,
        boards={
            "uc2": {
                "transport": "rest",
                "port": "/dev/ttyUSB0",
                "baudrate": 921600,
                "require_master": True,
            }
        },
    )
    bus = build_uc2_bus(real, instrument, UC2State())
    assert isinstance(bus, UC2RestBus)
    assert bus.config.serialport == "/dev/ttyUSB0"
    assert (bus.config.baudrate, bus.config.require_master) == (921600, True)


def test_cameras_are_what_it_wires(tmp_path: Path) -> None:
    """How to open each, and its options apart, by name; none wired is none."""
    camera = {
        "protocol": "gige-vision",
        "vendor": "HikRobot",
        "serial_number": "00F1",
        "buffer_size": 8,
        "store_image_data": True,
        "vendor_options": {"frame_rate": 20.0},
    }
    found = parts.cameras(rewired(tmp_path, cameras={"camera": camera}))
    assert found is not None
    (detector,), options = found
    assert (detector.name, detector.manufacturer) == ("camera", "HikRobot")
    assert (detector.connection_type, detector.serial_number) == ("GigE", "00F1")
    assert (detector.buffer_size, detector.store_image_data) == (8, True)
    assert options == {"camera": {"frame_rate": 20.0}}


# --- the description as a whole


def edited(tmp_path: Path, change: Callable[[dict[str, Any]], None]) -> Path:
    """The reference microscope's description, with `change` made to it."""
    copy = tmp_path / "instrument"
    shutil.copytree(REFERENCE_INSTRUMENT, copy)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data))
    return copy


def _simulation(data: dict[str, Any]) -> dict[str, Any]:
    """What the description says is on the holder."""
    return data["cubes"]["stage"]["element"]["simulations"]["gfp-beads"]


@pytest.mark.parametrize(
    "change, finding",
    [
        (lambda d: d.update(colour="red"), "colour"),
        (lambda d: d.update(sample={}), "sample"),
        (
            lambda d: d["cubes"]["stage"].update(element={"kind": "filter"}),
            "no cube holds the sample",
        ),
        (lambda d: d["cubes"]["stage"]["element"].pop("simulations"), "simulations"),
        (lambda d: d["cubes"]["stage"]["element"].update(simulations={}), "simulations"),
        (lambda d: d["cubes"]["stage"]["element"].pop("simulation"), "simulation"),
        (
            lambda d: d["cubes"]["stage"]["element"].update(simulation="moon"),
            "'moon' is none of the simulations",
        ),
        (lambda d: d["cubes"]["stage"].update(tilts={}), "cubes.stage.tilts"),
        (lambda d: d["cubes"]["laser_488"]["element"].update(wavelength="488 mW"), "wavelength"),
        (lambda d: d["cubes"]["laser_488"]["element"].update(kind="plasma"), "plasma"),
        (lambda d: d["cubes"]["laser_488"]["element"].update(wavelenght="488 nm"), "wavelenght"),
        (lambda d: d["cubes"]["camera"].pop("tunes"), "must tune"),
        (lambda d: d["cubes"]["camera"]["tunes"].pop("exposure"), "must tune"),
        (
            lambda d: d["cubes"]["laser_488"]["tunes"].update(
                power={"initial": "5 ms", "step": "1 ms"}
            ),
            "power is in mW",
        ),
        (lambda d: d["cubes"]["dichroic"].pop("element"), "exactly one"),
        (lambda d: d["cubes"]["tube"]["element"].pop("f"), "focal length"),
        (lambda d: d["cubes"]["camera"]["element"]["axes"].pop("y"), "axes x and y"),
        (lambda d: d["cubes"]["camera"]["element"]["axes"]["x"].update(size="512"), "size"),
        (lambda d: d["cubes"]["stage"]["moves"]["x"].update(initial="99999 um"), "above max"),
        (lambda d: d["cubes"]["stage"]["moves"]["x"].update(along="sideways"), "sideways"),
        (lambda d: d["cubes"]["objective"]["swaps"]["slot"].update(initial=7), "none of the slots"),
        (
            lambda d: d["cubes"]["filter_wheel"]["swaps"]["slot"]["slots"][2].update(
                curve={"type": "bandpass", "center": "525 nm", "peak": 0.95, "edge": "2 nm"}
            ),
            "width",
        ),
        (
            lambda d: d["cubes"]["filter_wheel"]["swaps"]["slot"]["slots"][2].update(
                curve="nothing"
            ),
            "no 'nothing' in curves",
        ),
        (lambda d: _simulation(d).update(transmit=1.5), "transmit"),
        (lambda d: _simulation(d).update(fluorophore="nothing"), "no 'nothing' in fluorophores"),
        (lambda d: _simulation(d).pop("absorbed"), "come together"),
        (lambda d: _simulation(d).pop("pattern"), "pattern"),
        (lambda d: _simulation(d)["pattern"].update(beads=-1), "beads"),
        (lambda d: d["detection"][0].update(via="absorb"), "absorb"),
        (lambda d: d["detection"][1].update(distance="far"), "distance"),
        (lambda d: d.update(parts={}), "parts"),
        (lambda d: d.pop("settings"), "settings"),
        (lambda d: d["cubes"]["camera"]["tunes"]["frame_rate"].pop("initial"), "frame_rate"),
        (
            lambda d: d["cubes"]["camera"]["tunes"]["frame_rate"].update(initial="30 mm"),
            "frame_rate",
        ),
        (lambda d: d.update(ui={"views": ["fluorescence"]}), "views"),
        (lambda d: d.update(ui={"catalog": "newswitch", "bloks": {}}), "catalog"),
        (lambda d: d.update(ui={"catalog": "newswitch@3", "bloks": {"v": {}}}), "bsx"),
        (lambda d: d.update(agent_ui={"bloks": {"v": {"x": 1}}}), "v"),
        (lambda d: d.update(agent_ui={"catalog": "orkestrator@v4", "bloks": {}}), "catalog"),
    ],
)
def test_a_description_that_does_not_validate_is_refused(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], finding: str
) -> None:
    """When it is loaded, naming the place in the file."""
    with pytest.raises(spec.SpecError, match=finding):
        spec.load(edited(tmp_path, change))


def test_an_objective_needs_its_na(tmp_path: Path) -> None:
    """Refused when the description is loaded, naming where in it."""

    def change(data: dict[str, Any]) -> None:
        del data["cubes"]["objective"]["swaps"]["slot"]["slots"][1]["na"]

    with pytest.raises(
        spec.SpecError, match=r"objective\.slot: slot 1: the lens nearest .* its na"
    ):
        spec.load(edited(tmp_path, change))


def test_a_detector_only_has_to_tune_its_exposure(tmp_path: Path) -> None:
    """What it does not tune is fixed: no frame rate, no gain, no binning, and it takes images."""

    def change(data: dict[str, Any]) -> None:
        tunes = data["cubes"]["camera"]["tunes"]
        data["cubes"]["camera"]["tunes"] = {"exposure": tunes["exposure"]}

    built = build_microscope(run_settings(tmp_path), spec.load(edited(tmp_path, change)))
    assert built.detector is not None
    (detector,) = built.detector_state.detectors
    assert (detector.current_frame_rate, detector.current_gain) == (None, None)
    assert detector.binning() == 1
    assert built.detector.capture_image("camera").data.shape == (512, 512)


def test_every_problem_is_listed_at_once(tmp_path: Path) -> None:
    """So that fixing a file takes one round."""

    def change(data: dict[str, Any]) -> None:
        data["cubes"]["laser_488"]["element"]["wavelength"] = "488 mW"
        _simulation(data)["transmit"] = 1.5

    with pytest.raises(spec.SpecError) as info:
        spec.load(edited(tmp_path, change))
    assert "cubes.laser_488.element.source.wavelength" in str(info.value)
    assert "cubes.stage.element.sample.simulations.gfp-beads.transmit" in str(info.value)


def test_the_loaded_values_are_typed_and_in_their_units() -> None:
    """A quantity in the file is a number in the unit newswitch keeps it in."""
    instrument = spec.load(REFERENCE_INSTRUMENT)
    laser = instrument.cubes["laser_488"].element
    assert isinstance(laser, spec.Source)
    assert (laser.wavelength, laser.max_power, laser.emits) == (488.0, 50.0, "laser")
    sensor = instrument.cubes["camera"].element
    assert isinstance(sensor, spec.Sensor)
    assert (sensor.axes["x"].size, sensor.axes["x"].pitch) == (512, 6.5)
    assert instrument.detection[-1].distance == "focus"
    assert instrument.detection[1].distance == 100.0
    fluorophore = instrument.sample_holder("stage").simulations["gfp-beads"].fluorophore
    assert fluorophore is not None and fluorophore.excitation == 488.0
    assert instrument.cubes["camera"].tunes["frame_rate"].initial == 30.0
    binning = instrument.cubes["camera"].variables["binning"].initial
    assert binning == 1 and isinstance(binning, int)


def test_the_instrument_is_itself_validated() -> None:
    """Not only what is loaded: an instrument that contradicts itself cannot be made at all."""
    instrument = spec.load(REFERENCE_INSTRUMENT)
    assert dataclasses.is_dataclass(instrument) and hasattr(instrument, "__pydantic_fields__")
    with pytest.raises(ValidationError, match="name"):
        dataclasses.replace(instrument, name=3)
    with pytest.raises(ValidationError, match="no light reaches camera"):
        dataclasses.replace(instrument, detection=instrument.detection[:1])
    assert instrument.cubes["stage"].variables["x"].name == "stage.x"
    assert instrument.cubes["stage"].variables["x"].cube == "stage"


def test_the_constants_are_the_files(tmp_path: Path) -> None:
    """Power range, frame rate and magnification reach the models as stated."""

    def change(data: dict[str, Any]) -> None:
        data["cubes"]["objective"]["swaps"]["slot"]["slots"][1]["magnification"] = 9.0
        data["cubes"]["laser_488"]["element"]["max_power"] = "255 mW"
        data["cubes"]["camera"]["tunes"]["frame_rate"]["initial"] = "12.5 Hz"

    instrument = spec.load(edited(tmp_path, change))
    built = build_microscope(run_settings(tmp_path), instrument)
    lens = built.swap_state.swaps["objective"]["slot"].options[0]
    assert lens.facts["magnification"] == "9x"
    laser = built.source_state.sources["laser_488"]
    assert (laser.max_power, laser.power) == (255.0, 20.0)
    assert parts.detectors(instrument)[0].current_frame_rate == 12.5


def test_sources_are_in_the_order_of_the_file(tmp_path: Path) -> None:
    """Swapping two cubes swaps them: nothing else says which comes first."""
    copy = edited(tmp_path, lambda _: None)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    cubes = data["cubes"]
    data["cubes"] = {"led_625": cubes.pop("led_625"), "laser_488": cubes.pop("laser_488"), **cubes}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert spec.load(copy).sources() == ["led_625", "laser_488"]


def test_real_and_simulated_detectors_are_refused_together(tmp_path: Path) -> None:
    """One manager runs them all: it would leave the simulated ones out without a word."""
    data = yaml.safe_load(
        (
            Path(__file__).parent.parent / "instruments" / "dual-camera" / spec.DESCRIPTION
        ).read_text()
    )
    data.pop("ui", None)
    data.pop("agent_ui", None)
    wired_only(data, {}, cameras={"camera_green": {"protocol": "usb3-vision"}})
    (tmp_path / spec.DESCRIPTION).write_text(yaml.safe_dump(data))
    with pytest.raises(spec.SpecError, match="camera_red has no camera beside those that do"):
        build_microscope(run_settings(tmp_path, simulate="unwired"), spec.load(tmp_path))


@pytest.mark.parametrize(
    "name",
    [
        "rgb-camera",
        "dual-camera",
        "fake-microscope",
        "flim",
        "light-sheet",
        "point-scanner",
        "he-microscope",
    ],
)
def test_the_example_wiring_can_be_built(name: str, tmp_path: Path) -> None:
    """They all simulate everything, so nothing else would notice a wrong option."""
    instrument = spec.load(Path(__file__).parent.parent / "instruments" / name)
    settings = run_settings(tmp_path, simulate="unwired")
    bus = build_uc2_bus(settings, instrument, UC2State())
    drivers = build_drivers(settings, instrument, bus, None)
    wired = [v.name for v in instrument.variables.values() if v.actuator is not None]
    assert wired and all(variable in drivers for variable in wired)
    assert all(not isinstance(drivers[variable], Simulated) for variable in wired)
