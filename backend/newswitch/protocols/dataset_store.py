"""Where an acquisition ends up: a store of datasets, not the local cache.

An acquisition makes one record per position and detector: along the detector's own axes, placed
on the sample by its own route through the coordinate graph.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable

import numpy as np

from newswitch.models.acquisition import AcquiredDataset
from newswitch.models.space import Axis, DimensionPart


@dataclass(frozen=True)
class AcquiredChannel:
    """One index of a record's ``c`` axis: what its detector saw of one channel, in one color."""

    label: str
    detector: str
    sources: tuple[str, ...]
    color: str | None = None
    light: bool = True
    """Whether light reached it: a thermometer's channel has no light path."""


@dataclass(frozen=True)
class AcquiredPlane:
    """One exposure of a record: where it sits on ``t``, ``c`` and ``z``, and what was true then."""

    t: int
    c: int
    z: int
    started: datetime
    ended: datetime
    state: Mapping[str, Any]
    """Every variable of the instrument, in its description's names."""


@dataclass(frozen=True)
class AcquiredRecord:
    """What one detector acquired at one position, along its own axes."""

    name: str
    position: int
    detector: str
    data: np.ndarray
    """Along `axes`, as the detector delivered it: a mirrored camera's images are not turned, its
    `registration` says so."""
    axes: tuple[Axis, ...]
    """``t``, ``c``, the detector's own axes but space (``m``), the plane ``z``, its space (``y``,
    ``x``): ``(t, c, z, y, x)`` of a camera, ``(t, c, m, z, y, x)`` timing photons; a thermometer's
    ``(t, c, plane, z, y, x)``, the plane it was read at an INDEX, and one position along each of
    ``z, y, x``, its point."""
    channels: tuple[AcquiredChannel, ...]
    planes: tuple[AcquiredPlane, ...]
    registration: tuple[DimensionPart, ...]
    """Its axes onto the sample's ``t, z, y, x``, in seconds and micrometres, part by part (a
    BY_DIMENSION): an axis no part names is placed nowhere."""
    calibrated: bool
    quantity: str = "intensity"
    """What its values are: intensity, temperature."""
    unit: str = ""
    """What its values are in: empty for counts."""
    sample: str = ""
    """The sample it was taken of, by the cube holding it."""
    mount_id: str = "0"
    """Which mounting of its sample it was taken on: what its sample micrometres are of."""
    mounted_at: str = ""
    """When that mounting was, as ISO 8601: where its sample's clock starts, on which its ``t``
    is."""
    mount: tuple[tuple[float, float, float, float], ...] = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    """``z, y, x`` stage micrometres to sample micrometres, for that mounting."""

    @property
    def dims(self) -> tuple[str, ...]:
        """The names of its axes, in order."""
        return tuple(axis.name for axis in self.axes)

    @property
    def stack(self) -> str:
        """Along which axis its planes (`AcquiredPlane.z`) are: ``plane`` where they are only where
        it was read, ``z`` where they are where it looked."""
        return "plane" if "plane" in self.dims else "z"


@runtime_checkable
class DatasetStore(Protocol):
    """Takes what an acquisition merged. Provided by the entry file, like a `FrameSink`."""

    def check(self) -> None:
        """Raise if nothing could be stored: asked before the stage moves or a light comes on."""
        ...

    def state(self) -> Mapping[str, Any]:
        """What the running microscope is set to now, in its description's names."""
        ...

    def publish(self, acquired: AcquiredRecord) -> AcquiredDataset:
        """Store one record, with its anchors and its place on the sample."""
        ...
