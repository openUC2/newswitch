"""
Virtual Detector Manager

A virtual camera/detector manager for microscopy simulation.
Provides synchronized image capture without background threads.
"""

from dataclasses import dataclass
from typing import Literal, Optional
import koil
import numpy as np
from rekuest_next import model

from newswitch.managers.helpers.frame import (
    create_sample_image,
    shift_image,
    extract_roi,
    render_astigmatic_psf,
    apply_psf_convolution,
    scale_intensity,
    add_noise,
    zoom_in,
)
from newswitch.protocols.detector import CameraState, Detector
from newswitch.protocols.illumination import IlluminationState
from newswitch.protocols.objective import ObjectiveState
from newswitch.protocols.stage import StageState
from newswitch.protocols.filter_bank import FilterBankState
from newswitch.broadcasters import FrameBroadcaster


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
class DetectorConfig:
    """Configuration for the virtual detector."""

    width: int = 512
    height: int = 512
    min_exposure: float = 0.001  # seconds
    max_exposure: float = 10.0  # seconds
    default_exposure: float = 0.1  # seconds
    min_gain: float = 0.0
    max_gain: float = 100.0
    default_gain: float = 1.0
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


class VirtualDetectorManager:
    """
    A virtual detector/camera manager for microscopy simulation.

    Provides sync image capture operations. All methods are synchronous
    and will be run in a threadpool via registered functions.

    The detector uses injected state objects for camera, stage, and illumination
    to generate realistic microscopy frames with:
    - Stage position-based sample navigation
    - Illumination intensity-based brightness
    - Optional PSF convolution for defocus simulation
    - Realistic noise models (Poisson + read noise)
    """

    state: CameraState

    def __init__(
        self,
        camera_state: CameraState,
        stage_state: StageState,
        objective_state: ObjectiveState,
        illumination_state: IlluminationState,
        broadcaster: FrameBroadcaster,
        config: Optional[DetectorConfig] = None,
        filter_bank_state: Optional[FilterBankState] = None,
        detectors: Optional[list[Detector]] = None,
    ) -> None:
        """
        Initialize the virtual detector manager.

        Args:
            camera_state: Shared state for camera parameters.
            stage_state: Shared state for stage position (affects frame content).
            illumination_state: Shared state for illumination (affects brightness).
            broadcaster: Frame broadcaster for video streaming.
            config: Detector configuration. Uses defaults if not provided.
            filter_bank_state: Shared state for filter bank (affects spectral filtering).
            detectors: Detectors to expose (e.g. from newswitch-config.yaml). Uses the
                built-in R/G/B channels if not provided.
        """
        self.state = camera_state
        self.stage_state = stage_state
        self.objective_state = objective_state
        self.illumination_state = illumination_state
        self.filter_bank_state = filter_bank_state
        self.broadcaster = broadcaster
        self.config = config or DetectorConfig()

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

        # Initialize detectors
        self._initialize_detectors(detectors)

    def _initialize_detectors(self, detectors: Optional[list[Detector]] = None) -> None:
        """Initialize the list of detectors, falling back to the built-in virtual ones."""
        if detectors is not None:
            self.state.detectors = list(detectors)
            return
        # Create default virtual detectors
        self.state.detectors = [
            Detector(
                slot=1,
                name="R Channel",
                width=1024,
                height=1024,
                is_active=True,
                current_exposure_time=self.config.default_exposure,
                current_gain=self.config.default_gain,
                pixel_size_um=6.5,
                preset_exposure_times=[0.01, 0.1, 0.5, 1.0, 2.0, 5.0],
                max_exposure_time=self.config.max_exposure,
                min_exposure_time=self.config.min_exposure,
                max_gain=self.config.max_gain,
                min_gain=self.config.min_gain,
            ),
            Detector(
                slot=2,
                name="G Channel",
                width=1024,
                height=1024,
                is_active=True,
                current_exposure_time=10.0,
                current_gain=self.config.default_gain,
                pixel_size_um=6.5,
                preset_exposure_times=[0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0],
                max_exposure_time=self.config.max_exposure,
                min_exposure_time=self.config.min_exposure,
                max_gain=self.config.max_gain,
                min_gain=self.config.min_gain,
            ),
            Detector(
                slot=3,
                name="B Channel",
                width=1024,
                height=1024,
                is_active=True,
                current_exposure_time=10.0,
                current_gain=self.config.default_gain,
                pixel_size_um=6.5,
                preset_exposure_times=[0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0],
                max_exposure_time=self.config.max_exposure,
                min_exposure_time=self.config.min_exposure,
                max_gain=self.config.max_gain,
                min_gain=self.config.min_gain,
            ),
        ]

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

    def _get_detector(self, slot: int) -> Optional[Detector]:
        """Get a detector by its slot number."""
        for detector in self.state.detectors:
            if detector.slot == slot:
                return detector
        return None

    def _get_active_detector(self, slot: int | None = None) -> Optional[Detector]:
        """Get an active detector by slot or take the first active detector."""
        for detector in self.state.detectors:
            if detector.is_active and (slot is None or detector.slot == slot):
                return detector
        return None

    def _get_active_detectors(self) -> list[Detector]:
        """Get all active detectors."""
        return [d for d in self.state.detectors if d.is_active]

    def _generate_frame(self, detector: Detector) -> np.ndarray:
        """
        Generate a simulated microscopy frame.

        Uses current state from stage, illumination, and camera to produce
        a realistic frame with PSF convolution and noise.

        Args:
            detector: The detector with exposure and gain settings.
        """
        if self.config.sample_type == "astigmatism":
            return self._generate_astigmatism_frame(detector)
        else:
            return self._generate_sample_frame(detector)

    def _generate_astigmatism_frame(self, detector: Detector) -> np.ndarray:
        """Generate a frame with astigmatic PSF (for autofocus testing)."""
        # Create cache key for current state
        cache_key = AstigmatismFrameCacheKey(
            stage_x=self.stage_state.x,
            stage_y=self.stage_state.y,
            stage_z=self.stage_state.z,
            width=self.config.width,
            height=self.config.height,
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
                height=self.config.height,
                width=self.config.width,
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

        # Scale by illumination and camera settings (must always recalculate)
        frame = scale_intensity(
            base_frame,
            light_intensity=max(0.1, self._get_cached_illumination_value() / 1000.0),
            exposure_time=detector.current_exposure_time,
            gain=detector.current_gain,
        )

        # Add noise (must always recalculate for randomness)
        frame = add_noise(
            frame,
            read_noise=self.config.read_noise,
            poisson=self.config.poisson_noise,
            rng=self._rng,
        )

        # Convert to uint16
        frame = np.clip(frame, 0, 65535)
        return frame.astype(np.uint16)

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
        import math

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

    def _generate_sample_frame(self, detector: Detector) -> np.ndarray:
        """Generate a frame from the sample image based on stage position."""
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
            width=self.config.width,
            height=self.config.height,
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
                self.config.height,
                self.config.width,
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

        # Scale by illumination and camera settings (must always recalculate)
        frame = scale_intensity(
            base_frame,
            light_intensity=max(0.1, self._get_cached_illumination_value() / 1000.0),
            exposure_time=detector.current_exposure_time,
            gain=detector.current_gain,
        )

        # Add noise (must always recalculate for randomness)
        frame = add_noise(
            frame,
            read_noise=self.config.read_noise,
            poisson=self.config.poisson_noise,
            rng=self._rng,
        )

        # Convert to uint16
        frame = np.clip(frame, 0, 65535)
        return frame.astype(np.uint16)

    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp a value to a range."""
        return max(min_val, min(value, max_val))

    def activate_detector(self, slot: int, raise_on_active: bool = False) -> Detector:
        """
        Activate a detector by its slot number.

        Args:
            slot: Detector slot number from detectors.

        Returns:
            The activated detector.

        Raises:
            ValueError: If the detector slot is not found or already active.
        """
        detector = self._get_detector(slot)
        if detector is None:
            raise ValueError(f"No detector found with slot {slot}")

        if detector.is_active and raise_on_active:
            raise ValueError(f"Detector with slot {slot} is already active")

        detector.is_active = True
        return detector

    def deactivate_detector(self, slot: int) -> None:
        """
        Deactivate a detector by its slot number.

        Args:
            slot: Detector slot number to deactivate.

        Raises:
            ValueError: If the detector slot is not found.
        """
        detector = self._get_detector(slot)
        if detector is None:
            raise ValueError(f"No detector found with slot {slot}")

        detector.is_active = False

    def update_detector(
        self, slot: int, exposure_time: Optional[float] = None, gain: Optional[float] = None
    ) -> Detector:
        """
        Update detector settings.

        Args:
            slot: Detector slot number.
            exposure_time: New exposure time in seconds (if provided).
            gain: New gain value (if provided).

        Returns:
            The updated detector.

        Raises:
            ValueError: If the detector slot is not found.
        """
        detector = self._get_detector(slot)
        if detector is None:
            raise ValueError(f"No detector found with slot {slot}")

        if exposure_time is not None:
            clamped = self._clamp(
                exposure_time, detector.min_exposure_time, detector.max_exposure_time
            )
            detector.current_exposure_time = clamped

        if gain is not None:
            clamped = self._clamp(gain, detector.min_gain, detector.max_gain)
            detector.current_gain = clamped

        return detector

    def get_detector_state(self, slot: int) -> Optional[Detector]:
        """
        Get the state of a detector.

        Args:
            slot: Detector slot number.

        Returns:
            The detector if found, None otherwise.
        """
        return self._get_detector(slot)

    def list_available_detectors(self) -> list[Detector]:
        """
        List all available detectors.

        Returns:
            List of detector configurations.
        """
        return self.state.detectors

    def list_active_detectors(self) -> list[Detector]:
        """
        List all active detectors.

        Returns:
            List of active detectors.
        """
        return self._get_active_detectors()

    def capture_image(self, slot: int | None = None) -> np.ndarray:
        """
        Capture a single image from a specific detector.

        Args:
            slot: Detector slot number.

        Returns:
            Captured frame as numpy array.

        Raises:
            ValueError: If the detector slot is not active.
        """
        detector = self._get_active_detector(slot)
        if detector is None:
            raise ValueError(f"No active detector found with slot {slot}")

        frame = self._generate_frame(detector)
        return frame

    def _compose_rgb_frame(self) -> np.ndarray:
        """
        Compose an RGB frame from all active detectors based on their colormaps.

        Returns:
            RGB frame as numpy array with shape (height, width, 3) and dtype uint8.
        """
        from newswitch.protocols.detector import Colormap

        active_detectors = self._get_active_detectors()
        if not active_detectors:
            # Return a black frame if no detectors are active
            return np.zeros((self.config.height, self.config.width, 3), dtype=np.uint8)

        # Initialize RGB channels
        r_channel = np.zeros((self.config.height, self.config.width), dtype=np.float64)
        g_channel = np.zeros((self.config.height, self.config.width), dtype=np.float64)
        b_channel = np.zeros((self.config.height, self.config.width), dtype=np.float64)

        for detector in active_detectors:
            # Generate frame for this detector
            frame = self._generate_frame(detector)

            # Normalize to 0-1 range
            frame_float = frame.astype(np.float64)
            if frame_float.max() > frame_float.min():
                frame_normalized = (frame_float - frame_float.min()) / (
                    frame_float.max() - frame_float.min()
                )
            else:
                frame_normalized = np.zeros_like(frame_float)

            # Resize if needed to match config dimensions
            if frame_normalized.shape != (self.config.height, self.config.width):
                # Simple resize by cropping or padding
                h, w = frame_normalized.shape
                target_h, target_w = self.config.height, self.config.width
                resized = np.zeros((target_h, target_w), dtype=np.float64)
                copy_h = min(h, target_h)
                copy_w = min(w, target_w)
                resized[:copy_h, :copy_w] = frame_normalized[:copy_h, :copy_w]
                frame_normalized = resized

            # Add to appropriate channel based on colormap
            if detector.current_colormap == Colormap.RED:
                r_channel += frame_normalized
            elif detector.current_colormap == Colormap.GREEN:
                g_channel += frame_normalized
            elif detector.current_colormap == Colormap.BLUE:
                b_channel += frame_normalized

        # Normalize and clip each channel
        def normalize_channel(channel: np.ndarray) -> np.ndarray:
            if channel.max() > 0:
                channel = channel / channel.max()
            return np.clip(channel * 255, 0, 255).astype(np.uint8)

        r_uint8 = normalize_channel(r_channel)
        g_uint8 = normalize_channel(g_channel)
        b_uint8 = normalize_channel(b_channel)

        # Stack into RGB image
        rgb_frame = np.stack([r_uint8, g_uint8, b_uint8], axis=-1)
        return rgb_frame

    def acquire_live(self) -> None:
        """
        Start continuous acquisition mode (protocol method).

        Continuously acquires frames from active detectors and broadcasts
        each detector stream on its own detector slot.
        """
        self.broadcaster.start_broadcasting()

        while True:
            if self.state.is_acquiring is False:
                koil.sleep(1)
            else:
                # Compose RGB frame from all active detectors
                active_detectors = self._get_active_detectors()
                if not active_detectors:
                    koil.sleep(0.1)
                    continue

                for detector in active_detectors:
                    frame = self._generate_frame(detector)

                    self.broadcaster.broadcast_sync(detector.slot, frame)

                    # Use exposure time from first active detector for frame interval

    def background(self) -> None:
        """Background task for the virtual detector manager."""
        # For this simple implementation, we don't need a background loop
        # since all operations are synchronous and triggered by registered functions.
        pass
