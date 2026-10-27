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

### End-to-end test for camera

Cameras are driven through [uc2_cam_py](https://github.com/openUC2/UC2_cam_py) (extra `camera`).
This walkthrough tests the whole chain with its simulated camera, from loading the configuration
to the image in a debug window; no camera hardware and no frontend are needed.

**What happens on the way:**

1. `backend/base_config.yaml` is read. `camera_debug_window: true` asks for a window per camera,
   and `camera_recording_dir` sets where recordings go.
2. `NEWSWITCH_CONFIG=configs/camTest.json` overrides two settings:
   `use_virtual_microscope: false` (cameras are only used on real hardware) and the device file
   `configs/camTest_config.yaml`.
3. `config_io` validates that file, and `adapters.cameras()` finds the camera: a detector
   (`manufacturer: Simulated`) mapped by a `usb3-vision` controller.
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

1. Validate the device file:

   ```bash
   uv run python -m newswitch.config_io configs/camTest_config.yaml
   ```

   It should list the controller and the detector `sim-cam` without errors.
2. Run the automated camera tests. They use the same simulated camera and never open a window:

   ```bash
   uv run pytest tests/test_uc2_detector.py tests/test_detector_selection.py tests/config_io/test_adapters.py
   ```

3. Start the backend with the camera configuration, from the repository root:

   ```bash
   NEWSWITCH_CONFIG=configs/camTest.json just dev-backend
   ```

4. A window **"uc2_cam_py debug - Simulated UC2-SIM SN SIM-0001"** opens. It shows a bright
   Gaussian spot that walks row by row over a 5 × 4 grid of the 640 × 480 sensor, 20 images per
   second. The terminal also prints `Initializing real hardware microscope managers`, followed
   by repeated `UC2 serial bus error ... reconnecting` warnings. Those come from stage and
   illumination looking for a UC2 board that is not there; they do not affect the camera.
5. Optional: run `just dev-frontend`. After login, the live view shows the same camera in the
   browser, next to the debug window.
6. Optional: record to disk. Call the action `start_live_view_and_save_to_disk` (there is no
   button yet; the frontend hook is `useStartLiveViewAndSaveToDisk`), e.g. with a token from
   `/auth/login`:

   ```bash
   TOKEN=$(curl -s -u <user>:<password> -X POST http://localhost:8069/auth/login \
     | python3 -c "import json, sys; print(json.load(sys.stdin)['token'])")
   curl -s -X POST http://localhost:8069/start_live_view_and_save_to_disk \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"args": {}, "cached": false, "log": true, "capture": false, "ephemeral": false}'
   ```

   The images are written as a `.uc2rb` file plus a `.json` sidecar to
   `backend/data/recordings/`, about 12 MB/s here, until `stop_live_view` (same call). A
   single saved snapshot: `capture_image_and_save_to_disk`.
7. Stop with Ctrl+C. The window closes and the runtime values are saved to
   `configs/camTest_config.persistent.yaml`; the main persistent file is not touched.

**Without frontend and `curl`:** the debug console starts the backend like `main.py` and drives
the detectors from the terminal (status, activate/deactivate, start/stop, exposure, gain, frame
rate, binning, ROI). It calls only the registered actions, as the frontend does:

```bash
cd backend
NEWSWITCH_CONFIG=configs/camTest.json BACKEND_PORT=8069 uv run -q python backend_cli.py
```

`BACKEND_PORT=8069` lets `just dev-frontend` connect at the same time (without it: 8099, as for
`python main.py`). The login is asked for, or taken from `NEWSWITCH_CLI_USER` /
`NEWSWITCH_CLI_PASSWORD`. Everything the backend itself prints goes to
`backend/data/backend_cli.log` (follow it with `tail -f`); `--verbose` shows it in the terminal
instead. `-q` keeps uv's own warnings out.

**A real camera:**

1. Copy the two camTest files and point the controller at the hardware: `protocol: gige-vision` or
   `usb3-vision`. In the detector, set the vendor as uc2_cam_py names it, e.g.
   `manufacturer: HikRobot`.
2. Select the camera with `serial_number` in its mapping entry. List the connected cameras with:

   ```bash
   uv run python -c "import uc2_cam_py; print(uc2_cam_py.list_devices())"
   ```

3. Remove the `vendor_options`; they are options of the simulated camera only.

Keys and options are described in `backend/configs/README.md`, section "Cameras".

**Troubleshooting:**

| Symptom | Cause |
| --- | --- |
| No window, and an error `debug_window=True: no X11 display available` | No display (headless session, or `DISPLAY` not set). The camera works anyway. |
| No window, and an error `this build has no X11 support` | uc2_cam_py was built without the X11 headers. Install `libX11-devel` (Fedora) or `libx11-dev` (Debian/Ubuntu), then `uv sync --extra camera --reinstall-package uc2-cam-py`. |
| Warning `uc2_cam_py cannot be imported`, virtual detector used | The extra is not installed, or the MVS runtime libraries are missing. |
| No window and no warning | `use_virtual_microscope` is still `true`; check that `NEWSWITCH_CONFIG` reached the backend. |
| `camera_debug_window` should stay off | Set it to `false` in `backend/base_config.yaml`, e.g. on headless machines. |

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

Apart from `BACKEND_HOST` / `BACKEND_PORT`, the backend reads no `.env` — the rest is configured in
`backend/base_config.yaml`, read by `ImswitchConfig` (`backend/newswitch/app.py`).

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

