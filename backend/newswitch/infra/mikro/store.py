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

import importlib.util
import logging
from dataclasses import dataclass
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

from newswitch.infra.mikro import histograms
from newswitch.infra.mikro.stream import (
    MikroRecordStream,
    Reduction,
    in_flight_limit,
    placeholder,
    pyramid_levels,
)
from newswitch.instrument import spec
from newswitch.instrument.spec import Instrument
from newswitch.microscope.parts import Microscope
from newswitch.models.acquisition import AcquiredDataset
from newswitch.models.space import DimensionPart
from newswitch.protocols.dataset_store import AcquiredChannel, AcquiredPlane, AcquiredRecord

#: The axes a dataset shares with the stage's space.
SPATIAL = ("z", "y", "x")
#: How a dataset's pyramid is made (`AcquisitionPlan.pyramid`): the max of each 2 x 2 in y and x,
#: so thin bright structures stay visible zoomed out; ``z`` keeps its planes.
PYRAMID_REDUCTION: Reduction = "max"
PYRAMID_AXES = ("y", "x")
#: What each reduction is recorded as on a level's edge (`mikro.pyramid`'s names for them).
_SCALE_METHODS = {"max": "MAX", "mean": "AREA", "nearest": "NEAREST"}

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


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Shown:
    """What a scene needs of a dataset: the sample space it is placed in, the color of each of its
    channels (None: not a color camera's), and its histograms by time point and channel."""

    space: str
    colors: tuple[str | None, ...]
    histograms: Mapping[tuple[int, int], Any]


#: The color a channel is drawn in, by the camera color it is.
_DRAWN = {"r": (255, 0, 0), "g": (0, 255, 0), "b": (0, 0, 255)}


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
        self._shown: dict[str, _Shown] = {}
        self._histograms: Mapping[tuple[int, int], Any] = {}  # of the dataset being written
        self._budget: Any = None  # what every stream waits on together (`stream`)
        """What a scene of each dataset published needs: where it is, its channels and contrast."""

    def show(self, name: str, datasets: list[AcquiredDataset]) -> list[str]:
        """A new scene of what one acquisition stored, named `name`: over the space of each sample
        it took (one scene a sample), a layer for each dataset, a color camera's as one RGB layer,
        any other's a layer per channel, each with its contrast from its histograms. The ids of the
        scenes made.

        A scene is a view: what cannot be drawn is logged and left out, the datasets stay.
        """
        by_space: dict[str, list[tuple[str, _Shown]]] = {}
        for dataset in datasets:
            shown = self._shown.get(dataset.id)
            if shown is not None:
                by_space.setdefault(shown.space, []).append((dataset.id, shown))
        scenes = []
        for space, members in by_space.items():
            scene = self.client.create_scene(name=name, coordinate_system=space)
            drawn = 0
            for order, (dataset, shown) in enumerate(members):
                try:
                    self._layers(str(scene.id), dataset, shown, order)
                    drawn += 1
                except Exception:  # noqa: BLE001 - a scene is a view; the data is stored
                    logger.exception("scene %s: dataset %s not drawn", name, dataset)
            logger.info(
                "scene %s (%s): %d of %d datasets drawn", scene.id, name, drawn, len(members)
            )
            scenes.append(str(scene.id))
        return scenes

    def _layers(self, scene: str, dataset: str, shown: _Shown, order: int) -> None:
        """Draw `dataset` into `scene`: RGB where its channels are a color camera's red, green and
        blue (in that order), else a layer per channel in its color."""
        whole = self.client.create_lens(dataset=dataset)

        def channel(c: int) -> str:
            return str(
                self.client.create_lens(
                    lens=whole.id, slices=[schema.SliceInput(axis="c", start=c, stop=c + 1)]
                ).id
            )

        colors = list(shown.colors)
        c = 0
        while c < len(colors):
            if colors[c : c + 3] == ["r", "g", "b"]:
                windows = [histograms.contrast(shown.histograms, c + k) for k in range(3)]
                lows = [w[0] for w in windows if w is not None]
                highs = [w[1] for w in windows if w is not None]
                self.client.create_rgb_layer(
                    lens=whole.id,
                    scene=scene,
                    red_lens=channel(c),
                    green_lens=channel(c + 1),
                    blue_lens=channel(c + 2),
                    clim_min=min(lows) if lows else None,
                    clim_max=max(highs) if highs else None,
                    order=order,
                )
                c += 3
                continue
            window = histograms.contrast(shown.histograms, c)
            self.client.create_intensity_layer(
                lens=channel(c),
                scene=scene,
                color=_DRAWN.get(colors[c] or ""),
                clim_min=window[0] if window else None,
                clim_max=window[1] if window else None,
                order=order,
            )
            c += 1

    def check(self) -> None:
        """A client is there: it connects with its first call, so a mikro that is down is only
        found out then."""

    def state(self) -> Mapping[str, Any]:
        """What the running microscope is set to now."""
        return self.microscope.values.snapshot()

    @property
    def streams(self) -> bool:
        """Whether records are streamed (`stream`): with newswitch's native module built (the
        extra "native"), else they are written at the end of the acquisition."""
        return importlib.util.find_spec("newswitch_native") is not None

    def stream(
        self,
        shape: tuple[int, ...],
        dtype: str,
        dims: tuple[str, ...],
        colors: int,
        pyramid: bool = False,
    ) -> MikroRecordStream:
        """A record of `shape` written into mikro's datalayer exposure by exposure, natively from
        where each is (`newswitch.infra.mikro.stream`); with its pyramid when `pyramid`, each
        level made by the native writer as the exposure is stored."""
        levels = pyramid_levels(shape[-2], shape[-1], PYRAMID_REDUCTION) if pyramid else 1
        return MikroRecordStream(
            self.client,
            shape,
            dtype,
            dims,
            colors,
            budget=self.budget(),
            levels=levels,
            reduction=PYRAMID_REDUCTION,
        )

    def budget(self) -> Any:  # noqa: ANN401 - a newswitch_native.InFlightBudget
        """The one budget every record streamed waits on, however many positions and cameras
        stream at once: sized to the memory available now (`in_flight_limit`), as each stream is
        opened, so a machine that has less for it lends it less."""
        from newswitch_native import InFlightBudget

        limit = in_flight_limit()
        if self._budget is None:
            self._budget = InFlightBudget(limit)
        elif self._budget.pending_bytes == 0:  # nothing of an earlier acquisition is held
            self._budget.limit = limit
        return self._budget

    def _create_dataset(
        self, acquired: AcquiredRecord, data: Any, anchors: list[Any]  # noqa: ANN401
    ) -> Any:  # noqa: ANN401 - mikro's ArrayDataset
        """The dataset of `acquired`: of `data` uploaded now, or of the store it was streamed
        into (`acquired.stream`), declared against a placeholder of its shape so mikro checks its
        axes and layout as for any array."""
        names, axes, types = dataset_axes(self.instrument, acquired)
        streamed = acquired.stream is not None
        if not streamed:
            levels = 1
            if acquired.pyramid and set(PYRAMID_AXES) <= set(names):
                levels = pyramid_levels(
                    data.shape[names.index("y")], data.shape[names.index("x")], PYRAMID_REDUCTION
                )
            level_zero, scales = dataset_arrays(
                data,
                levels=levels,
                method=PYRAMID_REDUCTION,
                axes=PYRAMID_AXES if levels > 1 else None,
                dims=names,
                types=types,
            )
            self._histograms = histograms.counted(data, names)
            return self.client.create_array_dataset(
                data=level_zero,
                scales=scales,
                name=acquired.name,
                axes=axes,
                anchors=[*anchors, *histograms.anchors(self._histograms)],
            )
        level_zero, _ = dataset_arrays(
            placeholder(acquired.shape, acquired.dtype), levels=1, dims=names, types=types
        )
        stream: MikroRecordStream = acquired.stream  # type: ignore[assignment]
        pyramid = stream.levels
        scales = [
            schema.ScaleInput(
                level=level.level,
                array=dataset_arrays(
                    placeholder(level.shape, acquired.dtype), levels=1, dims=names, types=types
                )[0],
                scale_method=schema.ScaleMethod(_SCALE_METHODS[stream.reduction]),
                scale=level.scale,
                translation=level.translation,
            )
            for level in pyramid
        ]
        store = stream.finish()
        # Counted natively while it was written: complete now that it is stored.
        self._histograms = stream.histograms
        anchors = [*anchors, *histograms.anchors(self._histograms)]
        variables = {
            "input": {
                "data": level_zero,
                "scales": scales,
                "name": acquired.name,
                "axes": axes,
                "anchors": anchors,
            }
        }
        serialized = self.client._serialize(schema.CreateArrayDatasetMutation, variables)
        serialized["input"]["data"] = store  # what the upload middleware would have put there
        for sent, level in zip(serialized["input"].get("scales") or [], pyramid):
            sent["array"] = level.store  # each level's own store, as its data's
        result = self.client.rath.query(
            schema.CreateArrayDatasetMutation.Meta.document,
            serialized,
            headers=self.client._headers(None),
        )
        return schema.CreateArrayDatasetMutation.model_validate(
            result.data, context=self.client._origin()
        ).create_array_dataset

    def publish(self, acquired: AcquiredRecord) -> AcquiredDataset:
        """Write `acquired`: what it took, its anchors, and its place on the sample.

        The sample's space is found again by its reference, so every record of one mounting lands
        in the same one, whatever detector took it.
        """
        dataset = self._create_dataset(
            acquired,
            acquired.data,
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
        self._shown[str(dataset.id)] = _Shown(
            space=str(sample.id),
            colors=tuple(channel.color for channel in acquired.channels),
            histograms=self._histograms,
        )
        return AcquiredDataset(
            id=str(dataset.id),
            name=acquired.name,
            position=acquired.position,
            detector=acquired.detector,
        )
