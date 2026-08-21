"""An entry point for running the application with Uvicorn."""

import os

from newswitch.app import create_app, ImswitchConfig
import uvicorn

if __name__ == "__main__":
    app = create_app(ImswitchConfig())

    # Same BACKEND_HOST / BACKEND_PORT as the root .env - see newswitch.app.main.
    uvicorn.run(
        app,
        host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        port=int(os.environ.get("BACKEND_PORT", "8099")),
    )
