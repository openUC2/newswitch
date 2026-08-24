"""Tests for the SQLite-backed user/role store and its authenticator.

`UserStore` is the persistence layer behind `UserStoreAuthenticator`; these tests hit
it directly (accounts, roles, sessions) and then once more through the authenticator
protocol, which is the seam `create_app` actually uses.
"""

from pathlib import Path

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
