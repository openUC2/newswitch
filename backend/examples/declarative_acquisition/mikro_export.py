"""What an image's record becomes in mikro: one registration edge and one coordinate anchor.

On the instrument the light path is the hub: it decides and it computes. In the data the hub is
mikro's `CoordinateAnchor`, so a `Record` splits into its spokes when it is written out:

=================== ==========================================
`lightGraph`        the light path: its cubes and their edges
`microscope`        the stage position and every device's values
`acquisitionWindow` when it was taken
registration edge   pixels to stage, named by the calibration it used
=================== ==========================================
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import numpy as np
import xarray as xr
from mikro import canonical, dataset_arrays, space_3d
from mikro.api import schema
from mikro.api.schema import (
    AcquisitionWindowInput,
    AxisAnchorInput,
    CoordinateAnchorInput,
    DeviceStateInput,
    LightEdgeInput,
    LightpathGraphInput,
    OptikitStateInput,
    PlacementValidity,
    SettingInput,
    StageStateInput,
)
from mikro.inputs.lightpath import in_out

if TYPE_CHECKING:
    from mikro import Mikro
    from mikro.api.schema import ArrayDataset

    from examples.declarative_acquisition.instrument import Instrument, Record


#: A cube's kind, in mikro's `ElementKind`, to the input class of that kind of element.
_ELEMENTS: dict[str, Any] = {
    "LASER": schema.LaserElementInput,
    "BEAM_SPLITTER": schema.BeamSplitterElementInput,
    "OBJECTIVE": schema.ObjectiveElementInput,
    "SAMPLE": schema.SampleElementInput,
    "FILTER": schema.FilterElementInput,
    "CCD": schema.CCDElementInput,
}


def _element(instrument: Instrument, name: str, record: Record) -> Any:  # noqa: ANN401
    """A cube as an optical element, with what its kind has a field for."""
    cube = instrument.cubes[name]
    fields: dict[str, Any] = {}
    if cube.kind == "LASER" and "wavelength_nm" in cube.properties:
        fields["nominal_wavelength"] = f"{cube.properties['wavelength_nm']} nm"
    if cube.kind == "CCD" and "pixel_um" in cube.properties:
        fields["pixel_size"] = f"{cube.properties['pixel_um']} um"
    for variable in cube.variables.values():
        selected = variable.values.get(record.values[variable.name], {})
        if cube.kind == "OBJECTIVE" and "magnification" in selected:
            fields["magnification"] = float(selected["magnification"])
            fields["numerical_aperture"] = float(selected["na"])
    return _ELEMENTS[cube.kind](id=name, label=name, ports=in_out(), **fields)


def light_graph(instrument: Instrument, record: Record) -> LightpathGraphInput:
    """The light path of `record`: every cube once, and an edge per hop of each arm."""
    path = instrument.paths[record.path]
    edges = [
        LightEdgeInput(
            id=f"{arm}-{index}",
            source_element_id=source,
            source_port_id="out",
            target_element_id=target,
            target_port_id="in",
        )
        for arm, cubes in (("illumination", path.illumination), ("detection", path.detection))
        for index, (source, target) in enumerate(zip(cubes, cubes[1:]))
    ]
    elements = [_element(instrument, name, record) for name in path.cubes]
    return LightpathGraphInput(elements=elements, edges=edges)


def _setting(name: str, value: Any) -> SettingInput:  # noqa: ANN401 - a device's value
    if isinstance(value, bool):
        return SettingInput(name=name, flag=value)
    if isinstance(value, (int, float)):
        return SettingInput(name=name, number=float(value))
    return SettingInput(name=name, text=str(value))


def microscope_state(instrument: Instrument, record: Record) -> OptikitStateInput:
    """What every device on the path was set to; the stage as lengths, the rest as settings."""
    path = instrument.paths[record.path]
    devices = []
    for name in path.cubes:
        cube = instrument.cubes[name]
        settings = [
            _setting(short, record.values[variable.name])
            for short, variable in cube.variables.items()
            if variable.axis is None
        ]
        if settings:
            devices.append(DeviceStateInput(label=name, kind=cube.kind.lower(), settings=settings))
    stage = StageStateInput(**{axis: f"{value} um" for axis, value in record.stage.items()})
    return OptikitStateInput(stage=stage, devices=devices)


def anchor(instrument: Instrument, record: Record) -> CoordinateAnchorInput:
    """The anchor of `record`: its light path, its state and its time, pinned to channel 0."""
    acquired = datetime.fromtimestamp(record.acquired_at, tz=timezone.utc)
    return CoordinateAnchorInput(
        axis_anchors=[AxisAnchorInput(axis="c", value=0)],
        light_graph=light_graph(instrument, record),
        microscope=microscope_state(instrument, record),
        acquisition_window=AcquisitionWindowInput(start=acquired),
    )


def registration(record: Record) -> dict[str, Any]:
    """The arguments of `space.register` for `record`: scale and offset, by axis name.

    `register` takes a scale and an offset, so a rotated calibration is refused rather than
    written out without its rotation: it would need an AFFINE edge, which this example leaves out.
    """
    matrix = record.matrix
    if not np.allclose(matrix[:3, :3], np.diag(np.diag(matrix[:3, :3]))):
        raise ValueError(f"{record.image} is rotated: register() cannot say that")
    return {
        "scale": {"z": 1.0, "y": float(matrix[1, 1]), "x": float(matrix[0, 0])},
        "z": float(matrix[2, 3]),
        "y": float(matrix[1, 3]),
        "x": float(matrix[0, 3]),
        "name": record.edge_name,
        "validity": PlacementValidity[record.validity.name],
    }


def publish(mikro: Mikro, instrument: Instrument, record: Record) -> ArrayDataset:
    """Write `record` to `mikro`: the frame, its anchor, and its place in the stage's space.

    The space is found again by its reference, so every image of this microscope lands in the same
    one; the reference names the microscope, as two of them have two different stages.
    """
    image = canonical(xr.DataArray(record.frame[None, None], dims=("c", "z", "y", "x")))
    level_zero, scales = dataset_arrays(image, levels=1, method="mean")
    dataset = mikro.create_array_dataset(
        data=level_zero,
        scales=scales,
        name=f"{record.channel} {record.image}",
        axes=[str(dim) for dim in image.dims],
        anchors=[anchor(instrument, record)],
    )
    world = space_3d(mikro, "stage", reference=f"stage-{instrument.name}")
    world.register(dataset, **registration(record))
    return dataset
