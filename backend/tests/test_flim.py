"""FLIM: a detector with one axis more, when each photon arrives after its pulse."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr
import yaml
from mikro import dataset_arrays
from mikro.api import schema

from newswitch.drivers.optics.simulator import SimulatedMicroscope
from newswitch.instrument import spec
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import StreamIllumination, Streams
from newswitch.services.mikro_store import AXES, MICROTIME_AXES, _dataset_axes, _optical_element
from tests.conftest import run_settings
from tests.test_multidimensional_acquisition import acquire, plan

INSTRUMENT = Path(__file__).parent.parent / "instruments" / "flim"


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """The FLIM microscope as described."""
    return spec.load(INSTRUMENT)


@pytest.fixture
def microscope(tmp_path: Path, instrument: spec.Instrument) -> Microscope:
    """The FLIM microscope on a server."""
    return build_microscope(run_settings(tmp_path), instrument)


def stream() -> Streams:
    """The laser for the detector."""
    return Streams(
        detectors=["spad"],
        illuminations=[StreamIllumination(source="laser_488", wavelength=488.0, intensity=1.0)],
    )


def edited(tmp_path: Path, change: Callable[[dict[str, Any]], Any]) -> Path:
    """The FLIM description with `change` made to it."""
    data = yaml.safe_load((INSTRUMENT / spec.DESCRIPTION).read_text())
    change(data)
    path = tmp_path / spec.DESCRIPTION
    path.write_text(yaml.safe_dump(data))
    return path


def fluorophore(data: dict[str, Any]) -> dict[str, Any]:
    """What the description says of the sample's fluorophore."""
    simulations = data["cubes"]["stage"]["element"]["simulations"]
    return simulations["gfp-beads"]["fluorophore"]


def test_the_detector_delivers_arrival_time(instrument: spec.Instrument) -> None:
    """From itself, on top of what the scan delivers."""
    m, y, x = instrument.detector_axes("spad")
    assert (m.name, m.size, m.step, m.delivered_by) == ("m", 64, 200.0, "spad")
    assert (y.delivered_by, x.delivered_by) == ("galvo", "galvo")


def test_the_stated_lifetime_can_be_fitted_back(instrument: spec.Instrument) -> None:
    """From the simulated histogram alone."""
    simulated = SimulatedMicroscope(instrument)
    simulated.set({"laser_488.power": 5.0})
    histogram = simulated.simulator.render_microtime("spad", simulated.state)
    assert histogram.shape == (64, 512, 512)
    decay = histogram.sum(axis=(1, 2)).astype(float)
    times = np.arange(64) * 0.2
    slope = np.polyfit(times[:25], np.log(decay[:25]), 1)[0]
    assert -1.0 / slope == pytest.approx(2.5, rel=0.03)


def test_a_counting_detector_has_no_offset(instrument: spec.Instrument) -> None:
    """In the dark there is nothing to count."""
    simulated = SimulatedMicroscope(instrument)
    assert simulated.simulator.render_microtime("spad", simulated.state).max() == 0


@pytest.mark.parametrize(
    "change, finding",
    [
        (lambda d: d["drives"].pop(1), "need one wire to its sync, not 0"),
        (lambda d: d["cubes"]["laser_488"]["element"].pop("repetition"), "needs a repetition"),
        (
            lambda d: d["cubes"]["laser_488"]["element"].update(repetition="100 MHz"),
            "does not fit in a pulse period of 10000 ps",
        ),
        (lambda d: fluorophore(d).pop("lifetime"), "needs its fluorophore's lifetime"),
        (lambda d: fluorophore(d).update(lifetime="3 mm"), "lifetime"),
        (lambda d: d["cubes"]["laser_488"]["signals"].pop("out"), "sends no signal 'sync'"),
    ],
)
def test_flim_that_cannot_work_is_refused_when_parsed(
    tmp_path: Path, change: Callable[[dict[str, Any]], Any], finding: str
) -> None:
    """Naming what is missing."""
    with pytest.raises(spec.SpecError, match=finding):
        spec.load(edited(tmp_path, change))


def test_what_expects_one_image_gets_one(microscope: Microscope) -> None:
    """The live view and an autofocus see the photons per pixel."""
    assert microscope.detector is not None
    microscope.detector.activate_detector(1)
    assert microscope.detector.capture_image(1).data.shape == (512, 512)
    assert microscope.detector.capture_channels(1).shape == (1, 64, 512, 512)


def test_an_acquisition_has_the_arrival_time_axis(microscope: Microscope) -> None:
    """As ``(t, c, m, z, y, x)``, every plane in its place."""
    acquired = acquire(microscope, plan([stream()], planes=[0.0, 5.0])).published[0]
    assert acquired.data.shape == (1, 1, 64, 2, 512, 512)
    assert acquired.data[0, 0, :, 0].sum() > 0
    assert acquired.data[0, 0, :, 1].sum() > 0
    assert acquired.data[0, 0, 0].sum() > acquired.data[0, 0, 40].sum()


def test_it_is_a_microtime_axis_for_mikro(
    microscope: Microscope, instrument: spec.Instrument
) -> None:
    """Declared with its type, in mikro's order, and a pyramid can be made of it."""
    acquired = acquire(microscope, plan([stream()])).published[0]
    names, axes, types = _dataset_axes(instrument, acquired)
    assert names == MICROTIME_AXES
    declared = axes[names.index("m")]
    assert declared.type == schema.AxisType.MICROTIME
    assert "200 ps" in declared.description
    level_zero, _ = dataset_arrays(
        xr.DataArray(acquired.data, dims=names), levels=1, method="mean", types=types
    )
    assert level_zero.sizes["m"] == 64


def test_other_datasets_keep_their_axes(tmp_path: Path) -> None:
    """Nothing declared, nothing new."""
    instrument = spec.load(INSTRUMENT.parent / "dual-camera")
    m = build_microscope(run_settings(tmp_path), instrument)
    streams = [
        Streams(
            detectors=["camera_green"],
            illuminations=[StreamIllumination(source="laser_488", wavelength=488.0, intensity=1.0)],
        )
    ]
    acquired = acquire(m, plan(streams)).published[0]
    assert _dataset_axes(instrument, acquired) == (AXES, list(AXES), {})


def test_the_new_elements_are_mikros_elements(instrument: spec.Instrument) -> None:
    """In the light graph of what was acquired."""
    state = instrument.initial_state()
    assert isinstance(_optical_element(instrument, "spad", state), schema.DetectorElementInput)
    assert isinstance(_optical_element(instrument, "pinhole", state), schema.PinholeElementInput)
    assert isinstance(_optical_element(instrument, "galvo", state), schema.MirrorElementInput)


def test_detectors_with_and_without_arrival_times_cannot_share_a_dataset(tmp_path: Path) -> None:
    """Refused before anything moves."""

    def change(data: dict[str, Any]) -> None:
        data["cubes"]["pmt"] = {
            "component": "generic-pmt",
            "tunes": data["cubes"]["spad"]["tunes"],
        }
        data["detection"].append({"from": "pinhole", "to": "pmt"})
        data["drives"].append({"from": "galvo.pixel", "to": "pmt.sample"})
        data["parts"]["detectors"][2] = {"cube": "pmt", "frame_rate": "1 Hz"}

    m = build_microscope(run_settings(tmp_path), spec.load(edited(tmp_path, change)))
    assert m.stage is not None
    moved_from = (m.stage_state.x, m.stage_state.y, m.stage_state.z)
    both = Streams(
        detectors=["spad", "pmt"],
        illuminations=[StreamIllumination(source="laser_488", wavelength=488.0, intensity=1.0)],
    )
    with pytest.raises(ValueError, match="arrival-time bins"):
        acquire(m, plan([both]))
    assert (m.stage_state.x, m.stage_state.y, m.stage_state.z) == moved_from
