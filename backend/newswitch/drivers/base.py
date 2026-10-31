"""What a driver is, which one a name means, and the one that needs no hardware.

A driver is small: it takes a value somewhere and says where it got to. Which one a variable has is
what ``hardware.actuators.<name>.driver`` says; third parties add their own with `register_driver`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol

from arkitekt import Task

from newswitch.instrument.errors import SpecError
from newswitch.instrument.spec import Variable

#: Called with where a value got to, on its way.
Report = Callable[[Any], None]


class Driver(Protocol):
    """Takes one variable to a value."""

    def start(self, initial: Any) -> Any:  # noqa: ANN401 - whatever the variable holds
        """Where the variable is when it opens; it was described to start at `initial`."""
        ...

    def set(self, value: Any, report: Report, task: Task | None = None) -> None:  # noqa: ANN401
        """Take the variable to `value`, reporting where it got to, and return once it is there."""
        ...

    @classmethod
    def set_together(
        cls, targets: Iterable[tuple[Driver, Any, Report]], task: Task | None = None
    ) -> None:
        """Take several variables, all of this driver, to their values: at once, if it can."""
        ...


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


#: Builds a driver: from the variable it drives, the actuator's options, and what it may need.
Factory = Callable[[Variable, Mapping[str, Any], Mapping[str, Any]], Driver]

_drivers: dict[str, Factory] = {}


def register_driver(name: str, factory: Factory) -> None:
    """Make a driver available as ``driver: name``."""
    _drivers[name] = factory


def build_driver(
    name: str, variable: Variable, options: Mapping[str, Any], context: Mapping[str, Any]
) -> Driver:
    """The driver `name` of `variable`.

    Raises:
        SpecError: No driver has that name, or it refuses these options.
    """
    if name not in _drivers:
        raise SpecError(f"{variable.name}: no driver is called {name}: {sorted(_drivers)}")
    try:
        return _drivers[name](variable, options, context)
    except TypeError as error:
        raise SpecError(f"{variable.name}: driver {name}: {error}") from error
