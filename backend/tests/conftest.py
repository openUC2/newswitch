"""Pytest configuration and shared fixtures for newswitch tests.

The microscope the tests run on is the complete reference microscope
(`newswitch.tools.export_schemas.REFERENCE_CONFIG`: every part), virtual, with every folder under the
test's ``tmp_path``:

- `settings`: the settings of such a run;
- `microscope`: its parts, built (`newswitch.microscope.parts.build_microscope`): managers and
  states wired exactly as the app wires them, no hand-wiring;
- `registry_names`: what a device configuration registers (states, actions), without an app;
- `virtual_microscope_app`: the full FastAPI app, for tests that talk to the agent.
"""

import asyncio
from pathlib import Path
from typing import Optional

import pytest
from arkitekt_fastapi.testing import AsyncAgentTestClient, BufferedEvent
from fastapi import FastAPI

from main_fastapi import create_fastapi_registry
from newswitch import config_io
from main_fastapi import create_app
from newswitch.accounts.auth import AllowAllAuthenticator
from newswitch.bloks import load_catalog
from newswitch.settings import Settings
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.tools.export_schemas import REFERENCE_CONFIG

#: The complete microscope: every part, so every action is registered.
COMPLETE_CONFIG = REFERENCE_CONFIG


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Virtual settings on the reference microscope, everything written under `tmp_path`."""
    return Settings(
        use_virtual_microscope=True,
        static_config_path=REFERENCE_CONFIG,
        persistent_config_path=tmp_path / "newswitch-config.persistent.yaml",
        load_from_static_config_path=True,
        db_path=str(tmp_path / "agent.db"),
        image_dir=tmp_path / "images",
        cache_dir=tmp_path / "cache",
        camera_recording_dir=tmp_path / "recordings",
        camera_debug_window=False,
    )


@pytest.fixture
def microscope(settings: Settings) -> Microscope:
    """The reference microscope's parts, built as the app builds them."""
    devices = config_io.load_config(REFERENCE_CONFIG).config
    return build_microscope(settings, devices)


def registry_names(devices: Optional[config_io.NewswitchConfig]) -> tuple[set[str], set[str]]:
    """The states and actions `devices` registers in FastAPI mode (no app, no startup)."""
    registry = create_fastapi_registry(devices).registry.snapshot()
    actions = {impl.interface or impl.definition.name for impl in registry.get_implementations()}
    return set(registry.states), actions


# AsyncAgentTestClient.collect_until_done() stops at "COMPLETED" only, so a task that
# fails would run out the clock. Poll for every terminal event type instead.
TERMINAL_EVENT_TYPES = {"COMPLETED", "FAILED", "CRITICAL", "CANCELLED"}


@pytest.fixture
def virtual_microscope_app(settings: Settings, tmp_path: Path) -> FastAPI:
    """The FastAPI app of the reference microscope (virtual, every action registered).

    The reference configuration has no UI; the app's is empty (a configuration without a
    ``ui`` section does not start). Everything is written under ``tmp_path``.
    """
    config = tmp_path / "complete-microscope.yaml"
    config.write_text(
        REFERENCE_CONFIG.read_text() + f"\nui:\n  catalog: {load_catalog().id}\n  bloks: {{}}\n"
    )
    app_settings = settings.model_copy(update={"static_config_path": config, "config_file": config})
    # Authentication is bypassed rather than satisfied: AsyncAgentTestClient hardcodes
    # its websocket init payload, so there is no seam to hand it a token through.
    return create_app(app_settings, authenticator=AllowAllAuthenticator())


# ---------------------------------------------------------------------------
# Config fixtures for the newswitch.config_io tests.
#
# The tests build their own documents instead of reading backend/configs, which
# is a development-only folder (see configs/__note__.md) and will disappear once
# the deployment paths are final. Only tests/config_io/test_schema_drift.py looks
# at the real files, and it skips when they are gone.
# ---------------------------------------------------------------------------


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A throwaway folder for the configuration files of one test.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.

    Returns:
        Path to the temporary config directory.
    """
    root = tmp_path / "configs"
    root.mkdir()
    return root


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
