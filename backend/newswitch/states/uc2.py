"""The UC2 state: what the bus reports of the board."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UC2State:
    """Connection, identity, and safety state of the UC2 hardware bus."""

    connected: bool = False
    transport: str = "virtual"
    firmware: str = ""
    estop_active: bool = False
    nodes_online: list[int] = field(default_factory=list)
    last_error: str = ""
