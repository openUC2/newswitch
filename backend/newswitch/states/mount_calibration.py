"""The holder calibration, as a panel shows it: what it measures with, where the holder is taken to
be, how far a run is, what it waits for, and what it found last."""

from dataclasses import dataclass
from typing import Optional

from newswitch.models.calibration import MeasuredMount


@dataclass
class MountCalibrationState:
    """The calibration of a holder's mount (`calibrate_mount`)."""

    sample: str = ""
    """The sample whose holder it measures, by the cube holding it; empty: none is described."""
    holder: str = ""
    """Which of its holders (by name), and what it is (from the library)."""
    holder_kind: str = ""
    slide: str = ""
    """The calibration slide, where it lies (``slot:A1``) and what of it is found."""
    at: str = ""
    mark: str = ""
    mount_x_mm: float = 0.0
    """Where the holder's origin is taken to be on the stage now, from where homing puts it."""
    mount_y_mm: float = 0.0
    busy: bool = False
    step: str = "idle"
    progress: int = 0
    waiting: Optional[str] = None
    """What the running calibration holds for (a person to approve), while it does."""
    error: Optional[str] = None
    last: Optional[MeasuredMount] = None
