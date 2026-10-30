"""The websocket live view: a detector's frames, one whole frame per message.

FastAPI only (``main_fastapi.py``): the routes stream from the running agent's
`FrameBroadcaster`, the `FrameSink` ``main_fastapi.py`` provides to the detectors.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from newswitch.accounts.auth import Authenticator
from newswitch.broadcasters import FrameBroadcaster
from newswitch.broadcasters.frame import FrameSubscription
from newswitch.broadcasters.wire import pack_frame
from newswitch.routes import running_context

logger = logging.getLogger(__name__)

#: How long a client gets to send its auth frame before the socket is dropped. Short,
#: because the frame is sent from the client's `onopen` handler.
AUTH_FRAME_TIMEOUT = 10.0

#: What a viewer is sent unless it asks otherwise: the longer side of the image (reached by
#: binning) and the frames per second. 640x480 of uint16 at 30 fps is about 150 Mbit/s; a
#: slower link gets fewer frames: a viewer only gets the next once it took the last.
DEFAULT_MAX_SIZE = 640
DEFAULT_MAX_FPS = 30.0


async def authenticate_stream_websocket(websocket: WebSocket) -> bool:
    """Consume and validate the client's opening auth frame.

    These sockets authenticate in band, like the agent socket does, because a browser
    cannot set an `Authorization` header on a `WebSocket`. The alternative - a token in
    the query string - would write the credential into every access log.

    The socket must already be accepted: a rejection before the handshake completes
    fails the HTTP upgrade, and browsers report that as an opaque close code 1006 that
    a client cannot tell apart from a network drop. Closing an accepted socket with
    1008 gives the client a code it can act on.

    Returns:
        Whether the client authenticated. On failure the socket is already closed.
    """
    authenticator: Authenticator = websocket.app.state.authenticator

    try:
        frame = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_FRAME_TIMEOUT)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        await _close_unauthorized(websocket)
        return False

    token = frame.get("token") if isinstance(frame, dict) else None
    if not authenticator.check_token(token):
        await _close_unauthorized(websocket)
        return False

    return True


async def _close_unauthorized(websocket: WebSocket) -> None:
    """Close with 1008, tolerating a client that already went away.

    One path into here is the client disconnecting mid-handshake, and closing an
    already-closed socket raises - which would turn an ordinary disconnect into a
    traceback in the logs.
    """
    try:
        await websocket.close(code=1008, reason="unauthorized")
    except RuntimeError:
        pass


router = APIRouter()


async def running_broadcaster(websocket: WebSocket) -> FrameBroadcaster | None:
    """The running agent's broadcaster; None (the socket closed, 1013) before it started."""
    try:
        return running_context(websocket, FrameBroadcaster)
    except HTTPException:
        await websocket.close(code=1013, reason="the microscope is not started yet")
        return None


async def _send_frames(
    websocket: WebSocket,
    subscription: FrameSubscription,
    acknowledged: asyncio.Event,
    max_size: int,
    max_fps: float,
) -> None:
    """Send the newest frame, whenever the client took the one before and another is due.

    `send_bytes` does not wait for the client: the server buffers whatever the client does
    not take yet, without limit. So one frame is on its way at a time, until `acknowledged`.
    """
    interval = 1.0 / max_fps if max_fps > 0 else 0.0
    loop = asyncio.get_running_loop()
    told_unshowable = False
    while True:
        frame = await subscription.next_frame()
        started = loop.time()
        # Off the event loop, which also runs the agent's actions and state updates.
        message = await asyncio.to_thread(pack_frame, frame, max_size)
        if message is None:
            if not told_unshowable:
                logger.warning(
                    "Slot %s sends frames the live view cannot show: shape %s, dtype %s",
                    frame.slot,
                    frame.data.shape,
                    frame.data.dtype,
                )
                told_unshowable = True
            continue
        await websocket.send_bytes(message)
        await acknowledged.wait()
        acknowledged.clear()
        await asyncio.sleep(max(0.0, interval - (loop.time() - started)))


async def _receive_until_closed(websocket: WebSocket, acknowledged: asyncio.Event) -> None:
    """Take the client's acknowledgements, one message per frame, until the client is gone.

    Watching for it here notices a client that leaves while there is nothing to send.
    """
    while (await websocket.receive())["type"] != "websocket.disconnect":
        acknowledged.set()


@router.websocket("/frames/{detector_slot}")
async def stream_frames(
    websocket: WebSocket,
    detector_slot: int,
    max_size: int = DEFAULT_MAX_SIZE,
    max_fps: float = DEFAULT_MAX_FPS,
) -> None:
    """A detector's frames, each message one whole frame (`newswitch.broadcasters.wire`).

    After its auth frame the client sends one message per frame it took, of any content; the
    next frame comes after that, and it is the newest. A slower client gets fewer frames.

    Args:
        detector_slot: The detector to show.
        max_size: The longer side of the image, reached by binning; 0 sends full size.
        max_fps: The most frames per second this viewer is sent; 0 sends them all.
    """
    await websocket.accept()

    if not await authenticate_stream_websocket(websocket):
        return

    broadcaster = await running_broadcaster(websocket)
    if broadcaster is None:
        return

    with broadcaster.subscribe(detector_slot) as subscription:
        acknowledged = asyncio.Event()
        tasks = {
            asyncio.create_task(
                _send_frames(websocket, subscription, acknowledged, max_size, max_fps)
            ),
            asyncio.create_task(_receive_until_closed(websocket, acknowledged)),
        }
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            for result in await asyncio.gather(*tasks, return_exceptions=True):
                # Sending to a client that just left is how most viewers end.
                if isinstance(result, Exception) and not isinstance(
                    result, (WebSocketDisconnect, RuntimeError)
                ):
                    logger.warning("Stream error: %s", result)
