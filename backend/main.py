"""newswitch: how a running microscope is put together. Start here.

    NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just dev     # main_fastapi.py
    NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just agent   # main_arkitekt.py
    uv run python main.py fastapi | arkitekt

newswitch is served one of two ways. Both start the same way, then register what is
particular to them:

1. settings  `newswitch.settings.load_settings`: the ``settings`` section of the instrument
             ``NEWSWITCH_CONFIG`` names;
2. devices   `newswitch.settings.load_devices`: the instrument the settings point at, its
             ``microscope.yml`` (``instruments/README.md``), which is only ever read;
3. registry  `newswitch.microscope.registry.create_registry`: a fresh app registry with
             only what the instrument needs registered on it;
4. serve     - `main_fastapi`: registers the websocket live view's `FrameBroadcaster` and
               the description's ``ui`` bloks (the newswitch frontend's catalog), and serves the
               registry with auth, accounts, live view, files and the cache;
             - `main_arkitekt`: registers a lovekit stream per detector and the description's
               ``agent_ui`` bloks (Orkestrator's catalog), and runs it as an arkitekt agent.

Tools beside them (compiling an instrument, exporting the frontend's schemas) are in
`newswitch.tools`; recovering accounts in `newswitch.infra.accounts.cli`. What serves the
microscope (auth, routes, streams, mikro, the UI) is `newswitch.infra`; the rest is the microscope.
"""

import argparse


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
