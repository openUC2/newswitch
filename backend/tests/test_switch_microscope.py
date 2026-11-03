"""Switches: flip mirrors that decide which sample a camera sees, and which camera the light goes to.

Which sample a detector sees is no longer fixed by the light path's shape: the selector sends arm a's
light or arm b's on, the port sends it to cam_color or to cam_mono. Each setting of them that gets a
source's light through is a channel of its own, found, with the swaps that make it.
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from arkitekt import Task

from newswitch.instrument import spec
from newswitch.instrument.compiler import compile_instrument, influences
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
from tests.test_acquire import StateStore, sample_of
from tests.test_space import AWAY, bead_misses, on_beads, placed_by_metadata

SWITCH = Path(__file__).parents[1] / "instruments" / "switch-microscope"
DUAL = Path(__file__).parents[1] / "instruments" / "dual-sample"
#: The middle of a 75 x 25 mm slide, in its sample's micrometres (from its corner).
MIDDLE = (37_500.0, 12_500.0)

ARM_A = {"selector.slot": 1}
ARM_B = {"selector.slot": 2}
COLOR = {"port.slot": 1}
MONO = {"port.slot": 2}


@pytest.fixture(scope="module")
def instrument() -> spec.Instrument:
    """The switch microscope's description."""
    return spec.load(SWITCH)


@pytest.fixture
def m(tmp_path: Path, instrument: spec.Instrument) -> Microscope:
    """The switch microscope, simulated."""
    return build_microscope(run_settings(tmp_path, instrument=SWITCH), instrument)


def described(tmp_path: Path, folder: Path, change) -> Path:  # noqa: ANN001 - a function of data
    """A copy of the description in `folder`, changed by `change`, beside the shared views."""
    data = yaml.safe_load((folder / "microscope.yml").read_text())
    change(data)
    copy = tmp_path / "instruments" / folder.name
    copy.mkdir(parents=True)
    (copy / "microscope.yml").write_text(yaml.safe_dump(data))
    for view in folder.glob("*.bsx"):
        (copy / view.name).write_text(view.read_text())
    views = tmp_path / "instruments" / "views"
    views.mkdir(exist_ok=True)
    for view in (folder.parent / "views").glob("*.bsx"):
        (views / view.name).write_text(view.read_text())
    return copy / "microscope.yml"


# --- which sample, under which switches


def test_the_selector_decides_which_sample_a_camera_sees(instrument: spec.Instrument) -> None:
    """Out of the way, arm a's light goes on; in the way, arm b's. The port says to which camera:
    the other one sees nothing."""
    start = instrument.initial_state()
    assert instrument.samples_of("cam_color") == ["stage_a", "stage_b"]
    assert instrument.sample_of("cam_color", {**start, **ARM_A, **COLOR}) == "stage_a"
    assert instrument.sample_of("cam_color", {**start, **ARM_B, **COLOR}) == "stage_b"
    assert instrument.sample_of("cam_mono", {**start, **ARM_B, **MONO}) == "stage_b"
    assert instrument.sample_of("cam_color", {**start, **ARM_A, **MONO}) is None
    with pytest.raises(spec.Dark, match=r"No light reaches cam_mono; with port.slot=2 it does"):
        instrument.seen_sample("cam_mono", start)


def test_a_camera_reached_from_two_samples_at_once_is_refused(tmp_path: Path) -> None:
    """Without came_from, the selector would let what comes from arm b through as well: with it out
    of the way, cam_color would see both samples at once."""

    def forget(data: dict) -> None:
        for edge in data["detection"]:
            edge.pop("came_from", None)

    with pytest.raises(
        spec.SpecError, match=r"cam_color is reached from [^;]* at once with [^:]*selector.slot=1"
    ):
        spec.load(described(tmp_path, SWITCH, forget))


def test_a_sample_no_detector_ever_sees_is_refused(tmp_path: Path) -> None:
    """cam_b looks at stage_a too: stage_b, and the LED that lights it, would be there for nothing."""

    def rewire(data: dict) -> None:
        for edge in data["detection"]:
            if edge["from"] == "stage_b":
                edge["from"] = "stage_a"

    with pytest.raises(spec.SpecError, match="no detector sees stage_b"):
        spec.load(described(tmp_path, DUAL, rewire))


# --- what the optics find


def test_every_channel_is_found_with_the_switches_that_make_it(
    instrument: spec.Instrument,
) -> None:
    """Each source, detector and sample is a channel, with what it takes of the selector, the port
    and the filter; whatever they are set to now. Through BP 625/50 GFP is lost in the noise: no
    channel."""
    table = compile_instrument(instrument)
    found = {
        (c.source, c.detector, c.sample): dict(c.swaps)
        for c in table.channels(instrument.initial_state())
    }
    assert found == {
        ("laser_488", "cam_color", "stage_a"): {
            "filter_wheel.slot": 1,
            "selector.slot": 1,
            "port.slot": 1,
        },
        ("laser_488", "cam_mono", "stage_a"): {
            "filter_wheel.slot": 1,
            "selector.slot": 1,
            "port.slot": 2,
        },
        ("white_led", "cam_color", "stage_b"): {"selector.slot": 2, "port.slot": 1},
        ("white_led", "cam_mono", "stage_b"): {"selector.slot": 2, "port.slot": 2},
    }


def test_an_objective_turret_does_not_split_a_channel() -> None:
    """The fake microscope's objectives change how much light, not which: one channel each."""
    fake = spec.load(Path(__file__).parents[1] / "instruments" / "fake-microscope")
    table = compile_instrument(fake)
    channels = table.channels(fake.initial_state())
    assert all("objective.slot" not in channel.swaps for channel in channels)
    pairs = [(c.source, c.detector) for c in channels]
    assert len(pairs) == len(set(pairs))


def test_a_calibration_on_one_sample_is_none_on_the_other(instrument: spec.Instrument) -> None:
    """The selector changes what cam_color's pixels are of: it is in what a calibration of it
    depends on, and so is the port, which leaves it dark."""
    found = influences(instrument)
    assert {"selector.slot", "port.slot"} <= found["cam_color"]


def test_what_moves_a_cameras_view_is_its_samples_stage(m: Microscope) -> None:
    """Found for each sample a camera can see: stage_a's moves on arm a, stage_b's on arm b."""
    assert m.values is not None
    roles = m.values.roles
    assert roles.x("cam_color", sample="stage_a").name == "stage_a.x"
    assert roles.x("cam_color", sample="stage_b").name == "stage_b.x"
    assert roles.focus("cam_mono", sample="stage_b").name == "stage_b.z"
    with pytest.raises(ValueError, match="say which"):
        roles.x("cam_color")


# --- what the cameras see


def image(m: Microscope, camera: str) -> np.ndarray:
    """What `camera` sees now."""
    assert m.detector is not None
    m.detector.activate_detector(camera)
    return m.detector.capture_image(camera).data.astype(float)


def test_flipping_the_selector_shows_a_camera_the_other_sample(m: Microscope) -> None:
    """cam_mono: GFP beads, the selector out; the section in white light, the selector in."""
    assert m.values is not None
    m.values.set({"laser_488.power": 20.0, "white_led.power": 0.01, **MONO})
    beads = image(m, "cam_mono")
    assert np.percentile(beads, 99.9) > 3 * np.median(beads)
    m.values.set(ARM_B)
    section = image(m, "cam_mono")
    assert np.median(section) > 3 * np.median(beads)


def test_a_camera_the_port_sends_no_light_to_shows_its_noise(m: Microscope) -> None:
    """The port sends it all to cam_mono: cam_color reads out its offset and its read noise."""
    assert m.values is not None
    m.values.set({"laser_488.power": 20.0, **MONO})
    dark = image(m, "cam_color")
    sensor = m.values.instrument.cubes["cam_color"].element
    assert isinstance(sensor, spec.Sensor)
    readout = sensor.readout
    assert np.median(dark) == pytest.approx(readout.offset, abs=3)
    assert np.percentile(dark, 99.9) < readout.offset + 10 * readout.read_noise


def test_a_camera_is_where_the_selector_puts_it(m: Microscope) -> None:
    """In the graph cam_color goes to stage_a's stage, then to stage_b's when the selector flips;
    cam_mono, dark, is nowhere, and neither are its optics."""
    assert m.values is not None
    edges = {(t.input, t.output) for t in m.space_state.transformations}
    assert ("detector:cam_color", "stage:stage_a") in edges
    assert "cam_mono" not in m.space_state.detectors
    assert "cam_mono" not in m.optics_state.detectors
    assert m.optics_state.detectors["cam_color"].sample == "stage_a"
    m.values.set(ARM_B)
    edges = {(t.input, t.output) for t in m.space_state.transformations}
    assert ("detector:cam_color", "stage:stage_b") in edges
    assert m.space_state.detectors["cam_color"].sample == "stage_b"


def test_a_camera_is_placed_on_the_beads_of_the_sample_it_sees(m: Microscope) -> None:
    """With stage_b far away, cam_mono's bright beads, placed by its placement, are on stage_a's."""
    assert m.values is not None
    m.values.set({"laser_488.power": 20.0, **MONO, "stage_a.x": AWAY[0], "stage_a.y": AWAY[1]})
    m.values.set({"stage_b.x": -AWAY[0], "stage_b.y": -AWAY[1]})
    seen = image(m, "cam_mono")
    placed = placed_by_metadata(m, "cam_mono")
    assert on_beads(bead_misses(m, seen, placed, "stage_a"), 3.0)


# --- an acquisition through both arms


def run(m: Microscope, plan: AcquisitionPlan) -> StateStore:
    """Acquire `plan` on `m` into a store that keeps what it is given."""
    assert m.values is not None and m.detector is not None
    store = StateStore(m)
    run_plan(plan, store, m.optics, m.detector, m.values, m.space, m.hooks, Task.local())
    return store


GFP = AcquisitionChannel(
    name="gfp",
    detectors=["cam_mono"],
    set_to={"laser_488.power": 20.0, **ARM_A, **MONO, "filter_wheel.slot": 1},
)
SECTION = AcquisitionChannel(
    name="section",
    detectors=["cam_mono"],
    set_to={"white_led.power": 0.01, **ARM_B, **MONO},
)


def test_one_camera_records_both_samples_one_record_each(m: Microscope) -> None:
    """Two channels that flip the selector: cam_mono images stage_a, then stage_b. A record for
    each, on its own sample, each brought to the place on "the sample" by its own stage, each
    stack swept by its own focus; started with the selector the other way."""
    assert m.values is not None
    m.values.set(ARM_B)
    x, y = MIDDLE[0] + 300.0, MIDDLE[1] - 200.0
    plan = AcquisitionPlan(
        name="both",
        channels=[GFP, SECTION],
        positions=[AcquisitionPosition(at=Position("sample", {"x": x, "y": y}))],
        stack=AcquisitionStack(offsets=[-1.0, 0.0, 1.0]),
    )
    a, b = run(m, plan).published
    assert (a.name, b.name) == ("both cam_mono-stage_a", "both cam_mono-stage_b")
    assert (a.sample, b.sample) == ("stage_a", "stage_b")
    assert a.mount_id != b.mount_id
    for record in (a, b):
        assert record.data.shape[:3] == (1, 1, 3)
        height, width = record.data.shape[-2:]
        middle = sample_of(record, z=1.0, y=(height - 1) / 2, x=(width - 1) / 2)
        assert (middle["x"], middle["y"]) == pytest.approx((x, y), abs=1e-6)
    assert len({plane.state["stage_a.z"] for plane in a.planes}) == 3
    assert len({plane.state["stage_b.z"] for plane in b.planes}) == 3
    beads = a.data[0, 0, 1].astype(float)
    assert np.percentile(beads, 99.9) > 3 * np.median(beads)
    assert np.median(b.data[0, 0, 1]) > 3 * np.median(beads)


def test_a_channel_onto_a_dark_camera_is_refused(m: Microscope) -> None:
    """The port sends the light to cam_mono, and the channel asks cam_color: refused, saying what to
    switch, before anything moves."""
    assert m.values is not None
    channel = AcquisitionChannel(detectors=["cam_color"], set_to={"laser_488.power": 20.0, **MONO})
    plan = AcquisitionPlan(
        channels=[channel], positions=[AcquisitionPosition(set_to={"stage_a.x": 500.0})]
    )
    with pytest.raises(spec.Dark, match="port.slot=1"):
        run(m, plan)
    assert m.values["stage_a.x"] == 0.0


class _SeenBy:
    """Hooks that only note which sample the selector shows, and what is lit, when they run."""

    def __init__(self, m: Microscope) -> None:
        self.m = m
        self.ran: list[tuple[int, bool, bool]] = []

    def check(self, hooks: object, level: str) -> None:
        """Every hook can run anywhere."""

    def execute_all(self, hooks: list) -> None:
        """Note the selector, and which source is on."""
        if hooks:
            assert self.m.values is not None
            values = self.m.values
            self.ran.append(
                (
                    values["selector.slot"],
                    values["laser_488.power"] > 0,
                    values["white_led.power"] > 0,
                )
            )


def test_a_refocus_at_each_place_runs_under_each_samples_channel(m: Microscope) -> None:
    """The selector shows one sample at a time: a position hook runs once with arm a's light on and
    the selector out, once with arm b's on and the selector in."""
    from newswitch.models.hooks import SoftwareAutofocusHook

    assert m.values is not None and m.detector is not None
    hooks = _SeenBy(m)
    plan = AcquisitionPlan(
        channels=[GFP, SECTION],
        positions=[AcquisitionPosition(set_to={"stage_a.x": 10.0})],
        p_hooks=[SoftwareAutofocusHook()],
    )
    run_plan(plan, StateStore(m), m.optics, m.detector, m.values, m.space, hooks, Task.local())  # type: ignore[arg-type]
    assert hooks.ran == [(1, True, False), (2, False, True)]


def test_each_channel_says_what_it_sees_through_its_own_swaps(m: Microscope) -> None:
    """Whatever the selector shows now, a channel's field and depth of field are of the objective
    its own swaps put on the way: arm a's NA 0.25 is deeper, and its 10x sees more, than arm b's."""
    assert m.values is not None
    m.values.set({**ARM_B, **MONO})
    found = {(c.source, c.detector): c for c in m.optics_state.channels}
    gfp, section = found["laser_488", "cam_color"], found["white_led", "cam_color"]
    assert gfp.depth_of_field_um > 2 * section.depth_of_field_um > 0
    assert gfp.field_width_um == pytest.approx(2 * section.field_width_um, rel=0.01)
