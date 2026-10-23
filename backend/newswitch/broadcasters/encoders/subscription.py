"""
High-performance frame broadcaster for low-latency video streaming.

Optimized for minimal latency with:
- Lock-free broadcasting using thread-safe primitives
- Zero-copy frame references where possible
- Automatic frame dropping to prevent queue backlog
- Integrated Zstd and H.264 encoding for WebSocket streaming
- Shared encoders for clients with matching configurations
"""

import asyncio
from typing import Optional

from newswitch.broadcasters.encoders.base import EncoderProtocol
from newswitch.broadcasters.encoders.config import EncoderConfig


class EncoderSubscription:
    """Subscription to a shared Zstd encoder's output stream."""

    __slots__ = ("_encoder", "_output_queue", "_id", "_detector_slot")

    def __init__(self, encoder: "EncoderProtocol", sub_id: int, detector_slot: int) -> None:
        """Initialize the subscription with a reference to the encoder, a unique ID, and the associated detector slot. The output queue is used to receive encoded chunks from the encoder."""
        self._encoder = encoder
        self._id = sub_id
        self._detector_slot = detector_slot
        self._output_queue: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=1
        )  # Buffer up to 10 chunks, drop oldest when full

    @property
    def config(self) -> EncoderConfig:
        """Return the encoder configuration associated with this subscription."""
        return self._encoder.config

    @property
    def is_running(self) -> bool:
        """ " Check if the underlying encoder is still running. If the encoder has stopped, this subscription is effectively inactive."""
        return self._encoder.is_running

    @property
    def detector_slot(self) -> int:
        """Return the detector slot associated with this subscription. This can be used by the encoder to determine which frames to encode for this subscriber."""
        return self._detector_slot

    async def get_encoded_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        """Asynchronously get the next encoded chunk from the output queue. If no chunk is available within the specified timeout, return None. This method is used by subscribers to receive encoded data from the encoder."""
        try:
            return await asyncio.wait_for(self._output_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def push_chunk(self, chunk: bytes) -> None:
        """Push an encoded chunk to this subscription's output queue. If the queue is full, the oldest chunk is dropped to make room for the new one. This method is called by the encoder when a new chunk is available."""
        if self._output_queue.full():
            try:
                self._output_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._output_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            pass
