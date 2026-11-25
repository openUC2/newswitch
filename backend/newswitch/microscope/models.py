"""The models: what travels by value in arguments, returns and states, registered by name by the app
that serves them (``app.py``; FastAPI through `newswitch.microscope.apps.models`)."""

from newswitch import models
from newswitch.actions import uc2
from newswitch.calibration.models import CalibratedLightPath, MeasuredMount
from newswitch.models.devices import AxisWindow, Detector, DetectorAxis
from newswitch.models.hooks import RegisteredHook, SoftwareAutofocusHook, ZCalibrationHook
from newswitch.models.space import (
    Axis,
    CoordinateSystem,
    DetectorPlacement,
    DimensionPart,
    HolderShape,
    MeasuredPoint,
    PlaceShape,
    Position,
    SampleSpace,
    Transformation,
)
from newswitch.models.uc2 import UC2Node

#: Every model, in the order they are registered.
MODELS: tuple[type, ...] = (
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
    MeasuredMount,
    models.AcquiredDataset,
    uc2.GalvoStatus,
    UC2Node,
)
