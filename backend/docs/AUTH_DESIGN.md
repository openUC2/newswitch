# Design note: accounts, seeding, and roles

This is the current state of user-account handling in newswitch: what's stored where, how a fresh
install gets its first login, and how access levels ("groups") are modelled. It reflects the code as
it stands, not a target design — see "Deferred" at the end for known gaps.

## One authenticator, plus a test double

`backend/newswitch/auth.py` defines an `Authenticator` protocol (`check_token`, `login`,
`username_for_token`, `logout`). Production code has exactly one implementation:

- `UserStoreAuthenticator` — what `create_app`/`default_authenticator()` wires up. Backed by
  `newswitch.users.UserStore`, a real multi-account table with random, individually-revocable
  session tokens.

`AllowAllAuthenticator` is a second, no-op implementation that accepts everything; it exists only
for tests that drive the app in-process without exercising the login gate at all. There used to be a
third, `CredentialAuthenticator` (a single hardcoded username/password from `auth.yaml`, one
deterministic token, no database) — removed once `UserStoreAuthenticator` covered every case it did,
since keeping two production-shaped authenticators side by side was one artifact too many for an app
this early in its life. `auth.yaml`/`auth.example.yaml` survive only as the source of the one-time
admin seed described below.

Both sit behind `AuthMiddleware`, an ASGI middleware that gates every HTTP request outside
`PUBLIC_PATHS` (`/health`, `/auth/login`, `/schemas/*`). Websocket scopes pass through the middleware
untouched and authenticate in-band instead — the first frame after connect carries the token, because
a `WebSocket` handshake cannot carry custom headers. A rejected websocket is accepted and then closed
with code 1008, which the frontend can tell apart from a dropped connection worth retrying.

## Storage: `backend/auth.db`

`newswitch/users.py` owns a small SQLite database, gitignored like the legacy `auth.yaml`, created
automatically wherever it's pointed (default `backend/auth.db`, overridable via `NEWSWITCH_AUTH_DB`).
Three tables:

- **`users`** — `id`, `username` (unique), `password_hash` (argon2, via `argon2.PasswordHasher`),
  `role` (`CHECK` constraint, one of `admin`/`operator`/`viewer`/`analyst`), `disabled`, `created_at`.
  One role per user — there is no `roles` join table.
- **`sessions`** — `token` (primary key, `secrets.token_urlsafe(32)`), `user_id`, `created_at`,
  `last_used_at`. A row per login, not per user, so logging out one browser tab doesn't touch another.
- **`login_events`** — append-only audit trail (`login_success`, `login_failure`, `logout`,
  `session_expired`), keyed by username rather than `user_id` so a failed login for an unknown or
  since-deleted account is still recorded.

`UserStore` opens a short-lived connection per method call, serialized by a `threading.Lock`. That's
adequate for a single-appliance, low-traffic deployment; it deliberately isn't built for concurrent
multi-process access.

### Sessions expire two ways

- **Idle timeout** — `sessions.last_used_at` is bumped on every successful `resolve_session`; a
  session unused for `NEWSWITCH_SESSION_IDLE_DAYS` (default 14) is dropped.
- **Absolute timeout** — measured from `created_at`; a session older than
  `NEWSWITCH_SESSION_ABSOLUTE_DAYS` (default 30) is dropped no matter how active it's been.

Either check happening inside `resolve_session` deletes the row and logs a `session_expired` event
rather than merely rejecting the token, so an expired session can't be resurrected by touching it again.

## Seeding: how the first account appears

`default_authenticator()` is the only place seeding happens:

```
store = UserStore()
if store.is_empty():
    credentials = load_credentials()   # auth.yaml, or admin/admin default
    store.create_user(credentials.username, credentials.password, Role.ADMIN)
```

- It only runs when `users` has zero rows — i.e. a genuinely fresh `auth.db`. Once any account exists
  (including one created by hand, or by the recovery CLI), this path never fires again.
- The seed credentials come from the *legacy* single-account file, `backend/auth.yaml` (copy of
  `auth.example.yaml`), read via `load_credentials()`. If that file doesn't exist and
  `NEWSWITCH_AUTH_FILE` isn't set, it falls back to `admin`/`admin` and logs a warning — the same
  zero-setup behaviour the old single-account scheme had.
- After seeding, `auth.yaml` has no further effect. It is not re-read, not kept in sync, and editing it
  does not affect existing accounts — that file is consulted exactly once, at the moment `auth.db` is
  first created.
- There is no seed data beyond that one admin — no default operator/viewer accounts, no fixtures. Every
  other account is created explicitly, either through the admin UI/API or the CLI.

## "Groups": role-based, not group-based

There is no separate groups table or many-to-many membership. Access levels are the fixed `Role` enum
(`admin`, `operator`, `viewer`, `analyst`), stored as one column on `users`. In effect the four roles
*are* the groups: a `CHECK` constraint closes the set, and `UserStore.set_role` reassigns a user from
one to another wholesale — there's no notion of a user belonging to several roles at once, and no
custom/ad-hoc roles.

Only `admin` is enforced anywhere today:

- `require_admin` (`backend/newswitch/routes/http/users.py`) gates the entire account-management API —
  listing/creating/editing/deleting users, resetting passwords, reading the audit log.
- `UserStore.count_enabled_admins()` guards against removing the last admin: `PATCH .../users/{u}`
  and `DELETE .../users/{u}` both refuse an edit that would leave zero enabled admins, and `DELETE`
  additionally refuses to let an admin delete their own account.
- `operator`/`viewer`/`analyst` exist as selectable roles and are surfaced in the UI (`UsersPage.tsx`),
  but nothing in the backend currently branches on them — no route or manager checks for anything but
  admin-or-not. They're groundwork for finer-grained authorization, not yet load-bearing.

## Managing accounts

Two ways to reach the same `UserStore`:

- **Admin HTTP API** (`backend/newswitch/routes/http/users.py`, mounted under `/auth/*`): `GET/POST
  /auth/users`, `PATCH/DELETE /auth/users/{username}`, `POST /auth/users/{username}/password` (admin
  resets someone else's password), `GET /auth/me`, `POST /auth/me/password` (self-service; returns a
  fresh token since changing your own password revokes the session that asked). 404s entirely if the
  app's authenticator isn't `UserStoreAuthenticator` — legacy/test authenticators have no accounts to
  manage. Surfaced in the frontend as the Account menu → "Manage users" / "Audit log" pages, guarded by
  `RequireAdmin`.
- **Recovery CLI** (`backend/newswitch/cli.py`, `python -m newswitch.cli ...`, wrapped by
  `just list-users` / `just reset-password` / `just create-admin`): talks to `UserStore` directly,
  bypassing HTTP auth entirely. Meant to be run on the appliance itself (local shell or SSH) for the
  cases the web UI can't help with — every admin locked out, a forgotten password, a corrupted role.
  It is deliberately not exposed over the network: whoever can run it already has full access to the
  machine.

## Deferred / known gaps

- One role per user, no custom roles, no fine-grained permissions beyond admin-or-not.
- No rate-limiting or lockout on repeated failed logins (only recorded in `login_events`).
- No self-registration — every account is created by an admin or the CLI.
- No multi-process-safe writes beyond the in-process lock (fine for the single-appliance deployment
  target; would need revisiting for horizontal scaling).
