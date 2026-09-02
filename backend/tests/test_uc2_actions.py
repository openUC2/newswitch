"""Agent-level tests for the Wave-1 UC2 registered actions (virtual bus)."""

import pytest
from fastapi import FastAPI
from rekuest_next.contrib.fastapi import AsyncAgentTestClient

from tests.conftest import collect_until_completed


@pytest.mark.asyncio
async def test_home_and_stop_stage(virtual_microscope_app: FastAPI) -> None:
    """home_stage and stop_stage complete against the virtual bus."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        result = await client.assign("home_stage", {"axes": ["Z", "X"]})
        events = await collect_until_completed(client, result.task_id, timeout=10.0)
        assert events[-1].event_type == "COMPLETED"

        result = await client.assign("stop_stage", {})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED"


@pytest.mark.asyncio
async def test_led_matrix_actions(virtual_microscope_app: FastAPI) -> None:
    """LED matrix fill/off complete against the virtual bus."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        result = await client.assign("led_matrix_fill", {"r": 255, "g": 0, "b": 0})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED"

        result = await client.assign("led_matrix_off", {})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED"


@pytest.mark.asyncio
async def test_uc2_scan_nodes_action(virtual_microscope_app: FastAPI) -> None:
    """uc2_scan_nodes completes and reports the fake fleet."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        result = await client.assign("uc2_scan_nodes", {})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED"


@pytest.mark.asyncio
async def test_galvo_actions(virtual_microscope_app: FastAPI) -> None:
    """Galvo goto/raster/status/stop complete against the virtual bus."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        for action, args in (
            ("galvo_set_position", {"x": 1000, "y": 2000}),
            ("galvo_raster_scan", {"nx": 16, "ny": 16}),
            ("galvo_get_status", {}),
            ("galvo_stop", {}),
        ):
            result = await client.assign(action, args)
            events = await collect_until_completed(client, result.task_id)
            assert events[-1].event_type == "COMPLETED", f"{action} failed: {events[-1]}"


@pytest.mark.asyncio
async def test_run_autofocus_action(virtual_microscope_app: FastAPI) -> None:
    """run_autofocus completes on the virtual microscope."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        # A detector must be active for capture_image to produce frames.
        result = await client.assign("activate_detector", {"slot": 1})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED"

        result = await client.assign("run_autofocus", {"z_range": 4.0, "steps": 5})
        events = await collect_until_completed(client, result.task_id, timeout=30.0)
        assert events[-1].event_type == "COMPLETED"
