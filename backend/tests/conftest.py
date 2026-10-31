"""Pytest configuration and shared fixtures for newswitch tests.

The microscope the tests run on is the complete reference microscope
(`newswitch.tools.export_schemas.REFERENCE_INSTRUMENT`: every part), simulated, with every folder
under the test's ``tmp_path``:

- `settings`: the settings of such a run;
- `microscope`: its parts, built (`newswitch.microscope.parts.build_microscope`): managers and
  states wired exactly as the app wires them, no hand-wiring;
- `registry_names`: what an instrument registers (states, actions), without an app;
- `virtual_microscope_app`: the full FastAPI app, for tests that talk to the agent.
"""

import asyncio
from pathlib import Path
from typing import Any, Optional

import pytest
from arkitekt_fastapi.testing import AsyncAgentTestClient, BufferedEvent
from fastapi import FastAPI

from main_fastapi import create_app, create_fastapi_registry
from newswitch.accounts.auth import AllowAllAuthenticator
from newswitch.instrument import spec
from newswitch.settings import Settings
from newswitch.models.acquisition import (
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    AcquisitionStack,
)
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.tools.export_schemas import REFERENCE_INSTRUMENT


def run_settings(tmp_path: Path, **changes: Any) -> Settings:  # noqa: ANN401
    """Simulated settings without an instrument, everything written under `tmp_path`."""
    return Settings(
        **{
            "simulate": "everything",
            "simulation": "gfp-beads",
            "db_path": str(tmp_path / "agent.db"),
            "image_dir": tmp_path / "images",
            "cache_dir": tmp_path / "cache",
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


def registry_names(instrument: Optional[spec.Instrument]) -> tuple[set[str], set[str]]:
    """The states and actions `instrument` registers in FastAPI mode (no app, no startup)."""
    registry = create_fastapi_registry(instrument).registry.snapshot()
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
