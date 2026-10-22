"""The arkitekt app newswitch declares its actions, states, contexts and hooks on.

Every module that declares something imports `nsapp` from here (named so it does not
shadow the FastAPI ``app``). `newswitch.app` serves it through arkitekt-fastapi.
"""

from arkitekt import App

from newswitch.config import ImswitchConfig

nsapp = App("newswitch", app_context=ImswitchConfig)
