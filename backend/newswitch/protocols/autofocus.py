"""Autofocus state shared between the autofocus routine and the frontend."""

from dataclasses import dataclass, field

from rekuest_next import state


@state
@dataclass
class AutofocusState:
    """Live view of the last/ongoing autofocus run."""

    running: bool = False
    best_z: float = 0.0
    best_metric: float = 0.0
    metric_name: str = "laplacian_variance"
    z_positions: list[float] = field(default_factory=list)
    metrics: list[float] = field(default_factory=list)
