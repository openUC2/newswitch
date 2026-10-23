"""The stage state: position, limits and step sizes."""

from dataclasses import dataclass

from arkitekt import model_field


@dataclass
class StageState:
    """Shared state for stage position."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    a: float = 0.0
    max_x: float = 1000.0
    min_x: float = -1000.0
    max_y: float = 1000.0
    min_y: float = -1000.0
    max_z: float = 100.0
    min_z: float = -100.0
    max_a: float = 360.0
    min_a: float = -360.0
    registered_step_sizes: list[float] = model_field(
        default_factory=lambda: [0.1, 1.0, 10.0, 100.0],
        description="List of registered step sizes for the stage.",
    )

    def is_roughly_equal(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        a: float | None = None,
        tolerance: float = 1e-6,
        raise_on_mismatch: bool = True,
    ) -> bool:
        """Check if this state is approximately equal to another StageState."""
        if x is not None and (abs(self.x - x) > tolerance):
            if raise_on_mismatch:
                raise ValueError(f"x value {x} is out of bounds ({self.x}")
            return False
        if y is not None and (abs(self.y - y) > tolerance):
            if raise_on_mismatch:
                raise ValueError(f"y value {y} is out of bounds ({self.y})")
            return False
        if z is not None and (abs(self.z - z) > tolerance):
            if raise_on_mismatch:
                raise ValueError(f"z value {z} is out of bounds ({self.z})")
            return False
        if a is not None and (abs(self.a - a) > tolerance):
            if raise_on_mismatch:
                raise ValueError(f"a value {a} is out of bounds ({self.min_a})")
            return False
        return True

    def as_affine_matrix(self) -> list[list[float]]:
        """Convert the stage position to a 4x4 affine transformation matrix."""
        return [
            [1.0, 0.0, 0.0, self.x],
            [0.0, 1.0, 0.0, self.y],
            [0.0, 0.0, 1.0, self.z],
            [0.0, 0.0, 0.0, 1.0],
        ]
