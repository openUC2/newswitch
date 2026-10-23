"""The detectors' frames as lovekit streams (arkitekt agent, ``main_arkitekt.py``).

Every configured detector is a lovekit `VideoStream`, keyed by its key in the device
configuration (lovekit keeps a stream's id by its key over restarts; slots change with
the file order), titled by its name. The detectors hand their frames to a `LovekitSink`
from their own threads; it keeps the newest one per detector, and the background hook
`publish_camera_streams` sends what is new, at most `MAX_FPS` per stream, from the event
loop. The declared streams are held in the state `CameraStreams`, which the ``agent_ui``
bloks show (``<StructureDisplay value="@stream" />``).

Not imported by `newswitch.broadcasters`: it needs the extra ``agent``
(``arkitekt[rekuest,lovekit]``).
"""

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
from lovekit import VideoStream, to_rgba
from lovekit.api.schema import Stream
from lovekit.lovekit import Lovekit

from newswitch.broadcasters.sink import FrameSink

#: The most frames a stream is sent per second; a detector may acquire faster.
MAX_FPS = 15.0


@dataclass(frozen=True)
class CameraStream:
    """A detector as a stream: its slot, and the key and title of its stream."""

    slot: int
    key: str
    title: str


class LovekitSink:
    """Takes the detectors' frames and keeps the newest per detector, for lovekit."""

    def __init__(self, cameras: Sequence[CameraStream] = ()) -> None:
        """A sink for `cameras`, the detectors it publishes."""
        self.cameras = list(cameras)
        self._newest: dict[int, np.ndarray] = {}
        self._lock = threading.Lock()

    def start_broadcasting(self) -> None:
        """A detector streams: nothing to start, frames are taken as they come."""

    def broadcast_sync(self, slot: int, frame: np.ndarray) -> None:
        """Keep `frame` as the newest of `slot` (called from the detector's thread)."""
        with self._lock:
            self._newest[slot] = frame

    def take(self, slot: int) -> Optional[np.ndarray]:
        """The newest frame of `slot` since the last take, or None."""
        with self._lock:
            return self._newest.pop(slot, None)


@dataclass
class CameraStreams:
    """The detectors' streams, as lovekit declared them."""

    streams: list[Stream] = field(default_factory=list)


async def publish_camera_streams(lovekit: Lovekit, sink: FrameSink, live: CameraStreams) -> None:
    """Background: declare a stream per detector and send each its newest frames.

    `sink` is the agent's `FrameSink` context, which ``main_arkitekt.py`` provides as a
    `LovekitSink`.
    """
    if not isinstance(sink, LovekitSink):
        raise TypeError(f"lovekit publishes a LovekitSink, not {type(sink).__name__}")
    declared = [VideoStream(camera.key, title=camera.title) for camera in sink.cameras]
    async with lovekit.publish(declared) as published:
        live.streams = list(published.streams)
        while not published.stopped.is_set():
            for camera in sink.cameras:
                frame = sink.take(camera.slot)
                if frame is not None:
                    # ~37 ms for a 1920x1200 frame: converted off the event loop, which
                    # also runs the agent's actions and state updates.
                    rgba = await asyncio.to_thread(to_rgba, frame)
                    await published[camera.key].send(rgba)
            await asyncio.sleep(1.0 / MAX_FPS)
