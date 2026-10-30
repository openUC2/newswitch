"""Estimation and validation of the 3D affine matrix mapping pixel to stage coordinates."""

from dataclasses import dataclass
from typing import List

import numpy as np
from pystackreg import StackReg
from scipy import ndimage

from newswitch.models.devices import Detector, ObjectiveLens
from newswitch.states.stage import StageState


@dataclass
class AffineMatrix:
    """A fitted 4x4 pixel-to-stage affine matrix together with its least-squares fit quality."""

    matrix: np.ndarray
    residuals: np.ndarray
    rank: int
    singular_values: np.ndarray


def calculate_3d_affine(
    images: List[np.ndarray], stage_positions: List[StageState]
) -> AffineMatrix:
    """
    Calculates the 4x4 3D affine matrix mapping [x, y, z, 1] pixel coordinates
    to [X, Y, Z, 1] stage microns.

    :param images: List of numpy arrays (2D images).
    :param stage_positions: List of StageTest dataclass objects.
    :return: 4x4 Affine Matrix.
    """
    if len(images) != len(stage_positions):
        raise ValueError("Image list and stage position list must be the same length.")

    sr = StackReg(StackReg.TRANSLATION)

    # We define the first image as the origin in 'Voxel Space'
    voxel_coords = [[0.0, 0.0, 0.0]]
    # We take the absolute 'World Space' coordinates directly
    world_coords = [[p.x, p.y, p.z] for p in stage_positions]

    current_px_x = 0.0
    current_px_y = 0.0

    # Calculate relative pixel shifts and accumulate them
    for i in range(len(images) - 1):
        # Register images[i+1] relative to images[i]
        tmat = sr.register(images[i], images[i + 1])

        # tmat[0, 2] is shift in x, tmat[1, 2] is shift in y
        current_px_x += tmat[0, 2]
        current_px_y += tmat[1, 2]

        # We assume each image in the list represents one 'step' in the Z-stack
        current_px_z = float(i + 1)

        voxel_coords.append([current_px_x, current_px_y, current_px_z])

    # Convert to Homogeneous coordinates by adding a column of ones
    # V: Voxel/Pixel Matrix (N x 4)
    # W: World/Stage Matrix (N x 4)
    V = np.hstack([np.array(voxel_coords), np.ones((len(voxel_coords), 1))])
    W = np.hstack([np.array(world_coords), np.ones((len(world_coords), 1))])

    # Solve the linear system: W = V @ M.T
    # This finds the matrix M that best maps V to W in a least-squares sense.
    affine_matrix_T, residuals, rank, singular_values = np.linalg.lstsq(V, W, rcond=None)
    affine_matrix = affine_matrix_T.T

    return AffineMatrix(
        matrix=affine_matrix, residuals=residuals, rank=int(rank), singular_values=singular_values
    )


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


@dataclass
class CalibrationMetrics:
    """Strongly typed container for all physical validation metrics."""

    mag_deviation_pct: float
    aspect_ratio: float
    ortho_error_deg: float
    determinant_sign: float
    mean_squared_error: float
    z_scaling_um: float


@dataclass
class ValidationResult:
    """Outcome of the calibration sanity checks run against a fitted affine matrix."""

    is_valid: bool
    summary: str
    metrics: CalibrationMetrics
    warnings: List[str]


def check_calibration(
    affine_matrix: AffineMatrix,
    objective: ObjectiveLens,
    detector: Detector,
    tolerance_pct: float = 15.0,
) -> ValidationResult:
    """
    Runs a battery of tests to verify the integrity of the 3D affine matrix
    and returns a typed ValidationResult.
    """
    # 1. Vector Extraction
    # Columns of the matrix are the basis vectors (microns per unit pixel)
    vec_x = affine_matrix.matrix[:3, 0]
    vec_y = affine_matrix.matrix[:3, 1]
    vec_z = affine_matrix.matrix[:3, 2]

    # 2. Magnification Check
    # Area scaling in XY
    measured_px_size = np.sqrt(np.abs(np.linalg.det(affine_matrix.matrix[:2, :2])))
    theoretical_px_size = detector.pixel_size_um / objective.magnification
    mag_error = abs(measured_px_size - theoretical_px_size) / theoretical_px_size * 100

    # 3. Aspect Ratio (X scale vs Y scale)
    scale_x, scale_y = np.linalg.norm(vec_x[:2]), np.linalg.norm(vec_y[:2])
    aspect_ratio = scale_x / scale_y

    # 4. Orthogonality (Shear)
    dot_prod = np.dot(vec_x[:2], vec_y[:2])
    cos_theta = dot_prod / (scale_x * scale_y)
    ortho_error = abs(90 - np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0))))

    # 5. Statistical & Handedness
    det_sign = np.sign(np.linalg.det(affine_matrix.matrix[:2, :2]))
    mse = np.mean(affine_matrix.residuals) if affine_matrix.residuals.size > 0 else 0.0
    z_scale = np.linalg.norm(vec_z)

    # --- Validation Logic ---
    warnings: list[str] = []
    pass_mag = mag_error <= tolerance_pct
    if not pass_mag:
        warnings.append(f"Mag mismatch: {mag_error:.1f}% deviation")

    pass_aspect = 0.95 <= aspect_ratio <= 1.05
    if not pass_aspect:
        warnings.append(f"Non-square pixels: aspect ratio {aspect_ratio:.3f}")

    pass_ortho = ortho_error < 2.0
    if not pass_ortho:
        warnings.append(f"Axes skew detected: {ortho_error:.2f}° from 90°")

    pass_mse = mse < 1.0
    if not pass_mse:
        warnings.append(f"High fit error: MSE {mse:.4f}")

    # Build typed metrics object
    metrics = CalibrationMetrics(
        mag_deviation_pct=mag_error,
        aspect_ratio=aspect_ratio,
        ortho_error_deg=ortho_error,
        determinant_sign=det_sign,
        mean_squared_error=mse,
        z_scaling_um=z_scale,
    )

    overall_pass = all([pass_mag, pass_aspect, pass_ortho, pass_mse])
    status_msg = "✅ CALIBRATION VALID" if overall_pass else "❌ CALIBRATION INVALID"

    return ValidationResult(
        is_valid=overall_pass, summary=status_msg, metrics=metrics, warnings=warnings
    )
