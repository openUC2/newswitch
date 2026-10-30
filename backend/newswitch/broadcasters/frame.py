"""The newest frame of every detector slot, for the websocket live view.

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
class SlotFrame:
    """A frame of a detector slot, numbered in the order it came."""

    slot: int
    sequence: int
    time_s: float
    data: np.ndarray
    #: The frame as sent, by binning factor: viewers of one size share the work.
    messages: dict[int, bytes] = field(default_factory=dict)


class FrameSubscription:
    """One viewer of a slot: `next_frame` waits for a frame it has not seen yet."""

    def __init__(self, broadcaster: "FrameBroadcaster", slot: int) -> None:
        """Watch `slot` of `broadcaster`, from the running event loop."""
        self._broadcaster = broadcaster
        self._slot = slot
        self._loop = asyncio.get_running_loop()
        self._changed = asyncio.Event()
        self._last_sequence: Optional[int] = None

    def __enter__(self) -> "FrameSubscription":
        """Start watching."""
        self._broadcaster._add(self._slot, self)
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Stop watching."""
        self._broadcaster._remove(self._slot, self)

    def _notify(self) -> None:
        """A new frame came; called from the detector's thread."""
        try:
            self._loop.call_soon_threadsafe(self._changed.set)
        except RuntimeError:  # the event loop is closed: the server is shutting down
            pass

    async def next_frame(self) -> SlotFrame:
        """The newest frame, once there is one this subscription has not returned."""
        while True:
            self._changed.clear()
            frame = self._broadcaster.newest(self._slot)
            if frame is not None and frame.sequence != self._last_sequence:
                self._last_sequence = frame.sequence
                return frame
            await self._changed.wait()


class FrameBroadcaster:
    """Keeps the newest frame per detector slot and tells the subscribers of that slot."""

    def __init__(self) -> None:
        """Nothing broadcast, nobody watching."""
        self._broadcasting = False
        self._lock = threading.Lock()
        self._newest: dict[int, SlotFrame] = {}
        self._subscriptions: dict[int, set[FrameSubscription]] = {}

    def start_broadcasting(self) -> None:
        """A detector starts streaming: frames follow."""
        self._broadcasting = True

    @property
    def is_broadcasting(self) -> bool:
        """Whether a detector has started streaming."""
        return self._broadcasting

    def subscribe(self, slot: int) -> FrameSubscription:
        """A subscription to `slot`, as a context manager; from the event loop."""
        return FrameSubscription(self, slot)

    def subscriber_count(self, slot: int) -> int:
        """How many subscriptions watch `slot`."""
        with self._lock:
            return len(self._subscriptions.get(slot, ()))

    def newest(self, slot: int) -> Optional[SlotFrame]:
        """The newest frame of `slot`, or None before the first one."""
        with self._lock:
            return self._newest.get(slot)

    def broadcast_sync(self, detector_slot: int, frame: np.ndarray) -> None:
        """Keep `frame` as the newest of `detector_slot`; called from the detector's thread.

        The frame is kept as it is, not copied: a detector must not write to it afterwards.
        """
        with self._lock:
            previous = self._newest.get(detector_slot)
            sequence = 0 if previous is None else previous.sequence + 1
            self._newest[detector_slot] = SlotFrame(detector_slot, sequence, time.time(), frame)
            subscriptions = list(self._subscriptions.get(detector_slot, ()))
        for subscription in subscriptions:
            subscription._notify()

    def _add(self, slot: int, subscription: FrameSubscription) -> None:
        with self._lock:
            self._subscriptions.setdefault(slot, set()).add(subscription)

    def _remove(self, slot: int, subscription: FrameSubscription) -> None:
        with self._lock:
            self._subscriptions.get(slot, set()).discard(subscription)
