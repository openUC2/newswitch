"""The newest frame of every detector, for the websocket live view.

A detector hands its frames over from its own thread, often holding its own lock, so
`broadcast_sync` only keeps the frame and wakes whoever waits. A subscriber takes the
newest frame whenever it is ready for one, so a slow viewer skips frames. Every frame stands
alone, so a viewer can join at any time and leave out any frame.
"""

import asyncio
import threading
import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import Optional

import numpy as np


@dataclass(eq=False)
class DetectorFrameMessage:
    """A frame of a detector, numbered in the order it came."""

    detector: str
    sequence: int
    time_s: float
    data: np.ndarray
    #: The frame as sent, by binning factor: viewers of one size share the work.
    messages: dict[str, bytes] = field(default_factory=dict)


class FrameSubscription:
    """One viewer of a detector: `next_frame` waits for a frame it has not seen yet."""

    def __init__(self, broadcaster: "FrameBroadcaster", detector: str) -> None:
        """Watch `detector` of `broadcaster`, from the running event loop."""
        self._broadcaster = broadcaster
        self._detector = detector
        self._loop = asyncio.get_running_loop()
        self._changed = asyncio.Event()
        self._last_sequence: Optional[int] = None

    def __enter__(self) -> "FrameSubscription":
        """Start watching."""
        self._broadcaster._add(self._detector, self)
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Stop watching."""
        self._broadcaster._remove(self._detector, self)

    def _notify(self) -> None:
        """A new frame came; called from the detector's thread."""
        try:
            self._loop.call_soon_threadsafe(self._changed.set)
        except RuntimeError:  # the event loop is closed: the server is shutting down
            pass

    async def next_frame(self) -> DetectorFrameMessage:
        """The newest frame, once there is one this subscription has not returned."""
        while True:
            self._changed.clear()
            frame = self._broadcaster.newest(self._detector)
            if frame is not None and frame.sequence != self._last_sequence:
                self._last_sequence = frame.sequence
                return frame
            await self._changed.wait()


class FrameBroadcaster:
    """Keeps the newest frame per detector and tells the subscribers of that detector."""

    def __init__(self) -> None:
        """Nothing broadcast, nobody watching."""
        self._broadcasting = False
        self._lock = threading.Lock()
        self._newest: dict[str, DetectorFrameMessage] = {}
        self._subscriptions: dict[str, set[FrameSubscription]] = {}

    def start_broadcasting(self) -> None:
        """A detector starts streaming: frames follow."""
        self._broadcasting = True

    @property
    def is_broadcasting(self) -> bool:
        """Whether a detector has started streaming."""
        return self._broadcasting

    def subscribe(self, detector: str) -> FrameSubscription:
        """A subscription to `detector`, as a context manager; from the event loop."""
        return FrameSubscription(self, detector)

    def subscriber_count(self, detector: str) -> int:
        """How many subscriptions watch `detector`."""
        with self._lock:
            return len(self._subscriptions.get(detector, ()))

    def newest(self, detector: str) -> Optional[DetectorFrameMessage]:
        """The newest frame of `detector`, or None before the first one."""
        with self._lock:
            return self._newest.get(detector)

    def broadcast_sync(self, detector: str, frame: np.ndarray) -> None:
        """Keep `frame` as the newest of `detector`; called from the detector's thread.

        The frame is kept as it is, not copied: a detector must not write to it afterwards.
        """
        with self._lock:
            previous = self._newest.get(detector)
            sequence = 0 if previous is None else previous.sequence + 1
            self._newest[detector] = DetectorFrameMessage(detector, sequence, time.time(), frame)
            subscriptions = list(self._subscriptions.get(detector, ()))
        for subscription in subscriptions:
            subscription._notify()

    def _add(self, detector: str, subscription: FrameSubscription) -> None:
        with self._lock:
            self._subscriptions.setdefault(detector, set()).add(subscription)

    def _remove(self, detector: str, subscription: FrameSubscription) -> None:
        with self._lock:
            self._subscriptions.get(detector, set()).discard(subscription)
