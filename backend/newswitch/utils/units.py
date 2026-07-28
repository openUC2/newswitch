from dataclasses import dataclass
import numpy as np


@dataclass
class PhysicalValue:
    value: float
    unit: str
    min_value: float = -np.inf
    max_value: float = np.inf
