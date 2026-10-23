"""The autofocus state: the last sweep's planes and scores."""

from dataclasses import dataclass, field


@dataclass
class AutofocusState:
    """Live view of the last/ongoing autofocus run."""

    running: bool = False
    best_z: float = 0.0
    best_metric: float = 0.0
    metric_name: str = "laplacian_variance"
    z_positions: list[float] = field(default_factory=list)
    metrics: list[float] = field(default_factory=list)
