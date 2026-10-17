"""Module-level ASGI app, so `uvicorn main:app --reload` can re-import on every edit.

`test.py` builds the app inside `__main__` and hands the object to `uvicorn.run(...)`,
which pins it to one process and rules out reload. Uvicorn's reloader needs an import
string it can re-evaluate, which is what `app` below provides.

Settings, including which device configuration to load, come from base_config.yaml.
To boot a specific microscope, set NEWSWITCH_CONFIG to a JSON file whose values
override single ImswitchConfig fields of base_config.yaml, e.g.

    NEWSWITCH_CONFIG=configs/uc2_canopen.json uvicorn main:app --port 8099

Without the variable base_config.yaml alone applies. Ready-made setups
live in backend/configs/ (uc2_serial.json, uc2_canopen.json).
"""

import json
import os
from pathlib import Path

from newswitch.app import ImswitchConfig, create_app


def load_config() -> ImswitchConfig:
    """Build the app config from base_config.yaml, overridden by the NEWSWITCH_CONFIG JSON file."""
    config_path = os.environ.get("NEWSWITCH_CONFIG")
    if not config_path:
        return ImswitchConfig()

    candidate = Path(config_path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parent / candidate

    return ImswitchConfig(**json.loads(candidate.read_text()))


app = create_app(load_config())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8099)
