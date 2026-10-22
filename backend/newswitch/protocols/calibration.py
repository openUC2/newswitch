"""
Illumination Manager Protocol

Defines the protocol for illumination/LED control and associated state.
"""

from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field
from newswitch.protocols.base import Manager
from newswitch.protocols.core import AffineMatrix, LightPathState
from arkitekt import model_field
from newswitch.arkitekt_app import nsapp


@nsapp.model
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
        description="Hash of the light path configuration this affine matrix corresponds to",
    )


@nsapp.state
@dataclass
class CalibrationState:
    """Active illumination source configuration."""

    calibrated_light_paths: list[CalibratedLightPath] = field(default_factory=lambda: [])

    def get_calibrated_path(self, light_path_state: LightPathState) -> CalibratedLightPath:
        """Get the calibrated light path for a given light path configuration."""
        for calibrated_light_path in self.calibrated_light_paths:
            if calibrated_light_path.light_path_state_hash == light_path_state.hash:
                return calibrated_light_path
        raise ValueError(
            f"No calibrated light path found for light path hash {light_path_state.hash}"
        )


@nsapp.context
@runtime_checkable
class CalibrationManager(Manager, Protocol):
    """Protocol defining the interface for illumination managers."""

    def set_calibrated_state(self, calibrated_light_path: CalibratedLightPath) -> None:
        """Set the calibrated state for a given light path configuration."""
