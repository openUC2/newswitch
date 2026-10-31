"""The models: what travels by value in arguments, returns and states."""

from arkitekt import App

from newswitch import models
from newswitch.actions import uc2
from newswitch.microscope.run import Run
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.devices import Detector, DetectorAxis, Filter, Illumination, ObjectiveLens
from newswitch.models.hooks import RegisteredHook, SoftwareAutofocusHook, ZCalibrationHook

app = App("newswitch", app_context=Run)

for model in (
    Illumination,
    Detector,
    DetectorAxis,
    ObjectiveLens,
    Filter,
    models.LightEdge,
    models.LightElement,
    models.LightPath,
    models.LightPathSnapshot,
    models.DetectorOptics,
    models.SourceOptics,
    models.OpticalChannel,
    models.Metadata,
    models.Image,
    models.Scale,
    models.ArrayMetadata,
    models.Frame,
    SoftwareAutofocusHook,
    ZCalibrationHook,
    RegisteredHook,
    CalibratedLightPath,
    models.StreamIllumination,
    models.Streams,
    models.AcquiredDataset,
    models.Stack,
    models.Position,
    models.Timepoint,
    models.MultidimensionalAcquisition,
    uc2.GalvoStatus,
):
    app.register_model(model)
