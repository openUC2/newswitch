"""The light sources."""

from typing import Tuple

from arkitekt import App

from newswitch.actions import illumination
from newswitch.microscope import locks
from newswitch.microscope.apps import core
from newswitch.microscope.run import Run
from newswitch.protocols.illumination import IlluminationManager
from newswitch.states.illumination import IlluminationState

app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry)

app.register_state(IlluminationState, required_locks=[locks.ILLUMINATION])
app.register_context(IlluminationManager, locks=[locks.ILLUMINATION])


async def provide_illumination(run: Run) -> Tuple[IlluminationManager, IlluminationState]:
    """The light sources."""
    return run.microscope.illumination, run.microscope.illumination_state


app.register_startup(provide_illumination)
app.register_action(illumination.set_illumination_intensity)
app.register_action(illumination.turn_on_illumination)
app.register_action(illumination.turn_off_illumination_channel)
