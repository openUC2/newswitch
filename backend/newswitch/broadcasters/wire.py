"""A frame as the live view sends it: a fixed header, then the pixels.

One websocket message is one whole frame, and the client answers each with a message of its
own before it is sent the next (`newswitch.routes.liveview`). The header (little-endian, 32 bytes, so the
pixels after it are aligned for a typed array):

    ====== ===== =========================================================
    offset type  field
    ====== ===== =========================================================
    0      4s    magic, ``NSF1``
    4      u8    bytes per sample: 1 (uint8) or 2 (uint16)
    5      u8    binning factor the sent image was reduced by
    6      u16   detector slot
    8      u32   sequence number of the frame (the viewer may have skipped some)
    12     u16   width of the sent image
    14     u16   height of the sent image
    16     u16   contrast low: the 1st percentile of the image
    18     u16   contrast high: its 99.9th percentile
    20     f64   when the detector handed the frame over, in seconds since the epoch
    28           4 bytes of padding
    ====== ===== =========================================================

The pixels are the detector's own values, unscaled: row after row, little-endian. Binning
takes block means, so a binned frame is still in the detector's units. The contrast is only
a suggestion for how to show them; frontend/src/components/liveview/frames.ts reads this.
"""

import math
import struct
from typing import Optional

import numpy as np

from newswitch.broadcasters.frame import SlotFrame

HEADER = struct.Struct("<4sBBHIHHHHd4x")
MAGIC = b"NSF1"

#: About how many pixels the contrast is computed from, however large the image.
CONTRAST_SAMPLES = 65536


def binning_for(width: int, height: int, max_size: int) -> int:
    """The smallest factor that brings the longer side down to `max_size` (<= 0: full size)."""
    if max_size <= 0:
        return 1
    wanted = math.ceil(max(width, height) / max_size)
    return max(1, min(wanted, width, height, 255))


def _binned(image: np.ndarray, factor: int) -> np.ndarray:
    """Block means, in the image's own dtype; a rest that fills no block is left out."""
    if factor == 1:
        return image
    height, width = image.shape[0] // factor, image.shape[1] // factor
    cropped = image[: height * factor, : width * factor]
    # One strided addition per position in a block: far faster than summing a 4D reshape,
    # which runs an inner loop per block, and this runs for every frame a viewer is sent.
    total = np.zeros((height, width), dtype=np.uint32)
    for row in range(factor):
        for column in range(factor):
            total += cropped[row::factor, column::factor]
    return (total // (factor * factor)).astype(image.dtype)


def _contrast(image: np.ndarray) -> tuple[int, int]:
    """The 1st and 99.9th percentile of `image`, from a sample of its pixels."""
    step = max(1, int(math.sqrt(image.size / CONTRAST_SAMPLES)))
    low, high = np.percentile(image[::step, ::step], (1.0, 99.9))
    return int(low), int(high)


def pack_frame(frame: SlotFrame, max_size: int) -> Optional[bytes]:
    """`frame` as one message, its longer side at most `max_size` (<= 0: full size).

    Returns:
        The message, or None for an image the live view cannot show: it takes gray images
        (height, width) of uint8 or uint16.
    """
    image = frame.data
    if image.ndim == 3 and image.shape[2] == 1:
        image = image[..., 0]
    if image.ndim != 2 or image.dtype not in (np.uint8, np.uint16):
        return None

    factor = binning_for(image.shape[1], image.shape[0], max_size)
    message = frame.messages.get(factor)
    if message is not None:
        return message

    binned = _binned(image, factor)
    low, high = _contrast(binned)
    header = HEADER.pack(
        MAGIC,
        binned.dtype.itemsize,
        factor,
        frame.slot,
        frame.sequence & 0xFFFFFFFF,
        binned.shape[1],
        binned.shape[0],
        low,
        high,
        frame.time_s,
    )
    message = header + binned.astype(binned.dtype.newbyteorder("<"), copy=False).tobytes()
    frame.messages[factor] = message
    return message
