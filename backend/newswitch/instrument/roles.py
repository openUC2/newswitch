"""What each variable is for: found by nudging it, and never stated.

The compiler can tell what changing a variable does to what a detector sees. That answers everything
the description used to have to say about its parts: what moves the image sideways changes where it
looks, what focuses it changes its blur but not its size.

Finding never guesses. Asked for the one thing that does something, it refuses when there are none or
several, and lists them, so that a second focus motor stops an autofocus with a clear message rather
than silently changing which motor it drives. A call can name the one it means.
"""

from __future__ import annotations

from typing import Any

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property

from newswitch.instrument.compiler import changes_between, nudge_of, traced_or_dark
from newswitch.instrument.spec import Instrument, Move


@dataclass(frozen=True)
class Roles:
    """What the variables of `instrument` were found to do, from where it starts.

    Per detector and per sample it can see: where a switch picks which sample a detector sees,
    what moves its view on one is not what moves it on the other.
    """

    instrument: Instrument

    def start_seeing(self, detector: str, sample: str) -> dict[str, Any]:
        """The state nearest where the instrument starts in which `detector` sees `sample`: as it
        starts, with as few of the switches on the way changed as will do."""
        start = self.instrument.initial_state()
        states = [
            state
            for state in self.instrument.switch_states(detector)
            if self.instrument.sample_of(detector, state) == sample
        ]
        return min(states, key=lambda state: sum(state[k] != start[k] for k in start))

    @cached_property
    def found(self) -> Mapping[tuple[str, str], Mapping[str, frozenset[str]]]:
        """By detector and sample, then by variable: what changing it changes."""
        table: dict[tuple[str, str], dict[str, frozenset[str]]] = {}
        for detector in self.instrument.detectors():
            for sample in self.instrument.samples_of(detector):
                state = self.start_seeing(detector, sample)
                before = traced_or_dark(self.instrument, detector, state)
                row: dict[str, frozenset[str]] = {}
                for name, variable in self.instrument.variables.items():
                    if variable.verb == "swaps":
                        nudges = [slot for slot in variable.slots if slot != state[name]]
                    else:
                        nudges = [state[name] + nudge_of(variable)]
                    changes: set[str] = set()
                    for nudge in nudges:
                        changes |= set(
                            changes_between(
                                self.instrument, detector, state, before, {**state, name: nudge}
                            )
                        )
                    row[name] = frozenset(changes)
                table[detector, sample] = row
        return table

    def does(self, variable: str) -> list[str]:
        """What changing `variable` changes on any detector."""
        return sorted({change for rows in self.found.values() for change in rows[variable]})

    def _moves(self) -> list[Move]:
        return [v for v in self.instrument.variables.values() if v.verb == "moves"]

    def _row(self, detector: str, sample: str | None) -> Mapping[str, frozenset[str]]:
        """What each variable does for `detector` seeing `sample`: the one it can, if not named.

        Raises:
            ValueError: It can see several, and none is named.
        """
        if sample is None:
            seen = self.instrument.samples_of(detector)
            if len(seen) != 1:
                raise ValueError(f"{detector} can see {seen}: say which")
            sample = seen[0]
        return self.found[detector, sample]

    def sideways(self, detector: str, along: str, sample: str | None = None) -> list[Move]:
        """What moves where `detector` looks along x or y, on `sample`."""
        row = self._row(detector, sample)
        return [
            move for move in self._moves() if move.along == along and "position" in row[move.name]
        ]

    def focuses(self, detector: str, sample: str | None = None) -> list[Move]:
        """What changes how sharp `detector`'s image of `sample` is, and not how large."""
        row = self._row(detector, sample)
        return [
            move
            for move in self._moves()
            if "blur" in row[move.name] and "scale" not in row[move.name]
        ]

    def plane_um(self, detector: str, values: Mapping[str, Any]) -> float:
        """Where along the axis what `detector` sees is, in the sample.

        What moves the sample and what focuses it, less what moves a light sheet: moving the light
        is moving the sample the other way, so a plane has one z whichever went there.
        """
        sample = self.instrument.seen_sample(detector, values)
        sheets = {move.name for move in self.instrument.sheet_moves(sample)}
        along = {
            move.name
            for move in (*self.instrument.sample_moves(sample), *self.focuses(detector, sample))
        }
        return sum(float(values[name]) for name in along - sheets) - sum(
            float(values[name]) for name in sheets
        )

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

    def focus(self, detector: str, named: str | None = None, sample: str | None = None) -> Move:
        """The one thing that focuses `detector` on `sample`, or the one `named`."""
        return self.one(f"focus of {detector}", self.focuses(detector, sample), named)

    def x(self, detector: str, named: str | None = None, sample: str | None = None) -> Move:
        """The one thing that moves `detector`'s view of `sample` along x, or the one `named`."""
        return self.one(f"sideways move of {detector}", self.sideways(detector, "x", sample), named)

    def y(self, detector: str, named: str | None = None, sample: str | None = None) -> Move:
        """The one thing that moves `detector`'s view of `sample` along y, or the one `named`."""
        return self.one(f"sideways move of {detector}", self.sideways(detector, "y", sample), named)
