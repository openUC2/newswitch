"""What can change, and the one way of changing each: by what it does, in the description's names.

What an action is asked to change is chosen from what its state lists (``withStateChoices``): a
microscope without it lists nothing, and has nothing to choose.
"""

from typing import Annotated, Optional

from arkitekt import Task
from arkitekt.widgets import withStateChoices

from newswitch.services.values import Values


def move(
    values: Values,
    task: Task,
    targets: dict[str, float],
    relative: bool = False,
) -> None:
    """Move variables together: to those values, or by them.

    Args:
        targets: How far, by variable: ``{"stage.x": 10.0, "stage.y": -5.0}``.
        relative: By them, rather than to them.
    """
    values.set(targets, relative=relative, task=task)


def move_one(
    values: Values,
    task: Task,
    name: Annotated[str, withStateChoices("self.move.names")],
    to: Optional[float] = None,
    by: Optional[float] = None,
) -> None:
    """Move one variable: to a value, or by one.

    Args:
        name: The variable: ``stage.z``.
        to: Where to.
        by: How far.
    """
    if (to is None) == (by is None):
        raise ValueError(f"Say either where to move {name} or by how much")
    values.set({name: by if to is None else to}, relative=to is None, task=task)


def move_home(values: Values, task: Task) -> None:
    """Move everything that moves to where it is described to start."""
    values.set(
        {
            name: variable.initial
            for name, variable in values.instrument.variables.items()
            if variable.verb == "moves"
        },
        task=task,
    )


def swap(
    values: Values, name: Annotated[str, withStateChoices("self.swap.names")], slot: int
) -> None:
    """Put another thing in place.

    Args:
        name: The variable: ``objective.slot``.
        slot: What to put in place.
    """
    values.set({name: slot})


def tune(
    values: Values, name: Annotated[str, withStateChoices("self.tune.names")], to: float
) -> None:
    """Change a value of an element.

    Args:
        name: The variable: ``laser_488.power``.
        to: To what, in its unit.
    """
    values.set({name: to})


def home_stage(
    values: Values,
    task: Task,
    stage: Annotated[str, withStateChoices("self.move.homes")],
) -> None:
    """Home what a stage moves, one after the other: along z first, then the rest.

    Args:
        stage: The cube: ``stage``.
    """
    values.home(values.moves_of(stage), task)
    task.progress(100, "homed")


def stop_stage(
    values: Values,
    stage: Annotated[str, withStateChoices("self.move.stops")],
) -> None:
    """Stop what a stage moves, where it is. It holds no lock, so it stops a move under way.

    Args:
        stage: The cube: ``stage``.
    """
    values.stop(values.moves_of(stage))


def home_objective(
    values: Values,
    name: Annotated[str, withStateChoices("self.swap.homes")],
) -> None:
    """Home a changer, which leaves it at its first slot.

    Args:
        name: The variable: ``objective.slot``.
    """
    values.home([name])
