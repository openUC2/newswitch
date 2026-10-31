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

from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.drivers.uc2.filter_bank_manager import UC2FilterBankManager
from newswitch.drivers.uc2.illumination_manager import UC2IlluminationManager
from newswitch.drivers.uc2.objective_manager import UC2ObjectiveManager
from newswitch.drivers.uc2.rest_bus import UC2RestBus, UC2RestBusConfig
from newswitch.drivers.uc2.stage_manager import UC2StageManager
from newswitch.drivers.uc2.virtual_bus import VirtualUC2Bus
from newswitch.instrument import hardware, parts, spec
from newswitch.microscope.parts import build_microscope, build_uc2_bus
from newswitch.settings import Settings
from newswitch.states.uc2 import UC2State
from newswitch.tools.export_schemas import REFERENCE_INSTRUMENT
from tests.conftest import registry_names, run_settings

README = Path(__file__).parent.parent / "instruments" / "README.md"


@pytest.fixture
def real(tmp_path: Path) -> Settings:
    """Real hardware, with every folder under `tmp_path` and no debug window."""
    return run_settings(tmp_path, use_virtual_microscope=False)


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
        ({"boards": {"uc2": {"transport": "rest", "stage": {"axes": ["X"]}}}}, "its actuators"),
        ({"actuators": {"stg-x": {"board": "nope", "axis": "X"}}}, "no board 'nope'"),
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
        ({"actuators": actuators(ghost={"board": "uc2", "axis": "X"})}, "no variable has"),
        ({"actuators": actuators(**{"stg-x": {"board": "uc2", "axis": "Y"}})}, "on axis X"),
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
    built = config(**board.options)
    assert built.steps_per_um_x == pytest.approx(3.2)
    assert board.stage["home_axes"] == ["Z", "X", "Y"]
    assert [a.channel for a in parsed.actuators.values() if a.channel is not None]


# --- simulated


def test_simulated_a_board_is_a_virtual_bus(tmp_path: Path) -> None:
    """Its UC2 actions work without one being there, and nothing else needs wiring."""
    settings = run_settings(tmp_path)
    instrument = rewired(tmp_path, actuators=None, cameras=None)
    assert "UC2State" in registry_names(instrument)[0]
    built = build_microscope(settings, instrument)
    assert isinstance(built.uc2_bus, VirtualUC2Bus)


# --- real hardware


def test_every_control_must_be_wired(tmp_path: Path, real: Settings) -> None:
    """Everything missing is said at once, before anything talks to a board."""
    instrument = rewired(
        tmp_path, actuators=actuators(**{"stg-x": None, "laser-dac": None}), cameras=None
    )
    with pytest.raises(spec.SpecError) as info:
        build_microscope(real, instrument)
    for finding in ("stage.x", "laser_488.power", "the sensor camera"):
        assert finding in str(info.value)


def test_a_wheel_needs_its_positions(tmp_path: Path, real: Settings) -> None:
    """One position per slot, or some slot would drive the wheel nowhere."""
    instrument = rewired(
        tmp_path, actuators=actuators(wheel={"board": "uc2", "axis": "A", "positions": {1: 0.0}})
    )
    with pytest.raises(spec.SpecError, match="a position for each of the slots"):
        build_microscope(real, instrument)


def test_sources_share_one_pwm_scale(tmp_path: Path, real: Settings) -> None:
    """The driver has one, so differing ones would drive a source at the wrong power."""
    instrument = rewired(
        tmp_path, actuators=actuators(**{"led-dac": {"board": "uc2", "channel": 2, "pwm_max": 255}})
    )
    with pytest.raises(spec.SpecError, match="one pwm_max"):
        build_microscope(real, instrument)


def test_a_rest_board_keeps_its_own_objective_positions(tmp_path: Path, real: Settings) -> None:
    """Saying them would be ignored, so it is refused."""
    instrument = rewired(tmp_path, boards={"uc2": {"transport": "rest"}})
    with pytest.raises(spec.SpecError, match="only a canopen board takes positions"):
        build_microscope(real, instrument)


def test_an_option_the_driver_does_not_have_is_refused(tmp_path: Path, real: Settings) -> None:
    """A misspelled option is an error, not ignored."""
    instrument = rewired(tmp_path, boards={"uc2": {"transport": "canopen", "bitrte": 500000}})
    with pytest.raises(spec.SpecError, match="bitrte"):
        build_microscope(real, instrument)


def test_it_runs_on_what_the_description_wires(real: Settings) -> None:
    """Every part gets its UC2 manager, configured from the section and the optics."""
    built = build_microscope(real, spec.load(REFERENCE_INSTRUMENT))

    assert isinstance(built.uc2_bus, UC2CanBus)
    assert built.uc2_bus.config.channel == "can0"
    assert built.uc2_bus.config.steps_per_um_x == pytest.approx(3.2)
    assert built.uc2_bus.config.objective_slot_positions_steps == [0, 20000]

    assert isinstance(built.stage, UC2StageManager)
    assert built.stage.config.axes == ["X", "Y", "Z"]
    assert built.stage.config.home_axes == ["Z", "X", "Y"]
    assert built.stage_state.max_x == 50000.0

    assert isinstance(built.illumination, UC2IlluminationManager)
    assert built.illumination.config.pwm_max == 1023
    sources = built.illumination_state.illuminations
    assert [(s.channel, s.wavelength) for s in sources] == [(1, 488.0), (2, 625.0)]
    assert not any(s.is_active for s in sources)  # nothing turned them on yet

    assert isinstance(built.objective, UC2ObjectiveManager)
    assert [lens.name for lens in built.objective_state.mounted_lenses] == [
        "f20 NA 0.25",
        "f10 NA 0.4",
    ]

    assert isinstance(built.filter_bank, UC2FilterBankManager)
    assert built.filter_bank.config.axis == "A"
    assert built.filter_bank.config.slot_positions == [0.0, 120.0]
    assert [f.name for f in built.filter_bank_state.filters] == ["Open", "BP 525/50"]


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
    """How to open each, and its options apart, by slot; none wired is none."""
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
    assert (detector.slot, detector.name, detector.manufacturer) == (1, "camera", "HikRobot")
    assert (detector.connection_type, detector.serial_number) == ("GigE", "00F1")
    assert (detector.buffer_size, detector.store_image_data) == (8, True)
    assert options == {1: {"frame_rate": 20.0}}


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
        (lambda d: d["settings"].pop("simulation"), "simulation"),
        (lambda d: d["settings"].update(simulation="moon"), "'moon' is none of the simulations"),
        (lambda d: d["cubes"]["stage"].update(tilts={}), "cubes.stage.tilts"),
        (lambda d: d["cubes"]["laser_488"]["element"].update(wavelength="488 mW"), "wavelength"),
        (lambda d: d["cubes"]["laser_488"]["element"].update(kind="plasma"), "plasma"),
        (lambda d: d["cubes"]["laser_488"]["element"].update(wavelenght="488 nm"), "wavelenght"),
        (lambda d: d["cubes"]["laser_488"].pop("tunes"), "must tune"),
        (lambda d: d["cubes"]["camera"].pop("tunes"), "must tune"),
        (lambda d: d["cubes"]["dichroic"].pop("element"), "exactly one"),
        (lambda d: d["cubes"]["tube"]["element"].pop("f"), "focal length"),
        (lambda d: d["cubes"]["camera"]["element"]["axes"].pop("y"), "axes x and y"),
        (lambda d: d["cubes"]["camera"]["element"]["axes"]["x"].update(size="512"), "size"),
        (lambda d: d["cubes"]["stage"]["moves"]["x"].update(initial=99999.0), "above max"),
        (lambda d: d["cubes"]["stage"]["moves"]["x"].update(along="sideways"), "sideways"),
        (lambda d: d["cubes"]["objective"]["swaps"]["slot"].update(initial=7), "none of the slots"),
        (lambda d: d["cubes"]["objective"]["swaps"]["slot"]["slots"][1].pop("na"), "f and na"),
        (lambda d: d["cubes"]["filter_wheel"]["swaps"]["slot"]["slots"][2].pop("width"), "both"),
        (lambda d: _simulation(d).update(transmit=1.5), "transmit"),
        (lambda d: _simulation(d)["fluorophore"].pop("emission"), "emission"),
        (lambda d: _simulation(d).pop("pattern"), "pattern"),
        (lambda d: _simulation(d)["pattern"].update(beads=-1), "beads"),
        (lambda d: d["detection"][0].update(via="absorb"), "absorb"),
        (lambda d: d["detection"][1].update(distance="far"), "distance"),
        (lambda d: d.pop("parts"), "parts"),
        (lambda d: d.pop("settings"), "settings"),
        (lambda d: d["parts"].update(stage="dichroic"), "holds no sample"),
        (lambda d: d["parts"].update(stage="nothing"), "holds no sample"),
        (lambda d: d["parts"].update(colour="red"), "colour"),
        (lambda d: d["parts"]["objective"].pop("reference_tube"), "reference_tube"),
        (lambda d: d["parts"]["objective"].update(swap="nothing.slot"), "no swap"),
        (lambda d: d["parts"]["objective"].update(swap="filter_wheel.slot"), "is no lens"),
        (lambda d: d["parts"]["filters"].update(swap="objective.slot"), "is no filter"),
        (lambda d: d["parts"]["objective"].update(swap="stage.x"), "no swap"),
        (lambda d: d["parts"]["sources"].pop(2), "'led_625' has no slot"),
        (lambda d: d["parts"]["sources"][2].update(cube="dichroic"), "holds no source"),
        (lambda d: d["parts"]["sources"][2].update(cube="laser_488"), "two slots"),
        (lambda d: d["parts"]["sources"][1].pop("full_intensity"), "full_intensity"),
        (lambda d: d["parts"]["sources"].update({5: d["parts"]["sources"].pop(2)}), "count from 1"),
        (lambda d: d["parts"]["detectors"].pop(1), "'camera' has no slot"),
        (lambda d: d["parts"]["detectors"][1].pop("frame_rate"), "frame_rate"),
        (lambda d: d["parts"]["detectors"][1].update(frame_rate="30 mm"), "frame_rate"),
        (
            lambda d: d["cubes"]["stage"]["moves"].update(w=d["cubes"]["stage"]["moves"].pop("x")),
            "not 'w'",
        ),
        (lambda d: d.update(ui={"views": ["fluorescence"]}), "views"),
        (lambda d: d.update(ui={"catalog": "newswitch", "bloks": {}}), "catalog"),
        (lambda d: d.update(ui={"catalog": "newswitch@2", "bloks": {"v": {}}}), "bsx"),
        (lambda d: d.update(agent_ui={"catalog": "orkestrator@v4", "bloks": {"v": {"x": 1}}}), "v"),
    ],
)
def test_a_description_that_does_not_validate_is_refused(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], finding: str
) -> None:
    """When it is loaded, naming the place in the file."""
    with pytest.raises(spec.SpecError, match=finding):
        spec.load(edited(tmp_path, change))


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
    assert (laser.wavelength, laser.max_power, laser.coherent) == (488.0, 50.0, True)
    sensor = instrument.cubes["camera"].element
    assert isinstance(sensor, spec.Sensor)
    assert (sensor.axes["x"].size, sensor.axes["x"].pitch) == (512, 6.5)
    assert instrument.detection[-1].distance == "focus"
    assert instrument.detection[1].distance == 100.0
    fluorophore = instrument.sample_holder().simulations["gfp-beads"].fluorophore
    assert fluorophore is not None and fluorophore.excitation == 488.0
    assert instrument.parts.objective is not None
    assert instrument.parts.objective.reference_tube == 200.0
    assert instrument.parts.detectors[1].frame_rate == 30.0
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
    """Intensity range, frame rate and reference tube reach the models as stated."""

    def change(data: dict[str, Any]) -> None:
        data["parts"]["objective"]["reference_tube"] = "180 mm"
        data["parts"]["sources"][1]["full_intensity"] = 255.0
        data["parts"]["detectors"][1]["frame_rate"] = "12.5 Hz"

    instrument = spec.load(edited(tmp_path, change))
    lenses = parts.objective_lenses(instrument)
    assert lenses is not None and lenses[0][0].magnification == pytest.approx(180.0 / 20.0)
    sources = parts.illuminations(instrument)
    assert sources is not None
    assert sources[0].max_intensity == 255.0
    assert sources[0].intensity == pytest.approx(255.0 * 20.0 / 50.0)
    detectors = parts.detectors(instrument)
    assert detectors is not None and detectors[0].current_frame_rate == 12.5


def test_slots_are_the_files_not_the_order_of_its_cubes(tmp_path: Path) -> None:
    """Swapping two slots swaps them, wherever the cubes stand in the file."""

    def change(data: dict[str, Any]) -> None:
        sources = data["parts"]["sources"]
        sources[1], sources[2] = sources[2], sources[1]

    instrument = spec.load(edited(tmp_path, change))
    assert instrument.sources() == ["led_625", "laser_488"]
    found = parts.illuminations(instrument)
    assert found is not None
    assert [(s.slot, s.wavelength) for s in found] == [(1, 625.0), (2, 488.0)]


def test_a_swap_with_no_role_has_no_control(tmp_path: Path) -> None:
    """A wheel of lenses is no objective changer until the file says so."""
    instrument = spec.load(edited(tmp_path, lambda d: d["parts"].pop("objective")))
    assert "switch_objective" not in registry_names(instrument)[1]
    assert parts.objective_lenses(instrument) is None


def test_a_cube_with_moves_is_no_stage_until_the_file_says_so(tmp_path: Path) -> None:
    """No stage part, whatever moves on the sample's cube."""
    instrument = spec.load(edited(tmp_path, lambda d: d["parts"].pop("stage")))
    assert "move_stage" not in registry_names(instrument)[1]
    assert parts.stage_moves(instrument) == {}
