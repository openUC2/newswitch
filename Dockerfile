# syntax=docker/dockerfile:1
#
# Production image of newswitch: backend and built frontend in one image, served on one port
# (8069), as ImSwitch does it. Built for linux/arm64 (Raspberry Pi 5) and linux/amd64 by
# .github/workflows/build-container.yml; locally the same way:
#   just prod-build            (or: docker buildx build --load -t newswitch:local .)
# The HikRobot MVS packages must be in backend/external first (backend/external/README.md).
# Run it with docker/docker-compose.yml (docs/INSTALL-RPI.md).
#
# The development setup is separate: docker-compose.yml in the repository root
# (backend/Dockerfile, frontend/Dockerfile, bind-mounted sources).

# Same base image as backend/Dockerfile (and Python 3.13 as ImSwitch); update tag and digest
# together.
ARG BASE_IMAGE=ghcr.io/astral-sh/uv:0.12.24-python3.13-trixie-slim@sha256:adb723cc75f8a5fa33fa1928af0e032d9199694599c77ffeea5527a76e37a512
ARG NODE_IMAGE=node:22-slim

# ---------- drivers: camera SDK where its installer puts it (base of builder and runtime) ----------
FROM ${BASE_IMAGE} AS drivers
ARG TARGETPLATFORM
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC
RUN --mount=type=bind,source=docker/install-drivers.sh,target=/mnt/build/install-drivers.sh \
    --mount=type=bind,source=backend/external,target=/mnt/external \
    bash /mnt/build/install-drivers.sh
# The MVS libraries at runtime: the folders of both architectures (only the image's own one
# exists). MVCAM_COMMON_RUNENV is what HikRobot's own set_env_path.sh sets.
ENV MVCAM_COMMON_RUNENV=/opt/MVS/lib \
    LD_LIBRARY_PATH=/opt/MVS/lib/aarch64:/opt/MVS/lib/64

# ---------- builder: the Python environment incl. the C++ extensions ----------
FROM drivers AS builder
# uc2_cam_py (extra "camera") and pystackreg (no aarch64 wheel) are built from source
RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ cmake ninja-build git \
    && rm -rf /var/lib/apt/lists/*
# The venv lives at its final path: venvs cannot be moved, the runtime stage copies it as is.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/newswitch/backend/.venv \
    CMAKE_ARGS=-DHIK_MVS=ON
# CMAKE_ARGS: HIK_MVS=ON makes a missing or unusable MVS SDK a build error; uc2_cam_py would
# otherwise build with the simulated camera only, without a word. MVS_ROOT=/opt/MVS comes from
# [tool.uv] in backend/pyproject.toml.
WORKDIR /opt/newswitch/backend

# Dependency layer, rebuilt only when pyproject.toml or uv.lock change
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    --mount=type=bind,source=backend/README.md,target=README.md \
    uv sync --frozen --no-install-project --extra uc2 --extra camera

# The backend itself: only what it needs at runtime (no tests, docs, databases, logs, and
# not the MVS packages in backend/external)
COPY backend/pyproject.toml backend/uv.lock backend/README.md backend/main.py \
     backend/base_config.yaml backend/auth.example.yaml ./
COPY backend/newswitch ./newswitch
COPY backend/configs ./configs
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra uc2 --extra camera
# Fail the build if uc2_cam_py came out without HikRobot support
RUN .venv/bin/python -c "import sys, uc2_cam_py; v = uc2_cam_py.vendors(); print('uc2_cam_py vendors:', v); sys.exit('HikRobot' not in v)"

# ---------- frontend: the bundle, built once on the build machine (platform-independent) ----------
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS frontend
WORKDIR /app
COPY frontend/package.json frontend/yarn.lock ./
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn \
    yarn install --frozen-lockfile --non-interactive
COPY frontend/ ./
# No backend runs here: the codegen falls back to the committed generated files, as in CI.
# --mode container: base /newswitch/ and same-origin backend URLs (frontend/.env.container).
RUN yarn build --mode container

# ---------- runtime ----------
FROM drivers AS runtime
# User pi (uid 1000) and the Raspberry Pi OS hardware groups, as in ImSwitch's image, so that
# file ownership and device permissions match the host. docker-compose.yml adds the device
# groups (tty, dialout, video, plugdev).
RUN groupadd --system --gid 1000 pi \
    && groupadd --system --gid 989 spi \
    && groupadd --system --gid 988 i2c \
    && groupadd --system --gid 986 gpio \
    && useradd --system --gid 1000 --uid 1000 --create-home pi
# Owned by pi: the backend writes its runtime files next to itself (agent_data.db, auth.db,
# backend.log, configs/*.persistent.yaml, data/recordings; OpenPoints_installChain.md #5).
COPY --from=builder --chown=1000:1000 /opt/newswitch/backend /opt/newswitch/backend
COPY --from=frontend --chown=1000:1000 /app/dist /opt/newswitch/frontend/dist
ENV PATH="/opt/newswitch/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    NEWSWITCH_FRONTEND_DIR=/opt/newswitch/frontend/dist \
    NEWSWITCH_MODE=hardware \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8069
WORKDIR /opt/newswitch/backend
USER pi
EXPOSE 8069
# `python main.py`: newswitch.app.main reads BACKEND_HOST / BACKEND_PORT and NEWSWITCH_MODE /
# NEWSWITCH_CONFIG, validates the device YAML and runs uvicorn. Exec form, so Python is PID 1
# and receives SIGTERM from `docker stop`.
CMD ["python", "main.py"]
# python:slim has no curl, so probe with urllib
HEALTHCHECK --interval=10s --timeout=5s --retries=30 --start-period=30s \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:'+os.environ['BACKEND_PORT']+'/health', timeout=3).status == 200 else 1)"
