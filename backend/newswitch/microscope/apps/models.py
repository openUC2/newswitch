"""The models: what travels by value in arguments, returns and states (`MODELS`)."""

from arkitekt import App

from newswitch.microscope.models import MODELS
from newswitch.microscope.run import Run

app = App("newswitch", app_context=Run)

for model in MODELS:
    app.register_model(model)
