"""Pytest configuration and shared fixtures for newswitch tests.

The microscope the tests run on is the complete reference microscope
(`newswitch.reference.REFERENCE_INSTRUMENT`: every part), simulated, with every folder
under the test's ``tmp_path``:

- `settings`: the settings of such a run;
- `microscope`: its parts, built (`newswitch.microscope.parts.build_microscope`): managers and
  states wired exactly as the app wires them, no hand-wiring;
- `registry_names`: what newswitch registers (states, actions), the same on every microscope;
- `virtual_microscope_app`: the full FastAPI app, for tests that talk to the agent.
"""

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from arkitekt_fastapi.testing import AsyncAgentTestClient, BufferedEvent
from fastapi import FastAPI

from main_fastapi import create_app, create_fastapi_registry
from newswitch import logging_setup, sys_config
from newswitch.infra.accounts.auth import AllowAllAuthenticator
from newswitch.instrument import spec
from newswitch.settings import Settings
from newswitch.models.acquisition import (
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    AcquisitionStack,
)
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.reference import REFERENCE_INSTRUMENT

#: The smallest microscope: one simulated camera, nothing else. For tests that need a run of some
#: instrument, and nothing of it in particular (auth, accounts, routes).
CAM_TEST = Path(__file__).parent.parent / "instruments" / "cam-test"


@pytest.fixture(autouse=True)
def views_beside_copies(tmp_path: Path) -> None:
    """A description names its views relative to itself, so copies of one keep them in reach."""
    for folder in (tmp_path, tmp_path.parent):
        link = folder / "views"
        if not link.exists():
            link.symlink_to(Path(__file__).parent.parent / "instruments" / "views")


@pytest.fixture(autouse=True)
def log_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Path]:
    """Logging into a folder of the test's own, undone afterwards: no test writes backend.log.

    `sys_config.SYS_CONFIG_FILE` is a copy of the committed ``sys_config.yaml`` whose log file is
    in that folder, and relative log files (the fallback included) go there too. Afterwards only
    what `configure_logging` installed is removed: pytest attaches handlers of its own to the
    root logger and removes them itself.
    """
    folder = tmp_path_factory.mktemp("log")
    config = yaml.safe_load(sys_config.SYS_CONFIG_FILE.read_text(encoding="utf-8"))
    config["log_file_path"] = str(folder / "backend.log")
    copy = tmp_path_factory.mktemp("sys_config") / "sys_config.yaml"
    copy.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(sys_config, "SYS_CONFIG_FILE", copy)
    monkeypatch.setattr(logging_setup, "LOG_DIR", folder)

    root = logging.getLogger()
    root_level = root.level
    library_names = (*logging_setup.UVICORN_LOGGERS, logging_setup.CONSOLE)
    libraries = {
        name: (list(lg.handlers), lg.level, lg.propagate)
        for name, lg in ((name, logging.getLogger(name)) for name in library_names)
    }
    yield folder
    for handler in logging_setup._installed:
        root.removeHandler(handler)
        handler.close()
    logging_setup._installed.clear()
    console = logging.getLogger(logging_setup.CONSOLE)
    for handler in logging_setup._console_installed:
        console.removeHandler(handler)
        handler.close()
    logging_setup._console_installed.clear()
    root.setLevel(root_level)
    logging.captureWarnings(False)
    for name, (handlers, level, propagate) in libraries.items():
        library_logger = logging.getLogger(name)
        library_logger.handlers[:] = handlers
        library_logger.setLevel(level)
        library_logger.propagate = propagate


def wired_only(data: dict[str, Any], actuators: dict[str, Any], **hardware: Any) -> None:  # noqa: ANN401
    """Wire a description with `actuators` alone: what names another then names none, and is unwired."""
    data["hardware"] = {"actuators": actuators, **hardware}
    for cube in data["cubes"].values():
        for verb in ("moves", "swaps", "tunes"):
            for variable in cube.get(verb, {}).values():
                if variable.get("actuator") not in actuators:
                    variable.pop("actuator", None)


def run_settings(tmp_path: Path, **changes: Any) -> Settings:  # noqa: ANN401
    """Simulated settings without an instrument, everything written under `tmp_path`."""
    return Settings(
        **{
            "simulate": "everything",
            "db_path": str(tmp_path / "agent.db"),
            "image_dir": tmp_path / "images",
            "cache_dir": tmp_path / "cache",
            "calibration_dir": tmp_path / "calibration",
            "camera_recording_dir": tmp_path / "recordings",
            "camera_debug_window": False,
            **changes,
        }
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Simulated settings on the reference microscope, everything written under `tmp_path`."""
    return run_settings(tmp_path, instrument=REFERENCE_INSTRUMENT)


@pytest.fixture
def microscope(settings: Settings) -> Microscope:
    """The reference microscope's parts, built as the app builds them."""
    return build_microscope(settings, spec.load(REFERENCE_INSTRUMENT))


def registry_names() -> tuple[set[str], set[str]]:
    """The states and actions newswitch registers in FastAPI mode (no app, no startup): the same
    whatever its instrument."""
    registry = create_fastapi_registry(None).registry.snapshot()
    actions = {impl.interface or impl.definition.name for impl in registry.get_implementations()}
    return set(registry.states), actions


# AsyncAgentTestClient.collect_until_done() stops at "COMPLETED" only, so a task that
# fails would run out the clock. Poll for every terminal event type instead.
TERMINAL_EVENT_TYPES = {"COMPLETED", "FAILED", "CRITICAL", "CANCELLED"}


@pytest.fixture
def virtual_microscope_app(settings: Settings) -> FastAPI:
    """The FastAPI app of the reference microscope (simulated, every action registered)."""
    # Authentication is bypassed rather than satisfied: AsyncAgentTestClient hardcodes
    # its websocket init payload, so there is no seam to hand it a token through.
    return create_app(settings, authenticator=AllowAllAuthenticator())


async def collect_until_completed(
    client: AsyncAgentTestClient, task_id: str, timeout: float = 5.0
) -> list[BufferedEvent]:
    """Collect events for a task until its terminal event (COMPLETED/FAILED/etc.) arrives."""
    collected: list[BufferedEvent] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        event = await client.receive_event(timeout=remaining)
        if event is None:
            break
        collected.append(event)
        if event.task == task_id and event.event_type in TERMINAL_EVENT_TYPES:
            break

    return collected


def acquisition(
    channels: list[AcquisitionChannel],
    planes: list[float] | None = None,
    times: int = 1,
    places: tuple[tuple[float, float], ...] = ((0.0, 0.0),),
    z: float = 0.0,
    name: str = "run",
    **rest: Any,  # noqa: ANN401
) -> AcquisitionPlan:
    """The same stack of `channels` at every place, every time."""
    return AcquisitionPlan(
        channels=channels,
        positions=[
            AcquisitionPosition(set_to={"stage.x": x, "stage.y": y, "stage.z": z})
            for x, y in places
        ],
        stack=AcquisitionStack(offsets=planes or []),
        times=times,
        name=name,
        **rest,
    )
