"""Tests for the account/role/audit management HTTP API.

Layered on top of `test_auth.py`'s gating tests: everything here assumes a caller
already has a valid session token and checks the role/ownership rules on top of that.
"""

import base64
from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from newswitch.app import ImswitchConfig, create_app
from newswitch.auth import CredentialAuthenticator, Credentials, UserStoreAuthenticator
from newswitch.users import Role, UserStore


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    """A store with one admin and one operator, ready to log in."""
    store = UserStore(tmp_path / "auth.db")
    store.create_user("admin", "adminpw", Role.ADMIN)
    store.create_user("alice", "alicepw", Role.OPERATOR)
    return store


@pytest.fixture
def client(store: UserStore) -> Iterator[TestClient]:
    """A client wired to a `UserStoreAuthenticator` over `store`."""
    app: FastAPI = create_app(ImswitchConfig(), authenticator=UserStoreAuthenticator(store))
    with TestClient(app) as test_client:
        yield test_client


def admin_headers(store: UserStore) -> dict[str, str]:
    """A fresh session for the seeded admin account."""
    return {"Authorization": f"Bearer {store.create_session('admin')}"}


def alice_headers(store: UserStore) -> dict[str, str]:
    """A fresh session for the seeded non-admin account."""
    return {"Authorization": f"Bearer {store.create_session('alice')}"}


def basic_header(username: str, password: str) -> dict[str, str]:
    """Build an HTTP Basic header the way a browser would."""
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


# --------------------------------------------------------------------------- /auth/me


def test_me_returns_the_caller(client: TestClient, store: UserStore) -> None:
    """The frontend uses this to know who is logged in and whether to show admin UI."""
    response = client.get("/auth/me", headers=alice_headers(store))
    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": "operator", "disabled": False}


def test_me_requires_a_token(client: TestClient) -> None:
    """No caller identity without a session."""
    assert client.get("/auth/me").status_code == 401


# ---------------------------------------------------------------------- self-service


def test_change_my_password_returns_a_working_replacement_token(
    client: TestClient, store: UserStore
) -> None:
    """Changing your own password must not lock you out of the request that did it."""
    old_headers = alice_headers(store)
    response = client.post(
        "/auth/me/password",
        json={"current_password": "alicepw", "new_password": "newpw"},
        headers=old_headers,
    )
    assert response.status_code == 200
    new_token = response.json()["token"]

    assert client.get("/auth/me", headers=old_headers).status_code == 401
    assert (
        client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
    )
    assert store.verify_password("alice", "newpw") is not None


def test_change_my_password_rejects_a_wrong_current_password(
    client: TestClient, store: UserStore
) -> None:
    """The current password must be proven, not just a valid session."""
    response = client.post(
        "/auth/me/password",
        json={"current_password": "wrong", "new_password": "newpw"},
        headers=alice_headers(store),
    )
    assert response.status_code == 401
    assert store.verify_password("alice", "alicepw") is not None


# -------------------------------------------------------------------------- listing


def test_non_admin_cannot_list_users(client: TestClient, store: UserStore) -> None:
    """User management is admin-only."""
    assert client.get("/auth/users", headers=alice_headers(store)).status_code == 403


def test_admin_can_list_users(client: TestClient, store: UserStore) -> None:
    """The seeded accounts come back, without password hashes."""
    response = client.get("/auth/users", headers=admin_headers(store))
    assert response.status_code == 200
    assert {user["username"] for user in response.json()} == {"admin", "alice"}


# -------------------------------------------------------------------------- creation


def test_admin_can_create_a_user(client: TestClient, store: UserStore) -> None:
    """The core of user management: an admin provisions a new account."""
    response = client.post(
        "/auth/users",
        json={"username": "bob", "password": "bobpw", "role": "viewer"},
        headers=admin_headers(store),
    )
    assert response.status_code == 201
    assert store.verify_password("bob", "bobpw") is not None


def test_creating_a_duplicate_username_is_rejected(client: TestClient, store: UserStore) -> None:
    """Two accounts cannot share a username through the API either."""
    response = client.post(
        "/auth/users",
        json={"username": "alice", "password": "pw", "role": "viewer"},
        headers=admin_headers(store),
    )
    assert response.status_code == 409


def test_creating_a_user_with_an_invalid_role_is_rejected(
    client: TestClient, store: UserStore
) -> None:
    """Only the four defined roles are acceptable input."""
    response = client.post(
        "/auth/users",
        json={"username": "bob", "password": "pw", "role": "superuser"},
        headers=admin_headers(store),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------- update


def test_admin_can_change_a_role(client: TestClient, store: UserStore) -> None:
    """Promoting/demoting a non-admin account is unrestricted."""
    response = client.patch(
        "/auth/users/alice", json={"role": "analyst"}, headers=admin_headers(store)
    )
    assert response.status_code == 200
    assert store.get_user("alice").role == Role.ANALYST


def test_admin_can_disable_a_user(client: TestClient, store: UserStore) -> None:
    """Disabling revokes the account's ability to log in or keep a session."""
    response = client.patch(
        "/auth/users/alice", json={"disabled": True}, headers=admin_headers(store)
    )
    assert response.status_code == 200
    assert store.get_user("alice").disabled is True


def test_updating_an_unknown_user_is_a_404(client: TestClient, store: UserStore) -> None:
    """A typo'd username in the URL is an error, not a silent no-op."""
    response = client.patch(
        "/auth/users/nobody", json={"role": "viewer"}, headers=admin_headers(store)
    )
    assert response.status_code == 404


def test_cannot_demote_the_last_admin(client: TestClient, store: UserStore) -> None:
    """The system may never end up with zero admins able to log in."""
    response = client.patch(
        "/auth/users/admin", json={"role": "viewer"}, headers=admin_headers(store)
    )
    assert response.status_code == 400
    assert store.get_user("admin").role == Role.ADMIN


def test_cannot_disable_the_last_admin(client: TestClient, store: UserStore) -> None:
    """Disabling has the same lockout potential as demoting."""
    response = client.patch(
        "/auth/users/admin", json={"disabled": True}, headers=admin_headers(store)
    )
    assert response.status_code == 400


def test_demoting_an_admin_is_fine_with_a_second_admin(
    client: TestClient, store: UserStore
) -> None:
    """The guard is about the *count*, not about any specific account."""
    store.create_user("root", "rootpw", Role.ADMIN)
    response = client.patch(
        "/auth/users/admin", json={"role": "viewer"}, headers=admin_headers(store)
    )
    assert response.status_code == 200


# --------------------------------------------------------------- admin password reset


def test_admin_can_reset_another_users_password(client: TestClient, store: UserStore) -> None:
    """Recovery path for a non-admin who forgot their password - no CLI access needed."""
    stale_headers = alice_headers(store)
    response = client.post(
        "/auth/users/alice/password", json={"password": "resetpw"}, headers=admin_headers(store)
    )
    assert response.status_code == 200
    assert store.verify_password("alice", "resetpw") is not None
    # existing sessions do not survive a reset
    assert client.get("/auth/me", headers=stale_headers).status_code == 401


def test_non_admin_cannot_reset_a_password(client: TestClient, store: UserStore) -> None:
    """Only admins may reset someone else's password."""
    response = client.post(
        "/auth/users/admin/password", json={"password": "pw"}, headers=alice_headers(store)
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------- delete


def test_admin_can_delete_a_non_admin_user(client: TestClient, store: UserStore) -> None:
    """The end of the account lifecycle."""
    response = client.delete("/auth/users/alice", headers=admin_headers(store))
    assert response.status_code == 204
    assert store.get_user("alice") is None


def test_admin_cannot_delete_their_own_account(client: TestClient, store: UserStore) -> None:
    """Self-deletion mid-session is refused rather than left to work oddly."""
    response = client.delete("/auth/users/admin", headers=admin_headers(store))
    assert response.status_code == 400
    assert store.get_user("admin") is not None


def test_deleting_the_last_admin_via_another_account_is_refused(
    client: TestClient, store: UserStore
) -> None:
    """The lockout guard applies to deletion, not just demotion/disabling."""
    store.create_user("root", "rootpw", Role.ADMIN)
    # "root" deletes "admin": fine, one admin remains.
    root_headers = {"Authorization": f"Bearer {store.create_session('root')}"}
    assert client.delete("/auth/users/admin", headers=root_headers).status_code == 204
    # Now only "root" is left, and it cannot delete itself either way.
    assert client.delete("/auth/users/root", headers=root_headers).status_code == 400


def test_deleting_an_unknown_user_is_a_404(client: TestClient, store: UserStore) -> None:
    """Consistent with `update_user`'s handling of an unknown username."""
    response = client.delete("/auth/users/nobody", headers=admin_headers(store))
    assert response.status_code == 404


# ----------------------------------------------------------------------------- audit


def test_admin_can_read_the_audit_log(client: TestClient, store: UserStore) -> None:
    """The audit trail surfaces through the API for admins."""
    client.post("/auth/login", headers=basic_header("alice", "alicepw"))
    response = client.get("/auth/audit", headers=admin_headers(store))
    assert response.status_code == 200
    events = response.json()
    assert any(
        event["username"] == "alice" and event["event"] == "login_success" for event in events
    )


def test_non_admin_cannot_read_the_audit_log(client: TestClient, store: UserStore) -> None:
    """The audit trail is not for every account to see."""
    assert client.get("/auth/audit", headers=alice_headers(store)).status_code == 403


# --------------------------------------------------------------- legacy authenticator


def test_user_management_is_unavailable_without_a_user_store(tmp_path: Path) -> None:
    """`CredentialAuthenticator`'s single YAML account has no store to manage."""
    credentials = Credentials(username="a", password="b")
    legacy_app = create_app(ImswitchConfig(), authenticator=CredentialAuthenticator(credentials))
    with TestClient(legacy_app) as legacy_client:
        response = legacy_client.get(
            "/auth/users", headers={"Authorization": f"Bearer {credentials.token}"}
        )
    assert response.status_code == 404
