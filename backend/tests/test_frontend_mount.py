"""Tests for serving the built frontend from the backend (container image).

The bundle must be reachable before anyone logs in, while the API next to it stays gated,
and reloading the page on a route of the React router must still get the app.
"""

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from newswitch.app import ImswitchConfig, create_app
from newswitch.auth import UserStoreAuthenticator
from newswitch.routes.http.frontend import FRONTEND_DIR_ENV_VAR
from newswitch.users import UserStore

INDEX = "<!doctype html><title>newswitch</title>"
ASSET = "console.log('newswitch');"


@pytest.fixture
def dist_dir(tmp_path: Path) -> Path:
    """A minimal built frontend: index.html plus one asset."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "index.js").write_text(ASSET)
    return dist


def gated_app_client(tmp_path: Path, frontend_dir: Path | None) -> TestClient:
    """A client of the app with a real (empty) account store, so the gate is exercised."""
    app = create_app(
        ImswitchConfig(config_file=None, use_virtual_microscope=True),
        authenticator=UserStoreAuthenticator(UserStore(tmp_path / "auth.db")),
        frontend_dir=frontend_dir,
    )
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path, dist_dir: Path) -> Iterator[TestClient]:
    """A client of the app that serves `dist_dir`; it never sends credentials."""
    with gated_app_client(tmp_path, dist_dir) as test_client:
        yield test_client


def test_index_is_served_without_a_token(client: TestClient) -> None:
    """The app's entry page needs no login: the login page is part of it."""
    response = client.get("/newswitch/")
    assert response.status_code == 200
    assert response.text == INDEX


def test_root_redirects_to_the_frontend(client: TestClient) -> None:
    """The bare host name leads to the frontend."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/newswitch/"


def test_assets_are_served(client: TestClient) -> None:
    """The bundle's files come as they are."""
    response = client.get("/newswitch/assets/index.js")
    assert response.status_code == 200
    assert response.text == ASSET


def test_router_paths_fall_back_to_the_index(client: TestClient) -> None:
    """A reload on a route of the React router still gets the app."""
    for path in ("/newswitch/login", "/newswitch/users", "/newswitch/replay/abc"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.text == INDEX


def test_missing_assets_stay_404(client: TestClient) -> None:
    """A path that names a file is not answered with the index."""
    assert client.get("/newswitch/assets/missing.js").status_code == 404


def test_api_stays_gated(client: TestClient) -> None:
    """Serving the frontend opens no API route."""
    assert client.get("/auth/me").status_code == 401
    assert client.get("/health").status_code == 200


def test_no_frontend_without_a_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a folder (argument or environment) nothing is served under /newswitch/."""
    monkeypatch.delenv(FRONTEND_DIR_ENV_VAR, raising=False)
    with gated_app_client(tmp_path, None) as client:
        assert client.get("/newswitch/").status_code == 404


def test_folder_from_the_environment(
    tmp_path: Path, dist_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The container image names the folder through the environment."""
    monkeypatch.setenv(FRONTEND_DIR_ENV_VAR, str(dist_dir))
    with gated_app_client(tmp_path, None) as client:
        assert client.get("/newswitch/").text == INDEX


def test_a_folder_without_index_fails_at_startup(tmp_path: Path) -> None:
    """A wrong path in a deployment fails loudly instead of serving an empty page."""
    with pytest.raises(FileNotFoundError, match="index.html"):
        create_app(
            ImswitchConfig(config_file=None, use_virtual_microscope=True),
            frontend_dir=tmp_path / "nowhere",
        )
