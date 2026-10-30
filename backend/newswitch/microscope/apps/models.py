"""The models: what travels by value in arguments, returns and states."""

from arkitekt import App

from newswitch import models
from newswitch.actions import uc2
from newswitch.microscope.run import Run
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.devices import Detector, Filter, Illumination, ObjectiveLens
from newswitch.models.hooks import RegisteredHook, SoftwareAutofocusHook, ZCalibrationHook

app = App("newswitch", app_context=Run)

for model in (
    Illumination,
    Detector,
    ObjectiveLens,
    Filter,
    models.ObjectiveKube,
    models.ObjectiveTurretKube,
    models.DetectorKube,
    models.IlluminationKube,
    models.DichroicKube,
    models.StageKube,
    models.FilterKube,
    models.FilterBankKube,
    models.GenericKube,
    models.LightEdge,
    models.LightPath,
    models.ObjectiveKubeState,
    models.DichroicKubeState,
    models.DetectorKubeState,
    models.IlluminationKubeState,
    models.FilterKubeState,
    models.FilterBankKubeState,
    models.ObjectiveTurretKubeState,
    models.StageKubeState,
    models.GenericKubeState,
    models.LightEdgeState,
    models.LightPathSnapshot,
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
    models.Stack,
    models.Position,
    models.Timepoint,
    models.MultidimensionalAcquisition,
    uc2.GalvoStatus,
):
    app.register_model(model)
