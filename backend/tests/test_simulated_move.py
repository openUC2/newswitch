"""A simulated move: it travels at the speed its variable states, and says where it got to."""

import time
from types import SimpleNamespace

import koil
import pytest

from newswitch.actions.values import move_home
from newswitch.drivers.base import MAX_REPORTS, REPORTS_PER_S, SimulatedMove
from newswitch.microscope.parts import Microscope


def moved(speed: float | None, start: float, to: float, task: object = None) -> list[float]:
    """Where a move at `speed` from `start` to `to` said it got to."""
    reports: list[float] = []
    SimulatedMove(speed, lambda: start).set(to, reports.append, task)  # type: ignore[arg-type]
    return reports


def test_absolute_and_relative_moves_and_going_home(microscope: Microscope) -> None:
    """To a value, by a value on top of where it is, and back to where it is described to start."""
    assert microscope.values is not None
    values = microscope.values

    values.set({"stage.x": 10.0, "stage.y": 20.0, "stage.z": 5.0})
    assert (values["stage.x"], values["stage.y"], values["stage.z"]) == pytest.approx(
        (10.0, 20.0, 5.0)
    )

    values.set({"stage.x": 5.0}, relative=True)
    assert values["stage.x"] == pytest.approx(15.0)  # 10 + 5

    move_home(values, SimpleNamespace(pausepoint=lambda: None, progress=lambda _: None))  # type: ignore[arg-type]
    assert (values["stage.x"], values["stage.y"], values["stage.z"]) == pytest.approx(
        (0.0, 0.0, 0.0)
    )


def test_with_no_speed_it_is_there_at_once() -> None:
    """One report, of where it was told to go."""
    assert moved(None, 0.0, 100.0) == [100.0]


def test_at_a_speed_it_takes_as_long_as_it_says() -> None:
    """100 um at 500 um/s: a fifth of a second, however often it reports."""
    started = time.monotonic()
    moved(500.0, 0.0, 100.0)
    assert 0.15 < time.monotonic() - started < 1.0


def test_it_reports_its_way_there_and_ends_where_it_was_told() -> None:
    """In even steps, at the rate that does not flood clients, from where it was."""
    reports = moved(500.0, 10.0, 110.0)
    assert len(reports) == int(0.2 * REPORTS_PER_S)
    assert reports == pytest.approx([35.0, 60.0, 85.0, 110.0])


def test_a_long_move_does_not_report_without_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """However far it goes: at most `MAX_REPORTS`."""
    monkeypatch.setattr(koil, "sleep", lambda _: None)
    speed = 1_000_000.0
    far = speed * (MAX_REPORTS / REPORTS_PER_S + 1.0)  # longer than the limit lasts
    reports = moved(speed, 0.0, far)
    assert len(reports) == MAX_REPORTS
    assert reports[-1] == pytest.approx(far)


def test_a_task_is_told_and_can_pause_it() -> None:
    """A pause point before each step, and how far it got, ending at all of it."""
    pauses: list[None] = []
    progress: list[int] = []
    task = SimpleNamespace(pausepoint=lambda: pauses.append(None), progress=progress.append)
    moved(500.0, 0.0, 100.0, task)
    assert len(pauses) == len(progress) == 4
    assert progress == [25, 50, 75, 100]


def test_moves_together_take_as_long_as_the_slowest() -> None:
    """Both arrive at the same time, whichever is faster."""
    fast, slow = SimulatedMove(1000.0, lambda: 0.0), SimulatedMove(100.0, lambda: 0.0)
    reached_fast: list[float] = []
    reached_slow: list[float] = []
    started = time.monotonic()
    SimulatedMove.set_together(
        [(fast, 100.0, reached_fast.append), (slow, 20.0, reached_slow.append)]
    )
    assert 0.15 < time.monotonic() - started < 1.0  # 20 um at 100 um/s
    assert len(reached_fast) == len(reached_slow) == 4
    assert reached_fast[-1] == pytest.approx(100.0) and reached_slow[-1] == pytest.approx(20.0)
    assert reached_fast[0] == pytest.approx(25.0) and reached_slow[0] == pytest.approx(5.0)


def test_a_described_move_travels_at_the_speed_it_states(microscope: Microscope) -> None:
    """What the description says of a variable is what its simulated driver takes."""
    assert microscope.values is not None
    assert microscope.values.instrument.variables["stage.x"].speed == 50000.0
    assert microscope.values.drivers["stage.x"].speed == 50000.0
