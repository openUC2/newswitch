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
"""

import os

from newswitch.app import create_app, load_app_config

app = create_app(load_app_config())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        port=int(os.environ.get("BACKEND_PORT", "8099")),
    )
