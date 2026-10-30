"""What is wrong with a description."""

from pydantic import ValidationError


class SpecError(ValueError):
    """The description contradicts itself, or does not say what running it needs."""


def problems_of(exc: ValidationError) -> list[str]:
    """One ``path: message (got value)`` per problem pydantic found, paths as in the file."""
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "<root>"
        given = error.get("input")
        got = f" (got {given!r})" if isinstance(given, (str, int, float, bool)) else ""
        lines.append(f"{where}: {error['msg'].removeprefix('Value error, ')}{got}")
    return lines
