"""Focusing: a stage to move and a detector to see with."""

from arkitekt import App

from newswitch.microscope import locks
from newswitch.microscope.apps import detector, values
from newswitch.microscope.run import Run
from newswitch.routines.autofocus import run_autofocus
from newswitch.routines.calibration import calibrate_light_path
from newswitch.routines.region_scan import scan_region
from newswitch.states.autofocus import AutofocusState

app = App("newswitch", app_context=Run)
app.registry.merge(values.app.registry).merge(detector.app.registry)

app.register_state(AutofocusState)


async def provide_focus(run: Run) -> AutofocusState:
    """The autofocus state."""
    return run.microscope.autofocus_state


app.register_startup(provide_focus)
app.register_action(run_autofocus, locks=[locks.MOTION])
app.register_action(calibrate_light_path, locks=[locks.MOTION])
app.register_action(scan_region, locks=[locks.MOTION])
