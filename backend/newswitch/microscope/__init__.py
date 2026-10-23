"""One microscope, as the device configuration describes it, and its app registry.

- `registry`: `create_registry` creates the app registry and registers on it, explicitly,
  what the configured devices need, with one startup hook per part;
- `parts`: `configured_parts` (which parts) and `build_microscope` (their managers and
  states, as a `Microscope` record);
- `locks`: one lock per part (and per shared service).

Import the modules themselves; this package imports nothing.
"""
