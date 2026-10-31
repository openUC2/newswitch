"""The app registry of one newswitch: what its instrument has, merged.

Each is a registry of its own (`newswitch.microscope.apps`): its states, contexts, startup hook,
actions and background tasks, as plain module-level functions. `create_registry` creates a fresh `App`
and merges the ones the instrument turns out to have:

1. the core every microscope has (the models, files, the expanse, calibration, light paths, hooks);
2. what it has: its variables, its detectors, a UC2 board;
3. what needs several of those, when all of them are there (focus, acquisition).

How it is served is not registered here. The detectors stream to a `FrameSink` context
(declared by the core, a protocol); ``main_fastapi.py`` and ``main_arkitekt.py`` each provide it
their way (the websocket live view's `FrameBroadcaster`, a lovekit sink), pass in the
arkitekt services they need, and register the UI they show (the description's ``ui`` or
``agent_ui``, checked strictly against what was merged here).

Without an instrument only the core is merged. Every app is run with its own `Run`, which holds its
one `build_microscope`: two apps share nothing.
"""

from typing import Any, Sequence

from arkitekt import App, Service

from newswitch.instrument.spec import Instrument
from newswitch.microscope.apps import acquisition, core, detector, focus, uc2, values
from newswitch.microscope.run import Run


def create_registry(instrument: Instrument | None, services: Sequence[Service[Any]] = ()) -> App:
    """A new app registry with what `instrument` has.

    Args:
        instrument: What to run; None: no devices, the core only.
        services: The arkitekt services the app is created with (lovekit for the agent).
    """
    app = App("newswitch", app_context=Run, services=services)
    app.registry.merge(core.app.registry)
    if instrument is None:
        return app

    moves = any(variable.verb == "moves" for variable in instrument.variables.values())
    detectors, sources = instrument.detectors(), instrument.sources()
    app.registry.merge(values.app.registry)
    if detectors:
        app.registry.merge(detector.app.registry)
    if moves and detectors:
        app.registry.merge(focus.app.registry)
    if moves and detectors and sources:
        app.registry.merge(acquisition.app.registry)
    if instrument.hardware.boards:
        app.registry.merge(uc2.app.registry)
    return app
