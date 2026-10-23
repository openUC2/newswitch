"""newswitch as an arkitekt agent, shown in Orkestrator (the steps: `main`).

    NEWSWITCH_CONFIG=configs/newswitch-config.fluorescence.yaml just agent
    uv run --extra agent python main_arkitekt.py

`create_arkitekt_registry` registers newswitch for Orkestrator: the microscope
(`create_registry`, with the lovekit service), a `LovekitSink` as the detectors'
`FrameSink`, published as one lovekit stream per detector, and the ``agent_ui`` bloks in
Orkestrator's catalog. `main` logs in to the arkitekt server (fakts: ``--url`` or ``$FAKTS_URL``, else
the public deployment) and provides it until stopped.

An agent serves no HTTP routes: the files the IO manager writes and the frame cache
(``main_fastapi.py``) are not reachable from Orkestrator, so a frame's cache id or a file
handle points nowhere there. Serving them through arkitekt is open.

Needs the extra ``agent`` (``uv sync --extra agent``).
"""

from typing import Tuple

from arkitekt import App, run
from lovekit import lovekit_service

from main import load_devices
from newswitch.bloks import declare_agent_ui
from newswitch.broadcasters.lovekit import (
    CameraStream,
    CameraStreams,
    LovekitSink,
    publish_camera_streams,
)
from newswitch.config_io import NewswitchConfig
from newswitch.config_io.devices import DetectorConfig
from newswitch.microscope.registry import create_registry
from newswitch.broadcasters import FrameSink
from newswitch.settings import Settings, load_settings
from newswitch.settings import load_devices as load_configured_devices


def cameras_of(devices: NewswitchConfig | None) -> list[CameraStream]:
    """A stream per detector, keyed by its configuration key (lovekit keeps a stream's id
    by its key over restarts; slots follow the file order), titled by its name."""
    if devices is None:
        return []
    return [
        CameraStream(slot=index + 1, key=key, title=detector.name or key)
        for index, (key, detector) in enumerate(devices.keyed(DetectorConfig).items())
    ]


async def provide_lovekit_sink(app_context: Settings) -> Tuple[FrameSink, CameraStreams]:
    """Startup: the detectors stream to a lovekit sink, one stream per configured detector."""
    return LovekitSink(cameras_of(load_configured_devices(app_context))), CameraStreams()


def create_arkitekt_registry(devices: NewswitchConfig | None) -> App:
    """Step 3: the registry of `devices` for Orkestrator: a lovekit stream per detector."""
    app = create_registry(devices, services=(lovekit_service,))
    app.register_state(CameraStreams)
    app.register_startup(provide_lovekit_sink)
    if cameras_of(devices):
        app.register_background(publish_camera_streams)
    declare_agent_ui(app, devices)
    return app


def create(settings: Settings) -> App:
    """Steps 2-3: the device configuration of `settings` (with an ``agent_ui``), registered."""
    return create_arkitekt_registry(load_devices(settings, "agent_ui"))


def main() -> None:
    """Steps 1-4: settings, registry, then run until stopped."""
    settings = load_settings()
    run(create(settings), context=settings)


if __name__ == "__main__":
    main()
