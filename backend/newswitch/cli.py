"""Command-line recovery for the account database.

Run directly on the appliance (local shell or SSH) when the web UI is unreachable -
every admin locked out, a forgotten password, or a corrupted role. Talks to the
`UserStore` directly, bypassing HTTP auth entirely, which is why this is not exposed
over the network: whoever can run this already has full access to the machine.

    uv run python -m newswitch.cli list-users
    uv run python -m newswitch.cli reset-password alice new-password
    uv run python -m newswitch.cli create-admin rescue rescue-password
"""

from __future__ import annotations

import argparse
import sys

from newswitch.users import Role, UserAlreadyExistsError, UserNotFoundError, UserStore


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m newswitch.cli`."""
    parser = argparse.ArgumentParser(prog="python -m newswitch.cli")
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
            print(f"{user.username}\t{user.role.value}\t{state}")
        return 0

    if args.command == "reset-password":
        try:
            store.change_password(args.username, args.password)
        except UserNotFoundError:
            print(f"No such user: {args.username}", file=sys.stderr)
            return 1
        print(f"Password for '{args.username}' has been reset; its sessions were revoked.")
        return 0

    if args.command == "create-admin":
        try:
            store.create_user(args.username, args.password, Role.ADMIN)
        except UserAlreadyExistsError:
            print(f"'{args.username}' already exists.", file=sys.stderr)
            return 1
        print(f"Created admin account '{args.username}'.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
