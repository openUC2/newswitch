"""The IO state: the last file written."""

from dataclasses import dataclass


@dataclass
class IOState:
    """Shared state for IO operations."""

    last_saved_file: str | None = None
