"""Where things are: coordinate systems as nodes, the maps between them as edges.

The hub is the ``sample``: the frame of what is mounted, in micrometres, with its origin where the
holder has its own. Everything that has a place is placed in it, by a route through the graph:

- ``stage``: where the stage is, the sum of what moves sideways (`newswitch.services.stage.where`);
  the mount, ``stage -> sample``, says where the holder sits on it;
- ``detector:<name>``: the pixel indices of what a detector delivers along space, as it is now;
- ``image:<id>``: a detector as it was when it took an image;
- a holder's places (``well:B3``), from its geometry.

An edge is a 4x4 homogeneous matrix over (x, y, z), stored one way. A route may walk an edge
backwards, through its inverse, so it does not matter which way an edge was made. Nothing here
knows about a microscope: the edges are built elsewhere (`newswitch.services.space`).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

#: The hub: the frame of what is mounted.
SAMPLE = "sample"
#: Where the stage is.
STAGE = "stage"

Matrix = np.ndarray


class NoRoute(ValueError):
    """Two coordinate systems are not connected."""


def detector_system(detector: str) -> str:
    """The system of the pixels `detector` delivers: ``"detector:camera"``."""
    return f"detector:{detector}"


def image_system(image: str) -> str:
    """The system of an image that was taken: ``"image:<id>"``."""
    return f"image:{image}"


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


@dataclass(frozen=True)
class Edge:
    """A map from one coordinate system to another."""

    source: str
    target: str
    matrix: Matrix
    name: str = ""  # what made it: "mount", "calibrated", "predicted", ...


@dataclass(frozen=True)
class Position:
    """A place, in a coordinate system. No `z`: wherever z is."""

    system: str
    x: float
    y: float
    z: float | None = None


class CoordinateGraph:
    """Coordinate systems are nodes, transformations are edges; a route may walk one backwards."""

    def __init__(self, edges: Iterable[Edge] = ()) -> None:
        """A graph of `edges`."""
        self.edges: list[Edge] = list(edges)

    def systems(self) -> list[str]:
        """Every system an edge connects, in the order they first appear."""
        return list(
            dict.fromkeys(name for edge in self.edges for name in (edge.source, edge.target))
        )

    def route(self, source: str, target: str) -> list[tuple[Edge, bool]]:
        """The edges from `source` to `target`, each with whether it is walked forwards.

        The shortest route by the number of edges.

        Raises:
            NoRoute: They are not connected.
        """
        queue: deque[tuple[str, list[tuple[Edge, bool]]]] = deque([(source, [])])
        seen = {source}
        while queue:
            at, walked = queue.popleft()
            if at == target:
                return walked
            for edge in self.edges:
                for start, end, forwards in (
                    (edge.source, edge.target, True),
                    (edge.target, edge.source, False),
                ):
                    if start == at and end not in seen:
                        seen.add(end)
                        queue.append((end, [*walked, (edge, forwards)]))
        raise NoRoute(f"no route from {source!r} to {target!r}")

    def matrix(self, source: str, target: str) -> Matrix:
        """The map from `source` to `target`, composed along the route."""
        matrix = np.eye(4)
        for edge, forwards in self.route(source, target):
            matrix = (edge.matrix if forwards else np.linalg.inv(edge.matrix)) @ matrix
        return matrix

    def transform(self, point: tuple[float, float, float], source: str, target: str) -> np.ndarray:
        """`point` (x, y, z) in `source`, said in `target`."""
        return (self.matrix(source, target) @ np.array([*point, 1.0]))[:3]
