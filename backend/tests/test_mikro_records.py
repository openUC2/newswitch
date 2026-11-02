"""What a record becomes in mikro, without a mikro: its axes by type, its parts, its anchors."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from mikro import dataset_arrays
from mikro.api import schema

from newswitch.infra.mikro.store import anchors_of_channels, dataset_axes, mikro_parts
from newswitch.instrument import spec
from newswitch.models.acquisition import AcquisitionChannel
from newswitch.protocols.dataset_store import AcquiredRecord
from tests.conftest import acquisition
from tests.test_acquire import StateStore
from tests.test_thermometer import he, run


@pytest.fixture
def records(tmp_path: Path) -> tuple[spec.Instrument, AcquiredRecord, AcquiredRecord]:
    """The he-microscope's camera and thermometer, acquired together."""
    m = he(tmp_path)
    assert m.values is not None
    channel = AcquisitionChannel(name="air", detectors=["camera", "thermometer"])
    camera, thermometer = run(m, acquisition([channel], planes=[0.0, 1.0]), StateStore(m)).published
    return m.values.instrument, camera, thermometer


def test_every_axis_is_declared_as_what_it_is(
    records: tuple[spec.Instrument, AcquiredRecord, AcquiredRecord],
) -> None:
    """A camera's are time, channels and space; a thermometer's plane is an index, placed nowhere."""
    instrument, camera, thermometer = records
    names, axes, types = dataset_axes(instrument, camera)
    assert names == ("t", "c", "z", "y", "x")
    assert [axis.type for axis in axes] == [
        schema.AxisType.TIME,
        schema.AxisType.CHANNEL,
        *[schema.AxisType.SPACE] * 3,
    ]
    names, axes, types = dataset_axes(instrument, thermometer)
    assert names == ("t", "c", "z") and types == {"t": "TIME", "c": "CHANNEL", "z": "INDEX"}
    assert "not placed" in (axes[2].description or "")


def test_a_reading_makes_a_pyramid_of_its_own(
    records: tuple[spec.Instrument, AcquiredRecord, AcquiredRecord],
) -> None:
    """With no space to coarsen, its level 0 is all of it."""
    instrument, _, thermometer = records
    names, _, types = dataset_axes(instrument, thermometer)
    level_zero, scales = dataset_arrays(
        xr.DataArray(thermometer.data, dims=names), levels=1, method="mean", types=types
    )
    assert level_zero.shape == (1, 1, 2) and scales == []


def test_its_registration_goes_to_mikro_part_for_part(
    records: tuple[spec.Instrument, AcquiredRecord, AcquiredRecord],
) -> None:
    """A camera's pixels and planes onto the sample; a thermometer's point, from no axes at all."""
    _, camera, thermometer = records
    (pixels,) = mikro_parts(camera.registration)
    assert pixels.kind == schema.PartKind.AFFINE
    assert (pixels.input_axes, pixels.output_axes) == (("z", "y", "x"), ("z", "y", "x"))
    assert np.array(pixels.affine) == pytest.approx(np.array(camera.registration[0].affine))
    (point,) = mikro_parts(thermometer.registration)
    assert (point.input_axes, point.output_axes) == ((), ("z", "y", "x"))
    assert np.ravel(point.affine) == pytest.approx([0.0, 0.0, 30_000.0])


def test_only_light_has_a_light_path(
    records: tuple[spec.Instrument, AcquiredRecord, AcquiredRecord],
) -> None:
    """A camera channel says how the light came; a thermometer's says what it is, no more."""
    instrument, camera, thermometer = records
    assert all(a.light_graph is not None for a in anchors_of_channels(instrument, camera))
    (anchor,) = anchors_of_channels(instrument, thermometer)
    assert anchor.light_graph is None
    assert anchor.label is not None and anchor.label.label == "air thermometer (degC)"
