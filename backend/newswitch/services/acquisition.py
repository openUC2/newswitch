"""Acquisition manager for handling image acquisition from detectors and managing the resulting images within the expanse state."""

from __future__ import annotations

import logging
from typing import Optional

from newswitch.models.frames import ArrayMetadata, Frame, Scale
from newswitch.protocols import MetadataManager
from newswitch.protocols.cache import CacheManager
from newswitch.protocols.detector import DetectorManager
from newswitch.protocols.expanse import ExpanseManager
from newswitch.protocols.optics import OpticsManager

logger = logging.getLogger(__name__)


class AcquisitionManager:
    """Takes an image with each detector that is on, and keeps it."""

    def __init__(
        self,
        expanse_manager: ExpanseManager,
        detector_manager: DetectorManager,
        metadata_manager: MetadataManager,
        optics_manager: OpticsManager,
        cache_manager: CacheManager,
    ) -> None:
        """Initialize the AcquisitionManager with the provided managers."""
        self.expanse_manager = expanse_manager
        self.detector_manager = detector_manager
        self.metadata_manager = metadata_manager
        self.optics_manager = optics_manager
        self.cache_manager = cache_manager

    def acquire(self, names: Optional[list[str]] = None) -> list[Frame]:
        """A frame from each active detector (only those in `names`, when given).

        Each frame is cached, gets the metadata of its light path, and is added to the expanse.
        """
        frames: list[Frame] = []

        for detector in self.detector_manager.state.detectors:
            if names is not None and detector.name not in names:
                continue
            if detector.is_active:
                image_data = self.detector_manager.capture_image(detector.name).data

                light_path = self.optics_manager.get_light_path_for_detector(detector.name)

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

                logger.debug("Acquired frame %s from detector %s", frame.id, detector.name)
                self.expanse_manager.add_frame(frame)
                frames.append(frame)

        return frames
