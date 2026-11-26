"""One microscope, as its instrument describes it, and its app registry.

- `startup`: the startup hooks, plain functions; `models`: `MODELS`, every model; both
  registered by the part registries of `apps`;
- `registry`: who newswitch is (`IDENTIFIER`, `VERSION`, `DESCRIPTION`), and `app`, every part
  included, which the agent and FastAPI mode both serve;
- `apps`: one registry per part: its states, contexts, startup hook and actions;
- `run`: `Run`, the app context: what one run has;
- `parts`: `build_microscope`: the managers and states of what the instrument has, as a
  `Microscope` record;
- `locks`: one lock per part (and per shared service).

Import the modules themselves; this package imports nothing.
"""
