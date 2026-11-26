"""What can change on a microscope, by what it does, in the description's names.

Each is keyed by cube, then by variable, so that a view can bind it by name:
``self.move.moves.stage.z.current``. Nothing here has a default: it all comes from the description.

Beside them, each lists what an action can be asked to do it to: the choices of its argument
(``withStateChoices("self.move.homes")``). An empty list is a microscope without one.
"""

from dataclasses import dataclass, field

from newswitch.models.values import LightSource, MoveValue, SwapValue, TuneValue


@dataclass
class MoveState:
    """What moves."""

    moves: dict[str, dict[str, MoveValue]] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)
    """The variables that move (`move_one`)."""
    homes: list[str] = field(default_factory=list)
    """The cubes whose moves can be homed (`home_stage`)."""
    stops: list[str] = field(default_factory=list)
    """The cubes whose moves can be stopped (`stop_stage`)."""


@dataclass
class SwapState:
    """What is swapped."""

    swaps: dict[str, dict[str, SwapValue]] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)
    """The variables that swap (`swap`)."""
    homes: list[str] = field(default_factory=list)
    """The variables that swap and can be homed (`home_objective`)."""


@dataclass
class TuneState:
    """What is tuned."""

    tunes: dict[str, dict[str, TuneValue]] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)
    """The variables that are tuned (`tune`)."""


@dataclass
class SourceState:
    """Where light starts."""

    sources: dict[str, LightSource] = field(default_factory=dict)
