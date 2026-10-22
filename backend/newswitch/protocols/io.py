"""
IO Manager Protocol

Defines the protocol for file I/O operations and associated state.
"""

from enum import Enum
from typing import Optional, Protocol, runtime_checkable
from dataclasses import dataclass
import numpy as np
from newswitch.protocols.base import Manager
from newswitch.arkitekt_app import nsapp


@dataclass
class FileHandle:
    """Handle for saved files."""

    file_path: str

    def __str__(self) -> str:
        """String representation of the file handle."""
        return self.file_path


@nsapp.state(required_locks=["io"])
@dataclass
class IOState:
    """Shared state for IO operations."""

    last_saved_file: str | None = None


class FileFormat(str, Enum):
    """Enumeration of supported file formats."""

    NPY = "npy"
    TIFF = "tiff"
    PNG = "png"


@nsapp.context(locks=["io"])
@runtime_checkable
class IOManager(Manager, Protocol):
    """Protocol defining the interface for IO managers."""

    state: IOState

    def save_numpy_array(
        self,
        array: np.ndarray,
        filename: Optional[str] = None,
        format: Optional[FileFormat] = None,
        rescale: bool = False,
    ) -> str:
        """
        Save a numpy array to storage.

        Args:
            array: The numpy array to save.
            filename: Optional filename. Auto-generated if not provided.
            format: File format. Uses default if not provided.
            rescale: If True, rescale values to use the full range of the
                target format (e.g., 0-255 for PNG). If False, values are
                converted directly (uint16 / 256 for PNG).

        Returns:
            Handle to the saved file.
        """
        ...

    def stream_file_handle(
        self,
        file_handle: str,
    ) -> bytes:
        """
        Stream the contents of a file given its handle.

        Args:
            file_handle: Handle to the file.

        Returns:
            File contents as bytes.
        """
        ...

    def file_exists(self, file_handle: str) -> bool:
        """Check if a file exists."""
        ...
