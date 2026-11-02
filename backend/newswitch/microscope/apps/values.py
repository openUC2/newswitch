"""What can change on a microscope, by what it does."""

from typing import Tuple

from arkitekt import App

from newswitch.actions import space, values
from newswitch.microscope import locks
from newswitch.microscope.apps import core
from newswitch.microscope.run import Run
from newswitch.services.values import Values
from newswitch.states.values import MoveState, SourceState, SwapState, TuneState

app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry)
app.register_state(MoveState)
app.register_state(SwapState)
app.register_state(TuneState)
app.register_state(SourceState)
app.register_context(Values)


async def provide_values(
    run: Run,
) -> Tuple[Values, MoveState, SwapState, TuneState, SourceState]:
    """Every variable."""
    m = run.microscope
    return m.values, m.move_state, m.swap_state, m.tune_state, m.source_state


app.register_startup(provide_values)
app.register_action(values.move, locks=[locks.MOTION])
app.register_action(values.move_one, locks=[locks.MOTION])
app.register_action(values.move_home, locks=[locks.MOTION])
app.register_action(values.swap, locks=[locks.SWAP])
app.register_action(values.tune, locks=[locks.TUNE])
app.register_action(space.move_to, locks=[locks.MOTION])
app.register_action(space.set_sample_origin_here)
app.register_action(space.register_mount)
app.register_action(space.mount_holder, locks=[locks.MOTION, locks.EXPANSE])
