"""Where everything is, on its sample: the coordinate graph of the running microscope.

The one place a pixel is placed. A detector's pixel goes to its sample's stage by how large its
pixels are on the sample (calibrated, or else as the optics predict: `OpticsManager.scale_under`)
and where it looks (`newswitch.services.stage.where`), the middle of its sensor where it looks; and
from the stage to the sample by the mount. An image taken is its detector's placement then, kept
under its id, so that a point in it is a place to go.

Each sample is a hub of its own (`Instrument.samples`), on a stage of its own:

    detector:cam_a -> stage:stage_a:  BY_DIMENSION
                                 (x, y) -> (x, y): T(where) · A · T(pixel from the sensor's middle)
                                 ()     -> (z):    the plane it looks at
                               its colors or arrival times: no part, nothing said
    detector:thermometer -> stage:stage_b:  BY_DIMENSION, () -> (x, y, z): where a probe sits
    stage:stage_a -> sample:stage_a:        AFFINE, that sample's mount
    well:stage_a:B3 -> sample:stage_a:      BY_DIMENSION, (x, y) -> (x, y): where its plate has it
    image:<id> -> sample:<its sample>:      AFFINE, its detector's placement when it was taken

A part from fewer axes than it states is walked forwards only: the camera's pixel is on the sample,
but nothing about a sample point says which pixel sees it (`targets` asks the other way round).

What a sample is mounted on is one of the holders the description names for it (`mount_holder`); a
new mounting is a new sample, with the mount the description gives it and none of its images.

The bare names ``sample``, ``stage`` and ``well:B3`` are short for those of one sample: the only one,
or the one a detector sees (`resolve`). With several samples and nothing to say which, a bare name
is refused, never guessed.
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
    NOT_PLACES,
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
    place_system,
    places_of,
    sample_system,
    spatial,
    spatial_affine,
    stage_system,
    translation,
)
from newswitch.instrument.spec import Grid, Instrument, MountedHolder, Probe
from newswitch.models.devices import Detector
from newswitch.models.space import (
    Axis,
    CoordinateSystem,
    DetectorPlacement,
    DimensionPart,
    HolderShape,
    MeasuredPoint,
    Position,
    SampleSpace,
    Transformation,
    PlaceShape,
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


def _shape_of(sample: str, name: str, mounted: MountedHolder) -> HolderShape:
    """What `sample` is mounted on as a view draws it, in its sample's micrometres."""
    holder = mounted.holder
    return HolderShape(
        name=name,
        kind=holder.kind,
        width_um=holder.extent.x * 1000.0,
        height_um=holder.extent.y * 1000.0,
        places=[
            PlaceShape(
                grid=grid,
                name=place_system(grid, sample, place),
                x=x * 1000.0,
                y=y * 1000.0,
                diameter_um=None
                if places.place.diameter is None
                else places.place.diameter * 1000.0,
                size_um=None if places.place.size is None else places.place.size * 1000.0,
            )
            for grid, places in holder.grids.items()
            for place, (x, y) in places.places().items()
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
        self._images: dict[str, tuple[str, np.ndarray]] = {}
        self._published = ""
        self._refreshing = threading.Lock()
        self._holders: dict[str, dict[str, MountedHolder]] = {}
        samples: dict[str, SampleSpace] = {}
        for sample in [] if self.instrument is None else self.instrument.samples():
            holder = self.instrument.sample_holder(sample)
            self._holders[sample] = dict(holder.holders)
            # Every start is a mounting of its own: what is on a stage now need not be what was
            # before, and the mount lives in memory only.
            samples[sample] = SampleSpace(
                sample=sample, mount_id=_new_mount_id(), holders=list(holder.holders)
            )
            if holder.mounted is not None:
                self._mount(samples[sample], holder.mounted)
        self.state.samples = samples

    @property
    def instrument(self) -> Instrument | None:
        """What is placed, if anything is."""
        return None if self.values is None else self.values.instrument

    # ------------------------------------------------------------- which sample

    def samples(self) -> list[str]:
        """The samples, by the cubes holding them."""
        return [] if self.instrument is None else self.instrument.samples()

    def _now(self, under: Mapping[str, Any] | None) -> Mapping[str, Any]:
        assert self.values is not None
        return self.values.snapshot() if under is None else under

    def sample_of(self, detector: str, under: Mapping[str, Any] | None = None) -> str:
        """The sample `detector` sees under `under` (now, by default), or sits beside.

        Raises:
            Dark: The switches send no light to it.
        """
        assert self.instrument is not None
        return self.instrument.seen_sample(detector, self._now(under))

    def sees(self, detector: str, under: Mapping[str, Any] | None = None) -> bool:
        """Whether `detector` measures anything under `under` (now, by default): light gets to it;
        a probe that reads a grid, the grid is on what its sample is mounted on."""
        assert self.instrument is not None
        element = self.instrument.cubes[detector].element
        if isinstance(element, Probe) and element.reads is not None:
            (sample,) = self.instrument.samples_of(detector)
            return self._grid_of(detector, sample) is not None
        return self.instrument.sample_of(detector, self._now(under)) is not None

    def _grid_of(self, probe: str, sample: str) -> Grid | None:
        """The grid `probe` reads, on what `sample` is mounted on now; None when that has none."""
        element = self.instrument.cubes[probe].element if self.instrument else None
        space = self.state.samples.get(sample)
        if not isinstance(element, Probe) or element.reads is None or space is None:
            return None
        if space.holder is None:
            return None
        return self._holders[sample][space.holder].holder.grids.get(element.reads.grid)

    def grid_placement(self, probe: str) -> np.ndarray:
        """Where a grid probe's places are (column, row, sample index) on its sample: the grid's,
        on what is mounted. Its electrodes are of the holder, so no stage move finds them.

        Raises:
            ValueError: What is mounted has no such grid.
        """
        (sample,) = self.instrument.samples_of(probe) if self.instrument else ("",)
        grid = self._grid_of(probe, sample)
        if grid is None:
            raise ValueError(f"{probe} reads a grid that what {sample} is mounted on has not")
        matrix = np.eye(4)
        matrix[0, 0], matrix[1, 1] = grid.pitch.x * 1000.0, grid.pitch.y * 1000.0
        matrix[0, 3], matrix[1, 3] = grid.a1.x * 1000.0, grid.a1.y * 1000.0
        matrix[2, 2] = 0.0
        return matrix

    def one_sample(
        self,
        sample: str | None = None,
        detector: str | None = None,
        under: Mapping[str, Any] | None = None,
    ) -> str:
        """`sample`, or the one `detector` sees, or the only one.

        Raises:
            ValueError: No such sample; or several, and nothing says which.
        """
        samples = self.samples()
        if sample is not None:
            if sample not in samples:
                raise ValueError(f"No sample {sample!r}: there are {samples}")
            return sample
        if detector is not None:
            return self.sample_of(detector, under)
        if len(samples) == 1:
            return samples[0]
        raise ValueError(
            f"Which sample? There are {samples}: name one, or the detector that looks at it"
        )

    def resolve(
        self, system: str, detector: str | None = None, under: Mapping[str, Any] | None = None
    ) -> str:
        """`system` as the graph names it: a bare ``sample``, ``stage`` or ``well:B3`` is that of the
        sample `detector` sees under `under` (now, by default), or of the only one; any other name
        is already the graph's.

        Raises:
            ValueError: A bare name, several samples, and no detector to say which.
        """
        head, _, rest = system.partition(":")
        if system == SAMPLE:
            return sample_system(self.one_sample(detector=detector, under=under))
        if system == STAGE:
            return stage_system(self.one_sample(detector=detector, under=under))
        if head not in NOT_PLACES and rest and ":" not in rest:
            return place_system(head, self.one_sample(detector=detector, under=under), rest)
        return system

    def sample_of_system(self, system: str) -> str | None:
        """The sample `system` is a part of: ``sample:stage_a``'s, an image's, a detector's. None
        for a bare name, which is any sample's (`resolve`)."""
        head, _, rest = system.partition(":")
        if not rest or (head not in NOT_PLACES and ":" not in rest):
            return None
        if head in (SAMPLE, STAGE):
            return rest
        if head not in NOT_PLACES:
            return rest.partition(":")[0]
        if head == "image":
            return self._images[rest][0] if rest in self._images else None
        if head == "detector":
            assert self.instrument is not None
            return self.instrument.sample_of(rest, self._now(None))
        return None

    # ------------------------------------------------------------- the edges

    def mount(self, sample: str | None = None) -> np.ndarray:
        """`sample`'s stage micrometres to its sample micrometres (the only sample's, by default)."""
        return np.array(self.state.samples[self.one_sample(sample)].mount, dtype=float)

    def to_stage(self, detector: str, values: Mapping[str, Any] | None = None) -> np.ndarray:
        """Where `detector`'s pixels (column, row, plane) are in its stage's micrometres, under
        `values` or as things are now."""
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
        """Where the middle of `detector`'s sensor looks, in its stage's micrometres, under `at`."""
        assert self.values is not None
        roles = self.values.roles
        sample = self.sample_of(detector, at)
        return (
            sum(float(at[move.name]) for move in roles.sideways(detector, "x", sample)),
            sum(float(at[move.name]) for move in roles.sideways(detector, "y", sample)),
            roles.plane_um(detector, at),
        )

    def _image_middle(self, detector: str) -> np.ndarray:
        """The middle of `detector`'s image as it is read out now: column, row, plane, 1."""
        height, width = self.detector_state.get(detector).plane()
        return np.array([(width - 1) / 2.0, (height - 1) / 2.0, 0.0, 1.0])

    def placement(self, detector: str, values: Mapping[str, Any] | None = None) -> np.ndarray:
        """Where `detector`'s pixels (column, row, plane) are on the sample it sees, under `values`
        or as things are now.

        Raises:
            Dark: The switches send no light to it.
        """
        return self.mount(self.sample_of(detector, values)) @ self.to_stage(detector, values)

    def remember(
        self, image: str, to_sample: np.ndarray | list[list[float]], sample: str | None = None
    ) -> None:
        """Keep where the pixels of an image taken of `sample` are, so a point in it is a place to
        go."""
        self._images[image] = (self.one_sample(sample), np.array(to_sample, dtype=float))

    def forget_images(self, sample: str | None = None) -> None:
        """The images belong to what was mounted: a new mounting of `sample` (of every sample, by
        default) starts without them."""
        self._images = {
            image: kept
            for image, kept in self._images.items()
            if sample is not None and kept[0] != sample
        }

    def _detector_edge(
        self, detector: Detector, values: Mapping[str, Any] | None = None
    ) -> Transformation:
        """Where `detector` measures, on its sample's stage, under `values` or as things are now:
        its pixels, or the point it reads at."""
        source = detector_system(detector.name)
        stage = stage_system(self.sample_of(detector.name, values))
        if not detector.delivers_images():
            assert self.instrument is not None
            element = self.instrument.cubes[detector.name].element
            assert isinstance(element, Probe), f"{detector.name} measures nowhere known"
            if element.reads is not None:  # on the holder: straight onto its sample
                hub = sample_system(self.sample_of(detector.name, values))
                matrix = self.grid_placement(detector.name)
                return by_dimension(
                    source,
                    hub,
                    [
                        spatial_affine(matrix, ("x", "y"), ("x", "y")),
                        spatial_affine(matrix, (), ("z",)),
                    ],
                    "on the holder",
                )
            at = element.at
            assert at is not None
            point = [[at.x * 1000.0], [at.y * 1000.0], [at.z * 1000.0]]
            return by_dimension(source, stage, [affine_part((), SPATIAL, point)], "on stage")
        matrix = self.to_stage(detector.name, values)
        if detector.has_axis("z"):  # it steps its planes itself: each is its step further
            matrix[2, 2] = detector.axis("z").step or 1.0
            parts = [spatial_affine(matrix)]
        else:
            parts = [
                spatial_affine(matrix, ("x", "y"), ("x", "y")),
                spatial_affine(matrix, (), ("z",)),
            ]
        return by_dimension(source, stage, parts, "pixels")

    def _live(
        self, values: Mapping[str, Any] | None = None
    ) -> tuple[list[CoordinateSystem], list[Transformation]]:
        """The systems and edges that hold under `values` (now, by default), but for the images
        taken."""
        systems: list[CoordinateSystem] = []
        edges: list[Transformation] = []
        for sample, space in self.state.samples.items():
            hub, stage = sample_system(sample), stage_system(sample)
            systems += [spatial(hub), spatial(stage)]
            mount = np.array(space.mount, dtype=float)[:3].tolist()
            edges.append(Transformation(stage, hub, "AFFINE", "mount", affine=mount))
            if space.holder is not None:
                holder = self._holders[sample][space.holder].holder
                for (grid, place), (x, y) in places_of(holder).items():
                    name = place_system(grid, sample, place)
                    systems.append(spatial(name, ("x", "y")))
                    edges.append(
                        by_dimension(
                            name,
                            hub,
                            [
                                DimensionPart(
                                    "TRANSLATION", ["x", "y"], ["x", "y"], translation=[x, y]
                                )
                            ],
                            "place",
                        )
                    )
        if self.values is not None:
            for detector in self.detector_state.detectors:
                systems.append(_system_of(detector))
                if self.sees(detector.name, values):  # one the switches leave dark is nowhere
                    edges.append(self._detector_edge(detector, values))
        return systems, edges

    def graph(self, values: Mapping[str, Any] | None = None) -> CoordinateGraph:
        """The coordinate graph as it holds under `values`: now, by default."""
        systems, edges = self._live(values)
        for image, (sample, matrix) in self._images.items():
            systems.append(spatial(image_system(image), unit=""))
            edges.append(
                Transformation(
                    image_system(image),
                    sample_system(sample),
                    "AFFINE",
                    "image",
                    affine=matrix[:3].tolist(),
                )
            )
        return CoordinateGraph(systems, edges)

    def transform(
        self,
        position: Position,
        target: str = SAMPLE,
        axes: tuple[str, ...] | None = None,
        detector: str | None = None,
        under: Mapping[str, Any] | None = None,
    ) -> dict[str, float]:
        """Where `position` is in `target`, by axis name: along `axes`, or all the route states;
        the graph as it holds under `under` (now, by default). Bare names are those of the sample
        `detector` sees, or of the only one (`resolve`).

        Raises:
            NoRoute: Its system is none the graph knows, or not one that leads to `target`.
            ValueError: An axis asked for depends on one the position does not give; or a bare
                name, several samples and no detector.
        """
        found = Position(self.resolve(position.system, detector, under), position.coordinates)
        return self.graph(under).transform(found, self.resolve(target, detector, under), axes)

    # ------------------------------------------------------------- going there

    def targets(
        self, position: Position, detector: str, under: Mapping[str, Any] | None = None
    ) -> dict[str, float]:
        """What to set so that the middle of `detector`'s image, as read out, is at `position`, with
        the rest as `under` sets it (as things are now, by default): which sample it sees, too.

        Sideways, the one move along each way (`Roles.x`, `Roles.y`). Along the axis only when the
        position has a z, by what focuses it; a z that only a light sheet's move reaches is refused,
        not guessed. A bare ``sample`` is the one `detector` sees.

        Raises:
            ValueError: Nothing, or several things, move it along a way it has to go.
            NoRoute: The position's system is none the graph knows, or on another sample.
            Dark: The switches send no light to it.
        """
        assert self.values is not None
        roles = self.values.roles
        at = self._now(under)
        sample = self.sample_of(detector, at)
        has_z = "z" in position.coordinates
        on_stage = self.transform(
            position,
            STAGE,
            ("x", "y", "z") if has_z else ("x", "y"),
            detector=detector,
            under=at,
        )
        # How far the middle of the image is from where the sensor's middle looks: a window that is
        # not in the middle of its sensor looks beside it.
        aside = (self.to_stage(detector, at) @ self._image_middle(detector))[:2] - np.array(
            self._looks_at(detector, at)[:2]
        )
        x_move = roles.x(detector, sample=sample)
        y_move = roles.y(detector, sample=sample)
        found = {
            x_move.name: float(at[x_move.name])
            + on_stage["x"]
            - float(aside[0])
            - sum(float(at[m.name]) for m in roles.sideways(detector, "x", sample)),
            y_move.name: float(at[y_move.name])
            + on_stage["y"]
            - float(aside[1])
            - sum(float(at[m.name]) for m in roles.sideways(detector, "y", sample)),
        }
        if has_z:
            focus = roles.focus(detector, sample=sample)
            assert self.instrument is not None
            if focus in self.instrument.sheet_moves(sample):
                raise ValueError(f"{focus.name} moves a light sheet: a z is not reached by it yet")
            plane = roles.plane_um(detector, at)
            found[focus.name] = float(at[focus.name]) + on_stage["z"] - plane
        return found

    # ------------------------------------------------------------- the mount

    def mount_holder(self, holder: str, sample: str | None = None) -> None:
        """Mount `holder` on `sample` (the only one, by default): a new sample, where the
        description says it sits, with none of its images taken.

        Raises:
            ValueError: The description names no such holder for it, or no such sample.
        """
        sample = self.one_sample(sample)
        if holder not in self._holders[sample]:
            raise ValueError(
                f"No holder {holder!r} to mount on {sample}: there are "
                f"{sorted(self._holders[sample])}"
            )
        space = self.state.samples[sample]
        space.mount_id = _new_mount_id()
        self._mount(space, holder)
        self.forget_images(sample)
        self.refresh()

    def _mount(self, space: SampleSpace, holder: str) -> None:
        mounted = self._holders[space.sample][holder]
        space.mount = np.linalg.inv(holder_to_stage(mounted.mount)).tolist()
        space.holder = holder
        space.shape = _shape_of(space.sample, holder, mounted)

    def register_mount(self, matrix: list[list[float]], sample: str | None = None) -> None:
        """Say where what `sample` is mounted on sits: its stage micrometres to its sample
        micrometres."""
        found = np.array(matrix, dtype=float)
        if found.shape != (4, 4) or abs(np.linalg.det(found)) < 1e-12:
            raise ValueError("a mount is an invertible 4x4 matrix")
        self.state.samples[self.one_sample(sample)].mount = found.tolist()
        self.refresh()

    def origin_here(self, detector: str) -> None:
        """Make the x and y 0 of the sample `detector` sees the middle of its image now."""
        assert self.values is not None
        sample = self.sample_of(detector)
        middle = self.placement(detector) @ self._image_middle(detector)
        self.register_mount(
            (translation(-middle[0], -middle[1]) @ self.mount(sample)).tolist(), sample
        )

    # ------------------------------------------------------------- publishing

    def _placed(self, detector: str) -> DetectorPlacement:
        assert self.values is not None
        if self.detector_state.get(detector).is_probe():  # a grid on the holder: never measured
            matrix = self.grid_placement(detector)
            return DetectorPlacement(
                detector=detector,
                to_sample=matrix.tolist(),
                pixel_um=[float(np.hypot(*matrix[:2, 0])), float(np.hypot(*matrix[:2, 1]))],
                calibrated=False,
                sample=self.sample_of(detector),
            )
        _, calibrated = self.optics.scale_under(detector, self.values.snapshot())
        matrix = self.placement(detector)
        return DetectorPlacement(
            detector=detector,
            to_sample=matrix.tolist(),
            pixel_um=[float(np.hypot(*matrix[:2, 0])), float(np.hypot(*matrix[:2, 1]))],
            calibrated=calibrated,
            sample=self.sample_of(detector),
        )

    def record_map(
        self,
        detector: str,
        dims: tuple[str, ...],
        offsets: list[float],
        light_sweep: bool = False,
        values: Mapping[str, Any] | None = None,
    ) -> AxisMap:
        """Where an acquired record's axes go on the sample `detector` sees, under `values` (as
        things are now, by default; a record's, what its channel sets): `detector`'s route to its
        sample (`graph`), over the record's `dims`.

        A detector that takes images has its plane index placed by the stack: the plane it looks
        at now, then `offsets` (moving the light is moving the sample the other way). What
        measures at a point has one position along each of its record's ``z, y, x``, and that one
        is its point: as mikro wants it, every row reads its own axis (a row that reads none would
        send every input to one value). Where it was read along the stack, time, channels and
        arrival times are placed nowhere.
        """
        route = self.graph(values).axis_map(
            detector_system(detector), sample_system(self.sample_of(detector, values))
        )
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
        if not images:
            # What has no extent along an axis has one position along it there: as mikro wants
            # it, its row reads its own axis.
            for axis, row in rows.items():
                if not row[:-1].any():
                    row[dims.index(axis)] = 1.0
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
        sample = self.sample_of(detector)
        at = self.transform(Position(detector_system(detector)), sample_system(sample), SPATIAL)
        return MeasuredPoint(detector, at["x"], at["y"], at["z"], sample)

    def refresh(self) -> None:
        """Publish the graph as it holds now, where every detector's pixels are and where every
        detector that measures at a point measures, if that changed."""
        if self.values is None:
            return
        with self._refreshing:
            detectors = self.detector_state.detectors
            placed = {
                d.name: self._placed(d.name)
                for d in detectors
                if (d.delivers_images() or (d.is_probe() and d.has_axis("x"))) and self.sees(d.name)
            }
            points = {
                d.name: self._measured(d.name)
                for d in detectors
                if d.is_probe() and not d.has_axis("x")
            }
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
