"""
Local File IO Manager

Manages saving numpy arrays to the local filesystem.
"""

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from newswitch.protocols.io import FileFormat, IOState
from newswitch.arkitekt_app import nsapp


@nsapp.model
@dataclass
class LocalFileConfig:
    """Configuration for the local file IO manager."""

    base_path: str = "/tmp/newswitch"
    create_dirs: bool = True
    default_format: FileFormat = FileFormat.PNG


class LocalFileIOManager:
    """
    A local filesystem IO manager for saving numpy arrays.

    Implements the IOManager protocol for saving and retrieving files
    from the local filesystem.
    """

    def __init__(
        self,
        state: IOState,
        config: Optional[LocalFileConfig] = None,
    ) -> None:
        """
        Initialize the local file IO manager.

        Args:
            state: Shared IO state.
            config: IO configuration. Uses defaults if not provided.
        """
        self.state = state
        self.config = config or LocalFileConfig()

        # Ensure base path exists
        if self.config.create_dirs:
            Path(self.config.base_path).mkdir(parents=True, exist_ok=True)

    def _generate_filename(self, format: FileFormat) -> str:
        """Generate a unique filename."""
        unique_id = uuid.uuid4().hex[:12]
        extension = format.value
        return f"image_{unique_id}.{extension}"

    def save_numpy_array(
        self,
        array: np.ndarray,
        filename: Optional[str] = None,
        format: Optional[FileFormat] = None,
        rescale: bool = False,
    ) -> str:
        """
        Save a numpy array to the filesystem.

        Args:
            array: The numpy array to save.
            filename: Optional filename. Auto-generated if not provided.
            format: File format. Uses default from config if not provided.
            rescale: If True, rescale values to use the full range of the
                target format (e.g., 0-255 for PNG). If False, values are
                converted directly.

        Returns:
            FileHandle pointing to the saved file.
        """
        format = format or self.config.default_format

        if filename is None:
            filename = self._generate_filename(format)

        file_path = os.path.join(self.config.base_path, filename)

        if format == FileFormat.NPY:
            np.save(file_path, array)
            # np.save adds .npy extension if not present
            if not file_path.endswith(".npy"):
                file_path = f"{file_path}.npy"
        elif format == FileFormat.TIFF:
            import tifffile

            # tifffile supports uint16 natively, no need to convert
            tifffile.imwrite(file_path, array)
        elif format == FileFormat.PNG:
            try:
                from PIL import Image

                # Convert to 8-bit for PNG
                if rescale:
                    # Rescale to use full 0-255 range
                    arr_min = array.min()
                    arr_max = array.max()
                    if arr_max > arr_min:
                        img_data = ((array - arr_min) / (arr_max - arr_min) * 255).astype(np.uint8)
                    else:
                        # Constant image - use middle gray
                        img_data = np.full(array.shape, 128, dtype=np.uint8)
                elif array.dtype == np.uint16:
                    img_data = (array / 256).astype(np.uint8)
                elif array.max() <= 1.0:
                    img_data = (array * 255).astype(np.uint8)
                else:
                    img_data = array.astype(np.uint8)

                Image.fromarray(img_data).save(file_path)
            except ImportError:
                raise ImportError("PIL/Pillow is required for PNG format")

        self.state.last_saved_file = file_path

        return file_path

    def stream_file_handle(self, file_handle: str) -> bytes:
        """
        Read the contents of a file and return as bytes.

        Args:
            file_handle: Handle to the file to read.

        Returns:
            File contents as bytes.
        """
        with open(file_handle, "rb") as f:
            return f.read()

    def get_file_path(self, file_handle: str) -> str:
        """
        Get the absolute path for a file handle.

        Args:
            file_handle: Handle to the file.

        Returns:
            Absolute file path.
        """
        return os.path.abspath(file_handle)

    def file_exists(self, file_handle: str) -> bool:
        """
        Check if a file exists.

        Args:
            file_handle: Handle to check.

        Returns:
            True if file exists.
        """
        return os.path.exists(file_handle)

    def delete_file(self, file_handle: str) -> bool:
        """
        Delete a file.

        Args:
            file_handle: Handle to the file to delete.

        Returns:
            True if file was deleted.
        """
        if os.path.exists(file_handle):
            os.remove(file_handle)
            return True
        return False
