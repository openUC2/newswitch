"""Where a detector sends the frames it acquires: a `FrameSink`.

A detector only produces: it starts the sink when it streams and hands it every new frame,
from its own thread. Who watches is the entrypoint's business: the websocket live view
(`FrameBroadcaster`, ``main_fastapi.py``) or lovekit streams (`newswitch.infra.streaming.lovekit`,
``app.py``).
"""

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class FrameSink(Protocol):
    """Takes the frames detectors acquire."""

    def start_broadcasting(self) -> None:
        """A detector starts streaming: frames follow."""
        ...

    def broadcast_sync(self, detector: str, frame: np.ndarray) -> None:
        """A new frame of `detector`, which the sink keeps as it is: the detector
        does not write to it afterwards. Called from the detector's thread."""
        ...


@runtime_checkable
class NewestOnlySink(Protocol):
    """A sink that keeps only the newest frame per detector and says when it wants one: not while
    the last is still untaken (`LovekitSink`). A detector asks before it copies a frame."""

    def wants(self, detector: str) -> bool:
        """Whether a new frame of `detector` is wanted now."""
        ...


@runtime_checkable
class I420Sink(Protocol):
    """A sink that also takes frames a detector's driver already scaled and converted to I420
    (`LovekitSink`): sent as they are, with no conversion in Python."""

    i420_width: int
    """How wide such a frame may be: what is sent."""

    def broadcast_i420(self, detector: str, width: int, height: int, data: np.ndarray) -> None:
        """A new frame of `detector`, `width` x `height` pixels, in I420."""
        ...
