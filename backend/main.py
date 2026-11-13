"""Backend CLI and ASGI entrypoint with shared YAML/mode selection."""

from newswitch.app import create_app, load_app_config, main
from newswitch.logging_setup import configure_logging

load_config = load_app_config

if __name__ == "__main__":
    main()
else:
    # Keep `uvicorn main:app` working; uvicorn owns its own CLI arguments.
    config = load_config()
    configure_logging(config.log_to_terminal, config.log_to_file, config.log_file_path)
    app = create_app(config)
