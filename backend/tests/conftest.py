"""Pytest configuration and shared fixtures for newswitch tests.

This module provides common fixtures used across multiple test modules,
including the virtual microscope FastAPI application and the config-directory
fixture used by the `newswitch.config_io` tests.
"""

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from rekuest_next.contrib.fastapi import AsyncAgentTestClient
from rekuest_next.contrib.fastapi.testing import BufferedEvent

from newswitch.app import ImswitchConfig, create_app
from newswitch.auth import AllowAllAuthenticator

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
    # config_file=None: built-in virtual devices; never writes into backend/Configs
    app = create_app(ImswitchConfig(config_file=None), authenticator=AllowAllAuthenticator())
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
