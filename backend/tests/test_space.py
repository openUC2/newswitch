"""Where things are: the coordinate graph, and whether what it says is where they really are."""

from collections.abc import Callable

import numpy as np
import pytest
from scipy import ndimage

from newswitch.drivers.simulated_detector import SimulatedDetectorManager
from newswitch.instrument.space import (
    SPATIAL,
    CoordinateGraph,
    NoRoute,
    affine_part,
    by_dimension,
    rotation_z,
    scaling,
    spatial,
    spatial_affine,
    translation,
)
from newswitch.models.space import Axis, CoordinateSystem, DimensionPart, Transformation
from arkitekt import Task

from newswitch.microscope.parts import Microscope
from newswitch.models.acquisition import AcquisitionChannel
from newswitch.models.devices import AxisWindow
from newswitch.models.space import Position
from newswitch.routines.acquire import acquire as run_plan
from tests.conftest import acquisition
from tests.test_acquire import RecordingStore

# --- the graph


def affine(source: str, target: str, matrix: np.ndarray) -> Transformation:
    """An AFFINE edge over (x, y, z) both sides, from a 4x4."""
    return Transformation(source, target, "AFFINE", affine=np.asarray(matrix)[:3].tolist())


def frames(*names: str) -> list[CoordinateSystem]:
    """Frames in space, x, y and z in micrometres."""
    return [spatial(name) for name in names]


def at(system: str, x: float, y: float, z: float | None = None) -> Position:
    """A position by axis name; without z, z is not said."""
    return Position(system, {"x": x, "y": y, **({} if z is None else {"z": z})})


def test_a_route_may_walk_an_edge_backwards() -> None:
    """Going to a place means walking from it to the motors, whichever way the edges were made."""
    graph = CoordinateGraph(
        frames("pixels", "stage", "plate"),
        [
            affine("pixels", "stage", scaling(0.5, 0.5)),
            affine("plate", "stage", translation(100.0, 0.0)),
        ],
    )
    found = graph.transform(at("pixels", 4.0, 2.0, 0.0), "plate")
    assert found == pytest.approx({"x": -98.0, "y": 1.0, "z": 0.0})


def test_systems_that_are_not_connected_have_no_route() -> None:
    """Nothing is guessed."""
    with pytest.raises(NoRoute):
        CoordinateGraph(frames("a", "b")).route("a", "b")


def test_a_route_is_the_shortest() -> None:
    """Two ways to the same place: the one with fewer edges is walked."""
    shortcut = affine("a", "c", translation(5.0))
    shortcut.name = "shortcut"
    graph = CoordinateGraph(
        frames("a", "b", "c"),
        [affine("a", "b", translation(1.0)), affine("b", "c", translation(1.0)), shortcut],
    )
    assert [edge.name for edge, _ in graph.route("a", "c")] == ["shortcut"]
    assert graph.transform(at("a", 0.0, 0.0, 0.0), "c")["x"] == pytest.approx(5.0)


def test_a_point_in_an_earlier_image_is_a_place_to_go() -> None:
    """An image's own edge says where its pixels are: its middle is where the stage was."""
    stage, size = (100.0, 50.0), (64, 48)
    pixel_um = 0.663
    image = (
        translation(*stage)
        @ scaling(-pixel_um, pixel_um)  # x is flipped
        @ translation(-(size[0] - 1) / 2, -(size[1] - 1) / 2)
    )
    graph = CoordinateGraph(
        [spatial("image:1", unit=""), spatial("stage")], [affine("image:1", "stage", image)]
    )
    middle = graph.transform(
        at("image:1", (size[0] - 1) / 2, (size[1] - 1) / 2), "stage", ("x", "y")
    )
    assert middle == pytest.approx({"x": stage[0], "y": stage[1]})
    corner = graph.transform(at("image:1", 0.0, 0.0), "stage", ("x", "y"))
    assert corner == pytest.approx({"x": 100.0 + pixel_um * 31.5, "y": 50.0 - pixel_um * 23.5})


def test_a_turned_edge_turns_its_points() -> None:
    """A quarter turn takes x to y."""
    graph = CoordinateGraph(frames("a", "b"), [affine("a", "b", rotation_z(90.0))])
    assert graph.transform(at("a", 1.0, 0.0, 0.0), "b") == pytest.approx(
        {"x": 0.0, "y": 1.0, "z": 0.0}
    )


# --- by dimension

#: A color camera's pixels: colors, rows and columns, as mikro types them.
CAMERA = CoordinateSystem("camera", [Axis("c", "CHANNEL"), Axis("y", "SPACE"), Axis("x", "SPACE")])


def camera_graph() -> CoordinateGraph:
    """Pixels of 0.5 um onto the stage, looking at the plane 7 um up; the colors said nothing of."""
    pixels = scaling(0.5, 0.5) @ translation(z=7.0)
    return CoordinateGraph(
        [CAMERA, spatial("stage")],
        [
            by_dimension(
                "camera",
                "stage",
                [
                    spatial_affine(pixels, ("x", "y"), ("x", "y")),
                    spatial_affine(pixels, (), ("z",)),
                ],
            )
        ],
    )


def test_by_dimension_places_its_parts_and_says_nothing_of_the_rest() -> None:
    """A pixel's column and row go onto the stage, its plane is where it looks; its color is no
    place, so a pixel of any color is in the same one."""
    graph = camera_graph()
    route = graph.axis_map("camera", "stage")
    assert route.output_axes == ("x", "y", "z")
    assert graph.transform(Position("camera", {"x": 4.0, "y": 2.0}), "stage") == pytest.approx(
        {"x": 2.0, "y": 1.0, "z": 7.0}
    )
    assert graph.transform(
        Position("camera", {"c": 2.0, "x": 4.0, "y": 2.0}), "stage"
    ) == graph.transform(Position("camera", {"x": 4.0, "y": 2.0}), "stage")


def test_a_part_that_changes_rank_is_walked_forwards_only() -> None:
    """A pixel is a place on the stage, but a place on the stage is no pixel: nothing says which
    plane it is in, so no route goes back."""
    with pytest.raises(NoRoute):
        camera_graph().route("stage", "camera")


def test_an_axis_a_route_let_go_of_is_not_taken_again() -> None:
    """Through a system without z, z is dropped: never taken as 0."""
    graph = CoordinateGraph(
        [spatial("a"), spatial("flat", ("x", "y")), spatial("b")],
        [
            by_dimension("a", "flat", [DimensionPart("IDENTITY", ["x", "y"], ["x", "y"])]),
            by_dimension("flat", "b", [DimensionPart("IDENTITY", ["x", "y"], ["x", "y"])]),
        ],
    )
    assert graph.axis_map("a", "b").output_axes == ("x", "y")
    with pytest.raises(ValueError, match="z"):
        graph.transform(at("a", 1.0, 2.0, 3.0), "b", SPATIAL)


def test_a_point_has_no_axes_and_is_placed_all_the_same() -> None:
    """A thermometer measures at one point: a part from no axes onto x, y and z places it."""
    point = CoordinateSystem("thermometer")
    graph = CoordinateGraph(
        [point, spatial("stage"), spatial("sample")],
        [
            by_dimension(
                "thermometer",
                "stage",
                [affine_part((), SPATIAL, [[30_000.0], [0.0], [0.0]])],
            ),
            affine("stage", "sample", translation(-100.0, 50.0)),
        ],
    )
    assert graph.transform(Position("thermometer"), "sample") == pytest.approx(
        {"x": 29_900.0, "y": 50.0, "z": 0.0}
    )
    with pytest.raises(NoRoute):
        graph.route("sample", "thermometer")


def test_an_axis_a_position_needs_and_does_not_give_is_refused() -> None:
    """A position without z is not at z 0: where z matters, it is said so."""
    graph = CoordinateGraph(frames("a", "b"), [affine("a", "b", rotation_z(0.0) @ _tilt())])
    with pytest.raises(ValueError, match="depends on"):
        graph.transform(at("a", 1.0, 0.0), "b", ("x",))


def _tilt() -> np.ndarray:
    """x reads z as well."""
    matrix = np.eye(4)
    matrix[0, 2] = 0.1
    return matrix


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


Placed = Callable[[float, float], np.ndarray]


def placed_by_metadata(microscope: Microscope, detector: str) -> Placed:
    """Where the expanse says a pixel is: its frame's affine, column and row in."""
    assert microscope.optics is not None and microscope.metadata is not None
    path = microscope.optics.get_light_path_for_detector(detector)
    matrix = np.array(microscope.metadata.get_metadata_for_light_path(path).affine_matrix)
    return lambda column, row: (matrix @ np.array([column, row, 0.0, 1.0]))[:2]


def bead_misses(microscope: Microscope, image: np.ndarray, place: Placed) -> list[float]:
    """How far each bright spot of `image`, placed by `place`, is from the nearest real bead."""
    assert microscope.values is not None
    assert isinstance(microscope.detector, SimulatedDetectorManager)
    simulator = microscope.detector.simulator
    pattern = simulator.instrument.simulation_at(microscope.values.snapshot()).pattern
    bead_y, bead_x, _ = simulator.beads_in_sample(pattern)
    return [
        float(np.min(np.hypot(bead_x - x, bead_y - y)))
        for x, y in (place(column, row) for column, row in bright_peaks(image))
    ]


def on_beads(misses: list[float], within_um: float) -> bool:
    """Whether at least four bright spots are placed on a bead.

    Beads are ~100 um apart: a wrong placement lands a spot within a few um of one about once in
    three hundred times. The rest of the brightest spots of a small window can be noise.
    """
    return sum(miss < within_um for miss in misses) >= 4


def lit_away(microscope: Microscope) -> None:
    """Fluorescence, with the stage far from where it starts."""
    assert microscope.values is not None
    microscope.values.set(
        {"laser_488.power": 20.0, "led_625.power": 0.0, "stage.x": AWAY[0], "stage.y": AWAY[1]}
    )


@pytest.mark.parametrize(
    ("binning", "windows"),
    [
        (1, []),
        (2, []),
        (1, [AxisWindow("x", 40, 300), AxisWindow("y", 100, 256)]),
        (2, [AxisWindow("x", 37, 300), AxisWindow("y", 101, 256)]),
    ],
)
def test_a_bead_is_where_the_placement_says(
    microscope: Microscope, binning: int, windows: list[AxisWindow]
) -> None:
    """Away from where the stage starts, the brightest beads of an image are placed on beads.

    The simulator knows where its beads are; a placement that is right puts the bright spots that
    are beads within a bead's width of one (`on_beads`). A window and a binning move and grow the
    pixels, not the beads.
    """
    assert microscope.values is not None and microscope.detector is not None
    lit_away(microscope)
    microscope.values.set({"camera.binning": binning})
    microscope.detector.update_detector("camera", windows=windows)
    image = microscope.detector.capture_image("camera").data
    misses = bead_misses(microscope, image, placed_by_metadata(microscope, "camera"))
    assert on_beads(misses, 3.0 * binning), misses


def test_a_dataset_is_placed_on_its_beads(microscope: Microscope) -> None:
    """What an acquisition hands mikro places its pixels as the live image does: on the beads."""
    lit_away(microscope)
    store = RecordingStore()
    channel = AcquisitionChannel(
        detectors=["camera"], set_to={"laser_488.power": 20.0, "led_625.power": 0.0}
    )
    m = microscope
    run_plan(
        acquisition([channel], places=(AWAY,)),
        store,
        m.optics,
        m.detector,
        m.values,
        m.space,
        m.hooks,
        Task.local(),
    )
    (acquired,) = store.published
    rows = np.array(acquired.to_sample)

    def place(column: float, row: float) -> np.ndarray:
        z, y, x = rows @ np.array([0.0, row, column, 1.0])
        return np.array([x, y])

    misses = bead_misses(microscope, acquired.data[0, 0, 0], place)
    assert on_beads(misses, 3.0), misses


# --- going there


def test_a_place_on_the_sample_comes_to_the_middle_of_the_image(microscope: Microscope) -> None:
    """Moving to a sample point puts it where the image's middle is placed."""
    assert microscope.values is not None
    target = at("sample", 1234.0, -567.0)
    microscope.values.set(microscope.space.targets(target, "camera"))
    middle = microscope.space.placement("camera") @ np.array([255.5, 255.5, 0.0, 1.0])
    assert middle[:2] == pytest.approx([1234.0, -567.0])


def test_a_point_in_an_image_taken_is_a_place_to_go(microscope: Microscope) -> None:
    """Its pixel's sample point comes under the middle of the image, from wherever the stage is."""
    assert microscope.values is not None and microscope.acquisition is not None
    lit_away(microscope)
    (frame,) = microscope.acquisition.acquire(["camera"])
    seen = np.array(frame.metadata.affine_matrix) @ np.array([10.0, 20.0, 0.0, 1.0])
    microscope.values.set({"stage.x": 0.0, "stage.y": 0.0})
    microscope.values.set(microscope.space.targets(at(f"image:{frame.id}", 10.0, 20.0), "camera"))
    middle = microscope.space.placement("camera") @ np.array([255.5, 255.5, 0.0, 1.0])
    assert middle[:2] == pytest.approx(seen[:2])


def test_the_sample_starts_where_it_is_said_to(microscope: Microscope) -> None:
    """Its origin set here, the sample point under the middle of the image is 0, 0."""
    assert microscope.values is not None
    microscope.values.set({"stage.x": 300.0, "stage.y": 40.0})
    microscope.space.origin_here("camera")
    middle = microscope.space.placement("camera") @ np.array([255.5, 255.5, 0.0, 1.0])
    assert middle[:2] == pytest.approx([0.0, 0.0], abs=1e-9)
    on_stage = microscope.space.transform(at("sample", 0.0, 0.0), "stage", ("x", "y"))
    assert on_stage == pytest.approx({"x": 300.0, "y": 40.0})


def test_a_mount_that_is_no_map_is_refused(microscope: Microscope) -> None:
    """A singular matrix would lose where the stage is."""
    with pytest.raises(ValueError, match="invertible"):
        microscope.space.register_mount([[0.0] * 4] * 4)


def test_a_window_beside_the_middle_comes_to_the_place_itself(microscope: Microscope) -> None:
    """What comes to a place is the middle of the image as read out, not of the sensor."""
    assert microscope.values is not None and microscope.detector is not None
    microscope.detector.update_detector(
        "camera", windows=[AxisWindow("x", 0, 100), AxisWindow("y", 300, 200)]
    )
    target = at("sample", 250.0, 75.0)
    microscope.values.set(microscope.space.targets(target, "camera"))
    middle = microscope.space.placement("camera") @ np.array([49.5, 99.5, 0.0, 1.0])
    assert middle[:2] == pytest.approx([250.0, 75.0])
