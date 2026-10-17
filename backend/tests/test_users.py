"""Tests for the SQLite-backed user/role store and its authenticator.

`UserStore` is the persistence layer behind `UserStoreAuthenticator`; these tests hit
it directly (accounts, roles, sessions) and then once more through the authenticator
protocol, which is the seam `create_app` actually uses.
"""

import sqlite3
from pathlib import Path
import time

import pytest
from argon2.exceptions import VerifyMismatchError

from newswitch.auth import UserStoreAuthenticator
from newswitch.users import (
    Role,
    User,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserStore,
)


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    """A fresh store backed by a throwaway database file."""
    return UserStore(tmp_path / "auth.db")


# --------------------------------------------------------------------------- accounts


def test_new_store_is_empty(store: UserStore) -> None:
    """A freshly created database has no accounts yet."""
    assert store.is_empty()
    assert store.list_users() == []


@pytest.mark.parametrize("role", list(Role))
def test_create_user_for_every_role(store: UserStore, role: Role) -> None:
    """All four roles can be assigned to a new account."""
    user = store.create_user("alice", "hunter2", role)
    assert user == User(id=user.id, username="alice", role=role, disabled=False)
    assert not store.is_empty()


def test_duplicate_username_is_rejected(store: UserStore) -> None:
    """Two accounts cannot share a username."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    with pytest.raises(UserAlreadyExistsError):
        store.create_user("alice", "different", Role.VIEWER)


def test_invalid_role_is_rejected_at_the_database_level(store: UserStore) -> None:
    """The CHECK constraint is a second line of defence behind the `Role` enum."""
    with store._connect() as connection, pytest.raises(Exception):  # noqa: PT011
        connection.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("mallory", "hash", "superuser"),
        )


def test_get_user_returns_none_for_unknown_username(store: UserStore) -> None:
    """Looking up a nonexistent account is not an error."""
    assert store.get_user("nobody") is None


def test_list_users_is_ordered_by_username(store: UserStore) -> None:
    """A stable, predictable order for any future admin UI."""
    store.create_user("bob", "pw", Role.VIEWER)
    store.create_user("alice", "pw", Role.ADMIN)
    assert [user.username for user in store.list_users()] == ["alice", "bob"]


def test_set_role_changes_the_role(store: UserStore) -> None:
    """Promoting/demoting an account updates what it can do."""
    store.create_user("alice", "hunter2", Role.VIEWER)
    store.set_role("alice", Role.ANALYST)
    assert store.get_user("alice").role == Role.ANALYST


def test_set_role_on_unknown_user_raises(store: UserStore) -> None:
    """A typo'd username must not silently do nothing."""
    with pytest.raises(UserNotFoundError):
        store.set_role("nobody", Role.ADMIN)


def test_delete_user_removes_the_account(store: UserStore) -> None:
    """A deleted account can no longer be found."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    store.delete_user("alice")
    assert store.get_user("alice") is None


def test_delete_unknown_user_raises(store: UserStore) -> None:
    """Deleting a nonexistent account is an error, not a no-op."""
    with pytest.raises(UserNotFoundError):
        store.delete_user("nobody")


# ---------------------------------------------------------------------- credentials


def test_verify_password_accepts_the_right_password(store: UserStore) -> None:
    """A correct password resolves to the account."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    user = store.verify_password("alice", "hunter2")
    assert user is not None
    assert user.username == "alice"


def test_verify_password_rejects_the_wrong_password(store: UserStore) -> None:
    """A wrong password resolves to nothing."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    assert store.verify_password("alice", "wrong") is None


def test_verify_password_rejects_an_unknown_username(store: UserStore) -> None:
    """An unknown username fails the same way as a wrong password."""
    assert store.verify_password("nobody", "hunter2") is None


def test_passwords_are_hashed_not_stored_in_plain_text(store: UserStore) -> None:
    """The stored hash never equals the password, and does not verify against another."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("alice",)
        ).fetchone()
    assert row["password_hash"] != "hunter2"
    from argon2 import PasswordHasher

    with pytest.raises(VerifyMismatchError):
        PasswordHasher().verify(row["password_hash"], "wrong")


def test_change_password_revokes_existing_sessions(store: UserStore) -> None:
    """A password change must not leave old sessions valid."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    token = store.create_session("alice")
    store.change_password("alice", "newpassword")
    assert store.resolve_session(token) is None
    assert store.verify_password("alice", "newpassword") is not None
    assert store.verify_password("alice", "hunter2") is None


def test_disabling_a_user_revokes_sessions_and_blocks_login(store: UserStore) -> None:
    """A disabled account can neither log in again nor keep an existing session."""
    store.create_user("alice", "hunter2", Role.VIEWER)
    token = store.create_session("alice")
    store.set_disabled("alice", True)
    assert store.resolve_session(token) is None
    assert store.verify_password("alice", "hunter2") is None


# -------------------------------------------------------------------------- sessions


def test_old_session_schema_is_migrated_to_include_last_used_at(tmp_path: Path) -> None:
    """Older auth databases need a one-time migration so logins keep working."""
    db_path = tmp_path / "auth.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer', 'analyst')),
                disabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        connection.execute(
            """
            CREATE TABLE sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at INTEGER NOT NULL
            );
            """
        )

    store = UserStore(db_path)
    store.create_user("alice", "hunter2", Role.OPERATOR)
    token = store.create_session("alice")

    with store._connect() as connection:
        row = connection.execute(
            "SELECT last_used_at FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()

    assert row is not None
    assert row["last_used_at"] > 0


def test_sessions_are_random_and_distinct(store: UserStore) -> None:
    """Two logins for the same account must not collide or reuse a token."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    first = store.create_session("alice")
    second = store.create_session("alice")
    assert first != second


def test_resolve_session_returns_the_owning_account(store: UserStore) -> None:
    """A valid token resolves back to its account."""
    store.create_user("alice", "hunter2", Role.ANALYST)
    token = store.create_session("alice")
    user = store.resolve_session(token)
    assert user is not None
    assert user.username == "alice"
    assert user.role == Role.ANALYST


def test_resolve_session_rejects_an_unknown_token(store: UserStore) -> None:
    """A token that was never issued grants nothing."""
    assert store.resolve_session("not-a-real-token") is None


def test_resolve_session_rejects_none(store: UserStore) -> None:
    """A missing token is handled without raising."""
    assert store.resolve_session(None) is None


def test_revoke_session_invalidates_only_that_session(store: UserStore) -> None:
    """Logging out one session must not log out a second one for the same account."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    first = store.create_session("alice")
    second = store.create_session("alice")
    store.revoke_session(first)
    assert store.resolve_session(first) is None
    assert store.resolve_session(second) is not None


def test_deleting_a_user_removes_their_sessions(store: UserStore) -> None:
    """Sessions cannot outlive the account they belong to."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    token = store.create_session("alice")
    store.delete_user("alice")
    assert store.resolve_session(token) is None


# ------------------------------------------------------------------- authenticator


def test_authenticator_login_issues_a_working_session(store: UserStore) -> None:
    """The authenticator's login/check_token round-trip matches the store."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    authenticator = UserStoreAuthenticator(store)
    token = authenticator.login(_basic_header("alice", "hunter2"))
    assert authenticator.check_token(token)
    assert authenticator.username_for_token(token) == "alice"


def test_authenticator_rejects_wrong_credentials(store: UserStore) -> None:
    """A wrong password must not issue a session."""
    from rekuest_next.contrib.fastapi.auth import AuthenticationError

    store.create_user("alice", "hunter2", Role.OPERATOR)
    authenticator = UserStoreAuthenticator(store)
    with pytest.raises(AuthenticationError):
        authenticator.login(_basic_header("alice", "wrong"))


def test_authenticator_logout_revokes_only_that_session(store: UserStore) -> None:
    """Logging out through the authenticator behaves like `UserStore.revoke_session`."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    authenticator = UserStoreAuthenticator(store)
    first = authenticator.login(_basic_header("alice", "hunter2"))
    second = authenticator.login(_basic_header("alice", "hunter2"))
    authenticator.logout(first)
    assert not authenticator.check_token(first)
    assert authenticator.check_token(second)


def _basic_header(username: str, password: str) -> str:
    import base64

    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


# ------------------------------------------------------------------- session TTLs


def test_session_ttls_default_to_fourteen_and_thirty_days(store: UserStore) -> None:
    """Generous idle timeout, hard cap on total lifetime - see the module docstring."""
    assert store.idle_seconds == 14 * 24 * 60 * 60
    assert store.absolute_seconds == 30 * 24 * 60 * 60


def test_session_ttls_are_configurable_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator can tune both without touching code."""
    monkeypatch.setenv("NEWSWITCH_SESSION_IDLE_DAYS", "1")
    monkeypatch.setenv("NEWSWITCH_SESSION_ABSOLUTE_DAYS", "2")
    store = UserStore(tmp_path / "auth.db")
    assert store.idle_seconds == 1 * 24 * 60 * 60
    assert store.absolute_seconds == 2 * 24 * 60 * 60


def test_an_idle_session_expires(store: UserStore) -> None:
    """A session nobody has used in longer than the idle window is dropped."""
    store.idle_seconds = 1
    store.create_user("alice", "hunter2", Role.OPERATOR)
    token = store.create_session("alice")
    with store._connect() as connection:
        connection.execute(
            "UPDATE sessions SET last_used_at = ? WHERE token = ?",
            (int(time.time()) - 10, token),
        )
    assert store.resolve_session(token) is None


def test_an_expired_session_is_recorded_in_the_audit_trail(store: UserStore) -> None:
    """TTL expiry is a login event too, not just a silent session deletion."""
    store.idle_seconds = 1
    store.create_user("alice", "hunter2", Role.OPERATOR)
    token = store.create_session("alice")
    with store._connect() as connection:
        connection.execute(
            "UPDATE sessions SET last_used_at = ? WHERE token = ?",
            (int(time.time()) - 10, token),
        )
    store.resolve_session(token)
    events = store.list_login_events()
    assert [event.event for event in events] == ["session_expired"]
    assert events[0].username == "alice"


def test_an_active_session_still_expires_at_the_absolute_limit(store: UserStore) -> None:
    """Constant activity does not let a session outlive the absolute ceiling."""
    store.absolute_seconds = 1
    store.create_user("alice", "hunter2", Role.OPERATOR)
    token = store.create_session("alice")
    with store._connect() as connection:
        connection.execute(
            "UPDATE sessions SET created_at = ?, last_used_at = ? WHERE token = ?",
            (int(time.time()) - 10, int(time.time()), token),
        )
    assert store.resolve_session(token) is None


def test_resolving_a_session_touches_last_used_at(store: UserStore) -> None:
    """Activity resets the idle clock - what makes idle timeout "idle" at all."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    token = store.create_session("alice")
    stale = int(time.time()) - 5
    with store._connect() as connection:
        connection.execute("UPDATE sessions SET last_used_at = ? WHERE token = ?", (stale, token))
    store.resolve_session(token)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT last_used_at FROM sessions WHERE token = ?", (token,)
        ).fetchone()
    assert row["last_used_at"] > stale


# ---------------------------------------------------------------------- audit trail


def test_authenticator_records_login_success(store: UserStore) -> None:
    """A correct login is recorded."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    UserStoreAuthenticator(store).login(_basic_header("alice", "hunter2"))
    events = store.list_login_events()
    assert len(events) == 1
    assert events[0].username == "alice"
    assert events[0].event == "login_success"


def test_authenticator_records_login_failure(store: UserStore) -> None:
    """A wrong password is recorded too - what an audit trail is for."""
    from rekuest_next.contrib.fastapi.auth import AuthenticationError

    store.create_user("alice", "hunter2", Role.OPERATOR)
    with pytest.raises(AuthenticationError):
        UserStoreAuthenticator(store).login(_basic_header("alice", "wrong"))
    events = store.list_login_events()
    assert len(events) == 1
    assert events[0].event == "login_failure"


def test_authenticator_records_logout(store: UserStore) -> None:
    """Logging out is recorded against the account that owned the session."""
    store.create_user("alice", "hunter2", Role.OPERATOR)
    authenticator = UserStoreAuthenticator(store)
    token = authenticator.login(_basic_header("alice", "hunter2"))
    authenticator.logout(token)
    events = store.list_login_events()
    assert [event.event for event in events] == ["logout", "login_success"]


def test_list_login_events_is_newest_first(store: UserStore) -> None:
    """The audit view reads top-to-bottom as a timeline, most recent on top."""
    store.record_login_event("alice", "login_success")
    store.record_login_event("alice", "logout")
    events = store.list_login_events()
    assert [event.event for event in events] == ["logout", "login_success"]


# ------------------------------------------------------------------- admin headcount


def test_count_enabled_admins(store: UserStore) -> None:
    """The guard rail that prevents a config from locking every admin out."""
    assert store.count_enabled_admins() == 0
    store.create_user("alice", "pw", Role.ADMIN)
    store.create_user("bob", "pw", Role.ADMIN)
    store.create_user("carol", "pw", Role.VIEWER)
    assert store.count_enabled_admins() == 2
    store.set_disabled("bob", True)
    assert store.count_enabled_admins() == 1
