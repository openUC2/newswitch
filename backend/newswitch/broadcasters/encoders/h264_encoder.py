"""Shared async H.264 encoder that pipes frames through an ffmpeg subprocess."""

from koil import unkoil

from .config import H264EncoderConfig
from typing import Optional
import asyncio
from .subscription import EncoderSubscription
import numpy as np


class H264Encoder:
    """
    Shared async H.264 encoder using ffmpeg subprocess.

    Multiple subscribers can share a single encoder instance.
    Each subscriber gets their own output queue but the encoding
    happens only once per frame.
    """

    __slots__ = (
        "_config",
        "_process",
        "_running",
        "_reader_task",
        "_subscribers",
        "_subscriber_id",
        "_lock",
    )

    def __init__(self, config: H264EncoderConfig) -> None:
        """Initialize the shared H.264 encoder with the given configuration."""
        self._config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self._reader_task: Optional[asyncio.Task] = None
        self._subscribers: dict[int, EncoderSubscription] = {}
        self._subscriber_id: int = 0
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Is the encoder currently running?"""
        return self._running

    @property
    def config(self) -> H264EncoderConfig:
        """The encoder configuration."""
        return self._config

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._subscribers)

    async def asubscribe(self, detector_slot: int) -> EncoderSubscription:
        """Create a new subscription to this encoder's output."""
        async with self._lock:
            self._subscriber_id += 1
            sub = EncoderSubscription(self, sub_id=self._subscriber_id, detector_slot=detector_slot)
            self._subscribers[self._subscriber_id] = sub
            return sub

    async def aunsubscribe(self, subscription: EncoderSubscription) -> None:
        """Remove a subscription."""
        async with self._lock:
            self._subscribers.pop(subscription._id, None)

    async def astart(self) -> None:
        """Start the ffmpeg encoder process."""
        if self._running:
            return

        # Nobody reads ffmpeg's stderr, and a full pipe would block ffmpeg and freeze the
        # stream: keep it quiet (no banner, no progress line) and discard what is left.
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self._config.width}x{self._config.height}",
            "-r",
            str(self._config.fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-preset",
            self._config.preset,
            "-tune",
            self._config.tune,
            "-g",
            str(self._config.fps),
            "-sc_threshold",
            "0",
            "-b:v",
            self._config.bitrate,
            "-maxrate",
            self._config.bitrate,
            "-bufsize",
            self._config.bitrate,
            "-pix_fmt",
            "yuv420p",
            "-f",
            "h264",
            "-",
        ]

        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._running = True
        self._reader_task = asyncio.create_task(self._read_output())

    async def _read_output(self) -> None:
        """Read encoded chunks from ffmpeg stdout and distribute to subscribers."""
        try:
            while self._running and self._process:
                data = await self._process.stdout.read(4096)
                if not data:
                    break
                # Distribute to all subscribers
                for sub in self._subscribers.values():
                    sub.push_chunk(data)
        except Exception:
            pass
        finally:
            self._running = False

    async def astop(self) -> None:
        """Stop the encoder and clean up."""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._process and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()
        self._process = None

    def _preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Preprocess frame for encoding: resize and convert to BGR24.
        """
        import cv2

        # Resize if needed
        if frame.shape[:2] != (self._config.height, self._config.width):
            frame = cv2.resize(frame, (self._config.width, self._config.height))

        # Convert grayscale to BGR
        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif len(frame.shape) == 3 and frame.shape[2] == 1:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        # Normalize uint16 to uint8 if needed
        if frame.dtype == np.uint16:
            frame = (frame / 256).astype(np.uint8)

        return frame

    def encode_frame(self, frame: np.ndarray) -> None:
        """Send a frame to the encoder."""
        if not self._process or not self._process.stdin:
            return

        try:
            processed = self._preprocess_frame(frame)
            self._process.stdin.write(processed.tobytes())
            unkoil(self._process.stdin.drain)  # TODO: Maybe find the right primitive
        except (BrokenPipeError, ConnectionResetError):
            self._running = False
