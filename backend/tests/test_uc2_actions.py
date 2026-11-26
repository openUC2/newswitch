"""Agent-level tests for the UC2 board's actions (virtual bus), and homing and stopping a stage."""

from pathlib import Path
from typing import Any

import pytest
from arkitekt_fastapi.testing import AsyncAgentTestClient
from fastapi import FastAPI

from main_fastapi import create_app
from newswitch.infra.accounts.auth import AllowAllAuthenticator
from tests.conftest import collect_until_completed, run_settings

FAKE = Path(__file__).parent.parent / "instruments" / "fake-microscope"


@pytest.mark.asyncio
async def test_home_and_stop_stage(virtual_microscope_app: FastAPI) -> None:
    """The stage is one to choose, and homing and stopping it complete."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        moves = (await client.get("/states/move")).json()["state"]
        assert "stage" in moves["homes"] and "stage" in moves["stops"]

        result = await client.assign("home_stage", {"stage": "stage"})
        events = await collect_until_completed(client, result.task_id, timeout=30.0)
        assert events[-1].event_type == "COMPLETED", events[-1]

        result = await client.assign("stop_stage", {"stage": "stage"})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED", events[-1]


@pytest.mark.asyncio
async def test_homing_what_does_not_move_says_what_does(virtual_microscope_app: FastAPI) -> None:
    """A cube that moves nothing is refused, naming the ones that move."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        result = await client.assign("home_stage", {"stage": "camera"})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type in ("FAILED", "CRITICAL"), events[-1]
        assert "camera moves nothing" in str(events[-1]) and "stage" in str(events[-1])


@pytest.mark.asyncio
async def test_uc2_scan_nodes_action(virtual_microscope_app: FastAPI) -> None:
    """uc2_scan_nodes completes and reports the fake fleet."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        result = await client.assign("uc2_scan_nodes", {"board": "uc2"})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED"


@pytest.mark.asyncio
async def test_a_board_it_lacks_is_refused_naming_those_it_has(
    virtual_microscope_app: FastAPI,
) -> None:
    """The boards are listed in UC2State; another is refused."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        assert (await client.get("/states/uc2")).json()["state"]["boards"] == ["uc2"]
        result = await client.assign("uc2_scan_nodes", {"board": "other"})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type in ("FAILED", "CRITICAL"), events[-1]
        assert "no UC2 board 'other'" in str(events[-1]) and "uc2" in str(events[-1])


@pytest.mark.asyncio
async def test_galvo_actions(virtual_microscope_app: FastAPI) -> None:
    """Galvo goto/raster/status/stop complete against the virtual bus."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        for action, args in (
            ("galvo_set_position", {"board": "uc2", "x": 1000, "y": 2000}),
            ("galvo_raster_scan", {"board": "uc2", "nx": 16, "ny": 16}),
            ("galvo_get_status", {"board": "uc2"}),
            ("galvo_stop", {"board": "uc2"}),
        ):
            result = await client.assign(action, args)
            events = await collect_until_completed(client, result.task_id)
            assert events[-1].event_type == "COMPLETED", f"{action} failed: {events[-1]}"


@pytest.mark.asyncio
async def test_run_autofocus_action(virtual_microscope_app: FastAPI) -> None:
    """run_autofocus finds the focal plane and leaves the stage there.

    The reference microscope's focal plane is z = 0; from z = 6 a sweep over 0..12 finds it.
    """
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        # A detector must be active for capture_image to produce frames.
        result = await client.assign("activate_detector", {"name": "camera"})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED"

        result = await client.assign("move_one", {"name": "stage.z", "to": 6.0})
        events = await collect_until_completed(client, result.task_id, timeout=30.0)
        assert events[-1].event_type == "COMPLETED"

        result = await client.assign("run_autofocus", {"z_range": 12.0, "steps": 13})
        events = await collect_until_completed(client, result.task_id, timeout=30.0)
        assert events[-1].event_type == "COMPLETED"
        returned = [e.get_returns() for e in events if e.get_returns()]
        assert returned, "run_autofocus returned no focus position"
        best_z = next(iter(returned[-1].values()))
        assert abs(best_z) <= 1.0

        moves = (await client.get("/states/move")).json()["state"]["moves"]
        assert moves["stage"]["z"]["current"] == pytest.approx(best_z)


@pytest.mark.asyncio
async def test_the_scan_says_what_each_node_runs(virtual_microscope_app: FastAPI) -> None:
    """Its return holds each node's image and version, and the board lands in UC2State."""
    async with AsyncAgentTestClient(virtual_microscope_app) as client:
        result = await client.assign("uc2_scan_nodes", {"board": "uc2"})
        events = await collect_until_completed(client, result.task_id)
        assert events[-1].event_type == "COMPLETED"
        returned = [e.get_returns() for e in events if e.get_returns()]
        assert "esp32_UC2_canopen_slave_motor_release.bin" in str(returned)
        state = (await client.get("/states/uc2")).json()
        assert "master" in str(state) and "esp32_UC2_canopen_master_release.bin" in str(state)


@pytest.mark.asyncio
async def test_update_firmware_flashes_what_the_description_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the fake microscope's simulated bus: the board and the named nodes, nothing downloaded."""
    from newswitch.drivers.uc2 import firmware

    async def fetch(spec: Any, pin: Any, full: bool) -> firmware.FirmwareImage:  # noqa: ANN401
        return firmware.FirmwareImage(
            path=Path(f"esp32_{pin.env}.bin"),
            chip="esp32",
            offset=0x10000,
            url="",
            version=spec.version_of(pin),
        )

    monkeypatch.setattr(firmware, "fetch", fetch)
    app = create_app(run_settings(tmp_path, instrument=FAKE), AllowAllAuthenticator())
    async with AsyncAgentTestClient(app) as client:
        result = await client.assign("update_firmware", {"board": "uc2", "nodes": [11]})
        events = await collect_until_completed(client, result.task_id, timeout=20.0)
        assert events[-1].event_type == "COMPLETED", events[-1]
        returned = [e.get_returns() for e in events if e.get_returns()]
        assert "esp32_UC2_canopen_slave_motor_release_motX.bin" in str(returned)
