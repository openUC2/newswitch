"""Finding a context of the running agent from a route."""

from typing import Any, Optional, TypeVar

T = TypeVar("T")


def context_of_type(agent: Any, cls: type[T]) -> Optional[T]:  # noqa: ANN401 - FastApiAgent
    """The first context the agent holds that is an instance of ``cls``, or None.

    The agent keeps contexts by name; routes know them by their (protocol) class.
    """
    return next((value for value in agent.contexts.values() if isinstance(value, cls)), None)
