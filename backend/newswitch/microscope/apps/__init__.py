"""One registry per part of a microscope, for FastAPI mode; `newswitch.microscope.registry` merges them.

The agent (``app.py``) registers the same directly, without these.

Every module declares an ``app``: its states, contexts, startup hook, actions and background tasks,
as plain module-level functions. A part merges the parts it names things of, so what reaches an app
through two parts counts once. Nothing here depends on an instrument: every part is merged, and
what each hook (`newswitch.microscope.startup`) hands out comes from the `Run` it is given (None
for a context the instrument lacks).

Declare nothing on them from outside: they live as long as the process, and every app merges them.
"""
