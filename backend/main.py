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

os.environ["NEWSWITCH_CONFIG"] = (
    "/Users/bene/Dropbox/Dokumente/Promotion/PROJECTS/MicronController/newswitch/backend/configs/uc2_serial.json"
)


def load_config() -> ImswitchConfig:
    """Build the app config, optionally from the NEWSWITCH_CONFIG JSON file."""
    config_path = os.environ.get("NEWSWITCH_CONFIG")
    if not config_path:
        return ImswitchConfig()
    return ImswitchConfig.model_validate_json(Path(config_path).read_text())


app = create_app(load_config())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8099)
