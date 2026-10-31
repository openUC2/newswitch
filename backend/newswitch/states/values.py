"""What can change on a microscope, by what it does, in the description's names.

Each is keyed by cube, then by variable, so that a view can bind it by name:
``self.MoveState.moves.stage.z.value``. Nothing here has a default: it all comes from the description.
"""

from dataclasses import dataclass, field

from newswitch.models.values import LightSource, MoveValue, SwapValue, TuneValue


@dataclass
class MoveState:
    """What moves."""

    moves: dict[str, dict[str, MoveValue]] = field(default_factory=dict)


@dataclass
class SwapState:
    """What is swapped."""

    swaps: dict[str, dict[str, SwapValue]] = field(default_factory=dict)


@dataclass
class TuneState:
    """What is tuned."""

    tunes: dict[str, dict[str, TuneValue]] = field(default_factory=dict)


@dataclass
class SourceState:
    """Where light starts."""

    sources: dict[str, LightSource] = field(default_factory=dict)
