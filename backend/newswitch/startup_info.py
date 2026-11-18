"""What `newswitch.app.main` prints to the terminal: the files in use, the URLs, how to stop.

Printed to stdout whatever ``log_to_terminal`` says, so it shows even when the terminal gets
no log records. Only `newswitch.app.main` (``uv run main.py``, the container) prints it;
``uvicorn main:app`` (``just dev``) does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from newswitch.routes.http.frontend import FRONTEND_PATH

if TYPE_CHECKING:
    from newswitch.app import ImswitchConfig

#: Bind addresses meaning "every interface"; the browser on this machine uses localhost.
_ANY_HOST = ("", "0.0.0.0", "::")

STOPPED_MESSAGE = "newswitch backend stopped"
FORCED_STOP_MESSAGE = (
    "newswitch backend stopped by a second Ctrl+C: the shutdown hooks may not have run "
    "(device configuration not saved, cameras not closed)"
)


def starting_message(config: ImswitchConfig, base_config: Path, log_path: Path | None) -> str:
    """The files the backend reads and writes, printed before the hardware starts.

    Args:
        config: The settings the backend runs with.
        base_config: The base settings file they were read from.
        log_path: The log file actually written (`logging_setup.log_file`), None for none.
    """
    mode = "virtual" if config.use_virtual_microscope else "hardware"
    rows: list[tuple[str, str]] = [("base config", str(base_config.resolve()))]
    files = config.device_config_files()
    if files is None:
        rows.append(("device config", "none (built-in virtual devices)"))
    else:
        static, persistent, from_static = files
        if from_static:
            rows.append(("device config", str(static.resolve())))
        elif persistent.exists():
            rows.append(("device config", str(persistent.resolve())))
        else:
            rows.append(
                (
                    "device config",
                    f"{persistent.resolve()} (first start: copied from {static.resolve()})",
                )
            )
        rows.append(("saved on exit to", str(persistent.resolve())))
    levels = f"(file: {config.log_to_file}, terminal: {config.log_to_terminal})"
    rows.append(("log file", f"{log_path if log_path else 'none'}  {levels}"))
    return _block(f"newswitch backend starting (mode: {mode})", rows)


def ready_message(
    host: str, port: int, pid: int, frontend_served: bool, frontend_port: int | str
) -> str:
    """Where to point the browser and how to stop, printed once the backend listens.

    Args:
        host: The address uvicorn binds to.
        port: The port uvicorn listens on.
        pid: The process id, for stopping from another terminal.
        frontend_served: The backend serves the built frontend (``NEWSWITCH_FRONTEND_DIR``).
        frontend_port: Port of the Vite dev server (``FRONTEND_PORT``), used otherwise.
    """
    backend = f"http://{_browser_host(host)}:{port}"
    if frontend_served:
        frontend = f"{backend}{FRONTEND_PATH}/"
    else:
        frontend = (
            "not served by this process: start it with `just dev-frontend`,\n"
            f"then open http://localhost:{frontend_port}"
        )
    rows = [
        ("frontend", frontend),
        ("backend", f"{backend}   (health: {backend}/health)"),
        (
            "stop",
            f'press Ctrl+C once and wait for "{STOPPED_MESSAGE}"\n'
            "(saves the device configuration, closes the cameras);\n"
            "a second Ctrl+C aborts without saving. Same as Ctrl+C: "
            f"kill {pid}",
        ),
    ]
    return _block(f"newswitch backend ready (pid {pid})", rows)


def announce(text: str) -> None:
    """Print `text` to the terminal at once, also when stdout is a pipe (docker logs)."""
    print(text, flush=True)


def _browser_host(host: str) -> str:
    """The host part of a URL for `host` as a browser on this machine reaches it."""
    if host in _ANY_HOST:
        return "localhost"
    return f"[{host}]" if ":" in host else host


def _block(title: str, rows: list[tuple[str, str]]) -> str:
    """`title`, then one aligned row per (label, value); a value may span several lines."""
    width = max(len(label) for label, _ in rows)
    lines = [title]
    for label, value in rows:
        first, *more = value.splitlines()
        lines.append(f"  {label:<{width}}  {first}")
        lines.extend(f"  {'':<{width}}  {line}" for line in more)
    return "\n".join(lines)
