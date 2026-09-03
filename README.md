# newswitch

ABSOLUTELY ALPHA

"Imswitch but new". This repo bears almost no resemblance to the original codebase, but aims to provide a
more web-stack-friendly, modern, and maintainable foundation for the same functionality.


## Quickstart

You need Python 3.11+ with uv and Node 20+. The repo uses [just](https://just.systems/man/en/) for task automation. Install it, then:

```bash
just install     # uv sync + yarn install
just dev         # backend , then frontend (will autocodegen)-> http://localhost:5173
```

Run `just` on its own to see every recipe. Both ports come from the committed root `.env` — see
[Environment](#environment).

## The one rule: the backend comes up first

The frontend is **generated from the backend**. On every `vite dev` and `vite build`, the plugin at
`frontend/plugins/generate-app.ts` fetches three schema endpoints from a *running* backend —
`/schemas/implementations`, `/schemas/states`, `/schemas/locks` — and regenerates the typed hooks in
`frontend/src/apps/default/**` along with `frontend/blok.json`.

If the backend is **not** reachable, the codegen does **not** fail. It warns and silently falls back to
the committed generated files. 

> **If you start the frontend without the backend, you are developing against stale hooks and nothing will
> stop you.** `just dev` sequences the two and warns loudly if the backend never came up.

`frontend/blok.json` and `frontend/src/apps/default/**` are **committed on purpose**. Don't gitignore them.


## Common recipes

```bash
just install                 # install both halves + activate git hooks
just dev                     # both, correctly sequenced
just dev-backend             # backend only  -> :$BACKEND_PORT  (hot-reloads on edit)
just dev-frontend            # frontend only -> :$FRONTEND_PORT (backend must already be up)

just check                   # fmt-check + lint + types + tests
just fmt                     # ruff format + prettier, in place
just lint                    # ruff + eslint
just types                   # tsc against tsconfig.app.json
just test                    # pytest + vitest
just test-all                # also runs the backend integration tests
just drift-check             # is the committed codegen still in sync with the backend?

just build                   # frontend bundle + backend wheel/sdist
just clean                   # nuke .venv, node_modules, dist

just list-users               # list every account and its role (run on the appliance)
just reset-password user pw   # recovery: set a new password for an existing account
just create-admin user pw     # recovery: create a fresh admin account
```

### Codegen drift

Because the generator falls back silently, committed hooks can quietly diverge from the backend.
`just drift-check` (and the `codegen-drift` CI job) boots the backend, regenerates, and fails if the
result differs from what's committed. If it fails, run `just dev-backend`, then `cd frontend && yarn build`,
and commit the regenerated output.

### End-to-end tests with Playwright

The browser-based end-to-end tests cover authentication and user-management workflows. They run
against an isolated local backend/frontend stack and a disposable authentication database; no
manually started development server is required.

Install the Chromium browser once after installing the project dependencies:

```bash
cd frontend
yarn playwright install chromium
```

Run the tests from `frontend/`:

```bash
yarn e2e          # headless test run
yarn e2e:ui       # interactive Playwright UI
yarn e2e:headed   # run with a visible browser
yarn e2e:debug    # step through tests with the Playwright Inspector
yarn e2e:report   # open the HTML report from the latest run
```

Tests live in `frontend/e2e/`, with shared helpers in `frontend/e2e/fixtures/`. Failed tests retain
screenshots, traces, and videos in `frontend/test-results/`; the HTML report is written to
`frontend/playwright-report/`. The CI workflow runs the same suite for backend or frontend changes
and uploads these diagnostics as an artifact when a run fails.

The E2E suite currently uses one shared disposable authentication database, so Playwright is
configured for a single worker and serial execution. See `frontend/playwright.config.ts` for the
complete runtime configuration.

### Commits

Commit messages must be [conventional](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `chore:`,
etc. This is enforced by a commit-msg hook (installed by `just install`) because the release version and
changelog are derived from them: a malformed message means no release, or the wrong bump.

## Docker

```bash
just up          # docker compose up --build
just down
just down-hard   # ALSO drops the named volumes - see below
just logs
```

Compose is the one path with **no schema race**: the frontend's `depends_on` waits on a backend
healthcheck. The probe hits `/health`, which is public and needs no credentials; because uvicorn
serves nothing until startup completes, a healthy backend is also one whose schema endpoints answer.


## Authentication

The app sits behind a login backed by a small multi-user account store — several accounts, each with
one role (`admin`/`operator`/`viewer`/`analyst`). Accounts and sessions live in a SQLite file,
`backend/auth.db`, gitignored and created automatically on first run. See
[backend/docs/AUTH_DESIGN.md](backend/docs/AUTH_DESIGN.md) for the full design note (seeding, roles,
sessions, audit trail).

On a completely fresh clone, with no accounts yet, the backend seeds one `admin` account from the
legacy single-account file if present:

```bash
cp backend/auth.example.yaml backend/auth.yaml   # optional, then edit the password
```

With no `auth.yaml` and no `NEWSWITCH_AUTH_FILE` it seeds `admin`/`admin` and logs a warning, so a fresh
clone runs without setup — change that password once logged in. This seed only ever runs once, the
first time the account store is empty; `auth.yaml` is irrelevant again afterwards.

Once accounts exist, admins manage them from the UI (Account menu → Manage users) or the admin HTTP
API (`/auth/users`). For dev/debug work or a locked-out appliance where the web UI is unreachable, use
the recovery CLI (SSH or local shell only — it talks to the database directly, bypassing HTTP auth):

```bash
just list-users                       # every account and its role
just reset-password alice new-pass    # forgotten password: set a new one, revokes its sessions
just create-admin rescue rescue-pass  # every admin locked out: create a fresh one
```

### How it works

`POST /auth/login` takes HTTP Basic, checks the password (argon2) against `backend/auth.db`, and returns
a random, revocable session token — unlike the legacy single-account token, a restart does *not* log
everyone out, but `POST /auth/logout` (or a password change) revokes just that one session. The
frontend keeps the token in `localStorage` until logout.

The token then has to reach the backend over transports that carry credentials differently, because a
browser will only let you set headers on some of them:

| Channel | Carries the token as |
|---|---|
| `fetch` calls | `Authorization: Bearer <token>` |
| Websockets (`/ws`, `/stream/*`) | the first message after connect - a `WebSocket` cannot set headers |
| Images and zarr chunks | `?token=` - three.js' `TextureLoader` and zarrita cannot set headers either |

`/health`, `/auth/login` and `/schemas/*` stay public. `/schemas/*` has to be - the frontend's codegen
reads it at build time, before anyone could have logged in - and it exposes only the shape of the API,
no data and no control.

A rejected websocket closes with code **1008**, which the frontend treats as "log out", distinct from a
dropped connection it should retry.


## Environment

### Ports live in the root `.env`

Every port is defined **once**, in the committed root `.env` (defaults, not secrets):

```dotenv
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8099
FRONTEND_PORT=5173
```

It propagates everywhere from there:

| Consumer | How it reads the file |
| --- | --- |
| `just` | `set dotenv-load` — exported into every recipe, and used for `wait-backend`'s health URL |
| `docker compose` | interpolation for the published ports, plus an `environment:` block so the value also reaches inside each container |
| `frontend/.env`, `.env.docker` | `${BACKEND_PORT:-8099}` in the URLs; an exported value wins, the fallback keeps a bare `yarn dev` working |
| `vite.config.ts` | `server.port` / `preview.port` from `FRONTEND_PORT` |
| backend | `os.environ` in `newswitch.app:main` and `backend/test.py`; the Dockerfile sets matching `ENV` defaults |
| CI | a "Load the ports from .env" step exports them into `$GITHUB_ENV` |

To change a port for one run, export it — a shell variable beats the file in all of the above:

```bash
BACKEND_PORT=9000 just dev      # backend, health check, codegen URLs and vite all follow
BACKEND_PORT=9000 just up       # same for compose (published port + container port)
```

To change it for good, edit the root `.env`. One caveat: `frontend/blok.json` records the schema URLs it
was generated from, ports included, so a *permanent* port change means regenerating and committing it.
An ad-hoc `BACKEND_PORT=... yarn dev` will dirty that file — `git checkout -- frontend/blok.json` after.
CI is unaffected: it reads the same `.env`.

### Frontend URLs

`frontend/.env` holds committed, non-secret **localhost defaults** whose ports interpolate the root `.env`.
To point at a different machine, create an untracked `frontend/.env.local` (it overrides `.env`, and is
gitignored):

```dotenv
VITE_BACKEND_URL=http://my-lab-box:${BACKEND_PORT:-8099}
VITE_WEBSOCKET_URL=ws://my-lab-box:${BACKEND_PORT:-8099}/ws
VITE_SCHEMA_IMPLEMENTATION_URL=http://my-lab-box:${BACKEND_PORT:-8099}/schemas/implementations
VITE_SCHEMA_STATES_URL=http://my-lab-box:${BACKEND_PORT:-8099}/schemas/states
VITE_SCHEMA_LOCKS_URL=http://my-lab-box:${BACKEND_PORT:-8099}/schemas/locks
```

Apart from `BACKEND_HOST` / `BACKEND_PORT`, the backend reads no `.env` — the rest is configured in code
via `ImswitchConfig` (`backend/newswitch/app.py`).

## Releases

One version for the whole repo, one tag (`vX.Y.Z`), **GitHub Releases only**.

Pushing [conventional commits](https://www.conventionalcommits.org/) to `main` triggers
`.github/workflows/release.yml`, which runs semantic-release from the root `release.config.cjs`. It bumps
`backend/pyproject.toml` **and** `frontend/package.json` to the same version, rebuilds the frontend *after*

Preview what a release would do, without tagging or pushing:

```bash
just release-dry
```


A full local dry run also needs a `GITHUB_TOKEN` in the environment (the GitHub plugin verifies auth even
in `--dry-run`). In CI, both the URL and the token come from the Actions checkout automatically.

