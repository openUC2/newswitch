"""The locks of a microscope: one per part (and per shared service), held by the actions using it.

A state's ``required_locks`` and a context's ``locks`` name these; an action taking that state
or context holds them while it runs (arkitekt infers them), so two actions using the same
part never run at once. Keep the strings stable: clients know the locks by name.
"""

STAGE = "stage_position"
ILLUMINATION = "illumination"
DETECTOR = "camera_parameters"
OBJECTIVE = "objective"
FILTER_BANK = "filter_bank"
GALVO = "galvo"
IO = "io"
HOOKS = "hook_registry"
EXPANSE = "expanse_state"
CACHE = "cache"
