"""The UC2 board."""

from typing import Tuple

from arkitekt import App

from newswitch.actions import uc2
from newswitch.microscope import locks
from newswitch.microscope.apps import core, values
from newswitch.microscope.run import Run
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.states.uc2 import UC2State

app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry).merge(values.app.registry)

app.register_state(UC2State)
app.register_context(UC2BusManager)


async def provide_uc2(run: Run) -> Tuple[UC2BusManager, UC2State]:
    """The UC2 board."""
    return run.microscope.uc2_bus, run.microscope.uc2_state


app.register_startup(provide_uc2)
app.register_background(uc2.run_uc2_bus)
app.register_background(uc2.run_uc2_event_dispatch)
app.register_action(uc2.home_stage, locks=[locks.MOTION])
app.register_action(uc2.stop_stage)
app.register_action(uc2.led_matrix_fill, locks=[locks.TUNE])
app.register_action(uc2.led_matrix_off, locks=[locks.TUNE])
app.register_action(uc2.uc2_scan_nodes)
app.register_action(uc2.home_objective, locks=[locks.SWAP])
app.register_action(uc2.galvo_set_position, locks=[locks.GALVO])
app.register_action(uc2.galvo_raster_scan, locks=[locks.GALVO])
app.register_action(uc2.galvo_stop)
app.register_action(uc2.galvo_get_status)
