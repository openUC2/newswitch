"""Multidimensional acquisition: moving a stage, lighting a sample, and imaging it."""

from arkitekt import App

from newswitch.microscope.apps import detector, illumination, stage
from newswitch.microscope.run import Run
from newswitch.routines import multidimensional_acquisition as mda

app = App("newswitch", app_context=Run)
app.registry.merge(stage.app.registry)
app.registry.merge(illumination.app.registry)
app.registry.merge(detector.app.registry)

app.register_action(mda.acquire_multidimensional_acquisition)
