"""ASGI entrypoint using shared YAML/mode selection and configured logging."""

import os
from newswitch.app import create_app, load_app_config
from newswitch.logging_setup import configure_logging

# Keep the old function name available to callers; every entrypoint uses the same loader.
load_config = load_app_config
config = load_config()
configure_logging(config.log_to_terminal, config.log_to_file, config.log_file_path)
app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        port=int(os.environ.get("BACKEND_PORT", "8099")),
        log_config=None,
    )
