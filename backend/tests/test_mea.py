"""A multi-electrode array: the chip is what the cells are mounted on, and a probe reads it.

Its electrodes are places of the sample, as a plate's wells are: they move with the mount, and a
camera can be brought over one. The cells it records are the beads the camera draws.
"""

from pathlib import Path

import numpy as np
import pytest

from arkitekt import Task

from newswitch.actions.space import mount_holder, move_to
from newswitch.instrument import spec
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import AcquisitionChannel, AcquisitionPlan
from newswitch.models.space import Position
from newswitch.routines.acquire import acquire as run_plan
from tests.conftest import run_settings
from tests.test_acquire import StateStore, sample_of

MEA = Path(__file__).parents[1] / "instruments" / "mea-microscope"
#: Where electrode A1 is on the chip, and how far apart they are, in micrometres.
A1, PITCH = 23_800.0, 200.0


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """The mea-microscope's description."""
    return spec.load(MEA)


@pytest.fixture
def m(tmp_path: Path, instrument: spec.Instrument) -> Microscope:
    """The mea-microscope, simulated."""
    return build_microscope(run_settings(tmp_path, instrument=MEA), instrument)


def electrode(name: str) -> tuple[float, float]:
    """Where an electrode (``D5``) is on the chip: x, y in micrometres."""
    row, column = ord(name[0]) - ord("A"), int(name[1:]) - 1
    return A1 + column * PITCH, A1 + row * PITCH


# --- what it is


def test_a_probe_on_a_grid_has_its_electrodes_and_samples_time(instrument: spec.Instrument) -> None:
    """8 x 8 electrodes 200 um apart, and blocks of 1000 samples, 0.05 ms apart."""
    axes = {
        axis.name: (axis.size, axis.step, axis.domain) for axis in instrument.detector_axes("mea")
    }
    assert axes == {
        "s": (1000, pytest.approx(0.05), "time"),
        "y": (8, pytest.approx(PITCH), "space"),
        "x": (8, pytest.approx(PITCH), "space"),
    }


def test_it_measures_no_light(m: Microscope) -> None:
    """A probe: no image of light, however its electrodes are laid out."""
    mea = m.detector_state.get("mea")
    assert mea.is_probe() and not mea.delivers_images()
    assert (mea.quantity, mea.unit) == ("voltage", "uV")


def test_a_probe_reading_a_grid_no_holder_has_is_refused(tmp_path: Path) -> None:
    """Reading wells of a sample whose holders have none: refused when the description loads."""
    import yaml

    data = yaml.safe_load((MEA / "microscope.yml").read_text())
    data["cubes"]["mea"]["element"]["reads"]["grid"] = "pin"
    folder = tmp_path / "instruments" / "mea"
    folder.mkdir(parents=True)
    (folder / "microscope.yml").write_text(yaml.safe_dump(data))
    (folder / "view.bsx").write_text((MEA / "view.bsx").read_text())
    views = tmp_path / "instruments" / "views"
    views.mkdir()
    for view in (MEA.parent / "views").glob("*.bsx"):
        (views / view.name).write_text(view.read_text())
    with pytest.raises(spec.SpecError, match="no holder of stage has the grid 'pin'"):
        spec.load(folder)


# --- where it is


def test_its_electrodes_are_where_the_chip_has_them(m: Microscope) -> None:
    """Straight onto the sample, not the stage: electrode (column, row) to the chip's micrometres."""
    edges = {(t.input, t.output) for t in m.space_state.transformations}
    assert ("detector:mea", "sample:stage") in edges
    placed = np.array(m.space_state.detectors["mea"].to_sample)
    assert (placed @ [0, 0, 0, 1])[:2] == pytest.approx(electrode("A1"))
    assert (placed @ [4, 3, 0, 1])[:2] == pytest.approx(electrode("D5"))


def test_moving_the_stage_moves_no_electrode(m: Microscope) -> None:
    """The chip goes with the stage: in the sample's frame its electrodes stay where they are."""
    assert m.values is not None
    before = m.space_state.detectors["mea"].to_sample
    m.values.set({"stage.x": 300.0, "stage.y": -120.0})
    assert m.space_state.detectors["mea"].to_sample == before


def test_every_electrode_is_a_place_to_go(m: Microscope) -> None:
    """``electrode:D5`` brings the middle of the camera's image over electrode D5."""
    assert m.values is not None
    move_to(
        m.space, m.values, Task.local(), Position("electrode:D5", {"x": 0.0, "y": 0.0}), "camera"
    )
    middle = m.space.placement("camera") @ np.array([255.5, 255.5, 0.0, 1.0])
    assert middle[:2] == pytest.approx(electrode("D5"), abs=1e-6)


def test_another_holder_has_no_electrodes_to_read(m: Microscope) -> None:
    """On a slide the array reads nothing: it is nowhere, and an acquisition of it is refused."""
    assert m.values is not None
    mount_holder(m.space, m.expanse, "slide")
    assert not m.space.sees("mea")
    edges = {t.input for t in m.space_state.transformations}
    assert "detector:mea" not in edges
    plan = AcquisitionPlan(channels=[AcquisitionChannel(detectors=["mea"])])
    with pytest.raises(spec.Dark, match="mea reads a grid"):
        run_plan(
            plan, StateStore(m), m.optics, m.detector, m.values, m.space, m.hooks, Task.local()
        )


# --- what it records


def expected_pickup(m: Microscope) -> np.ndarray:
    """How strongly each electrode picks up the cells, as the cells and the sample say: (8, 8)."""
    assert m.detector is not None
    simulator = m.detector.simulator  # type: ignore[attr-defined]
    simulation = m.values.instrument.simulation_at(m.values.snapshot(), "stage")  # type: ignore[union-attr]
    y, x, depth = simulator.beads_in_sample(simulation.pattern, "stage")
    rows = A1 + np.arange(8) * PITCH
    distance = np.sqrt(
        (y[:, None, None] - rows[None, :, None]) ** 2
        + (x[:, None, None] - rows[None, None, :]) ** 2
        + depth[:, None, None] ** 2
    )
    return np.exp(-distance / simulation.electrical.reach).sum(axis=0)


def test_the_electrodes_near_cells_the_camera_sees_swing_most(m: Microscope) -> None:
    """Over a second, the electrode with the most cells near it swings well above the one with
    the fewest, which swings like its noise."""
    assert m.detector is not None
    pickup = expected_pickup(m)
    strong = np.unravel_index(pickup.argmax(), pickup.shape)
    weak = np.unravel_index(pickup.argmin(), pickup.shape)
    simulator = m.detector.simulator  # type: ignore[attr-defined]
    blocks = [simulator.potentials("mea", k * 0.05, m.values.snapshot()) for k in range(20)]  # type: ignore[union-attr]
    swing = np.mean([(b.max(axis=0) - b.min(axis=0)) for b in blocks], axis=0)
    assert swing[strong] > 2 * swing[weak]


def test_a_block_is_the_same_however_often_it_is_read(m: Microscope) -> None:
    """Seeded by when it is: the same instant, the same voltages."""
    assert m.detector is not None and m.values is not None
    simulator = m.detector.simulator  # type: ignore[attr-defined]
    one = simulator.potentials("mea", 1.0, m.values.snapshot())
    assert np.array_equal(one, simulator.potentials("mea", 1.0, m.values.snapshot()))
    assert not np.array_equal(one, simulator.potentials("mea", 1.05, m.values.snapshot()))


def test_an_acquisition_records_its_electrodes_on_the_sample(m: Microscope) -> None:
    """A record of its own, (t, c, s, plane, z, y, x), its electrodes where the chip has them."""
    assert m.values is not None
    plan = AcquisitionPlan(
        channels=[
            AcquisitionChannel(
                name="gfp", detectors=["camera", "mea"], set_to={"laser_488.power": 20.0}
            )
        ]
    )
    camera, mea = _acquire(m, plan)
    assert mea.data.shape == (1, 1, 1000, 1, 1, 8, 8)
    assert mea.unit == "uV"
    d5 = sample_of(mea, x=4.0, y=3.0, z=0.0)
    assert (d5["x"], d5["y"]) == pytest.approx(electrode("D5"))
    assert camera.data.shape[-2:] == (512, 512)


def _acquire(m: Microscope, plan: AcquisitionPlan) -> list:
    store = StateStore(m)
    run_plan(plan, store, m.optics, m.detector, m.values, m.space, m.hooks, Task.local())  # type: ignore[arg-type]
    return store.published
