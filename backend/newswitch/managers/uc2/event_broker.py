"""Fan-out helper distributing UC2 hardware events to async subscribers."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from newswitch.protocols.uc2 import UC2Event

_DEFAULT_QUEUE_SIZE = 1024


class UC2EventBroker:
    """Distributes `UC2Event`s to any number of async subscribers.

    ``publish`` must be called from the event loop; ``publish_threadsafe``
    can be called from worker/driver threads. Slow subscribers lose the
    oldest events instead of blocking the producer.
    """

    def __init__(self, queue_size: int = _DEFAULT_QUEUE_SIZE) -> None:
        """Initialize the broker with a per-subscriber queue size."""
        self._queues: list[asyncio.Queue[UC2Event]] = []
        self._queue_size = queue_size
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Bind the broker to an event loop (defaults to the running loop)."""
        self._loop = loop or asyncio.get_running_loop()

    def publish(self, event: UC2Event) -> None:
        """Publish an event to all subscribers (call from the event loop)."""
        for queue in list(self._queues):
            if queue.full():
                try:
                    queue.get_nowait()  # drop oldest
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def publish_threadsafe(self, event: UC2Event) -> None:
        """Publish an event from a non-loop thread (driver callbacks)."""
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self.publish, event)
        except RuntimeError:
            pass  # loop already closed during shutdown

    async def subscribe(self) -> AsyncIterator[UC2Event]:
        """Yield events as they arrive; each consumer gets its own queue."""
        queue: asyncio.Queue[UC2Event] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues.remove(queue)
