"""Authentication for the newswitch backend.

Two authenticators exist side by side, both behind the same `Authenticator` protocol:

- `CredentialAuthenticator` checks the single account in `auth.yaml` and issues one
  deterministic token (`sha256("username:password")`) - no database, no session
  store, still used directly by tests that want a fixed, predictable token.
- `UserStoreAuthenticator` (the default `create_app` wires up) checks a real user
  table in `newswitch.users.UserStore` - several accounts, each with a role - and
  issues a random, revocable session token per login. On first run, with no accounts
  yet, it seeds one admin account from `auth.yaml` (or the `admin`/`admin` default),
  so a fresh clone still runs without setup.

A client exchanges credentials once at `POST /auth/login` (HTTP Basic) for a token,
then presents the token on every later call, and can give it back at `POST /auth/logout`.

Three transports need three ways to carry that token, because a browser can only set
headers on some of them:

- `fetch` calls send `Authorization: Bearer <token>`.
- `WebSocket` cannot set headers at all, so the token rides in the first frame the
  client sends (see `expand_user_from_request` and `authenticate_stream_websocket`).
- `<img>`, three.js `TextureLoader` and zarrita likewise cannot set headers, so those
  URLs carry `?token=<token>`.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs

import yaml
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from fastapi.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from rekuest_next.contrib.fastapi.auth import AuthenticationError, UserSource
from rekuest_next.contrib.fastapi.models import WebSocketSubscriptionInit

from newswitch.users import Role, UserStore

logger = logging.getLogger(__name__)

#: Environment variable naming the credentials file. When set, the file must exist -
#: a typo in a deployment must fail loudly rather than fall back to a default login.
AUTH_FILE_ENV_VAR = "NEWSWITCH_AUTH_FILE"

#: Default location, alongside `pyproject.toml` in the backend directory.
DEFAULT_AUTH_FILE = Path(__file__).resolve().parent.parent / "auth.yaml"

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"

#: Reachable without a token. `/schemas/*` stays public because the frontend's build
#: -time codegen reads it before any user could log in, and it exposes only the shape
#: of the API - no data and no control.
PUBLIC_PATHS = frozenset({"/health", "/auth/login"})
PUBLIC_PATH_PREFIXES = ("/schemas/",)


class Credentials(BaseModel):
    """The one username/password pair this backend accepts.

    Doubles as the schema for `auth.yaml`, so a malformed file is rejected by the
    same rules that guard the in-process value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("username", "password", mode="before")
    @classmethod
    def _coerce_to_text(cls, value: object) -> object:
        """Accept unquoted YAML scalars.

        `password: 1234` parses as an int and `password: yes` as a bool, neither of
        which a strict `str` field would accept - so the file would be rejected for
        containing a perfectly reasonable password.
        """
        if isinstance(value, (int, float, bool)):
            return str(value)
        return value

    @property
    def token(self) -> str:
        """The opaque token issued for these credentials."""
        digest = hashlib.sha256(f"{self.username}:{self.password}".encode()).hexdigest()
        return digest


def load_credentials(path: str | os.PathLike[str] | None = None) -> Credentials:
    """Read credentials from YAML, falling back to a warned-about default.

    Args:
        path: Explicit file to read. Defaults to `$NEWSWITCH_AUTH_FILE`, then to
            `backend/auth.yaml`.

    Raises:
        RuntimeError: If a file was named explicitly but cannot be read or is
            missing a username or password. A misconfigured deployment must not
            silently accept the default login.
    """
    explicit = path is not None or AUTH_FILE_ENV_VAR in os.environ
    auth_file = Path(path or os.environ.get(AUTH_FILE_ENV_VAR) or DEFAULT_AUTH_FILE)

    if not auth_file.is_file():
        if explicit:
            raise RuntimeError(f"Credentials file not found: {auth_file}")
        logger.warning(
            "No credentials file at %s - falling back to %s/%s. "
            "Copy auth.example.yaml to auth.yaml before exposing this instance.",
            auth_file,
            DEFAULT_USERNAME,
            DEFAULT_PASSWORD,
        )
        return Credentials(username=DEFAULT_USERNAME, password=DEFAULT_PASSWORD)

    try:
        parsed = yaml.safe_load(auth_file.read_text()) or {}
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"Could not read credentials file {auth_file}") from error

    try:
        return Credentials.model_validate(parsed)
    except ValidationError as error:
        raise RuntimeError(f"{auth_file} is not a valid credentials file: {error}") from error


class Authenticator(Protocol):
    """Decides whether a credential is acceptable."""

    def check_token(self, token: str | None) -> bool:
        """Return whether `token` grants access."""
        ...

    def login(self, authorization_header: str | None) -> str:
        """Exchange an HTTP Basic header for a token.

        Raises:
            AuthenticationError: If the header is absent, malformed, or wrong.
        """
        ...

    def username_for_token(self, token: str | None) -> str | None:
        """Return the username `token` belongs to, or `None` if it grants nothing."""
        ...

    def logout(self, token: str | None) -> None:
        """Invalidate `token`, if this authenticator can revoke individual ones."""
        ...


class CredentialAuthenticator:
    """Checks credentials against a single `Credentials` pair."""

    def __init__(self, credentials: Credentials) -> None:
        """Accept exactly the given username/password pair."""
        self.credentials = credentials
        self._token = credentials.token

    def check_token(self, token: str | None) -> bool:
        """Return whether `token` matches the issued token."""
        if not token:
            return False
        return secrets.compare_digest(token, self._token)

    def login(self, authorization_header: str | None) -> str:
        """Validate an `Authorization: Basic ...` header and issue the token."""
        username, password = _parse_basic_header(authorization_header)
        # Both halves are always compared, so a wrong username and a wrong password
        # take the same path.
        username_ok = secrets.compare_digest(username, self.credentials.username)
        password_ok = secrets.compare_digest(password, self.credentials.password)
        if not (username_ok & password_ok):
            raise AuthenticationError("Invalid username or password")
        return self._token

    def username_for_token(self, token: str | None) -> str | None:
        """Return the one account's username, if `token` is its token."""
        return self.credentials.username if self.check_token(token) else None

    def logout(self, token: str | None) -> None:
        """No-op: the one deterministic token stays valid until the password changes."""


class AllowAllAuthenticator:
    """Accepts everything. For tests, which drive the app in-process."""

    def check_token(self, token: str | None) -> bool:
        """Accept any token, including none at all."""
        return True

    def login(self, authorization_header: str | None) -> str:
        """Issue a fixed placeholder token."""
        return "test-token"

    def username_for_token(self, token: str | None) -> str | None:
        """Attribute every request to the same placeholder user."""
        return "user"

    def logout(self, token: str | None) -> None:
        """No-op: tests do not model logout."""


class UserStoreAuthenticator:
    """Checks credentials and tokens against a `UserStore` of several accounts.

    Unlike `CredentialAuthenticator`'s single deterministic token, `login` mints a
    random session row per login, so `logout` can revoke exactly one session without
    logging out every other account - or every other tab of the same account.
    """

    def __init__(self, store: UserStore) -> None:
        """Authenticate against `store`."""
        self.store = store

    def check_token(self, token: str | None) -> bool:
        """Return whether `token` is a live, unexpired session."""
        return self.store.resolve_session(token) is not None

    def login(self, authorization_header: str | None) -> str:
        """Validate an `Authorization: Basic ...` header and issue a session token."""
        username, password = _parse_basic_header(authorization_header)
        user = self.store.verify_password(username, password)
        if user is None:
            raise AuthenticationError("Invalid username or password")
        return self.store.create_session(user.username)

    def username_for_token(self, token: str | None) -> str | None:
        """Return the username the session `token` belongs to."""
        user = self.store.resolve_session(token)
        return user.username if user else None

    def logout(self, token: str | None) -> None:
        """Revoke a single session."""
        self.store.revoke_session(token)


def default_authenticator() -> UserStoreAuthenticator:
    """Build the production authenticator: a `UserStore`, seeded on first run.

    An empty store means a fresh deployment, so it is seeded with one admin account
    from the legacy `auth.yaml` (or the `admin`/`admin` default) - the same zero-setup
    behaviour `CredentialAuthenticator` used to provide on its own.
    """
    store = UserStore()
    if store.is_empty():
        credentials = load_credentials()
        store.create_user(credentials.username, credentials.password, Role.ADMIN)
        logger.warning(
            "No accounts in %s - seeded '%s' as an admin from the legacy credentials "
            "file. Change its password once logged in.",
            store.path,
            credentials.username,
        )
    return UserStoreAuthenticator(store)


def _parse_basic_header(header: str | None) -> tuple[str, str]:
    """Split an `Authorization: Basic <base64>` header into username and password.

    Parsed by hand rather than with `fastapi.security.HTTPBasic`, which attaches a
    `WWW-Authenticate` header to its 401 and makes the browser open its own credential
    dialog on top of the application's login page.
    """
    if not header:
        raise AuthenticationError("Missing Authorization header")

    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        raise AuthenticationError("Expected an HTTP Basic Authorization header")

    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise AuthenticationError("Malformed HTTP Basic credentials") from error

    username, separator, password = decoded.partition(":")
    if not separator:
        raise AuthenticationError("Malformed HTTP Basic credentials")
    return username, password


def bearer_token(header: str | None) -> str | None:
    """Extract the token from an `Authorization: Bearer ...` header."""
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token or None


def make_expand_user_from_request(
    authenticator: Authenticator,
) -> Callable[[UserSource], Any]:
    """Build the hook rekuest uses to authenticate both of its transports.

    The websocket arm reads the token from the init payload rather than a header,
    because browsers cannot set headers on a `WebSocket` handshake.
    """

    def expand_user_from_request(source: UserSource) -> str:
        if isinstance(source, WebSocketSubscriptionInit):
            token = source.token
        else:
            token = bearer_token(source.headers.get("authorization")) or (
                source.query_params.get("token")
            )
        username = authenticator.username_for_token(token)
        if username is None:
            raise AuthenticationError("Invalid or missing token")
        return username

    return expand_user_from_request


def is_public_path(path: str) -> bool:
    """Return whether `path` is reachable without a token."""
    if path in PUBLIC_PATHS:
        return True
    return path.startswith(PUBLIC_PATH_PREFIXES)


class AuthMiddleware:
    """Requires a valid token on every HTTP request outside `PUBLIC_PATHS`.

    Written against the raw ASGI interface rather than Starlette's
    `BaseHTTPMiddleware`, which returns early for any non-`http` scope - a shape that
    invites the assumption that it guards websockets too.

    It does not: websocket scopes pass straight through here, because both websocket
    endpoints authenticate *in band*, one frame after the handshake. Rejecting a
    websocket before it is accepted fails the HTTP upgrade, which browsers report as
    an opaque close code 1006 that a client cannot tell apart from a network drop.
    Accepting first and then closing with 1008 gives the client a code it can act on.
    """

    def __init__(self, app: ASGIApp, authenticator: Authenticator) -> None:
        """Wrap `app`, gating it behind `authenticator`."""
        self.app = app
        self.authenticator = authenticator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Gate an HTTP request, or pass any other scope through untouched."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Preflight carries no credentials by design; CORSMiddleware answers it.
        if scope.get("method") == "OPTIONS" or is_public_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        if self.authenticator.check_token(_token_from_scope(scope)):
            await self.app(scope, receive, send)
            return

        # Answered rather than raised: the error middleware sits outside CORS, so an
        # exception here would reach the browser as a header-less 500 that shows up as
        # an opaque CORS failure instead of a 401.
        response = JSONResponse({"detail": "Not authenticated"}, status_code=401)
        await response(scope, receive, send)


def _token_from_scope(scope: Scope) -> str | None:
    """Read the token from an `Authorization` header or a `token` query parameter.

    The query parameter serves the callers that cannot set headers: three.js'
    `TextureLoader` and zarrita's fetch store.
    """
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name == b"authorization":
            token = bearer_token(raw_value.decode("latin-1"))
            if token:
                return token
            break

    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    tokens = query.get("token")
    return tokens[0] if tokens else None


router = APIRouter(tags=["Auth"])


@router.post("/auth/login")
async def login(request: Request) -> JSONResponse:
    """Exchange HTTP Basic credentials for a token."""
    authenticator: Authenticator = request.app.state.authenticator
    try:
        token = authenticator.login(request.headers.get("authorization"))
    except AuthenticationError:
        # Deliberately no `WWW-Authenticate` header - see `_parse_basic_header`.
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)
    return JSONResponse({"token": token, "token_type": "bearer"})


@router.post("/auth/logout", status_code=204)
async def logout(request: Request) -> Response:
    """Revoke the caller's session, if the authenticator tracks individual ones.

    Not in `PUBLIC_PATHS`: revoking a session requires presenting it, the same as any
    other authenticated call.
    """
    authenticator: Authenticator = request.app.state.authenticator
    token = bearer_token(request.headers.get("authorization"))
    authenticator.logout(token)
    return Response(status_code=204)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe.

    Public and free of dependencies on `app.state.agent`, so container healthchecks
    do not need credentials and do not double as a readiness check on the agent.
    """
    return {"status": "ok"}
