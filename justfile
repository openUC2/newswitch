set shell := ["bash", "-uc"]

# Ports live in the root .env (committed defaults). dotenv-load exports them into every
# recipe, and env(...) makes them usable in the just expressions below. A variable already
# exported in the shell wins over the file, so `BACKEND_PORT=9000 just dev` works.
set dotenv-load := true

BACKEND_HOST := env("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT := env("BACKEND_PORT", "8099")
FRONTEND_PORT := env("FRONTEND_PORT", "5173")
MIKRO_PORT := env("MIKRO_PORT", "6580")
RUSTFS_PORT := env("RUSTFS_PORT", "6890")

BACKEND_HEALTH := "http://localhost:" + BACKEND_PORT + "/health"

# List available recipes
default:
    @just --list

# ---------- setup ----------

# Install python + node dependencies, and activate the git hooks
install:
    cd backend && uv sync --all-extras --dev
    cd frontend && yarn install --frozen-lockfile
    # Without this the commit-msg / pre-commit hooks never activate for a fresh clone.
    npx --yes lefthook install

# ---------- dev ----------
# --ws-per-message-deflate false: the live view compresses its frames itself; this compressing
# every one again on the event loop takes a core and most of the frame rate (uvicorn does so by default).

# Backend only -> http://localhost:$BACKEND_PORT (hot-reloads on edit)
dev-backend:
    cd backend && uv run uvicorn main_fastapi:create --factory --ws-per-message-deflate false --host {{BACKEND_HOST}} --port {{BACKEND_PORT}} --reload --timeout-graceful-shutdown 3

# Frontend only -> http://localhost:$FRONTEND_PORT (codegen reads frontend/schemas/, no backend needed)
# Binding, port and allowedHosts live in vite.config.ts, so no flags needed here.
dev-frontend:
    cd frontend && yarn dev

# The mikro stack in docker: images and their metadata, for FastAPI mode
mikro:
    docker compose --profile mikro up -d mikro

# Backend + frontend talking to the mikro stack (`just mikro` first)
dev-mikro:
    MIKRO_URL=http://localhost:{{MIKRO_PORT}} MIKRO_DATALAYER_URL=http://localhost:{{RUSTFS_PORT}} MIKRO_TOKEN=newswitch-dev just dev

# Block until the backend's schema endpoints answer
wait-backend url=BACKEND_HEALTH:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "waiting for backend at {{url}} ..."
    for _ in $(seq 1 60); do
      if curl -sf "{{url}}" >/dev/null 2>&1; then echo "backend is up"; exit 0; fi
      sleep 1
    done
    echo "backend did not answer within 60s" >&2
    exit 1

# Run backend + frontend together. Any device configuration works: the frontend's hooks
# are generated from the committed schema export (just export-schemas), not this backend.
dev:
    #!/usr/bin/env bash
    set -uo pipefail
    trap 'trap - EXIT; kill 0' EXIT INT TERM
    (cd backend && exec uv run uvicorn main_fastapi:create --factory --ws-per-message-deflate false --host {{BACKEND_HOST}} --port {{BACKEND_PORT}} --reload --timeout-graceful-shutdown 3) &
    just wait-backend || echo "!! backend unreachable - the frontend will show it as offline" >&2
    echo "frontend -> http://localhost:{{FRONTEND_PORT}}"
    (cd frontend && exec yarn dev) &
    wait

# newswitch as an arkitekt agent (lovekit streams, the configuration's agent_ui), e.g.
#   NEWSWITCH_CONFIG=configs/newswitch-config.fluorescence.yaml just agent
# Logs in to the arkitekt server fakts finds (--url / $FAKTS_URL). Needs the extra 'agent'.
agent *args:
    cd backend && uv run --extra agent python main_arkitekt.py {{args}}

# Isolated stack for Playwright. Vite's test mode skips backend schema codegen so an
# E2E run cannot dirty the committed generated frontend files.
dev-e2e:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'trap - EXIT; kill 0' EXIT INT TERM
    rm -f frontend/test-results/e2e-auth.db
    (cd backend && NEWSWITCH_AUTH_DB=../frontend/test-results/e2e-auth.db exec uv run uvicorn main_fastapi:create --factory --ws-per-message-deflate false --host {{BACKEND_HOST}} --port {{BACKEND_PORT}}) &
    just wait-backend
    (cd frontend && exec yarn dev --mode test) &
    wait

# Write a device configuration, UI included, from an optikit design; run it with
# NEWSWITCH_CONFIG=<out> just dev. Needs the extra 'design'.
build-design dsn out:
    cd backend && uv run python -m newswitch.tools.build_design {{dsn}} -o {{out}}

# ---------- quality ----------

lint:
    cd backend && uv run ruff check .
    cd frontend && yarn lint

# Format everything in place
fmt:
    cd backend && uv run ruff format .
    cd frontend && yarn prettier --write "src/**/*.{ts,tsx,css}" "plugins/**/*.ts"

# Fail if anything is unformatted (used by CI / the pre-commit hook)
fmt-check:
    cd backend && uv run ruff format --check .
    cd frontend && yarn prettier --check "src/**/*.{ts,tsx,css}" "plugins/**/*.ts"

# NOTE: not `tsc --noEmit` - the root tsconfig is a solution config with `files: []`,
# so a non-build tsc there checks ZERO files and passes trivially.
types:
    cd frontend && yarn types

# Fast tests, both halves (no running server needed)
test: test-backend test-frontend

test-backend:
    cd backend && uv run pytest -k "not integration"

test-frontend:
    cd frontend && yarn test

# Everything, including integration tests
test-all:
    cd backend && uv run pytest
    cd frontend && yarn test

check: fmt-check lint types test

# ---------- accounts ----------

# List every account and its role (run on the appliance itself)
list-users:
    cd backend && uv run python -m newswitch.tools.accounts list-users

# Recovery: set a new password for an existing account, e.g. after it's forgotten
reset-password username password:
    cd backend && uv run python -m newswitch.tools.accounts reset-password {{username}} {{password}}

# Recovery: create a fresh admin account, e.g. if every admin got locked out
create-admin username password:
    cd backend && uv run python -m newswitch.tools.accounts create-admin {{username}} {{password}}


# Write the schemas of a complete microscope (configs/newswitch-config.yaml) into
# frontend/schemas/, which the frontend's codegen generates its typed hooks from.
export-schemas:
    cd backend && uv run python -m newswitch.tools.export_schemas

# Fail if the committed schema export or generated frontend code is stale.
drift-check: export-schemas
    #!/usr/bin/env bash
    set -euo pipefail
    cd frontend && yarn build >/dev/null
    cd ..
    paths="frontend/schemas frontend/src/apps"
    if ! git diff --quiet -- $paths; then
      echo "!! the schema export or the generated code is out of date:" >&2
      git diff --stat -- $paths >&2
      echo "!! commit the result of 'just drift-check' (it just regenerated both)" >&2
      exit 1
    fi
    echo "schema export and generated code match the backend"

# ---------- build ----------

# Frontend bundle + backend wheel/sdist
build:
    cd frontend && yarn build
    cd backend && uv build --out-dir dist

clean:
    rm -rf backend/.venv backend/dist backend/.pytest_cache backend/.ruff_cache
    rm -rf frontend/node_modules frontend/dist blok.zip
    find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ---------- docker ----------

up:
    docker compose up --build

down:
    docker compose down

# Also drops the named venv / node_modules volumes (needed after a dependency change)
down-hard:
    docker compose down -v

logs:
    docker compose logs -f

# ---------- release ----------

# Dry-run the unified release locally (no push, no tag)
release-dry:
    npx -y \
      -p semantic-release@24 \
      -p @semantic-release/changelog \
      -p @semantic-release/exec \
      -p @semantic-release/git \
      -p @semantic-release/github \
      -p conventional-changelog-conventionalcommits \
      semantic-release --dry-run --no-ci
