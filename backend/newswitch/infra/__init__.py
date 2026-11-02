"""What serves the microscope, apart from it: users and auth, routes, streams, storage, the UI.

- `accounts`: users and auth of the FastAPI server (``cli``: their recovery from a shell);
- `http`: what ``main_fastapi.py`` serves beside the agent (live view, files, cache);
- `streaming`: the `FrameSink`s the detectors stream to (websocket live view; `lovekit` for the
  agent);
- `mikro`: where an acquisition is stored (`DatasetStore`): a mikro, or nowhere;
- `ui`: the bloks the frontend and Orkestrator show, checked against their catalogs;
- `export_schemas`: the schemas the frontend generates its hooks from (just export-schemas).

The rest of `newswitch` is the microscope. This package imports it; it never imports this one, nor
the entry files that put it together (``tests/test_layering.py``), so the microscope runs, and is tested, without anything here.
"""
