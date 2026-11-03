"""Tests for the FastAPI agent integration.

This module tests the FastAPI agent using AsyncAgentTestClient
for full async integration testing with proper event handling.
Verifies that the agent correctly processes assignments and returns results.
"""

import pytest
from fastapi import FastAPI
from rekuest_next.contrib.fastapi import AsyncAgentTestClient
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


@pytest.mark.asyncio
async def test_update_detector_sets_frame_rate_binning_and_roi(
    virtual_microscope_app: FastAPI,
) -> None:
    """The update_detector action passes frame rate, binning and region on to the detector.

    Args:
        virtual_microscope_app: The FastAPI application fixture with virtual microscope.
    """
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        activate_result = await client.assign("activate_detector", {"slot": 1})
        events = await collect_until_completed(client, activate_result.task_id)
        assert events[-1].event_type == "COMPLETED"

        assign_result = await client.assign(
            "update_detector",
            {"slot": 1, "frame_rate": 5.0, "binning": 2, "roi": [0, 0, 256, 128]},
        )
        events = await collect_until_completed(client, assign_result.task_id)
        assert events[-1].event_type == "COMPLETED"

        # The returned detector, not CameraState: its patches may arrive after COMPLETED.
        returns = [event.get_returns() for event in events if event.event_type == "YIELD"]
        detector = returns[-1]["return0"]
        assert detector["current_frame_rate"] == 5.0
        assert detector["current_binning"] == 2
        assert detector["current_roi"] == [0, 0, 256, 128]
        assert (detector["width"], detector["height"]) == (128, 64)
