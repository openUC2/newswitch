"""Files the IO manager writes, and their formats."""

from dataclasses import dataclass
from enum import Enum


@dataclass
class FileHandle:
    """Handle for saved files."""

    file_path: str

    def __str__(self) -> str:
        """String representation of the file handle."""
        return self.file_path


class FileFormat(str, Enum):
    """Enumeration of supported file formats."""

    NPY = "npy"
    TIFF = "tiff"
    PNG = "png"
