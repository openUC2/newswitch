"""Tests of ``backend/sys_config.yaml``, the backend's global settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from newswitch.settings import BACKEND_DIR
from newswitch.sys_config import SysConfigError, load_sys_config

#: The committed file (the autouse fixture `log_dir` points `SYS_CONFIG_FILE` at a copy).
COMMITTED = BACKEND_DIR / "sys_config.yaml"

VALID = "log_to_terminal: warn\nlog_to_file: debug\nlog_file_path: backend.log\n"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "sys_config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_committed_file_loads() -> None:
    """The committed sys_config.yaml is valid, and its log file is in backend/."""
    config = load_sys_config(COMMITTED)
    assert config.log_to_terminal == "warn"
    assert config.log_to_file == "debug"
    assert config.log_file_path == BACKEND_DIR / "backend.log"


def test_load_reads_the_configured_file(log_dir: Path) -> None:
    """Without an argument, `SYS_CONFIG_FILE` is read (in tests: the copy with the test's folder)."""
    assert load_sys_config().log_file_path == log_dir / "backend.log"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("logs/newswitch.log", BACKEND_DIR / "logs" / "newswitch.log"),
        ("/var/log/newswitch.log", Path("/var/log/newswitch.log")),
        ("null", None),
        ("''", None),
    ],
)
def test_log_file_path_is_relative_to_backend(
    tmp_path: Path, value: str, expected: Path | None
) -> None:
    """A relative path starts at backend/, an absolute one stays, an empty one is none."""
    text = VALID.replace("log_file_path: backend.log", f"log_file_path: {value}")
    assert load_sys_config(_write(tmp_path, text)).log_file_path == expected


def test_an_unknown_key_is_refused(tmp_path: Path) -> None:
    """A misspelled or obsolete key is an error that names it, not ignored."""
    with pytest.raises(SysConfigError, match="db_path"):
        load_sys_config(_write(tmp_path, VALID + "db_path: agent_data.db\n"))


def test_a_missing_key_is_refused(tmp_path: Path) -> None:
    """Every key must be there."""
    with pytest.raises(SysConfigError, match="log_to_file"):
        load_sys_config(_write(tmp_path, VALID.replace("log_to_file: debug\n", "")))


def test_an_unknown_level_is_refused(tmp_path: Path) -> None:
    """Only fatal, error, warn, info, debug and none are levels."""
    with pytest.raises(SysConfigError, match="log_to_terminal"):
        load_sys_config(_write(tmp_path, VALID.replace("warn", "verbose")))


def test_an_empty_file_names_every_key(tmp_path: Path) -> None:
    """An empty file lacks all three keys, and says so."""
    with pytest.raises(SysConfigError) as raised:
        load_sys_config(_write(tmp_path, ""))
    for key in ("log_to_terminal", "log_to_file", "log_file_path"):
        assert key in str(raised.value)


def test_a_missing_file_is_named(tmp_path: Path) -> None:
    """Without the file nothing starts, and the error says which file."""
    missing = tmp_path / "nowhere" / "sys_config.yaml"
    with pytest.raises(SysConfigError, match="nowhere"):
        load_sys_config(missing)
