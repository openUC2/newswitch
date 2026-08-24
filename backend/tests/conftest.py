"""Pytest configuration and shared fixtures for newswitch tests.

This module provides common fixtures used across multiple test modules,
including the virtual microscope FastAPI application and the config-file
fixtures used by the `newswitch.schemas` tests.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Generator

import pytest
import yaml
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
# Config fixtures for the newswitch.schemas tests.
#
# The tests build their own documents instead of reading backend/Configs, which
# is a development-only folder (see Configs/__note__.md) and will disappear once
# the deployment paths are final. Only tests/test_schema_export_drift.py looks at
# the real files, and it skips when they are gone.
# ---------------------------------------------------------------------------

# (document, file name) -> path written to
ConfigWriter = Callable[[Any, str], Path]


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


@pytest.fixture
def write_config(config_dir: Path) -> ConfigWriter:
    """Return a helper that writes a document into the temporary config directory.

    The format follows the file name's suffix, so the same document can be written
    as .yaml, .yml and .json to prove the loaders treat them identically.

    Args:
        config_dir: The temporary config directory fixture.

    Returns:
        A callable ``(document, name) -> Path``.
    """

    def _write(document: Any, name: str) -> Path:  # noqa: ANN401 - any JSON-shaped document
        path = config_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".json":
            path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def camera_doc() -> dict[str, Any]:
    """A valid single-camera document, exercising both `Bounded` spellings.

    Returns:
        The document as a plain dict.
    """
    return {
        "name": "TestCam-2000",
        "manufacturer": "openUC2",
        "camera_id": "testcam-001",
        "pixelcount": {"x": 1920, "y": 1200},
        "pixelpitch_um": {"x": 10.0},  # y omitted -> derived
        "channels": 1,
        "exposure_time_ms": {"value": 10.0, "min": 0.024, "max": 10000.0, "increment": 0.001},
        "framerate_per_sec": 30.0,  # scalar shorthand
        "binning": 1,
        "trigger": {"type": "hardware", "edge": "rising"},
        "tags": ["monochrome", "test"],
    }


@pytest.fixture
def registry_doc(camera_doc: dict[str, Any]) -> dict[str, Any]:
    """A valid multi-device document holding one of each device type.

    Args:
        camera_doc: The single-camera document fixture.

    Returns:
        The document as a plain dict.
    """
    return {
        "version": 1,
        "setup": "test-bench",
        "devices": [
            {**camera_doc, "type": "camera"},
            {
                "type": "stage",
                "name": "XY-Test",
                "device_id": "stage-001",
                "axes": [
                    {"label": "x", "travel_um": 100000.0, "steps_per_um": 8.0},
                    {"label": "y", "travel_um": 100000.0, "steps_per_um": 8.0},
                ],
                "max_speed_um_per_sec": 5000.0,
            },
            {
                "type": "laser",
                "name": "LD-488",
                "device_id": "laser-001",
                "wavelength_nm": 488.0,
                "max_power_mw": 100.0,
                "modulation": "digital",
            },
            {
                "type": "filterwheel",
                "name": "FW-Test",
                "device_id": "fw-001",
                "slots": [
                    {"position": 0, "label": "empty"},
                    {"position": 1, "label": "GFP-525/50", "center_nm": 525.0},
                ],
            },
        ],
    }


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
