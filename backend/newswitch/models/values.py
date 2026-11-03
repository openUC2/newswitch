"""What can change on a microscope and what it is now: one entry per variable, by what it does."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MoveValue:
    """A value along a direction, and what moving it does."""

    name: str
    value: float
    unit: str
    along: str
    """Across the optical axis (x, y), or along it (axis)."""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    does: list[str] = field(default_factory=list)
    """What changing it was found to change, on any detector: position, blur, scale, colour, light."""
    speed: Optional[float] = None
    """How fast it moves, in its unit a second, where the description says: what a move takes."""


@dataclass
class SwapOption:
    """One thing a swap can put in place."""

    slot: int
    label: str
    kind: str
    facts: dict[str, str] = field(default_factory=dict)


@dataclass
class SwapValue:
    """Which of several things is in place, and what swapping it does."""

    name: str
    value: int
    label: str
    """What is in place, as it reads."""
    options: list[SwapOption] = field(default_factory=list)
    does: list[str] = field(default_factory=list)


@dataclass
class TuneValue:
    """A value of an element, and what tuning it does."""

    name: str
    value: float
    unit: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    does: list[str] = field(default_factory=list)


@dataclass
class LightSource:
    """Where light starts, and how much of it there is now."""

    name: str
    emits: str
    wavelength: float
    """Where most of its light is, in nm."""
    lines: list[float]
    """All it emits, in nm."""
    color: str
    """The colour of the theme its wavelength reads as."""
    max_power: float
    """In mW."""
    power: float
    """In mW."""
    lit_power: float
    """What to come on at: the last power it was on at, or else its maximum."""
    on: bool
    power_variable: Optional[str] = None
    """The variable that tunes it; none: it is at its maximum, whatever anyone asks."""
