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

from newswitch.users import (
    OIDCIdentityConflictError,
    Role,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserStore,
)


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

    link_oidc = subparsers.add_parser("link-oidc", help="Link a Keycloak identity to a local user.")
    link_oidc.add_argument("username")
    link_oidc.add_argument("issuer")
    link_oidc.add_argument("subject")

    unlink_oidc = subparsers.add_parser("unlink-oidc", help="Remove a Keycloak identity link.")
    unlink_oidc.add_argument("username")
    unlink_oidc.add_argument("issuer")

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

    if args.command == "link-oidc":
        try:
            store.link_oidc_identity(args.username, args.issuer.rstrip("/"), args.subject)
        except UserNotFoundError:
            print(f"No such user: {args.username}", file=sys.stderr)
            return 1
        except OIDCIdentityConflictError:
            print("The identity or local user is already linked for this issuer.", file=sys.stderr)
            return 1
        print(f"Linked Keycloak identity for '{args.username}'.")
        return 0

    if args.command == "unlink-oidc":
        if not store.unlink_oidc_identity(args.username, args.issuer.rstrip("/")):
            print(f"No link for '{args.username}' and this issuer.", file=sys.stderr)
            return 1
        print(f"Removed the link for '{args.username}' and revoked its sessions.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
