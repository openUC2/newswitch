"""What an acquisition becomes in mikro: an `ArrayDataset` per record, with anchors, on the sample.

=================== =================================================================
dataset             one detector at one position, along its own axes, each typed:
                    ``(t, c, z, y, x)`` of a camera; ``(t, c, plane, z, y, x)`` of a
                    thermometer, one position along ``z, y, x``: mikro's SCALAR
channel anchor      ``c``: its label, and the light path it was seen through (if light)
plane anchor        ``t, c, z``: the microscope's state, and when it was taken
registration edge   a BY_DIMENSION onto the sample's space, the record's parts as they are
=================== =================================================================

Importing this needs the extra ``mikro``.
"""

from datetime import datetime
from typing import Any, Mapping

from mikro import Mikro, dataset_arrays, space_3d, timelapse_3d
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

from newswitch.instrument import spec
from newswitch.instrument.spec import Instrument
from newswitch.microscope.parts import Microscope
from newswitch.models.acquisition import AcquiredDataset
from newswitch.models.space import DimensionPart
from newswitch.protocols.dataset_store import AcquiredChannel, AcquiredPlane, AcquiredRecord

#: The axes a dataset shares with the stage's space.
SPATIAL = ("z", "y", "x")

#: What an axis of each type says it is, beside its name.
_DESCRIPTIONS = {
    "TIME": "Each time it was taken, on its sample's clock: in seconds since it was mounted",
    "CHANNEL": "A channel of the plan, in a color of the detector",
    "INDEX": "The plane of the stack it was read at; what measures at a point is not placed by it",
}


def dataset_axes(
    instrument: Instrument, acquired: AcquiredRecord
) -> tuple[tuple[str, ...], list[schema.AxisInput], dict[str, Any]]:
    """The names of a record's axes, as `create_array_dataset` declares them, and their types, as
    a pyramid wants them: each as its detector delivers it."""
    steps = {axis.name: axis for axis in instrument.detector_axes(acquired.detector)}
    declared = []
    for axis in acquired.axes:
        description = _DESCRIPTIONS.get(axis.type)
        if axis.name == "m" and "m" in steps:
            description = f"Arrival time after the pulse, in bins of {steps['m'].step:g} ps"
        if axis.name == "s" and "s" in steps:
            description = f"A sample of a block in time, {steps['s'].step:g} ms apart"
        declared.append(
            schema.AxisInput(
                name=axis.name, type=schema.AxisType(axis.type), description=description
            )
        )
    return acquired.dims, declared, {axis.name: axis.type for axis in acquired.axes}


def mikro_parts(parts: tuple[DimensionPart, ...]) -> list[DimensionPartInput]:
    """A record's registration as mikro's BY_DIMENSION parts, part for part."""
    return [
        DimensionPartInput(
            kind=PartKind(part.kind),
            input_axes=tuple(part.input_axes),
            output_axes=tuple(part.output_axes),
            scale=None if part.scale is None else tuple(part.scale),
            translation=None if part.translation is None else tuple(part.translation),
            affine=None if part.affine is None else tuple(tuple(row) for row in part.affine),
        )
        for part in parts
    ]


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
    edges = instrument.edges_to(channel.detector, state, channel.sources)
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


def microscope_state(
    instrument: Instrument, state: Mapping[str, Any], sample: str
) -> OptikitStateInput:
    """What every device was set to; `sample`'s stage as lengths, the rest (another sample's stage
    too) as settings."""
    holder = sample
    moves = instrument.cubes[holder].moves
    stage = {short: f"{state[move.name]} um" for short, move in moves.items() if short in "xyz"}
    devices = [
        DeviceStateInput(
            label=cube.name,
            settings=[
                _setting(short, state[variable.name]) for short, variable in cube.variables.items()
            ],
        )
        for cube in instrument.cubes.values()
        if cube.variables and cube.name != holder
    ]
    return OptikitStateInput(stage=StageStateInput(**stage), devices=devices)


def anchors_of_channels(
    instrument: Instrument, acquired: AcquiredRecord
) -> list[CoordinateAnchorInput]:
    """What each index of a record's ``c`` is: its label, and the light path if light reached it."""
    first_state = {plane.c: plane.state for plane in reversed(acquired.planes)}
    return [
        CoordinateAnchorInput(
            axis_anchors=[AxisAnchorInput(axis="c", value=index)],
            label=LabelInput(label=channel.label),
            light_graph=light_graph(instrument, channel, first_state[index])
            if channel.light
            else None,
        )
        for index, channel in enumerate(acquired.channels)
    ]


def _anchor_of_plane(
    instrument: Instrument, plane: AcquiredPlane, sample: str, stack: str = "z"
) -> CoordinateAnchorInput:
    return CoordinateAnchorInput(
        axis_anchors=[
            AxisAnchorInput(axis="t", value=plane.t),
            AxisAnchorInput(axis="c", value=plane.c),
            AxisAnchorInput(axis=stack, value=plane.z),
        ],
        microscope=microscope_state(instrument, plane.state, sample),
        acquisition_window=AcquisitionWindowInput(start=plane.started, end=plane.ended),
    )


class MikroDatasetStore:
    """Stores what an acquisition merged in mikro, in the space of the sample it was taken of.

    One sample space per sample and mounting (``sample-<instrument>-<sample>-<mount id>``), and one
    stage space per sample's stage (``stage-<instrument>-<sample>``), the mount between them
    written whenever it is one not
    written yet: a mount registered later is an edge of its own.
    """

    def __init__(self, client: Mikro, instrument: Instrument, microscope: Microscope) -> None:
        """A store through `client`, reading the states of `microscope`."""
        self.client = client
        self.instrument = instrument
        self.microscope = microscope
        self._mounted: set[tuple[str, tuple[tuple[float, ...], ...]]] = set()

    def check(self) -> None:
        """A client is there: it connects with its first call, so a mikro that is down is only
        found out then."""

    def state(self) -> Mapping[str, Any]:
        """What the running microscope is set to now."""
        return self.microscope.values.snapshot()

    def publish(self, acquired: AcquiredRecord) -> AcquiredDataset:
        """Write `acquired`: what it took, its anchors, and its place on the sample.

        The sample's space is found again by its reference, so every record of one mounting lands
        in the same one, whatever detector took it.
        """
        names, axes, types = dataset_axes(self.instrument, acquired)
        level_zero, scales = dataset_arrays(
            acquired.data, levels=1, method="mean", dims=names, types=types
        )
        dataset = self.client.create_array_dataset(
            data=level_zero,
            scales=scales,
            name=acquired.name,
            axes=axes,
            anchors=[
                *anchors_of_channels(self.instrument, acquired),
                *(
                    _anchor_of_plane(self.instrument, plane, acquired.sample, acquired.stack)
                    for plane in acquired.planes
                ),
            ],
        )
        # One space a mounting: in seconds since it was mounted, and in micrometres of what is.
        sample = timelapse_3d(
            self.client,
            "sample",
            epoch=datetime.fromisoformat(acquired.mounted_at) if acquired.mounted_at else None,
            reference=f"sample-{self.instrument.name}-{acquired.sample}-{acquired.mount_id}-t",
        )
        dataset.intrinsic_system.transform_to(
            sample,
            kind="BY_DIMENSION",
            parts=mikro_parts(acquired.registration),
            name=f"{acquired.name} -> sample",
            validity=PlacementValidity.VALIDATED
            if acquired.calibrated
            else PlacementValidity.INFERRED,
        )
        if (acquired.mount_id, acquired.mount) not in self._mounted:
            stage = space_3d(
                self.client,
                "stage",
                reference=f"stage-{self.instrument.name}-{acquired.sample}",
            )
            stage.transform_to(
                sample,
                kind="BY_DIMENSION",
                parts=[
                    DimensionPartInput(
                        kind=PartKind.AFFINE,
                        input_axes=SPATIAL,
                        output_axes=SPATIAL,
                        affine=acquired.mount,
                    )
                ],
                name=f"mount {acquired.mount_id}",
            )
            self._mounted.add((acquired.mount_id, acquired.mount))
        return AcquiredDataset(
            id=str(dataset.id),
            name=acquired.name,
            position=acquired.position,
            detector=acquired.detector,
        )
