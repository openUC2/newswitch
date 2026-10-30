"""The websocket live view: whole frames, the newest one, and viewers that come and go."""

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Callable, Iterator

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from newswitch.accounts.auth import AllowAllAuthenticator
from newswitch.broadcasters import FrameBroadcaster
from newswitch.broadcasters.frame import SlotFrame
from newswitch.broadcasters.wire import HEADER, MAGIC, binning_for, pack_frame
from newswitch.routes.liveview import router


@pytest.fixture
def broadcaster() -> FrameBroadcaster:
    """The sink the running agent would hold."""
    return FrameBroadcaster()


@pytest.fixture
def client(broadcaster: FrameBroadcaster) -> Iterator[TestClient]:
    """The live view's routes, as if the agent were running with `broadcaster`."""
    app = FastAPI()
    app.state.authenticator = AllowAllAuthenticator()
    app.state.agent = SimpleNamespace(contexts={"sink": broadcaster})
    app.include_router(router, prefix="/stream")
    with TestClient(app) as test_client:
        yield test_client


def unpack(message: bytes) -> tuple[dict[str, int | float], np.ndarray]:
    """A message's header and its pixels, as the frontend reads them."""
    magic, sample, factor, slot, sequence, width, height, low, high, time_s = HEADER.unpack_from(
        message
    )
    assert magic == MAGIC
    dtype = {1: "<u1", 2: "<u2"}[sample]
    pixels = np.frombuffer(message, dtype=dtype, offset=HEADER.size).reshape(height, width)
    return (
        dict(factor=factor, slot=slot, sequence=sequence, low=low, high=high, time_s=time_s),
        pixels,
    )


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Poll `condition` until it holds."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "the condition did not come true in time"
        time.sleep(0.01)


def test_the_header_is_aligned_for_typed_arrays() -> None:
    """The frontend views the pixels in place: uint16 needs an even offset, f64 is 8 bytes."""
    assert HEADER.size == 32


@pytest.mark.parametrize(
    ("width", "height", "max_size", "factor"),
    [
        (512, 512, 640, 1),
        (640, 480, 640, 1),
        (1920, 1200, 640, 3),
        (1200, 1920, 640, 3),
        (1920, 1200, 0, 1),
        (1, 100, 1, 1),
    ],
)
def test_binning_brings_the_longer_side_down(
    width: int, height: int, max_size: int, factor: int
) -> None:
    """Integer factors only, the smallest that fits; 0 is full size."""
    assert binning_for(width, height, max_size) == factor


def test_a_frame_arrives_with_exactly_the_detectors_values(
    client: TestClient, broadcaster: FrameBroadcaster
) -> None:
    """Unbinned, the live view is lossless; the first frame needs no keyframe to wait for."""
    image = np.arange(480 * 640, dtype=np.uint32).reshape(480, 640).astype(np.uint16)
    broadcaster.broadcast_sync(1, image)

    with client.websocket_connect("/stream/frames/1") as websocket:
        websocket.send_json({"token": "any"})
        header, pixels = unpack(websocket.receive_bytes())

    assert header["slot"] == 1
    assert header["factor"] == 1
    np.testing.assert_array_equal(pixels, image)


def test_a_large_frame_is_binned_to_block_means_in_its_own_units(
    client: TestClient, broadcaster: FrameBroadcaster
) -> None:
    """The default size is reached by averaging, so the values stay the detector's."""
    image = np.full((1200, 1920), 1000, dtype=np.uint16)
    image[0:3, 0:3] = [[1000, 2000, 3000], [4000, 5000, 6000], [7000, 8000, 9000]]
    broadcaster.broadcast_sync(2, image)

    with client.websocket_connect("/stream/frames/2") as websocket:
        websocket.send_json({"token": "any"})
        header, pixels = unpack(websocket.receive_bytes())

    assert header["factor"] == 3
    assert pixels.shape == (400, 640)
    assert pixels.dtype == np.uint16
    assert pixels[0, 0] == 5000
    assert pixels[-1, -1] == 1000


def test_full_size_is_on_request(client: TestClient, broadcaster: FrameBroadcaster) -> None:
    """max_size=0 sends the image as the detector took it."""
    image = np.zeros((1200, 1920), dtype=np.uint16)
    broadcaster.broadcast_sync(1, image)

    with client.websocket_connect("/stream/frames/1?max_size=0") as websocket:
        websocket.send_json({"token": "any"})
        header, pixels = unpack(websocket.receive_bytes())

    assert header["factor"] == 1
    assert pixels.shape == (1200, 1920)


def test_uint8_frames_stay_uint8() -> None:
    """A detector's dtype is kept, binned or not."""
    frame = SlotFrame(1, 0, 0.0, np.full((1200, 1920), 200, dtype=np.uint8))
    message = pack_frame(frame, 640)
    assert message is not None
    header, pixels = unpack(message)
    assert pixels.dtype == np.uint8
    assert pixels[0, 0] == 200
    assert header["factor"] == 3


@pytest.mark.parametrize(
    "data",
    [np.zeros((4, 4, 3), dtype=np.uint8), np.zeros((4, 4), dtype=np.float32)],
)
def test_an_image_the_view_cannot_show_is_not_sent(data: np.ndarray) -> None:
    """Gray uint8 and uint16 only: anything else is left out, not sent as garbage."""
    assert pack_frame(SlotFrame(1, 0, 0.0, data), 640) is None


def test_viewers_of_one_size_share_the_work() -> None:
    """A frame is binned and packed once per size."""
    frame = SlotFrame(1, 0, 0.0, np.zeros((1200, 1920), dtype=np.uint16))
    assert pack_frame(frame, 640) is pack_frame(frame, 640)


def test_a_late_viewer_gets_a_picture_at_once(
    client: TestClient, broadcaster: FrameBroadcaster
) -> None:
    """A viewer that joins while another watches needs nothing from before it came."""
    image = np.full((48, 64), 7, dtype=np.uint16)
    broadcaster.broadcast_sync(1, image)

    with client.websocket_connect("/stream/frames/1") as first:
        first.send_json({"token": "any"})
        first.receive_bytes()
        broadcaster.broadcast_sync(1, image + 1)
        first.send_text("took it")
        first.receive_bytes()

        with client.websocket_connect("/stream/frames/1") as late:
            late.send_json({"token": "any"})
            header, pixels = unpack(late.receive_bytes())

    assert header["sequence"] == 1
    assert pixels[0, 0] == 8


def test_a_slot_only_gets_its_own_frames(client: TestClient, broadcaster: FrameBroadcaster) -> None:
    """Another detector's frame does not reach this slot's viewer."""
    broadcaster.broadcast_sync(2, np.full((4, 4), 2, dtype=np.uint16))
    broadcaster.broadcast_sync(1, np.full((4, 4), 1, dtype=np.uint16))

    with client.websocket_connect("/stream/frames/1") as websocket:
        websocket.send_json({"token": "any"})
        header, pixels = unpack(websocket.receive_bytes())

    assert header["slot"] == 1
    assert pixels[0, 0] == 1


def test_a_slow_viewer_skips_to_the_newest_frame() -> None:
    """Frames that came while a viewer was busy are left out, never queued."""

    async def scenario() -> tuple[int, int]:
        broadcaster = FrameBroadcaster()
        with broadcaster.subscribe(1) as subscription:
            for value in range(5):
                broadcaster.broadcast_sync(1, np.full((2, 2), value, dtype=np.uint16))
            frame = await subscription.next_frame()
            return frame.sequence, int(frame.data[0, 0])

    assert asyncio.run(scenario()) == (4, 4)


def test_a_viewer_is_sent_no_frame_until_it_took_the_last_and_then_the_newest(
    client: TestClient, broadcaster: FrameBroadcaster
) -> None:
    """One frame on its way at a time: the server does not buffer what a client cannot take.

    Sending more would pile up in the server's memory, as `send_bytes` does not wait for the
    client: a viewer that stopped reading took a server to 2.3 GB in half a minute.
    """
    image = np.zeros((4, 4), dtype=np.uint16)
    broadcaster.broadcast_sync(1, image)

    with client.websocket_connect("/stream/frames/1?max_fps=0") as websocket:
        websocket.send_json({"token": "any"})
        first, _ = unpack(websocket.receive_bytes())
        for value in range(1, 5):
            broadcaster.broadcast_sync(1, image + value)
        time.sleep(0.1)  # time enough to send, if it did not wait
        websocket.send_text("took it")
        second, pixels = unpack(websocket.receive_bytes())

    assert first["sequence"] == 0
    assert second["sequence"] == 4
    assert pixels[0, 0] == 4


def test_a_frame_from_the_detectors_thread_wakes_a_waiting_viewer() -> None:
    """The handover crosses threads: the viewer must wake without anything else happening."""

    async def scenario() -> float:
        broadcaster = FrameBroadcaster()
        with broadcaster.subscribe(1) as subscription:
            waiting = asyncio.create_task(subscription.next_frame())
            await asyncio.sleep(0.05)
            sent = time.monotonic()
            threading.Thread(
                target=broadcaster.broadcast_sync,
                args=(1, np.zeros((2, 2), dtype=np.uint16)),
            ).start()
            await asyncio.wait_for(waiting, timeout=2.0)
            return time.monotonic() - sent

    assert asyncio.run(scenario()) < 0.5


def test_a_viewer_is_let_go_when_it_leaves_while_no_frames_come(
    client: TestClient, broadcaster: FrameBroadcaster
) -> None:
    """With live stopped there is nothing to send, and still a client that left is noticed."""
    with client.websocket_connect("/stream/frames/1") as websocket:
        websocket.send_json({"token": "any"})
        wait_until(lambda: broadcaster.subscriber_count(1) == 1)
    wait_until(lambda: broadcaster.subscriber_count(1) == 0)


def test_many_viewers_coming_and_going_leave_nothing_behind(
    client: TestClient, broadcaster: FrameBroadcaster
) -> None:
    """Viewers hold nothing but their subscription, so there is nothing to leak or race."""
    broadcaster.broadcast_sync(1, np.zeros((4, 4), dtype=np.uint16))

    def visit() -> None:
        with client.websocket_connect("/stream/frames/1") as websocket:
            websocket.send_json({"token": "any"})
            websocket.receive_bytes()

    threads = [threading.Thread(target=visit) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wait_until(lambda: broadcaster.subscriber_count(1) == 0)
