set shell := ["bash", "-uc"]

# Ports live in the root .env (committed defaults). dotenv-load exports them into every
# recipe, and env(...) makes them usable in the just expressions below. A variable already
# exported in the shell wins over the file, so `BACKEND_PORT=9000 just dev` works.
set dotenv-load := true

BACKEND_HOST := env("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT := env("BACKEND_PORT", "8099")
FRONTEND_PORT := env("FRONTEND_PORT", "5173")

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

# Backend only -> http://localhost:$BACKEND_PORT (hot-reloads on edit)
dev-backend:
    cd backend && uv run uvicorn main:app --host {{BACKEND_HOST}} --port {{BACKEND_PORT}} --reload

# Frontend only -> http://localhost:$FRONTEND_PORT (needs the backend up for fresh codegen)
# Binding, port and allowedHosts live in vite.config.ts, so no flags needed here.
dev-frontend:
    cd frontend && yarn dev

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

# Run backend + frontend together (backend first: the frontend codegen fetches its schemas)
dev:
    #!/usr/bin/env bash
    set -uo pipefail
    trap 'trap - EXIT; kill 0' EXIT INT TERM
    (cd backend && exec uv run uvicorn main:app --host {{BACKEND_HOST}} --port {{BACKEND_PORT}} --reload) &
    if ! just wait-backend; then
      echo "!! backend unreachable - vite will fall back to the COMMITTED generated hooks" >&2
      echo "!! (see frontend/plugins/generate-app.ts: fetch failures are warnings, not errors)" >&2
    fi
    echo "frontend -> http://localhost:{{FRONTEND_PORT}}"
    (cd frontend && exec yarn dev) &
    wait

# Isolated stack for Playwright. Vite's test mode skips backend schema codegen so an
# E2E run cannot dirty the committed generated frontend files.
dev-e2e:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'trap - EXIT; kill 0' EXIT INT TERM
    rm -f frontend/test-results/e2e-auth.db
    (cd backend && NEWSWITCH_AUTH_DB=../frontend/test-results/e2e-auth.db exec uv run uvicorn main:app --host {{BACKEND_HOST}} --port {{BACKEND_PORT}}) &
    just wait-backend
    (cd frontend && exec yarn dev --mode test) &
    wait

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
    cd backend && uv run python -m newswitch.cli list-users

# Recovery: set a new password for an existing account, e.g. after it's forgotten
reset-password username password:
    cd backend && uv run python -m newswitch.cli reset-password {{username}} {{password}}

# Recovery: create a fresh admin account, e.g. if every admin got locked out
create-admin username password:
    cd backend && uv run python -m newswitch.cli create-admin {{username}} {{password}}


# Fail if the committed generated code no longer matches the running backend.
# Requires the backend to be up (`just dev-backend`).
drift-check:
    #!/usr/bin/env bash
    set -euo pipefail
    just wait-backend
    cd frontend && yarn build >/dev/null
    cd ..
    if ! git diff --quiet -- frontend/src/apps frontend/blok.json; then
      echo "!! generated code is out of sync with the backend:" >&2
      git diff --stat -- frontend/src/apps frontend/blok.json >&2
      echo "!! run 'just dev-backend' + 'cd frontend && yarn build', then commit the result" >&2
      exit 1
    fi
    echo "generated code matches the backend"

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
