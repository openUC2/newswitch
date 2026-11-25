"""The calibration states: the calibrated light paths, and the holder calibration as a panel shows it."""

from dataclasses import dataclass, field
from typing import Optional

from newswitch.calibration.models import CalibratedMount, MeasuredMount
from newswitch.models.light_path import CalibratedLightPath, LightPathSnapshot


@dataclass
class CalibrationState:
    """What is calibrated of this copy of the microscope, as its calibration store keeps it: the
    light paths measured (how large a detector's pixels are on the sample, per setup) and how far
    each holder sits from its design's place."""

    calibrated_light_paths: list[CalibratedLightPath] = field(default_factory=lambda: [])
    mounts: list[CalibratedMount] = field(default_factory=lambda: [])
    design: str = ""
    """The design it is of (`Instrument.design_hash`)."""
    stale: bool = False
    """The store holds calibrations of another design: none of them is applied until they are
    measured again."""
    stored_design: Optional[str] = None
    """The design the store's calibrations are of, when it holds any."""
    saved: Optional[str] = None
    """When the store was last written, ISO 8601."""
    store: Optional[str] = None
    """Where it is kept; None: nowhere, it lives as long as the run."""

    def get_calibrated_path(self, light_path_state: LightPathSnapshot) -> CalibratedLightPath:
        """Get the calibrated light path for a given light path configuration."""
        for calibrated_light_path in self.calibrated_light_paths:
            if calibrated_light_path.key == light_path_state.key:
                return calibrated_light_path
        raise ValueError(f"No calibrated light path found for light path {light_path_state.key}")


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
