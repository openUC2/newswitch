"""The locks of a microscope: one per way of changing it (and per shared service), held by an action.

A state's ``required_locks`` and a context's ``locks`` name these; an action taking such a state or
context holds them while it runs (arkitekt infers them), so two actions on one never run at once. A
move does not block changing a laser. Keep the strings stable: clients know the locks by them.
"""

MOTION = "motion"
SWAP = "swap"
TUNE = "tune"
DETECTOR = "detector"
GALVO = "galvo"
IO = "io"
HOOKS = "hook_registry"
EXPANSE = "expanse_state"
CACHE = "cache"
