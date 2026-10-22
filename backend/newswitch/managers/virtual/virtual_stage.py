"""
Virtual Stage Manager

A virtual stage/positioner manager for microscopy simulation.
Handles X, Y, Z, and A (angle) positioning.
"""

from dataclasses import dataclass
from typing import Optional

import koil
from newswitch.protocols.stage import StageState
from arkitekt import Task
from newswitch.arkitekt_app import nsapp


#: The most steps (state updates) a move at a configured speed takes.
MAX_STEPS = 100


@nsapp.model
@dataclass
class StageConfig:
    """Configuration for the virtual stage."""

    min_x: float = -10000.0
    max_x: float = 10000.0
    min_y: float = -10000.0
    max_y: float = 10000.0
    min_z: float = -1000.0
    max_z: float = 1000.0
    min_a: float = -360.0
    max_a: float = 360.0
    simulated_pos_sleep_per_micrometer: float = (
        0.1  # Sleep time to simulate movement delay (seconds)
    )
    speed_um_per_s: float | None = None
    """The speed of the simulated stage, when the device configuration gives one (an axis'
    ``vel``): a move then takes as long as it would on the real stage, in at most
    `MAX_STEPS` steps. None: every step takes `simulated_pos_sleep_per_micrometer`."""
    # PSF computation dimensions (height, width)
    psf_a_dimension: int = 128
    psf_b_dimension: int = 128


class VirtualStageManager:
    """
    A virtual stage manager for microscopy simulation.

    Provides position control for X, Y, Z, and A axes with optional
    PSF computation for defocus simulation.
    Implements the StageManager protocol.
    """

    state: StageState

    def __init__(
        self,
        stage: StageState,
        config: Optional[StageConfig] = None,
    ) -> None:
        """
        Initialize the virtual stage manager.

        Args:
            stage: Shared stage state.
            config: Stage configuration. Uses defaults if not provided.
        """
        self.config = config or StageConfig()
        self.state = stage

    def move(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        a: Optional[float] = None,
        step_size: Optional[float] = None,
        is_absolute: bool = False,
        task: Optional[Task] = None,
    ) -> None:
        """Move the stage to an absolute or relative target position.

        The travel is simulated in increments of `step_size` micrometers, sleeping between
        steps and clamping to the configured axis limits.
        """
        if step_size is None:
            step_size = 10.0

        # 1. Determine Target Absolute Positions
        target_x = x if is_absolute else (self.state.x + (x or 0))
        target_y = y if is_absolute else (self.state.y + (y or 0))
        target_z = z if is_absolute else (self.state.z + (z or 0))
        target_a = a if is_absolute else (self.state.a + (a or 0))

        # 2. Calculate Total Delta (for calculation only)
        dx = (target_x - self.state.x) if x is not None else 0.0
        dy = (target_y - self.state.y) if y is not None else 0.0
        dz = (target_z - self.state.z) if z is not None else 0.0
        da = (target_a - self.state.a) if a is not None else 0.0

        total_distance = (dx**2 + dy**2 + dz**2) ** 0.5
        if total_distance == 0 and da != 0:
            total_distance = abs(da)

        if total_distance < 0.001:  # Already there
            return

        num_steps = max(1, int(total_distance / step_size))
        sleep_per_step = self.config.simulated_pos_sleep_per_micrometer
        if self.config.speed_um_per_s:
            # At a real stage's speed: few steps (state updates), so a long move does not
            # flood the clients, each taking its share of the travel time.
            num_steps = min(num_steps, MAX_STEPS)
            sleep_per_step = total_distance / num_steps / self.config.speed_um_per_s

        # Calculate step increments
        step_x = dx / num_steps
        step_y = dy / num_steps
        step_z = dz / num_steps
        step_a = da / num_steps

        # 3. Simulate gradual movement
        for step in range(num_steps):
            if task is not None:
                task.pausepoint()
            koil.sleep(sleep_per_step)

            # Move and Clamp
            if x is not None:
                self.state.x = self._clamp(
                    self.state.x + step_x, self.config.min_x, self.config.max_x
                )
            if y is not None:
                self.state.y = self._clamp(
                    self.state.y + step_y, self.config.min_y, self.config.max_y
                )
            if z is not None:
                self.state.z = self._clamp(
                    self.state.z + step_z, self.config.min_z, self.config.max_z
                )
            if a is not None:
                self.state.a = self._clamp(
                    self.state.a + step_a, self.config.min_a, self.config.max_a
                )

            if task is not None:
                task.progress(int((step + 1) / num_steps * 100))

        return None

    def move_home(self) -> None:
        """Move the stage to the home position (0, 0, 0, 0) (protocol method)."""
        return self.move(x=0.0, y=0.0, z=0.0, a=0.0, is_absolute=True)

    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp a value to the specified range."""
        return max(min_val, min(max_val, value))

    def background(self) -> None:
        """Background task for the virtual detector manager."""
        # For this simple implementation, we don't need a background loop
        # since all operations are synchronous and triggered by registered functions.
        pass
