"""The motion stage."""

from typing import Tuple

from arkitekt import App, OptimisticInput

from newswitch.actions import stage
from newswitch.microscope import locks
from newswitch.microscope.apps import core
from newswitch.microscope.run import Run
from newswitch.protocols.stage import StageManager
from newswitch.states.stage import StageState

app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry)

app.register_state(StageState, required_locks=[locks.STAGE])
app.register_context(StageManager, locks=[locks.STAGE])


async def provide_stage(run: Run) -> Tuple[StageManager, StageState]:
    """The motion stage."""
    return run.microscope.stage, run.microscope.stage_state


app.register_startup(provide_stage)
app.register_action(
    stage.move_stage,
    optimistics=[
        OptimisticInput(state=StageState.__name__, path=f"/{axis}", accessor=f"/{axis}")
        for axis in ("x", "y", "z", "a")
    ],
)
app.register_action(stage.move_home)
