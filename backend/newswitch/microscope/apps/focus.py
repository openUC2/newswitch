"""Focusing: a stage to move and a detector to see with."""

from arkitekt import App

from newswitch.calibration.light_path import calibrate_light_path
from newswitch.microscope import locks
from newswitch.microscope.apps import detector, values
from newswitch.microscope.run import Run
from newswitch.microscope.startup import provide_focus
from newswitch.routines.autofocus import run_autofocus
from newswitch.routines.region_scan import scan_region
from newswitch.states.autofocus import AutofocusState

app = App("newswitch", app_context=Run)
app.registry.merge(values.app.registry).merge(detector.app.registry)

app.register_state(AutofocusState)
app.register_startup(provide_focus)
app.register_action(run_autofocus, locks=[locks.MOTION, locks.DETECTOR])
app.register_action(calibrate_light_path, locks=[locks.MOTION, locks.DETECTOR])
app.register_action(scan_region, locks=[locks.MOTION, locks.DETECTOR, locks.EXPANSE, locks.IO])
