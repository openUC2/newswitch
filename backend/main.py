"""newswitch: how a running microscope is put together. Start here.

    NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just agent --url <server>  # app.py
    NEWSWITCH_CONFIG=instruments/fake-microscope/microscope.yml just dev                   # main_fastapi.py
    uv run python main.py [arkitekt | fastapi]

newswitch is an arkitekt app (``app.py``), which Orkestrator shows: the standard way to run it. The
same app can be served by FastAPI to the newswitch frontend instead (``main_fastapi.py``). Both
register the same, and both start the same way:

1. registry  every part a microscope can have, whatever the instrument has:
             `newswitch.microscope.registry.app`, which both include; ``app.py``'s global ``app``
             is one static declaration that arkitekt can inspect and compile without an
             instrument (``arkitekt inspect all app``);
2. serve     - `app`: declares a lovekit stream per detector, the mikro the server provides and the
               agent's bloks (`newswitch.infra.ui.AGENT_BLOKS`, Orkestrator's catalog), and runs
               it as an arkitekt agent;
             - `main_fastapi`: adds the websocket live view's `FrameBroadcaster` and the
               description's ``ui`` bloks (the newswitch frontend's catalog), and serves it with
               auth, accounts, live view, files and the cache;
3. settings  `newswitch.settings.load_settings`: the ``settings`` section of the instrument
             ``NEWSWITCH_CONFIG`` names, read when it starts;
4. devices   `newswitch.settings.load_devices`: the instrument the settings point at, its
             ``microscope.yml`` (``instruments/README.md``), which is only ever read. Together
             they are the app context, a `newswitch.microscope.run.Run`; a part the instrument
             lacks is there all the same, empty.

Tools beside them (compiling an instrument, exporting the frontend's schemas) are in
`newswitch.tools`; recovering accounts in `newswitch.infra.accounts.cli`. What serves the
microscope (auth, routes, streams, mikro, the UI) is `newswitch.infra`; the rest is the microscope.
"""

import argparse


def main(argv: list[str] | None = None) -> None:
    """Serve newswitch the way the command line says: as an arkitekt agent unless told otherwise."""
    parser = argparse.ArgumentParser(prog="python main.py", description=__doc__.splitlines()[0])
    parser.add_argument(
        "mode",
        nargs="?",
        default="arkitekt",
        choices=["arkitekt", "fastapi"],
        help="how to serve newswitch (default: arkitekt)",
    )
    args = parser.parse_args(argv)
    if args.mode == "fastapi":
        import main_fastapi

        main_fastapi.main()
    else:
        import app  # needs the extra agent

        app.main()


if __name__ == "__main__":
    main()
