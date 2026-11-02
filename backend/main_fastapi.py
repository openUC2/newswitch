"""newswitch served by FastAPI, to the newswitch frontend (the steps: `main`).

    NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just dev
    uv run uvicorn main_fastapi:create --factory --reload

`create_fastapi_registry` registers newswitch for the newswitch frontend: the microscope
(`create_registry`), a `FrameBroadcaster` as the detectors' `FrameSink` (the websocket live
view streams from it), and the description's ``ui`` bloks checked against the frontend's catalog. `create_app`
serves that registry through arkitekt-fastapi, with auth, accounts, live view, files and
the cache beside it. There is no module-level app: uvicorn calls `create` (``--factory``), on every
reload again.
"""

import logging
import os

import uvicorn
from arkitekt import App
from arkitekt_fastapi import configure_fastapi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from newswitch.infra.accounts.auth import (
    Authenticator,
    AuthMiddleware,
    default_authenticator,
    make_expand_user_from_request,
)
from newswitch.infra.accounts.auth import router as auth_router
from newswitch.infra.accounts.routes import router as users_router
from newswitch.infra.ui import declare_ui
from newswitch.infra.streaming import FrameBroadcaster
from newswitch.instrument.spec import Instrument
from newswitch.microscope.registry import create_registry
from newswitch.infra.http.cache import router as cache_router
from newswitch.infra.http.files import router as files_router
from newswitch.infra.http.liveview import router as liveview_router
from newswitch.microscope.run import Run
from newswitch.protocols.dataset_store import DatasetStore
from newswitch.protocols.frame_sink import FrameSink
from newswitch.infra.mikro.none import NoDatasetStore
from newswitch.infra.mikro.connection import MikroConnection
from newswitch.settings import Settings, load_settings

logger = logging.getLogger(__name__)


async def provide_frame_broadcaster(run: Run) -> FrameSink:
    """Startup: the detectors stream to a broadcaster, which the live view encodes."""
    return FrameBroadcaster()


async def provide_no_dataset_store(run: Run) -> DatasetStore:
    """Startup: no mikro is configured, so an acquisition says so instead of starting."""
    return NoDatasetStore()


def create_fastapi_registry(instrument: Instrument | None, with_mikro: bool = False) -> App:
    """Step 3: the registry of `instrument` for the newswitch frontend.

    Args:
        instrument: What to run; None: no devices, the core only.
        with_mikro: Provide the client of the run's mikro. Nothing provides one here, as arkitekt
            does in agent mode.
    """
    app = create_registry(instrument)
    app.register_startup(provide_frame_broadcaster)
    if with_mikro:
        from newswitch.infra.mikro import app as mikro_app  # needs the extra mikro

        app.registry.merge(mikro_app.app.registry)
    else:
        app.register_startup(provide_no_dataset_store)
    declare_ui(app, instrument)
    return app


def create_app(
    config: Settings,
    authenticator: Authenticator | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: The app context handed to every registered function.
        authenticator: Overrides the credentials file. Tests pass
            `AllowAllAuthenticator()`; production leaves this unset. Injected as an
            argument rather than read from the environment so that authentication
            cannot be switched off by a stray variable on a deployed machine.
    """

    fastapi = FastAPI(
        title="Virtual Microscope API",  # TODO: should we load this from config?
        description="Integrated virtual microscope controller with protocol-based managers based on arkitekt",
        version="2.0.0",
    )

    authenticator = authenticator or default_authenticator()
    fastapi.state.authenticator = authenticator

    # Middleware order is load-bearing. `add_middleware` PREPENDS, so the LAST call
    # here ends up OUTERMOST: auth is added first and CORS wraps it. Reversed, a 401
    # would leave without CORS headers and the browser at :5173 would report an opaque
    # CORS failure instead of the 401 that tells the app to send the user to /login.
    fastapi.add_middleware(AuthMiddleware, authenticator=authenticator)

    # Add CORS middleware
    # bceause CORS sucks
    fastapi.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        # Auth travels in an Authorization header or a query parameter, never a
        # cookie, so credentialed CORS is not needed - and without it the wildcard
        # origin above can be sent literally instead of being echoed back.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # The registry this app serves: created here, everything registered on it, with the
    # views of the instrument
    run = Run.of(config, MikroConnection.from_env())
    registry = create_fastapi_registry(run.instrument, with_mikro=run.mikro is not None)

    # Serve everything registered (actions, states, contexts, hooks, bloks)
    configure_fastapi(
        app=fastapi,
        app_registry=registry.registry,
        expand_user_from_request=make_expand_user_from_request(authenticator),
        app_context=run,
        db_file=config.db_path,
    )

    # Mount the public auth + health routes
    fastapi.include_router(auth_router)

    # Mount account/role/audit management routes (admin-only except /auth/me)
    fastapi.include_router(users_router)

    # The live view, the files and the cache of the running agent
    fastapi.include_router(liveview_router, prefix="/stream")
    fastapi.include_router(files_router)
    fastapi.include_router(cache_router)

    return fastapi


def create() -> FastAPI:
    """Steps 1-4: the uvicorn factory (``uvicorn main_fastapi:create --factory``)."""
    return create_app(load_settings())


def main() -> None:
    """Main entry point to run the FastAPI server.

    Host and port come from BACKEND_HOST / BACKEND_PORT (the repo's root .env, which
    `just` and docker compose export), so they stay defined in exactly one place.
    """
    uvicorn.run(
        create(),
        host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        port=int(os.environ.get("BACKEND_PORT", "8099")),
        # The live view compresses its frames itself: deflating every one again on the event
        # loop takes a core and most of the frame rate.
        ws_per_message_deflate=False,
    )


if __name__ == "__main__":
    main()
