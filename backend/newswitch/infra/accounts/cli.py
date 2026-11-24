"""Command-line recovery for the account database.

Run directly on the appliance (local shell or SSH) when the web UI is unreachable -
every admin locked out, a forgotten password, or a corrupted role. Talks to the
`UserStore` directly, bypassing HTTP auth entirely, which is why this is not exposed
over the network: whoever can run this already has full access to the machine.

    uv run python -m newswitch.infra.accounts.cli list-users
    uv run python -m newswitch.infra.accounts.cli reset-password alice new-password
    uv run python -m newswitch.infra.accounts.cli create-admin rescue rescue-password
"""

from __future__ import annotations

import argparse

from newswitch.infra.accounts.store import (
    Role,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserStore,
)
from newswitch.logging_setup import console, setup_logging

#: What this tool reports: to stdout (errors to stderr), and into the log file.
report = console("accounts")


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m newswitch.infra.accounts.cli`."""
    setup_logging()
    parser = argparse.ArgumentParser(prog="python -m newswitch.infra.accounts.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-users", help="Print every account and its role.")

    reset_password = subparsers.add_parser(
        "reset-password", help="Set a new password for an existing account."
    )
    reset_password.add_argument("username")
    reset_password.add_argument("password")

    create_admin = subparsers.add_parser("create-admin", help="Create a new admin account.")
    create_admin.add_argument("username")
    create_admin.add_argument("password")

    args = parser.parse_args(argv)
    store = UserStore()

    if args.command == "list-users":
        for user in store.list_users():
            state = "disabled" if user.disabled else "enabled"
            report.info("%s\t%s\t%s", user.username, user.role.value, state)
        return 0

    if args.command == "reset-password":
        try:
            store.change_password(args.username, args.password)
        except UserNotFoundError:
            report.error("No such user: %s", args.username)
            return 1
        report.info("Password for '%s' has been reset; its sessions were revoked.", args.username)
        return 0

    if args.command == "create-admin":
        try:
            store.create_user(args.username, args.password, Role.ADMIN)
        except UserAlreadyExistsError:
            report.error("'%s' already exists.", args.username)
            return 1
        report.info("Created admin account '%s'.", args.username)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
