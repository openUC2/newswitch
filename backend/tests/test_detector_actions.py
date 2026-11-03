"""Agent-level tests for the live view and snapshot actions (virtual microscope).

The virtual detector cannot record, so the ``*_save_to_disk`` actions must fail with a
clear message; recording itself is tested with the simulated camera in
``test_uc2_detector.py``.
"""

import pytest
from fastapi import FastAPI
from rekuest_next.contrib.fastapi import AsyncAgentTestClient
from rekuest_next.contrib.fastapi.testing import BufferedEvent

from tests.conftest import collect_until_completed


async def run(client: AsyncAgentTestClient, action: str, args: dict) -> BufferedEvent:
    """Assign an action and return its terminal event."""
    result = await client.assign(action, args)
    events = await collect_until_completed(client, result.task_id, timeout=10.0)
    return events[-1]


@pytest.mark.asyncio
async def test_start_and_stop_live_view(virtual_microscope_app: FastAPI) -> None:
    """start_live_view and stop_live_view complete."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        assert (await run(client, "activate_detector", {"slot": 1})).event_type == "COMPLETED"
        assert (await run(client, "start_live_view", {})).event_type == "COMPLETED"
        assert (await run(client, "stop_live_view", {})).event_type == "COMPLETED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", ["start_live_view_and_save_to_disk", "capture_image_and_save_to_disk"]
)
async def test_saving_fails_on_the_virtual_detector(
    virtual_microscope_app: FastAPI, action: str
) -> None:
    """The saving actions fail with a message saying why.

    rekuest reports an exception raised by an action as CRITICAL (FAILED is for
    arguments or results that cannot be serialized).
    """
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        assert (await run(client, "activate_detector", {"slot": 1})).event_type == "COMPLETED"
        event = await run(client, action, {})
        assert event.event_type == "CRITICAL"
        assert event.data["error"] == "the virtual detector cannot record to disk"
