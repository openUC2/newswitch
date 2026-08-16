"""
Virtual Setup

The simulated optical scene behind the virtual microscope: sample generation,
stage-driven navigation, objective magnification, illumination and spectral
filtering.

This is deliberately *not* a manager. It owns no device, implements no protocol
and is never injected by the agent - it is the simulation collaborator that
``VirtualDetectorManager`` asks for pixels. Keeping it separate is what allows the
detector managers to depend on ``CameraState`` alone, exactly like a real hardware
detector manager does.
"""

import math
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
from rekuest_next import model

from newswitch.managers.helpers.frame import (
    add_noise,
    apply_psf_convolution,
    create_sample_image,
    extract_roi,
    render_astigmatic_psf,
    scale_intensity,
    shift_image,
    zoom_in,
)
from newswitch.protocols.filter_bank import FilterBankState
from newswitch.protocols.illumination import IlluminationState
from newswitch.protocols.objective import ObjectiveState
from newswitch.protocols.stage import StageState

SampleType = Literal["branching", "cells", "grid", "astigmatism"]


@dataclass(frozen=True)
class SampleFrameCacheKey:
    """Cache key for sample frame generation (before intensity/noise)."""

    stage_x: float
    stage_y: float
    stage_z: float
    magnification: float
    width: int
    height: int


@dataclass(frozen=True)
class AstigmatismFrameCacheKey:
    """Cache key for astigmatism frame generation (before intensity/noise)."""

    stage_x: float
    stage_y: float
    stage_z: float
    width: int
    height: int


@dataclass(frozen=True)
class IlluminationCacheKey:
    """Cache key for illumination calculation."""

    active_sources: tuple[tuple[int, float, float], ...]  # (slot, intensity, wavelength) tuples
    active_filter_slot: int  # Current filter slot


@dataclass
class FrameCache:
    """Cache for expensive frame generation operations."""

    # Sample frame cache (before intensity scaling and noise)
    sample_frame_key: Optional[SampleFrameCacheKey] = None
    sample_frame: Optional[np.ndarray] = None

    # Astigmatism frame cache (before intensity scaling and noise)
    astigmatism_frame_key: Optional[AstigmatismFrameCacheKey] = None
    astigmatism_frame: Optional[np.ndarray] = None

    # PSF cache for defocus
    psf_z: Optional[float] = None
    psf: Optional[np.ndarray] = None

    # Illumination value cache
    illumination_key: Optional[IlluminationCacheKey] = None
    illumination_value: Optional[float] = None


@model
@dataclass
class SceneConfig:
    """Configuration for the simulated optical scene."""

    # Noise parameters
    read_noise: float = 2.2
    poisson_noise: bool = True
    # Sample parameters
    sample_type: SampleType = "cells"
    sample_width: int = 2000  # Full sample size (larger than sensor)
    sample_height: int = 2000
    sample_seed: int = 42
    # Astigmatism parameters (for astigmatism mode)
    astig_phi_deg: float = 33.0
    astig_s0: float = 1.7
    astig_slope: float = 0.33
    astig_amplitude: float = 2400.0
    astig_background: float = 35.0


class VirtualSetup:
    """
    The simulated optical scene shared by every virtual detector.

    Renders frames from the current microscope state:
    - Stage position-based sample navigation
    - Objective magnification-based zoom
    - Illumination intensity (spectrally filtered) based brightness
    - Optional PSF convolution for defocus simulation
    - Realistic noise models (Poisson + read noise)

    The injected states are read at *render* time only, never during
    construction, so this object may be built at any point after the states
    exist - its position relative to the other virtual managers is irrelevant.
    """

    def __init__(
        self,
        stage_state: StageState,
        objective_state: ObjectiveState,
        illumination_state: IlluminationState,
        filter_bank_state: Optional[FilterBankState] = None,
        config: Optional[SceneConfig] = None,
    ) -> None:
        """
        Initialize the virtual scene.

        Args:
            stage_state: Shared state for stage position (affects frame content).
            objective_state: Shared state for the objective (affects zoom).
            illumination_state: Shared state for illumination (affects brightness).
            filter_bank_state: Shared state for filter bank (affects spectral filtering).
            config: Scene configuration. Uses defaults if not provided.
        """
        self.stage_state = stage_state
        self.objective_state = objective_state
        self.illumination_state = illumination_state
        self.filter_bank_state = filter_bank_state
        self.config = config or SceneConfig()

        # Random number generator for reproducible noise
        self._rng = np.random.default_rng(self.config.sample_seed)

        # Pre-generate the sample image (if not astigmatism mode)
        self._sample_image: Optional[np.ndarray] = None
        if self.config.sample_type != "astigmatism":
            self._sample_image = create_sample_image(
                self.config.sample_height,
                self.config.sample_width,
                self.config.sample_type,
                self.config.sample_seed,
            )

        # Initialize frame cache
        self._cache = FrameCache()

    def render(self, width: int, height: int, exposure_time: float, gain: float) -> np.ndarray:
        """
        Render the current scene at the requested sensor size.

        Args:
            width: Sensor width in pixels.
            height: Sensor height in pixels.
            exposure_time: Exposure time in seconds.
            gain: Detector gain.

        Returns:
            The rendered frame as a uint16 array of shape (height, width).
        """
        if self.config.sample_type == "astigmatism":
            return self._render_astigmatism(width, height, exposure_time, gain)
        else:
            return self._render_sample(width, height, exposure_time, gain)

    def clear_cache(self) -> None:
        """Clear all cached frame data.

        Call this method to force recalculation of all cached values.
        Useful when external state changes that the cache doesn't track.
        """
        self._cache = FrameCache()

    def invalidate_illumination_cache(self) -> None:
        """Invalidate the illumination cache.

        Call this when illumination state changes externally.
        """
        self._cache.illumination_key = None
        self._cache.illumination_value = None

    def _expose(self, base_frame: np.ndarray, exposure_time: float, gain: float) -> np.ndarray:
        """Apply illumination, exposure, gain and noise to a rendered base frame.

        Always recalculated - the base frame is cacheable, this part is not
        (gain/exposure change per detector and the noise must stay random).
        """
        frame = scale_intensity(
            base_frame,
            light_intensity=max(0.1, self._get_cached_illumination_value() / 1000.0),
            exposure_time=exposure_time,
            gain=gain,
        )

        frame = add_noise(
            frame,
            read_noise=self.config.read_noise,
            poisson=self.config.poisson_noise,
            rng=self._rng,
        )

        # Convert to uint16
        frame = np.clip(frame, 0, 65535)
        return frame.astype(np.uint16)

    def _render_astigmatism(
        self, width: int, height: int, exposure_time: float, gain: float
    ) -> np.ndarray:
        """Render a frame with astigmatic PSF (for autofocus testing)."""
        # Create cache key for current state
        cache_key = AstigmatismFrameCacheKey(
            stage_x=self.stage_state.x,
            stage_y=self.stage_state.y,
            stage_z=self.stage_state.z,
            width=width,
            height=height,
        )

        # Check cache
        if (
            self._cache.astigmatism_frame_key == cache_key
            and self._cache.astigmatism_frame is not None
        ):
            base_frame = self._cache.astigmatism_frame.copy()
        else:
            # Render PSF based on Z position
            base_frame = render_astigmatic_psf(
                height=height,
                width=width,
                z_offset=self.stage_state.z,
                phi_deg=self.config.astig_phi_deg,
                s0=self.config.astig_s0,
                astig_slope=self.config.astig_slope,
                amplitude=self.config.astig_amplitude,
                background=self.config.astig_background,
                x_offset=self.stage_state.x * 0.01,  # Scale stage to pixels
                y_offset=self.stage_state.y * 0.01,
            )
            # Cache the base frame
            self._cache.astigmatism_frame_key = cache_key
            self._cache.astigmatism_frame = base_frame.copy()

        return self._expose(base_frame, exposure_time, gain)

    def _render_sample(
        self, width: int, height: int, exposure_time: float, gain: float
    ) -> np.ndarray:
        """Render a frame from the sample image based on stage position."""
        if self._sample_image is None:
            # Fallback: create on demand
            self._sample_image = create_sample_image(
                self.config.sample_height,
                self.config.sample_width,
                self.config.sample_type,
                self.config.sample_seed,
            )

        # Create cache key for current state
        cache_key = SampleFrameCacheKey(
            stage_x=self.stage_state.x,
            stage_y=self.stage_state.y,
            stage_z=self.stage_state.z,
            magnification=self.objective_state.magnification,
            width=width,
            height=height,
        )

        # Check cache for base frame (before intensity scaling and noise)
        if self._cache.sample_frame_key == cache_key and self._cache.sample_frame is not None:
            base_frame = self._cache.sample_frame.copy()
        else:
            # Shift sample based on stage position
            shifted = shift_image(
                self._sample_image,
                x_offset=self.stage_state.x * 10,  # Scale stage units to pixels
                y_offset=self.stage_state.y * 10,
            )

            scaled = zoom_in(
                shifted,
                zoom_factor=self.objective_state.magnification
                / 10.0,  # Placeholder scaling based on magnification
            )

            # Extract ROI at sensor size
            base_frame = extract_roi(
                scaled,
                height,
                width,
            )

            # Optional: Apply PSF convolution for defocus
            if abs(self.stage_state.z) > 0.1:
                # Check PSF cache
                if self._cache.psf_z != self.stage_state.z or self._cache.psf is None:
                    psf_size = 15
                    sigma = 1.0 + abs(self.stage_state.z) * 0.1
                    y, x = np.ogrid[
                        -psf_size // 2 : psf_size // 2 + 1, -psf_size // 2 : psf_size // 2 + 1
                    ]
                    self._cache.psf = np.exp(-(x**2 + y**2) / (2 * sigma**2))
                    self._cache.psf_z = self.stage_state.z

                base_frame = apply_psf_convolution(base_frame, self._cache.psf)

            # Cache the base frame
            self._cache.sample_frame_key = cache_key
            self._cache.sample_frame = base_frame.copy()

        return self._expose(base_frame, exposure_time, gain)

    def _get_illumination_cache_key(self) -> IlluminationCacheKey:
        """Build cache key for current illumination state."""
        active_sources = tuple(
            (src.slot, src.intensity, src.wavelength)
            for src in self.illumination_state.illuminations
            if src.is_active
        )
        # Include filter slot in cache key
        active_filter_slot = 0
        if self.filter_bank_state is not None:
            active_filter_slot = self.filter_bank_state.current_slot
        return IlluminationCacheKey(
            active_sources=active_sources, active_filter_slot=active_filter_slot
        )

    def _get_filter_transmission(self, wavelength: float) -> float:
        """Get filter transmission for a given wavelength.

        Args:
            wavelength: Wavelength in nm.

        Returns:
            Transmission factor (0.0 to 1.0).
        """
        if self.filter_bank_state is None:
            return 1.0  # No filter bank means full transmission

        # Find active filter
        active_filter = None
        for f in self.filter_bank_state.filters:
            if f.is_active:
                active_filter = f
                break

        if active_filter is None:
            return 1.0

        # Open filter (no filtering)
        if active_filter.center_wavelength == 0.0:
            return active_filter.transmission

        # Calculate Gaussian transmission profile
        if active_filter.bandwidth <= 0:
            if abs(wavelength - active_filter.center_wavelength) < 1.0:
                return active_filter.transmission
            return 0.0

        sigma = active_filter.bandwidth / (2.0 * math.sqrt(2.0 * math.log(2.0)))
        delta = wavelength - active_filter.center_wavelength
        gaussian = math.exp(-(delta**2) / (2.0 * sigma**2))

        return active_filter.transmission * gaussian

    def _get_cached_illumination_value(self) -> float:
        """Get cached illumination value, recalculating only if state changed.

        Takes into account the filter transmission for each illumination source.
        """
        cache_key = self._get_illumination_cache_key()

        if self._cache.illumination_key == cache_key and self._cache.illumination_value is not None:
            return self._cache.illumination_value

        # Calculate total illumination with filter transmission
        total = 0.0
        for src in self.illumination_state.illuminations:
            if src.is_active:
                transmission = self._get_filter_transmission(src.wavelength)
                total += src.intensity * transmission

        self._cache.illumination_key = cache_key
        self._cache.illumination_value = total
        return total

    def calculate_illumination_value(self) -> float:
        """Calculate illumination value based on current settings."""
        return self._get_cached_illumination_value()
