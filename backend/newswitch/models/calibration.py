"""A calibrated light path: the pixel-to-stage transform of one light path configuration."""

from dataclasses import dataclass

from arkitekt import model_field

from newswitch.models.light_path import AffineMatrix


@dataclass
class CalibratedLightPath:
    """Shared state for affine transformation parameters."""

    affine_matrix: AffineMatrix = model_field(
        default_factory=lambda: [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        description="4x4 affine transformation matrix for mapping between coordinate systems",
    )
    fov_width: float = model_field(default=10.0, description="Field of view width in micrometers")
    fov_height: float = model_field(default=10.0, description="Field of view height in micrometers")
    light_path_state_hash: str = model_field(
        default="",
        description="The transformation hash of the light path configuration this affine matrix corresponds to",
    )
