"""Core domain types: the kubes making up a light path, and the images and metadata it produces."""

from dataclasses import dataclass
from typing import Protocol
from arkitekt import model_field
from newswitch.arkitekt_app import nsapp


AffineMatrix = list[list[float]]


class BaseKube(Protocol):
    """Base class for different types of kubes, representing optical components in the light path."""

    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


class StatefulKube(Protocol):
    """Base class for different types of kubes, representing optical components in the light path, including their state information."""

    pass


@nsapp.model
class ObjectiveKube(BaseKube):
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot_id: int  # Slot number of the objective
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


@nsapp.model
class ObjectiveTurretKube(BaseKube):
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective turret (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective turret",
    )


@nsapp.model
class DetectorKube(BaseKube, StatefulKube):
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot_id: int  # Slot number of the detector
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the detector (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the detector",
    )


@nsapp.model
class IlluminationKube(BaseKube, StatefulKube):
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot_id: int  # Slot number of the illumination source
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


@nsapp.model
class DichroicKube(BaseKube):
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot_id: int  # Slot number of the dichroic mirror
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


@nsapp.model
class StageKube(BaseKube, StatefulKube):
    """Data class repesentating the stage, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot_id: int  # Slot number of the stage
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


@nsapp.model
class FilterKube(BaseKube):
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    wavelength: float  # Wavelength of the filter in nm
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the filter (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the filter",
    )


@nsapp.model
class FilterBankKube(BaseKube, StatefulKube):
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    # TODO: Should have probably have a slot_id field as well, since there can be multiple filter banks in the light path
    kube_id: str  # ID of the kube
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the filter bank (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the filter bank",
    )


@nsapp.model
class GenericKube(BaseKube):
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    other_metadata: dict[str, str]  # Arbitrary metadata for this kube
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the generic kube (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )
    state_accessor: str | None = model_field(
        default=None,
        description="Name of the state accessor method to get the current state of this kube (e.g., 'detector_state.affine_matrix')",
    )


Kube = (
    ObjectiveKube
    | DetectorKube
    | FilterKube
    | IlluminationKube
    | GenericKube
    | StageKube
    | DichroicKube
    | FilterBankKube
    | ObjectiveTurretKube
)


@nsapp.model
@dataclass
class LightEdge:
    """Data class representing the light path used for an image, including illumination settings."""

    source: str = model_field(
        description="Source identifier (e.g., ID of LED or laser)",
    )
    target: str = model_field(
        description="Target identifier (e.g., ID of sample or detector)",
    )
    intensity: float | None = model_field(
        description="Intensity of the light source (arbitrary units)",
    )


@nsapp.model
@dataclass
class LightPath:
    """Data class representing the light path used for an image, including illumination settings."""

    detector: int = model_field(
        default=0,
        description="Slot number of the detector in the current light path configuration, used to determine which detector's metadata to include in the light path state",
    )
    kubes: list[Kube] = model_field(
        default_factory=list,
        description="List of kubes representing the optical components in the light path (e.g., objective, detector)",
    )
    edges: list[LightEdge] = model_field(
        default_factory=list,
        description="List of edges representing the light path from source to sample",
    )

    def transformation_hash(self) -> str:
        """Calculate a hash indicating if the kube is affecting the transformation from sample to pixel coordinates, which is used to determine if we can reuse the affine matrix from a previous image."""
        # Placeholder logic to calculate a hash based on the objective and camera states
        # In a real implementation, this would involve more complex logic based on the microscope's optical configuration
        objective = next(
            (kube for kube in self.kubes if isinstance(kube, ObjectiveTurretKube)), None
        )
        detector = next(
            (
                kube
                for kube in self.kubes
                if isinstance(kube, DetectorKube) and kube.slot_id == self.detector
            ),
            None,
        )
        filter = next((kube for kube in self.kubes if isinstance(kube, FilterBankKubeState)), None)

        start_hash: str = "hash"
        if objective is not None:
            start_hash += f"_obj{objective}"
        if detector is not None:
            start_hash += f"_det{detector.slot_id}"
        if filter is not None:
            start_hash += f"_filter{filter.slot_id}"

        return start_hash


@nsapp.model
class ObjectiveKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot_id: int  # Slot number of the objective
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


@nsapp.model
class DichroicKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the dichroic mirror (e.g., 'Dichroic 405/488/561/640 nm')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the dichroic mirror",
    )


@nsapp.model
class DetectorKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    gain: float  # Gain setting for the detector
    exposure_time: float  # Exposure time in milliseconds
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the detector (e.g., 'Pco Edge 4.2m')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the detector",
    )


@nsapp.model
class IlluminationKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot_id: int  # Slot number of the illumination source
    intensity: float  # Intensity of the illumination source
    wavelength: float  # Wavelength of the illumination source in nm
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


@nsapp.model
class FilterKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    wavelength: float  # Wavelength of the filter in nm
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


@nsapp.model
class FilterBankKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot_id: int  # Slot number of the filter bank
    center_wavelength: float
    bandwidth: float
    transmission: float
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the filter bank (e.g., 'Filter Bank 405/488/561/640 nm')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective lens",
    )


@nsapp.model
class ObjectiveTurretKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    slot: int  # Slot number of the active objective in the turret
    magnification: float  # Magnification of the active objective
    numerical_aperture: float  # Numerical aperture of the active objective
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the objective turret (e.g., 'Objective Turret 40x/0.6 NA')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the objective turret",
    )


@nsapp.model
class StageKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the stage (e.g., 'Stage 100x/0.8 NA')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the stage",
    )


@nsapp.model
class GenericKubeState:
    """Data class representing metadata for a kube, including its ID and affine transformation matrix."""

    kube_id: str  # ID of the kube
    other_metadata: dict[str, str]  # Arbitrary metadata for this kube
    affine_matrix: AffineMatrix = model_field(
        description="Affine transformation matrix of the kube",
    )
    model_name: str | None = model_field(
        default=None,
        description="Model name of the stage (e.g., 'Stage 100x/0.8 NA')",
    )
    model_file: str | None = model_field(
        default=None,
        description="Path to a file containing the physical model of the stage",
    )


KubeState = (
    ObjectiveKubeState
    | DetectorKubeState
    | FilterKubeState
    | IlluminationKubeState
    | GenericKubeState
    | StageKubeState
    | DichroicKubeState
    | FilterBankKubeState
    | ObjectiveTurretKubeState
)


@nsapp.model
@dataclass
class LightEdgeState:
    """Data class representing the light path used for an image, including illumination settings."""

    source: str = model_field(
        description="Source identifier (e.g., ID of LED or laser)",
    )
    target: str = model_field(
        description="Target identifier (e.g., ID of sample or detector)",
    )
    intensity: float | None = model_field(
        description="Intensity of the light source (arbitrary units)",
    )
    polarization: str | None = model_field(
        description="Polarization state of the light (e.g., 'linear', 'circular')",
    )


@nsapp.model
@dataclass
class LightPathState:
    """Data class representing the light path used for an image, including illumination settings."""

    hash: str = model_field(
        default="",
        description="Hash of the light path configuration, used to uniquely describe the optical path for this image",
    )
    kubes: list[KubeState] = model_field(
        default_factory=list,
        description="List of kubes representing the optical components in the light path (e.g., objective, detector)",
    )
    edges: list[LightEdgeState] = model_field(
        default_factory=list,
        description="List of edges representing the light path from source to sample",
    )
    transformation_hash: str = model_field(
        default="",
        description="Hash indicating if the kube is affecting the transformation from sample to pixel coordinates, which is used to determine if we can reuse the affine matrix from a previous image",
    )


@nsapp.model
@dataclass
class Metadata:
    """Data class representing metadata for an image, including its ID and affine transformation matrix."""

    affine_matrix: AffineMatrix  # 4x4 affine transformation matrix, mapping from expanse coordinates to pixel coordinates
    fov_width: float  # Field of view width in micrometers
    fov_height: float  # Field of view height in micrometers
    light_state: LightPathState
    acquisition_time: str  # ISO 8601 timestamp of when the image was acquired
    colormap: str = "gray"  # Colormap used for the image (e.g., 'gray', 'viridis')
    min_value: float | None = (
        None  # Minimum pixel value for display (if None, it will be calculated from the image data)
    )
    max_value: float | None = (
        None  # Maximum pixel value for display (if None, it will be calculated from the image data)
    )


@nsapp.model
class Image:
    """Represents a single image captured by the detector."""

    id: str
    metadata: Metadata


@nsapp.model
class Scale:
    """Represents a scale factor for a 3D volume."""

    x: float
    y: float
    z: float
    cached_id: str | None = None  # ID of the cached scaled image, if it has been cached
    affine_matrix: AffineMatrix | None = (
        None  # Affine matrix for this scale, if it has been calculated
    )


@nsapp.model
class ArrayMetadata:
    """Metadata for a raw array before it is saved as an image, including the light path and acquisition settings."""

    min_value: float
    max_value: float


@nsapp.model
class Frame:
    """Represents a single 3D volume captured by the detector."""

    id: str
    scales: list[Scale]
    metadata: Metadata
    array_metadata: ArrayMetadata
