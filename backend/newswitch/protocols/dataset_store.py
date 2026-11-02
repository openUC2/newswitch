"""Where an acquisition ends up: a store of datasets, not the local cache."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable

import numpy as np

from newswitch.models.acquisition import AcquiredDataset


@dataclass(frozen=True)
class AcquiredChannel:
    """One index of a dataset's ``c`` axis: what one detector saw of one stream, in one color."""

    label: str
    detector: str
    sources: tuple[str, ...]
    color: str | None = None


@dataclass(frozen=True)
class AcquiredPlane:
    """One image of a dataset: where it sits on ``t``, ``c`` and ``z``, and what was true then."""

    t: int
    c: int
    z: int
    started: datetime
    ended: datetime
    state: Mapping[str, Any]
    """Every variable of the instrument, in its description's names."""


@dataclass(frozen=True)
class AcquiredPosition:
    """Everything acquired at one stage position, merged."""

    name: str
    position: int
    data: np.ndarray
    """Along `dims`. A mirrored or inverted detector's images are flipped already, so that every
    channel shows the sample the same way round and `to_sample` is one map for all of them."""
    dims: tuple[str, ...]
    """The axes of `data`: ``(t, c, z, y, x)``, or ``(t, c, m, z, y, x)`` from a detector timing its
    photons."""
    channels: tuple[AcquiredChannel, ...]
    planes: tuple[AcquiredPlane, ...]
    to_sample: tuple[tuple[float, float, float, float], ...]
    """``z, y, x`` index to sample micrometres: three rows of a homogeneous matrix."""
    calibrated: bool
    """Whether its pixel scale was measured, rather than predicted from the optics."""
    mount_id: str = "0"
    """Which mounting of a sample it was taken on: what its sample micrometres are of."""
    mount: tuple[tuple[float, float, float, float], ...] = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    """``z, y, x`` stage micrometres to sample micrometres, for that mounting."""


@runtime_checkable
class DatasetStore(Protocol):
    """Takes what an acquisition merged. Provided by the entry file, like a `FrameSink`."""

    def check(self) -> None:
        """Raise if nothing could be stored: asked before the stage moves or a light comes on."""
        ...

    def state(self) -> Mapping[str, Any]:
        """What the running microscope is set to now, in its description's names."""
        ...

    def publish(self, acquired: AcquiredPosition) -> AcquiredDataset:
        """Store one position's dataset, with its anchors and its place in stage space."""
        ...
