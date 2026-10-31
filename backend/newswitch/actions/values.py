"""What can change, and the one way of changing each: by what it does, in the description's names."""

from typing import Optional

from arkitekt import Task

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
    name: str,
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


def swap(values: Values, name: str, slot: int) -> None:
    """Put another thing in place.

    Args:
        name: The variable: ``objective.slot``.
        slot: What to put in place.
    """
    values.set({name: slot})


def tune(values: Values, name: str, to: float) -> None:
    """Change a value of an element.

    Args:
        name: The variable: ``laser_488.power``.
        to: To what, in its unit.
    """
    values.set({name: to})
