"""Multidimensional acquisition: moving a stage, lighting a sample, and imaging it."""

from arkitekt import App

from newswitch.microscope import locks
from newswitch.microscope.apps import detector, values
from newswitch.microscope.run import Run
from newswitch.routines.acquire import acquire

app = App("newswitch", app_context=Run)
app.registry.merge(values.app.registry)
app.registry.merge(detector.app.registry)

app.register_action(acquire, locks=[locks.MOTION, locks.SWAP, locks.TUNE])
