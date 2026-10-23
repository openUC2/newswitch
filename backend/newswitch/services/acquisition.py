"""Acquisition manager for handling image acquisition from detectors and managing the resulting images within the expanse state."""

from __future__ import annotations

import logging
from typing import Optional

from newswitch.models.frames import ArrayMetadata, Frame, Scale
from newswitch.protocols import MetadataManager
from newswitch.protocols.cache import CacheManager
from newswitch.protocols.detector import DetectorManager
from newswitch.protocols.expanse import ExpanseManager
from newswitch.protocols.light_path import LightPathManager

logger = logging.getLogger(__name__)


class AcquisitionManager:
    """Registry and execution for acquisition hooks."""

    def __init__(
        self,
        expanse_manager: ExpanseManager,
        detector_manager: DetectorManager,
        metadata_manager: MetadataManager,
        light_path_manager: LightPathManager,
        cache_manager: CacheManager,
    ) -> None:
        """Initialize the AcquisitionManager with the provided managers."""
        self.expanse_manager = expanse_manager
        self.detector_manager = detector_manager
        self.metadata_manager = metadata_manager
        self.light_path_manager = light_path_manager
        self.cache_manager = cache_manager

    def acquire(self, slots: Optional[list[int]] = None) -> list[Frame]:
        """A frame from each active detector (only those in `slots`, when given).

        Each frame is cached, gets the metadata of its light path, and is added to the expanse.
        """
        frames: list[Frame] = []

        for detector in self.detector_manager.state.detectors:
            if slots is not None and detector.slot not in slots:
                continue
            if detector.is_active:
                image_data = self.detector_manager.capture_image(slot=detector.slot).data

                light_path = self.light_path_manager.get_light_path_for_detector(
                    detector_slot=detector.slot
                )

                metadata = self.metadata_manager.get_metadata_for_light_path(light_path=light_path)

                three_d_image_data = image_data.reshape(
                    (1, *image_data.shape)
                )  # Add a Z dimension for 3D compatibility

                # Save to cache and return handle
                file_handle = self.cache_manager.save_frame(
                    array=three_d_image_data,
                    metadata=metadata,
                    expanse_id=self.expanse_manager.state.current_id,
                )

                frame = Frame(
                    id=file_handle,
                    scales=[Scale(x=1, y=1, z=1, cached_id=file_handle)],
                    metadata=metadata,
                    array_metadata=ArrayMetadata(
                        min_value=float(image_data.min()), max_value=float(image_data.max())
                    ),
                )

                logger.debug("Acquired frame %s from detector %d", frame.id, detector.slot)
                self.expanse_manager.add_frame(frame)
                frames.append(frame)

        return frames
