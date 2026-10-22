"""
Virtual Stage Manager

A virtual stage/positioner manager for microscopy simulation.
Handles X, Y, Z, and A (angle) positioning.
"""

from dataclasses import dataclass
from typing import Optional

from newswitch.protocols.z_range import ZRangeState
from newswitch.arkitekt_app import nsapp


@nsapp.model
@dataclass
class ZStageConfig:
    """Configuration for the virtual stage."""

    min_z: float = -100.0
    max_z: float = 100.0


class VirtualZRangeManager:
    """
    A virtual Z range manager for microscopy simulation.

    Provides position control for X, Y, Z, and A axes with optional
    PSF computation for defocus simulation.
    Implements the StageManager protocol.
    """

    state: ZRangeState

    def __init__(
        self,
        stage: ZRangeState,
        config: Optional[ZStageConfig] = None,
    ) -> None:
        """
        Initialize the virtual Z range manager.

        Args:
            stage: Shared Z range state.
            config: Z range configuration. Uses defaults if not provided.
        """
        self.config = config or ZStageConfig()
        self.state = stage

    def move(
        self,
        z: Optional[float] = None,
    ) -> None:
        """Move the stage to a new position (protocol method)."""
        if z is not None:
            self.state.current_z = self._clamp(z, self.config.min_z, self.config.max_z)
        return None

    def set_range(
        self,
        start_z: Optional[float] = None,
        end_z: Optional[float] = None,
    ) -> None:
        """Set the Z range for a Z stack acquisition (protocol method)."""
        if start_z is not None:
            self.state.start_z = self._clamp(start_z, self.config.min_z, self.config.max_z)
        if end_z is not None:
            self.state.end_z = self._clamp(end_z, self.config.min_z, self.config.max_z)
        return None

    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp a value to the specified range."""
        return max(min_val, min(max_val, value))

    def background(self) -> None:
        """Background task for the virtual detector manager."""
        # For this simple implementation, we don't need a background loop
        # since all operations are synchronous and triggered by registered functions.
        pass
