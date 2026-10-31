"""What an acquisition becomes in mikro: an `ArrayDataset`, with anchors, placed in stage space.

=================== =================================================================
dataset             ``(t, c, z, y, x)`` of one stage position
channel anchor      ``c``: its label, and the light path it was seen through
plane anchor        ``t, c, z``: the microscope's state, and when the image was taken
registration edge   pixels to the shared stage space of this microscope
=================== =================================================================

Importing this needs the extra ``mikro``.
"""

from typing import Any, Mapping

import xarray as xr
from mikro import Mikro, dataset_arrays, space_3d
from mikro.api import schema
from mikro.api.schema import (
    AcquisitionWindowInput,
    AxisAnchorInput,
    CoordinateAnchorInput,
    DeviceStateInput,
    DimensionPartInput,
    LabelInput,
    LightEdgeInput,
    LightpathGraphInput,
    OptikitStateInput,
    PartKind,
    PlacementValidity,
    SettingInput,
    StageStateInput,
)
from mikro.inputs.lightpath import in_out

from newswitch.instrument import parts as instrument_parts
from newswitch.instrument import spec
from newswitch.instrument.spec import Instrument
from newswitch.microscope.parts import Microscope
from newswitch.models.acquisition import AcquiredDataset
from newswitch.protocols.dataset_store import AcquiredChannel, AcquiredPlane, AcquiredPosition

AXES = ("t", "c", "z", "y", "x")
#: The axes of a dataset from a detector timing its photons: `MICROTIME` comes before space.
MICROTIME_AXES = ("t", "c", "m", "z", "y", "x")
#: The axes a dataset shares with the stage's space.
SPATIAL = ("z", "y", "x")


def _dataset_axes(
    instrument: Instrument, acquired: AcquiredPosition
) -> tuple[tuple[str, ...], list[Any], dict[str, Any]]:
    """The names of a dataset's axes, as `create_array_dataset` wants them, and as a pyramid does."""
    if acquired.data.ndim == len(AXES):
        return AXES, list(AXES), {}
    bins = next(
        axis for axis in instrument.detector_axes(acquired.channels[0].detector) if axis.name == "m"
    )
    declared = schema.AxisInput(
        name="m",
        type=schema.AxisType.MICROTIME,
        description=f"Arrival time after the pulse, in bins of {bins.step:g} ps",
    )
    return (
        MICROTIME_AXES,
        [declared if name == "m" else name for name in MICROTIME_AXES],
        {"m": "MICROTIME"},
    )


def _optical_element(instrument: Instrument, name: str, state: Mapping[str, Any]) -> Any:  # noqa: ANN401
    """A cube as mikro's optical element of its kind."""
    element = instrument.cubes[name].element_at(state)
    common: dict[str, Any] = {"id": name, "label": name, "ports": in_out()}
    match element:
        case spec.Source(emits="laser"):
            return schema.LaserElementInput(nominal_wavelength=f"{element.wavelength} nm", **common)
        case spec.Source():
            return schema.LampElementInput(**common)
        case spec.SampleHolder():
            return schema.SampleElementInput(**common)
        case spec.Sensor():
            return schema.CCDElementInput(pixel_size=f"{element.axes['x'].pitch} um", **common)
        case spec.PointDetector():
            return schema.DetectorElementInput(**common)
        case spec.Pinhole():
            return schema.PinholeElementInput(diameter=f"{element.diameter} um", **common)
        case spec.Scanner():  # mikro has no galvo: a scanner is a mirror that turns
            return schema.MirrorElementInput(**common)
        case spec.Filter():
            return schema.FilterElementInput(**common)
        case spec.Dichroic() | spec.Splitter():
            return schema.BeamSplitterElementInput(**common)
        case spec.Lens(na=na) if na is not None:
            return schema.ObjectiveElementInput(numerical_aperture=na, **common)
        case spec.Lens(f=f) if f is not None:
            return schema.LensElementInput(focal_length=f"{f} mm", **common)
    return schema.OtherElementInput(**common)


def light_graph(
    instrument: Instrument, channel: AcquiredChannel, state: Mapping[str, Any]
) -> LightpathGraphInput:
    """The way light took to `channel`: its sources to the sample, the sample to its detector."""
    edges = instrument.edges_to(channel.detector, channel.sources)
    hops = list(dict.fromkeys((edge.source, edge.target) for edge in edges))
    names = list(dict.fromkeys(name for hop in hops for name in hop))
    return LightpathGraphInput(
        elements=[_optical_element(instrument, name, state) for name in names],
        edges=[
            LightEdgeInput(
                id=f"{index}",
                source_element_id=source,
                source_port_id="out",
                target_element_id=target,
                target_port_id="in",
            )
            for index, (source, target) in enumerate(hops)
        ],
    )


def _setting(name: str, value: Any) -> SettingInput:  # noqa: ANN401 - a variable's value
    if isinstance(value, bool):
        return SettingInput(name=name, flag=value)
    if isinstance(value, (int, float)):
        return SettingInput(name=name, number=float(value))
    return SettingInput(name=name, text=str(value))


def microscope_state(instrument: Instrument, state: Mapping[str, Any]) -> OptikitStateInput:
    """What every device was set to; the stage as lengths, the rest as settings."""
    moves = instrument_parts.stage_moves(instrument)
    stage = {short: f"{state[move.name]} um" for short, move in moves.items() if short in "xyz"}
    devices = [
        DeviceStateInput(
            label=cube.name,
            settings=[
                _setting(short, state[variable.name]) for short, variable in cube.variables.items()
            ],
        )
        for cube in instrument.cubes.values()
        if cube.variables and cube.name != instrument.parts.stage
    ]
    return OptikitStateInput(stage=StageStateInput(**stage), devices=devices)


def _anchors_of_channels(
    instrument: Instrument, acquired: AcquiredPosition
) -> list[CoordinateAnchorInput]:
    first_state = {plane.c: plane.state for plane in reversed(acquired.planes)}
    return [
        CoordinateAnchorInput(
            axis_anchors=[AxisAnchorInput(axis="c", value=index)],
            label=LabelInput(label=channel.label),
            light_graph=light_graph(instrument, channel, first_state[index]),
        )
        for index, channel in enumerate(acquired.channels)
    ]


def _anchor_of_plane(instrument: Instrument, plane: AcquiredPlane) -> CoordinateAnchorInput:
    return CoordinateAnchorInput(
        axis_anchors=[
            AxisAnchorInput(axis="t", value=plane.t),
            AxisAnchorInput(axis="c", value=plane.c),
            AxisAnchorInput(axis="z", value=plane.z),
        ],
        microscope=microscope_state(instrument, plane.state),
        acquisition_window=AcquisitionWindowInput(start=plane.started, end=plane.ended),
    )


class MikroDatasetStore:
    """Stores what an acquisition merged in mikro, in the space of this microscope's stage."""

    def __init__(self, client: Mikro, instrument: Instrument, microscope: Microscope) -> None:
        """A store through `client`, reading the states of `microscope`."""
        self.client = client
        self.instrument = instrument
        self.microscope = microscope

    def check(self) -> None:
        """A client is there: it connects with its first call, so a mikro that is down is only
        found out then."""

    def state(self) -> Mapping[str, Any]:
        """What the running microscope is set to now."""
        m = self.microscope
        return instrument_parts.runtime_state(
            self.instrument,
            m.camera_state,
            m.stage_state,
            m.objective_state,
            m.illumination_state,
            m.filter_bank_state,
        )

    def publish(self, acquired: AcquiredPosition) -> AcquiredDataset:
        """Write `acquired`: the images, their anchors, and their place in the stage's space.

        The space is found again by its reference, so every image of this microscope lands in the
        same one; the reference names the microscope, as two of them have two different stages.
        """
        names, axes, types = _dataset_axes(self.instrument, acquired)
        image = xr.DataArray(acquired.data, dims=names)
        level_zero, scales = dataset_arrays(image, levels=1, method="mean", types=types)
        dataset = self.client.create_array_dataset(
            data=level_zero,
            scales=scales,
            name=acquired.name,
            axes=axes,
            anchors=[
                *_anchors_of_channels(self.instrument, acquired),
                *(_anchor_of_plane(self.instrument, plane) for plane in acquired.planes),
            ],
        )
        world = space_3d(self.client, "stage", reference=f"stage-{self.instrument.name}")
        dataset.intrinsic_system.transform_to(
            world,
            kind="BY_DIMENSION",
            parts=[
                DimensionPartInput(
                    kind=PartKind.AFFINE,
                    input_axes=SPATIAL,
                    output_axes=SPATIAL,
                    affine=acquired.to_stage,
                )
            ],
            name=f"{acquired.name} -> stage",
            validity=PlacementValidity.VALIDATED
            if acquired.calibrated
            else PlacementValidity.INFERRED,
        )
        return AcquiredDataset(id=str(dataset.id), name=acquired.name, position=acquired.position)
