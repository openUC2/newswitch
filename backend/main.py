"""Module-level ASGI app, so `uvicorn main:app --reload` can re-import on every edit.

`test.py` builds the app inside `__main__` and hands the object to `uvicorn.run(...)`,
which pins it to one process and rules out reload. Uvicorn's reloader needs an import
string it can re-evaluate, which is what `app` below provides.
"""

from newswitch.app import ImswitchConfig, create_app
from newswitch.config_io import DEFAULT_CONFIG_NAME

app = create_app(ImswitchConfig(config_file=DEFAULT_CONFIG_NAME))
