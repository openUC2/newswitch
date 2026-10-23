"""Events the UC2 bus reports (positions, motion done, homing, buttons, ...)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

STAGE_AXES = ("X", "Y", "Z", "A")


@dataclass(frozen=True)
class PositionUpdate:
    """Live position telemetry for one stage axis (micrometers)."""

    axis: str
    position: float


@dataclass(frozen=True)
class MotionDone:
    """A stage axis finished its motion at ``position`` (micrometers)."""

    axis: str
    position: float


@dataclass(frozen=True)
class HomingChanged:
    """Homing phase change for an axis (0=idle, 1=homing, 2=done, 3=timeout)."""

    axis: str
    status: int


@dataclass(frozen=True)
class EStopChanged:
    """The hardware emergency-stop state changed."""

    active: bool


@dataclass(frozen=True)
class ButtonPressed:
    """A hardware button / firmware key-value event was received."""

    key: Optional[str]
    data: Any


@dataclass(frozen=True)
class NodeSeen:
    """A bus node announced itself (CAN heartbeat or firmware identity)."""

    node_id: int
    nmt_state: int


@dataclass(frozen=True)
class BusError:
    """A transport-level error occurred (link loss, protocol error)."""

    message: str


UC2Event = Union[
    PositionUpdate,
    MotionDone,
    HomingChanged,
    EStopChanged,
    ButtonPressed,
    NodeSeen,
    BusError,
]
