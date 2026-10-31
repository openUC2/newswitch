"""A light sheet: lit from the side, seen by a camera, and stepped by the camera's own frames."""

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from newswitch.drivers.optics.simulator import SimulatedMicroscope
from newswitch.instrument import spec
from newswitch.instrument.compiler import compile_instrument, impacts
from newswitch.instrument.predict import Compiled
from newswitch.instrument.tracing import coupling
from newswitch.routines.affine_matrix import calibrate_pixel_to_stage
from newswitch.tools.check_instrument import _stage_moves

INSTRUMENT = Path(__file__).parent.parent / "instruments" / "light-sheet"


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """The light sheet as described."""
    return spec.load(INSTRUMENT)


@pytest.fixture(scope="module")
def table(instrument: spec.Instrument) -> Compiled:
    """What is compiled for it."""
    return compile_instrument(instrument)


def edited(tmp_path: Path, change: Callable[[dict[str, Any]], Any]) -> Path:
    """The light sheet's description with `change` made to it."""
    data = yaml.safe_load((INSTRUMENT / spec.DESCRIPTION).read_text())
    change(data)
    path = tmp_path / spec.DESCRIPTION
    path.write_text(yaml.safe_dump(data))
    return path


def test_its_thickness_and_reach_come_from_the_lens(
    instrument: spec.Instrument, table: Compiled
) -> None:
    """A Gaussian beam: nothing states them."""
    sheet = table.answer("camera", instrument.initial_state()).sheet_by_source["laser-488"]
    waist = 0.488 / (math.pi * 0.02)
    assert sheet["waist_um"] == pytest.approx(waist)
    assert sheet["rayleigh_um"] == pytest.approx(math.pi * waist**2 / 0.488)
    assert sheet["along"] == "x"


def test_its_only_channel_is_fluorescence(instrument: spec.Instrument, table: Compiled) -> None:
    """Across the camera's view no light reaches it directly, however much the sample lets through."""
    state = instrument.initial_state()
    channel = table.channels(state)[0]
    assert (channel.source, channel.detector) == ("laser-488", "camera")
    assert channel.band_nm == pytest.approx(517.0, abs=2.0)
    assert table.channels({**state, "stage.simulation": "empty-slide"}) == []


def test_a_sample_leaving_the_sheet_goes_dark(instrument: spec.Instrument, table: Compiled) -> None:
    """At the rate its waist says."""
    state = instrument.initial_state()
    at_focus = table.answer("camera", state).light
    moved = table.answer("camera", {**state, "stage.z": 5.0}).light
    waist = 0.488 / (math.pi * 0.02)
    assert moved / at_focus == pytest.approx(math.exp(-2.0 * (5.0 / waist) ** 2))


def test_the_stage_moving_the_light_is_calculated(table: Compiled) -> None:
    """What impacts what comes out of the optics: nothing declares it."""
    changes = next(
        row["changes"]
        for row in impacts(table.instrument, table.instrument.initial_state())
        if row["variable"] == "stage.z" and row["detector"] == "camera"
    )
    assert "light" in changes


def test_the_image_fades_along_the_sheet_not_across_it(instrument: spec.Instrument) -> None:
    """On an even slide: the two edges are equally far from the middle, so only the sheet differs."""
    answer = compile_instrument(instrument).answer("camera", instrument.initial_state())
    half = answer.field_of_view_um[0] / 2.0
    rayleigh = answer.sheet_by_source["laser-488"]["rayleigh_um"]
    expected = 1.0 / math.sqrt(1.0 + (half / rayleigh) ** 2)
    assert expected < 0.95  # it has to be visible for this to mean anything

    microscope = SimulatedMicroscope(instrument)
    pattern = instrument.simulation_at(microscope.state).pattern
    microscope.simulator._sample_images[pattern] = np.ones((3000, 3000), dtype=np.float32)
    image = microscope.image("camera").astype(float) - 100.0
    along_edge = image[246:266, :4].mean()
    across_edge = image[:4, 246:266].mean()
    assert along_edge / across_edge == pytest.approx(expected, rel=0.01)


def test_calibrating_finds_the_predicted_pixel(
    instrument: spec.Instrument, table: Compiled
) -> None:
    """The camera is a camera: only the lighting differs. A move this field's few beads can follow."""
    microscope = SimulatedMicroscope(instrument)
    step = 50.0
    frames = _stage_moves(microscope, "camera", step)
    matrix = np.array(calibrate_pixel_to_stage(*frames, step, step))
    predicted = abs(table.answer("camera", microscope.state).pixel_to_stage[0][0])
    assert math.hypot(matrix[0, 0], matrix[1, 0]) == pytest.approx(predicted, rel=0.01)


@pytest.mark.parametrize(
    "change, finding",
    [
        (lambda d: d["illumination"][1].pop("along"), "a sheet has side: orthogonal"),
        (lambda d: d["illumination"][1].pop("side"), "a sheet has side: orthogonal"),
        (lambda d: d["illumination"][1].update(along="z"), "along"),
        (lambda d: d["cubes"]["sheet-lens"]["element"].pop("na"), "a sheet comes from a lens"),
        (
            lambda d: (
                d["cubes"].update({"other": {"element": {"kind": "lens", "f": 50.0, "na": 0.1}}}),
                d["illumination"].extend(
                    [
                        {"from": "laser-488", "to": "other"},
                        {"from": "other", "to": "stage", "side": "orthogonal", "along": "y"},
                    ]
                ),
            ),
            "one sheet per source",
        ),
    ],
)
def test_a_sheet_that_cannot_work_is_refused_when_parsed(
    tmp_path: Path, change: Callable[[dict[str, Any]], Any], finding: str
) -> None:
    """Naming what is missing."""
    with pytest.raises(spec.SpecError, match=finding):
        spec.load(edited(tmp_path, change))


def test_a_sheet_is_in_the_table_only_where_there_is_one(instrument: spec.Instrument) -> None:
    """Every other instrument's table stays as it was."""
    arriving = coupling(instrument, "camera", instrument.initial_state())
    assert "sheet" in arriving["laser-488"]
    other = spec.load(INSTRUMENT.parent / "dual-camera")
    arriving = coupling(other, "camera-green", other.initial_state())
    assert all("sheet" not in entry for entry in arriving.values())
