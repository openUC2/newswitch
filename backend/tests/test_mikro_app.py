"""A mikro in FastAPI mode: its client lives as long as the agent."""

import asyncio
import time
from pathlib import Path

import pytest
from arkitekt import App
from fastapi.testclient import TestClient

from main_fastapi import create_app, create_fastapi_registry
from newswitch.accounts.auth import AllowAllAuthenticator
from newswitch.microscope.run import Run
from newswitch.services.mikro_connection import MikroConnection
from tests.conftest import run_settings

pytest.importorskip("mikro")

from newswitch.services import mikro_app  # noqa: E402  (needs the extra "mikro")
from newswitch.services.mikro_store import MikroDatasetStore  # noqa: E402


class FakeClient:
    """What a connection hands out: records being entered and left."""

    def __init__(self) -> None:
        """Neither yet."""
        self.events: list[str] = []

    async def __aenter__(self) -> "FakeClient":
        """Entered."""
        self.events.append("entered")
        return self

    async def __aexit__(self, *_: object) -> None:
        """Left."""
        self.events.append("left")


def test_the_client_lives_as_long_as_the_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entered when the hook starts, left when it finishes."""
    client = FakeClient()
    connection = MikroConnection("http://mikro", "http://data", "token")
    monkeypatch.setattr(MikroConnection, "client", lambda self: client)
    run = Run(run_settings(tmp_path), None, connection)

    async def lifetime() -> None:
        hook = mikro_app.provide_mikro(run)
        provided, store = await anext(hook)
        assert provided is client
        assert isinstance(store, MikroDatasetStore) and store.client is client
        assert client.events == ["entered"]
        with pytest.raises(StopAsyncIteration):
            await anext(hook)

    asyncio.run(lifetime())
    assert client.events == ["entered", "left"]


def test_a_started_agent_enters_and_leaves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the real start and stop of the served agent, not just the hook."""
    client = FakeClient()
    connection = MikroConnection("http://mikro", "http://data", "token")
    monkeypatch.setattr(MikroConnection, "from_env", classmethod(lambda cls, *_: connection))
    monkeypatch.setattr(MikroConnection, "client", lambda self: client)

    app = create_app(run_settings(tmp_path), AllowAllAuthenticator())
    with TestClient(app):
        for _ in range(250):
            if client.events:
                break
            time.sleep(0.02)
        assert client.events == ["entered"]
    assert client.events == ["entered", "left"]


def test_it_is_merged_only_when_asked_for() -> None:
    """Without a mikro nothing of it is registered."""
    assert "provide_mikro" not in _hooks(create_fastapi_registry(None))
    assert "provide_mikro" in _hooks(create_fastapi_registry(None, with_mikro=True))
    assert "provide_mikro" not in _hooks(create_fastapi_registry(None))


def _hooks(app: App) -> set[str]:
    return set(app.registry.hooks_registry.startup_hooks)
