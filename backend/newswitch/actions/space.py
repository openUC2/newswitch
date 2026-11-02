"""Going to a place, in any coordinate system the graph knows; and saying where the sample sits."""

from typing import Optional

from arkitekt import Task

from newswitch import protocols
from newswitch.models.space import Position
from newswitch.services.space import SpaceManager
from newswitch.services.values import Values


def _looking(space: SpaceManager, detector: Optional[str]) -> str:
    """The detector named, or else the first that is on, or else the first."""
    if detector is not None:
        return detector
    detectors = space.detector_state.detectors
    if not detectors:
        raise ValueError("Nothing here looks at the sample")
    return next((d.name for d in detectors if d.is_active), detectors[0].name)


def move_to(
    space: SpaceManager,
    values: Values,
    task: Task,
    position: Position,
    detector: Optional[str] = None,
) -> None:
    """Look at a place: the middle of the detector's image goes there.

    Args:
        position: Where: in the sample, the stage, an image taken (``image:<id>``), a detector
            (``detector:<name>``, its pixels as they are now). Without z, z stays.
        detector: Whose image; by default the first that is on.
    """
    values.set(space.targets(position, _looking(space, detector)), task=task)


def set_sample_origin_here(space: SpaceManager, detector: Optional[str] = None) -> None:
    """Make where a detector looks now the sample's x and y 0.

    Args:
        detector: Whose image's middle; by default the first that is on.
    """
    space.origin_here(_looking(space, detector))


def register_mount(space: SpaceManager, matrix: list[list[float]]) -> None:
    """Say where what is mounted sits on the stage.

    Args:
        matrix: 4x4, stage micrometres to sample micrometres.
    """
    space.register_mount(matrix)


def mount_holder(
    space: SpaceManager, expanse_manager: protocols.ExpanseManager, holder: str
) -> None:
    """Mount another holder: a new sample, where the description says it sits.

    The images taken were of what was mounted before: the expanse starts empty.

    Args:
        holder: One of the holders the description names for its sample.
    """
    space.mount_holder(holder)
    expanse_manager.reset_expanse()
