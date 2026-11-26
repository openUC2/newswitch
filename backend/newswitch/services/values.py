"""What every variable of a microscope is now, and the one way of changing it.

Everything goes through `Values.set`: it takes a variable to its value through its driver, publishes
what that became, and has the optics find out what it means. That is why there is one place to look,
and why nothing can change a value and leave what is published behind.

A published entry is replaced along with its whole field rather than changed where it is: arkitekt
takes over the class of what is published, so the plain values are kept here and copies go out.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from arkitekt import Task

from newswitch.drivers.base import Driver, Homes, Report, Stops, Unwired
from newswitch.instrument import spec
from newswitch.instrument.roles import Roles
from newswitch.instrument.spec import Instrument, Variable
from newswitch.models.values import LightSource, MoveValue, SwapOption, SwapValue, TuneValue
from newswitch.services.element_facts import facts_of, spectrum_color
from newswitch.states.values import MoveState, SourceState, SwapState, TuneState


def _in_range(variable: Variable, value: float) -> float:
    """`value`, as far as the range `variable` states allows it."""
    low = -float("inf") if variable.min is None else variable.min
    high = float("inf") if variable.max is None else variable.max
    return max(low, min(high, value))


#: How a unit reads, where its name in the description is what a keyboard has.
_READS_AS = {"um": "µm", "deg": "°"}


def _preset(instrument: Any, source: str) -> float | None:  # noqa: ANN401 - the instrument
    """What a source comes on at, as its description states it (its power's ``lit``)."""
    tune = instrument.variables.get(f"{source}.power")
    return getattr(tune, "lit", None)


def _copied(entries: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Copies of what is kept here: publishing turns an entry into another class, for good."""
    return {cube: {short: replace(e) for short, e in by.items()} for cube, by in entries.items()}


def _label(element: spec.Element, slot: int) -> str:
    return getattr(element, "name", None) or f"Slot {slot}"


class Values:
    """Holds what every variable is, and publishes it, by what the variable does."""

    def __init__(
        self,
        instrument: Instrument,
        move_state: MoveState,
        swap_state: SwapState,
        tune_state: TuneState,
        source_state: SourceState,
        drivers: Mapping[str, Driver] | None = None,
        *,
        unwired: Unwired,
    ) -> None:
        """The values of `instrument`, at what its `drivers` say they start at.

        A variable with no driver here gets the one `unwired` builds: what the composition root
        chose for what no hardware reaches (`newswitch.simulation.drivers.unwired`).
        """
        self.instrument = instrument
        self.roles = Roles(instrument)
        self.move_state = move_state
        self.swap_state = swap_state
        self.tune_state = tune_state
        self.source_state = source_state
        self.on_change: Callable[[], None] = lambda: None
        self._lock = threading.RLock()
        self.drivers: dict[str, Driver] = {
            name: (drivers or {}).get(name)
            or unwired(variable, lambda name=name: self._values[name])
            for name, variable in instrument.variables.items()
        }
        self._values: dict[str, Any] = instrument.initial_state()
        for name, driver in self.drivers.items():
            self._values[name] = driver.start(self._values[name])
        self._lit = {
            source: self._values.get(f"{source}.power", 0.0)
            or _preset(instrument, source)
            or instrument.cubes[source].element_at(self._values).max_power
            for source in instrument.sources()
        }
        self._publish_all()

    def __getitem__(self, name: str) -> Any:  # noqa: ANN401 - whatever the variable holds
        """What the variable `name` is now."""
        return self._values[name]

    def snapshot(self) -> dict[str, Any]:
        """Every value now: what the optics take."""
        return dict(self._values)

    def set(
        self,
        targets: Mapping[str, Any],
        relative: bool = False,
        task: Task | None = None,
    ) -> None:
        """Take variables to values, or by them, and return once they are there.

        Raises:
            ValueError: One of them is not a variable, or a swap to a slot it does not have. Then
                nothing has moved.
        """
        wanted = {name: self._target(name, value, relative) for name, value in targets.items()}
        groups: dict[type, list[tuple[Driver, Any, Report]]] = defaultdict(list)
        for name, value in wanted.items():
            driver = self.drivers[name]
            groups[type(driver)].append((driver, value, self.reporter(name)))
        try:
            for driver_type, group in groups.items():
                driver_type.set_together(group, task)
        finally:
            # What did move has moved, whichever failed.
            self.on_change()

    def _target(self, name: str, value: Any, relative: bool) -> Any:  # noqa: ANN401
        variable = self._known(name)
        if variable.verb == "swaps":
            return self._slot(variable, value)
        wanted = _in_range(variable, value + (self._values[name] if relative else 0.0))
        limit = self._power_limit(variable)
        return wanted if limit is None else min(wanted, limit)

    def _known(self, name: str) -> Variable:
        variable = self.instrument.variables.get(name)
        if variable is None:
            raise ValueError(f"{name} is no variable: {sorted(self.instrument.variables)}")
        return variable

    @staticmethod
    def _slot(variable: spec.Swap, value: Any) -> int:  # noqa: ANN401
        """The slot `value` means: a plan's numbers all arrive as floats."""
        for slot in variable.slots:
            if slot == value:
                return slot
        raise ValueError(f"{variable.name} has no slot {value}: {sorted(variable.slots)}")

    def _power_limit(self, variable: Variable) -> float | None:
        """How far a source's power goes, whatever its tune states."""
        if variable.verb == "tunes" and variable.name == f"{variable.cube}.power":
            element = self.instrument.cubes[variable.cube].element_at(self._values)
            if isinstance(element, spec.Source):
                return element.max_power
        return None

    def resolved(self, targets: Mapping[str, Any]) -> dict[str, Any]:
        """`targets`, each as what its variable holds: a plan's numbers all arrive as floats."""
        return {
            name: self._slot(variable, value)
            if (variable := self._known(name)).verb == "swaps"
            else value
            for name, value in targets.items()
        }

    def check(self, targets: Mapping[str, Any]) -> None:
        """Refuse what `set` would otherwise bring into range: a plan says what it means.

        Raises:
            ValueError: One of them is not a variable, not a slot it has, or out of its range.
        """
        for name, value in targets.items():
            variable = self._known(name)
            if variable.verb == "swaps":
                self._slot(variable, value)
                continue
            limit = self._power_limit(variable)
            highest = variable.max if limit is None else limit
            if (variable.min is not None and value < variable.min) or (
                highest is not None and value > highest
            ):
                raise ValueError(
                    f"{name} goes from {variable.min} to {highest} {variable.unit}, not to {value}"
                )

    def _cubes_whose_moves(self, can: type) -> list[str]:
        """The cubes with a move, every one of whose moves has a driver that `can`."""
        cubes: dict[str, bool] = {}
        for name, variable in self.instrument.variables.items():
            if variable.verb == "moves":
                cubes[variable.cube] = cubes.get(variable.cube, True) and isinstance(
                    self.drivers[name], can
                )
        return [cube for cube, every in cubes.items() if every]

    def moves_of(self, cube: str) -> list[str]:
        """The moves of `cube`: those along ``z`` first (homing a stage, it moves away from the
        sample first), then the rest as the description has them.

        Raises:
            ValueError: `cube` has no move.
        """
        found = [
            name
            for name, variable in self.instrument.variables.items()
            if variable.verb == "moves" and variable.cube == cube
        ]
        if not found:
            moving = sorted(
                {v.cube for v in self.instrument.variables.values() if v.verb == "moves"}
            )
            raise ValueError(f"{cube} moves nothing; what moves: {moving or 'nothing'}")
        return sorted(found, key=lambda name: name.split(".", 1)[1] != "z")

    def home(self, names: list[str], task: Task | None = None) -> None:
        """Home variables one after the other, in this order: each goes to its reference, and is
        known to be where its driver then says.

        Raises:
            ValueError: One of them is not a variable, or its driver cannot home. Then nothing has
                moved.
        """
        drivers = {name: self.drivers[self._known(name).name] for name in names}
        cannot = [name for name, driver in drivers.items() if not isinstance(driver, Homes)]
        if cannot:
            raise ValueError(f"{', '.join(cannot)} cannot be homed")
        try:
            for index, (name, driver) in enumerate(drivers.items()):
                if task is not None:
                    task.progress(int(100 * index / len(drivers)), f"homing {name}")
                driver.home(self.reporter(name), task)  # type: ignore[union-attr]
        finally:
            self.on_change()

    def stop(self, names: list[str]) -> None:
        """Stop variables where they are, while a move may still be taking them somewhere. It
        holds nothing a move holds: it is meant to run beside one.

        Raises:
            ValueError: One of them is not a variable, or its driver cannot stop. Then nothing has
                stopped.
        """
        drivers = {name: self.drivers[self._known(name).name] for name in names}
        cannot = [name for name, driver in drivers.items() if not isinstance(driver, Stops)]
        if cannot:
            raise ValueError(f"{', '.join(cannot)} cannot be stopped")
        for driver in drivers.values():
            driver.stop()  # type: ignore[union-attr]

    def stepped(self, name: str, value: Any) -> None:  # noqa: ANN401
        """A wire took a variable there: nothing is commanded, it is only known to be there now.

        Where it already is, nothing is published: a board reports its positions over and over,
        standing still too, and an unchanged state is no update.
        """
        with self._lock:
            if name in self._values and self._values[name] == value:
                return
        self.reporter(name)(value)
        self.on_change()

    def reporter(self, name: str) -> Report:
        """What publishes where a variable got to, on its way."""

        def report(value: Any) -> None:  # noqa: ANN401 - whatever the variable holds
            with self._lock:
                self._values[name] = value
                self._publish(name)

        return report

    def _publish(self, name: str) -> None:
        """Publish the entry of one variable, in a new copy of its field."""
        variable = self.instrument.variables[name]
        cube, short = variable.cube, name.split(".", 1)[1]
        if variable.verb == "moves":
            self._moves[cube][short] = replace(self._moves[cube][short], current=self._values[name])
            self.move_state.moves = _copied(self._moves)
        elif variable.verb == "swaps":
            self._swaps[cube][short] = replace(
                self._swaps[cube][short],
                current=self._values[name],
                label=_label(variable.slots[self._values[name]], self._values[name]),
            )
            self.swap_state.swaps = _copied(self._swaps)
        else:
            self._tunes[cube][short] = replace(self._tunes[cube][short], current=self._values[name])
            self.tune_state.tunes = _copied(self._tunes)
            if cube in self._sources and short == "power":
                self._publish_source(cube)

    def _publish_source(self, source: str) -> None:
        power = self._values[f"{source}.power"]
        if power > 0.0:
            self._lit[source] = power
        self._sources[source] = replace(
            self._sources[source],
            power=power,
            lit_power=self._lit[source],
            on=power > 0.0,
        )
        self.source_state.sources = {name: replace(s) for name, s in self._sources.items()}

    def _publish_all(self) -> None:
        moves: dict[str, dict[str, MoveValue]] = defaultdict(dict)
        swaps: dict[str, dict[str, SwapValue]] = defaultdict(dict)
        tunes: dict[str, dict[str, TuneValue]] = defaultdict(dict)
        for name, variable in self.instrument.variables.items():
            short = name.split(".", 1)[1]
            value = self._values[name]
            does = self.roles.does(name)
            if variable.verb == "moves":
                moves[variable.cube][short] = MoveValue(
                    name=name,
                    current=value,
                    unit=_READS_AS.get(variable.unit, variable.unit),
                    along=variable.along,
                    minimum=variable.min,
                    maximum=variable.max,
                    step=variable.step,
                    does=does,
                    speed=variable.speed,
                )
            elif variable.verb == "swaps":
                swaps[variable.cube][short] = SwapValue(
                    name=name,
                    current=value,
                    label=_label(variable.slots[value], value),
                    options=[
                        SwapOption(
                            slot=slot,
                            label=_label(element, slot),
                            kind=element.kind,
                            facts=facts_of(element),
                        )
                        for slot, element in variable.slots.items()
                    ],
                    does=does,
                )
            else:
                tunes[variable.cube][short] = TuneValue(
                    name=name,
                    current=value,
                    unit=_READS_AS.get(variable.unit, variable.unit),
                    minimum=variable.min,
                    maximum=variable.max,
                    step=variable.step,
                    does=does,
                )
        self._moves, self._swaps, self._tunes = dict(moves), dict(swaps), dict(tunes)
        self.move_state.moves = _copied(self._moves)
        self.swap_state.swaps = _copied(self._swaps)
        self.tune_state.tunes = _copied(self._tunes)
        variables = self.instrument.variables
        self.move_state.names = [n for n, v in variables.items() if v.verb == "moves"]
        self.move_state.homes = self._cubes_whose_moves(Homes)
        self.move_state.stops = self._cubes_whose_moves(Stops)
        self.swap_state.names = [n for n, v in variables.items() if v.verb == "swaps"]
        self.swap_state.homes = [
            n for n in self.swap_state.names if isinstance(self.drivers[n], Homes)
        ]
        self.tune_state.names = [n for n, v in variables.items() if v.verb == "tunes"]
        sources = {}
        for source in self.instrument.sources():
            element = self.instrument.cubes[source].element_at(self._values)
            variable = f"{source}.power"
            power = self._values.get(variable, element.max_power)
            sources[source] = LightSource(
                name=source,
                emits=element.emits,
                wavelength=element.wavelength,
                lines=[line.center for line in element.spectrum],
                color=spectrum_color(element.wavelength),
                max_power=element.max_power,
                power=power,
                lit_power=self._lit[source],
                on=power > 0.0,
                power_variable=variable if variable in self.instrument.variables else None,
            )
        self._sources = sources
        self.source_state.sources = {name: replace(s) for name, s in sources.items()}
