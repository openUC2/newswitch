"""
Frame Generation Helpers

Pure functions for microscopy frame simulation.
"""

from math import cos, sin
from typing import Tuple

import numpy as np
from scipy.ndimage import gaussian_filter, zoom


def render_astigmatic_psf(
    height: int,
    width: int,
    z_offset: float,
    phi_deg: float = 33.0,
    s0: float = 1.7,
    astig_slope: float = 0.33,
    amplitude: float = 2400.0,
    background: float = 35.0,
    x_offset: float = 0.0,
    y_offset: float = 0.0,
) -> np.ndarray:
    """
    Render an astigmatic point spread function.

    Args:
        height: Frame height in pixels.
        width: Frame width in pixels.
        z_offset: Z position (defocus amount).
        phi_deg: Astigmatism axis rotation in degrees.
        s0: Base sigma at nominal focus (pixels).
        astig_slope: Astigmatism slope (sigma_x = s0 + a*z, sigma_y = s0 - a*z).
        amplitude: PSF amplitude.
        background: Background intensity.
        x_offset: X position offset.
        y_offset: Y position offset.

    Returns:
        2D numpy array with the rendered PSF.
    """
    phi = np.deg2rad(phi_deg)

    y, x = np.mgrid[0:height, 0:width].astype(np.float32)

    cx = width / 2 + x_offset
    cy = height / 2 + y_offset

    # Astigmatism: different sigma in x and y depending on z
    sx = max(s0 + astig_slope * z_offset, 0.5)
    sy = max(s0 - astig_slope * z_offset, 0.5)

    # Rotate coordinates by phi (principal axes of astigmatism)
    xp = (x - cx) * cos(phi) + (y - cy) * sin(phi)
    yp = -(x - cx) * sin(phi) + (y - cy) * cos(phi)

    g = np.exp(-0.5 * ((xp / sx) ** 2 + (yp / sy) ** 2))
    frame = amplitude * g + background

    return frame.astype(np.float32)


def add_noise(
    frame: np.ndarray,
    read_noise: float = 2.2,
    poisson: bool = True,
    rng: np.random.Generator = None,
) -> np.ndarray:
    """
    Add realistic noise to a frame.

    Args:
        frame: Input frame.
        read_noise: Read noise standard deviation.
        poisson: Whether to apply Poisson noise.
        rng: Random number generator. Uses default if not provided.

    Returns:
        Frame with noise added.
    """
    rng = rng or np.random.default_rng()

    if poisson:
        # Clip to non-negative before Poisson sampling
        frame = rng.poisson(np.clip(frame, 0, None)).astype(np.float32)
    else:
        frame = frame.astype(np.float32)

    if read_noise > 0:
        frame += rng.normal(0, read_noise, frame.shape).astype(np.float32)

    return np.clip(frame, 0, None)


def create_sample_image(
    height: int,
    width: int,
    sample_type: str = "branching",
    seed: int = 0,
) -> np.ndarray:
    """
    Create a sample image for microscopy simulation.

    Args:
        height: Image height.
        width: Image width.
        sample_type: Type of sample ("branching", "cells", "grid").
        seed: Random seed for reproducibility.

    Returns:
        2D numpy array with the sample image (normalized 0-1).
    """
    np.random.seed(seed)

    if sample_type == "branching":
        return _create_branching_sample(height, width)
    elif sample_type == "cells":
        return _create_cells_sample(height, width)
    elif sample_type == "grid":
        return _create_grid_sample(height, width)
    else:
        return _create_branching_sample(height, width)


def _create_branching_sample(height: int, width: int) -> np.ndarray:
    """Create a branching tree pattern (like blood vessels)."""
    from skimage.draw import line

    image = np.ones((height, width), dtype=np.float32)

    def draw_vessel(start: Tuple[int, int], end: Tuple[int, int], img: np.ndarray) -> None:
        try:
            rr, cc = line(start[0], start[1], end[0], end[1])
            # Clip to valid indices
            valid = (rr >= 0) & (rr < height) & (cc >= 0) & (cc < width)
            img[rr[valid], cc[valid]] = 0
        except Exception:
            pass

    def draw_tree(
        start: Tuple[int, int],
        angle: float,
        length: float,
        depth: int,
        img: np.ndarray,
        reducer: float,
        max_angle: float = 40.0,
    ) -> None:
        if depth == 0:
            return
        end = (
            int(start[0] + length * np.sin(np.radians(angle))),
            int(start[1] + length * np.cos(np.radians(angle))),
        )
        draw_vessel(start, end, img)
        angle += np.random.uniform(-10, 10)
        new_length = length * reducer
        new_depth = depth - 1
        draw_tree(
            end,
            angle - max_angle * np.random.uniform(-1, 1),
            new_length,
            new_depth,
            img,
            reducer,
        )
        draw_tree(
            end,
            angle + max_angle * np.random.uniform(-1, 1),
            new_length,
            new_depth,
            img,
            reducer,
        )

    start_point = (height - 1, width // 2)
    initial_angle = -90
    initial_length = max(width, height) * 0.15
    depth = 5
    reducer = 0.85

    draw_tree(start_point, initial_angle, initial_length, depth, image, reducer)

    # Normalize
    return 1.0 - image  # Invert so vessels are bright


def _create_cells_sample(height: int, width: int) -> np.ndarray:
    """Create a random cells pattern."""
    image = np.zeros((height, width), dtype=np.float32)

    y, x = np.ogrid[:height, :width]

    num_cells = np.random.randint(10, 30)
    for _ in range(num_cells):
        cx = np.random.randint(20, width - 20)
        cy = np.random.randint(20, height - 20)
        radius = np.random.randint(5, 30)
        intensity = np.random.uniform(0.5, 1.0)

        dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        cell = np.exp(-(dist**2) / (2 * radius**2)) * intensity
        image += cell

    # Normalize
    if image.max() > 0:
        image = image / image.max()
    return image


def _create_grid_sample(height: int, width: int) -> np.ndarray:
    """Create a grid pattern (like a calibration target)."""
    image = np.zeros((height, width), dtype=np.float32)

    spacing = min(height, width) // 10
    line_width = max(1, spacing // 10)

    # Horizontal lines
    for y in range(0, height, spacing):
        y_start = max(0, y - line_width // 2)
        y_end = min(height, y + line_width // 2 + 1)
        image[y_start:y_end, :] = 1.0

    # Vertical lines
    for x in range(0, width, spacing):
        x_start = max(0, x - line_width // 2)
        x_end = min(width, x + line_width // 2 + 1)
        image[:, x_start:x_end] = 1.0

    return image


#: How much an image blurs per micrometre of defocus (Gaussian sigma, in pixels).
DEFOCUS_BLUR_PER_UM = 0.5


def apply_defocus(
    image: np.ndarray,
    z: float,
    blur_per_um: float = DEFOCUS_BLUR_PER_UM,
) -> np.ndarray:
    """Blur an image as a focal plane `z` micrometres off focus shows it.

    A Gaussian blur growing linearly with ``|z|``, sharp only at ``z == 0``. The image is
    reflected at its border (no dark rim from zero padding, which a focus metric would
    mistake for sharpness).

    Args:
        image: Input image.
        z: Distance from the focal plane in micrometres.
        blur_per_um: Gaussian sigma (pixels) per micrometre.

    Returns:
        The blurred image.
    """
    sigma = abs(z) * blur_per_um
    if sigma < 1e-6:
        return image.astype(np.float32)
    return gaussian_filter(image.astype(np.float32), sigma=sigma, mode="reflect")


def shift_image(
    image: np.ndarray,
    x_offset: float,
    y_offset: float,
) -> np.ndarray:
    """
    Shift an image by the given offsets using roll.

    Args:
        image: Input image.
        x_offset: X offset in pixels.
        y_offset: Y offset in pixels.

    Returns:
        Shifted image.
    """
    shifted = np.roll(image, int(x_offset), axis=1)
    shifted = np.roll(shifted, int(y_offset), axis=0)
    return shifted


def zoom_in(
    image: np.ndarray,
    zoom_factor: float,
) -> np.ndarray:
    """
    Shift an image by the given offsets using roll.

    Args:
        image: Input image.
        x_offset: X offset in pixels.
        y_offset: Y offset in pixels.

    Returns:
        Shifted image.
    """
    zoomed = zoom(image, zoom_factor, order=1)
    return zoomed


def extract_roi(
    image: np.ndarray,
    height: int,
    width: int,
) -> np.ndarray:
    """
    Extract a centered region of interest from an image.

    Args:
        image: Input image.
        height: ROI height.
        width: ROI width.

    Returns:
        Extracted ROI.
    """
    img_h, img_w = image.shape[:2]

    # Calculate center crop
    start_y = (img_h - height) // 2
    start_x = (img_w - width) // 2

    # Handle case where requested size is larger than image
    if start_y < 0 or start_x < 0:
        # Pad the image
        pad_y = max(0, -start_y)
        pad_x = max(0, -start_x)
        image = np.pad(image, ((pad_y, pad_y), (pad_x, pad_x)), mode="constant")
        start_y = max(0, start_y)
        start_x = max(0, start_x)

    return image[start_y : start_y + height, start_x : start_x + width]


#: Counts per second a fully lit, fully bright sample pixel collects at unity gain: a
#: 25 ms exposure at full power peaks around 50000 of the 16-bit range, so the live view
#: (8 bits: counts / 256) shows the sample at the default settings; longer exposures
#: saturate, as on a real camera.
SIGNAL_RATE = 2e6


def scale_intensity(
    frame: np.ndarray,
    light_intensity: float,
    exposure_time: float,
    gain: float,
) -> np.ndarray:
    """Turn a sample (0..1) into the counts a camera collects of it.

    Args:
        frame: The sample, 0 (dark) .. 1 (bright).
        light_intensity: How much light reaches it: 1 is one source at full power.
        exposure_time: Exposure time in seconds.
        gain: Camera gain.

    Returns:
        The frame in counts, before noise.
    """
    # Photons collected: light x exposure x the camera's signal rate
    frame = frame * light_intensity * exposure_time * SIGNAL_RATE

    # Apply gain (multiplicative)
    frame = frame * (1.0 + gain / 10.0)

    return frame.astype(np.float32)
