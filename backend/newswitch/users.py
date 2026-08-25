"""Persistent, multi-user storage for accounts and roles.

Where `auth.py` issues one deterministic token for the single account in `auth.yaml`,
this module backs a real user table: several accounts, each with a role, stored in a
SQLite file next to the backend (`backend/auth.db`, gitignored like `auth.yaml`).
Passwords are hashed with argon2 rather than compared in plaintext, and logging in
creates a random, revocable session row instead of deriving a token from the password
- which is what makes revoking a single login (a real "log out") possible.

The file is generated state, not hand-authored config, so - unlike `auth.yaml` - it is
created automatically wherever it is pointed at, including at an explicit
`NEWSWITCH_AUTH_DB` path.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterator

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

#: Environment variable overriding where the user database lives.
AUTH_DB_ENV_VAR = "NEWSWITCH_AUTH_DB"

#: Default location, alongside `pyproject.toml` in the backend directory.
DEFAULT_AUTH_DB = Path(__file__).resolve().parent.parent / "auth.db"

#: How long an unused session stays valid - generous, since a lab operator can be
#: away from the instrument for hours without wanting to log back in. Mostly a
#: cleanup mechanism for sessions nobody is using anymore, not a working limit.
SESSION_IDLE_DAYS_ENV_VAR = "NEWSWITCH_SESSION_IDLE_DAYS"
DEFAULT_SESSION_IDLE_DAYS = 14

#: Hard ceiling on a session's lifetime regardless of activity - what actually
#: guarantees a token cannot live forever, even if it is used every day.
SESSION_ABSOLUTE_DAYS_ENV_VAR = "NEWSWITCH_SESSION_ABSOLUTE_DAYS"
DEFAULT_SESSION_ABSOLUTE_DAYS = 30

_hasher = PasswordHasher()


def _env_days(env_var: str, default_days: int) -> int:
    """Read a day count from an environment variable, in seconds."""
    raw = os.environ.get(env_var)
    days = int(raw) if raw else default_days
    return days * 24 * 60 * 60


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer', 'analyst')),
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER NOT NULL
);

-- Append-only: a login attempt or logout is a fact, never edited or owned by a
-- user row, so it survives even a since-deleted account.
CREATE TABLE IF NOT EXISTS login_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    event TEXT NOT NULL CHECK (
        event IN ('login_success', 'login_failure', 'logout', 'session_expired')
    ),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Role(StrEnum):
    """The fixed set of roles a user can hold.

    A closed set rather than free-form strings or a many-to-many `roles` table: with
    four roles and one role per account, a join table would add complexity for
    flexibility nothing here needs yet.
    """

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    ANALYST = "analyst"


class UserAlreadyExistsError(Exception):
    """Raised by `UserStore.create_user` for a username already taken."""


class UserNotFoundError(Exception):
    """Raised for operations on a username that does not exist."""


@dataclass(frozen=True)
class User:
    """A stored account, without its password hash."""

    id: int
    username: str
    role: Role
    disabled: bool


@dataclass(frozen=True)
class LoginEvent:
    """One row of the append-only login audit trail."""

    username: str
    event: str
    created_at: str


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        role=Role(row["role"]),
        disabled=bool(row["disabled"]),
    )


class UserStore:
    """SQLite-backed accounts, roles and login sessions.

    Every method opens its own short-lived connection rather than holding one open -
    SQLite handles that cheaply, and it sidesteps thread- or async-safety questions for
    what is, on this single-instrument appliance, an occasional write plus one lookup
    per request.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        """Open the database at `path`, `$NEWSWITCH_AUTH_DB`, or the default, creating it if needed."""
        self.path = Path(path or os.environ.get(AUTH_DB_ENV_VAR) or DEFAULT_AUTH_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.idle_seconds = _env_days(SESSION_IDLE_DAYS_ENV_VAR, DEFAULT_SESSION_IDLE_DAYS)
        self.absolute_seconds = _env_days(
            SESSION_ABSOLUTE_DAYS_ENV_VAR, DEFAULT_SESSION_ABSOLUTE_DAYS
        )
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()

    def is_empty(self) -> bool:
        """Whether no account has been created yet - the signal to seed a first admin."""
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return row is None

    def create_user(self, username: str, password: str, role: Role) -> User:
        """Create a new account. Raises `UserAlreadyExistsError` for a taken username."""
        password_hash = _hasher.hash(password)
        with self._connect() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, password_hash, role.value),
                )
            except sqlite3.IntegrityError as error:
                raise UserAlreadyExistsError(username) from error
        return User(id=cursor.lastrowid, username=username, role=role, disabled=False)

    def get_user(self, username: str) -> User | None:
        """Look up an account by name, or `None` if it does not exist."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, role, disabled FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return _row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        """All accounts, ordered by username."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, username, role, disabled FROM users ORDER BY username"
            ).fetchall()
        return [_row_to_user(row) for row in rows]

    def set_role(self, username: str, role: Role) -> None:
        """Change an account's role. Raises `UserNotFoundError` for an unknown username."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET role = ? WHERE username = ?", (role.value, username)
            )
            if cursor.rowcount == 0:
                raise UserNotFoundError(username)

    def set_disabled(self, username: str, disabled: bool) -> None:
        """Disable or re-enable an account. Disabling revokes its sessions immediately."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET disabled = ? WHERE username = ?",
                (int(disabled), username),
            )
            if cursor.rowcount == 0:
                raise UserNotFoundError(username)
            if disabled:
                connection.execute(
                    "DELETE FROM sessions WHERE user_id = "
                    "(SELECT id FROM users WHERE username = ?)",
                    (username,),
                )

    def change_password(self, username: str, new_password: str) -> None:
        """Set a new password and revoke every existing session for the account."""
        password_hash = _hasher.hash(new_password)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
            if cursor.rowcount == 0:
                raise UserNotFoundError(username)
            connection.execute(
                "DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = ?)",
                (username,),
            )

    def delete_user(self, username: str) -> None:
        """Remove an account and its sessions. Raises `UserNotFoundError` if unknown."""
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM users WHERE username = ?", (username,))
            if cursor.rowcount == 0:
                raise UserNotFoundError(username)

    def count_enabled_admins(self) -> int:
        """How many non-disabled admin accounts exist.

        Callers use this to refuse an edit that would leave zero admins able to log
        in - the one lockout the CLI recovery tool cannot fix without wiping every
        account (see `newswitch.cli`).
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role = ? AND disabled = 0",
                (Role.ADMIN.value,),
            ).fetchone()
        return row["count"]

    def verify_password(self, username: str, password: str) -> User | None:
        """Return the account if `password` is correct and it is not disabled."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash, role, disabled FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None or row["disabled"]:
            return None
        try:
            _hasher.verify(row["password_hash"], password)
        except VerifyMismatchError:
            return None
        return User(
            id=row["id"],
            username=row["username"],
            role=Role(row["role"]),
            disabled=bool(row["disabled"]),
        )

    def create_session(self, username: str) -> str:
        """Issue a new random session token for `username`."""
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions (token, user_id, created_at, last_used_at) "
                "SELECT ?, id, ?, ? FROM users WHERE username = ?",
                (token, now, now, username),
            )
        return token

    def resolve_session(self, token: str | None) -> User | None:
        """Return the account a session token belongs to, or `None` if it is invalid.

        A session that has outlived either TTL is deleted here rather than merely
        rejected, so an idle or ancient token cannot be resurrected by touching it
        again. A still-valid session has its `last_used_at` bumped, which is what
        makes the idle timeout "idle" rather than a fixed clock from login.
        """
        if not token:
            return None
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.username, users.role, users.disabled,
                       sessions.created_at, sessions.last_used_at
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ?
                """,
                (token,),
            ).fetchone()
            if row is None:
                return None
            expired = (
                row["disabled"]
                or now - row["created_at"] > self.absolute_seconds
                or now - row["last_used_at"] > self.idle_seconds
            )
            if expired:
                connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
                return None
            connection.execute("UPDATE sessions SET last_used_at = ? WHERE token = ?", (now, token))
        return _row_to_user(row)

    def revoke_session(self, token: str | None) -> None:
        """Drop a single session. A no-op for a missing or unknown token."""
        if not token:
            return
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def record_login_event(self, username: str, event: str) -> None:
        """Append one row to the login audit trail.

        Takes a bare username rather than a `User`, so a failed login for an
        unknown or misspelled username is still recorded - that is the case an
        audit trail exists to catch.
        """
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO login_events (username, event) VALUES (?, ?)",
                (username, event),
            )

    def list_login_events(self, limit: int = 200) -> list[LoginEvent]:
        """The most recent login events, newest first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT username, event, created_at FROM login_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            LoginEvent(username=row["username"], event=row["event"], created_at=row["created_at"])
            for row in rows
        ]
