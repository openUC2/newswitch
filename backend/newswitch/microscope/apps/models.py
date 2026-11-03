"""The models: what travels by value in arguments, returns and states."""

from arkitekt import App

from newswitch import models
from newswitch.actions import uc2
from newswitch.microscope.run import Run
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.devices import AxisWindow, Detector, DetectorAxis
from newswitch.models.space import (
    Axis,
    CoordinateSystem,
    DetectorPlacement,
    DimensionPart,
    HolderShape,
    MeasuredPoint,
    Position,
    SampleSpace,
    Transformation,
    PlaceShape,
)
from newswitch.models.hooks import RegisteredHook, SoftwareAutofocusHook, ZCalibrationHook

app = App("newswitch", app_context=Run)

for model in (
    Detector,
    DetectorAxis,
    AxisWindow,
    Position,
    Axis,
    CoordinateSystem,
    DimensionPart,
    Transformation,
    DetectorPlacement,
    MeasuredPoint,
    SampleSpace,
    PlaceShape,
    HolderShape,
    models.LightEdge,
    models.LightElement,
    models.LightPath,
    models.LightPathSnapshot,
    models.DetectorOptics,
    models.LightSource,
    models.MoveValue,
    models.SwapOption,
    models.SwapValue,
    models.TuneValue,
    models.SourceOptics,
    models.ChannelSwap,
    models.OpticalChannel,
    models.Metadata,
    models.Image,
    models.Scale,
    models.ArrayMetadata,
    models.Frame,
    models.AcquisitionChannel,
    models.AcquisitionPosition,
    models.AcquisitionStack,
    models.AcquisitionPlan,
    SoftwareAutofocusHook,
    ZCalibrationHook,
    RegisteredHook,
    CalibratedLightPath,
    models.AcquiredDataset,
    uc2.GalvoStatus,
):
    app.register_model(model)
