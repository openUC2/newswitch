"""Tests for `newswitch.startup_info`: the overview `uv run main.py` prints."""

from __future__ import annotations

from pathlib import Path

import pytest

from newswitch.app import ImswitchConfig
from newswitch.startup_info import STOPPED_MESSAGE, ready_message, starting_message


def _config(tmp_path: Path, **values: object) -> ImswitchConfig:
    """Settings with the device files in `tmp_path`; `values` override single ones."""
    return ImswitchConfig(
        **{
            "use_virtual_microscope": False,
            "static_config_path": tmp_path / "static.yaml",
            "persistent_config_path": tmp_path / "static.persistent.yaml",
            "load_from_static_config_path": True,
            "log_to_terminal": "warn",
            "log_to_file": "debug",
            **values,
        }
    )


def _row(text: str, label: str) -> str:
    """The value of the row `label` in `text` (its first line)."""
    for line in text.splitlines():
        if line.strip().startswith(label + "  "):
            return line.strip()[len(label) :].strip()
    raise AssertionError(f"no row {label!r} in:\n{text}")


def test_starting_message_names_the_files(tmp_path: Path) -> None:
    """Base config, the device file read, the one written on exit and the log file."""
    base = tmp_path / "base_config.yaml"
    text = starting_message(_config(tmp_path), base, tmp_path / "backend.log")
    assert text.splitlines()[0] == "newswitch backend starting (mode: hardware)"
    assert _row(text, "base config") == str(base.resolve())
    assert _row(text, "device config") == str((tmp_path / "static.yaml").resolve())
    assert _row(text, "saved on exit to") == str((tmp_path / "static.persistent.yaml").resolve())
    assert _row(text, "log file") == f"{tmp_path / 'backend.log'}  (file: debug, terminal: warn)"


def test_starting_message_persistent_file(tmp_path: Path) -> None:
    """Reading the persistent file: it is named; on the first start, with its seed."""
    config = _config(tmp_path, load_from_static_config_path=False, use_virtual_microscope=True)
    persistent = (tmp_path / "static.persistent.yaml").resolve()
    first = starting_message(config, tmp_path / "base_config.yaml", None)
    assert "(mode: virtual)" in first
    assert _row(first, "device config") == (
        f"{persistent} (first start: copied from {(tmp_path / 'static.yaml').resolve()})"
    )

    persistent.write_text("newswitch_version: v1.0.2\ndevices: {}\n")
    later = starting_message(config, tmp_path / "base_config.yaml", None)
    assert _row(later, "device config") == str(persistent)


def test_starting_message_without_device_file_or_log_file(tmp_path: Path) -> None:
    """No device configuration and no log file are said as such."""
    config = _config(tmp_path, config_file=None, log_to_file="none")
    text = starting_message(config, tmp_path / "base_config.yaml", None)
    assert _row(text, "device config") == "none (built-in virtual devices)"
    assert "saved on exit to" not in text
    assert _row(text, "log file") == "none  (file: none, terminal: warn)"


def test_ready_message_says_how_to_start_and_stop(tmp_path: Path) -> None:
    """The backend URL, the command starting the frontend, its URL, and how to stop both."""
    repo = tmp_path / "repo"
    text = ready_message("0.0.0.0", 8069, 4242, frontend_port=5473, repo_root=repo)
    assert text.splitlines()[0] == "newswitch backend ready (pid 4242)"
    assert _row(text, "backend") == "http://localhost:8069   (health: http://localhost:8069/health)"
    assert _row(text, "frontend") == "start it now in a second terminal:"
    assert f"cd {repo.resolve()} && just dev-frontend" in text
    assert "then open http://localhost:5473 in the browser" in text
    assert _row(text, "stop") == "frontend: Ctrl+C in its terminal"
    assert f'backend:  Ctrl+C here, once, and wait for "{STOPPED_MESSAGE}"' in text
    assert "a second Ctrl+C aborts without saving. Same as Ctrl+C: kill 4242" in text


def test_ready_message_quotes_the_repository_path(tmp_path: Path) -> None:
    """A path with a space stays one argument of `cd`, so the line can be pasted as it is."""
    repo = tmp_path / "my repo"
    text = ready_message("0.0.0.0", 8069, 1, frontend_port=5473, repo_root=repo)
    assert f"cd '{repo.resolve()}' && just dev-frontend" in text


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("::", "http://localhost:8069"),
        ("127.0.0.1", "http://127.0.0.1:8069"),
        ("::1", "http://[::1]:8069"),
    ],
)
def test_ready_message_url_of_the_bind_address(host: str, url: str) -> None:
    """Every-interface addresses become localhost; a concrete one is kept, IPv6 bracketed."""
    text = ready_message(host, 8069, 1, frontend_port=5473, repo_root=Path("/repo"))
    assert _row(text, "backend").startswith(url + " ")
