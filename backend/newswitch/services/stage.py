"""What moves a detector's view: found from what the variables do, for what acquires."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dataclasses import dataclass

from arkitekt import Task

from newswitch.instrument.spec import Move
from newswitch.services.values import Values


@dataclass(frozen=True)
class Stage:
    """The sideways moves and the focus of one detector, as one thing to move.

    Which each is, is found (`instrument.roles`), and a routine that needs one that is not there, or
    cannot tell which it is, is refused before anything moves.
    """

    values: Values
    x_move: Move | None
    y_move: Move | None
    z_move: Move | None

    @property
    def state(self) -> Stage:
        """Where it is, and how far it can go."""
        return self

    def _limit(self, move: Move | None, limit: str, away: float) -> float:
        found = None if move is None else getattr(move, limit)
        return away if found is None else found

    def _at(self, move: Move | None) -> float:
        return 0.0 if move is None else float(self.values[move.name])

    @property
    def x(self) -> float:
        """Where it looks along x."""
        return self._at(self.x_move)

    @property
    def y(self) -> float:
        """Where it looks along y."""
        return self._at(self.y_move)

    @property
    def z(self) -> float:
        """Where it focuses."""
        return self._at(self.z_move)

    @property
    def min_x(self) -> float:
        """How far it goes along -x."""
        return self._limit(self.x_move, "min", -float("inf"))

    @property
    def max_x(self) -> float:
        """How far it goes along +x."""
        return self._limit(self.x_move, "max", float("inf"))

    @property
    def min_y(self) -> float:
        """How far it goes along -y."""
        return self._limit(self.y_move, "min", -float("inf"))

    @property
    def max_y(self) -> float:
        """How far it goes along +y."""
        return self._limit(self.y_move, "max", float("inf"))

    @property
    def min_z(self) -> float:
        """How far it focuses down."""
        return self._limit(self.z_move, "min", -float("inf"))

    @property
    def max_z(self) -> float:
        """How far it focuses up."""
        return self._limit(self.z_move, "max", float("inf"))

    def move(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        is_absolute: bool = False,
        task: Task | None = None,
    ) -> None:
        """Move there, or by that, and return once it is.

        Raises:
            ValueError: Nothing here moves along one of them.
        """
        targets = {}
        for what, move, value in (
            ("x", self.x_move, x),
            ("y", self.y_move, y),
            ("z", self.z_move, z),
        ):
            if value is None:
                continue
            if move is None:
                raise ValueError(f"Nothing here moves along {what}")
            targets[move.name] = value if is_absolute else self.values[move.name] + value
        if targets:
            self.values.set(targets, task=task)


def stage_of(
    values: Values,
    detector: str,
    focus: str | None = None,
    under: Mapping[str, Any] | None = None,
) -> Stage:
    """What moves `detector`'s view, and what focuses it: `focus`, if that is named. Of the sample
    it sees `under` a state, or now.

    Raises:
        ValueError: There are several of one, and it cannot be told which is meant.
        Dark: The switches send no light to it.
    """
    roles = values.roles
    sample = values.instrument.seen_sample(detector, values.snapshot() if under is None else under)
    x, y = roles.sideways(detector, "x", sample), roles.sideways(detector, "y", sample)
    z = roles.focuses(detector, sample)
    return Stage(
        values,
        roles.x(detector, sample=sample) if x else None,
        roles.y(detector, sample=sample) if y else None,
        roles.focus(detector, focus, sample) if z or focus is not None else None,
    )


def where(values: Values, detector: str) -> tuple[float, float, float]:
    """Where `detector` looks: the sum of whatever moves it along each way.

    That holds however many things do: it says where the view is, and asks none of them to go.
    """
    roles = values.roles
    now = values.snapshot()
    sample = values.instrument.seen_sample(detector, now)
    return (
        sum(float(now[move.name]) for move in roles.sideways(detector, "x", sample)),
        sum(float(now[move.name]) for move in roles.sideways(detector, "y", sample)),
        roles.plane_um(detector, now),
    )
