"""
Shared Zstd encoder with optional delta compression and noise gate.

Designed for low-latency streaming of numpy frames, similar to the shared
H.264 encoder pattern.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import numpy as np
import zstandard as zstd

from .config import ZstdEncoderConfig
from .subscription import EncoderSubscription


class ZstdEncoder:
    """
    Shared async Zstd encoder.

    Encodes frames to compressed delta chunks and fan-outs to subscribers.
    """

    __slots__ = (
        "_config",
        "_compressor",
        "_running",
        "_subscribers",
        "_subscriber_id",
        "_lock",
        "_last_frame",
    )

    def __init__(self, config: ZstdEncoderConfig) -> None:
        """Initialize the shared Zstd encoder with the given configuration. The compressor is set up based on the specified compression level. The encoder starts in a non-running state with no subscribers and an optional last frame for delta encoding."""
        self._config = config
        self._compressor = zstd.ZstdCompressor(level=self._config.level)
        self._running = False
        self._subscribers: dict[int, EncoderSubscription] = {}
        self._subscriber_id = 0
        self._lock = asyncio.Lock()
        self._last_frame: Optional[np.ndarray] = None

    @property
    def is_running(self) -> bool:
        """Check if the encoder is currently running. If False, the encoder will not process frames or produce output chunks."""
        return self._running

    @property
    def config(self) -> ZstdEncoderConfig:
        """Return the configuration of this encoder. This includes settings like compression level, delta encoding usage, and threshold for noise gating."""
        return self._config

    @property
    def subscriber_count(self) -> int:
        """Return the number of active subscribers to this encoder. This can be used to determine if the encoder is still needed or if it can be stopped and cleaned up."""
        return len(self._subscribers)

    async def asubscribe(self, detector_slot: int) -> EncoderSubscription:
        """Asynchronously subscribe to this encoder's output stream for a specific detector slot. A new subscription is created with a unique ID and added to the list of subscribers. The subscription object is returned, which can be used to receive encoded chunks."""
        async with self._lock:
            self._subscriber_id += 1
            sub = EncoderSubscription(self, self._subscriber_id, detector_slot)
            self._subscribers[self._subscriber_id] = sub
            return sub

    async def aunsubscribe(self, subscription: EncoderSubscription) -> None:
        """Asynchronously unsubscribe from this encoder's output stream. The subscription is removed from the list of subscribers. If this was the last subscriber, the encoder can be stopped and cleaned up by the broadcaster."""
        async with self._lock:
            self._subscribers.pop(subscription._id, None)

    async def astart(self) -> None:
        """Asynchronously start the encoder. This sets the running state to True, allowing the encoder to process frames and produce output chunks for subscribers."""
        self._running = True

    async def astop(self) -> None:
        """ " Asynchronously stop the encoder. This sets the running state to False and clears the last frame used for delta encoding. The encoder will no longer process frames or produce output chunks until it is started again."""
        self._running = False
        self._last_frame = None

    def _prepare_frame(self, frame: np.ndarray) -> np.ndarray:
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)
        return frame.astype(np.float32, copy=False)

    def _compute_delta(self, current: np.ndarray) -> np.ndarray:
        if self._last_frame is None:
            self._last_frame = np.zeros_like(current)

        delta = current - self._last_frame

        if self._config.threshold > 0:
            delta[np.abs(delta) < self._config.threshold] = 0

        self._last_frame += delta
        return delta

    def _compress(self, frame: np.ndarray) -> bytes:
        if self._config.use_delta:
            payload = self._compute_delta(frame)
        else:
            payload = frame

        return self._compressor.compress(payload.tobytes())

    def encode_frame(self, frame: np.ndarray) -> None:
        """Compress a frame and push the resulting chunk to every subscriber.

        Does nothing if the encoder is not running, and silently drops the frame if
        compression fails.
        """
        if not self._running:
            return

        prepared = self._prepare_frame(frame)
        try:
            chunk = self._compress(prepared)
        except Exception:
            return

        for sub in self._subscribers.values():
            sub.push_chunk(chunk)
