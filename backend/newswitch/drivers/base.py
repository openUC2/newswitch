"""What a driver is, and which one a name means.

A driver is small: it takes a value somewhere and says where it got to. Which one a variable has is
what ``hardware.actuators.<name>.driver`` says; third parties add their own with `register_driver`.
What no driver reaches is simulated (`newswitch.simulation.drivers`).
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


#: Builds the driver of a variable no hardware reaches: from the variable, and where it is now.
Unwired = Callable[[Variable, Callable[[], Any]], Driver]

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
