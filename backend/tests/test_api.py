"""Tests for the FastAPI agent integration.

This module tests the FastAPI agent using AsyncAgentTestClient
for full async integration testing with proper event handling.
Verifies that the agent correctly processes assignments and returns results.
"""

import pytest
from fastapi import FastAPI
from arkitekt_fastapi.testing import AsyncAgentTestClient
from typing import ParamSpec

from tests.conftest import collect_until_completed

P = ParamSpec("P")


@pytest.mark.asyncio
async def test_assign_and_get_result(virtual_microscope_app: FastAPI) -> None:
    """Test that the agent correctly processes detector activation and update assignments.

    Verifies:
        - Detector can be activated via agent assignment.
        - Detector settings can be updated via agent assignment.
        - Events are properly emitted and collected.
        - Assignment completes with a COMPLETED status.

    Args:
        virtual_microscope_app: The FastAPI application fixture with virtual microscope.
    """
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        # First activate a detector
        activate_result = await client.assign("activate_detector", {"slot": 1})
        events = await collect_until_completed(client, activate_result.task_id)
        assert len(events) >= 1
        assert events[-1].event_type == "COMPLETED"

        # Now update the detector exposure
        assign_result = await client.assign("update_detector", {"slot": 1, "exposure_time": 0.5})
        assert assign_result.status == "submitted"

        # Collect events until done
        events = await collect_until_completed(client, assign_result.task_id)

        # Should have received events including COMPLETED
        assert len(events) >= 1
        assert events[-1].event_type == "COMPLETED"
