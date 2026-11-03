"""Going to a place, in any coordinate system the graph knows; and saying where each sample sits."""

from typing import Optional

from arkitekt import Task

from newswitch import protocols
from newswitch.models.space import Position
from newswitch.services.space import SpaceManager
from newswitch.services.values import Values


def _looking(space: SpaceManager, detector: Optional[str], sample: Optional[str] = None) -> str:
    """The detector named, or else the first imaging one of the sample that is on, or else the
    first imaging one of it. Of the only sample, unless one is named.

    A thermometer measures at a point: it has no image whose middle could go anywhere.

    Raises:
        ValueError: Nothing looks at that sample; or several samples, and none named.
    """
    if detector is not None:
        return detector
    on = space.one_sample(sample)
    detectors = [
        d
        for d in space.detector_state.detectors
        if d.delivers_images() and space.sees(d.name) and space.sample_of(d.name) == on
    ]
    if not detectors:
        raise ValueError(f"Nothing here looks at the sample {on}")
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
        position: Where, by axis name: on a sample (``sample``, or ``sample:<cube>``), a stage, a
            well (``well:B3``), an image taken (``image:<id>``), a detector (``detector:<name>``,
            its pixels as they are now; a thermometer, where it measures). Without z, z stays. A
            bare ``sample`` is that of the detector, or of the only one.
        detector: Whose image; by default the first that is on, of the sample named or the only
            one.
    """
    head, _, rest = position.system.partition(":")
    sample = rest if head == "sample" and rest else None
    looking = _looking(space, detector, sample)
    values.set(space.targets(position, looking), task=task)


def set_sample_origin_here(space: SpaceManager, detector: Optional[str] = None) -> None:
    """Make where a detector looks now its sample's x and y 0.

    Args:
        detector: Whose image's middle; by default the first that is on, of the only sample.
    """
    space.origin_here(_looking(space, detector))


def register_mount(
    space: SpaceManager, matrix: list[list[float]], sample: Optional[str] = None
) -> None:
    """Say where what a sample is mounted on sits on its stage.

    Args:
        matrix: 4x4, stage micrometres to sample micrometres.
        sample: Which sample, by the cube holding it; may be left out when there is one.
    """
    space.register_mount(matrix, sample)


def mount_holder(
    space: SpaceManager,
    expanse_manager: protocols.ExpanseManager,
    holder: str,
    sample: Optional[str] = None,
) -> None:
    """Mount another holder: a new sample, where the description says it sits.

    The images taken were of what was mounted before: that sample's leave the expanse.

    Args:
        holder: One of the holders the description names for the sample.
        sample: Which sample, by the cube holding it; may be left out when there is one.
    """
    on = space.one_sample(sample)
    space.mount_holder(holder, on)
    expanse_manager.forget_sample(on)
