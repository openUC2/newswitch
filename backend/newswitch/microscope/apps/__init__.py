"""One registry per part of a microscope; `newswitch.microscope.registry` includes them.

Every module declares an ``app``: its states, contexts, startup hook, actions and background tasks,
as plain module-level functions. A part includes the parts it names things of (`App.include`), so what reaches an
app through two parts counts once. Nothing here depends on an instrument: every part is included, and
what each hook (`newswitch.microscope.startup`) hands out comes from the `Run` it is given (None
for a context the instrument lacks).

Declare nothing on them from outside: they live as long as the process, and every app includes them.
"""
