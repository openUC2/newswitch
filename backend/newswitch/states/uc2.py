"""The UC2 state: what the bus reports of the board."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from newswitch.models.uc2 import UC2Node


@dataclass
class UC2State:
    """Connection, identity, and safety state of the UC2 hardware bus."""

    boards: list[str] = field(default_factory=list)
    """The boards, by name: what a board's action can be asked of; empty without one."""
    connected: bool = False
    transport: str = "virtual"
    firmware: str = ""
    estop_active: bool = False
    nodes_online: list[int] = field(default_factory=list)
    last_error: str = ""
    board: Optional[UC2Node] = None
    """The board on the port, as it identified itself (`uc2_scan_nodes`)."""
    nodes: list[UC2Node] = field(default_factory=list)
    """The CAN nodes, as the last scan found them."""
    flashing: Optional[str] = None
    """What is being flashed, and how far (`update_firmware`); None: nothing."""
