"""Two samples, each on a stage of its own, each seen through a light path of its own.

What one camera sees is its own sample, moved by its own stage; nothing of the other leaks in.
"""

from pathlib import Path

import numpy as np
import pytest

from arkitekt import Task

from newswitch.actions.space import mount_holder, move_to
from newswitch.instrument import spec
from newswitch.instrument.predict import state_key
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import (
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    AcquisitionStack,
)
from newswitch.models.space import Position
from newswitch.routines.acquire import acquire as run_plan
from tests.conftest import run_settings
from tests.test_acquire import RecordingStore, StateStore, sample_of
from tests.test_space import AWAY, bead_misses, on_beads, placed_by_metadata

DUAL = Path(__file__).parents[1] / "instruments" / "dual-sample"
#: The middle of a 75 x 25 mm slide, in its sample's micrometres (from its corner).
MIDDLE = (37_500.0, 12_500.0)


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """The dual-sample description."""
    return spec.load(DUAL)


@pytest.fixture
def m(tmp_path: Path, instrument: spec.Instrument) -> Microscope:
    """The dual-sample microscope, simulated."""
    return build_microscope(run_settings(tmp_path, instrument=DUAL), instrument)


def at_sample(x: float, y: float) -> Position:
    """A point of "the sample": whichever one is meant by what looks at it."""
    return Position("sample", {"x": x, "y": y})


def image(m: Microscope, camera: str) -> np.ndarray:
    """What `camera` sees now."""
    assert m.detector is not None
    m.detector.activate_detector(camera)
    return m.detector.capture_image(camera).data.astype(float)


# --- the description


def test_it_has_two_samples_each_seen_by_its_own_camera(instrument: spec.Instrument) -> None:
    """Every light detector is reached from one sample; a thermometer is where it says it sits."""
    assert instrument.samples() == ["stage_a", "stage_b"]
    state = instrument.initial_state()
    assert instrument.sample_of("cam_a", state) == "stage_a"
    assert instrument.sample_of("cam_b", state) == "stage_b"
    assert instrument.sample_of("thermometer", state) == "stage_b"
    assert instrument.samples_of("cam_b") == ["stage_b"]
    assert instrument.sample_holder("stage_b").simulation == "he-section"


def test_each_sample_says_what_is_on_it(instrument: spec.Instrument) -> None:
    """The simulator keeps what is on each, apart; the state, and what the optics compile, hold
    the variables alone."""
    from newswitch.simulation.simulator import Simulator

    simulator = Simulator(instrument)
    assert simulator.on == {"stage_a": "gfp-beads", "stage_b": "he-section"}
    state = instrument.initial_state()
    assert not any(name.endswith(".simulation") for name in state)
    assert state_key(instrument, state) == state_key(instrument, instrument.initial_state())


# --- what each camera sees


def test_each_stage_moves_its_own_cameras_image(m: Microscope) -> None:
    """Which move shifts a camera's image is found from its own light path."""
    assert m.values is not None
    assert m.values.roles.x("cam_a").name == "stage_a.x"
    assert m.values.roles.x("cam_b").name == "stage_b.x"
    assert m.values.roles.focus("cam_b").name == "stage_b.z"


def test_moving_one_stage_leaves_the_other_cameras_image_alone(m: Microscope) -> None:
    """stage_b moves: cam_b sees elsewhere, cam_a sees exactly what it saw."""
    assert m.values is not None
    m.values.set({"laser_488.power": 20.0})
    a_before, b_before = image(m, "cam_a"), image(m, "cam_b")
    m.values.set({"stage_b.x": 400.0})
    a_after, b_after = image(m, "cam_a"), image(m, "cam_b")
    # The simulated read noise differs from frame to frame: the same scene correlates fully.
    assert np.corrcoef(a_before.ravel(), a_after.ravel())[0, 1] > 0.95
    assert np.corrcoef(b_before.ravel(), b_after.ravel())[0, 1] < 0.5


def test_each_camera_sees_its_own_sample(m: Microscope) -> None:
    """cam_a: bright beads where the laser excites GFP; cam_b: a stained section in white light,
    darker in green than in blue (eosin takes up green)."""
    assert m.values is not None and m.detector is not None
    m.values.set({"laser_488.power": 20.0})
    beads = image(m, "cam_a")
    assert np.percentile(beads, 99.9) > 3 * np.median(beads)
    colors = m.detector.capture_channels("cam_b").astype(float)
    red, green, blue = (np.median(channel) for channel in colors)
    assert green < blue and green < red


# --- where things are: a hub for each sample


def test_each_sample_is_a_hub_of_its_own(m: Microscope) -> None:
    """Each camera goes to its own stage, each stage to its own sample; the thermometer to
    stage_b's insert."""
    edges = {(t.input, t.output) for t in m.space_state.transformations}
    assert ("detector:cam_a", "stage:stage_a") in edges
    assert ("detector:cam_b", "stage:stage_b") in edges
    assert ("stage:stage_a", "sample:stage_a") in edges
    assert ("stage:stage_b", "sample:stage_b") in edges
    assert ("detector:thermometer", "stage:stage_b") in edges
    assert m.space_state.detectors["cam_a"].sample == "stage_a"
    assert m.space_state.points["thermometer"].sample == "stage_b"
    with pytest.raises(ValueError, match="no route"):
        m.space.transform(Position("sample:stage_a", {"x": 0.0, "y": 0.0}), "sample:stage_b")


def test_each_camera_is_placed_on_its_own_samples_beads(m: Microscope) -> None:
    """With each stage far from the other, cam_a's bright beads, placed by its own placement, are
    on stage_a's beads; and the same placement on stage_b's would miss them."""
    assert m.values is not None
    m.values.set({"laser_488.power": 20.0, "stage_a.x": AWAY[0], "stage_a.y": AWAY[1]})
    m.values.set({"stage_b.x": -AWAY[0], "stage_b.y": -AWAY[1]})
    seen = image(m, "cam_a")
    placed = placed_by_metadata(m, "cam_a")
    assert on_beads(bead_misses(m, seen, placed, "stage_a"), 3.0)


def test_a_bare_sample_is_the_one_the_camera_sees(m: Microscope) -> None:
    """Moving cam_b to a point of "the sample" moves stage_b, and leaves stage_a where it is."""
    assert m.values is not None
    x, y = MIDDLE[0] + 250.0, MIDDLE[1] - 120.0
    move_to(m.space, m.values, Task.local(), at_sample(x, y), "cam_b")
    assert m.values["stage_a.x"] == 0.0 and m.values["stage_a.y"] == 0.0
    assert (m.values["stage_b.x"], m.values["stage_b.y"]) != (0.0, 0.0)
    middle = m.space.placement("cam_b") @ np.array([255.5, 255.5, 0.0, 1.0])
    assert middle[:2] == pytest.approx([x, y], abs=1e-6)


def test_with_two_samples_a_bare_name_needs_a_camera(m: Microscope) -> None:
    """ "The sample" is either: nothing is guessed."""
    with pytest.raises(ValueError, match="Which sample"):
        m.space.transform(at_sample(0.0, 0.0), "stage")
    with pytest.raises(ValueError, match="Which sample"):
        m.space.mount_holder("slide")


def test_mounting_one_sample_leaves_the_other(m: Microscope) -> None:
    """A new mounting of stage_a: its own mount id and images change, stage_b's do not."""
    assert m.acquisition is not None and m.values is not None
    m.values.set({"laser_488.power": 20.0})
    frames = m.acquisition.acquire(["cam_a", "cam_b"])
    assert {frame.metadata.sample for frame in frames} == {"stage_a", "stage_b"}
    a, b = (m.space_state.samples[name].mount_id for name in ("stage_a", "stage_b"))
    mount_holder(m.space, m.expanse, "slide", "stage_a")
    assert m.space_state.samples["stage_a"].mount_id != a
    assert m.space_state.samples["stage_b"].mount_id == b
    assert [frame.metadata.sample for frame in m.expanse_state.current_frames] == ["stage_b"]


# --- an acquisition of both


def run(m: Microscope, plan: AcquisitionPlan) -> RecordingStore:
    """Acquire `plan` on `m` into a store that keeps what it is given."""
    assert m.values is not None and m.detector is not None
    store = StateStore(m)
    run_plan(plan, store, m.optics, m.detector, m.values, m.space, m.hooks, Task.local())
    return store


def test_one_plan_acquires_both_samples(m: Microscope) -> None:
    """One position on "the sample" is that point on each, each brought there by its own stage;
    a stack sweeps each sample's own focus; each record is on its own sample."""
    assert m.values is not None
    # A channel lights what it names, and only that: both arms' sources, for both cameras.
    channel = AcquisitionChannel(
        name="all",
        detectors=["cam_a", "cam_b", "thermometer"],
        set_to={"laser_488.power": 20.0, "white_led.power": 0.01},
    )
    x, y = MIDDLE[0] + 300.0, MIDDLE[1] - 200.0
    plan = AcquisitionPlan(
        channels=[channel],
        positions=[AcquisitionPosition(at=at_sample(x, y))],
        stack=AcquisitionStack(offsets=[-1.0, 0.0, 1.0]),
    )
    cam_a, cam_b, thermometer = run(m, plan).published
    assert (cam_a.sample, cam_b.sample, thermometer.sample) == ("stage_a", "stage_b", "stage_b")
    assert cam_a.mount_id != cam_b.mount_id
    for record in (cam_a, cam_b):
        height, width = record.data.shape[-2:]
        middle = sample_of(record, z=1.0, y=(height - 1) / 2, x=(width - 1) / 2)
        assert (middle["x"], middle["y"]) == pytest.approx((x, y), abs=1e-6)
    a_z = {plane.state["stage_a.z"] for plane in cam_a.planes}
    b_z = {plane.state["stage_b.z"] for plane in cam_b.planes}
    assert len(a_z) == 3 and len(b_z) == 3
    assert thermometer.data.shape == (1, 1, 3, 1, 1, 1)
    # What each took is its own sample, lit: GFP beads, and a stained section in color.
    beads = cam_a.data[0, 0, 1].astype(float)
    assert np.percentile(beads, 99.9) > 3 * np.median(beads)
    red, green, blue = (np.median(cam_b.data[0, c, 1].astype(float)) for c in range(3))
    assert green < blue and green < red and min(red, green, blue) > 0


def test_a_named_sweep_across_two_samples_is_refused(m: Microscope) -> None:
    """It would sweep one of them: refused before anything moves."""
    assert m.values is not None
    channel = AcquisitionChannel(detectors=["cam_a", "cam_b"], set_to={"laser_488.power": 20.0})
    plan = AcquisitionPlan(
        channels=[channel],
        positions=[AcquisitionPosition(set_to={"stage_a.x": 500.0})],
        stack=AcquisitionStack(offsets=[0.0, 1.0], variable="stage_a.z"),
    )
    with pytest.raises(ValueError, match="leave stack.variable out"):
        run(m, plan)
    assert m.values["stage_a.x"] == 0.0


def test_a_place_on_one_sample_moves_only_its_stage(m: Microscope) -> None:
    """A position on sample:stage_a: stage_a goes there, stage_b stays."""
    assert m.values is not None
    channel = AcquisitionChannel(detectors=["cam_a", "cam_b"], set_to={"laser_488.power": 20.0})
    where = Position("sample:stage_a", {"x": MIDDLE[0] + 100.0, "y": MIDDLE[1] + 50.0})
    run(m, AcquisitionPlan(channels=[channel], positions=[AcquisitionPosition(at=where)]))
    assert m.values["stage_b.x"] == 0.0 and m.values["stage_b.y"] == 0.0
    assert (m.values["stage_a.x"], m.values["stage_a.y"]) != (0.0, 0.0)


def test_a_thermometer_without_its_stage_is_refused_beside_two_samples(tmp_path: Path) -> None:
    """Which stage it sits on cannot be guessed."""
    import shutil

    import yaml

    folder = tmp_path / "dual"
    shutil.copytree(DUAL, folder)
    path = folder / "microscope.yml"
    data = yaml.safe_load(path.read_text())
    data["cubes"]["thermometer"]["element"]["at"].pop("stage")
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(spec.SpecError, match="which of the samples"):
        spec.load(folder)
