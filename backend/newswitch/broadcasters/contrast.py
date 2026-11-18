"""Contrast of the live view: stretch a frame to 8 bit between robust limits.

Used for the H.264 live stream only, when a detector's ``auto_contrast`` is on (see
`FrameBroadcaster.broadcast_sync`). The data of captured images and recordings is never
changed. Like the debug window of uc2_cam_py, which stretches from minimum to maximum, but with
percentiles, so a few hot or dark pixels do not set the limits.
"""

import numpy as np

#: Share of the darkest and of the brightest pixels left outside the stretched range (%).
LOW_PERCENTILE = 0.1
HIGH_PERCENTILE = 99.9
#: The limits are taken from every n-th pixel in both directions (fast for 1920 x 1200).
SAMPLE_STEP = 4


def stretch_to_uint8(frame: np.ndarray) -> np.ndarray:
    """`frame` mapped linearly to 0 ... 255 between its 0.1 and 99.9 percentiles.

    Values outside the limits are clipped. A flat frame (both limits equal) becomes black.
    Colour frames ``(H, W, 3)`` use one pair of limits for all channels, so the colours stay.

    Args:
        frame: A camera frame, ``uint8`` or ``uint16`` (any numeric type works).

    Returns:
        A new ``uint8`` array of the same shape.
    """
    sample = frame[::SAMPLE_STEP, ::SAMPLE_STEP]
    low, high = np.percentile(sample, (LOW_PERCENTILE, HIGH_PERCENTILE))
    if high <= low:
        return np.zeros(frame.shape, dtype=np.uint8)
    scaled = (frame.astype(np.float32) - np.float32(low)) * np.float32(255.0 / (high - low))
    return np.clip(scaled, 0, 255).astype(np.uint8)
