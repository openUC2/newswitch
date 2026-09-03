"""Tests for the CLI recovery tool.

`main()` is called directly (not via subprocess) so these run at unit-test speed;
`newswitch.cli`'s own `UserStore()` call picks up `NEWSWITCH_AUTH_DB` from the
environment exactly like it would when invoked as `python -m newswitch.cli`.
"""

from pathlib import Path

import pytest

from newswitch.cli import main
from newswitch.users import Role, UserStore


@pytest.fixture(autouse=True)
def auth_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every CLI invocation in this file at a throwaway database."""
    db_path = tmp_path / "auth.db"
    monkeypatch.setenv("NEWSWITCH_AUTH_DB", str(db_path))
    return db_path


def test_list_users_prints_every_account(auth_db: Path, capsys: pytest.CaptureFixture) -> None:
    """Output is a simple, greppable tab-separated table."""
    UserStore(auth_db).create_user("alice", "hunter2", Role.VIEWER)

    assert main(["list-users"]) == 0
    assert "alice\tviewer\tenabled" in capsys.readouterr().out


def test_reset_password_changes_the_password(auth_db: Path) -> None:
    """The documented recovery path for a forgotten password."""
    UserStore(auth_db).create_user("alice", "old-password", Role.OPERATOR)

    assert main(["reset-password", "alice", "new-password"]) == 0

    store = UserStore(auth_db)
    assert store.verify_password("alice", "new-password") is not None
    assert store.verify_password("alice", "old-password") is None


def test_reset_password_reports_an_unknown_user(
    auth_db: Path, capsys: pytest.CaptureFixture
) -> None:
    """A typo'd username fails loudly rather than doing nothing."""
    assert main(["reset-password", "nobody", "new-password"]) == 1
    assert "No such user" in capsys.readouterr().err


def test_create_admin_creates_an_enabled_admin(auth_db: Path) -> None:
    """The documented recovery path when every admin is locked out."""
    assert main(["create-admin", "rescue", "hunter2"]) == 0

    user = UserStore(auth_db).get_user("rescue")
    assert user is not None
    assert user.role == Role.ADMIN
    assert not user.disabled


def test_create_admin_reports_an_existing_username(
    auth_db: Path, capsys: pytest.CaptureFixture
) -> None:
    """Two accounts cannot share a username here either."""
    UserStore(auth_db).create_user("rescue", "pw", Role.VIEWER)

    assert main(["create-admin", "rescue", "hunter2"]) == 1
    assert "already exists" in capsys.readouterr().err
