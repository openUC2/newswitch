"""Tests of the backend's logging: levels, log file, console loggers and libraries.

The autouse fixture `log_dir` (conftest) points relative log files and ``sys_config.yaml`` at a
folder of the test's own and undoes what `configure_logging` changed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from newswitch import logging_setup
from newswitch.logging_setup import (
    UVICORN_LOGGERS,
    configure_logging,
    console,
    log_file,
    log_prints,
    route_to_root,
    setup_logging,
)


def _flush() -> None:
    for handler in (*logging_setup._installed, *logging_setup._console_installed):
        handler.flush()


def test_each_output_has_its_own_level(log_dir: Path, capsys: pytest.CaptureFixture) -> None:
    """``info`` keeps debug records off the terminal, while the file takes them."""
    configure_logging("info", "debug", "out.log")
    log = logging.getLogger("test.levels")
    log.debug("debug record")
    log.info("info record")
    _flush()

    terminal = capsys.readouterr().err
    assert "info record" in terminal
    assert "debug record" not in terminal
    written = (log_dir / "out.log").read_text(encoding="utf-8")
    assert "debug record" in written
    assert "INFO     test.levels: info record" in written


def test_levels_filter_upwards(log_dir: Path, capsys: pytest.CaptureFixture) -> None:
    """``warn`` and ``fatal`` let only records of that level and above through."""
    configure_logging("warn", "fatal", "out.log")
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
    written = (log_dir / "out.log").read_text(encoding="utf-8")
    assert "error record" not in written
    assert "critical record" in written


def test_none_writes_nothing(log_dir: Path, capsys: pytest.CaptureFixture) -> None:
    """``none`` for both: no terminal output, no file."""
    configure_logging("none", "none", "out.log")
    logging.getLogger("test.none").error("an error")
    _flush()

    assert capsys.readouterr().err == ""
    assert list(log_dir.iterdir()) == []


def test_relative_paths_start_at_the_log_dir(log_dir: Path) -> None:
    """A relative log file is taken relative to backend/ (`LOG_DIR`), not the working directory."""
    configure_logging("none", "debug", "sub.log")
    assert log_file() == log_dir / "sub.log"


@pytest.mark.parametrize("file_path", [None, "", "  "])
def test_missing_path_falls_back(log_dir: Path, file_path: str | None) -> None:
    """Without a path the log goes to backend.log in backend/, with a warning."""
    configure_logging("none", "debug", file_path)
    logging.getLogger("test.fallback").info("after the fallback")
    _flush()

    written = (log_dir / "backend.log").read_text(encoding="utf-8")
    assert "WARNING" in written
    assert "no log_file_path given" in written
    assert "after the fallback" in written


@pytest.mark.parametrize("file_path", ["missing/out.log", "."])
def test_unusable_path_falls_back(log_dir: Path, file_path: str) -> None:
    """A path in a missing folder, or a folder, falls back; no folder is created."""
    configure_logging("none", "info", file_path)
    _flush()

    written = (log_dir / "backend.log").read_text(encoding="utf-8")
    assert f"log_file_path '{file_path}' cannot be used" in written
    assert not (log_dir / "missing").exists()


@pytest.mark.parametrize(
    ("file_level", "file_path", "expected"),
    [
        ("debug", "out.log", "out.log"),
        ("debug", "missing/out.log", "backend.log"),
        ("none", "out.log", None),
    ],
)
def test_log_file_names_the_file_written(
    log_dir: Path, file_level: str, file_path: str, expected: str | None
) -> None:
    """`log_file` gives the absolute path actually written, after a fallback too."""
    configure_logging("none", file_level, file_path)  # type: ignore[arg-type]
    assert log_file() == (log_dir / expected if expected else None)


def test_the_file_is_appended_and_rotated(log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A restart appends; a full file is rotated to backend.log.1."""
    target = log_dir / "backend.log"
    target.write_text("from the last run\n", encoding="utf-8")
    configure_logging("none", "info", "backend.log")
    assert target.read_text(encoding="utf-8").startswith("from the last run\n")

    monkeypatch.setattr(logging_setup, "MAX_LOG_FILE_BYTES", 500)
    configure_logging("none", "info", "backend.log")
    log = logging.getLogger("test.rotation")
    for index in range(20):
        log.info("line %d of the rotation test", index)
    _flush()

    assert (log_dir / "backend.log.1").is_file()
    assert not (log_dir / "backend.log.4").exists()


def test_a_second_call_replaces_the_handlers(log_dir: Path) -> None:
    """Calling it again neither duplicates records nor keeps the old file."""
    configure_logging("none", "info", "first.log")
    configure_logging("none", "info", "second.log")
    logging.getLogger("test.again").info("once")
    console("tool").info("result once")
    _flush()

    second = (log_dir / "second.log").read_text(encoding="utf-8")
    assert second.count("once") == 2  # the record and the console's result, each once
    assert "once" not in (log_dir / "first.log").read_text(encoding="utf-8")
    assert len(logging.getLogger(logging_setup.CONSOLE).handlers) == 2


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


# --- the console loggers: what a command-line tool reports


def test_console_results_go_to_stdout_and_problems_to_stderr(
    log_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """The bare message: results to stdout, problems to stderr, each once; both into the file."""
    configure_logging("info", "debug", "out.log")
    report = console("tool")
    report.info("node\tkind")
    report.error("No such user: %s", "bob")
    logging.getLogger("test.diagnostic").info("what the tool did")
    _flush()

    captured = capsys.readouterr()
    assert captured.out == "node\tkind\n"
    assert captured.err.count("No such user: bob") == 1
    assert "No such user: bob\n" in captured.err
    assert "INFO     test.diagnostic: what the tool did" in captured.err
    written = (log_dir / "out.log").read_text(encoding="utf-8")
    assert "INFO     newswitch.console.tool: node\tkind" in written
    assert "ERROR    newswitch.console.tool: No such user: bob" in written


def test_console_writes_whatever_the_terminal_level(capsys: pytest.CaptureFixture) -> None:
    """A tool's result is its output: written with ``none`` for the terminal and the file too."""
    configure_logging("none", "none", None)
    console("tool").info("the result")
    _flush()

    assert capsys.readouterr().out == "the result\n"


# --- libraries: handed a logger, or logging to one of their own


def test_library_loggers_reach_the_file(log_dir: Path, capsys: pytest.CaptureFixture) -> None:
    """A library's own logger, and a logger of the newswitch tree handed to it, follow the levels."""
    configure_logging("warn", "debug", "out.log")
    logging.getLogger("uc2_cam_py").debug("from the package logger")
    logging.getLogger("newswitch.camera.cam").info("from a camera")
    _flush()

    written = (log_dir / "out.log").read_text(encoding="utf-8")
    assert "DEBUG    uc2_cam_py: from the package logger" in written
    assert "INFO     newswitch.camera.cam: from a camera" in written
    assert capsys.readouterr().err == ""


def test_uc2_cam_py_takes_a_logger_of_the_newswitch_tree(log_dir: Path) -> None:
    """What uc2_cam_py says through the logger it is handed (as `uc2_detector` does) lands here."""
    uc2_logging = pytest.importorskip("uc2_cam_py._logging")
    configure_logging("none", "debug", "out.log")
    adapter = uc2_logging.LoggerAdapter(logging.getLogger("newswitch.camera.cam"))
    adapter.log(logging.WARNING, "frame dropped")
    _flush()

    assert "WARNING  newswitch.camera.cam: frame dropped" in (log_dir / "out.log").read_text(
        encoding="utf-8"
    )


# --- setup_logging: what the entry points call


def test_setup_logging_reads_sys_config(log_dir: Path, capsys: pytest.CaptureFixture) -> None:
    """Levels and file come from sys_config.yaml (here: warn, debug, the test's log folder)."""
    setup_logging()
    logging.getLogger("test.setup").info("only in the file")
    _flush()

    assert log_file() == log_dir / "backend.log"
    assert capsys.readouterr().err == ""
    assert "only in the file" in (log_dir / "backend.log").read_text(encoding="utf-8")


def test_setup_logging_terminal_overrides_only_the_terminal(
    log_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """``terminal="info"`` (``--verbose``) shows INFO on the terminal; the file keeps its level."""
    setup_logging(terminal="info")
    logging.getLogger("test.verbose").info("now on the terminal")
    logging.getLogger("test.verbose").debug("still only in the file")
    _flush()

    terminal = capsys.readouterr().err
    assert "now on the terminal" in terminal
    assert "still only in the file" not in terminal
    assert "still only in the file" in (log_dir / "backend.log").read_text(encoding="utf-8")
