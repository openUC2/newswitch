FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Run as uid 1000, not root. The app writes agent_data.db (and cache files) into its CWD,
# which compose bind-mounts from the host - as root those land root-owned and the host user
# can no longer delete them. uid 1000 matches a typical Linux host user.
RUN useradd --uid 1000 --create-home app

WORKDIR /app
RUN chown app:app /app
USER app

# Dependency layer, cached across source edits
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY --chown=app:app . .
RUN uv sync --frozen

# Defaults matching the repo's root .env. compose overrides them per service, and
# `docker run -e BACKEND_PORT=...` works too - CMD/HEALTHCHECK below both read them.
ENV BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8099

# Documentation only, and resolved at BUILD time - a runtime -e BACKEND_PORT still works,
# it just is not reflected here.
EXPOSE ${BACKEND_PORT}

# main.py exposes a module-level `app`, which is what lets --reload re-import on edit.
# The source dir is bind-mounted by compose, so edits on the host reload the container.
# Via `sh -c` so $BACKEND_PORT is expanded instead of passed literally, and `exec` so
# uvicorn replaces the shell as PID 1 and still receives SIGTERM from `docker compose down`.
CMD ["sh", "-c", "exec uvicorn main:app --host \"$BACKEND_HOST\" --port \"$BACKEND_PORT\" --reload"]

# python:slim has no curl, so probe with urllib instead
HEALTHCHECK --interval=5s --timeout=5s --retries=30 --start-period=30s \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:'+os.environ['BACKEND_PORT']+'/health', timeout=3).status == 200 else 1)"
