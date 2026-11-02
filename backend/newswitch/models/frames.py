"""Acquired frames and their metadata: what an acquisition hands out and caches."""

from dataclasses import dataclass

from newswitch.models.light_path import AffineMatrix, LightPathSnapshot


@dataclass
class Metadata:
    """Where an image's pixels are on the sample, and what it was taken under."""

    affine_matrix: AffineMatrix  # pixel column, row and plane to sample micrometres
    fov_width: float  # how wide it is on the sample, in micrometres, along its rows
    fov_height: float  # how high, along its columns
    light_state: LightPathSnapshot
    acquisition_time: str  # ISO 8601 timestamp of when the image was acquired
    colormap: str = "gray"  # Colormap used for the image (e.g., 'gray', 'viridis')
    min_value: float | None = (
        None  # Minimum pixel value for display (if None, it will be calculated from the image data)
    )
    max_value: float | None = (
        None  # Maximum pixel value for display (if None, it will be calculated from the image data)
    )


@dataclass
class Image:
    """Represents a single image captured by the detector."""

    id: str
    metadata: Metadata


@dataclass
class Scale:
    """Represents a scale factor for a 3D volume."""

    x: float
    y: float
    z: float
    cached_id: str | None = None  # ID of the cached scaled image, if it has been cached
    affine_matrix: AffineMatrix | None = (
        None  # Affine matrix for this scale, if it has been calculated
    )


@dataclass
class ArrayMetadata:
    """Metadata for a raw array before it is saved as an image, including the light path and acquisition settings."""

    min_value: float
    max_value: float


@dataclass
class Frame:
    """Represents a single 3D volume captured by the detector."""

    id: str
    scales: list[Scale]
    metadata: Metadata
    array_metadata: ArrayMetadata
