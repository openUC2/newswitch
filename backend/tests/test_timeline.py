"""Each channel is taken on its own clock, and a probe can stream through the whole acquisition.

A camera every 0.3 s from 0.2 s, an electrode array recording without pause: one clock, the
sample's, counted from when it was mounted, on which every record's time axis is placed.
"""

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from arkitekt import Task

from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import AcquisitionChannel, AcquisitionPlan
from newswitch.instrument import spec
from newswitch.routines.acquire import _Cadence, _events
from newswitch.routines.acquire import acquire as run_plan
from tests.conftest import run_settings
from tests.test_acquire import StateStore

MEA = Path(__file__).parents[1] / "instruments" / "mea-microscope"


@pytest.fixture
def m(tmp_path: Path) -> Microscope:
    """The mea-microscope, simulated."""
    return build_microscope(run_settings(tmp_path, instrument=MEA), spec.load(MEA))


def run(m: Microscope, plan: AcquisitionPlan) -> list:
    """What `plan` records on `m`."""
    store = StateStore(m)
    run_plan(plan, store, m.optics, m.detector, m.values, m.space, m.hooks, Task.local())  # type: ignore[arg-type]
    return store.published


def seconds(record, **at: float) -> float:  # noqa: ANN001 - an AcquiredRecord
    """Where a point of `record` is on its sample's clock, by its time part."""
    (when,) = [part for part in record.registration if part.output_axes == ["t"]]
    point = np.array([*(at[axis] for axis in when.input_axes), 1.0])
    return float(np.dot(when.affine[0], point))


def on_the_clock(record, instant: datetime) -> float:  # noqa: ANN001 - an AcquiredRecord
    """Where a wall-clock instant is on `record`'s sample's clock."""
    return (instant - datetime.fromisoformat(record.mounted_at)).total_seconds()


GFP = AcquisitionChannel(
    name="gfp",
    detectors=["camera"],
    set_to={"laser_488.power": 20.0},
    every_s=0.3,
    start_s=0.2,
    times=3,
)
VOLTAGE = AcquisitionChannel(name="voltage", detectors=["mea"], stream=True)


# --- when


def test_channels_due_at_once_are_one_visit_and_one_channel_never_is_twice() -> None:
    """Every 0.3 s from 0.2, every 0.6 s from 0.2: due together at 0.2 and 0.8; and one taken
    twice with no time between is two visits."""
    events = _events([_Cadence(0.2, 0.3, 3), _Cadence(0.2, 0.6, 2)])
    assert [(round(at, 6), due) for at, due in events] == [
        (0.2, {0: 0, 1: 0}),
        (0.5, {0: 1}),
        (0.8, {0: 2, 1: 1}),
    ]
    assert _events([_Cadence(0.0, 0.0, 2)]) == [(0.0, {0: 0}), (0.0, {0: 1})]


def test_a_channel_is_taken_when_it_is_due_and_its_record_says_when(m: Microscope) -> None:
    """Three images at 0.2, 0.5 and 0.8 s: the record's time axis places each on the sample's
    clock where it was planned, and each was taken then, give or take an exposure."""
    camera, _ = run(m, AcquisitionPlan(name="clock", channels=[GFP, VOLTAGE]))
    assert camera.data.shape[0] == 3
    planned = [seconds(camera, t=k) for k in range(3)]
    assert np.diff(planned) == pytest.approx([0.3, 0.3])
    for k, plane in enumerate(camera.planes):
        assert plane.t == k
        assert on_the_clock(camera, plane.started) == pytest.approx(planned[k], abs=0.25)


def test_a_stream_records_the_whole_time_on_the_same_clock(m: Microscope) -> None:
    """The array's blocks follow one another without a gap from the start to the end, 50 ms each,
    20 kHz within; and the sample the camera took its last image at is in it."""
    camera, mea = run(m, AcquisitionPlan(name="clock", channels=[GFP, VOLTAGE]))
    blocks = mea.data.shape[0]
    assert mea.data.shape[1:] == (1, 1000, 1, 8, 8)
    assert seconds(mea, t=1, s=0) - seconds(mea, t=0, s=0) == pytest.approx(0.05)
    assert seconds(mea, t=0, s=1) - seconds(mea, t=0, s=0) == pytest.approx(0.00005)
    start, end = seconds(mea, t=0, s=0), seconds(mea, t=blocks - 1, s=999)
    assert start <= seconds(camera, t=0) and seconds(camera, t=2) <= end + 0.2
    assert mea.position == 0 and mea.unit == "uV"
    # its blocks are what the simulator's clock had: a voltage that moves, not a constant
    assert float(mea.data.std()) > 1.0


def test_one_record_has_one_time_axis(m: Microscope) -> None:
    """The camera in two channels taken at other times: refused, before anything moves."""
    other = AcquisitionChannel(
        name="bright",
        detectors=["camera"],
        set_to={"white_led.power": 0.01},
        every_s=0.5,
        times=2,
    )
    with pytest.raises(ValueError, match="one record has one time axis"):
        run(m, AcquisitionPlan(channels=[GFP, other]))


def test_what_samples_no_time_does_not_stream(m: Microscope) -> None:
    """A camera has no time of its own to stream: refused."""
    with pytest.raises(ValueError, match="camera samples no time of its own"):
        run(
            m,
            AcquisitionPlan(channels=[GFP, AcquisitionChannel(detectors=["camera"], stream=True)]),
        )


def test_a_stream_alone_is_refused(m: Microscope) -> None:
    """With nothing taken, nothing says how long it runs."""
    with pytest.raises(ValueError, match="A stream records while something is taken"):
        run(m, AcquisitionPlan(channels=[VOLTAGE]))
