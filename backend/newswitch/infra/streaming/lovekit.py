"""The detectors' frames as lovekit streams (arkitekt agent, ``app.py``).

Every detector is a lovekit `VideoStream`, keyed by its cube in the instrument
(lovekit keeps a stream's id by its key over restarts; detectors change with
the description's order), titled by its name. The detectors hand their frames to a `LovekitSink`
from their own threads; it keeps the newest one per detector, and the background hook
`publish_camera_streams` sends what is new, at most `MAX_FPS` per stream, from the event
loop. The declared streams are held in the state `CameraStreams`, which the agent's
bloks show (``<StructureDisplay value="@stream" />``).

A stream is a view, not the data: a frame is binned down to at most `STREAM_MAX_WIDTH` pixels
wide before it is sent (`stream_rgba`), and stretched to eight bits from a sparse sample of its
pixels. A full 6 MP frame converted whole took 0.6 s on a Pi, and a software encoder held to the
stream's bitrate turned it to grain; binned, it takes a few tens of milliseconds and averages the
sensor's noise away. Images and acquisitions keep every pixel: they never go through here.

Not imported by `newswitch.infra.streaming`: it needs the extra ``agent``
(``arkitekt[rekuest,lovekit]``).
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
from lovekit import I420Frame, VideoStream, to_rgba
from lovekit.api.schema import Stream
from lovekit.lovekit import Lovekit

from newswitch.protocols.frame_sink import FrameSink
from newswitch.simulation.test_pattern import timestamp_rgba

logger = logging.getLogger(__name__)

#: How often the publisher says how its streams keep up, in seconds.
STATS_INTERVAL_S = 10.0
#: How soon the publisher looks again for a frame when none was new, in seconds.
POLL_INTERVAL_S = 0.005

#: The most frames a stream is sent per second; a detector may acquire faster.
MAX_FPS = 15.0
#: The widest a streamed frame is: wider frames are binned down by a whole factor (3072 -> 1024).
STREAM_MAX_WIDTH = 1024
#: What a stream's encoder may spend, in bits per second: enough for a binned frame at MAX_FPS.
STREAM_BITRATE = 2_500_000
#: How large the test pattern is (``simulate: debug``): the size a stream sends at most, 3:2.
TEST_PATTERN_SIZE = (STREAM_MAX_WIDTH, STREAM_MAX_WIDTH * 2 // 3)
#: Every how many pixels (per axis) the contrast stretch is sampled.
STRETCH_SAMPLE = 4


def binned(frame: np.ndarray, max_width: int = STREAM_MAX_WIDTH) -> np.ndarray:
    """`frame` averaged over squares of a whole factor, so it is at most `max_width` wide, and
    of even size (which video encoders want). A frame narrow enough is sent as it is."""
    height, width = frame.shape[:2]
    factor = max(1, -(-width // max_width))
    if factor == 1:
        return frame
    rows, cols = height // factor // 2 * 2, width // factor // 2 * 2
    view = frame[: rows * factor, : cols * factor]
    if view.dtype.kind in "ui":
        # Added up in integers, rows then columns, one slice at a time, and divided once: a third
        # of the time of numpy's sum over an axis, a sixth of a float mean. 8-bit frames add up in
        # 16 bits while they fit. A color frame's channels ride along (y, x, c).
        rest = frame.shape[2:]
        fits = view.dtype.itemsize == 1 and factor * factor * 255 < 2**16
        wide = np.uint16 if fits else np.uint32
        by_rows = view.reshape(rows, factor, cols * factor, *rest)
        summed = by_rows[:, 0].astype(wide)
        for k in range(1, factor):
            summed += by_rows[:, k]
        by_cols = summed.reshape(rows, cols, factor, *rest)
        total = by_cols[:, :, 0].copy()
        for k in range(1, factor):
            total += by_cols[:, :, k]
        return total.astype(np.float32) * np.float32(1.0 / (factor * factor))
    shape = (rows, factor, cols, factor, *frame.shape[2:])
    return view.reshape(shape).mean(axis=(1, 3), dtype=np.float32)


def _full_scale(data: np.ndarray) -> float:
    """The brightest a frame of this kind can be: 8, 12 or 16 bits, from its type and values (a
    12-bit camera delivers uint16 that stay below 4096)."""
    if data.dtype == np.uint8:
        return 255.0
    brightest = float(data.max()) if data.size else 0.0
    return 4095.0 if brightest <= 4095 else 65535.0


def stream_rgba(frame: np.ndarray, max_width: int = STREAM_MAX_WIDTH) -> np.ndarray:
    """A frame as the RGBA bytes a video track takes, binned down to the stream's size.

    A gray image is stretched between the 1st and 99.9th percentile of a sparse sample of its
    pixels (a uint16 frame shifted down to eight bits shows nothing of a dim sample); a color one
    is binned and handed to lovekit's `to_rgba`."""
    data = binned(np.asarray(frame), max_width)
    if data.ndim != 2:
        return to_rgba(np.asarray(data, dtype=np.uint8) if data.dtype != np.uint8 else data)
    sample = data[::STRETCH_SAMPLE, ::STRETCH_SAMPLE]
    low, high = (float(v) for v in np.percentile(sample, (1.0, 99.9)))
    if high <= low:  # nearly all of it one level (black): a small bright spot is above that
        high = float(data.max())
    if high <= low:  # all of it one level: shown as that level of the sensor's range, so a
        low, high = 0.0, _full_scale(data)  # saturated frame is white and a dark one black
    scale = 255.0 / (high - low) if high > low else 0.0
    eight = np.clip((data - low) * scale, 0, 255).astype(np.uint8)
    rgba = np.empty((*eight.shape, 4), dtype=np.uint8)
    rgba[..., :3] = eight[..., None]
    rgba[..., 3] = 255
    return rgba


@dataclass(frozen=True)
class CameraStream:
    """A detector as a stream: its detector, and the key and title of its stream."""

    detector: str
    key: str
    title: str


class LovekitSink:
    """Takes the detectors' frames and keeps the newest per detector, for lovekit."""

    def __init__(self, cameras: Sequence[CameraStream] = (), test_pattern: bool = False) -> None:
        """A sink for `cameras`, the detectors it publishes.

        Args:
            test_pattern: Each stream sends the time it sends instead of its camera's frames
                (`newswitch.simulation.test_pattern`): to test the network, not the camera.
        """
        self.cameras = list(cameras)
        self.test_pattern = test_pattern
        self._newest: dict[str, np.ndarray | I420Frame] = {}
        self._lock = threading.Lock()
        self.offered: dict[str, int] = {}
        """How many new frames each detector had (the publisher sends the newest it takes)."""

    def start_broadcasting(self) -> None:
        """A detector streams: nothing to start, frames are taken as they come."""

    def broadcast_sync(self, detector: str, frame: np.ndarray) -> None:
        """Keep `frame` as the newest of `detector` (called from the detector's thread)."""
        with self._lock:
            self._newest[detector] = frame

    #: How wide a frame handed over ready to encode (`broadcast_i420`) may be: what is sent.
    i420_width = STREAM_MAX_WIDTH

    def broadcast_i420(self, detector: str, width: int, height: int, data: np.ndarray) -> None:
        """Keep a frame already scaled to the stream (at most `i420_width` wide) and converted to
        I420 by the camera's driver as the newest of `detector`: it is sent as it is, with no
        conversion here (a camera that converts natively, straight from its ring, offers it)."""
        with self._lock:
            self._newest[detector] = I420Frame(width, height, data)

    def wants(self, detector: str) -> bool:
        """Whether a new frame of `detector` is wanted: not while the last one is still untaken,
        as it would only replace it. A detector asks before it copies a frame (a 6 MP frame at
        30 fps is 375 MB/s of copying, of which the stream sends a third)."""
        with self._lock:
            self.offered[detector] = self.offered.get(detector, 0) + 1
            return detector not in self._newest

    def take(self, detector: str) -> Optional[np.ndarray | I420Frame]:
        """The newest frame of `detector` since the last take, or None."""
        with self._lock:
            return self._newest.pop(detector, None)


@dataclass
class CameraStreams:
    """The detectors' streams, as lovekit declared them, and what each is titled: the detector,
    at the same place in ``titles`` as its stream in ``streams`` (a view's tab per camera)."""

    streams: list[Stream] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)


async def publish_camera_streams(lovekit: Lovekit, sink: FrameSink, live: CameraStreams) -> None:
    """Background: declare a stream per detector and send each its newest frames.

    `sink` is the agent's `FrameSink` context, which ``app.py`` provides as a
    `LovekitSink`.
    """
    if not isinstance(sink, LovekitSink):
        raise TypeError(f"lovekit publishes a LovekitSink, not {type(sink).__name__}")
    declared = [
        VideoStream(
            camera.key,
            title=camera.title,
            max_framerate=MAX_FPS,
            max_bitrate=STREAM_BITRATE,
            # One full-size layer: few viewers watch it, and every layer more is another software
            # encoding on the agent's machine (the Pi 5 encodes no video in hardware).
            simulcast=False,
        )
        for camera in sink.cameras
    ]
    async with lovekit.publish(declared) as published:
        streams = list(published.streams)
        live.titles = [stream.title or stream.key for stream in streams]
        live.streams = streams
        stats = _Stats()
        while not published.stopped.is_set():
            started_round = time.perf_counter()
            sent_any = False
            if sink.test_pattern:
                for camera in sink.cameras:
                    started = time.perf_counter()
                    rgba = timestamp_rgba(*TEST_PATTERN_SIZE, frame=stats.total(camera.key) + 1)
                    drawn = time.perf_counter()
                    await published[camera.key].send(rgba)
                    stats.add(camera.key, rgba[..., 0], drawn - started, time.perf_counter() - drawn)
                stats.report(sink)
                busy = time.perf_counter() - started_round
                await asyncio.sleep(max(0.0, 1.0 / MAX_FPS - busy))
                continue
            for camera in sink.cameras:
                frame = sink.take(camera.detector)
                if isinstance(frame, I420Frame):
                    # Scaled and converted by the camera's driver already: sent as it is.
                    started = time.perf_counter()
                    await published[camera.key].send(frame)
                    plane = frame.data[: frame.width * frame.height].reshape(frame.height, frame.width)
                    stats.add(camera.key, plane, 0.0, time.perf_counter() - started)
                    sent_any = True
                elif frame is not None:
                    # Binned and converted off the event loop, which also runs the agent's
                    # actions and state updates.
                    started = time.perf_counter()
                    rgba = await asyncio.to_thread(stream_rgba, frame)
                    converted = time.perf_counter()
                    await published[camera.key].send(rgba)
                    stats.add(
                        camera.key,
                        frame,
                        converted - started,
                        time.perf_counter() - converted,
                    )
                    sent_any = True
            stats.report(sink)
            # At most MAX_FPS: after a frame, wait out only what is left of its period (converting
            # took some of it); with nothing new, look again soon, so a fresh frame waits little.
            busy = time.perf_counter() - started_round
            await asyncio.sleep(max(0.0, 1.0 / MAX_FPS - busy) if sent_any else POLL_INTERVAL_S)


def _levels(frame: Optional[np.ndarray]) -> str:
    """How bright the last frame sent was: its 1st and 99.9th percentile and its brightest pixel,
    in its own units (so a black frame shows as one, and a dark one with a bright spot too)."""
    if frame is None:
        return "-"
    sample = np.asarray(frame)[::STRETCH_SAMPLE, ::STRETCH_SAMPLE]
    low, high = np.percentile(sample, (1.0, 99.9))
    return f"p1 {low:.0f} / p99.9 {high:.0f} / max {np.asarray(frame).max():.0f}"


class _Stats:
    """How the streams keep up, said every `STATS_INTERVAL_S`: what each camera offered, what
    was sent, and how long converting and sending a frame took."""

    def __init__(self) -> None:
        self.since = time.monotonic()
        self.sent: dict[str, int] = {}
        self.convert: dict[str, float] = {}
        self.send: dict[str, float] = {}
        self.shape: dict[str, tuple[int, ...]] = {}
        self.offered_before: dict[str, int] = {}
        self.last: dict[str, np.ndarray] = {}
        self.totals: dict[str, int] = {}

    def total(self, key: str) -> int:
        """How many frames `key` has sent since the stream started."""
        return self.totals.get(key, 0)

    def add(
        self, key: str, frame: np.ndarray, convert: float, send: float
    ) -> None:
        self.last[key] = frame
        self.totals[key] = self.totals.get(key, 0) + 1
        shape = frame.shape
        self.sent[key] = self.sent.get(key, 0) + 1
        self.convert[key] = self.convert.get(key, 0.0) + convert
        self.send[key] = self.send.get(key, 0.0) + send
        self.shape[key] = shape

    def report(self, sink: LovekitSink) -> None:
        elapsed = time.monotonic() - self.since
        if elapsed < STATS_INTERVAL_S:
            return
        for camera in sink.cameras:
            key = camera.key
            offered = sink.offered.get(camera.detector, 0)
            new = offered - self.offered_before.get(camera.detector, 0)
            self.offered_before[camera.detector] = offered
            sent = self.sent.get(key, 0)
            if not new and not sent:
                continue
            logger.info(
                "stream %s: camera offered %.1f fps, sent %.1f fps, frame %s, convert %.0f ms, "
                "send %.0f ms, levels %s",
                key,
                new / elapsed,
                sent / elapsed,
                "x".join(str(n) for n in self.shape.get(key, ())),
                1000 * self.convert.get(key, 0.0) / max(sent, 1),
                1000 * self.send.get(key, 0.0) / max(sent, 1),
                _levels(self.last.get(key)),
            )
        self.since = time.monotonic()
        self.sent.clear()
        self.convert.clear()
        self.send.clear()
