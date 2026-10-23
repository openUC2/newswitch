"""The websocket live view: a detector's frames, encoded as the client asks (Zstd, H.264).

FastAPI only (``main_fastapi.py``): the routes stream from the running agent's
`FrameBroadcaster`, the `FrameSink` ``main_fastapi.py`` provides to the detectors.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from newswitch.accounts.auth import Authenticator
from newswitch.broadcasters import FrameBroadcaster, H264EncoderConfig, ZstdEncoderConfig
from newswitch.routes import running_context

logger = logging.getLogger(__name__)

#: How long a client gets to send its auth frame before the socket is dropped. Short,
#: because the frame is sent from the client's `onopen` handler.
AUTH_FRAME_TIMEOUT = 10.0


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


@router.websocket("/zstd/{detector_slot}")
async def stream_zstd(websocket: WebSocket, detector_slot: int) -> None:
    """
    WebSocket endpoint for Zstd video streaming.

    Streams Zstd-compressed chunks to connected clients.
    Multiple clients with the same settings share a single encoder.
    """
    await websocket.accept()

    if not await authenticate_stream_websocket(websocket):
        return

    broadcaster = await running_broadcaster(websocket)
    if broadcaster is None:
        return

    # Get subscription to shared encoder
    config = ZstdEncoderConfig(level=1, threshold=0.0, use_delta=True)

    # We run encoding in a separate thread, so we need to use an encoded subscription which gives us access to the encoded chunks directly.
    subscription = await broadcaster.get_subscription_(detector_slot, config)

    try:
        while True:
            if not broadcaster.is_broadcasting:
                await asyncio.sleep(0.1)
                continue

            # Get encoded chunk from our subscription
            chunk = await subscription.get_encoded_chunk(timeout=1.0)
            if chunk is None:
                continue

            if not subscription.is_running:
                break

            await websocket.send_bytes(chunk)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Stream error: %s", e)
    finally:
        await broadcaster.arelease_subscription(subscription)


@router.websocket("/h264/{detector_slot}")
async def stream_h264(websocket: WebSocket, detector_slot: int) -> None:
    """
    WebSocket endpoint for H264 video streaming.

    Streams H264-compressed chunks to connected clients.
    Multiple clients with the same settings share a single encoder.
    """
    await websocket.accept()

    if not await authenticate_stream_websocket(websocket):
        return

    broadcaster = await running_broadcaster(websocket)
    if broadcaster is None:
        return

    # Get subscription to shared encoder
    config = H264EncoderConfig()

    # We run encoding in a separate thread, so we need to use an encoded subscription which gives us access to the encoded chunks directly.
    subscription = await broadcaster.get_subscription_(detector_slot, config)

    try:
        while True:
            if not broadcaster.is_broadcasting:
                await asyncio.sleep(0.1)
                continue

            # Get encoded chunk from our subscription
            chunk = await subscription.get_encoded_chunk(timeout=1.0)
            if chunk is None:
                continue

            if not subscription.is_running:
                break

            await websocket.send_bytes(chunk)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Stream error: %s", e)
    finally:
        await broadcaster.arelease_subscription(subscription)
