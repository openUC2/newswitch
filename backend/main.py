"""newswitch: how a running microscope is put together. Start here.

    NEWSWITCH_CONFIG=configs/newswitch-config.fluorescence.yaml just dev     # main_fastapi.py
    NEWSWITCH_CONFIG=configs/newswitch-config.fluorescence.yaml just agent   # main_arkitekt.py
    uv run python main.py fastapi | arkitekt

newswitch is served one of two ways. Both start the same way, then register what is
particular to them:

1. settings  `newswitch.settings.load_settings`: ``backend/base_config.yaml``, or the file
             ``NEWSWITCH_CONFIG`` names in its place (a device configuration ``.yaml``, or
             settings overrides ``.json``);
2. devices   `load_devices`: the device configuration the settings point at
             (``configs/README.md``), with the UI section the server shows;
3. registry  `newswitch.microscope.registry.create_registry`: a fresh app registry with
             only what the configured devices need registered on it;
4. serve     - `main_fastapi`: registers the websocket live view's `FrameBroadcaster` and
               the ``ui`` bloks (the newswitch frontend's catalog), and serves the registry
               with auth, accounts, live view, files and the cache;
             - `main_arkitekt`: registers a lovekit stream per detector and the
               ``agent_ui`` bloks (Orkestrator's catalog), and runs it as an arkitekt agent.

Tools beside them (building a configuration from a design, exporting the frontend's
schemas, recovering accounts) are in `newswitch.tools`.
"""

import argparse

from newswitch import config_io, settings
from newswitch.instrument.spec import Instrument


def load_devices(
    config: settings.Settings, ui_section: str
) -> config_io.NewswitchConfig | Instrument | None:
    """Step 2: the device configuration of `config`, which must have `ui_section`, or its instrument.

    Raises:
        config_io.ConfigError: It has no `ui_section` (``ui`` for FastAPI, ``agent_ui``
            for arkitekt): newswitch shows only the bloks its configuration lists. An instrument
            runs in FastAPI mode only: it has no ``agent_ui``.
    """
    devices = settings.load_devices(config)
    if isinstance(devices, Instrument):
        if ui_section != "ui":
            raise config_io.ConfigError(
                f"{devices.name} is an instrument, which runs in FastAPI mode only so far"
            )
        return devices
    if devices is not None and getattr(devices, ui_section) is None:
        raise config_io.ConfigError(
            f"{config.config_file} has no {ui_section} section: newswitch shows only the "
            "bloks its configuration lists (see configs/README.md)"
        )
    return devices


def main(argv: list[str] | None = None) -> None:
    """Serve newswitch the way the command line says."""
    parser = argparse.ArgumentParser(prog="python main.py", description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["fastapi", "arkitekt"], help="how to serve newswitch")
    args = parser.parse_args(argv)
    if args.mode == "fastapi":
        import main_fastapi

        main_fastapi.main()
    else:
        import main_arkitekt  # needs the extra agent

        main_arkitekt.main()


if __name__ == "__main__":
    main()
