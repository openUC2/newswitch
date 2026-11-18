"""Serve the built frontend (``frontend/dist``) from the backend.

The container image runs one process on one port, as ImSwitch does: the backend serves the
React bundle under `FRONTEND_PATH` next to its API. The browser then reaches the API on the
same origin, so no backend URL has to be baked into the bundle (it is built with
``vite build --mode container``, see ``frontend/.env.container``).

Only active when `FRONTEND_DIR_ENV_VAR` is set (the Dockerfile sets it). Without it nothing
changes; `just dev` keeps using the Vite dev server.
"""

import logging
import os
from pathlib import Path, PurePosixPath

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

logger = logging.getLogger(__name__)

#: Environment variable naming the folder of the built frontend (``index.html`` + assets).
FRONTEND_DIR_ENV_VAR = "NEWSWITCH_FRONTEND_DIR"

#: URL prefix of the frontend. Must match ``base`` of ``vite build --mode container``, and is
#: public in `newswitch.auth` (the bundle holds no data; the API behind it stays gated).
FRONTEND_PATH = "/newswitch"


class SinglePageApp(StaticFiles):
    """Static files plus the single-page-app fallback.

    The React router owns paths such as ``/newswitch/login``; reloading the page there asks
    for a file that does not exist, so such paths get ``index.html``. Paths that look like a
    file (a suffix such as ``.js``) still answer 404, so a missing asset stays visible.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Serve `path`, or ``index.html`` for an unknown route of the frontend."""
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or PurePosixPath(path).suffix:
                raise
            return await super().get_response("index.html", scope)


def frontend_dir_from_env() -> Path | None:
    """The folder `FRONTEND_DIR_ENV_VAR` names, or None when it is not set."""
    value = os.environ.get(FRONTEND_DIR_ENV_VAR)
    return Path(value) if value else None


def mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    """Serve `dist_dir` under `FRONTEND_PATH` and redirect ``/`` there.

    Raises:
        FileNotFoundError: `dist_dir` holds no ``index.html``. A wrong path in a deployment
            fails at startup instead of serving an empty page.
    """
    if not (dist_dir / "index.html").is_file():
        raise FileNotFoundError(
            f"{FRONTEND_DIR_ENV_VAR}={dist_dir} holds no index.html (not a built frontend)"
        )
    app.mount(FRONTEND_PATH, SinglePageApp(directory=dist_dir, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    async def _redirect_to_frontend() -> RedirectResponse:
        return RedirectResponse(f"{FRONTEND_PATH}/")

    logger.info("serving the frontend from %s at %s/", dist_dir, FRONTEND_PATH)
