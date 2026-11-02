"""The routes ``main_fastapi.py`` serves beside the agent: live view, files, cache."""

from typing import TypeVar

from fastapi import HTTPException
from starlette.requests import HTTPConnection

T = TypeVar("T")


def running_context(connection: HTTPConnection, cls: type[T]) -> T:
    """The context of the running agent that is a `cls` (for a request or a websocket).

    Raises:
        HTTPException: 503 until the agent has started and provided it.
    """
    agent = getattr(connection.app.state, "agent", None)
    contexts = getattr(agent, "contexts", None) or {}
    for context in contexts.values():
        if isinstance(context, cls):
            return context
    raise HTTPException(status_code=503, detail="The microscope is not started yet")
