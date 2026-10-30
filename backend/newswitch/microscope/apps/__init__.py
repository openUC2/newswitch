"""One registry per part of a microscope; `newswitch.microscope.registry` merges the ones it has.

Every module declares an ``app``: its states, contexts, startup hook, actions and background tasks,
as plain module-level functions. A part merges the parts it names things of, so what reaches an app
through two parts counts once. Nothing here depends on an instrument: which parts a run has is decided
by what gets merged, and what each hook hands out comes from the `Run` it is given.

Declare nothing on them from outside: they live as long as the process, and every app merges them.
"""
