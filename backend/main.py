"""Module-level ASGI app, so `uvicorn main:app --reload` can re-import on every edit.

`test.py` builds the app inside `__main__` and hands the object to `uvicorn.run(...)`,
which pins it to one process and rules out reload. Uvicorn's reloader needs an import
string it can re-evaluate, which is what `app` below provides.

Configuration file support: set NEWSWITCH_CONFIG to a JSON file matching the
ImswitchConfig schema to boot a specific microscope, e.g.

    NEWSWITCH_CONFIG=configs/uc2_canopen.json uvicorn main:app --port 8099

Without the variable the virtual-microscope defaults apply. Ready-made setups
live in backend/configs/ (uc2_serial.json, uc2_canopen.json).
"""

import os
from pathlib import Path

from newswitch.app import ImswitchConfig, create_app

# Settings, including which device configuration to load, come from base_config.yaml.
app = create_app(ImswitchConfig())
