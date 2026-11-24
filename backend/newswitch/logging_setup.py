"""Logging of the backend: one level for the terminal, one for the log file, and no print.

The levels and the file come from ``backend/sys_config.yaml`` (``log_to_terminal``,
``log_to_file``, ``log_file_path``; `newswitch.sys_config`). `setup_logging` reads it and calls
`configure_logging`. The entry points call it (``main_fastapi.create``, ``app.main`` and the
command-line tools), never `main_fastapi.create_app`, so tests write no log files.

Nothing in the backend prints. A module logs through ``logging.getLogger(__name__)``; what a
command-line tool reports as its result goes through `console`, which writes the bare message to
stdout (warnings and errors to stderr), whatever ``log_to_terminal`` says, and into the log file
like every other record.

Libraries: one that logs to a logger of its own name and attaches no handler, or that is handed a
logger of the ``newswitch`` tree, follows these levels and this file without anything else to do.
uc2_cam_py is such a library: `newswitch.drivers.uc2.uc2_detector` hands each camera
``logging.getLogger("newswitch.camera.<name>")``, which also gets what its C++ core says, and its
own logger ``uc2_cam_py`` has no handler. A library that attaches handlers of its own bypasses the
levels; `route_to_root` takes them away (uvicorn, uc2rest). `log_prints` turns what a library
prints into log records.

Not covered: what arkitekt's own command line (``arkitekt run ...``) sets up, uvicorn's reloader
process under ``--reload``, warnings raised while the backend is imported (before this file is
read), prints of libraries outside `log_prints`, native output.
"""

from __future__ import annotations

import contextlib
import io
import logging
import logging.handlers
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from newswitch.settings import BACKEND_DIR

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

#: Where a relative log file goes, and the fallback file with it.
LOG_DIR = BACKEND_DIR
#: Log file used when ``log_file_path`` is missing or cannot be opened; in `LOG_DIR`.
DEFAULT_LOG_FILE = "backend.log"
#: The log file is rotated at this size; this many old ones are kept (backend.log.1, ...).
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUPS = 3

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

#: uvicorn attaches handlers of its own to these loggers.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

#: The loggers of `console`: the results of the command-line tools.
CONSOLE = "newswitch.console"

#: Handlers installed by `configure_logging` on the root logger; a second call replaces them.
_installed: list[logging.Handler] = []
#: Handlers installed by `configure_logging` on `CONSOLE`; a second call replaces them.
_console_installed: list[logging.Handler] = []


def console(name: str) -> logging.Logger:
    """The logger a command-line tool reports its result through, e.g. ``console("uc2")``.

    Once `configure_logging` ran, its INFO records are written to stdout and its WARNING and
    above to stderr, as the bare message, whatever ``log_to_terminal`` says. They reach the log
    file too, but not the terminal a second time.
    """
    return logging.getLogger(f"{CONSOLE}.{name}")


def setup_logging(*, terminal: LogLevel | None = None) -> None:
    """Configure logging as ``sys_config.yaml`` says; `terminal` overrides ``log_to_terminal``.

    Raises:
        SysConfigError: ``sys_config.yaml`` is missing or invalid.
    """
    from newswitch.sys_config import load_sys_config

    config = load_sys_config()
    configure_logging(
        terminal if terminal is not None else config.log_to_terminal,
        config.log_to_file,
        config.log_file_path,
    )


def configure_logging(terminal: LogLevel, file: LogLevel, file_path: str | Path | None) -> None:
    """Write log records to stderr and to a rotating log file, each from its own level up.

    Calling it again replaces the handlers of the previous call; handlers installed by
    others on the root logger stay. uvicorn's loggers lose their own handlers, so their
    records follow these levels too. Warnings of the `warnings` module become log records.
    The `console` loggers always write to stdout and stderr.

    Args:
        terminal: Lowest level written to stderr.
        file: Lowest level written to the log file.
        file_path: The log file, relative to `LOG_DIR`. If it is missing or cannot be opened
            for appending, `DEFAULT_LOG_FILE` is used and a warning logged.
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
        # The console loggers write to the terminal themselves
        stream_handler.addFilter(_not_console)
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

    _configure_console()

    route_to_root(*UVICORN_LOGGERS)
    for name in UVICORN_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    logging.captureWarnings(True)

    for level, message in problems:
        logger.log(level, "%s", message)


def log_file() -> Path | None:
    """The log file `configure_logging` writes to, including its fallback.

    Returns:
        The absolute path, or None if no log file is written (``none``, or not openable).
    """
    for handler in _installed:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None


def _not_console(record: logging.LogRecord) -> bool:
    """Whether a record is not one of a `console` logger."""
    return record.name != CONSOLE and not record.name.startswith(CONSOLE + ".")


def _below_warning(record: logging.LogRecord) -> bool:
    """Whether a record is below WARNING: what a console logger writes to stdout."""
    return record.levelno < logging.WARNING


def _configure_console() -> None:
    """Give the `console` loggers their own stdout and stderr, as the bare message."""
    console_logger = logging.getLogger(CONSOLE)
    for handler in _console_installed:
        console_logger.removeHandler(handler)
        handler.close()
    _console_installed.clear()

    results = logging.StreamHandler(sys.stdout)
    results.addFilter(_below_warning)
    problems = logging.StreamHandler(sys.stderr)
    problems.setLevel(logging.WARNING)
    for handler in (results, problems):
        handler.setFormatter(logging.Formatter("%(message)s"))
        console_logger.addHandler(handler)
        _console_installed.append(handler)
    # A tool's result is written whatever the root logger's level is; the log file has its own
    console_logger.setLevel(logging.INFO)
    console_logger.propagate = True


def _open_log_file(
    file_path: str | Path | None, problems: list[tuple[int, str]]
) -> logging.Handler | None:
    """Open `file_path` for appending, falling back to `DEFAULT_LOG_FILE`.

    Args:
        file_path: The configured log file, relative to `LOG_DIR`.
        problems: Receives a (level, message) for every fallback taken.

    Returns:
        The handler, or None if not even `DEFAULT_LOG_FILE` can be opened.
    """
    fallback = LOG_DIR / DEFAULT_LOG_FILE
    if file_path is not None and str(file_path).strip():
        path = Path(file_path)
        try:
            return _rotating_file_handler(path if path.is_absolute() else LOG_DIR / path)
        except OSError as exc:
            message = (
                f"log_file_path {str(file_path)!r} cannot be used ({exc}); logging to {fallback}"
            )
            problems.append((logging.WARNING, message))
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
