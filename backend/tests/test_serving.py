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
from newswitch.infra.streaming import FrameBroadcaster
from newswitch.protocols.frame_sink import FrameSink
from newswitch.instrument import spec
from newswitch.microscope.run import Run
from tests.conftest import run_settings

pytest.importorskip("lovekit")

from app import (  # noqa: E402  (needs the extra "agent")
    app,
    provide_lovekit_sink,
)
from newswitch.infra.streaming.lovekit import (  # noqa: E402
    CameraStream,
    CameraStreams,
    LovekitSink,
    publish_camera_streams,
)

CAM_TEST = Path(__file__).parent.parent / "instruments" / "cam-test"


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
        [CameraStream("main", "bigcamera42", "Main"), CameraStream("side", "side-cam", "Side")]
    )
    live = CameraStreams()
    lovekit = FakeLovekit()

    def detector() -> None:
        for value in range(1, 6):  # only the newest is kept between sends
            sink.broadcast_sync("main", np.full((4, 6), value, dtype=np.uint16))
        sink.broadcast_sync("side", np.zeros((3, 3), dtype=np.uint8))

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
    """The agent's sink: a lovekit stream per detector, keyed by its cube."""
    current = Run.of(run_settings(tmp_path, instrument=CAM_TEST))
    sink, streams = asyncio.run(provide_lovekit_sink(current))
    assert isinstance(sink, LovekitSink) and isinstance(streams, CameraStreams)
    assert [(c.detector, c.key) for c in sink.cameras] == [("sim_cam", "sim_cam")]
    assert "CameraStreams" in app.registry.snapshot().states


def test_without_detectors_the_agent_publishes_nothing(tmp_path: Path) -> None:
    """No detector, no sink: arkitekt then does not start the publisher, which needs one."""
    sink, streams = asyncio.run(provide_lovekit_sink(Run.of(run_settings(tmp_path))))
    assert sink is None and isinstance(streams, CameraStreams)


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
    current = Run.of(run_settings(tmp_path))
    first, second = (
        asyncio.run(provide_frame_broadcaster(current)),
        asyncio.run(provide_frame_broadcaster(current)),
    )
    assert isinstance(first, FrameBroadcaster) and first is not second


def test_the_agent_is_declared_without_an_instrument(monkeypatch: pytest.MonkeyPatch) -> None:
    """What ``arkitekt inspect all app`` does when it compiles a release: import the app, with no
    instrument named, and declare all of it."""
    import importlib
    import sys

    from arkitekt.app.spec import app_declaration

    monkeypatch.delenv("NEWSWITCH_CONFIG", raising=False)
    monkeypatch.setattr(spec, "load", lambda *_: pytest.fail("the description was read"))
    sys.modules.pop("app", None)
    agent = importlib.import_module("app").app

    declaration = app_declaration(agent, agent.snapshot(), entrypoint="app")
    inspection = declaration.to_inspection()
    actions = {impl.interface for impl in inspection.implementations}
    assert {"capture_image", "move", "acquire_mda", "home_stage", "galvo_stop"} <= actions
    assert {"view-microscope", "view-acquire"} <= {blok.key for blok in inspection.bloks}


def test_the_agent_runs_the_instrument_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its context is the run of the description ``NEWSWITCH_CONFIG`` names."""
    from app import load_run

    monkeypatch.setenv("NEWSWITCH_CONFIG", str(CAM_TEST))
    current = load_run()
    assert current.instrument is not None and current.instrument.detectors() == ["sim_cam"]


def test_the_agent_reads_the_instrument_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its hook takes what the run holds, so the file cannot change between two reads."""
    current = Run.of(run_settings(tmp_path, instrument=CAM_TEST))

    def nothing_reads(*_: object) -> None:
        raise AssertionError("the description was read again")

    monkeypatch.setattr(spec, "load", nothing_reads)
    sink, _ = asyncio.run(provide_lovekit_sink(current))
    assert isinstance(sink, LovekitSink) and [c.key for c in sink.cameras] == ["sim_cam"]


def test_a_streamed_frame_is_binned_to_the_streams_size() -> None:
    """A 6 MP frame goes out at most STREAM_MAX_WIDTH wide, even-sized, averaged over its bins;
    a narrow one keeps its pixels."""
    from newswitch.infra.streaming.lovekit import STREAM_MAX_WIDTH, binned, stream_rgba

    frame = np.zeros((2048, 3072), dtype=np.uint16)
    frame[:, 1536:] = 1000
    rgba = stream_rgba(frame)
    assert rgba.shape == (682, 1024, 4) and rgba.dtype == np.uint8
    assert rgba.shape[1] <= STREAM_MAX_WIDTH and rgba.shape[0] % 2 == 0
    assert (rgba[..., 3] == 255).all()
    assert rgba[0, 0, 0] == 0 and rgba[0, -1, 0] == 255  # the stretch spans dark to bright
    noisy = np.random.default_rng(0).normal(100.0, 10.0, (300, 3000)).astype(np.float32)
    assert binned(noisy).std() < noisy.std() / 2  # binning by 3 averages the noise down
    small = np.arange(64 * 63, dtype=np.uint16).reshape(64, 63)
    assert binned(small) is small  # narrow enough: sent as it is


def test_a_lovekit_sink_wants_a_frame_only_once_the_last_is_taken() -> None:
    """While a frame waits to be sent, a newer one would only replace it: the camera is told not
    to copy it, and every new frame still counts as offered."""
    sink = LovekitSink([CameraStream(detector="cam", key="cam", title="cam")])
    assert sink.wants("cam")
    sink.broadcast_sync("cam", np.zeros((2, 2), dtype=np.uint16))
    assert not sink.wants("cam")
    assert sink.take("cam") is not None
    assert sink.wants("cam") and sink.offered["cam"] == 3


def test_a_black_frame_with_a_small_bright_spot_shows_the_spot() -> None:
    """Nearly all of it at the black level: the percentiles agree, and the spot is stretched
    against the brightest pixel instead of the image going black."""
    import numpy as np

    from newswitch.infra.streaming.lovekit import stream_rgba

    frame = np.full((512, 512), 8, dtype=np.uint16)
    frame[250:254, 250:254] = 4000
    rgba = stream_rgba(frame, max_width=512)
    assert rgba[..., 0].max() >= 250 and rgba[0, 0, 0] == 0


def test_a_saturated_frame_is_white_and_a_black_one_black() -> None:
    """All of a frame at one level shows as that level of the sensor's range, not as black."""
    import numpy as np

    from newswitch.infra.streaming.lovekit import stream_rgba

    assert stream_rgba(np.full((64, 64), 4088, dtype=np.uint16))[0, 0, 0] >= 250
    assert stream_rgba(np.full((64, 64), 8, dtype=np.uint16))[0, 0, 0] <= 1


def test_a_color_frame_is_binned_per_channel_and_sent_in_color() -> None:
    """A color camera's (y, x, 3) frame keeps its colors: each channel averaged on its own."""
    import numpy as np

    from newswitch.infra.streaming.lovekit import binned, stream_rgba

    frame = np.zeros((12, 18, 3), dtype=np.uint8)
    frame[..., 0] = 200  # red
    frame[:, :9, 2] = 90  # blue on the left half
    small = binned(frame, max_width=6)
    assert small.shape == (4, 6, 3)
    assert np.allclose(small[..., 0], 200) and np.allclose(small[:, :3, 2], 90)
    assert np.allclose(small[:, 3:, 2], 0) and np.allclose(small[..., 1], 0)
    rgba = stream_rgba(frame, max_width=6)
    assert rgba.shape == (4, 6, 4) and tuple(rgba[0, 0, :3]) == (200, 0, 90)


def test_a_frame_converted_natively_is_sent_as_it_is_in_one_layer() -> None:
    """A camera that scales and converts to I420 itself hands that over: it goes out unchanged,
    and every stream is published as one layer (no simulcast to encode on the agent)."""
    from lovekit import I420Frame

    sink = LovekitSink([CameraStream("main", "main", "Main")])
    lovekit = FakeLovekit()
    declared: list = []
    publish = lovekit.publish

    def recording(streams: list) -> FakePublished:
        declared.extend(streams)
        return publish(streams)

    lovekit.publish = recording  # type: ignore[method-assign]
    data = np.arange(8 * 4 * 3 // 2, dtype=np.uint8)

    async def run() -> None:
        task = asyncio.create_task(publish_camera_streams(lovekit, sink, CameraStreams()))  # type: ignore[arg-type]
        while lovekit.published is None:
            await asyncio.sleep(0)
        sink.broadcast_i420("main", 8, 4, data)
        await asyncio.sleep(0.3)
        lovekit.published.stopped.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())
    assert lovekit.published is not None
    [frame] = lovekit.published.tracks["main"].frames
    assert isinstance(frame, I420Frame) and (frame.width, frame.height) == (8, 4)
    assert frame.data is data
    assert [stream.simulcast for stream in declared] == [False]


def test_only_eight_bit_frames_go_natively_and_color_only_for_color_detectors() -> None:
    from types import SimpleNamespace

    from newswitch.drivers.uc2.uc2_detector import _natively

    takes = SimpleNamespace(broadcast_i420=lambda *a: None)
    camera = lambda fmt: SimpleNamespace(pixel_format=fmt)  # noqa: E731
    assert _natively(takes, camera("RGB8"), colored=True) is False
    assert _natively(takes, camera("BGR8"), colored=True) is True
    assert _natively(takes, camera("Mono8"), colored=False) is False
    assert _natively(takes, camera("RGB8"), colored=False) is None  # shown gray: numpy's mean
    assert _natively(takes, camera("Mono12"), colored=False) is None  # needs the stretch
    assert _natively(object(), camera("RGB8"), colored=True) is None  # a sink taking no I420
