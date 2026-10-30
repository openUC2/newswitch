"""One microscope, as its instrument describes it, and its app registry.

- `registry`: `create_registry` creates the app registry and merges into it the parts the
  instrument has;
- `apps`: one registry per part: its states, contexts, startup hook and actions;
- `run`: `Run`, the app context: what one run has;
- `parts`: `build_microscope`: the managers and states of what the instrument has, as a
  `Microscope` record;
- `locks`: one lock per part (and per shared service).

Import the modules themselves; this package imports nothing.
"""
