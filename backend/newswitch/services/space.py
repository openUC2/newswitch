"""Where everything is, on the sample: the coordinate graph of the running microscope.

The one place a pixel is placed. A detector's pixel goes to the stage by how large its pixels are
on the sample (calibrated, or else as the optics predict: `OpticsManager.scale_under`) and where it
looks (`newswitch.services.stage.where`), the middle of its sensor where it looks; and from the stage
to the sample by the mount. An image taken is its detector's placement then, kept under its id, so
that a point in it is a place to go.

    detector:camera -> stage:  BY_DIMENSION
                                 (x, y) -> (x, y): T(where) · A · T(pixel from the sensor's middle)
                                 ()     -> (z):    the plane it looks at
                               its colors or arrival times: no part, nothing said
    detector:thermometer -> stage:  BY_DIMENSION, () -> (x, y, z): where it sits on the stage
    stage -> sample:          AFFINE, the mount
    well:B3 -> sample:        BY_DIMENSION, (x, y) -> (x, y): where the mounted plate has it
    image:<id> -> sample:     AFFINE, its detector's placement when it was taken

A part from fewer axes than it states is walked forwards only: the camera's pixel is on the sample,
but nothing about a sample point says which pixel sees it (`targets` asks the other way round).

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
    SPATIAL,
    STAGE,
    AxisMap,
    CoordinateGraph,
    affine_part,
    by_dimension,
    detector_system,
    holder_to_stage,
    image_system,
    places_of,
    spatial,
    spatial_affine,
    translation,
)
from newswitch.instrument.spec import MountedHolder, Thermometer
from newswitch.models.devices import Detector
from newswitch.models.space import (
    Axis,
    CoordinateSystem,
    DetectorPlacement,
    DimensionPart,
    HolderShape,
    MeasuredPoint,
    Position,
    Transformation,
    WellShape,
)
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


#: What mikro calls an axis that measures each domain.
AXIS_TYPES = {"space": "SPACE", "spectrum": "CHANNEL", "microtime": "MICROTIME", "time": "TIME"}


def _system_of(detector: Detector) -> CoordinateSystem:
    """What `detector` delivers, as a system: an axis of indices for each of its axes; none for one
    that measures at a point."""
    return CoordinateSystem(
        detector_system(detector.name),
        [Axis(axis.name, AXIS_TYPES[axis.domain]) for axis in detector.axes],
    )


def _new_mount_id() -> str:
    """An id for a mounting no other has."""
    return uuid.uuid4().hex[:8]


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
        # Every start is a mounting of its own: what is on the stage now need not be what was
        # before, and the mount lives in memory only.
        self.state.mount_id = _new_mount_id()
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

    def _detector_edge(
        self, detector: Detector, values: Mapping[str, Any] | None = None
    ) -> Transformation:
        """Where `detector` measures, on the stage, under `values` or as things are now: its
        pixels, or the point it reads at."""
        source = detector_system(detector.name)
        if not detector.delivers_images():
            assert self.values is not None
            element = self.values.instrument.cubes[detector.name].element
            assert isinstance(element, Thermometer), f"{detector.name} measures nowhere known"
            at = element.on_stage
            point = [[at.x * 1000.0], [at.y * 1000.0], [at.z * 1000.0]]
            return by_dimension(source, STAGE, [affine_part((), SPATIAL, point)], "on stage")
        matrix = self.to_stage(detector.name, values)
        if detector.has_axis("z"):  # it steps its planes itself: each is its step further
            matrix[2, 2] = detector.axis("z").step or 1.0
            parts = [spatial_affine(matrix)]
        else:
            parts = [
                spatial_affine(matrix, ("x", "y"), ("x", "y")),
                spatial_affine(matrix, (), ("z",)),
            ]
        return by_dimension(source, STAGE, parts, "pixels")

    def _live(
        self, values: Mapping[str, Any] | None = None
    ) -> tuple[list[CoordinateSystem], list[Transformation]]:
        """The systems and edges that hold under `values` (now, by default), but for the images
        taken."""
        systems = [spatial(SAMPLE), spatial(STAGE)]
        edges = [Transformation(STAGE, SAMPLE, "AFFINE", "mount", affine=self.mount()[:3].tolist())]
        if self.values is not None:
            for detector in self.detector_state.detectors:
                systems.append(_system_of(detector))
                edges.append(self._detector_edge(detector, values))
        if self.state.holder is not None:
            for place, (x, y) in places_of(self._holders[self.state.holder].holder).items():
                systems.append(spatial(place, ("x", "y")))
                edges.append(
                    by_dimension(
                        place,
                        SAMPLE,
                        [DimensionPart("TRANSLATION", ["x", "y"], ["x", "y"], translation=[x, y])],
                        "place",
                    )
                )
        return systems, edges

    def graph(self, values: Mapping[str, Any] | None = None) -> CoordinateGraph:
        """The coordinate graph as it holds under `values`: now, by default."""
        systems, edges = self._live(values)
        for image, matrix in self._images.items():
            systems.append(spatial(image_system(image), unit=""))
            edges.append(
                Transformation(
                    image_system(image), SAMPLE, "AFFINE", "image", affine=matrix[:3].tolist()
                )
            )
        return CoordinateGraph(systems, edges)

    def transform(
        self, position: Position, target: str = SAMPLE, axes: tuple[str, ...] | None = None
    ) -> dict[str, float]:
        """Where `position` is in `target`, by axis name: along `axes`, or all the route states.

        Raises:
            NoRoute: Its system is none the graph knows, or not one that leads to `target`.
            ValueError: An axis asked for depends on one the position does not give.
        """
        return self.graph().transform(position, target, axes)

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
        has_z = "z" in position.coordinates
        on_stage = self.transform(position, STAGE, ("x", "y", "z") if has_z else ("x", "y"))
        # How far the middle of the image is from where the sensor's middle looks: a window that is
        # not in the middle of its sensor looks beside it.
        aside = (self.to_stage(detector) @ self._image_middle(detector))[:2] - np.array(
            self._looks_at(detector, at)[:2]
        )
        x_move, y_move = roles.x(detector), roles.y(detector)
        found = {
            x_move.name: float(at[x_move.name])
            + on_stage["x"]
            - float(aside[0])
            - sum(float(at[m.name]) for m in roles.sideways(detector, "x")),
            y_move.name: float(at[y_move.name])
            + on_stage["y"]
            - float(aside[1])
            - sum(float(at[m.name]) for m in roles.sideways(detector, "y")),
        }
        if has_z:
            focus = roles.focus(detector)
            if focus in self.values.instrument.sheet_moves():
                raise ValueError(f"{focus.name} moves a light sheet: a z is not reached by it yet")
            plane = roles.plane_um(detector, at)
            found[focus.name] = float(at[focus.name]) + on_stage["z"] - plane
        return found

    # ------------------------------------------------------------- the mount

    def mount_holder(self, holder: str) -> None:
        """Mount `holder`: a new sample, where the description says it sits, with no images taken.

        Raises:
            ValueError: The description names no such holder.
        """
        if holder not in self._holders:
            raise ValueError(f"No holder {holder!r} to mount: there are {sorted(self._holders)}")
        self._mount(holder, _new_mount_id())
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

    def record_map(
        self,
        detector: str,
        dims: tuple[str, ...],
        offsets: list[float],
        light_sweep: bool = False,
        values: Mapping[str, Any] | None = None,
    ) -> AxisMap:
        """Where an acquired record's axes go on the sample, under `values` (as things are now, by
        default; a record's, what its channel sets): `detector`'s route to the sample (`graph`),
        over the record's `dims`.

        A detector that takes images has its plane index placed by the stack: the plane it looks
        at now, then `offsets` (moving the light is moving the sample the other way). What
        measures at a point is where it is at every plane: its plane index is placed nowhere. Time,
        channels and arrival times are placed nowhere either.
        """
        route = self.graph(values).axis_map(detector_system(detector), SAMPLE)
        images = self.detector_state.get(detector).delivers_images()
        rows: dict[str, np.ndarray] = {}
        for axis in SPATIAL:
            if axis not in route.output_axes:
                continue
            form = route.matrix[route.output_axes.index(axis)]
            row = np.zeros(len(dims) + 1)
            row[-1] = form[-1]
            for name, factor in zip(route.input_axes, form[:-1]):
                if factor != 0.0 and name in dims and not (images and name == "z"):
                    row[dims.index(name)] = factor
            rows[axis] = row
        if images and "z" in rows:
            direction = -1.0 if light_sweep else 1.0
            step = offsets[1] - offsets[0] if len(offsets) > 1 else 1.0
            rows["z"][dims.index("z")] = direction * step
            rows["z"][-1] += direction * offsets[0]
        stated = tuple(axis for axis in ("z", "y", "x") if axis in rows)
        bottom = np.zeros(len(dims) + 1)
        bottom[-1] = 1.0
        return AxisMap(dims, stated, np.vstack([*(rows[axis] for axis in stated), bottom]))

    def _measured(self, detector: str) -> MeasuredPoint:
        at = self.transform(Position(detector_system(detector)), SAMPLE, SPATIAL)
        return MeasuredPoint(detector, at["x"], at["y"], at["z"])

    def refresh(self) -> None:
        """Publish the graph as it holds now, where every detector's pixels are and where every
        detector that measures at a point measures, if that changed."""
        if self.values is None:
            return
        with self._refreshing:
            detectors = self.detector_state.detectors
            placed = {d.name: self._placed(d.name) for d in detectors if d.delivers_images()}
            points = {d.name: self._measured(d.name) for d in detectors if not d.delivers_images()}
            systems, edges = self._live()
            text = json.dumps(
                [
                    {name: asdict(found) for name, found in placed.items()},
                    {name: asdict(found) for name, found in points.items()},
                    [asdict(system) for system in systems],
                    [asdict(edge) for edge in edges],
                ],
                sort_keys=True,
            )
            if text != self._published:
                self._published = text
                self.state.systems = systems
                self.state.transformations = edges
                self.state.points = points
                self.state.detectors = placed
