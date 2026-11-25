"""Acquisition: going where a plan says, setting what it says, and imaging it."""

from arkitekt import App

from newswitch.microscope import locks
from newswitch.microscope.apps import detector, values
from newswitch.microscope.run import Run
from newswitch.routines.acquire import acquire
from newswitch.routines.mda import acquire_mda

app = App("newswitch", app_context=Run)
app.include(values.app, detector.app)

# Stated, so nothing is inferred from what it takes: everything it depends on staying as it is.
app.register_action(acquire, locks=[locks.MOTION, locks.SWAP, locks.TUNE, locks.DETECTOR])
# What a blok can ask for (it cannot build a plan): the plan made of plain values, then `acquire`.
app.register_action(acquire_mda, locks=[locks.MOTION, locks.SWAP, locks.TUNE, locks.DETECTOR])
