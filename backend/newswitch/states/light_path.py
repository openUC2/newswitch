"""The light path state: the light paths the microscope's parts allow."""

from dataclasses import dataclass
from typing import List, Optional

from arkitekt import model_field

from newswitch.models.light_path import LightPath


@dataclass
class LightPathState:
    """State class for the LightPathManager, holding the current light path information."""

    light_paths: List[LightPath] = model_field(default_factory=list)
    current_light_path: Optional[LightPath] = None
