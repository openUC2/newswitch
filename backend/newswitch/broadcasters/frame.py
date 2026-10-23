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
import threading
from typing import Optional

import numpy as np

from newswitch.broadcasters.encoders.base import EncoderProtocol, EncoderSubscriptionProtocol
from newswitch.broadcasters.encoders.config import EncoderConfig
from newswitch.broadcasters.encoders.h264_encoder import H264Encoder, H264EncoderConfig
from newswitch.broadcasters.encoders.zstd_encoder import (
    ZstdEncoder,
    ZstdEncoderConfig,
)


class FrameBroadcaster:
    """
    High-performance frame broadcaster with shared Zstd and H.264 encoding.

    Design principles:
    1. Shared encoders - clients with same config share one encoder
    2. Lock-free broadcasting - optimized for speed
    3. Automatic cleanup - encoders stop when last subscriber leaves

    Usage:
        broadcaster = FrameBroadcaster()
        broadcaster.start_broadcasting()

        # Producer (sync, from detector thread):
        broadcaster.broadcast_sync(1, frame)

        # Consumer (async, from WebSocket):
        config = ZstdEncoderConfig(level=1)
        subscription = await broadcaster.get_encoder_subscription(1, config)
        chunk = await subscription.get_encoded_chunk()
        # When done:
        await broadcaster.release_subscription(subscription)
    """

    __slots__ = (
        "_broadcasting",
        "_loop",
        "_latest_frame",
        "_encoders",
        "_encoder_lock",
    )

    def __init__(self) -> None:
        """Initialize the FrameBroadcaster."""
        self._broadcasting: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._latest_frame: Optional[np.ndarray] = None
        # Shared encoders keyed by config
        self._encoders: dict[tuple[int, EncoderConfig], EncoderProtocol] = {}
        self._encoder_lock = threading.Lock()

    def start_broadcasting(self) -> None:
        """Start broadcasting frames to encoders."""
        self._broadcasting = True

    def stop_broadcasting(self) -> None:
        """Stop broadcasting frames."""
        self._broadcasting = False
        self._latest_frame = None

    @property
    def is_broadcasting(self) -> bool:
        """Check if broadcasting is active."""
        return self._broadcasting

    @property
    def encoder_count(self) -> int:
        """Number of active shared encoders."""
        return len(self._encoders)

    async def get_subscription_(
        self, detector_slot: int, config: Optional[EncoderConfig] = None
    ) -> EncoderSubscriptionProtocol:
        """
        Get a subscription to a Zstd encoder with the given config.

        Args:
            config: Zstd encoder configuration. Uses defaults if not provided.

        Returns:
            EncoderSubscriptionProtocol for receiving encoded chunks.
        """
        config = config or ZstdEncoderConfig()
        key = (detector_slot, config)

        with self._encoder_lock:
            encoder = self._encoders.get(key)
            if encoder is None:
                match config:
                    case ZstdEncoderConfig():
                        encoder = ZstdEncoder(config)
                    case H264EncoderConfig():
                        encoder = H264Encoder(config)

            self._encoders[key] = encoder

        if not encoder.is_running:
            await encoder.astart()

        return await encoder.asubscribe(detector_slot)

    async def arelease_subscription(self, subscription: EncoderSubscriptionProtocol) -> None:
        """Unsubscribe from its shared encoder, stopping the encoder if it was the last one."""
        key = (subscription.detector_slot, subscription.config)

        with self._encoder_lock:
            encoder = self._encoders.get(key)

        if encoder is None:
            return

        await encoder.aunsubscribe(subscription)

        if encoder.subscriber_count == 0:
            await encoder.astop()
            with self._encoder_lock:
                self._encoders.pop(key, None)

    def _schedule_encoder_frames(self, detector_slot: int, frame: np.ndarray) -> None:
        """Schedule frame encoding for active encoders of one detector slot."""

        for (slot, _), encoder in self._encoders.items():
            if slot != detector_slot:
                continue
            if encoder.is_running:
                encoder.encode_frame(frame)

    def broadcast_sync(self, detector_slot: int, frame: np.ndarray) -> None:
        """
        Synchronous broadcast for use from detector/camera thread.

        Sends frames to all active shared encoders.

        Args:
            frame: The numpy array frame to broadcast (uint16 typically).
        """

        self._schedule_encoder_frames(detector_slot, frame)

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """
        Get the most recently broadcast frame.

        Returns:
            The latest frame or None if no frame has been broadcast.
        """
        return self._latest_frame

    async def stop_all_encoders(self) -> None:
        """Stop all active encoders."""
        with self._encoder_lock:
            encoders = list(self._encoders.values())

        for encoder in encoders:
            await encoder.astop()
