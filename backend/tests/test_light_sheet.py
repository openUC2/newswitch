"""A light sheet: lit from the side, seen by a camera, and stepped by the camera's own frames."""

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from arkitekt import Task

from newswitch.drivers.simulator import SimulatedMicroscope, _add_blurred, _beads
from newswitch.instrument import spec
from newswitch.instrument.compiler import compile_instrument, impacts
from newswitch.instrument.predict import Compiled
from newswitch.instrument.roles import Roles
from newswitch.microscope.parts import build_microscope
from newswitch.models.acquisition import (
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    AcquisitionStack,
)
from newswitch.routines.acquire import acquire as run_plan
from newswitch.routines.autofocus import run_autofocus
from newswitch.states.autofocus import AutofocusState
from newswitch.instrument.tracing import coupling
from newswitch.routines.affine_matrix import calibrate_pixel_to_stage
from newswitch.tools.check_instrument import _stage_moves
from tests.conftest import acquisition, run_settings
from tests.test_acquire import RecordingStore, sample_of

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
    sheet = table.answer("camera", instrument.initial_state()).sheet_by_source["laser_488"]
    waist = 0.488 / (math.pi * 0.02)
    assert sheet["waist_um"] == pytest.approx(waist)
    assert sheet["rayleigh_um"] == pytest.approx(math.pi * waist**2 / 0.488)
    assert sheet["along"] == "x"


def test_its_only_channel_is_fluorescence(instrument: spec.Instrument, table: Compiled) -> None:
    """Across the camera's view no light reaches it directly, however much the sample lets through."""
    state = instrument.initial_state()
    channel = table.channels(state)[0]
    assert (channel.source, channel.detector) == ("laser_488", "camera")
    assert channel.band_nm == pytest.approx(517.0, abs=2.0)
    assert table.channels({**state, "stage.simulation": "empty-slide"}) == []


def test_a_sample_leaving_the_sheet_goes_dark(instrument: spec.Instrument, table: Compiled) -> None:
    """At the rate its waist says."""
    state = {**instrument.initial_state(), "stage.simulation": "gfp-section"}
    at_focus = table.answer("camera", state).light
    moved = table.answer("camera", {**state, "stage.z": 5.0}).light
    waist = 0.488 / (math.pi * 0.02)
    # 4 um deep, so its nearest part has gone 3 um.
    assert moved / at_focus == pytest.approx(math.exp(-2.0 * (3.0 / waist) ** 2))


def test_the_stage_moving_the_light_is_calculated(table: Compiled) -> None:
    """What impacts what comes out of the optics: nothing declares it."""
    changes = next(
        row["changes"]
        for row in impacts(
            table.instrument,
            {**table.instrument.initial_state(), "stage.simulation": "gfp-section"},
        )
        if row["variable"] == "stage.z" and row["detector"] == "camera"
    )
    assert "light" in changes


def test_the_image_fades_along_the_sheet_not_across_it(instrument: spec.Instrument) -> None:
    """On an even slide: the two edges are equally far from the middle, so only the sheet differs."""
    answer = compile_instrument(instrument).answer("camera", instrument.initial_state())
    half = answer.field_of_view_um[0] / 2.0
    rayleigh = answer.sheet_by_source["laser_488"]["rayleigh_um"]
    expected = 1.0 / math.sqrt(1.0 + (half / rayleigh) ** 2)
    assert expected < 0.95  # it has to be visible for this to mean anything

    microscope = SimulatedMicroscope(instrument)
    microscope.simulator._slice = lambda *_: np.ones((512, 512))
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
        (lambda d: d["cubes"]["sheet_lens"]["element"].pop("na"), "a sheet comes from a lens"),
        (
            lambda d: (
                d["cubes"].update(
                    {
                        "other": {
                            "element": {"kind": "lens", "f": "50 mm", "na": 0.1, "immersion": "air"}
                        }
                    }
                ),
                d["illumination"].extend(
                    [
                        {"from": "laser_488", "to": "other"},
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
    assert "sheet" in arriving["laser_488"]
    other = spec.load(INSTRUMENT.parent / "dual-camera")
    arriving = coupling(other, "camera_green", other.initial_state())
    assert all("sheet" not in entry for entry in arriving.values())


# --- two things move along z: the sheet, and the stage


def single_bead(tmp_path: Path, deep: str = "1 um") -> spec.Instrument:
    """One bead in a small field of view, to follow."""

    def change(data: dict[str, Any]) -> None:
        simulation = data["cubes"]["stage"]["element"]["simulations"]["gfp-beads"]
        simulation["pattern"] = {"beads": 1, "radius": "1 um", "depth": deep, "extent": "0.1 mm"}

    return spec.load(edited(tmp_path, change))


def lit_at(microscope: SimulatedMicroscope, stage: float, sheet: float) -> np.ndarray:
    """An image without its offset, with the stage and the sheet there."""
    microscope.set({"stage.z": stage, "sheet_lens.z": sheet, "laser_488.power": 5.0})
    return microscope.image("camera").astype(float) - 100.0


def sharpness(image: np.ndarray) -> float:
    """How much the image changes from pixel to pixel, for what it has of light."""
    return float(np.abs(np.diff(image, axis=0)).mean() / max(image.clip(min=0).mean(), 1.0))


def correlation(one: np.ndarray, other: np.ndarray) -> float:
    """How alike two images are."""
    return float(np.corrcoef(one.ravel(), other.ravel())[0, 1])


def test_in_a_volume_the_sheet_focuses_and_the_stage_goes_through(
    instrument: spec.Instrument,
) -> None:
    """Found by moving them: nothing says so."""
    roles = Roles(instrument)
    assert sorted(roles.found["camera"]["sheet_lens.z"]) == ["blur"]
    assert sorted(roles.found["camera"]["stage.z"]) == []
    assert [move.name for move in roles.focuses("camera")] == ["sheet_lens.z"]


def test_in_a_thin_section_the_stage_focuses(tmp_path: Path) -> None:
    """The same law: the sheet can only miss it, and it is the section that leaves focus."""

    def change(data: dict[str, Any]) -> None:
        data["cubes"]["stage"]["element"]["simulation"] = "gfp-section"

    roles = Roles(spec.load(edited(tmp_path, change)))
    assert {"blur", "light"} <= set(roles.found["camera"]["stage.z"])
    assert sorted(roles.found["camera"]["sheet_lens.z"]) == ["light"]
    assert [move.name for move in roles.focuses("camera")] == ["stage.z"]


def test_moving_either_lights_other_beads(instrument: spec.Instrument) -> None:
    """A step well under the sheet's waist shows much the same; well over it, others."""
    microscope = SimulatedMicroscope(instrument)
    here = lit_at(microscope, 0.0, 0.0)
    assert correlation(here, lit_at(microscope, 0.0, 1.0)) > 0.8
    assert correlation(here, lit_at(microscope, 0.0, 40.0)) < 0.3
    assert correlation(here, lit_at(microscope, 40.0, 0.0)) < 0.3


def test_the_stage_keeps_it_sharp_and_the_sheet_does_not(instrument: spec.Instrument) -> None:
    """Whatever the stage carries into the sheet is as far from focus as the sheet is."""
    microscope = SimulatedMicroscope(instrument)
    focused = sharpness(lit_at(microscope, 0.0, 0.0))
    assert sharpness(lit_at(microscope, 60.0, 0.0)) == pytest.approx(focused, rel=0.5)
    assert sharpness(lit_at(microscope, 0.0, 40.0)) < focused / 2.0
    assert sharpness(lit_at(microscope, 40.0, 40.0)) < focused / 2.0


def test_out_of_focus_a_bead_spreads_its_light_and_keeps_it(tmp_path: Path) -> None:
    """Dimmer for being wider: how much it gives is what the sheet gave it."""
    microscope = SimulatedMicroscope(single_bead(tmp_path))
    focused = lit_at(microscope, 0.0, 0.0)
    spread = lit_at(microscope, 20.0, 20.0)
    assert spread.max() < focused.max() / 4.0
    assert spread.sum() == pytest.approx(focused.sum(), rel=0.1)


def test_far_out_of_focus_a_bead_is_drawn_as_it_would_be_near(tmp_path: Path) -> None:
    """Blurred with others of about its width, it keeps its light and its place."""
    instrument = single_bead(tmp_path)
    simulator = SimulatedMicroscope(instrument).simulator
    state = {**instrument.initial_state(), "laser_488.power": 5.0, "stage.z": 100.0}
    state["sheet_lens.z"] = 100.0
    answer = simulator._answer("camera", state)
    pattern = instrument.simulation_at(state, "stage").pattern
    field = simulator._slice("camera", state, answer, pattern)

    y, x, depth = _beads(pattern)
    to_sample = np.array(answer.pixel_to_stage)
    columns, rows = np.linalg.inv(to_sample) @ np.stack(
        [x - answer.centre[0], y - answer.centre[1]]
    )
    pixel_um = abs(to_sample[0, 0])
    grown = pattern.radius / pixel_um
    sigma = float(np.hypot(grown, answer.blur_px_per_um * (depth[0] + 100.0)))
    lit = math.exp(-2.0 * (depth[0] / answer.sheet_by_source["laser_488"]["waist_um"]) ** 2)
    across, down = np.meshgrid(np.arange(512.0), np.arange(512.0))
    expected = (
        lit
        * (grown / sigma) ** 2
        * np.exp(
            -0.5
            * (
                ((across - columns[0] - 255.5) / sigma) ** 2
                + ((down - rows[0] - 255.5) / sigma) ** 2
            )
        )
    )
    assert field.sum() == pytest.approx(expected.sum(), rel=0.05)
    assert np.abs(field - expected).max() < 0.1 * expected.max()


def test_blurring_beads_together_changes_nothing_a_focus_metric_can_see(tmp_path: Path) -> None:
    """Width by width the image changes smoothly, or the steps would look like focus."""
    columns, rows = np.full(3, 256.0), np.full(3, 256.0)
    brightness = np.ones(3)

    def peak(sigma: float) -> float:
        field = np.zeros((512, 512))
        _add_blurred(field, columns[:1], rows[:1], np.array([sigma]), brightness[:1])
        return float(field.max())

    widths = np.linspace(20.0, 40.0, 81)
    peaks = np.array([peak(float(width)) for width in widths])
    # A peak of one is what a bead of that brightness has, whichever groups it fell between.
    assert np.abs(peaks - 1.0).max() < 0.05
    assert np.abs(np.diff(peaks)).max() < 0.01


def test_the_frames_step_the_sheet_and_leave_the_stage(tmp_path: Path) -> None:
    """A stack is one sweep of what the wire reaches, and its planes are other slices."""
    m = build_microscope(run_settings(tmp_path), spec.load(INSTRUMENT))
    channel = AcquisitionChannel(detectors=["camera"], name="gfp", set_to={"laser_488.power": 5.0})
    store = RecordingStore()
    planes = [float(index) * 0.5 for index in range(-40, 41)]
    run_plan(
        acquisition([channel], planes=planes),
        store,
        m.optics,
        m.detector,
        m.values,
        m.space,
        m.hooks,
        Task.local(),
    )
    assert m.values["stage.z"] == 0.0
    assert m.values["sheet_lens.z"] == 20.0
    data = store.published[0].data.astype(float)[0, 0]
    assert correlation(data[0], data[-1]) < 0.5


def test_a_bead_is_at_the_same_z_whichever_swept(tmp_path: Path) -> None:
    """A stack through the sheet has the same depth axis as one by the stage, turned over."""

    def peak(variable: str | None, folder: str) -> float:
        instrument = single_bead(tmp_path / folder, "30 um")
        m = build_microscope(run_settings(tmp_path / folder), instrument)
        channel = AcquisitionChannel(
            detectors=["camera"], name="gfp", set_to={"laser_488.power": 5.0}
        )
        store = RecordingStore()
        plan = AcquisitionPlan(
            channels=[channel],
            positions=[AcquisitionPosition(set_to={"stage.z": 0.0})],
            stack=AcquisitionStack(
                offsets=[float(index) * 0.5 for index in range(-60, 61)], variable=variable
            ),
        )
        run_plan(plan, store, m.optics, m.detector, m.values, m.space, m.hooks, Task.local())
        published = store.published[0]
        lit = (published.data.astype(float)[0, 0] - 100.0).clip(min=0).sum(axis=(1, 2))
        return sample_of(published, z=float(lit.argmax()), y=0.0, x=0.0)["z"]

    (tmp_path / "wired").mkdir()
    (tmp_path / "moved").mkdir()
    assert peak(None, "wired") == pytest.approx(peak("stage.z", "moved"), abs=2.0)


def test_autofocus_brings_the_sheet_to_the_focus_of_the_objective(tmp_path: Path) -> None:
    """Named by nothing: it is what focuses, and it is left where a plane is sharpest."""
    m = build_microscope(run_settings(tmp_path), spec.load(INSTRUMENT))
    m.values.set({"laser_488.power": 5.0, "sheet_lens.z": 12.0})
    found = run_autofocus(
        m.values,
        m.detector,
        AutofocusState(),
        m.optics,
        Task.local(),
        z_range=30.0,
        steps=31,
        detector_name="camera",
    )
    assert abs(found) <= 5.0
    assert m.values["sheet_lens.z"] == found
    assert m.values["stage.z"] == 0.0


def test_what_is_published_says_which_plane_is_seen(tmp_path: Path) -> None:
    """In the sample, whichever moved: the same z a dataset records for it."""
    m = build_microscope(run_settings(tmp_path), spec.load(INSTRUMENT))
    m.values.set({"stage.z": 50.0})
    assert m.optics_state.detectors["camera"].plane_um == pytest.approx(50.0)
    m.values.set({"sheet_lens.z": 15.0})
    assert m.optics_state.detectors["camera"].plane_um == pytest.approx(35.0)
