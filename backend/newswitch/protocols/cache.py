"""
IO Manager Protocol

Defines the protocol for file I/O operations and associated state.
"""

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

import numpy as np
from newswitch.protocols.base import Manager
from newswitch.protocols.core import Metadata
from newswitch.arkitekt_app import nsapp


@nsapp.context(locks=["cache"])
@runtime_checkable
class CacheManager(Manager, Protocol):
    """Protocol defining the interface for Cache managers."""

    def save_frame(
        self,
        array: np.ndarray,
        metadata: Metadata,
        expanse_id: Optional[str] = None,
    ) -> str:
        """
        Save a numpy array to storage.

        Args:
            array: The numpy array to save.
            metadata: Metadata for the array.
            expanse_id: Optional expanse ID.

        Returns:
            Handle to the saved file.
        """
        ...

    def stream_frame(self, cached_id: str) -> bytes:
        """
        Stream the contents of a cached file given its ID.

        Args:
            cached_id: ID of the cached file.

        Returns:
            File contents as bytes.
        """
        ...

    def frame_exists(self, store_id: str) -> bool:
        """Check if a file exists."""
        ...

    def get_frame_path(self, store_id: str) -> str:
        """Get the actual file path for a given cache ID."""
        ...

    def get_frame_store_dir(self, store_id: str) -> Path:
        """Get the directory path for a given store ID."""
        ...
