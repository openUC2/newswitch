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


@dataclass
class MeasuredMount:
    """Where a holder was measured to sit on its stage, from its calibration slide."""

    sample: str = model_field(description="The sample, by the cube holding it")
    holder: str = model_field(description="Which of its holders")
    x_mm: float = model_field(description="Where the holder's origin is on the stage, along x")
    y_mm: float = model_field(description="... and along y, from where homing puts the stage")
    rotation_deg: float = model_field(default=0.0, description="How far it is turned, as described")
    shift_um: list[float] = model_field(
        default_factory=list, description="How far that is from where it was taken to be, x and y"
    )
    pixel_um: float = model_field(default=0.0, description="Image scale measured on the way")
    saved_to: str | None = model_field(
        default=None, description="The description it was written into, if it was"
    )
