"""
WebSocket routes for live video streaming.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
from rekuest_next.agents.context import get_context_name
from newswitch.auth import Authenticator
from newswitch.broadcasters import FrameBroadcaster, ZstdEncoderConfig, H264EncoderConfig


router = APIRouter()

#: How long a client gets to send its auth frame before the socket is dropped. Short,
#: because the frame is sent from the client's `onopen` handler.
AUTH_FRAME_TIMEOUT = 10.0

#: How long a stream waits for the agent to provide the FrameBroadcaster. The agent's
#: startup hooks run in a task started after the app began serving, so a client that
#: connects right after startup can arrive before the context exists - and the frontend
#: does not reconnect when the socket is closed.
BROADCASTER_WAIT_TIMEOUT = 10.0


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


async def await_broadcaster(websocket: WebSocket) -> FrameBroadcaster | None:
    """Get the FrameBroadcaster from the agent's contexts, waiting until it is provided.

    The agent (`app.state.agent`) keeps its contexts in a dict keyed by context name;
    `get_context_name` gives the same key rekuest assigns when the startup hook returns
    the broadcaster.

    Returns:
        The broadcaster, or None if it did not appear within `BROADCASTER_WAIT_TIMEOUT`.

    Raises:
        TypeError: The context under the broadcaster's name is something else.
    """
    contexts = websocket.app.state.agent.contexts
    key = get_context_name(FrameBroadcaster)
    deadline = asyncio.get_running_loop().time() + BROADCASTER_WAIT_TIMEOUT

    while (broadcaster := contexts.get(key)) is None:
        if asyncio.get_running_loop().time() > deadline:
            return None
        await asyncio.sleep(0.1)

    if not isinstance(broadcaster, FrameBroadcaster):
        raise TypeError(
            f"Context {key!r} is a {type(broadcaster).__name__}, not a FrameBroadcaster"
        )
    return broadcaster


async def _close_unavailable(websocket: WebSocket) -> None:
    """Close with 1011, tolerating a client that already went away."""
    try:
        await websocket.close(code=1011, reason="frame broadcaster unavailable")
    except RuntimeError:
        pass


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

    broadcaster = await await_broadcaster(websocket)
    if broadcaster is None:
        await _close_unavailable(websocket)
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
        print(f"Stream error: {e}")
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

    broadcaster = await await_broadcaster(websocket)
    if broadcaster is None:
        await _close_unavailable(websocket)
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
        print(f"Stream error: {e}")
    finally:
        await broadcaster.arelease_subscription(subscription)
