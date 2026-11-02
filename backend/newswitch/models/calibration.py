"""A calibrated light path: how large a detector's pixels are on the sample, as measured."""

from dataclasses import dataclass

from arkitekt import model_field

from newswitch.models.light_path import AffineMatrix


@dataclass
class CalibratedLightPath:
    """How a step along a column and along a row moves on the sample, for one light path."""

    affine_matrix: AffineMatrix = model_field(
        default_factory=lambda: [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        description="Pixel to sample micrometres, without where it looks: its 2x2 is the scale",
    )
    key: str = model_field(
        default="",
        description="Of what changes where a pixel looks: this matrix holds for as long as it does",
    )
