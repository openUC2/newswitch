"""Where a detector sends the frames it acquires: a `FrameSink`.

A detector only produces: it starts the sink when it streams and hands it every new frame,
from its own thread. Who watches is the entrypoint's business: the websocket live view
(`FrameBroadcaster`, ``main_fastapi.py``) or lovekit streams (`newswitch.broadcasters.lovekit`,
``main_arkitekt.py``).
"""

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class FrameSink(Protocol):
    """Takes the frames detectors acquire."""

    def start_broadcasting(self) -> None:
        """A detector starts streaming: frames follow."""
        ...

    def broadcast_sync(self, slot: int, frame: np.ndarray) -> None:
        """A new frame of the detector in `slot`, which the sink keeps as it is: the detector
        does not write to it afterwards. Called from the detector's thread."""
        ...
