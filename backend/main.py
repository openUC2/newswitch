"""Module-level ASGI app, so `uvicorn main:app --reload` can re-import on every edit.

`test.py` builds the app inside `__main__` and hands the object to `uvicorn.run(...)`,
which pins it to one process and rules out reload. Uvicorn's reloader needs an import
string it can re-evaluate, which is what `app` below provides.

Settings, including which device configuration to load, come from base_config.yaml.
To boot a specific microscope, set NEWSWITCH_CONFIG to a JSON file whose values
override single ImswitchConfig fields of base_config.yaml, e.g.

    NEWSWITCH_CONFIG=configs/uc2_canopen.json uvicorn main:app --port 8099

Without the variable base_config.yaml alone applies (see `newswitch.app.load_app_config`,
which ``python -m newswitch.app`` uses as well). Ready-made setups live in backend/configs/
(uc2_serial.json, uc2_canopen.json, camTest.json).

Run directly (``python main.py``, e.g. in the debugger) the app serves on BACKEND_HOST /
BACKEND_PORT from the environment, like `newswitch.app.main`.

Logging follows log_to_terminal / log_to_file / log_file_path of the settings. Under
``uvicorn main:app`` uvicorn sets up its own logging first and imports this module afterwards,
so the settings win.
"""

import os

from newswitch.app import create_app, load_app_config
from newswitch.logging_setup import configure_logging

config = load_app_config()
configure_logging(config.log_to_terminal, config.log_to_file, config.log_file_path)
app = create_app(config)


if __name__ == "__main__":
    import uvicorn

    # log_config=None: uvicorn would otherwise put its own handlers back
    uvicorn.run(
        app,
        host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        port=int(os.environ.get("BACKEND_PORT", "8099")),
        log_config=None,
    )
