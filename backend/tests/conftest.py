"""Pytest configuration and shared fixtures for newswitch tests.

This module provides common fixtures used across multiple test modules,
including the virtual microscope FastAPI application.
"""

import asyncio

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
    app = create_app(ImswitchConfig(), authenticator=AllowAllAuthenticator())
    return app


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
