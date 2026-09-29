"""Pytest configuration and shared fixtures for newswitch tests.

This module provides common fixtures used across multiple test modules,
including the virtual microscope FastAPI application and the config-directory
fixture used by the `newswitch.config_io` tests.
"""

import asyncio
from pathlib import Path
from typing import Generator

import pytest
from fastapi import FastAPI
from rekuest_next.contrib.fastapi import AsyncAgentTestClient
from rekuest_next.contrib.fastapi.testing import BufferedEvent

from newswitch.app import ImswitchConfig, create_app
from newswitch.auth import AllowAllAuthenticator
from newswitch.config import get_paths

# rekuest_next==2.1.1's AsyncAgentTestClient.collect_until_done()/BufferedEvent.is_done()
# still check for a "DONE" event type, but the agent's wire protocol emits "COMPLETED"
# (and "FAILED" instead of "ERROR") for terminal task events, so those helpers never
# match and always run out the clock. Poll for the actual terminal event types instead.
TERMINAL_EVENT_TYPES = {"COMPLETED", "FAILED", "CRITICAL", "CANCELLED"}


@pytest.fixture
def virtual_microscope_app() -> FastAPI:
    """Create the Newswitch FastAPI app for testing.

    Creates a virtual microscope application with default configuration,
    suitable for integration testing of the FastAPI endpoints.

    Returns:
        FastAPI: The configured FastAPI application instance.
    """
    # Authentication is bypassed rather than satisfied: AsyncAgentTestClient hardcodes
    # its websocket init payload, so there is no seam to hand it a token through.
    app = create_app(ImswitchConfig(), authenticator=AllowAllAuthenticator())
    return app


# ---------------------------------------------------------------------------
# Config fixtures for the newswitch.config_io tests.
#
# The tests build their own documents instead of reading backend/Configs, which
# is a development-only folder (see Configs/__note__.md) and will disappear once
# the deployment paths are final. Only tests/config_io/test_schema_drift.py looks
# at the real files, and it skips when they are gone.
# ---------------------------------------------------------------------------


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Point `newswitch.config` at a throwaway config directory.

    All four `Paths` fields are independent settings, so each one gets its own
    environment override. `get_paths()` is `lru_cache`d, so the cache is cleared on
    both sides of the test to keep the override from leaking.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.
        monkeypatch: Pytest's environment patcher.

    Yields:
        Path to the temporary config directory.
    """
    root = tmp_path / "configs"
    root.mkdir()
    monkeypatch.setenv("NEWSWITCH_CONFIG_DIR", str(root))
    monkeypatch.setenv("NEWSWITCH_SCHEMA_DIR", str(root / "schemas"))
    monkeypatch.setenv("NEWSWITCH_DATA_DIR", str(root / "data"))
    monkeypatch.setenv("NEWSWITCH_LOG_DIR", str(root / "logs"))
    get_paths.cache_clear()
    yield root
    get_paths.cache_clear()


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
