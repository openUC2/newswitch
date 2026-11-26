"""newswitch as an arkitekt app: the agent Orkestrator shows. The standard way to run newswitch.

    NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just agent --url <server>
    NEWSWITCH_CONFIG=... uv run --extra agent python app.py --url <server>
    NEWSWITCH_CONFIG=... uv run --extra agent arkitekt run prod app --context app:load_run --url <server>
    uv run --extra agent arkitekt inspect all app        # what it declares, without an instrument

`app` is one global, static app, declared below at module level: it includes the microscope
(`newswitch.microscope.registry.app`: every model, state, context, startup hook, action and
background task newswitch has, on every microscope). So arkitekt can inspect it without an
instrument and compile it into a release. Which
microscope it runs is the app context, a `Run`, known only when it starts: `load_run` reads the
description ``NEWSWITCH_CONFIG`` names. A part that microscope lacks is there all the same, empty
(`newswitch.microscope.startup`): what an action is asked of is chosen from what a state lists,
and it lists nothing.

Beside the microscope, `app` declares what is particular to the agent: a `LovekitSink` as the
detectors' `FrameSink`, published as one lovekit stream per detector, the mikro the server provides
as the `DatasetStore`, and the agent's bloks (`AGENT_BLOKS`, in Orkestrator's catalog). `__main__`
logs in to the arkitekt server (fakts: ``--url`` or ``$FAKTS_URL``, else the public deployment)
and provides it until stopped.

FastAPI mode (``main_fastapi.py``) includes the same microscope registry; ``tests/test_registry.py``
holds the two to the same actions, states and locks.

An agent serves no HTTP routes: the files the IO manager writes and the frame cache
(``main_fastapi.py``) are not reachable from Orkestrator, so a frame's cache id or a file
handle points nowhere there. Serving them through arkitekt is open.

Needs the extra ``agent`` (``uv sync --extra agent``).
"""

import os
import sys
from typing import Tuple

from arkitekt import App, run
from lovekit import Lovekit
from mikro import Mikro

from newswitch.infra.mikro.store import MikroDatasetStore
from newswitch.infra.streaming.lovekit import (
    CameraStream,
    CameraStreams,
    LovekitSink,
    publish_camera_streams,
)
from newswitch.infra.ui import declare_agent_ui
from newswitch.instrument.spec import Instrument
from newswitch.logging_setup import setup_logging
from newswitch.microscope import registry
from newswitch.microscope.registry import DESCRIPTION, IDENTIFIER, VERSION
from newswitch.microscope.run import Run
from newswitch.protocols.dataset_store import DatasetStore
from newswitch.protocols.frame_sink import FrameSink
from newswitch.settings import SIMULATE_ENV_VAR, load_settings


def cameras_of(instrument: Instrument) -> list[CameraStream]:
    """A stream per detector, keyed by its cube (lovekit keeps a stream's id by its key over
    restarts), titled by that too."""
    return [CameraStream(detector=name, key=name, title=name) for name in instrument.detectors()]


async def provide_lovekit_sink(current: Run) -> Tuple[FrameSink, CameraStreams]:
    """Startup: the detectors stream to a lovekit sink, one stream per detector (none, without
    detectors: the publisher then has nothing to publish)."""
    # with `simulate: debug` the network is tested, not the cameras
    sink = LovekitSink(cameras_of(current.instrument), test_pattern=current.settings.test_pattern)
    return sink, CameraStreams()


async def provide_dataset_store(current: Run, client: Mikro) -> DatasetStore:
    """Startup: acquisitions are stored in the mikro the server provides."""
    return MikroDatasetStore(client, current.instrument, current.microscope)


def load_run() -> Run:
    """The app context: the run of the description ``NEWSWITCH_CONFIG`` names, in the mode
    ``NEWSWITCH_SIMULATE`` names, if any (``arkitekt run ... --context app:load_run``).

    Raises:
        SpecError: None is named, or what is named is no valid description.
    """
    return Run.of(load_settings(simulate=os.environ.get(SIMULATE_ENV_VAR))) #TODO: make this more functional, i want a load_run that takes a path and returns a run,


#: newswitch, as arkitekt finds it (``arkitekt ... app``, ``$ARKITEKT_APP``). Global, and declared
#: without reading anything of an instrument.
app = App(
    IDENTIFIER,
    VERSION,
    description=DESCRIPTION,
    app_context=Run,
    clients=[Lovekit, Mikro],
)

# --- the microscope: every part, whatever the instrument has (`newswitch.microscope.registry`)
app.include(registry.app)

# --- the agent's own: the cameras as lovekit streams, mikro from the server, Orkestrator's bloks
app.register_state(CameraStreams, name="camera_streams")
app.register_startup(provide_lovekit_sink)
app.register_startup(provide_dataset_store)
app.register_background(publish_camera_streams)
declare_agent_ui(app)


def main() -> None:
    """Run `app` on the microscope ``NEWSWITCH_CONFIG`` names, until stopped.

    ``--force`` takes over a connection the server still holds for this agent (one that was not
    closed, say, and has not timed out yet); without it such a start is refused.
    """
    # As sys_config.yaml says: what newswitch says at INFO (the firmware check, how the camera
    # streams keep up) is in the log file; on the terminal with log_to_terminal: info.
    setup_logging()
    run(app, context=load_run(), force="--force" in sys.argv[1:])


if __name__ == "__main__":
    main()
