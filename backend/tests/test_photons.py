"""The laws: light counted in photons, from what the description states."""

import copy
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pytest
import yaml

from newswitch.instrument import spec, tracing
from newswitch.instrument.compiler import compile_instrument
from newswitch.simulation import light
from newswitch.simulation.simulator import SimulatedMicroscope

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
BASE = yaml.safe_load((INSTRUMENTS / "dual-camera" / spec.DESCRIPTION).read_text())


def described(tmp_path: Path, change: Callable[[dict[str, Any]], Any]) -> spec.Instrument:
    """The dual camera instrument, with `change` made to it."""
    data = copy.deepcopy(BASE)
    data.pop("ui", None)
    data.pop("agent_ui", None)
    change(data)
    path = tmp_path / spec.DESCRIPTION
    path.write_text(yaml.safe_dump(data))
    return spec.load(path)


def electrons(instrument: spec.Instrument, detector: str = "camera_green") -> float:
    """What the laser makes at `detector`, per milliwatt and millisecond."""
    entry = light.traced(instrument, detector, instrument.initial_state())
    return entry["laser_488"]["electrons_per_mw_ms"]


def lens(data: dict[str, Any]) -> dict[str, Any]:
    """What the description says of the objective."""
    return data["cubes"]["objective"]["element"]


# --- quantities


@pytest.mark.parametrize(
    "change, finding",
    [
        (lambda d: d["cubes"]["stage"]["moves"]["x"].update(initial=0.0), "needs its unit"),
        (lambda d: d["cubes"]["stage"]["moves"]["x"].update(max="5 mW"), "different kinds"),
        (lambda d: d["cubes"]["stage"]["moves"]["x"].update(units="um"), "units"),
        (
            lambda d: d["cubes"]["stage"]["moves"].update(
                x={"along": "x", "initial": "0 mW", "step": "1 mW"}
            ),
            "moves in a length",
        ),
        (
            lambda d: d["cubes"]["camera_green"]["tunes"].update(gain={"initial": "1 ms"}),
            "gain is in",
        ),
        (lambda d: lens(d).update(f=20.0), "needs its unit"),
        (lambda d: lens(d).pop("immersion"), "needs its immersion"),
        (lambda d: lens(d).update(na=1.4), "needs more than an index"),
        (lambda d: lens(d).update(immersion="honey"), "honey"),
    ],
)
def test_what_is_not_a_quantity_is_refused(
    tmp_path: Path, change: Callable[[dict[str, Any]], Any], finding: str
) -> None:
    """A bare number has no unit, and a value in the wrong one means something else."""
    with pytest.raises(spec.SpecError, match=finding):
        described(tmp_path, change)


def test_any_unit_of_a_dimension_says_the_same(tmp_path: Path) -> None:
    """An exposure in seconds is the same exposure: the description decides how to write it."""

    def in_seconds(data: dict[str, Any]) -> None:
        data["cubes"]["camera_green"]["tunes"]["exposure"] = {"initial": "0.1 s", "step": "0.01 s"}

    tune = described(tmp_path, in_seconds).cubes["camera_green"].tunes["exposure"]
    assert (tune.initial, tune.step, tune.unit) == (pytest.approx(100.0), pytest.approx(10.0), "ms")


# --- the chain


def test_a_milliwatt_is_as_many_photons_as_physics_says() -> None:
    """A millijoule per second at 488 nm, over a millisecond."""
    assert 1e-6 * 488e-9 / (6.62607015e-34 * 299792458.0) == pytest.approx(2.4567e12, rel=1e-3)


def test_collection_is_the_cone_of_the_objective() -> None:
    """The solid angle's share of a sphere: hand computed."""
    air = spec.Lens(kind="lens", f="20 mm", na=0.25, immersion="air")
    assert tracing.collected(air) == pytest.approx(0.015877, rel=1e-3)
    oil = spec.Lens(kind="lens", f="2 mm", na=1.4, immersion="oil")
    assert tracing.collected(oil) == pytest.approx((1 - math.cos(math.asin(1.4 / 1.515))) / 2)


def test_more_na_collects_more(tmp_path: Path) -> None:
    """In the ratio of the cones: what used to be the same for any NA."""
    low = electrons(described(tmp_path, lambda d: None))
    high = electrons(described(tmp_path, lambda d: lens(d).update(na=0.5)))
    expected = (1 - math.cos(math.asin(0.5))) / (1 - math.cos(math.asin(0.25)))
    assert high / low == pytest.approx(expected, rel=1e-4)


def test_the_full_chain_by_hand(tmp_path: Path) -> None:
    """A bead's electrons per milliwatt and millisecond, multiplied out factor by factor."""
    instrument = described(tmp_path, lambda d: None)
    grid = light.grid(instrument)
    holder = instrument.sample_holder("stage")
    sample = holder.simulations[holder.simulation]
    photons = 1e-6 * 488e-9 / (6.62607015e-34 * 299792458.0)
    laser = tracing.gaussian(grid, 488.0, 2.0)
    laser = laser / laser.sum()
    reflected = 1.0 - tracing.curve_at(instrument.cubes["dichroic"].element.curve, grid)
    excited = (laser * reflected * tracing.gaussian(grid, 488.0, 20.0)).sum()
    emission = tracing.gaussian(grid, 515.0, 25.0)
    emission = emission / emission.sum()
    passed = (
        tracing.curve_at(instrument.cubes["dichroic"].element.curve, grid)
        * 0.5  # the splitter
        * tracing.curve_at(instrument.cubes["filter_green"].element.curve, grid)
    )
    expected = (
        photons
        * excited
        * sample.absorbed
        * sample.fluorophore.quantum_yield
        * tracing.collected(instrument.cubes["objective"].element)
        * (emission * passed).sum()
        * instrument.cubes["camera_green"].element.readout.qe
    )
    assert electrons(instrument) == pytest.approx(expected, rel=1e-3)


def test_a_field_shares_its_light_by_area(tmp_path: Path) -> None:
    """Light on twice the width is a quarter as bright per pixel."""

    def wider(data: dict[str, Any]) -> None:
        for edge in data["illumination"]:
            if edge.get("field"):
                edge["field"] = "1 mm"

    narrow = described(tmp_path, lambda d: None)
    wide = described(tmp_path, wider)
    lit = {**narrow.initial_state(), "laser_488.power": 10.0}
    assert compile_instrument(wide).answer("camera_green", lit).light == pytest.approx(
        compile_instrument(narrow).answer("camera_green", lit).light / 4.0
    )


def test_light_needs_somewhere_to_land(tmp_path: Path) -> None:
    """How wide a source's light lands decides how bright a pixel is."""

    def no_field(data: dict[str, Any]) -> None:
        for edge in data["illumination"]:
            edge.pop("field", None)

    with pytest.raises(spec.SpecError, match="needs its field"):
        described(tmp_path, no_field)


# --- curves


def test_curves_are_what_they_say() -> None:
    """Each shape, at the wavelengths that define it."""
    grid = np.array([400.0, 500.0, 525.0, 600.0, 700.0])
    edge = {"peak": 0.9, "edge": "2 nm"}
    band = spec.BandPass(type="bandpass", center="525 nm", width="50 nm", **edge)
    assert tracing.curve_at(band, grid)[2] == pytest.approx(0.9, abs=1e-4)
    assert tracing.curve_at(band, grid)[0] < 1e-9
    long = spec.LongPass(type="longpass", cut="500 nm", **edge)
    assert tracing.curve_at(long, grid)[1] == pytest.approx(0.45)
    assert tracing.curve_at(long, grid)[4] == pytest.approx(0.9)
    short = spec.ShortPass(type="shortpass", cut="500 nm", **edge)
    assert tracing.curve_at(short, grid)[0] == pytest.approx(0.9, abs=1e-4)
    many = spec.MultiBand(
        type="multiband",
        bands=({"center": "400 nm", "width": "20 nm"}, {"center": "700 nm", "width": "20 nm"}),
        **edge,
    )
    assert tracing.curve_at(many, grid)[[0, 4]] == pytest.approx([0.9, 0.9], abs=0.01)
    assert tracing.curve_at(many, grid)[2] < 1e-9
    blocked = spec.BandPass(type="bandpass", center="525 nm", width="50 nm", od=3.0, **edge)
    assert tracing.curve_at(blocked, grid)[0] == pytest.approx(1e-3)
    assert tracing.curve_at(spec.Neutral(type="neutral", transmission=0.1), grid)[0] == 0.1
    table = spec.Table(type="table", points=((400.0, 0.0), (500.0, 1.0)))
    assert tracing.curve_at(table, np.array([450.0]))[0] == pytest.approx(0.5)


def test_a_filter_transmits_what_it_states(tmp_path: Path) -> None:
    """A neutral density of a tenth passes a tenth: this used to be ignored."""

    def darker(data: dict[str, Any]) -> None:
        data["cubes"]["filter_green"]["element"]["curve"] = {"type": "neutral", "transmission": 0.1}

    def clear(data: dict[str, Any]) -> None:
        data["cubes"]["filter_green"]["element"]["curve"] = {"type": "neutral", "transmission": 1.0}

    assert electrons(described(tmp_path, darker)) == pytest.approx(
        0.1 * electrons(described(tmp_path, clear))
    )


def test_the_spectrum_covers_what_is_stated(tmp_path: Path) -> None:
    """A near-infrared source is computed, not lost off the end of a fixed range."""

    def infrared(data: dict[str, Any]) -> None:
        data["cubes"]["laser_488"]["element"]["spectrum"] = {"center": "920 nm", "width": "5 nm"}

    grid = tracing.wavelengths(described(tmp_path, infrared))
    assert grid.min() <= 920.0 <= grid.max() and grid[-1] - 920.0 >= 100.0


# --- immersion


def test_an_oil_objective_is_traced(tmp_path: Path) -> None:
    """An NA above 1 works, in a medium, and magnifies as the lenses say."""

    def oil(data: dict[str, Any]) -> None:
        lens(data).update(f="2 mm", na=1.4, immersion="oil")

    instrument = described(tmp_path, oil)
    pixel = abs(
        compile_instrument(instrument)
        .answer("camera_green", instrument.initial_state())
        .pixel_to_stage[0][0]
    )
    assert pixel == pytest.approx(6.5 * 2.0 / 200.0, rel=1e-3)


# --- the sensor


def test_the_readout_makes_the_noise(tmp_path: Path) -> None:
    """In the dark: its offset, and its read noise in counts. Both come from the sensor."""

    def noisy(data: dict[str, Any]) -> None:
        data["cubes"]["camera_green"]["element"]["readout"] = {
            "qe": 0.7,
            "electrons_per_count": 2.0,
            "read_noise": 10.0,
            "offset": 200.0,
            "full_well": 30000,
            "bit_depth": 12,
        }

    microscope = SimulatedMicroscope(described(tmp_path, noisy))
    image = microscope.image("camera_green")
    assert image.mean() == pytest.approx(200.0, abs=0.5)
    assert image.std() == pytest.approx(5.0, abs=0.2)  # 10 electrons, at 2 electrons per count


def test_a_bright_image_stops_at_what_the_sensor_holds(tmp_path: Path) -> None:
    """At its full well and within its bit depth, whichever comes first."""

    def small(data: dict[str, Any]) -> None:
        data["cubes"]["camera_green"]["element"]["readout"] = {
            "qe": 0.7,
            "electrons_per_count": 1.0,
            "read_noise": 0.0,
            "offset": 0.0,
            "full_well": 500,
            "bit_depth": 8,
        }

    microscope = SimulatedMicroscope(described(tmp_path, small))
    microscope.set({"laser_488.power": 50.0})
    image = microscope.image("camera_green")
    assert image.dtype == np.uint8
    assert image.max() == 255


def test_gain_does_not_improve_the_signal_to_noise(tmp_path: Path) -> None:
    """It multiplies what was collected, and the shot noise with it."""
    instrument = described(tmp_path, lambda d: None)
    lit = {"laser_488.power": 5.0}
    plain = SimulatedMicroscope(instrument)
    plain.set(lit)
    boosted = SimulatedMicroscope(instrument)
    boosted.set({**lit, "camera_green.gain": 12.0})
    raised = boosted.image("camera_green").astype(float) - 100.0
    base = plain.image("camera_green").astype(float) - 100.0
    assert raised.max() > 2.5 * base.max()
    bright = base > base.max() / 2
    assert (raised[bright].std() / raised[bright].mean()) == pytest.approx(
        base[bright].std() / base[bright].mean(), rel=0.15
    )


@pytest.mark.parametrize(
    "mount, matrix",
    [
        ({"rotation": "90 deg"}, ((0.0, 0.65), (-0.65, 0.0))),
        ({"flip": "x"}, ((0.65, 0.0), (0.0, -0.65))),
    ],
)
def test_how_a_sensor_is_mounted_is_in_its_map(
    tmp_path: Path, mount: dict[str, Any], matrix: tuple
) -> None:
    """Turned or mirrored, in the map from pixels to the stage."""
    instrument = described(tmp_path, lambda d: d["cubes"]["camera_red"]["element"].update(mount))
    answer = compile_instrument(instrument).answer("camera_red", instrument.initial_state())
    assert np.abs(np.array(answer.pixel_to_stage)) == pytest.approx(
        np.abs(np.array(matrix)), abs=1e-6
    )
