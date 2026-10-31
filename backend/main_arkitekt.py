"""newswitch as an arkitekt agent, shown in Orkestrator (the steps: `main`).

    NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just agent
    uv run --extra agent python main_arkitekt.py

`create_arkitekt_registry` registers newswitch for Orkestrator: the microscope
(`create_registry`, with the lovekit service), a `LovekitSink` as the detectors'
`FrameSink`, published as one lovekit stream per detector, and the description's ``agent_ui``
bloks in Orkestrator's catalog. `main` logs in to the arkitekt server (fakts: ``--url`` or ``$FAKTS_URL``, else
the public deployment) and provides it until stopped.

An agent serves no HTTP routes: the files the IO manager writes and the frame cache
(``main_fastapi.py``) are not reachable from Orkestrator, so a frame's cache id or a file
handle points nowhere there. Serving them through arkitekt is open.

Needs the extra ``agent`` (``uv sync --extra agent``).
"""

from typing import Tuple

from arkitekt import App, run
from lovekit import lovekit_service
from mikro import Mikro, mikro_service

from newswitch.bloks import declare_agent_ui
from newswitch.broadcasters.lovekit import (
    CameraStream,
    CameraStreams,
    LovekitSink,
    publish_camera_streams,
)
from newswitch.instrument.spec import Instrument
from newswitch.microscope.registry import create_registry
from newswitch.broadcasters import FrameSink
from newswitch.microscope.run import Run
from newswitch.protocols.dataset_store import DatasetStore
from newswitch.services.mikro_store import MikroDatasetStore
from newswitch.settings import load_settings


def cameras_of(instrument: Instrument | None) -> list[CameraStream]:
    """A stream per detector, keyed by its cube (lovekit keeps a stream's id by its key over
    restarts), titled by that too."""
    if instrument is None:
        return []
    return [CameraStream(detector=name, key=name, title=name) for name in instrument.detectors()]


async def provide_lovekit_sink(current: Run) -> Tuple[FrameSink, CameraStreams]:
    """Startup: the detectors stream to a lovekit sink, one stream per detector."""
    return LovekitSink(cameras_of(current.instrument)), CameraStreams()


async def provide_dataset_store(current: Run, client: Mikro) -> DatasetStore:
    """Startup: acquisitions are stored in the mikro the server provides."""
    return MikroDatasetStore(client, current.instrument, current.microscope)


def create_arkitekt_registry(instrument: Instrument | None) -> App:
    """Step 3: the registry of `instrument` for Orkestrator: a lovekit stream per detector, and
    the mikro the server provides."""
    app = create_registry(instrument, services=(lovekit_service, mikro_service))
    app.register_state(CameraStreams)
    app.register_startup(provide_lovekit_sink)
    app.register_startup(provide_dataset_store)
    if cameras_of(instrument):
        app.register_background(publish_camera_streams)
    declare_agent_ui(app, instrument)
    return app


def create(current: Run) -> App:
    """Step 3: the instrument of `current`, registered."""
    return create_arkitekt_registry(current.instrument)


def main() -> None:
    """Steps 1-4: settings, registry, then run until stopped."""
    current = Run.of(load_settings())
    run(create(current), context=current)


if __name__ == "__main__":
    main()
