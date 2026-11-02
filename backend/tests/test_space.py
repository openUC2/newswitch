"""Where things are: the coordinate graph, and whether what it says is where they really are."""

from collections.abc import Callable

import numpy as np
import pytest
from scipy import ndimage

from newswitch.drivers.simulated_detector import SimulatedDetectorManager
from newswitch.drivers.simulator import _beads
from newswitch.instrument.space import (
    CoordinateGraph,
    Edge,
    NoRoute,
    rotation_z,
    scaling,
    translation,
)
from newswitch.microscope.parts import Microscope

# --- the graph


def test_a_route_may_walk_an_edge_backwards() -> None:
    """Going to a place means walking from it to the motors, whichever way the edges were made."""
    graph = CoordinateGraph(
        [
            Edge("pixels", "stage", scaling(0.5, 0.5)),
            Edge("plate", "stage", translation(100.0, 0.0)),
        ]
    )
    assert graph.transform((4.0, 2.0, 0.0), "pixels", "plate") == pytest.approx([-98.0, 1.0, 0.0])


def test_systems_that_are_not_connected_have_no_route() -> None:
    """Nothing is guessed."""
    with pytest.raises(NoRoute):
        CoordinateGraph().route("a", "b")


def test_a_route_is_the_shortest() -> None:
    """Two ways to the same place: the one with fewer edges is walked."""
    graph = CoordinateGraph(
        [
            Edge("a", "b", translation(1.0)),
            Edge("b", "c", translation(1.0)),
            Edge("a", "c", translation(5.0)),
        ]
    )
    assert [edge.name for edge, _ in graph.route("a", "c")] == [""]
    assert graph.transform((0.0, 0.0, 0.0), "a", "c") == pytest.approx([5.0, 0.0, 0.0])


def test_a_point_in_an_earlier_image_is_a_place_to_go() -> None:
    """An image's own edge says where its pixels are: its middle is where the stage was."""
    stage, size = (100.0, 50.0), (64, 48)
    pixel_um = 0.663
    image = (
        translation(*stage)
        @ scaling(-pixel_um, pixel_um)  # x is flipped
        @ translation(-(size[0] - 1) / 2, -(size[1] - 1) / 2)
    )
    graph = CoordinateGraph([Edge("image:1", "stage", image)])
    middle = graph.transform(((size[0] - 1) / 2, (size[1] - 1) / 2, 0.0), "image:1", "stage")
    assert middle[:2] == pytest.approx(stage)
    corner = graph.transform((0.0, 0.0, 0.0), "image:1", "stage")
    assert corner[:2] == pytest.approx([100.0 + pixel_um * 31.5, 50.0 - pixel_um * 23.5])


def test_a_turned_edge_turns_its_points() -> None:
    """A quarter turn takes x to y."""
    graph = CoordinateGraph([Edge("a", "b", rotation_z(90.0))])
    assert graph.transform((1.0, 0.0, 0.0), "a", "b") == pytest.approx([0.0, 1.0, 0.0])


# --- the graph against what is really there

#: Where the stage is when the bead test images: far from where every system starts.
AWAY = (1500.0, -800.0)


def bright_peaks(image: np.ndarray, count: int = 12) -> list[tuple[float, float]]:
    """The `count` brightest isolated spots of `image`, as (column, row), away from its edge."""
    smooth = ndimage.gaussian_filter(image.astype(float), 1.0)
    peaks = (smooth == ndimage.maximum_filter(smooth, size=9)) & (smooth > np.median(smooth))
    rows, columns = np.nonzero(peaks)
    height, width = image.shape
    inside = (rows > 8) & (rows < height - 8) & (columns > 8) & (columns < width - 8)
    rows, columns = rows[inside], columns[inside]
    order = np.argsort(smooth[rows, columns])[::-1][:count]
    return [(float(columns[i]), float(rows[i])) for i in order]


def placed_by_metadata(
    microscope: Microscope, detector: str
) -> Callable[[float, float], np.ndarray]:
    """Where today's placement (the expanse's) says a pixel is: its affine, column and row in."""
    assert microscope.optics is not None and microscope.metadata is not None
    path = microscope.optics.get_light_path_for_detector(detector)
    matrix = np.array(microscope.metadata.get_metadata_for_light_path(path).affine_matrix)
    return lambda column, row: (matrix @ np.array([column, row, 0.0, 1.0]))[:2]


@pytest.mark.xfail(
    strict=True,
    reason="today's expanse placement is M·T(stage): its offset is scaled, and its origin a corner",
)
def test_a_bead_is_where_the_placement_says(microscope: Microscope) -> None:
    """Away from where the stage starts, the brightest beads of an image are placed on beads.

    The simulator knows where its beads are; a placement that is right puts every bright spot
    within a bead's width of one, and a wrong one, on average, half a bead spacing (~50 um) away.
    """
    assert microscope.values is not None and microscope.detector is not None
    microscope.values.set(
        {"laser_488.power": 20.0, "led_625.power": 0.0, "stage.x": AWAY[0], "stage.y": AWAY[1]}
    )
    image = microscope.detector.capture_image("camera").data
    place = placed_by_metadata(microscope, "camera")
    assert isinstance(microscope.detector, SimulatedDetectorManager)
    simulator = microscope.detector.simulator
    pattern = simulator.instrument.simulation_at(microscope.values.snapshot()).pattern
    bead_y, bead_x, _ = _beads(pattern)
    misses = []
    for column, row in bright_peaks(image):
        x, y = place(column, row)
        misses.append(float(np.min(np.hypot(bead_x - x, bead_y - y))))
    assert np.median(misses) < 3.0, misses
