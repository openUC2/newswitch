"""
WebSocket routes for live video streaming.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
from newswitch.auth import Authenticator
from newswitch.broadcasters import FrameBroadcaster, ZstdEncoderConfig, H264EncoderConfig


router = APIRouter()

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


# This is a helper function to get the broadcaster from the app state via WebSocket.
# By default, the app agent, which is set on app.state.agent holds references
# to all contexts, including the FrameBroadcaster context which manages video streaming.
def get_broadcaster_from_websocket(websocket: WebSocket) -> FrameBroadcaster:
    """
    Get the FrameBroadcaster from the app state via WebSocket.

    The broadcaster is set on app.state.agent context during startup.
    """
    agent = getattr(websocket.app.state, "agent", None)
    if agent is None:
        raise RuntimeError("Agent not available")

    broadcaster = agent.get_context_for_type(FrameBroadcaster)
    if broadcaster is None:
        raise RuntimeError("FrameBroadcaster not available")

    return broadcaster


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

    broadcaster = get_broadcaster_from_websocket(websocket)

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

    broadcaster = get_broadcaster_from_websocket(websocket)

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
