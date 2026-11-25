"""The drivers of what no hardware reaches: a value that is wherever it is told, at once or at the
speed its variable states."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from arkitekt import Task

from newswitch.drivers.base import Driver, Report


class Simulated:
    """A value that is wherever it is told, at once."""

    def start(self, initial: Any) -> Any:  # noqa: ANN401 - whatever the variable holds
        """It starts where it was described to."""
        return initial

    def set(self, value: Any, report: Report, task: Task | None = None) -> None:  # noqa: ANN401
        """There it is."""
        report(value)

    @classmethod
    def set_together(
        cls, targets: Iterable[tuple[Driver, Any, Report]], task: Task | None = None
    ) -> None:
        """One after the other: there is nothing to wait for."""
        for driver, value, report in targets:
            driver.set(value, report, task)


#: At most this many reports per second of a move at a real speed, so as not to flood clients.
REPORTS_PER_S = 20
#: And at most this many in all.
MAX_REPORTS = 200


class SimulatedMove(Simulated):
    """A value that travels there at the speed its variable states; with none, it is there at once."""

    def __init__(self, speed: float | None, current: Callable[[], float]) -> None:
        """A move at `speed` per second, from where `current` says it is."""
        self.speed = speed
        self.current = current

    @classmethod
    def set_together(
        cls, targets: Iterable[tuple[Driver, Any, Report]], task: Task | None = None
    ) -> None:
        """Together, in as long as the slowest takes."""
        import koil

        moves = [(d, d.current(), float(v), report) for d, v, report in targets]
        travel_s = max(
            (abs(to - frm) / d.speed for d, frm, to, _ in moves if d.speed),
            default=0.0,
        )
        reports = max(1, min(MAX_REPORTS, int(travel_s * REPORTS_PER_S)))
        for index in range(1, reports + 1):
            if task is not None:
                task.pausepoint()
            if travel_s:
                koil.sleep(travel_s / reports)
            for _, frm, to, report in moves:
                report(frm + (to - frm) * index / reports)
            if task is not None:
                task.progress(int(index / reports * 100))

    def set(self, value: Any, report: Report, task: Task | None = None) -> None:  # noqa: ANN401
        """Travel there."""
        type(self).set_together([(self, value, report)], task)
