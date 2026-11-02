"""newswitch: a microscope, described by its optical elements, served through arkitekt.

Start at ``backend/main.py`` (how it is built and served: ``main_fastapi.py``,
``main_arkitekt.py``). The code is in two halves: the microscope, and `infra`, which serves it.
`infra` may import the microscope; the microscope never imports `infra` (``tests/test_layering.py``).

The microscope:

- `settings`: how it runs (``NEWSWITCH_CONFIG`` names the description that says);
- `instrument`: the description (`microscope.yml`), what follows from it, how it reaches hardware;
- `microscope`: the parts it has (`parts`) and the app registry they fill (`registry`);
- `actions`, `routines`: what the app offers, per part;
- `models`, `states`: the values exchanged and the states published;
- `protocols`: what each part (and each service) can do, and where detectors send frames
  (`FrameSink`);
- `drivers`: the parts' implementations (UC2 hardware, simulation); `services`: the shared
  managers (acquisition, light path, metadata, calibration, hooks, io, cache, expanse);
- `tools`: compiling an instrument, exporting schemas;
- `reference`: the complete microscope the frontend's schemas are exported from.

What serves it, `infra`:

- `infra.accounts`: users and auth (and their recovery from a shell, `infra.accounts.cli`);
- `infra.http`: what ``main_fastapi.py`` serves beside the agent (live view, files, cache);
- `infra.streaming`: the `FrameSink`s (websocket live view; `lovekit` for the agent);
- `infra.mikro`: where acquisitions are stored (mikro, or nowhere);
- `infra.ui`: the bloks the frontend and Orkestrator show, checked against their catalogs.
"""
