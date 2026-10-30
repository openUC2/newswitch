"""The objectives."""

from typing import Tuple

from arkitekt import App

from newswitch.actions import objective
from newswitch.microscope import locks
from newswitch.microscope.apps import core
from newswitch.microscope.run import Run
from newswitch.protocols.objective import ObjectiveManager
from newswitch.states.objective import ObjectiveState

app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry)

app.register_state(ObjectiveState, required_locks=[locks.OBJECTIVE])
app.register_context(ObjectiveManager, locks=[locks.OBJECTIVE])


async def provide_objective(run: Run) -> Tuple[ObjectiveManager, ObjectiveState]:
    """The objectives."""
    return run.microscope.objective, run.microscope.objective_state


app.register_startup(provide_objective)
app.register_action(objective.switch_objective)
app.register_action(objective.toggle_objective)
