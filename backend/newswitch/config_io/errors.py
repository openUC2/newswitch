"""Errors and warnings raised while reading or writing ``newswitch-config.yaml``."""

from __future__ import annotations


class ConfigError(ValueError):
    """Raised when the configuration file cannot be read or does not validate.

    Carries every problem found, not only the first one, so a broken file can be fixed
    in a single pass.
    """

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        """Build the error.

        Args:
            message: Summary line, usually naming the file.
            problems: Individual findings, one per entry, each prefixed with its path.
        """
        self.problems: list[str] = list(problems or [])
        if self.problems:
            message = message + "\n  - " + "\n  - ".join(self.problems)
        super().__init__(message)


class ConfigWarning(UserWarning):
    """Issued for recoverable problems, e.g. a unit that cannot be converted."""
