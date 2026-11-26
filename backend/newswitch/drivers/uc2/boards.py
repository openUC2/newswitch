"""The UC2 boards of a microscope, by name: always there, empty on a microscope without one.

Each board is a bus (`newswitch.protocols.uc2.UC2BusManager`): CANopen or REST on real hardware, or
the virtual bus (`newswitch.simulation.uc2_bus`) when the run simulates it; which one is the
composition root's to say (`newswitch.microscope.parts.build_uc2_boards`). An action about a board
itself (what is on its bus, its firmware, its galvo) names the board, chosen from those
`UC2State.boards` lists; what a board moves or lights is a variable, driven through `Values`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from typing import Annotated

from arkitekt.widgets import withStateChoices

from newswitch.protocols.uc2 import UC2BusManager
from newswitch.states.uc2 import UC2State

#: A board, chosen from those the microscope has.
BoardName = Annotated[str, withStateChoices("self.uc2.boards")]


class UC2Boards:
    """The buses of a microscope's UC2 boards, by the name the description gives each."""

    def __init__(self, buses: Mapping[str, UC2BusManager], state: UC2State) -> None:
        """The boards `buses`, listed in `state`."""
        self.buses = dict(buses)
        self.state = state
        state.boards = list(self.buses)

    def __getitem__(self, board: str) -> UC2BusManager:
        """The bus of `board`.

        Raises:
            ValueError: There is no such board.
        """
        if board not in self.buses:
            have = sorted(self.buses) or "none"
            raise ValueError(f"no UC2 board {board!r} on this microscope: it has {have}")
        return self.buses[board]

    def __iter__(self) -> Iterator[UC2BusManager]:
        """Each bus."""
        return iter(self.buses.values())

    def __len__(self) -> int:
        return len(self.buses)

    async def abackground(self) -> None:
        """Connect every bus and pump it until shutdown; with no board, there is nothing to do."""
        await asyncio.gather(*(bus.abackground() for bus in self))
