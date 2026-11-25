"""What is on the sample holder decides what is drawn, never which channels there are: those follow
from the design alone, as on a real instrument, which does not know what is mounted."""

import shutil
from pathlib import Path

import pytest
import yaml

from newswitch.instrument import spec
from newswitch.instrument.compiler import compile_instrument, impacts
from newswitch.instrument.predict import Compiled
from newswitch.simulation import light
from newswitch.simulation.simulator import SimulatedMicroscope

INSTRUMENT = Path(__file__).parent.parent / "instruments" / "dual-camera"


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """Two cameras, each behind a filter of its own, with something on the holder or nothing."""
    return spec.load(INSTRUMENT)


def channels(compiled: Compiled) -> dict[tuple[str, str], str]:
    """Which source makes a channel at which detector, and of which kind."""
    state = compiled.instrument.initial_state()
    return {(c.source, c.detector): c.kind for c in compiled.channels(state)}


def edited(tmp_path: Path, simulation: dict) -> spec.Instrument:
    """The dual camera with its gfp-beads simulation changed as `simulation` says."""
    copy = tmp_path / "instrument"
    shutil.copytree(INSTRUMENT, copy)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    data["cubes"]["stage"]["element"]["simulations"]["gfp-beads"].update(simulation)
    path.write_text(yaml.safe_dump(data))
    return spec.load(copy)


def test_the_channels_are_found_from_the_optics(instrument: spec.Instrument) -> None:
    """The fluorescence and the transmitted light each reach the camera whose filter passes them."""
    assert channels(compile_instrument(instrument)) == {
        ("laser_488", "camera_green"): "emitted",
        ("led_625", "camera_red"): "direct",
    }


def test_the_channels_do_not_depend_on_what_is_simulated(
    instrument: spec.Instrument, tmp_path: Path
) -> None:
    """A sample letting nothing through, emitting nothing: the light paths, and so the channels,
    stay as they are. How bright one is, is the sample's."""
    dark = edited(tmp_path, {"transmit": 0.0, "fluorophore": None, "absorbed": None})
    assert channels(compile_instrument(dark)) == channels(compile_instrument(instrument))


def test_a_filter_keeps_a_reflection_from_being_a_channel(instrument: spec.Instrument) -> None:
    """With an emission filter in place, what a slide reflects of the laser never arrives: the
    laser's channel is of what is emitted."""
    assert channels(compile_instrument(instrument))[("laser_488", "camera_green")] == "emitted"


def test_with_no_filter_the_dichroic_alone_decides() -> None:
    """An open wheel: the dichroic keeps all but a trace of the laser out, and lets a dye's
    emission through, so the laser's channel is of what is emitted."""
    compiled = compile_instrument(spec.load(INSTRUMENT.parent / "fake-microscope"))
    assert compiled.instrument.initial_state()["filter_wheel.slot"] == 1  # Open
    assert channels(compiled)[("laser_488", "camera_a")] == "emitted"


def test_what_a_sample_does_decides_how_much_arrives(
    instrument: spec.Instrument, tmp_path: Path
) -> None:
    """The simulated light: no fluorophore, no electrons from the laser at the green camera."""
    state = instrument.initial_state()
    beads = light.traced(instrument, "camera_green", state)
    empty = light.traced(instrument, "camera_green", state, "empty-slide")
    assert beads["laser_488"]["electrons_per_mw_ms"] > 1e3 * empty["laser_488"]["electrons_per_mw_ms"]


def test_impacts_are_those_of_the_design(instrument: spec.Instrument) -> None:
    """What a change does is the optics': the laser's power changes the light of its channel,
    whatever is on the holder."""
    assert "light" in next(
        row["changes"]
        for row in impacts(instrument, instrument.initial_state())
        if row["variable"] == "laser_488.power" and row["detector"] == "camera_green"
    )


def test_a_simulation_decides_what_is_drawn(instrument: spec.Instrument) -> None:
    """Beads light up where they are; on an empty slide there is only the camera's offset."""
    microscope = SimulatedMicroscope(instrument)
    microscope.set({"laser_488.power": 50.0})
    assert microscope.image("camera_green").max() > 1000
    microscope.set({"stage.simulation": "empty-slide"})
    assert microscope.image("camera_green").max() < 200
