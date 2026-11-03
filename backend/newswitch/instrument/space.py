"""Where things are: coordinate systems as nodes, transformations as edges, as mikro has them.

Each sample is a hub of its own: ``sample:<cube>``, the frame of what is mounted on that sample's
holder, in micrometres, with its origin where the holder has its own. An instrument has as many as
it has samples (`Instrument.samples`), each on a stage of its own. Everything that has a place is
placed in its sample's hub, by a route through the graph:

- ``stage:<cube>``: where that sample's stage is, the sum of what moves it sideways
  (`newswitch.services.stage.where`); the mount, ``stage:<cube> -> sample:<cube>``, says where the
  holder sits on it. What sits on the stage insert (a thermometer) is placed on the stage;
- ``detector:<name>``: what a detector delivers, an axis for each of its axes, as it is now; it
  goes to the stage of the sample it sees;
- ``image:<id>``: a detector as it was when it took an image;
- a holder's places (``well:<cube>:B3``), from its geometry.

The bare names ``sample``, ``stage`` and ``well:B3`` are short for the ones of a sample understood
from what looks (`newswitch.services.space.SpaceManager.resolve`).

A system has named, typed axes (`Axis`); an edge is one of mikro's kinds (`Transformation`). A
BY_DIMENSION is parts side by side over named axes, and says nothing about an axis no part names: a
color camera's columns and rows are placed and its colors are not, and a thermometer (no axes) is
placed at one point by a part from no axes onto x, y and z.

Routes compose axis by axis, by name (`compose`), as mikro composes them: an axis a step reads that
an earlier step stopped stating is dropped, never taken as 0. An edge is walked backwards only when
it can be: every part of it maps as many axes as it reads. Units pass through as they are: the
graph converts none.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from newswitch.instrument.spec import Holder, Mount
from newswitch.models.space import Axis, CoordinateSystem, DimensionPart, Position, Transformation

__all__ = [
    "SAMPLE",
    "SPATIAL",
    "STAGE",
    "AxisMap",
    "CoordinateGraph",
    "NOT_PLACES",
    "NoRoute",
    "Position",
    "affine_part",
    "by_dimension",
    "detector_system",
    "place_system",
    "sample_system",
    "stage_system",
    "holder_to_stage",
    "image_system",
    "places_of",
    "rotation_z",
    "scaling",
    "spatial",
    "spatial_affine",
    "to_parts",
    "translation",
    "walks_backwards",
    "zyx_rows",
]

#: A sample's hub, short: the frame of what is mounted on it (``sample:<cube>`` in the graph).
SAMPLE = "sample"
#: Where a sample's stage is, short (``stage:<cube>`` in the graph).
STAGE = "stage"
#: What a system's name starts with that is no place of a holder: any other is a grid's
#: (``well:B3``, ``electrode:D5``; ``well:<cube>:B3`` in the graph).
NOT_PLACES = frozenset({SAMPLE, STAGE, "detector", "image"})


def sample_system(sample: str) -> str:
    """The hub of the sample on the cube `sample`: ``"sample:stage_a"``."""
    return f"{SAMPLE}:{sample}"


def stage_system(sample: str) -> str:
    """Where the stage of the sample on the cube `sample` is: ``"stage:stage_a"``."""
    return f"{STAGE}:{sample}"


def place_system(grid: str, sample: str, place: str) -> str:
    """A place of a grid of what `sample` is mounted on: ``"well:stage_a:B3"``,
    ``"electrode:stage:D5"``."""
    return f"{grid}:{sample}:{place}"


#: The axes of a frame in space, in the order a 4x4 has them.
SPATIAL = ("x", "y", "z")

Matrix = np.ndarray


class NoRoute(ValueError):
    """Two coordinate systems are not connected, or not in the direction asked."""


def detector_system(detector: str) -> str:
    """The system of what `detector` delivers: ``"detector:camera"``."""
    return f"detector:{detector}"


def image_system(image: str) -> str:
    """The system of an image that was taken: ``"image:<id>"``."""
    return f"image:{image}"


def spatial(name: str, axes: Sequence[str] = SPATIAL, unit: str = "um") -> CoordinateSystem:
    """A frame in space: `axes` along space, in `unit` (empty: pixel indices)."""
    return CoordinateSystem(name, [Axis(axis, "SPACE", unit) for axis in axes])


# ------------------------------------------------------------- 4x4s over (x, y, z)


def translation(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Matrix:
    """A 4x4 translation over (x, y, z)."""
    matrix = np.eye(4)
    matrix[:3, 3] = (x, y, z)
    return matrix


def scaling(x: float = 1.0, y: float = 1.0, z: float = 1.0) -> Matrix:
    """A 4x4 scaling over (x, y, z)."""
    return np.diag([x, y, z, 1.0])


def rotation_z(degrees: float) -> Matrix:
    """A 4x4 rotation about z, counter-clockwise by `degrees` (x towards y)."""
    radians = np.deg2rad(degrees)
    cos, sin = np.cos(radians), np.sin(radians)
    matrix = np.eye(4)
    matrix[:2, :2] = [[cos, -sin], [sin, cos]]
    return matrix


def zyx_rows(matrix: Matrix) -> tuple[tuple[float, float, float, float], ...]:
    """A 4x4 over (x, y, z) as the three rows over (z, y, x) mikro and arrays take."""
    order = (2, 1, 0)
    return tuple(
        (*(float(matrix[row, column]) for column in order), float(matrix[row, 3])) for row in order
    )


# ------------------------------------------------------------- transformations


def affine_part(
    inputs: Sequence[str], outputs: Sequence[str], matrix: Matrix | Sequence[Sequence[float]]
) -> DimensionPart:
    """An AFFINE part: `inputs` onto `outputs` by the rows of `matrix` over `inputs` and 1.

    With no inputs, each row is an offset only: a point, placed.
    """
    rows = np.asarray(matrix, dtype=float).reshape(len(outputs), len(inputs) + 1)
    return DimensionPart("AFFINE", list(inputs), list(outputs), affine=rows.tolist())


def spatial_affine(
    matrix: Matrix, inputs: Sequence[str] = SPATIAL, outputs: Sequence[str] = SPATIAL
) -> DimensionPart:
    """The part of a 4x4 over (x, y, z) that maps `inputs` onto `outputs`."""
    columns = [SPATIAL.index(axis) for axis in inputs] + [3]
    return affine_part(
        inputs, outputs, np.asarray(matrix)[[SPATIAL.index(axis) for axis in outputs]][:, columns]
    )


def by_dimension(
    source: str, target: str, parts: Iterable[DimensionPart], name: str = ""
) -> Transformation:
    """A BY_DIMENSION from `source` to `target`: `parts` side by side."""
    return Transformation(source, target, "BY_DIMENSION", name=name, parts=list(parts))


@dataclass(frozen=True, eq=False)
class AxisMap:
    """An affine map between two systems, keyed by axis name, as mikro's.

    `matrix` is ``(len(output_axes) + 1) x (len(input_axes) + 1)``: a row per output axis, a column
    per input axis, the last the offset. `output_axes` names only what the map states: an axis it
    says nothing about has no row, never a zero one.
    """

    input_axes: tuple[str, ...]
    output_axes: tuple[str, ...]
    matrix: Matrix

    def apply(
        self, point: Mapping[str, float], outputs: Sequence[str] | None = None
    ) -> dict[str, float]:
        """`point`, by axis name, mapped onto `outputs` (all it states, by default).

        A point may leave out an axis as long as no output asked for reads it.

        Raises:
            ValueError: The point names an axis the map does not read, an output is one the map
                does not state, or an output reads an axis the point does not give.
        """
        strange = [axis for axis in point if axis not in self.input_axes]
        if strange:
            raise ValueError(f"{strange} are no axes of this map's input {list(self.input_axes)}")
        wanted = self.output_axes if outputs is None else tuple(outputs)
        unstated = [axis for axis in wanted if axis not in self.output_axes]
        if unstated:
            raise ValueError(
                f"Nothing says where {unstated} are: from {list(self.input_axes)} the route "
                f"states only {list(self.output_axes)}"
            )
        found = {}
        for axis in wanted:
            row = self.matrix[self.output_axes.index(axis)]
            missing = [
                name
                for name, factor in zip(self.input_axes, row[:-1])
                if factor != 0.0 and name not in point
            ]
            if missing:
                raise ValueError(f"{axis!r} depends on {missing}, which the position does not give")
            found[axis] = float(
                row[-1]
                + sum(
                    factor * point[name]
                    for name, factor in zip(self.input_axes, row[:-1])
                    if name in point
                )
            )
        return found

    def spatial(self) -> Matrix:
        """This map as a 4x4 over (x, y, z) on both sides; an axis it lacks is a zero.

        Only for drawing what is known to be spatial both ways (a detector's pixels on the sample).

        Raises:
            ValueError: It does not state x, y and z.
        """
        if not set(SPATIAL) <= set(self.output_axes):
            raise ValueError(f"it states only {list(self.output_axes)}, not x, y and z")
        matrix = np.zeros((4, 4))
        matrix[3, 3] = 1.0
        for row, axis in enumerate(SPATIAL):
            form = self.matrix[self.output_axes.index(axis)]
            matrix[row, 3] = form[-1]
            for name, factor in zip(self.input_axes, form[:-1]):
                if name in SPATIAL:
                    matrix[row, SPATIAL.index(name)] = factor
        return matrix


def _homogeneous(rows: Sequence[Sequence[float]], n_in: int) -> Matrix:
    """An M x (N+1) affine as an (M+1) x (N+1) homogeneous matrix."""
    block = np.asarray(rows, dtype=float).reshape(-1, n_in + 1)
    bottom = np.zeros((1, n_in + 1))
    bottom[0, -1] = 1.0
    return np.vstack([block, bottom])


def _block(kind: str, n_in: int, n_out: int, scale, translation_, affine) -> Matrix:  # noqa: ANN001
    """One kind's homogeneous matrix over its own axes."""
    if kind == "AFFINE":
        assert affine is not None, "an AFFINE takes affine"
        return _homogeneous(affine, n_in)
    if n_in != n_out:
        raise ValueError(f"a {kind} maps its axes one for one, but this maps {n_in} onto {n_out}")
    block = np.eye(n_in + 1)
    if kind == "SCALE":
        assert scale is not None, "a SCALE takes scale"
        block[:n_in, :n_in] = np.diag(scale)
    elif kind == "TRANSLATION":
        assert translation_ is not None, "a TRANSLATION takes translation"
        block[:n_in, n_in] = translation_
    elif kind != "IDENTITY":
        raise ValueError(f"no transformation of the kind {kind!r}")
    return block


def walks_backwards(
    transformation: Transformation, systems: Mapping[str, CoordinateSystem]
) -> bool:
    """Whether an edge can be walked from its output to its input: what it maps, it maps one for
    one. A BY_DIMENSION part that changes rank (a point placed in space) is walked forwards only."""
    if transformation.kind == "BY_DIMENSION":
        return all(len(part.input_axes) == len(part.output_axes) for part in transformation.parts)
    ranks = (len(systems[name].axes) for name in (transformation.input, transformation.output))
    return len(set(ranks)) == 1


def edge_map(
    transformation: Transformation,
    systems: Mapping[str, CoordinateSystem],
    backwards: bool = False,
) -> AxisMap:
    """One edge as an `AxisMap`, in the direction it is walked.

    Raises:
        ValueError: It does not fit its systems' axes, or cannot be walked backwards.
    """
    t = transformation
    ins = [axis.name for axis in systems[t.input].axes]
    outs = [axis.name for axis in systems[t.output].axes]
    if t.kind != "BY_DIMENSION":
        if t.kind == "IDENTITY":
            if ins != outs:
                raise ValueError(f"an IDENTITY from {t.input} {ins} to {t.output} {outs}")
            matrix = np.eye(len(ins) + 1)
        else:
            matrix = _block(t.kind, len(ins), len(outs), t.scale, t.translation, t.affine)
        if matrix.shape != (len(outs) + 1, len(ins) + 1):
            raise ValueError(
                f"{t.name or t.kind} does not map {t.input} {ins} to {t.output} {outs}"
            )
        if not backwards:
            return AxisMap(tuple(ins), tuple(outs), matrix)
        if len(ins) != len(outs):
            raise ValueError(f"{t.name or t.kind} changes rank and cannot be walked backwards")
        return AxisMap(tuple(outs), tuple(ins), np.linalg.inv(matrix))

    if backwards:
        ins, outs = outs, ins
    rows: dict[str, np.ndarray] = {}
    for part in t.parts:
        reads, writes = list(part.input_axes), list(part.output_axes)
        block = _block(
            part.kind, len(reads), len(writes), part.scale, part.translation, part.affine
        )
        if backwards:
            if len(reads) != len(writes):
                raise ValueError(f"{t.name or t.input} changes rank and cannot be walked backwards")
            reads, writes, block = writes, reads, np.linalg.inv(block)
        strangers = [a for a in reads if a not in ins] + [a for a in writes if a not in outs]
        if strangers:
            raise ValueError(
                f"{t.name or t.input}: a {part.kind} part names {strangers}, which {ins} -> {outs} "
                "do not have"
            )
        for index, axis in enumerate(writes):
            row = np.zeros(len(ins) + 1)
            for column, name in enumerate(reads):
                row[ins.index(name)] = block[index, column]
            row[-1] = block[index, len(reads)]
            rows[axis] = row
    stated = [axis for axis in outs if axis in rows]
    bottom = np.zeros(len(ins) + 1)
    bottom[-1] = 1.0
    return AxisMap(tuple(ins), tuple(stated), np.vstack([*(rows[a] for a in stated), bottom]))


def to_parts(axis_map: AxisMap) -> list[DimensionPart]:
    """`axis_map` as a BY_DIMENSION says it: one AFFINE part from the axes it reads onto the axes it
    states. An axis it neither reads nor states no part names, and so nothing is said of it: a
    camera record's time and channels, a thermometer's all."""
    if not axis_map.output_axes:
        return []
    form = axis_map.matrix[:-1]
    reads = [
        axis for index, axis in enumerate(axis_map.input_axes) if np.any(form[:, index] != 0.0)
    ]
    columns = [axis_map.input_axes.index(axis) for axis in reads]
    rows = [[*(row[column] for column in columns), row[-1]] for row in form]
    return [affine_part(reads, axis_map.output_axes, rows)]


def compose(maps: Iterable[AxisMap], source_axes: Sequence[str]) -> AxisMap:
    """A route's maps as one over `source_axes`, by substitution, axis by axis.

    An axis a step reads that an earlier one stopped stating is dropped: once a route has let go of
    an axis, nothing downstream takes hold of it again.
    """
    source = tuple(source_axes)
    current = AxisMap(source, source, np.eye(len(source) + 1))
    for edge in maps:
        rows, stated = [], []
        for axis, form in zip(edge.output_axes, edge.matrix[:-1]):
            row = np.zeros(len(source) + 1)
            row[-1] = form[-1]
            for name, factor in zip(edge.input_axes, form[:-1]):
                if factor == 0.0:
                    continue
                if name not in current.output_axes:
                    break
                row += factor * current.matrix[current.output_axes.index(name)]
            else:
                rows.append(row)
                stated.append(axis)
        bottom = np.zeros(len(source) + 1)
        bottom[-1] = 1.0
        current = AxisMap(source, tuple(stated), np.vstack([*rows, bottom]))
    return current


class CoordinateGraph:
    """Coordinate systems are nodes, transformations are edges; a route may walk one backwards
    when it can be."""

    def __init__(
        self, systems: Iterable[CoordinateSystem] = (), edges: Iterable[Transformation] = ()
    ) -> None:
        """A graph of `systems`, connected by `edges`.

        Raises:
            ValueError: An edge names a system that is not one of them.
        """
        self.systems = {system.name: system for system in systems}
        self.edges = list(edges)
        unknown = {
            name
            for edge in self.edges
            for name in (edge.input, edge.output)
            if name not in self.systems
        }
        if unknown:
            raise ValueError(f"edges name systems {sorted(unknown)} the graph does not have")

    def route(self, source: str, target: str) -> list[tuple[Transformation, bool]]:
        """The edges from `source` to `target`, each with whether it is walked backwards.

        The shortest route by the number of edges.

        Raises:
            NoRoute: They are not connected, or only against an edge that cannot be walked back.
        """
        for name in (source, target):
            if name not in self.systems:
                raise NoRoute(f"no route from {source!r} to {target!r}: there is no {name!r}")
        queue: deque[tuple[str, list[tuple[Transformation, bool]]]] = deque([(source, [])])
        seen = {source}
        while queue:
            at, walked = queue.popleft()
            if at == target:
                return walked
            for edge in self.edges:
                steps = [(edge.input, edge.output, False)]
                if walks_backwards(edge, self.systems):
                    steps.append((edge.output, edge.input, True))
                for start, end, backwards in steps:
                    if start == at and end not in seen:
                        seen.add(end)
                        queue.append((end, [*walked, (edge, backwards)]))
        raise NoRoute(f"no route from {source!r} to {target!r}")

    def axis_map(self, source: str, target: str) -> AxisMap:
        """The map from `source` to `target`, composed along the route."""
        return compose(
            (
                edge_map(edge, self.systems, backwards)
                for edge, backwards in self.route(source, target)
            ),
            [axis.name for axis in self.systems[source].axes],
        )

    def transform(
        self, position: Position, target: str, axes: Sequence[str] | None = None
    ) -> dict[str, float]:
        """`position`, said in `target`: along `axes`, or every axis the route states."""
        return self.axis_map(position.system, target).apply(position.coordinates, axes)


# ------------------------------------------------------------- holders


def holder_to_stage(mount: Mount, offset_um: tuple[float, float] = (0.0, 0.0)) -> Matrix:
    """Where a mounted holder's points are on the stage: the inverse of the mount, stage to sample.

    Its origin sits at `mount` (shifted by `offset_um`, what really is), turned by its rotation.
    """
    return translation(
        mount.x * 1000.0 + offset_um[0], mount.y * 1000.0 + offset_um[1]
    ) @ rotation_z(mount.rotation)


def places_of(holder: Holder) -> dict[tuple[str, str], tuple[float, float]]:
    """A holder's named places by grid (``("well", "B3")``, ``("electrode", "D5")``), in its
    sample's micrometres."""
    return {
        (grid, name): (x * 1000.0, y * 1000.0)
        for grid, places in holder.grids.items()
        for name, (x, y) in places.places().items()
    }
