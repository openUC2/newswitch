"""A UC2 board driving a stage: what the bus reports moves the stage's state."""

from arkitekt import App

from newswitch.actions import uc2 as uc2_actions
from newswitch.microscope.apps import stage, uc2
from newswitch.microscope.run import Run

app = App("newswitch", app_context=Run)
app.registry.merge(uc2.app.registry).merge(stage.app.registry)

app.register_background(uc2_actions.run_uc2_event_dispatch)
