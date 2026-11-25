"""What a stream sends when the network is tested, not the camera: the time it was sent.

Under ``simulate: debug`` (`newswitch.infra.streaming.lovekit.publish_camera_streams`) each camera's
stream carries this instead of the camera's frames: the wall-clock time the frame was sent
(``HH:MM:SS.mmm``), its number, and a bar sweeping across once a second, drawn straight at the
stream's size as the RGBA a video track takes. Nothing of it runs through a camera, the optics or a
conversion, so what a viewer shows, held against a clock, is the encoder, the network and the
decoder alone; a skipped number is a frame lost on the way, a bar that stutters frames held up.
"""

from __future__ import annotations

import time

import numpy as np

#: 5 x 7 glyphs, a row of five bits each: the digits and what separates them.
_FONT = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
}
_GLYPHS = {
    character: np.array([[bit == "1" for bit in row] for row in rows])
    for character, rows in _FONT.items()
}


def _bitmap(text: str) -> np.ndarray:
    """`text` as a 7-row bitmap, one blank column between glyphs."""
    parts = []
    for character in text:
        parts += [_GLYPHS[character], np.zeros((7, 1), bool)]
    return np.concatenate(parts[:-1], axis=1)


def timestamp_rgba(width: int, height: int, frame: int, now: float | None = None) -> np.ndarray:
    """A ``(height, width, 4)`` uint8 image of the time `now` (default: this instant) and `frame`,
    white on black, with a bar along the bottom at the fraction of the second."""
    now = time.time() if now is None else now
    image = np.zeros((height, width, 4), np.uint8)
    image[..., 3] = 255
    lines = [
        time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 1000) % 1000:03d}",
        f"#{frame:06d}",
    ]
    bitmaps = [_bitmap(line) for line in lines]
    scale = max(1, min(int(0.9 * width / max(b.shape[1] for b in bitmaps)), height // 25))
    y = max(0, (height - sum(b.shape[0] + 3 for b in bitmaps) * scale) // 2)
    for bitmap in bitmaps:
        big = np.repeat(np.repeat(bitmap, scale, axis=0), scale, axis=1)
        x = max(0, (width - big.shape[1]) // 2)
        h, w = min(big.shape[0], height - y), min(big.shape[1], width - x)
        if h > 0 and w > 0:
            image[y : y + h, x : x + w, :3][big[:h, :w]] = 255
        y += (bitmap.shape[0] + 3) * scale
    band = max(1, height // 20)
    bar = int((now % 1.0) * width)
    image[height - band :, max(0, bar - band // 2) : bar + band // 2 + 1, :3] = 255
    return image
