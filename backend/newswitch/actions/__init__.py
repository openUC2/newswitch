"""What newswitch can do, per part of the microscope: plain functions, nothing registered here.

``app.py`` imports and registers each function directly (FastAPI mode through the part registries
of `newswitch.microscope.apps`), whatever the instrument has: an action of a part it lacks fails
when it is called. The routines that need several parts live in
`newswitch.routines`.
"""
