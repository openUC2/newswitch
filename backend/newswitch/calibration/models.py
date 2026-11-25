"""What a calibration found: where a holder sits, and how far that is from its design."""

from dataclasses import dataclass

from arkitekt import model_field


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
        default=None, description="The calibration store it was kept in, if it was"
    )


@dataclass
class CalibratedMount:
    """How far a holder sits from where its design puts it (its `mount`): what is kept of it."""

    sample: str = model_field(description="The sample, by the cube holding it")
    holder: str = model_field(description="Which of its holders")
    offset_x_um: float = model_field(default=0.0, description="Off its design's place, along x")
    offset_y_um: float = model_field(default=0.0, description="... and along y")
    rotation_deg: float = model_field(default=0.0, description="Turned further than its design says")
    measured: str = model_field(default="", description="When it was measured, ISO 8601")
