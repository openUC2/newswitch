"""
Virtual Detector Manager

A virtual camera/detector manager for microscopy simulation.
Provides synchronized image capture without background threads.
"""

from dataclasses import dataclass
from typing import Optional

import koil
import numpy as np
from rekuest_next import model

from newswitch.broadcasters import FrameBroadcaster
from newswitch.protocols.detector import CameraState, Detector, FrameSource


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


class VirtualDetectorManager:
    """
    A virtual detector/camera manager for microscopy simulation.

    Provides sync image capture operations. All methods are synchronous
    and will be run in a threadpool via registered functions.

    The manager owns detector bookkeeping only - slots, exposure, gain and
    activation. Pixels come from an injected :class:`FrameSource`; this manager
    neither knows nor cares that the source is a simulated optical scene, so it
    carries no stage/objective/illumination/filter state of its own.
    """

    state: CameraState

    def __init__(
        self,
        camera_state: CameraState,
        broadcaster: FrameBroadcaster,
        frame_source: FrameSource,
        config: Optional[DetectorConfig] = None,
    ) -> None:
        """
        Initialize the virtual detector manager.

        Args:
            camera_state: Shared state for camera parameters.
            broadcaster: Frame broadcaster for video streaming.
            frame_source: Supplies the pixels (the simulated scene).
            config: Detector configuration. Uses defaults if not provided.
        """
        self.state = camera_state
        self.broadcaster = broadcaster
        self.frame_source = frame_source
        self.config = config or DetectorConfig()

        # Initialize detectors
        self._initialize_detectors()

    def _initialize_detectors(self) -> None:
        """Initialize the list of detectors."""
        # Create default virtual detectors
        self.state.detectors = [
            Detector(
                slot=1,
                name="R Channel",
                width=self.config.width,
                height=self.config.height,
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
                width=self.config.width,
                height=self.config.height,
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
                width=self.config.width,
                height=self.config.height,
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

    def _render(self, detector: Detector) -> np.ndarray:
        """Render a frame for a detector at its own sensor size and settings."""
        return self.frame_source.render(
            detector.width,
            detector.height,
            detector.current_exposure_time,
            detector.current_gain,
        )

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

        return self._render(detector)

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
            frame = self._render(detector)

            # Normalize to 0-1 range
            frame_float = frame.astype(np.float64)
            if frame_float.max() > frame_float.min():
                frame_normalized = (frame_float - frame_float.min()) / (
                    frame_float.max() - frame_float.min()
                )
            else:
                frame_normalized = np.zeros_like(frame_float)

            # Resize if needed to match config dimensions. Detectors are created at
            # the config size, so this only kicks in if a slot was resized later.
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
                    frame = self._render(detector)

                    self.broadcaster.broadcast_sync(detector.slot, frame)

                    # Use exposure time from first active detector for frame interval

    def background(self) -> None:
        """Background task for the virtual detector manager."""
        # For this simple implementation, we don't need a background loop
        # since all operations are synchronous and triggered by registered functions.
        pass
