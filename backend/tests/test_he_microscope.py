"""A standard H&E microscope: white light, a thin stained section, and a color camera."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from arkitekt import Task

from newswitch.drivers.simulator import SimulatedMicroscope
from newswitch.instrument import spec
from newswitch.instrument.roles import Roles
from newswitch.microscope.parts import build_microscope
from newswitch.models.acquisition import AcquisitionChannel
from newswitch.routines.acquire import acquire as run_plan
from tests.conftest import acquisition, run_settings
from tests.test_acquire import RecordingStore

INSTRUMENT = Path(__file__).parent.parent / "instruments" / "he-microscope"


@pytest.fixture(scope="module")
def microscope() -> SimulatedMicroscope:
    """It, simulated."""
    return SimulatedMicroscope(spec.load(INSTRUMENT))


@pytest.fixture
def colors(microscope: SimulatedMicroscope) -> dict[str, np.ndarray]:
    """One exposure of it, per color, without the offset."""
    microscope.set({"stage.z": 0.0, "objective.slot": 1})
    rendered = microscope.simulator.render_colors("camera", microscope.state)
    return {name: image.astype(float) - 100.0 for name, image in rendered.items()}


def test_it_is_a_thin_section_the_stage_focuses(microscope: SimulatedMicroscope) -> None:
    """Thin, so that it leaves focus as a whole."""
    assert microscope.simulator.instrument.simulation_at(microscope.state).pattern.depth == 4.0
    roles = Roles(microscope.simulator.instrument)
    assert [move.name for move in roles.focuses("camera")] == ["stage.z"]


def test_nothing_on_the_slide_is_about_white(microscope: SimulatedMicroscope) -> None:
    """Without stains the three bands are about as bright: the light is white."""
    state = {**microscope.state, "stage.simulation": "empty-slide"}
    rendered = microscope.simulator.render_colors("camera", state)
    means = [float(image.astype(float).mean() - 100.0) for image in rendered.values()]
    assert max(means) / min(means) < 1.3


def test_what_is_stained_is_pink_with_blue_purple_nuclei(colors: dict[str, np.ndarray]) -> None:
    """Eosin takes the green, and hematoxylin the red and the green but less of the blue."""
    red, green, blue = colors["r"], colors["g"], colors["b"]
    tissue = np.median(np.stack([red, green, blue]), axis=(1, 2))
    assert tissue[0] > tissue[1] and tissue[2] > tissue[1]  # more red and blue than green: pink
    nuclei = red < np.percentile(red, 5)
    assert blue[nuclei].mean() > red[nuclei].mean()


def test_the_stains_show_where_they_are_and_only_there(colors: dict[str, np.ndarray]) -> None:
    """The section has structure, or calibrating and focusing would have nothing to go by."""
    assert colors["r"].std() / colors["r"].mean() > 0.1


def test_the_other_objective_magnifies_and_out_of_focus_blurs(
    microscope: SimulatedMicroscope,
) -> None:
    """Through the stains as through anything: nothing fluoresces here."""

    def detail(image: np.ndarray) -> float:
        return float(np.abs(np.diff(image.astype(float), axis=0)).mean())

    table = microscope.simulator._table
    state = {**microscope.state, "stage.z": 0.0, "objective.slot": 1}
    low = table.answer("camera", state)
    high = table.answer("camera", {**state, "objective.slot": 2})
    assert abs(high.pixel_to_stage[0][0]) == pytest.approx(abs(low.pixel_to_stage[0][0]) / 2.0)
    sharp = microscope.simulator.render_colors("camera", state)["r"]
    blurred = microscope.simulator.render_colors("camera", {**state, "stage.z": 40.0})["r"]
    assert np.ptp(blurred.astype(float)) < np.ptp(sharp.astype(float))
    assert detail(blurred) <= detail(sharp)


def test_an_acquisition_has_a_channel_per_color(tmp_path: Path) -> None:
    """In the order the camera states them, each with its stains in it."""
    m = build_microscope(run_settings(tmp_path), spec.load(INSTRUMENT))
    channel = AcquisitionChannel(
        detectors=["camera"], name="he", set_to={"white_led.power": m.values["white_led.power"]}
    )
    store = RecordingStore()
    run_plan(acquisition([channel]), store, m.optics, m.detector, m.values, m.hooks, Task.local())
    data = store.published[0].data
    assert data.shape[1] == 3
    assert data[0, 0].astype(float).mean() != data[0, 1].astype(float).mean()
