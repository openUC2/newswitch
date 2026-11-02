"""Where everything is, on the sample: the coordinate graph of the running microscope.

The one place a pixel is placed. A detector's pixel goes to the stage by how large its pixels are
on the sample (calibrated, or else as the optics predict: `OpticsManager.scale_under`) and where it
looks (`newswitch.services.stage.where`), the middle of its sensor where it looks; and from the stage
to the sample by the mount. An image taken is its detector's placement then, kept under its id, so
that a point in it is a place to go.

    pixel -> stage:   T(where) · A · T(offset of the pixel from the middle of the sensor)
    stage -> sample:  the mount
    well:B3 -> sample: where the mounted plate has it

What is mounted is one of the holders the description names for its sample (`mount_holder`); a new
mounting is a new sample, with the mount the description gives it and none of the images taken.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

import numpy as np

from newswitch.instrument.space import (
    SAMPLE,
    STAGE,
    CoordinateGraph,
    Edge,
    detector_system,
    holder_to_stage,
    image_system,
    places_of,
    translation,
)
from newswitch.instrument.spec import MountedHolder
from newswitch.models.devices import Detector
from newswitch.models.space import DetectorPlacement, HolderShape, Position, WellShape
from newswitch.services.optics import OpticsManager
from newswitch.services.values import Values
from newswitch.states.detector import DetectorState
from newswitch.states.space import SpaceState


def _middle_offset(detector: Detector, name: str, values: Mapping[str, Any]) -> float:
    """Where pixel 0 along `name` is, from the middle of the whole axis, in pixels as delivered.

    The pixel delivered at index i covers the unbinned steps from start + i·b on, b of them.
    """
    axis = detector.axis(name)
    binning = int(values.get(f"{detector.name}.binning", axis.binning)) if axis.binnable else 1
    size = axis.size or 1
    return (axis.window_start + (binning - 1) / 2 - (size - 1) / 2) / binning


def _shape_of(name: str, mounted: MountedHolder) -> HolderShape:
    """What is mounted as a view draws it, in sample micrometres."""
    holder = mounted.holder
    plate = holder.plate
    return HolderShape(
        name=name,
        kind=holder.kind,
        width_um=holder.extent.x * 1000.0,
        height_um=holder.extent.y * 1000.0,
        wells=[]
        if plate is None
        else [
            WellShape(
                name=f"well:{well}",
                x=x * 1000.0,
                y=y * 1000.0,
                diameter_um=None if plate.well.diameter is None else plate.well.diameter * 1000.0,
                size_um=None if plate.well.size is None else plate.well.size * 1000.0,
            )
            for well, (x, y) in plate.wells().items()
        ],
    )


class SpaceManager:
    """Builds the coordinate graph from what the microscope is now, and publishes its placements."""

    def __init__(
        self,
        state: SpaceState,
        values: Values | None,
        optics: OpticsManager,
        detector_state: DetectorState,
    ) -> None:
        """A space of `values`, placed by `optics`, with the windows of `detector_state`."""
        self.state = state
        self.values = values
        self.optics = optics
        self.detector_state = detector_state
        self._images: dict[str, np.ndarray] = {}
        self._published = ""
        self._refreshing = threading.Lock()
        holder = None if values is None else values.instrument.sample_holder()
        self._holders: dict[str, MountedHolder] = {} if holder is None else dict(holder.holders)
        self.state.holders = list(self._holders)
        if holder is not None and holder.mounted is not None:
            self._mount(holder.mounted, self.state.mount_id)

    # ------------------------------------------------------------- the edges

    def mount(self) -> np.ndarray:
        """Stage micrometres to sample micrometres."""
        return np.array(self.state.mount, dtype=float)

    def to_stage(self, detector: str, values: Mapping[str, Any] | None = None) -> np.ndarray:
        """Where `detector`'s pixels (column, row, plane) are in stage micrometres, under `values`
        or as things are now."""
        assert self.values is not None
        at = self.values.snapshot() if values is None else values
        scale, _ = self.optics.scale_under(detector, at)
        linear = np.array(scale.affine_matrix, dtype=float)[:2, :2]
        found = self.detector_state.get(detector)
        offset = np.array([_middle_offset(found, "x", at), _middle_offset(found, "y", at)])
        x, y, plane = self._looks_at(detector, at)
        matrix = np.eye(4)
        matrix[:2, :2] = linear
        matrix[:2, 3] = np.array([x, y]) + linear @ offset
        matrix[2, 3] = plane
        return matrix

    def _looks_at(self, detector: str, at: Mapping[str, Any]) -> tuple[float, float, float]:
        """Where the middle of `detector`'s sensor looks, in stage micrometres, under `at`."""
        assert self.values is not None
        roles = self.values.roles
        return (
            sum(float(at[move.name]) for move in roles.sideways(detector, "x")),
            sum(float(at[move.name]) for move in roles.sideways(detector, "y")),
            roles.plane_um(detector, at),
        )

    def _image_middle(self, detector: str) -> np.ndarray:
        """The middle of `detector`'s image as it is read out now: column, row, plane, 1."""
        height, width = self.detector_state.get(detector).plane()
        return np.array([(width - 1) / 2.0, (height - 1) / 2.0, 0.0, 1.0])

    def placement(self, detector: str, values: Mapping[str, Any] | None = None) -> np.ndarray:
        """Where `detector`'s pixels (column, row, plane) are on the sample."""
        return self.mount() @ self.to_stage(detector, values)

    def remember(self, image: str, to_sample: np.ndarray | list[list[float]]) -> None:
        """Keep where the pixels of an image taken are, so a point in it is a place to go."""
        self._images[image] = np.array(to_sample, dtype=float)

    def forget_images(self) -> None:
        """The images belong to what was mounted: a new mounting starts without them."""
        self._images.clear()

    def graph(self) -> CoordinateGraph:
        """The coordinate graph as it holds now."""
        edges = [Edge(STAGE, SAMPLE, self.mount(), "mount")]
        if self.values is not None:
            edges += [
                Edge(detector_system(detector.name), STAGE, self.to_stage(detector.name), "pixels")
                for detector in self.detector_state.detectors
            ]
        edges += [
            Edge(image_system(image), SAMPLE, matrix, "image")
            for image, matrix in self._images.items()
        ]
        if self.state.holder is not None:
            edges += [
                Edge(place, SAMPLE, translation(x, y), "holder")
                for place, (x, y) in places_of(self._holders[self.state.holder].holder).items()
            ]
        return CoordinateGraph(edges)

    def transform(self, position: Position, target: str = SAMPLE) -> np.ndarray:
        """Where `position` is in `target`, as (x, y, z); a position without z is at its z 0.

        Raises:
            NoRoute: Its system is none the graph knows.
        """
        point = (position.x, position.y, 0.0 if position.z is None else position.z)
        return self.graph().transform(point, position.system, target)

    # ------------------------------------------------------------- going there

    def targets(self, position: Position, detector: str) -> dict[str, float]:
        """What to set so that the middle of `detector`'s image, as read out, is at `position`.

        Sideways, the one move along each way (`Roles.x`, `Roles.y`). Along the axis only when the
        position has a z, by what focuses it; a z that only a light sheet's move reaches is refused,
        not guessed.

        Raises:
            ValueError: Nothing, or several things, move it along a way it has to go.
            NoRoute: The position's system is none the graph knows.
        """
        assert self.values is not None
        roles = self.values.roles
        at = self.values.snapshot()
        on_stage = self.transform(position, STAGE)
        # How far the middle of the image is from where the sensor's middle looks: a window that is
        # not in the middle of its sensor looks beside it.
        aside = (self.to_stage(detector) @ self._image_middle(detector))[:2] - np.array(
            self._looks_at(detector, at)[:2]
        )
        x_move, y_move = roles.x(detector), roles.y(detector)
        found = {
            x_move.name: float(at[x_move.name])
            + float(on_stage[0] - aside[0])
            - sum(float(at[m.name]) for m in roles.sideways(detector, "x")),
            y_move.name: float(at[y_move.name])
            + float(on_stage[1] - aside[1])
            - sum(float(at[m.name]) for m in roles.sideways(detector, "y")),
        }
        if position.z is not None:
            focus = roles.focus(detector)
            if focus in self.values.instrument.sheet_moves():
                raise ValueError(f"{focus.name} moves a light sheet: a z is not reached by it yet")
            plane = roles.plane_um(detector, at)
            found[focus.name] = float(at[focus.name]) + float(on_stage[2]) - plane
        return found

    # ------------------------------------------------------------- the mount

    def mount_holder(self, holder: str) -> None:
        """Mount `holder`: a new sample, where the description says it sits, with no images taken.

        Raises:
            ValueError: The description names no such holder.
        """
        if holder not in self._holders:
            raise ValueError(f"No holder {holder!r} to mount: there are {sorted(self._holders)}")
        self._mount(holder, uuid.uuid4().hex[:8])
        self.forget_images()
        self.refresh()

    def _mount(self, holder: str, mount_id: str) -> None:
        mounted = self._holders[holder]
        self.state.mount = np.linalg.inv(holder_to_stage(mounted.mount)).tolist()
        self.state.mount_id = mount_id
        self.state.holder = holder
        self.state.shape = _shape_of(holder, mounted)

    def register_mount(self, matrix: list[list[float]]) -> None:
        """Say where what is mounted sits: stage micrometres to sample micrometres."""
        found = np.array(matrix, dtype=float)
        if found.shape != (4, 4) or abs(np.linalg.det(found)) < 1e-12:
            raise ValueError("a mount is an invertible 4x4 matrix")
        self.state.mount = found.tolist()
        self.refresh()

    def origin_here(self, detector: str) -> None:
        """Make the sample's x and y 0 at the middle of `detector`'s image now."""
        assert self.values is not None
        middle = self.placement(detector) @ self._image_middle(detector)
        self.register_mount((translation(-middle[0], -middle[1]) @ self.mount()).tolist())

    # ------------------------------------------------------------- publishing

    def _placed(self, detector: str) -> DetectorPlacement:
        assert self.values is not None
        _, calibrated = self.optics.scale_under(detector, self.values.snapshot())
        matrix = self.placement(detector)
        return DetectorPlacement(
            detector=detector,
            to_sample=matrix.tolist(),
            pixel_um=[float(np.hypot(*matrix[:2, 0])), float(np.hypot(*matrix[:2, 1]))],
            calibrated=calibrated,
        )

    def refresh(self) -> None:
        """Publish where every detector's pixels are now, if that changed."""
        if self.values is None:
            return
        with self._refreshing:
            placed = {
                detector.name: self._placed(detector.name)
                for detector in self.detector_state.detectors
            }
            text = json.dumps(
                {name: asdict(found) for name, found in placed.items()}, sort_keys=True
            )
            if text != self._published:
                self._published = text
                self.state.detectors = placed
