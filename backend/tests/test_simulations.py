"""What is on the sample holder: which channels there are, and what is drawn, follow from it."""

import dataclasses
import shutil
from pathlib import Path

import pytest
import yaml

from newswitch.drivers.optics.simulator import SimulatedMicroscope
from newswitch.instrument import spec
from newswitch.instrument.compiler import compile_instrument, impacts
from newswitch.instrument.predict import Compiled, state_key
from newswitch.instrument.tracing import coupling

INSTRUMENT = Path(__file__).parent.parent / "instruments" / "dual-camera"


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """Two cameras, each behind a filter of its own, with something on the holder or nothing."""
    return spec.load(INSTRUMENT)


def channels(compiled: Compiled, simulation: str) -> set[tuple[str, str]]:
    """Which source reaches which detector under `simulation`."""
    instrument = compiled.instrument
    state = {**instrument.initial_state(), instrument.simulation_key(): simulation}
    return {(channel.source, channel.detector) for channel in compiled.channels(state)}


def under(instrument: spec.Instrument, simulation: str) -> spec.Instrument:
    """`instrument` with `simulation` picked in its settings."""
    picked = instrument.settings.model_copy(update={"simulation": simulation})
    return dataclasses.replace(instrument, settings=picked)


def test_the_channels_are_found_from_the_optics(instrument: spec.Instrument) -> None:
    """The fluorescence and the transmitted light each reach the camera whose filter passes them."""
    assert channels(compile_instrument(instrument), "gfp-beads") == {
        ("laser-488", "camera-green"),
        ("led-625", "camera-red"),
    }


def test_without_a_fluorophore_there_is_no_fluorescence_channel(
    instrument: spec.Instrument,
) -> None:
    """Only what passes through the slide is left."""
    assert channels(compile_instrument(instrument), "empty-slide") == {("led-625", "camera-red")}


def test_a_reflection_too_faint_to_see_is_no_channel() -> None:
    """With the filter open, a slide's reflection of the laser arrives, under the read noise."""
    compiled = compile_instrument(spec.load(INSTRUMENT.parent / "fake-microscope"))
    assert channels(compiled, "empty-slide") == {
        ("led-625", "camera-a"),
        ("led-625", "camera-b"),
    }


def test_a_sample_letting_nothing_through_has_no_transmitted_channel(tmp_path: Path) -> None:
    """A sample's numbers decide what is a channel: the light paths stay as they are."""
    copy = tmp_path / "instrument"
    shutil.copytree(INSTRUMENT, copy)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    data["cubes"]["stage"]["element"]["simulations"]["gfp-beads"]["transmit"] = 0.0
    path.write_text(yaml.safe_dump(data))
    opaque = spec.load(copy)
    state = opaque.initial_state()
    entry = {
        detector: {"coupling": coupling(opaque, detector, state)} for detector in opaque.detectors()
    }
    compiled = Compiled(opaque, {state_key(opaque, state): entry})
    assert channels(compiled, "gfp-beads") == {("laser-488", "camera-green")}


def test_impacts_are_those_of_the_simulation_picked(instrument: spec.Instrument) -> None:
    """What a change does depends on what is on the holder."""

    def light_changes(picked: spec.Instrument) -> bool:
        return "light" in next(
            row["changes"]
            for row in impacts(picked, picked.initial_state())
            if row["variable"] == "laser-488.power" and row["detector"] == "camera-green"
        )

    assert light_changes(instrument)
    assert not light_changes(under(instrument, "empty-slide"))


def test_a_simulation_decides_what_is_drawn(instrument: spec.Instrument) -> None:
    """Beads light up where they are; on an empty slide there is only the camera's offset."""
    microscope = SimulatedMicroscope(instrument)
    microscope.set({"laser-488.power": 50.0})
    assert microscope.image("camera-green").max() > 1000
    microscope.set({"stage.simulation": "empty-slide"})
    assert microscope.image("camera-green").max() < 200
