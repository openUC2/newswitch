"""Serving: FastAPI sends the frames to the websocket live view, the agent to lovekit."""

import asyncio
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main_fastapi import provide_frame_broadcaster
from newswitch import config_io
from newswitch.broadcasters import FrameBroadcaster, FrameSink
from newswitch.settings import Settings

pytest.importorskip("lovekit")

from main_arkitekt import (  # noqa: E402  (needs the extra "agent")
    create_arkitekt_registry,
    provide_lovekit_sink,
)
from newswitch.broadcasters.lovekit import (  # noqa: E402
    CameraStream,
    CameraStreams,
    LovekitSink,
    publish_camera_streams,
)

CONFIGS = Path(__file__).parent.parent / "configs"


class FakeTrack:
    """A published stream: records what it is sent."""

    def __init__(self) -> None:
        """Nothing sent yet."""
        self.frames: list[np.ndarray] = []

    async def send(self, rgba: np.ndarray) -> None:
        """Record a frame."""
        self.frames.append(rgba)


class FakePublished:
    """What ``lovekit.publish`` yields: the declared streams, a track per key."""

    def __init__(self, keys: list[str]) -> None:
        """A stream and a track per key."""
        self.streams = [f"stream:{key}" for key in keys]
        self.tracks = {key: FakeTrack() for key in keys}
        self.stopped = asyncio.Event()

    def __getitem__(self, key: str) -> FakeTrack:
        """The track of `key`."""
        return self.tracks[key]

    async def __aenter__(self) -> "FakePublished":
        """Published."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Unpublished."""
        return None


class FakeLovekit:
    """The lovekit client: publishing hands out a `FakePublished`."""

    def __init__(self) -> None:
        """Nothing published yet."""
        self.published: FakePublished | None = None

    def publish(self, streams: list) -> FakePublished:
        """Publish `streams`."""
        self.published = FakePublished([stream.key for stream in streams])
        return self.published


def test_both_sinks_take_frames() -> None:
    """The websocket broadcaster and the lovekit sink are both a detector's FrameSink."""
    assert isinstance(FrameBroadcaster(), FrameSink)
    assert isinstance(LovekitSink(), FrameSink)


def test_the_newest_frame_is_sent_per_stream_key() -> None:
    """Frames come in on a detector thread and go out on their detector's stream, as RGBA."""
    sink = LovekitSink(
        [CameraStream(1, "bigcamera42", "Main"), CameraStream(2, "side-cam", "Side")]
    )
    live = CameraStreams()
    lovekit = FakeLovekit()

    def detector() -> None:
        for value in range(1, 6):  # only the newest is kept between sends
            sink.broadcast_sync(1, np.full((4, 6), value, dtype=np.uint16))
        sink.broadcast_sync(2, np.zeros((3, 3), dtype=np.uint8))

    async def run() -> None:
        task = asyncio.create_task(publish_camera_streams(lovekit, sink, live))  # type: ignore[arg-type]
        while lovekit.published is None:
            await asyncio.sleep(0)
        thread = threading.Thread(target=detector)
        thread.start()
        thread.join()
        await asyncio.sleep(0.3)
        lovekit.published.stopped.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())
    assert lovekit.published is not None
    assert live.streams == ["stream:bigcamera42", "stream:side-cam"]
    main = lovekit.published.tracks["bigcamera42"].frames
    side = lovekit.published.tracks["side-cam"].frames
    assert len(main) == 1 and main[0].shape == (4, 6, 4) and main[0].dtype == np.uint8
    assert len(side) == 1 and side[0].shape == (3, 3, 4)


def test_the_agent_publishes_the_detectors(tmp_path: Path) -> None:
    """The agent's sink: a lovekit stream per detector, keyed by its configuration key."""
    settings = Settings(
        static_config_path=CONFIGS / "camTest_config.yaml",
        persistent_config_path=tmp_path / "persistent.yaml",
        load_from_static_config_path=True,
    )
    sink, streams = asyncio.run(provide_lovekit_sink(settings))
    assert isinstance(sink, LovekitSink) and isinstance(streams, CameraStreams)
    assert [(c.slot, c.key) for c in sink.cameras] == [(1, "sim-cam")]
    app = create_arkitekt_registry(config_io.load_config(settings.config_file).config)
    assert "CameraStreams" in app.registry.snapshot().states


def test_lovekit_publishes_only_its_own_sink() -> None:
    """The publisher refuses another FrameSink (a misprovided context fails loudly)."""
    with pytest.raises(TypeError, match="LovekitSink"):
        asyncio.run(publish_camera_streams(FakeLovekit(), FrameBroadcaster(), CameraStreams()))  # type: ignore[arg-type]


def test_fastapi_serves_files_and_cache_of_its_agent(virtual_microscope_app: FastAPI) -> None:
    """The routes reach the app's running agent: 503 until it runs, then its files."""
    client = TestClient(virtual_microscope_app)
    assert client.get("/files/nowhere.png").status_code == 503  # not started
    with TestClient(virtual_microscope_app) as started:
        for _ in range(250):  # the startup hooks build the microscope once the agent is up
            if started.get("/files/nowhere.png").status_code != 503:
                break
            time.sleep(0.02)
        assert started.get("/files/nowhere.png").status_code == 404
        assert started.get("/cache/no_such_store/zarr.json").status_code == 404


def test_fastapi_streams_over_the_websocket(tmp_path: Path) -> None:
    """FastAPI: each start gives the detectors a broadcaster of its own, for the live view."""
    settings = Settings(config_file=None)
    (first,), (second,) = (
        asyncio.run(provide_frame_broadcaster(settings)),
        asyncio.run(provide_frame_broadcaster(settings)),
    )
    assert isinstance(first, FrameBroadcaster) and first is not second


def test_the_agent_needs_an_agent_ui(tmp_path: Path) -> None:
    """The agent's UI is the configuration's agent_ui: without one it does not start."""
    from main_arkitekt import create

    config = tmp_path / "newswitch-config.yaml"
    config.write_text("newswitch_version: v1.0.2\ndevices: {}\n")
    settings = Settings(
        static_config_path=config,
        persistent_config_path=tmp_path / "persistent.yaml",
        load_from_static_config_path=True,
    )
    with pytest.raises(config_io.ConfigError, match="no agent_ui section"):
        create(settings)
