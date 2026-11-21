"""Who newswitch is on an arkitekt server, and the microscope FastAPI mode serves: every part merged.

The agent (``app.py``) registers every part itself, directly; FastAPI mode (``main_fastapi.py``)
merges `app` here. Each part is a registry of its own (`newswitch.microscope.apps`): its states,
contexts, startup hook, actions and background tasks, as plain module-level functions. `app` merges
all of them, once, when this module is imported:

1. the core every microscope has (the models, files, the expanse, calibration, light paths, hooks);
2. what a microscope may have: its variables, its detectors, a UC2 board;
3. what needs several of those (focus, acquisition).

What is registered does not depend on the instrument, which is only known when a run starts (its
`Run`, the app context). That is what lets arkitekt inspect the app without one, and compile it into
a release (``arkitekt inspect all app``). Every state is always provided; a part the instrument
lacks is a context its startup hook provides as ``None``. arkitekt then fails an action that needs
it when it is called, and does not start the background tasks or shutdown hooks that need it.

How it is served is not registered here. The detectors stream to a `FrameSink` context
(declared by the core, a protocol); ``main_fastapi.py`` merges `app` into the app it serves,
provides that context (the websocket live view's `FrameBroadcaster`) and declares the UI it shows.
Like the parts, `app` lives as long as the process: declare nothing on it from outside.
``tests/test_registry.py`` holds it and ``app.py`` to the same actions, states and locks.

Every app is run with its own `Run`, which holds its one `build_microscope`: two runs share nothing.
"""

from importlib.metadata import PackageNotFoundError, version

from arkitekt import App

from newswitch.microscope.apps import acquisition, core, detector, focus, uc2, values
from newswitch.microscope.run import Run

#: What newswitch is called on an arkitekt server.
IDENTIFIER = "newswitch"
#: What it says it is there.
DESCRIPTION = (
    "A microscope, described by its optical elements: its stage, optics, detectors and acquisition."
)

try:
    #: The installed newswitch's version: the one in ``pyproject.toml``.
    VERSION = version("newswitch")
except PackageNotFoundError:  # run from a checkout that was never installed
    VERSION = "0.0.0"

app = App(IDENTIFIER, app_context=Run)
for part in (core, values, detector, focus, acquisition, uc2):
    app.registry.merge(part.app.registry)
