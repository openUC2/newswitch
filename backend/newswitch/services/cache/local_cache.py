"""
Local File IO Manager

Manages saving numpy arrays to the local filesystem as Zarr v3 stores.
"""

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import zarr
from numpy.typing import NDArray
from zarr.storage import LocalStore

# Assuming Metadata is defined in your protocols
from newswitch.models.frames import Metadata


@dataclass
class LocalCacheConfig:
    """Configuration for the local cache manager."""

    base_path: str = "/tmp/newswitch/cache"
    create_dirs: bool = True
    delete_on_restart: bool = True
    # Default chunking strategy for 3D arrays (Z, Y, X). Adjust as needed.
    default_chunks: tuple[float, float, float] = (1, 256, 256)


class LocalCacheManager:
    """
    A local cache manager for saving frames.

    Implements the IOManager protocol for saving and retrieving files
    from the local filesystem using Zarr v3.
    """

    def __init__(
        self,
        config: Optional[LocalCacheConfig] = None,
    ) -> None:
        """
        Initialize the local cache manager.

        Args:
            config: IO configuration. Uses defaults if not provided.
        """
        self.config = config or LocalCacheConfig()

        # Ensure base path exists
        if self.config.create_dirs:
            Path(self.config.base_path).mkdir(parents=True, exist_ok=True)

        if self.config.delete_on_restart:
            # Clear existing cache on startup if configured to do so
            shutil.rmtree(self.config.base_path, ignore_errors=True)
            Path(self.config.base_path).mkdir(parents=True, exist_ok=True)

    @property
    def local_store(self) -> LocalStore:
        """Get the base local store path."""
        return LocalStore(self.config.base_path)

    def _generate_filename(self, metadata: Metadata) -> str:
        """Generate a unique directory name for the Zarr store."""
        # Using a UUID to prevent collisions. You could also hash the metadata.
        return f"frame_{uuid.uuid4().hex}.zarr"

    def save_frame(
        self,
        array: NDArray[Any],
        metadata: Metadata,
        expanse_id: Optional[str] = None,
    ) -> str:
        """
        Save a numpy array to the filesystem as a Zarr v3 store.

        Args:
            array: The numpy array to save.
            metadata: Metadata associated with the frame.
            expanse_id: Optional tracking ID.

        Returns:
            The string ID (folder name) of the saved Zarr store.
        """
        if len(array.shape) != len(self.config.default_chunks):
            raise ValueError(
                f"Array shape {array.shape} does not match the expected chunk dimensions {self.config.default_chunks}. "
                "Please provide an array with matching dimensions or adjust the default_chunks configuration."
            )

        assert len(array.shape) == 3, "Expected a 3D array (Z, Y, X) for saving as a frame."
        store_id = self._generate_filename(metadata)
        store_path = os.path.join(self.config.base_path, store_id)

        # Initialize the LocalStore pointing directly to the new directory
        store = LocalStore(store_path)

        # Determine chunks. Fall back to auto-chunking (True) if shape dimensions don't match

        # Save directly to the root of the store in Zarr v3 format
        zarr.save_array(
            store=store,
            arr=array,
            zarr_format=3,
            # We omit `path` so the array sits at the root (creates zarr.json at store_path/zarr.json)
        )

        return store_id

    def stream_file_handle(self, file_handle: str) -> bytes:
        """
        Read the contents of a specific file inside the store and return as bytes.
        (Useful if you need to read a specific chunk manually).

        Args:
            file_handle: Absolute path to the file to read.

        Returns:
            File contents as bytes.
        """
        with open(file_handle, "rb") as f:
            return f.read()

    def get_frame_path(self, store_id: str) -> str:
        """
        Get the absolute path for a Zarr store ID.

        Args:
            store_id: The ID/folder name of the Zarr store.

        Returns:
            Absolute directory path.
        """
        return os.path.abspath(os.path.join(self.config.base_path, store_id))

    def stream_frame(self, cached_id: str) -> bytes:
        """Streams a specific file handle (alias for stream_file_handle)."""
        return self.stream_file_handle(cached_id)

    def frame_exists(self, store_id: str) -> bool:
        """Check if a Zarr store exists."""
        target_path = os.path.join(self.config.base_path, store_id)
        return os.path.exists(target_path) and os.path.isdir(target_path)

    def delete_frame(self, store_id: str) -> bool:
        """
        Delete a Zarr store.

        Args:
            store_id: The ID of the store to delete.

        Returns:
            True if the store was deleted, False otherwise.
        """
        target_path = os.path.join(self.config.base_path, store_id)
        if os.path.exists(target_path):
            # Zarr stores are directories, so we must use shutil.rmtree
            shutil.rmtree(target_path, ignore_errors=True)
            return True
        return False

    def get_frame_store_dir(self, store_id: str) -> Path:
        """Get the directory Path object for a given store ID."""
        return Path(self.config.base_path) / store_id
