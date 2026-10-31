"""Estimation and validation of the 3D affine matrix mapping pixel to stage coordinates."""

from dataclasses import dataclass

import numpy as np
from scipy import ndimage


@dataclass
class AffineMatrix:
    """A fitted 4x4 pixel-to-stage affine matrix together with its least-squares fit quality."""

    matrix: np.ndarray
    residuals: np.ndarray
    rank: int
    singular_values: np.ndarray


#: How many times `pixel_shift` measures again on what two images have in common.
_SHIFT_ROUNDS = 6
#: The smallest overlap, in pixels per side, worth correlating.
_SHIFT_MIN_OVERLAP = 16


def _correlation_peak(reference: np.ndarray, moved: np.ndarray, pad: bool) -> tuple[float, float]:
    """Where two same-sized images correlate best (x, y), to a fraction of a pixel."""
    height, width = reference.shape
    window = np.outer(np.hanning(height), np.hanning(width))
    ref = (reference - reference.mean()) * window
    mov = (moved - moved.mean()) * window
    # Padded, a long shift is not read as a short one from the other side of the frame.
    shape = (2 * height, 2 * width) if pad else (height, width)
    correlation = np.fft.irfft2(np.fft.rfft2(mov, shape) * np.conj(np.fft.rfft2(ref, shape)), shape)
    peak_y, peak_x = np.unravel_index(int(np.argmax(correlation)), correlation.shape)
    rows, columns = correlation.shape

    def refined(before: float, peak: float, after: float) -> float:
        curvature = before - 2.0 * peak + after
        return 0.5 * (before - after) / curvature if curvature != 0 else 0.0

    x = peak_x + refined(
        correlation[peak_y, (peak_x - 1) % columns],
        correlation[peak_y, peak_x],
        correlation[peak_y, (peak_x + 1) % columns],
    )
    y = peak_y + refined(
        correlation[(peak_y - 1) % rows, peak_x],
        correlation[peak_y, peak_x],
        correlation[(peak_y + 1) % rows, peak_x],
    )
    return float(x - columns if x > columns / 2 else x), float(y - rows if y > rows / 2 else y)


def _overlaps(
    ref: np.ndarray, mov: np.ndarray, x: int, y: int
) -> tuple[np.ndarray, np.ndarray] | None:
    """What two images have in common if `mov` is shifted by (x, y), or None if too little."""
    height, width = ref.shape
    if width - abs(x) < _SHIFT_MIN_OVERLAP or height - abs(y) < _SHIFT_MIN_OVERLAP:
        return None
    return (
        ref[max(0, -y) : height - max(0, y), max(0, -x) : width - max(0, x)],
        mov[max(0, y) : height + min(0, y), max(0, x) : width + min(0, x)],
    )


def _phase_peak(ref: np.ndarray, mov: np.ndarray) -> tuple[int, int]:
    """Where two images correlate best when every coarse frequency counts alike (x, y).

    Good at long shifts, where the window starves plain correlation. Only the frequencies the
    optics may well pass are used, as beyond them is noise.
    """
    height, width = ref.shape
    window = np.outer(np.hanning(height), np.hanning(width))
    cross = np.fft.rfft2(mov * window) * np.conj(np.fft.rfft2(ref * window))
    fy = np.fft.fftfreq(height)[:, None]
    fx = np.fft.rfftfreq(width)[None, :]
    cross = cross * (np.hypot(fx, fy) < 0.125) / (np.abs(cross) + 1e-12)
    correlation = np.fft.irfft2(cross, ref.shape)
    peak_y, peak_x = np.unravel_index(int(np.argmax(correlation)), correlation.shape)
    return (
        int(peak_x - width if peak_x > width // 2 else peak_x),
        int(peak_y - height if peak_y > height // 2 else peak_y),
    )


def _agreement(ref: np.ndarray, mov: np.ndarray, x: int, y: int) -> float:
    """How alike two images are under a shift, from -1 to 1, on what they have in common."""
    parts = _overlaps(ref, mov, x, y)
    if parts is None:
        return -1.0
    a, b = parts[0] - parts[0].mean(), parts[1] - parts[1].mean()
    energy = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / energy) if energy > 0 else -1.0


def pixel_shift(reference: np.ndarray, moved: np.ndarray) -> tuple[float, float]:
    """How far (x, y, in pixels) the content of `moved` is shifted against `reference`.

    To a fraction of a pixel, as a few pixels' move rounded to whole pixels is many percent off.

    Two ways to a first guess, as neither always works: plain correlation is robust against noise
    but starves on long shifts, and phase correlation the other way round. How alike the images are
    under each guess decides. A window also pulls a peak towards zero, so it then measures again on
    what the two have in common until nothing is left to pull. What does not move with the sample,
    such as vignetting, is taken out first: it would vote for no shift at all.
    """
    sigma = min(reference.shape) / 16.0
    ref = reference.astype(np.float64)
    ref = ref - ndimage.gaussian_filter(ref, sigma)
    mov = moved.astype(np.float64)
    mov = mov - ndimage.gaussian_filter(mov, sigma)

    plain = _correlation_peak(ref, mov, pad=True)
    guesses = [(int(round(plain[0])), int(round(plain[1]))), _phase_peak(ref, mov)]
    x_guess, y_guess = max(guesses, key=lambda guess: _agreement(ref, mov, *guess))

    x, y = float(x_guess), float(y_guess)
    for _ in range(_SHIFT_ROUNDS):
        whole_x, whole_y = int(round(x)), int(round(y))
        parts = _overlaps(ref, mov, whole_x, whole_y)
        if parts is None:
            break
        left_x, left_y = _correlation_peak(parts[0], parts[1], pad=False)
        previous_x, previous_y = x, y
        x, y = whole_x + left_x, whole_y + left_y
        if abs(x - previous_x) < 0.01 and abs(y - previous_y) < 0.01:
            break
    return x, y


def calibrate_pixel_to_stage(
    reference: np.ndarray,
    moved_x: np.ndarray,
    moved_y: np.ndarray,
    dx_um: float,
    dy_um: float,
) -> list[list[float]]:
    """The 4x4 pixel-to-stage affine from two stage moves at a fixed focus.

    `moved_x` is taken after moving the stage `dx_um` in x only, `moved_y` after moving it
    `dy_um` in y only (both from where `reference` was taken). Their pixel shifts give the
    2x2 map from stage micrometres to pixels; its inverse is the pixel-to-stage scale
    (rotation, flip and skew included). Z is left as it is (1:1).

    Raises:
        ValueError: A move did not shift the image, or both shifted it the same way: the
            pixel scale cannot be determined (no structure in the sample, moves too small).
    """
    sx = pixel_shift(reference, moved_x)
    sy = pixel_shift(reference, moved_y)
    # Columns: pixels per micrometre of stage x, and of stage y
    um_to_px = np.array([[sx[0] / dx_um, sy[0] / dy_um], [sx[1] / dx_um, sy[1] / dy_um]])
    if abs(np.linalg.det(um_to_px)) < 1e-9 or np.linalg.cond(um_to_px) > 1e3:
        raise ValueError(
            f"the stage moves shifted the image by {sx} and {sy} px: the pixel scale cannot "
            "be determined"
        )
    px_to_um = np.linalg.inv(um_to_px)
    return [
        [float(px_to_um[0, 0]), float(px_to_um[0, 1]), 0.0, 0.0],
        [float(px_to_um[1, 0]), float(px_to_um[1, 1]), 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
