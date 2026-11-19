# newswitch

ABSOLUTELY ALPHA

"Imswitch but new". This repo bears almost no resemblance to the original codebase, but aims to provide a
more web-stack-friendly, modern, and maintainable foundation for the same functionality.


## Quickstart

You need Python 3.11+ with uv and Node 20+. The repo uses [just](https://just.systems/man/en/) for task automation. Install it, then:

```bash
just install     # uv sync + yarn install
just dev         # mikro (docker), backend, then frontend (will autocodegen) -> http://localhost:5473
```

Run `just` on its own to see every recipe. Both ports come from the committed root `.env` — see
[Environment](#environment).

## The one rule: re-export the schemas when the API changes

The frontend's typed hooks are **generated from the backend's schemas** — but not from a running backend.
What a backend registers depends on its instrument (`create_registry` in
`backend/newswitch/microscope/registry.py`), while the hooks must cover everything newswitch can do. So the
schemas come from a committed export of a *complete* microscope:

```bash
just export-schemas   # = cd backend && uv run python -m newswitch.infra.export_schemas
```

builds the app registry in-process on the reference microscope
`backend/newswitch/reference/complete-microscope/` (everything a microscope can have, no bloks; it
refuses an instrument lacking any of it), takes a snapshot of it — nothing is started — and writes exactly what a
FastAPI backend on it serves at `/schemas/implementations`, `/schemas/states` and `/schemas/locks` into
`frontend/schemas/{implementations,states,locks}.json`. It is the mirror of the blok catalog, which the
frontend exports for the backend.

On every `vite dev` and `vite build`, the plugin at `frontend/plugins/generate-app.ts` reads only those files
(paths set in `frontend/vite.config.ts`) and regenerates the typed hooks in `frontend/src/apps/default/**`.
No backend is needed for codegen, so `just dev` works on any instrument
(e.g. `NEWSWITCH_CONFIG=instruments/cam-test just dev`) without
rewriting the generated hooks. A missing export file fails the build and points at `just export-schemas`.

> **After changing an action, state or lock, run `just export-schemas`** — otherwise the frontend keeps
> generating from the old export. `just drift-check` catches it.

`frontend/schemas/` and `frontend/src/apps/default/**` are **committed on purpose**.
Don't gitignore them.


## Common recipes

```bash
just install                 # install both halves + activate git hooks
just dev                     # FastAPI mode: mikro (docker), backend and frontend, correctly sequenced
just dev-backend             # FastAPI mode, backend only (with mikro) -> :$BACKEND_PORT (hot-reloads on edit)
just dev-frontend            # frontend only -> :$FRONTEND_PORT (codegen needs no backend)
just agent --url <server>    # agent mode: the arkitekt app alone; mikro and the UI come from the server
just mikro / just mikro-down # start / stop the mikro stack alone (it outlives `just dev`)

just check                   # fmt-check + lint + types + tests
just fmt                     # ruff format + prettier, in place
just lint                    # ruff + eslint
just types                   # tsc against tsconfig.app.json
just test                    # pytest + vitest
just test-all                # also runs the backend integration tests
just export-schemas          # write the complete microscope's schemas into frontend/schemas/
just drift-check             # are the committed export and codegen still in sync with the backend?

just build                   # frontend bundle + backend wheel/sdist
just clean                   # nuke .venv, node_modules, dist

just list-users               # list every account and its role (run on the appliance)
just reset-password user pw   # recovery: set a new password for an existing account
just create-admin user pw     # recovery: create a fresh admin account

just agent                    # serve as an arkitekt agent instead (see below)
```

### Two ways to serve: FastAPI or arkitekt agent

newswitch can be served two ways, each its own entry file. Both read the same settings and
instrument (`load_devices` in `backend/newswitch/settings.py`) and call
`create_registry` (`backend/newswitch/microscope/registry.py`), which registers the contexts
`FrameSink`, the detectors send their frames to, and `DatasetStore`, an acquisition stores its datasets
in; each entry file passes in the arkitekt services it needs, then registers on the returned app the
startup hooks that provide those two, how the frames are watched and the UI.

| Entry file | Run | Registry | Frames | UI | HTTP routes |
| --- | --- | --- | --- | --- | --- |
| `backend/main_fastapi.py` | `uvicorn main_fastapi:create --factory`, `just dev` | `create_fastapi_registry` | `FrameBroadcaster` → websocket live view `/stream/...` | the description's `ui`, in the newswitch frontend's catalog | auth, accounts, live view, files, cache |
| `backend/main_arkitekt.py` | `python main_arkitekt.py`, `just agent` | `create_arkitekt_registry` | `LovekitSink` → one lovekit `VideoStream` per detector | the description's `agent_ui`, in Orkestrator's standard catalog | none |

As an agent, newswitch runs through `arkitekt.run`, logs in to the arkitekt
server fakts finds (`--url` or `$FAKTS_URL`) and is shown in Orkestrator. It needs the extra `agent`:

```bash
cd backend && uv sync --extra agent
NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just agent   # extra args go to the agent, e.g. --url
```

The agent serves no HTTP routes: the files and the frame cache that
`main_fastapi.py` serves (`/files/...`, `/cache/...`) are not reachable from Orkestrator yet. The agent is
tested offline only, against a fake lovekit client; it has not been run against a real arkitekt
server, lovekit or LiveKit yet.

### Codegen drift

The committed export and hooks can quietly diverge from the backend if nobody re-exports.
`just drift-check` (and the `codegen-drift` CI job) re-exports the schemas, runs `yarn build`, and fails if
`frontend/schemas` or `frontend/src/apps` differ from what's committed — no backend
is booted. If it fails, commit what it just regenerated.

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

### End-to-end test for camera

Cameras are driven through [uc2_cam_py](https://github.com/openUC2/UC2_cam_py) (extra `camera`).
This walkthrough tests the whole chain with its simulated camera, from loading the description
to the image in a debug window; no camera hardware and no frontend are needed.

**What happens on the way:**

1. `NEWSWITCH_CONFIG=instruments/cam-test/microscope.yml` names the instrument, and `spec.load`
   reads it. Everything below comes from that one file.
2. Its `settings` section has `simulate: unwired` (a camera is only opened when it is not
   simulated, and without the extra `camera` the optics stand in, with a warning), `camera_debug_window: true` (a window per camera) and `camera_recording_dir` (where
   recordings go).
3. `cameras()` in `newswitch/instrument/parts.py` finds the camera: the entry of
   its sensor in `hardware.cameras` (`protocol: usb3-vision`, `vendor: Simulated`).
4. `build_detector_manager()` creates the `UC2DetectorManager`, which calls
   `uc2_cam_py.create_camera(..., debug_window=True)`.
5. The debug window keeps the camera acquiring, so the window shows the live image from startup.

**Prerequisites:**

- Linux with a graphical session (X11, or Wayland with XWayland: `DISPLAY` must be set).
- The MVS SDK in `/opt/MVS`, or `MVCAM_SDK_PATH` pointing to it. uc2_cam_py needs it to build,
  also for the simulated camera.
- Python 3.12.
- The extra installed: `just install` (it syncs `--all-extras`) or `cd backend && uv sync --extra camera`.
  Check it with:

  ```bash
  cd backend && uv run python -c "import uc2_cam_py; print(uc2_cam_py.vendors())"
  ```

  It should print `['HikRobot', 'Simulated']`.

**Steps** (paths are relative to `backend/`):

1. Validate the description:

   ```bash
   uv run python -c "from newswitch.instrument import spec; print(spec.load('instruments/cam-test').detectors())"
   ```

   It should print `['sim_cam']`.
2. Run the automated camera tests. They use the same simulated camera and never open a window:

   ```bash
   uv run pytest tests/test_uc2_detector.py tests/test_detector_selection.py tests/test_instrument_hardware.py
   ```

3. Start the backend on that instrument, from the repository root:

   ```bash
   NEWSWITCH_CONFIG=instruments/cam-test/microscope.yml just dev-backend
   ```

4. A window **"uc2_cam_py debug - Simulated UC2-SIM SN SIM-0001"** opens. It shows a bright
   Gaussian spot that walks row by row over a 5 × 4 grid of the 640 × 480 sensor, 20 images per
   second. Nothing on this instrument moves and it has no board, so only its detector and its
   tunes are built: no focus routine and no UC2 bus is started for it.
5. Optional: run `just dev-frontend`. After login, the live view shows the same camera in the
   browser, next to the debug window. Capturing works too: the light path is what the description's
   edges say (here `sample`, `lens_a`, `lens_b` and `sim_cam`).
6. Optional: record to disk. Set `store_image_data: true` for `sim_cam` in
   `instruments/cam-test/microscope.yml` and restart. Each acquisition session is written as a `.uc2rb`
   file plus a `.json` sidecar to `backend/data/recordings/`. Because the debug window keeps
   the camera running, this records continuously, about 12 MB/s here.
7. Stop with Ctrl+C. The window closes. Nothing is written back: the next start begins from the
   description's initial values again.

**A real camera:**

1. Copy `instruments/cam-test` and change its camera in `hardware.cameras`: `protocol:
   gige-vision` or `usb3-vision`, and the vendor as uc2_cam_py names it, e.g. `vendor: HikRobot`.
   Set the sensor's size and pitch in its cube.
2. Select the camera with `serial_number` in its entry. List the connected cameras with:

   ```bash
   uv run python -c "import uc2_cam_py; print(uc2_cam_py.list_devices())"
   ```

3. Remove the `vendor_options`; they are options of the simulated camera only.

Keys and options are described in [`backend/instruments/README.md`](backend/instruments/README.md).

**Troubleshooting:**

| Symptom | Cause |
| --- | --- |
| No window, and an error `debug_window=True: no X11 display available` | No display (headless session, or `DISPLAY` not set). The camera works anyway. |
| No window, and an error `this build has no X11 support` | uc2_cam_py was built without the X11 headers. Install `libX11-devel` (Fedora) or `libx11-dev` (Debian/Ubuntu), then `uv sync --extra camera --reinstall-package uc2-cam-py`. |
| Warning `uc2_cam_py cannot be imported`, rendered from the optics | The extra is not installed, or the MVS runtime libraries are missing. |
| No window and no warning | `settings.simulate` is `everything`, which opens no camera; check that `NEWSWITCH_CONFIG` reached the backend. |
| `camera_debug_window` should stay off | Set it to `false` in the `settings` section of the instrument's `microscope.yml`, e.g. on headless machines. |

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

The frontend container's codegen reads the committed schema export (`frontend/schemas/`), so it does not
need the backend container. Compose's backend healthcheck probes `/health`, which is public and needs no
credentials.


## Authentication

The app sits behind a login backed by a small multi-user account store — several accounts, each with
one role (`admin`/`operator`/`viewer`/`analyst`). Accounts and sessions live in a SQLite file,
`backend/auth.db`, gitignored and created automatically on first run. See
[backend/docs/AUTH_DESIGN.md](backend/docs/AUTH_DESIGN.md) for the full design note (seeding, roles,
sessions, audit trail).

On a completely fresh clone, with no accounts yet, the backend seeds one `admin` account from the
single-account file `auth.yaml` if present:

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
a random, revocable session token: a restart does *not* log
anyone out, but `POST /auth/logout` (or a password change) revokes just that one session. The
frontend keeps the token in `localStorage` until logout.

The token then has to reach the backend over transports that carry credentials differently, because a
browser will only let you set headers on some of them:

| Channel | Carries the token as |
|---|---|
| `fetch` calls | `Authorization: Bearer <token>` |
| Websockets (`/ws`, `/stream/*`) | the first message after connect - a `WebSocket` cannot set headers |
| Images and zarr chunks | `?token=` - three.js' `TextureLoader` and zarrita cannot set headers either |

`/health`, `/auth/login` and `/schemas/*` stay public. `/schemas/*` is served for tools and inspection
(`just export-schemas` writes the same objects from a registry snapshot without calling it, the
frontend's codegen reads the committed export),
and it exposes only the shape of the API, no data and no control.

A rejected websocket closes with code **1008**, which the frontend treats as "log out", distinct from a
dropped connection it should retry.


## Environment

### Ports live in the root `.env`

Every port is defined **once**, in the committed root `.env` (defaults, not secrets), beside the
microscope to run:

```dotenv
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8069
NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml
FRONTEND_PORT=5473
MIKRO_PORT=6580
RUSTFS_PORT=6890
```

It propagates everywhere from there:

| Consumer | How it reads the file |
| --- | --- |
| `just` | `set dotenv-load` — exported into every recipe, and used for `wait-backend`'s health URL |
| `docker compose` | interpolation for the published ports, plus an `environment:` block so the value also reaches inside each container |
| `frontend/.env`, `.env.docker` | `${BACKEND_PORT:-8099}` in the URLs; an exported value wins, the fallback (not the root `.env`'s value) keeps a bare `yarn dev` working |
| `vite.config.ts` | `server.port` / `preview.port` from `FRONTEND_PORT` |
| backend | `os.environ` in `main_fastapi:main`, `--port` from `just`; the Dockerfile has `ENV` defaults of its own, which compose overrides |
| Playwright | `frontend/playwright.config.ts` reads `FRONTEND_PORT` from the file, and starts `just dev-e2e` |

To change a port for one run, export it — a shell variable beats the file in all of the above:

```bash
BACKEND_PORT=9000 just dev      # backend, health check, frontend URLs and vite all follow
BACKEND_PORT=9000 just up       # same for compose (published port + container port)
```

To change it for good, edit the root `.env`. Codegen reads the committed export, not a backend URL, so a
port change does not touch the generated files.

### Frontend URLs

`frontend/.env` holds committed, non-secret **localhost defaults** whose ports interpolate the root `.env`.
To point at a different machine, create an untracked `frontend/.env.local` (it overrides `.env`, and is
gitignored):

```dotenv
VITE_BACKEND_URL=http://my-lab-box:${BACKEND_PORT:-8099}
VITE_WEBSOCKET_URL=ws://my-lab-box:${BACKEND_PORT:-8099}/ws
```

Apart from `BACKEND_HOST`, `BACKEND_PORT`, `NEWSWITCH_CONFIG` (which microscope to run, by default the
fake one) and, in FastAPI mode, `MIKRO_URL`, `MIKRO_DATALAYER_URL` and `MIKRO_TOKEN` (where a mikro is;
`just dev` and `just dev-backend` set them for the stack they start), the backend reads no `.env`: everything about a microscope, how it runs
included, is in its `microscope.yml` ([`backend/instruments/README.md`](backend/instruments/README.md)).

## Releases

One version for the whole repo, one tag (`vX.Y.Z`), **GitHub Releases only**.

Pushing [conventional commits](https://www.conventionalcommits.org/) to `main` triggers
`.github/workflows/release.yml`, which runs semantic-release from the root `release.config.cjs`. It bumps
`backend/pyproject.toml` **and** `frontend/package.json` to the same version, rebuilds the frontend *after*
that bump, builds the backend wheel and sdist, commits the bump and `CHANGELOG.md`, and attaches
`blok.zip`, the wheel and the sdist to the GitHub Release.

Preview what a release would do, without tagging or pushing:

```bash
just release-dry
```


A full local dry run also needs a `GITHUB_TOKEN` in the environment (the GitHub plugin verifies auth even
in `--dry-run`). In CI, the workflow passes in its own `secrets.GITHUB_TOKEN`.

