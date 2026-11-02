"""What the software does when a motor misbehaves.

The files in ``instruments/expected-failures/motors`` wire a motor to `Faulty`, a driver only these
tests register, so nothing but a test can run one. Every fault is on `stage.z`, and is exact rather
than random: a run repeats.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from arkitekt import Task

from newswitch.drivers.base import Report, Simulated, register_driver
from newswitch.instrument import spec
from newswitch.instrument.spec import Variable
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import AcquisitionChannel
from newswitch.routines.acquire import acquire
from newswitch.routines.autofocus import run_autofocus
from newswitch.states.autofocus import AutofocusState
from tests.conftest import acquisition, run_settings
from tests.test_acquire import RecordingStore

MOTORS = Path(__file__).parent.parent / "instruments" / "expected-failures" / "motors"


class Faulty(Simulated):
    """A motor that goes wrong in the way its options say."""

    def __init__(
        self,
        name: str,
        drops_from: int | None = None,
        stalls_from: int | None = None,
        stops_at: float = 0.5,
        pushed_back: float = 0.0,
        drifts: float = 0.0,
    ) -> None:
        """Which command goes wrong first, counting from 1, and how."""
        self.name = name
        self.drops_from = drops_from
        self.stalls_from = stalls_from
        self.stops_at = stops_at
        self.pushed_back = pushed_back
        self.drifts = drifts
        self.commands = 0
        self.value = 0.0

    def start(self, initial: Any) -> Any:  # noqa: ANN401 - whatever the variable holds
        """Where it was described to start."""
        self.value = initial
        return initial

    def set(self, value: Any, report: Report, task: Task | None = None) -> None:  # noqa: ANN401
        """Go there, if it does."""
        self.commands += 1
        if self.drops_from is not None and self.commands >= self.drops_from:
            raise RuntimeError(f"{self.name}: no answer to command {self.commands}")
        travel = value - self.value
        if self.stalls_from is not None and self.commands >= self.stalls_from:
            self.value += travel * self.stops_at
            report(self.value)
            raise RuntimeError(f"{self.name}: stalled at {self.value}")
        self.value += travel - np.sign(travel) * min(self.pushed_back, abs(travel))
        report(self.value)

    def creep(self, report: Report) -> None:
        """Be pushed, with nothing commanding it: `report` is how a board's event arrives."""
        self.value += self.drifts
        report(self.value)


def _faulty(variable: Variable, options: Mapping[str, Any], context: Mapping[str, Any]) -> Faulty:
    return Faulty(variable.name, **options)


register_driver("test.faulty", _faulty)


def built(tmp_path: Path, fault: str) -> Microscope:
    """The microscope of the file `fault`, with what its motor is really doing."""
    instrument = spec.load(MOTORS / f"{fault}.yml")
    return build_microscope(run_settings(tmp_path, simulate="unwired"), instrument)


def defocus(m: Microscope) -> float:
    """What the optics say about where z is."""
    return m.optics_state.detectors["camera"].defocus_um


def test_a_lost_command_leaves_it_where_it_was_and_says_which(tmp_path: Path) -> None:
    """Nothing claims it arrived, and the optics still know where it is."""
    m = built(tmp_path, "drops")
    m.values.set({"stage.z": 10.0})
    m.values.set({"stage.z": 20.0})
    with pytest.raises(RuntimeError, match=r"stage\.z: no answer to command 3"):
        m.values.set({"stage.z": 30.0})
    assert m.values["stage.z"] == 20.0
    assert m.move_state.moves["stage"]["z"].value == 20.0
    assert defocus(m) == pytest.approx(20.0)


def test_what_moved_beside_a_lost_command_is_known_about(tmp_path: Path) -> None:
    """The optics go stale otherwise: a failed move is no reason to forget a finished one."""
    m = built(tmp_path, "stalls")
    told: list[float] = []
    on_change = m.values.on_change
    m.values.on_change = lambda: (told.append(m.values["stage.z"]), on_change())
    with pytest.raises(RuntimeError, match=r"stage\.z: stalled"):
        m.values.set({"stage.z": 100.0})
    assert told == [50.0]
    assert defocus(m) == pytest.approx(50.0)


def test_a_stall_leaves_it_on_the_way(tmp_path: Path) -> None:
    """Published and predicted where it stopped: not where it was, nor where it was going."""
    m = built(tmp_path, "stalls")
    with pytest.raises(RuntimeError, match=r"stage\.z: stalled at 50"):
        m.values.set({"stage.z": 100.0})
    assert m.values["stage.z"] == 50.0
    assert m.move_state.moves["stage"]["z"].value == 50.0


def test_ending_short_is_what_everyone_sees(tmp_path: Path) -> None:
    """No error to go by: the value, the optics and the image all say where it really is."""
    short = built(tmp_path, "pushed-back")
    short.values.set({"laser_488.power": 40.0})
    short.values.set({"stage.z": 100.0})
    assert short.values["stage.z"] == 98.0
    assert defocus(short) == pytest.approx(98.0)

    def sharpness(m: Microscope) -> float:
        frame = m.detector.capture_image("camera").data.astype(float)
        return float(np.var(np.diff(frame, axis=0)))

    close = built(tmp_path / "close", "pushed-back")
    close.values.set({"laser_488.power": 40.0})
    close.values.set({"stage.z": 3.0})
    assert close.values["stage.z"] == 1.0
    assert sharpness(close) > sharpness(short)


def test_it_never_ends_behind_where_it_started(tmp_path: Path) -> None:
    """Pushed back further than it went, it just has not gone anywhere."""
    m = built(tmp_path, "pushed-back")
    m.values.set({"stage.z": 1.0})
    assert m.values["stage.z"] == 0.0


def test_a_push_nothing_commanded_reaches_everyone(tmp_path: Path) -> None:
    """Through `stepped`, as a board's report does."""
    m = built(tmp_path, "drifts")
    m.values.drivers["stage.z"].creep(lambda value: m.values.stepped("stage.z", value))
    assert m.values["stage.z"] == 3.0
    assert m.move_state.moves["stage"]["z"].value == 3.0
    assert defocus(m) == pytest.approx(3.0)


def test_an_acquisition_stops_at_a_lost_command_and_says_which(tmp_path: Path) -> None:
    """Rather than taking the same plane again and calling it the next, or finishing."""
    m = built(tmp_path, "drops")
    store = RecordingStore()
    channel = AcquisitionChannel(detectors=["camera"], name="gfp", set_to={"laser_488.power": 40.0})
    plan = acquisition([channel], planes=[0.0, 10.0, 20.0, 30.0])
    with pytest.raises(RuntimeError, match=r"stage\.z: no answer"):
        acquire(plan, store, m.optics, m.detector, m.values, m.space, m.hooks, Task.local())
    assert store.published == []


def test_a_failed_acquisition_turns_the_light_off(tmp_path: Path) -> None:
    """A sample is left lit otherwise, for as long as nobody looks."""
    m = built(tmp_path, "drops")
    channel = AcquisitionChannel(detectors=["camera"], name="gfp", set_to={"laser_488.power": 40.0})
    plan = acquisition([channel], planes=[0.0, 10.0, 20.0, 30.0])
    with pytest.raises(RuntimeError):
        acquire(
            plan, RecordingStore(), m.optics, m.detector, m.values, m.space, m.hooks, Task.local()
        )
    assert m.values["laser_488.power"] == 0.0


def test_an_autofocus_stops_at_a_lost_command_and_says_which(tmp_path: Path) -> None:
    """It does not find a focus among the planes it never went to, and is no longer running."""
    m = built(tmp_path, "drops")
    m.values.set({"laser_488.power": 40.0})
    state = AutofocusState()
    with pytest.raises(RuntimeError, match=r"stage\.z: no answer"):
        run_autofocus(
            m.values, m.detector, state, m.optics, Task.local(), steps=7, detector_name="camera"
        )
    assert state.running is False
    assert state.best_z == 0.0  # what it starts as: nothing was found
    assert len(state.metrics) < 7
