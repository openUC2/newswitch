"""What each variable is for: found by nudging it, and never stated.

The compiler can tell what changing a variable does to what a detector sees. That answers everything
the description used to have to say about its parts: what moves the image sideways changes where it
looks, what focuses it changes its blur but not its size.

Finding never guesses. Asked for the one thing that does something, it refuses when there are none or
several, and lists them, so that a second focus motor stops an autofocus with a clear message rather
than silently changing which motor it drives. A call can name the one it means.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property

from newswitch.instrument.compiler import difference, traced_answer
from newswitch.instrument.spec import Instrument, Move, Variable


def _nudge(variable: Variable) -> float:
    """How far to move a variable to see what it does: a part of its range, not its finest step.

    A piezo's 10 nm step changes nothing a detector can tell, and it is still what focuses.
    """
    assert variable.step is not None
    if variable.min is not None and variable.max is not None:
        return max(variable.step, (variable.max - variable.min) / 20.0)
    return variable.step * 10.0


@dataclass(frozen=True)
class Roles:
    """What the variables of `instrument` were found to do, from where it starts."""

    instrument: Instrument

    @cached_property
    def found(self) -> Mapping[str, Mapping[str, frozenset[str]]]:
        """By detector, then by variable: what changing it changes."""
        state = self.instrument.initial_state()
        table: dict[str, dict[str, frozenset[str]]] = {}
        for detector in self.instrument.detectors():
            before = traced_answer(self.instrument, detector, state)
            table[detector] = {}
            for name, variable in self.instrument.variables.items():
                if variable.verb == "swaps":
                    nudges = [slot for slot in variable.slots if slot != state[name]]
                else:
                    nudges = [state[name] + _nudge(variable)]
                changes: set[str] = set()
                for nudge in nudges:
                    after = traced_answer(self.instrument, detector, {**state, name: nudge})
                    changes |= set(difference(before, after))
                table[detector][name] = frozenset(changes)
        return table

    def does(self, variable: str) -> list[str]:
        """What changing `variable` changes on any detector."""
        return sorted({change for rows in self.found.values() for change in rows[variable]})

    def _moves(self) -> list[Move]:
        return [v for v in self.instrument.variables.values() if v.verb == "moves"]

    def sideways(self, detector: str, along: str) -> list[Move]:
        """What moves where `detector` looks along x or y."""
        return [
            move
            for move in self._moves()
            if move.along == along and "position" in self.found[detector][move.name]
        ]

    def focuses(self, detector: str) -> list[Move]:
        """What changes how sharp `detector`'s image is, and not how large."""
        return [
            move
            for move in self._moves()
            if "blur" in self.found[detector][move.name]
            and "scale" not in self.found[detector][move.name]
        ]

    def one(self, what: str, candidates: list[Move], named: str | None = None) -> Move:
        """The one of `candidates`, or the one `named`.

        Raises:
            ValueError: There is none, or several and none is named; or the one named is no such.
        """
        names = [move.name for move in candidates]
        if named is not None:
            if named not in names:
                raise ValueError(f"{named} is no {what}: that is {', '.join(names) or 'nothing'}")
            return next(move for move in candidates if move.name == named)
        if not candidates:
            raise ValueError(f"Nothing here is a {what}")
        if len(candidates) > 1:
            raise ValueError(f"Several things are a {what}: {', '.join(names)}. Name one.")
        return candidates[0]

    def focus(self, detector: str, named: str | None = None) -> Move:
        """The one thing that focuses `detector`, or the one `named`."""
        return self.one(f"focus of {detector}", self.focuses(detector), named)

    def x(self, detector: str, named: str | None = None) -> Move:
        """The one thing that moves `detector`'s view along x, or the one `named`."""
        return self.one(f"sideways move of {detector}", self.sideways(detector, "x"), named)

    def y(self, detector: str, named: str | None = None) -> Move:
        """The one thing that moves `detector`'s view along y, or the one `named`."""
        return self.one(f"sideways move of {detector}", self.sideways(detector, "y"), named)
