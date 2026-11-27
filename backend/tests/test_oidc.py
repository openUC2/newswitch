"""Security regressions for the alternate sign-in path."""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from newswitch.auth import AuthMiddleware, UserStoreAuthenticator, router as auth_router
from newswitch.routes.http import oidc
from newswitch.routes.http.users import router as users_router
from newswitch.users import Role, UserStore

ISSUER = "https://sso.example.org/realms/openuc2"
REDIRECT = "https://instrument.example.org/login/keycloak/callback"
SUBJECT = "6784cfb0-90cb-4aae-b739-556bbb5b6f89"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    """An isolated test signer for real token validation."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    """A local account with a working password and its chosen device role."""
    result = UserStore(tmp_path / "auth.db")
    result.create_user("operator", "local-password", Role.OPERATOR)
    return result


@pytest.fixture
def client(store: UserStore) -> TestClient:
    """Exercise OIDC and password auth through the usual auth middleware."""
    app = FastAPI()
    app.state.authenticator = UserStoreAuthenticator(store)
    app.state.oidc_config = oidc.OIDCConfig(ISSUER, "newswitch", REDIRECT)
    app.add_middleware(AuthMiddleware, authenticator=app.state.authenticator)
    app.include_router(auth_router)
    app.include_router(oidc.router)
    app.include_router(users_router)
    return TestClient(app)


def begin(client: TestClient) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Start a login and expose the authorization parameters for the fake issuer."""
    result = client.post("/auth/oidc/start")
    assert result.status_code == 200
    flow = result.json()
    query = parse_qs(urlsplit(flow["authorization_url"]).query)
    assert query["redirect_uri"] == [REDIRECT]
    assert query["code_challenge_method"] == ["S256"]
    assert flow["proof"] not in flow["authorization_url"]
    return {"state": flow["state"], "proof": flow["proof"], "code": "test-code"}, query


def mock_provider(
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
    claims: dict[str, str | int],
) -> None:
    """Supply discovery, the token response and JWKS offline."""
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "test-key", "alg": "RS256"})

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": ISSUER})
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [public_jwk]})
        assert request.url.path.endswith("/token")
        form = parse_qs(request.content.decode())
        assert form["redirect_uri"] == [REDIRECT]
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["test-code"]
        assert len(form["code_verifier"][0]) == 43
        now = int(time.time())
        payload = {"iss": ISSUER, "aud": "newswitch", "sub": SUBJECT, "iat": now, "exp": now + 60}
        token = jwt.encode(
            {**payload, **claims}, signing_key, algorithm="RS256", headers={"kid": "test-key"}
        )
        return httpx.Response(200, json={"id_token": token})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        oidc.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )


def test_linked_login_requires_browser_proof_and_is_single_use(
    client: TestClient,
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
) -> None:
    """An authorization callback cannot sign in a different tab or be reused."""
    claims: dict[str, str | int] = {}
    mock_provider(monkeypatch, signing_key, claims)
    store.link_oidc_identity("operator", ISSUER, SUBJECT)
    body, query = begin(client)
    claims["nonce"] = query["nonce"][0]

    wrong_browser = client.post("/auth/oidc/complete", json={**body, "proof": "x" * 43})
    assert wrong_browser.status_code == 401
    result = client.post("/auth/oidc/complete", json=body)
    assert result.status_code == 200
    token = result.json()["token"]
    user = store.resolve_session(token)
    assert user is not None and user.role == Role.OPERATOR
    assert client.post("/auth/oidc/complete", json=body).status_code == 401
    assert store.unlink_oidc_identity("operator", ISSUER)
    assert store.resolve_session(token) is None


@pytest.mark.parametrize(
    ("overrides", "status", "disabled"),
    [
        ({"nonce": "wrong"}, 401, False),
        ({"aud": "optikit"}, 401, False),
        ({"iss": f"{ISSUER}-other"}, 401, False),
        ({"exp": 0}, 401, False),
        ({"sub": "unlinked"}, 403, False),
        ({}, 403, True),
    ],
)
def test_oidc_rejects_invalid_or_unauthorized_identity(
    client: TestClient,
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
    overrides: dict[str, str | int],
    status: int,
    disabled: bool,
) -> None:
    """Only current Keycloak identities linked to an enabled user can sign in."""
    claims: dict[str, str | int] = {}
    mock_provider(monkeypatch, signing_key, claims)
    store.link_oidc_identity("operator", ISSUER, SUBJECT)
    store.set_disabled("operator", disabled)
    body, query = begin(client)
    claims.update({"nonce": query["nonce"][0], **overrides})
    assert client.post("/auth/oidc/complete", json=body).status_code == status


def test_oidc_outage_preserves_password_login(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed provider leaves password login available and can recover in place."""
    reachable = False

    def discovery(request: httpx.Request) -> httpx.Response:
        if not reachable:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json={"issuer": ISSUER})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        oidc.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(discovery), **kwargs),
    )
    assert client.get("/auth/oidc/enabled").json() == {"enabled": True, "issuer": ISSUER}
    unavailable = client.get("/auth/oidc/availability")
    assert unavailable.json() == {"available": False}
    assert unavailable.headers["cache-control"] == "no-store"
    assert client.post("/auth/oidc/start").status_code == 503
    assert client.post("/auth/login", auth=("operator", "local-password")).status_code == 200

    reachable = True
    assert client.get("/auth/oidc/availability").json() == {"available": True}
    client.app.state.oidc_config = None
    assert client.get("/auth/oidc/enabled").json() == {"enabled": False}
    assert client.get("/auth/oidc/availability").status_code == 404
    assert client.post("/auth/oidc/start").status_code == 404


def begin_link(
    client: TestClient, headers: dict[str, str], claims: dict[str, str | int]
) -> dict[str, str]:
    """Start a link and set the fake provider's nonce to match the attempt."""
    reply = client.post(
        "/auth/oidc/link/start", json={"current_password": "local-password"}, headers=headers
    )
    assert reply.status_code == 200
    flow = reply.json()
    query = parse_qs(urlsplit(flow["authorization_url"]).query)
    assert query["prompt"] == ["login"]
    assert query["scope"] == ["openid profile"]
    claims["nonce"] = query["nonce"][0]
    return {"state": flow["state"], "proof": flow["proof"], "code": "test-code"}


def test_link_requires_local_password_same_session_and_explicit_confirmation(
    client: TestClient,
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
) -> None:
    """Linking cannot replace sign-in, and only the original session can confirm."""
    claims: dict[str, str | int] = {"preferred_username": "central-user"}
    mock_provider(monkeypatch, signing_key, claims)
    headers = {"Authorization": f"Bearer {store.create_session('operator')}"}
    other_session = {"Authorization": f"Bearer {store.create_session('operator')}"}
    path = "/auth/oidc/link"
    assert (
        client.post(f"{path}/start", json={"current_password": "local-password"}).status_code == 401
    )
    wrong_password = client.post(
        f"{path}/start", json={"current_password": "wrong"}, headers=headers
    )
    assert wrong_password.status_code == 403

    attempt = begin_link(client, headers, claims)
    assert client.post("/auth/oidc/complete", json=attempt).status_code == 401
    assert client.post(f"{path}/preview", json=attempt, headers=other_session).status_code == 400
    result = client.post(f"{path}/preview", json=attempt, headers=headers)
    assert result.status_code == 200
    preview = result.json()
    assert (preview["local_username"], preview["account_name"]) == ("operator", "central-user")
    assert client.get(path, headers=headers).json() == {"linked": False}
    assert store.create_oidc_session(ISSUER, SUBJECT) is None

    confirmation = {"ticket": preview["ticket"]}
    assert (
        client.post(f"{path}/confirm", json=confirmation, headers=other_session).status_code == 400
    )
    assert client.post(f"{path}/confirm", json=confirmation, headers=headers).status_code == 204
    assert client.post(f"{path}/confirm", json=confirmation, headers=headers).status_code == 400
    assert client.get(path, headers=headers).json() == {"linked": True}
    session = store.resolve_session(store.create_oidc_session(ISSUER, SUBJECT))
    assert session is not None and session.username == "operator" and session.role is Role.OPERATOR


def test_revoked_session_cannot_confirm_link(
    client: TestClient,
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
) -> None:
    """Logging out cancels confirmation even if the same person signs back in."""
    claims: dict[str, str | int] = {}
    mock_provider(monkeypatch, signing_key, claims)
    token = store.create_session("operator")
    headers = {"Authorization": f"Bearer {token}"}
    attempt = begin_link(client, headers, claims)
    preview = client.post("/auth/oidc/link/preview", json=attempt, headers=headers).json()
    store.revoke_session(token)

    fresh_session = {"Authorization": f"Bearer {store.create_session('operator')}"}
    response = client.post(
        "/auth/oidc/link/confirm", json={"ticket": preview["ticket"]}, headers=fresh_session
    )
    assert response.status_code == 400
    assert client.get("/auth/oidc/link", headers=fresh_session).json() == {"linked": False}


def test_link_does_not_reassign_an_existing_identity(
    client: TestClient,
    store: UserStore,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
) -> None:
    """A user cannot take an identity linked to a different account at the instrument."""
    claims: dict[str, str | int] = {}
    mock_provider(monkeypatch, signing_key, claims)
    owner = store.create_user("existing-owner", "owner-password", Role.VIEWER)
    store.link_oidc_identity(owner.username, ISSUER, SUBJECT)
    headers = {"Authorization": f"Bearer {store.create_session('operator')}"}
    path = "/auth/oidc/link"
    attempt = begin_link(client, headers, claims)
    preview = client.post(f"{path}/preview", json=attempt, headers=headers).json()
    confirmation = {"ticket": preview["ticket"]}

    assert client.post(f"{path}/confirm", json=confirmation, headers=headers).status_code == 409
    assert store.oidc_linked_user_ids(ISSUER) == {owner.id}
    assert client.post(f"{path}/confirm", json=confirmation, headers=headers).status_code == 400


def test_admin_can_unlink_offline_and_revoke_sessions(client: TestClient, store: UserStore) -> None:
    """Only a device admin can remove a link, even if OIDC is disabled."""
    store.create_user("device-admin", "admin-password", Role.ADMIN)
    store.link_oidc_identity("operator", ISSUER, SUBJECT)
    token = store.create_session("operator")
    admin_headers = {"Authorization": f"Bearer {store.create_session('device-admin')}"}
    path = "/auth/users/operator/oidc"
    client.app.state.oidc_config = None

    listed = {
        user["username"]: user for user in client.get("/auth/users", headers=admin_headers).json()
    }
    assert listed["operator"]["oidc_linked"]
    assert not listed["device-admin"]["oidc_linked"]
    assert client.delete(path, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.delete(path, headers=admin_headers).status_code == 204
    assert store.resolve_session(token) is None
    assert store.create_oidc_session(ISSUER, SUBJECT) is None
    assert client.post("/auth/login", auth=("operator", "local-password")).status_code == 200
