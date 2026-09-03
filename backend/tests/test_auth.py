"""Tests for the login gate.

The gate has to hold across transports that carry credentials differently - a header
for `fetch`, an in-band frame for websockets, a query parameter for the loaders that
can set neither - so most of these tests are about a specific channel rather than about
the credential check itself.
"""

import base64
from pathlib import Path
from typing import Iterator

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from newswitch.app import ImswitchConfig, create_app
from newswitch.auth import (
    AUTH_FILE_ENV_VAR,
    AuthenticationError,
    Credentials,
    UserStoreAuthenticator,
    default_authenticator,
    load_credentials,
)
from newswitch.users import Role, UserStore

USERNAME = "operator"
PASSWORD = "hunter2"


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    """A store with one account, ready to log in."""
    store = UserStore(tmp_path / "auth.db")
    store.create_user(USERNAME, PASSWORD, Role.OPERATOR)
    return store


@pytest.fixture
def authed_app(store: UserStore) -> FastAPI:
    """The app with a real account store, so the gate is actually exercised."""
    return create_app(
        ImswitchConfig(),
        authenticator=UserStoreAuthenticator(store),
    )


@pytest.fixture
def client(authed_app: FastAPI) -> Iterator[TestClient]:
    """A client that never sends credentials unless a test asks it to."""
    with TestClient(authed_app) as test_client:
        yield test_client


@pytest.fixture
def token(client: TestClient) -> str:
    """A live session token for the seeded account."""
    response = client.post("/auth/login", headers=basic_header())
    return response.json()["token"]


def basic_header(username: str = USERNAME, password: str = PASSWORD) -> dict[str, str]:
    """Build an HTTP Basic header the way a browser would."""
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


# ------------------------------------------------------------------ credential file


def test_credentials_load_from_yaml(tmp_path: Path) -> None:
    """Credentials come from the YAML file."""
    auth_file = tmp_path / "auth.yaml"
    auth_file.write_text(yaml.safe_dump({"username": "a", "password": "b"}))
    assert load_credentials(auth_file) == Credentials(username="a", password="b")


def test_numeric_password_is_read_as_text(tmp_path: Path) -> None:
    """`password: 1234` parses as an int, but the comparison is on strings."""
    auth_file = tmp_path / "auth.yaml"
    auth_file.write_text("username: a\npassword: 1234\n")
    assert load_credentials(auth_file).password == "1234"


def test_missing_default_file_falls_back_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A fresh clone must run without setup, but must say so."""
    monkeypatch.delenv(AUTH_FILE_ENV_VAR, raising=False)
    monkeypatch.setattr("newswitch.auth.DEFAULT_AUTH_FILE", "/nonexistent/auth.yaml", raising=False)
    with caplog.at_level("WARNING"):
        credentials = load_credentials()
    assert credentials == Credentials(username="admin", password="admin")
    assert "admin" in caplog.text


def test_explicitly_named_missing_file_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo'd deployment path must fail, not silently accept admin/admin."""
    monkeypatch.setenv(AUTH_FILE_ENV_VAR, "/nonexistent/auth.yaml")
    with pytest.raises(RuntimeError):
        load_credentials()


def test_incomplete_file_refuses_to_start(tmp_path: Path) -> None:
    """Half a credential is a misconfiguration, not a default."""
    auth_file = tmp_path / "auth.yaml"
    auth_file.write_text("username: a\n")
    with pytest.raises(RuntimeError):
        load_credentials(auth_file)


def test_non_mapping_file_refuses_to_start(tmp_path: Path) -> None:
    """A YAML list or scalar is not a credentials file."""
    auth_file = tmp_path / "auth.yaml"
    auth_file.write_text("- just\n- a list\n")
    with pytest.raises(RuntimeError):
        load_credentials(auth_file)


def test_unknown_keys_refuse_to_start(tmp_path: Path) -> None:
    """A misspelled key would otherwise leave the real one at its default."""
    auth_file = tmp_path / "auth.yaml"
    auth_file.write_text("username: a\npassword: b\nusrename: typo\n")
    with pytest.raises(RuntimeError):
        load_credentials(auth_file)


def test_empty_password_refuses_to_start(tmp_path: Path) -> None:
    """An empty password is a misconfiguration, not a blank login."""
    auth_file = tmp_path / "auth.yaml"
    auth_file.write_text('username: a\npassword: ""\n')
    with pytest.raises(RuntimeError):
        load_credentials(auth_file)


# -------------------------------------------------------------------------- login


def test_login_returns_a_token(client: TestClient) -> None:
    """A correct login issues the token every later call uses."""
    response = client.post("/auth/login", headers=basic_header())
    assert response.status_code == 200
    assert response.json()["token"]


def test_login_rejects_a_wrong_password(client: TestClient) -> None:
    """A wrong password does not issue a token."""
    response = client.post("/auth/login", headers=basic_header(password="wrong"))
    assert response.status_code == 401


def test_login_rejects_a_missing_header(client: TestClient) -> None:
    """No credentials means no token."""
    assert client.post("/auth/login").status_code == 401


def test_login_401_has_no_www_authenticate_header(client: TestClient) -> None:
    """That header makes the browser open its own credential dialog.

    The app drives its own login page; a native Basic prompt appearing over it would
    leave the user with two competing forms.
    """
    response = client.post("/auth/login", headers=basic_header(password="wrong"))
    assert "www-authenticate" not in {key.lower() for key in response.headers}


def test_malformed_basic_header_is_rejected(client: TestClient) -> None:
    """Undecodable credentials are rejected, not crashed on."""
    response = client.post("/auth/login", headers={"Authorization": "Basic !!!not-b64"})
    assert response.status_code == 401


# ------------------------------------------------------------------------- logout


def test_logout_revokes_a_user_store_session(tmp_path: Path) -> None:
    """Logout invalidates exactly the session used, not every session for the account."""
    store = UserStore(tmp_path / "auth.db")
    store.create_user(USERNAME, PASSWORD, Role.OPERATOR)
    app = create_app(ImswitchConfig(), authenticator=UserStoreAuthenticator(store))
    with TestClient(app) as user_client:
        login_response = user_client.post("/auth/login", headers=basic_header())
        token = login_response.json()["token"]

        before = user_client.get("/states", headers={"Authorization": f"Bearer {token}"})
        assert before.status_code != 401

        logout_response = user_client.post(
            "/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert logout_response.status_code == 204

        after = user_client.get("/states", headers={"Authorization": f"Bearer {token}"})
        assert after.status_code == 401


# ----------------------------------------------------------------- http gating


def test_protected_route_requires_a_token(client: TestClient) -> None:
    """The default for any route is closed."""
    assert client.get("/states").status_code == 401


def test_protected_route_accepts_a_bearer_token(client: TestClient, token: str) -> None:
    """The header path, used by every `fetch` call."""
    response = client.get("/states", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code != 401


def test_protected_route_accepts_a_query_token(client: TestClient, token: str) -> None:
    """For three.js' TextureLoader and zarrita, which cannot set headers."""
    response = client.get(f"/states?token={token}")
    assert response.status_code != 401


def test_a_wrong_token_is_rejected(client: TestClient) -> None:
    """A token that is not the issued one grants nothing."""
    response = client.get("/states", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/health", "/schemas/states", "/schemas/locks"])
def test_public_paths_need_no_token(client: TestClient, path: str) -> None:
    """`/schemas/*` stays public: the frontend's codegen reads it at build time,
    before any user could have logged in."""
    assert client.get(path).status_code == 200


def test_preflight_is_not_gated(client: TestClient) -> None:
    """A browser sends no credentials on a preflight, by design."""
    response = client.options(
        "/states",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code != 401


def test_login_preflight_allows_the_authorization_header(client: TestClient) -> None:
    """The preflight that gates the entire feature.

    Login POSTs cross-origin with an `Authorization` header, which forces a preflight
    carrying `Access-Control-Request-Headers: authorization`. If that is refused, login
    fails and nothing else in the app is reachable.
    """
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed or allowed == "*"


def test_protected_preflight_allows_the_authorization_header(client: TestClient) -> None:
    """Same for every authenticated call the app makes afterwards."""
    response = client.options(
        "/states",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed or allowed == "*"


def test_a_401_still_carries_cors_headers(client: TestClient) -> None:
    """The one test that catches a reversed middleware order.

    CORS has to wrap the auth middleware. If it does not, the browser sees an opaque
    CORS failure instead of the 401 that tells the app to send the user to /login.
    """
    response = client.get("/states", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 401
    assert "access-control-allow-origin" in {key.lower() for key in response.headers}


# ------------------------------------------------------------------- websockets


def test_agent_websocket_rejects_a_missing_token(client: TestClient) -> None:
    """1008 rather than a silent drop: the frontend keys its logout on that code."""
    with pytest.raises(WebSocketDisconnect) as excinfo:  # noqa: PT012
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "INIT"})
            websocket.receive_json()
    assert excinfo.value.code == 1008


def test_agent_websocket_accepts_an_in_band_token(client: TestClient, token: str) -> None:
    """The token rides the init frame the client already sends."""
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "INIT", "token": token})
        assert websocket.receive_json()["type"] == "INIT"


def test_stream_websocket_rejects_a_missing_token(client: TestClient) -> None:
    """Video sockets carry no frames until the auth frame is accepted."""
    with pytest.raises(WebSocketDisconnect) as excinfo:  # noqa: PT012
        with client.websocket_connect("/stream/zstd/1") as websocket:
            websocket.send_json({"type": "auth"})
            websocket.receive_bytes()
    assert excinfo.value.code == 1008


def test_stream_websocket_rejects_a_wrong_token(client: TestClient) -> None:
    """Video sockets are gated like the agent socket."""
    with pytest.raises(WebSocketDisconnect) as excinfo:  # noqa: PT012
        with client.websocket_connect("/stream/h264/1") as websocket:
            websocket.send_json({"type": "auth", "token": "nope"})
            websocket.receive_bytes()
    assert excinfo.value.code == 1008


# ---------------------------------------------------------------- authenticator


def test_authenticator_rejects_an_empty_token(store: UserStore) -> None:
    """An absent credential is not a match."""
    authenticator = UserStoreAuthenticator(store)
    assert not authenticator.check_token(None)
    assert not authenticator.check_token("")


def test_authenticator_login_raises_on_bad_credentials(store: UserStore) -> None:
    """Rejection is signalled by the exception the routes translate to 401."""
    authenticator = UserStoreAuthenticator(store)
    with pytest.raises(AuthenticationError):
        authenticator.login("Basic " + "bm9wZTpub3Bl")  # nope:nope


# ------------------------------------------------------------------- bootstrapping


def test_default_authenticator_seeds_an_admin_from_the_legacy_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh deployment still runs without setup: the first login becomes an admin."""
    auth_file = tmp_path / "auth.yaml"
    auth_file.write_text(yaml.safe_dump({"username": "root", "password": "secret"}))
    monkeypatch.setenv(AUTH_FILE_ENV_VAR, str(auth_file))
    monkeypatch.setenv("NEWSWITCH_AUTH_DB", str(tmp_path / "auth.db"))

    authenticator = default_authenticator()

    seeded = authenticator.store.get_user("root")
    assert seeded is not None
    assert seeded.role == Role.ADMIN
    assert authenticator.store.verify_password("root", "secret") is not None


def test_default_authenticator_does_not_reseed_an_existing_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once accounts exist, the legacy YAML is no longer consulted."""
    monkeypatch.setenv("NEWSWITCH_AUTH_DB", str(tmp_path / "auth.db"))
    UserStore(tmp_path / "auth.db").create_user("alice", "hunter2", Role.VIEWER)
    monkeypatch.setenv(AUTH_FILE_ENV_VAR, str(tmp_path / "nonexistent.yaml"))

    authenticator = default_authenticator()

    assert authenticator.store.get_user("admin") is None
    assert authenticator.store.get_user("alice") is not None
