"""Tests for `newswitch.logging_setup`: levels per output, the log file and its fallback."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from newswitch import logging_setup
from newswitch.logging_setup import (
    UVICORN_LOGGERS,
    configure_logging,
    log_prints,
    route_to_root,
)


@pytest.fixture(autouse=True)
def restore_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Run each test in a temporary folder and undo what `configure_logging` changed.

    Only the handlers `configure_logging` installed are removed: pytest attaches handlers of
    its own to the root logger and removes them itself.
    """
    monkeypatch.chdir(tmp_path)
    root = logging.getLogger()
    root_level = root.level
    uvicorn = {
        name: (list(logging.getLogger(name).handlers), logging.getLogger(name).level)
        for name in UVICORN_LOGGERS
    }
    uvicorn_propagate = {name: logging.getLogger(name).propagate for name in UVICORN_LOGGERS}
    yield
    for handler in logging_setup._installed:
        root.removeHandler(handler)
        handler.close()
    logging_setup._installed.clear()
    root.setLevel(root_level)
    logging.captureWarnings(False)
    for name, (handlers, level) in uvicorn.items():
        library_logger = logging.getLogger(name)
        library_logger.handlers[:] = handlers
        library_logger.setLevel(level)
        library_logger.propagate = uvicorn_propagate[name]


def _flush() -> None:
    for handler in logging_setup._installed:
        handler.flush()


def test_each_output_has_its_own_level(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """``info`` keeps debug records off the terminal, while the file takes them."""
    log_file = tmp_path / "out.log"
    configure_logging("info", "debug", str(log_file))
    log = logging.getLogger("test.levels")
    log.debug("debug record")
    log.info("info record")
    _flush()

    terminal = capsys.readouterr().err
    assert "info record" in terminal
    assert "debug record" not in terminal
    written = log_file.read_text(encoding="utf-8")
    assert "debug record" in written
    assert "INFO     test.levels: info record" in written


def test_levels_filter_upwards(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """``warn`` and ``fatal`` let only records of that level and above through."""
    log_file = tmp_path / "out.log"
    configure_logging("warn", "fatal", str(log_file))
    log = logging.getLogger("test.upwards")
    log.info("info record")
    log.warning("warning record")
    log.error("error record")
    log.critical("critical record")
    _flush()

    terminal = capsys.readouterr().err
    assert "info record" not in terminal
    assert "warning record" in terminal
    assert "error record" in terminal
    written = log_file.read_text(encoding="utf-8")
    assert "error record" not in written
    assert "critical record" in written


def test_none_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """``none`` for both: no terminal output, no file."""
    configure_logging("none", "none", "out.log")
    logging.getLogger("test.none").error("an error")
    _flush()

    assert capsys.readouterr().err == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("file_path", [None, "", "  "])
def test_missing_path_falls_back(tmp_path: Path, file_path: str | None) -> None:
    """Without a path the log goes to backend.log in the working directory, with a warning."""
    configure_logging("none", "debug", file_path)
    logging.getLogger("test.fallback").info("after the fallback")
    _flush()

    written = (tmp_path / "backend.log").read_text(encoding="utf-8")
    assert "WARNING" in written
    assert "no log_file_path given" in written
    assert "after the fallback" in written


@pytest.mark.parametrize("file_path", ["missing/out.log", "."])
def test_unusable_path_falls_back(tmp_path: Path, file_path: str) -> None:
    """A path in a missing folder, or a folder, falls back; no folder is created."""
    configure_logging("none", "info", file_path)
    _flush()

    written = (tmp_path / "backend.log").read_text(encoding="utf-8")
    assert f"log_file_path '{file_path}' cannot be used" in written
    assert not (tmp_path / "missing").exists()


def test_the_file_is_appended_and_rotated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A restart appends; a full file is rotated to backend.log.1."""
    log_file = tmp_path / "backend.log"
    log_file.write_text("from the last run\n", encoding="utf-8")
    configure_logging("none", "info", "backend.log")
    assert log_file.read_text(encoding="utf-8").startswith("from the last run\n")

    monkeypatch.setattr(logging_setup, "MAX_LOG_FILE_BYTES", 500)
    configure_logging("none", "info", "backend.log")
    log = logging.getLogger("test.rotation")
    for index in range(20):
        log.info("line %d of the rotation test", index)
    _flush()

    assert (tmp_path / "backend.log.1").is_file()
    assert not (tmp_path / "backend.log.4").exists()


def test_a_second_call_replaces_the_handlers(tmp_path: Path) -> None:
    """Calling it again neither duplicates records nor keeps the old file."""
    configure_logging("none", "info", "first.log")
    configure_logging("none", "info", "second.log")
    logging.getLogger("test.again").info("once")
    _flush()

    assert (tmp_path / "second.log").read_text(encoding="utf-8").count("once") == 1
    assert "once" not in (tmp_path / "first.log").read_text(encoding="utf-8")


def test_uvicorn_loses_its_own_handlers() -> None:
    """uvicorn's loggers propagate to the root logger, without handlers or levels of their own."""
    access = logging.getLogger("uvicorn.access")
    access.addHandler(logging.StreamHandler())
    access.propagate = False
    access.setLevel(logging.INFO)

    configure_logging("none", "none", None)

    for name in UVICORN_LOGGERS:
        library_logger = logging.getLogger(name)
        assert library_logger.handlers == []
        assert library_logger.propagate is True
        assert library_logger.level == logging.NOTSET


def test_route_to_root() -> None:
    """A library logger's own handlers are taken away and it propagates again."""
    library_logger = logging.getLogger("test.library")
    library_logger.addHandler(logging.StreamHandler())
    library_logger.propagate = False

    route_to_root("test.library")

    assert library_logger.handlers == []
    assert library_logger.propagate is True


def test_log_prints(caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture) -> None:
    """Every non-empty printed line becomes a record; nothing reaches stdout."""
    caplog.set_level(logging.DEBUG, logger="test.prints")
    with log_prints(logging.getLogger("test.prints"), logging.DEBUG):
        print({1: [], 2: []})  # noqa: T201 - what a library would print
        print("two\nlines")  # noqa: T201

    assert [record.getMessage() for record in caplog.records] == ["{1: [], 2: []}", "two", "lines"]
    assert all(record.levelno == logging.DEBUG for record in caplog.records)
    assert capsys.readouterr().out == ""
