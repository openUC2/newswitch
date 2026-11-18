"""Tests for the live view's contrast: `stretch_to_uint8` and where the broadcaster uses it."""

from __future__ import annotations

import numpy as np
import pytest

from newswitch.broadcasters import FrameBroadcaster
from newswitch.broadcasters.contrast import stretch_to_uint8
from newswitch.broadcasters.encoders.config import H264EncoderConfig, ZstdEncoderConfig


def _gradient(high: int, dtype: type, shape: tuple[int, ...] = (200, 300)) -> np.ndarray:
    """A frame rising from 0 to `high` along its rows."""
    rows = np.linspace(0, high, shape[0]).astype(dtype)
    return np.broadcast_to(rows[:, None, *([None] * (len(shape) - 2))], shape).copy()


def test_a_dark_frame_uses_the_full_range() -> None:
    """A dark 8-bit frame (HikRobot at short exposure: maximum about 24) spans 0 ... 255."""
    result = stretch_to_uint8(_gradient(24, np.uint8))
    assert result.dtype == np.uint8
    assert result.min() == 0 and result.max() == 255


def test_sixteen_bit_frames_become_eight_bit() -> None:
    """A 16-bit frame using only a few thousand counts still spans 0 ... 255."""
    result = stretch_to_uint8(_gradient(4000, np.uint16))
    assert result.dtype == np.uint8 and result.shape == (200, 300)
    assert result.min() == 0 and result.max() == 255


def test_a_hot_pixel_does_not_set_the_limits() -> None:
    """One saturated pixel is clipped instead of turning the rest of the frame dark."""
    frame = _gradient(24, np.uint8)
    frame[0, 0] = 255
    result = stretch_to_uint8(frame)
    assert np.median(result) > 100  # a min-max stretch would leave the median near 12


def test_a_flat_frame_becomes_black() -> None:
    """Both limits equal: no division by zero, the frame is black."""
    result = stretch_to_uint8(np.full((50, 60), 17, dtype=np.uint16))
    assert result.dtype == np.uint8 and not result.any()


def test_colour_frames_keep_their_colours() -> None:
    """(H, W, 3) frames are stretched with one pair of limits for all channels."""
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[..., 0] = _gradient(20, np.uint8, (40, 40))  # red rises, the others stay dark
    result = stretch_to_uint8(frame)
    assert result.shape == (40, 40, 3)
    assert result[..., 0].max() == 255
    assert result[..., 1].max() == 0 and result[..., 2].max() == 0


class FakeEncoder:
    """Stands in for a running encoder; keeps the frames it is given."""

    is_running = True

    def __init__(self) -> None:
        """Start with no frames."""
        self.frames: list[np.ndarray] = []

    def encode_frame(self, frame: np.ndarray) -> None:
        """Keep the frame."""
        self.frames.append(frame)


@pytest.fixture
def encoders() -> tuple[FrameBroadcaster, FakeEncoder, FakeEncoder, FakeEncoder]:
    """A broadcaster with an H.264 and a Zstd encoder on slot 1, and an H.264 one on slot 2."""
    broadcaster = FrameBroadcaster()
    h264, zstd, other = FakeEncoder(), FakeEncoder(), FakeEncoder()
    broadcaster._encoders[(1, H264EncoderConfig())] = h264
    broadcaster._encoders[(1, ZstdEncoderConfig())] = zstd
    broadcaster._encoders[(2, H264EncoderConfig())] = other
    return broadcaster, h264, zstd, other


def test_only_the_live_view_is_stretched(
    encoders: tuple[FrameBroadcaster, FakeEncoder, FakeEncoder, FakeEncoder],
) -> None:
    """With auto_contrast the H.264 encoder gets the stretched frame, Zstd the raw one."""
    broadcaster, h264, zstd, other = encoders
    frame = _gradient(24, np.uint8)
    broadcaster.broadcast_sync(1, frame, auto_contrast=True)
    assert h264.frames[0].max() == 255
    assert zstd.frames[0] is frame  # the data itself is never changed
    assert other.frames == []  # another slot's encoder gets nothing
    assert frame.max() == 24


def test_without_auto_contrast_every_encoder_gets_the_raw_frame(
    encoders: tuple[FrameBroadcaster, FakeEncoder, FakeEncoder, FakeEncoder],
) -> None:
    """auto_contrast off (the default of broadcast_sync): raw values in the live view too."""
    broadcaster, h264, zstd, _ = encoders
    frame = _gradient(24, np.uint8)
    broadcaster.broadcast_sync(1, frame)
    assert h264.frames[0] is frame and zstd.frames[0] is frame
