"""Logging of the backend: one level for the terminal, one for the log file.

The levels and the file come from base_config.yaml (``log_to_terminal``, ``log_to_file``,
``log_file_path``). `configure_logging` is called by the entry points (``main.py``,
`newswitch.app.main`, ``backend_cli.py``), not by `create_app`, so tests write no log files.

Libraries that attach handlers of their own bypass these levels; `route_to_root` takes their
handlers away. `log_prints` turns what a library prints into log records.
"""

import contextlib
import io
import logging
import logging.handlers
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

#: Values of ``log_to_terminal`` and ``log_to_file``: records from this level up are written;
#: ``none`` writes nothing.
LogLevel = Literal["fatal", "error", "warn", "info", "debug", "none"]

LOG_LEVELS: dict[str, int | None] = {
    "fatal": logging.CRITICAL,
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "none": None,
}

#: Log file used when ``log_file_path`` is missing or cannot be opened; relative to the
#: working directory.
DEFAULT_LOG_FILE = "backend.log"
#: The log file is rotated at this size; this many old ones are kept (backend.log.1, ...).
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUPS = 3

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

#: uvicorn attaches handlers of its own to these loggers.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

#: Handlers installed by `configure_logging`; a second call replaces them.
_installed: list[logging.Handler] = []


def configure_logging(terminal: LogLevel, file: LogLevel, file_path: str | None) -> None:
    """Write log records to stderr and to a rotating log file, each from its own level up.

    Calling it again replaces the handlers of the previous call; handlers installed by
    others on the root logger stay. uvicorn's loggers lose their own handlers, so their
    records follow these levels too. Warnings of the `warnings` module become log records.

    Args:
        terminal: Lowest level written to stderr.
        file: Lowest level written to the log file.
        file_path: The log file, relative to the working directory. If it is missing or
            cannot be opened for appending, `DEFAULT_LOG_FILE` is used and a warning logged.
    """
    root = logging.getLogger()
    for handler in _installed:
        root.removeHandler(handler)
        handler.close()
    _installed.clear()

    terminal_level = LOG_LEVELS[terminal]
    file_level = LOG_LEVELS[file]

    if terminal_level is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(terminal_level)
        _installed.append(stream_handler)

    # Logged only once the handlers are in place, so they reach the terminal and the file
    problems: list[tuple[int, str]] = []
    if file_level is not None:
        file_handler = _open_log_file(file_path, problems)
        if file_handler is not None:
            file_handler.setLevel(file_level)
            _installed.append(file_handler)

    levels = [handler.level for handler in _installed]
    if not _installed:
        # Without any handler, Python's last resort would still print warnings to stderr
        _installed.append(logging.NullHandler())

    formatter = logging.Formatter(LOG_FORMAT)
    for handler in _installed:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(min(levels) if levels else logging.CRITICAL + 1)

    route_to_root(*UVICORN_LOGGERS)
    for name in UVICORN_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    logging.captureWarnings(True)

    for level, message in problems:
        logger.log(level, "%s", message)


def _open_log_file(
    file_path: str | None, problems: list[tuple[int, str]]
) -> logging.Handler | None:
    """Open `file_path` for appending, falling back to `DEFAULT_LOG_FILE`.

    Args:
        file_path: The configured log file.
        problems: Receives a (level, message) for every fallback taken.

    Returns:
        The handler, or None if not even `DEFAULT_LOG_FILE` can be opened.
    """
    fallback = Path(DEFAULT_LOG_FILE).absolute()
    if file_path and file_path.strip():
        try:
            return _rotating_file_handler(Path(file_path))
        except OSError as exc:
            problems.append(
                (
                    logging.WARNING,
                    f"log_file_path {file_path!r} cannot be used ({exc}); logging to {fallback}",
                )
            )
    else:
        problems.append((logging.WARNING, f"no log_file_path given; logging to {fallback}"))
    try:
        return _rotating_file_handler(fallback)
    except OSError as exc:
        problems.append((logging.ERROR, f"cannot open {fallback} ({exc}); no log file is written"))
        return None


def _rotating_file_handler(path: Path) -> logging.Handler:
    """A handler appending to `path`, rotated at `MAX_LOG_FILE_BYTES`.

    Raises:
        OSError: The file cannot be opened (missing folder, a folder, no permission).
    """
    return logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_LOG_FILE_BYTES, backupCount=LOG_FILE_BACKUPS, encoding="utf-8"
    )


def route_to_root(*names: str) -> None:
    """Take away the handlers of these loggers, so their records go through the root logger.

    For libraries that attach handlers of their own (uvicorn, uc2rest), which would write
    regardless of the levels set by `configure_logging`.
    """
    for name in names:
        library_logger = logging.getLogger(name)
        for handler in list(library_logger.handlers):
            library_logger.removeHandler(handler)
        library_logger.propagate = True


class _PrintsToLog(io.TextIOBase):
    """Text stream that logs every non-empty line written to it."""

    def __init__(self, target: logging.Logger, level: int) -> None:
        """Log to `target` at `level`."""
        self._target = target
        self._level = level

    def write(self, text: str) -> int:
        """Log each non-empty line of `text`."""
        for line in text.splitlines():
            if line.strip():
                self._target.log(self._level, "%s", line)
        return len(text)


@contextlib.contextmanager
def log_prints(target: logging.Logger, level: int) -> Iterator[None]:
    """Log what is printed inside the block instead of writing it to stdout.

    `sys.stdout` is replaced for the whole process while the block runs, so prints of other
    threads land in the log as well.
    """
    with contextlib.redirect_stdout(_PrintsToLog(target, level)):
        yield
