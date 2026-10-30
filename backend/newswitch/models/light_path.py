"""The light path model: kubes (the optical parts light passes), their edges, and snapshots of their state."""

from dataclasses import dataclass

from arkitekt import model_field

AffineMatrix = list[list[float]]


@dataclass
class ObjectiveKube:
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


@dataclass
class ObjectiveTurretKube:
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


@dataclass
class DetectorKube:
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


@dataclass
class IlluminationKube:
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


@dataclass
class DichroicKube:
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


@dataclass
class StageKube:
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


@dataclass
class FilterKube:
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


@dataclass
class FilterBankKube:
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


@dataclass
class GenericKube:
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
class LightPathSnapshot:
    """Data class representing the light path used for an image, including illumination settings."""

    hash: str = model_field(
        default="",
        description="Hash of the optical setup of this image: the transformation hash, the active light sources and the filters",
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
        description="Hash of what the optics do to a pixel (detector, objective, their poses), which keys the calibration of this light path. Where the sample is, is not part of it",
    )
