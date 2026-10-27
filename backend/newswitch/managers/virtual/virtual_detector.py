"""
Virtual Detector Manager

A virtual camera/detector manager for microscopy simulation.
Provides synchronized image capture without background threads.

Besides exposure and gain it simulates how a camera reads out its sensor: a region of
interest is cut out of the rendered frame, binning averages blocks of pixels, the frame
rate paces the live stream, and every acquisition session (live stream, snapshot outside
of it) numbers its images.
"""

import threading
import time
from dataclasses import dataclass
from typing import Literal, Optional
import koil
import numpy as np
from rekuest_next import model
from rekuest_next.state.lock import acquired_locks

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
from newswitch.protocols.detector import (
    CameraState,
    Detector,
    DetectorFrame,
    DetectorSessionInfo,
    Roi,
    is_full_sensor,
)
from newswitch.protocols.illumination import IlluminationState
from newswitch.protocols.objective import ObjectiveState
from newswitch.protocols.stage import StageState
from newswitch.protocols.filter_bank import FilterBankState
from newswitch.broadcasters import FrameBroadcaster


SampleType = Literal["branching", "cells", "grid", "astigmatism"]

#: Binning factors the virtual detectors offer.
BINNINGS = [1, 2, 4]
#: Frame rates the virtual detectors offer (frames per second).
FRAME_RATE_RANGE = (0.1, 100.0)
#: Longest pause of the live loop (s): while idle, and between two paced images.
IDLE_INTERVAL_S = 0.1
#: Lock that guards the `Detector` state.
CAMERA_LOCK = "camera_parameters"
#: Why ``save_to_disk`` fails here.
NO_DISK_RECORDING = "the virtual detector cannot record to disk"


@dataclass
class Readout:
    """The acquisition session of one virtual detector.

    How the sensor is read out (binning, region, frame rate) is in its `Detector`.
    """

    session: Optional[DetectorSessionInfo] = None
    """Current or last acquisition session; None before the first acquisition."""
    sequence: int = 0
    """Index of the next image within the session."""
    streaming: bool = False
    """The live loop streams this detector (its session is the live session)."""
    next_due_ns: int = 0
    """When the live loop sends the next image (monotonic ns)."""


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

        # Readout and session per detector slot; the lock serializes them with the live loop
        self._readouts: dict[int, Readout] = {}
        self._lock = threading.RLock()
        self._closed = False

        # Initialize detectors
        self._initialize_detectors(detectors)

    def _initialize_detectors(self, detectors: Optional[list[Detector]] = None) -> None:
        """Initialize the list of detectors, falling back to the built-in virtual ones."""
        if detectors is None:
            detectors = self._default_detectors()
        for detector in detectors:
            self._describe(detector)
        self.state.detectors = list(detectors)

    def _default_detectors(self) -> list[Detector]:
        """The built-in R/G/B channels."""
        return [
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

    def _describe(self, detector: Detector) -> None:
        """Fill in what the virtual detector is and can do; keep valid configured values.

        The image size follows the rendered sensor (`DetectorConfig.width`/`height`), the
        region of interest and the binning.
        """
        binning = self._snap_binning(detector.current_binning)
        roi = None if detector.current_roi is None else self._clamp_roi(detector.current_roi)
        width, height = self._image_size(binning, roi)
        frame_rate = detector.current_frame_rate
        with acquired_locks(CAMERA_LOCK):
            detector.manufacturer = "virtual"
            detector.model = "simulated"
            detector.serial_number = f"virtual-{detector.slot}"
            detector.connection_type = None
            detector.device_index = None
            detector.pixel_format = "Mono16"
            detector.data_type = "uint16"
            detector.sensor_width, detector.sensor_height = self.config.width, self.config.height
            detector.pixel_pitch_um = detector.pixel_size_um
            detector.width, detector.height = width, height
            detector.current_binning = binning
            detector.current_roi = roi
            detector.current_frame_rate = (
                None if frame_rate is None else self._clamp(frame_rate, *FRAME_RATE_RANGE)
            )
            detector.min_frame_rate, detector.max_frame_rate = FRAME_RATE_RANGE
            detector.available_binnings = list(BINNINGS)
            detector.can_set_exposure = True
            detector.can_set_gain = True
            detector.can_set_frame_rate = True
            detector.can_set_binning = True
            detector.can_set_roi = True
            detector.is_recording = False
            detector.recording_file = None

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

    def _require_detector(self, slot: int) -> Detector:
        """Get a detector by its slot number.

        Raises:
            ValueError: No detector in this slot.
        """
        detector = self._get_detector(slot)
        if detector is None:
            raise ValueError(f"No detector found with slot {slot}")
        return detector

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

    # ------------------------------------------------------------- readout

    def _readout(self, slot: int) -> Readout:
        """The readout of a detector slot, with the defaults on first use."""
        return self._readouts.setdefault(slot, Readout())

    @staticmethod
    def _snap_binning(binning: int) -> int:
        """The allowed binning factor nearest to `binning`.

        Raises:
            ValueError: A factor < 1.
        """
        if binning < 1:
            raise ValueError(f"binning must be >= 1, got {binning}")
        return min(BINNINGS, key=lambda allowed: abs(allowed - binning))

    def _clamp_roi(self, roi: Roi) -> Optional[list[int]]:
        """Clamp a region to the sensor; None for the complete sensor.

        Raises:
            ValueError: A negative coordinate or size.
        """
        x, y, width, height = (int(value) for value in roi)
        if min(x, y, width, height) < 0:
            raise ValueError(f"invalid region {roi}: negative values")
        if is_full_sensor(roi):
            return None
        sensor_width, sensor_height = self.config.width, self.config.height
        x, y = min(x, sensor_width - 1), min(y, sensor_height - 1)
        clamped = [x, y, min(width, sensor_width - x), min(height, sensor_height - y)]
        return None if clamped == [0, 0, sensor_width, sensor_height] else clamped

    def _image_size(self, binning: int, roi: Optional[Roi]) -> tuple[int, int]:
        """Image (width, height) after cutting out `roi` and binning."""
        width, height = self.config.width, self.config.height
        if roi is not None:
            _, _, width, height = roi
        return width // binning, height // binning

    @staticmethod
    def _read_out(frame: np.ndarray, detector: Detector) -> np.ndarray:
        """Cut the region out of a rendered sensor frame and bin it (block means)."""
        if detector.current_roi is not None:
            x, y, width, height = detector.current_roi
            frame = frame[y : y + height, x : x + width]
        factor = detector.current_binning
        if factor > 1:
            height, width = frame.shape[0] // factor, frame.shape[1] // factor
            blocks = frame[: height * factor, : width * factor].reshape(
                height, factor, width, factor
            )
            frame = blocks.mean(axis=(1, 3))
        return np.ascontiguousarray(frame, dtype=np.uint16)

    def _start_session(self, detector: Detector, readout: Readout) -> None:
        """Begin a new acquisition session of `detector`; its images count from 0 again."""
        width, height = self._image_size(detector.current_binning, detector.current_roi)
        readout.session = DetectorSessionInfo(
            detector_id=f"virtual-{detector.slot}",
            width=width,
            height=height,
            channels=1,
            dtype="uint16",
            frame_bytes=width * height * 2,
            slot_count=1,
            start_wall_ns=time.time_ns(),
            start_mono_ns=time.monotonic_ns(),
            settings={
                "exposure_time_ms": detector.current_exposure_time * 1000.0,
                "gain_db": detector.current_gain,
                "frame_rate_per_sec": detector.current_frame_rate,
                "binning": detector.current_binning,
                "roi": detector.current_roi,
            },
            recording_file=None,
        )
        readout.sequence = 0

    def _next_frame(self, detector: Detector, readout: Readout) -> DetectorFrame:
        """Render the next image of the detector's current session."""
        data = self._read_out(self._generate_frame(detector), detector)
        time_ns = time.monotonic_ns()
        sequence = readout.sequence
        readout.sequence += 1
        session = readout.session
        return DetectorFrame(
            slot=detector.slot,
            data=data,
            sequence=sequence,
            time_ns=time_ns,
            wall_time_ns=None if session is None else session.wall_time_ns(time_ns),
        )

    def _set_streaming(self, detector: Detector, readout: Readout, streaming: bool) -> None:
        """Mark whether the live loop streams `detector`; it counts as recording then."""
        readout.streaming = streaming
        with acquired_locks(CAMERA_LOCK):
            detector.is_recording = streaming

    def _end_live_sessions(self) -> None:
        """Mark every detector as not streaming; its last session stays readable."""
        with self._lock:
            for detector in self.state.detectors:
                readout = self._readout(detector.slot)
                if readout.streaming:
                    self._set_streaming(detector, readout, False)

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
        self,
        slot: int,
        exposure_time: Optional[float] = None,
        gain: Optional[float] = None,
        frame_rate: Optional[float] = None,
        binning: Optional[int] = None,
        roi: Optional[Roi] = None,
    ) -> Detector:
        """
        Update detector settings; None keeps a setting. Values are clamped to the ranges.

        A new binning or region changes the detector's image size and, while streaming,
        starts a new session (as a camera restarts).

        Args:
            slot: Detector slot number.
            exposure_time: New exposure time in seconds (if provided).
            gain: New gain value (if provided).
            frame_rate: New live frame rate in frames per second (if provided); 0 removes
                the limit.
            binning: New binning factor (if provided), snapped to the nearest of `BINNINGS`.
            roi: New region of interest (if provided) in unbinned sensor pixels, clamped to
                the sensor; `FULL_SENSOR` selects the complete sensor.

        Returns:
            The updated detector with every value applied.

        Raises:
            ValueError: If the detector slot is not found, or for a frame rate < 0, a
                binning < 1, or a region with negative values or smaller than the binning.
        """
        detector = self._require_detector(slot)
        if frame_rate is not None and frame_rate < 0:
            raise ValueError(f"frame rate must be >= 0, got {frame_rate}")

        with self._lock:
            readout = self._readout(slot)
            if binning is not None or roi is not None:
                new_binning = (
                    detector.current_binning if binning is None else self._snap_binning(binning)
                )
                new_roi = detector.current_roi if roi is None else self._clamp_roi(roi)
                width, height = self._image_size(new_binning, new_roi)
                if width == 0 or height == 0:
                    raise ValueError(f"region {new_roi} is smaller than the binning {new_binning}")
                detector.current_binning, detector.current_roi = new_binning, new_roi
                detector.width, detector.height = width, height
                if readout.streaming:
                    self._start_session(detector, readout)

            if exposure_time is not None:
                clamped = self._clamp(
                    exposure_time, detector.min_exposure_time, detector.max_exposure_time
                )
                detector.current_exposure_time = clamped

            if gain is not None:
                clamped = self._clamp(gain, detector.min_gain, detector.max_gain)
                detector.current_gain = clamped

            if frame_rate is not None:
                detector.current_frame_rate = (
                    None if frame_rate == 0 else self._clamp(frame_rate, *FRAME_RATE_RANGE)
                )

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

    def get_image_info(self, slot: int) -> Optional[DetectorSessionInfo]:
        """
        Return the metadata of the current or last acquisition session.

        Args:
            slot: Detector slot number.

        Returns:
            The session metadata, or None before the first acquisition.

        Raises:
            ValueError: If the detector slot is not found.
        """
        self._require_detector(slot)
        with self._lock:
            return self._readout(slot).session

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

    def capture_image(self, slot: int | None = None, save_to_disk: bool = False) -> DetectorFrame:
        """
        Capture a single image from a specific detector.

        Outside of the live stream every snapshot is a session of its own.

        Args:
            slot: Detector slot number; None = the first active detector.
            save_to_disk: Not supported by the virtual detector.

        Returns:
            The image (region of interest, binned) with its timing.

        Raises:
            ValueError: If the detector slot is not active.
            NotImplementedError: ``save_to_disk``.
        """
        if save_to_disk:
            raise NotImplementedError(NO_DISK_RECORDING)
        detector = self._get_active_detector(slot)
        if detector is None:
            raise ValueError(f"No active detector found with slot {slot}")

        with self._lock:
            readout = self._readout(detector.slot)
            if not readout.streaming:
                self._start_session(detector, readout)
            return self._next_frame(detector, readout)

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
        Run the live loop until `close` (protocol method).

        While `CameraState.is_acquiring` is set, renders an image of every active detector
        and broadcasts it on the detector's slot: as fast as frames render, or paced by
        the detector's frame rate. Each detector streams in a session of its own.
        """
        self.broadcaster.start_broadcasting()

        while not self._closed:
            if not self.state.is_acquiring:
                self._end_live_sessions()
                koil.sleep(IDLE_INTERVAL_S)
                continue
            wait_s = self._stream_due_frames()
            if wait_s > 0:
                koil.sleep(wait_s)

    def _stream_due_frames(self) -> float:
        """Broadcast an image of every active detector that is due.

        Returns:
            Seconds until the next image is due, at most `IDLE_INTERVAL_S`.
        """
        wait_s = IDLE_INTERVAL_S
        with self._lock:
            if not self.state.is_acquiring:  # stopped since the loop looked
                return 0.0
            for detector in self.state.detectors:
                readout = self._readout(detector.slot)
                if not detector.is_active:
                    if readout.streaming:
                        self._set_streaming(detector, readout, False)
                    continue
                if not readout.streaming:
                    self._set_streaming(detector, readout, True)
                    readout.next_due_ns = 0
                    self._start_session(detector, readout)
                now_ns = time.monotonic_ns()
                if now_ns >= readout.next_due_ns:
                    frame = self._next_frame(detector, readout)
                    self.broadcaster.broadcast_sync(detector.slot, frame.data)
                    rate = detector.current_frame_rate
                    period_ns = 0 if rate is None else int(1e9 / rate)
                    readout.next_due_ns = now_ns + period_ns
                remaining_s = (readout.next_due_ns - time.monotonic_ns()) / 1e9
                wait_s = min(wait_s, max(0.0, remaining_s))
        return wait_s

    def start_acquire_live(self, save_to_disk: bool = False) -> None:
        """
        Start the live stream: set `CameraState.is_acquiring` (protocol method).

        Args:
            save_to_disk: Not supported by the virtual detector.

        Raises:
            NotImplementedError: ``save_to_disk``; the live stream is then not started.
        """
        if save_to_disk:
            raise NotImplementedError(NO_DISK_RECORDING)
        with self._lock:
            self.state.is_acquiring = True

    def stop_acquire_live(self) -> None:
        """
        Stop the live stream now: clear `CameraState.is_acquiring`, end the live sessions.

        `acquire_live` keeps running and streams again once the live stream is started.
        """
        with self._lock:
            self.state.is_acquiring = False
            self._end_live_sessions()

    def close(self) -> None:
        """End `acquire_live`; calling it again does nothing."""
        self._closed = True
        self._end_live_sessions()

    def background(self) -> None:
        """Background task for the virtual detector manager."""
        # For this simple implementation, we don't need a background loop
        # since all operations are synchronous and triggered by registered functions.
        pass
