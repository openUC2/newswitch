"""A multidimensional acquisition: detectors merged into channels, a dataset per position."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pytest
from arkitekt import Task
from scipy import ndimage

from newswitch.instrument import spec
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import (
    AcquiredDataset,
    MultidimensionalAcquisition,
    Position,
    Stack,
    StreamIllumination,
    Streams,
    Timepoint,
)
from newswitch.protocols.dataset_store import AcquiredPosition
from newswitch.routines.multidimensional_acquisition import acquire_multidimensional_acquisition
from newswitch.services.dataset_store import NoDatasetStore
from tests.conftest import run_settings

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
LASER = StreamIllumination(source="laser_488", wavelength=488.0, intensity=0.8)
LED = StreamIllumination(source="led_625", wavelength=625.0, intensity=0.5)


@dataclass
class RecordingStore:
    """Keeps what it is given."""

    published: list[AcquiredPosition] = field(default_factory=list)

    def check(self) -> None:
        """Always there."""

    def state(self) -> Mapping[str, Any]:
        """Nothing of interest here."""
        return {"stage.z": 0.0}

    def publish(self, acquired: AcquiredPosition) -> AcquiredDataset:
        """Keep it."""
        self.published.append(acquired)
        return AcquiredDataset(
            id=str(acquired.position), name=acquired.name, position=acquired.position
        )


def built(tmp_path: Path, name: str) -> Microscope:
    """The simulated microscope of an instrument."""
    return build_microscope(run_settings(tmp_path), spec.load(INSTRUMENTS / name))


def plan(
    streams: list[Streams],
    planes: list[float] | None = None,
    times: int = 1,
    places: tuple[tuple[float, float], ...] = ((0.0, 0.0),),
) -> MultidimensionalAcquisition:
    """The same stack of `streams` at every place, every time."""
    positions = [
        Position(
            x=x,
            y=y,
            z=0.0,
            stacks=[Stack(z_offset=0.0, z_slices=planes or [], z_step=1.0, channels=streams)],
        )
        for x, y in places
    ]
    return MultidimensionalAcquisition(
        timepoints=[Timepoint(positions=positions) for _ in range(times)], file_name="run"
    )


def acquire(
    m: Microscope,
    config: MultidimensionalAcquisition,
    store: Any = None,  # noqa: ANN401
) -> RecordingStore:
    """Run the routine on `m`, wired as the app wires it."""
    store = store or RecordingStore()
    acquire_multidimensional_acquisition(
        config,
        store,
        m.optics,
        m.detector,
        m.stage,
        m.illumination,
        m.illumination_state,
        m.calibration_state,
        m.metadata,
        m.hooks,
        Task.local(),
    )
    return store


def brightest_bead(image: np.ndarray) -> tuple[int, int]:
    """Where the most light of `image` is, as (row, column); smoothed against noise."""
    smooth = ndimage.gaussian_filter(image.astype(float), 2.0)
    row, column = np.unravel_index(np.argmax(smooth), smooth.shape)
    return int(row), int(column)


def stage_of(acquired: AcquiredPosition, z: int, y: float, x: float) -> np.ndarray:
    """Where a pixel is in stage micrometres, by the dataset's own placement."""
    return np.array(acquired.to_stage) @ np.array([z, y, x, 1.0])


# --- two detectors behind two filters


def test_two_detectors_of_a_stream_become_two_channels(tmp_path: Path) -> None:
    """Both cameras, one lighting: t, c, z, y, x, and a label each."""
    m = built(tmp_path, "dual-camera")
    store = acquire(
        m,
        plan(
            [
                Streams(
                    detectors=["camera_green", "camera_red"],
                    mapping="all",
                    illuminations=[LASER, LED],
                )
            ],
            planes=[-2.0, 0.0, 2.0],
            times=2,
        ),
    )
    (acquired,) = store.published
    assert acquired.data.shape == (2, 2, 3, 512, 512)
    assert [c.label for c in acquired.channels] == ["all camera_green", "all camera_red"]
    assert {c.detector for c in acquired.channels} == {"camera_green", "camera_red"}
    assert len(acquired.planes) == 2 * 2 * 3
    assert {(p.t, p.c, p.z) for p in acquired.planes} == {
        (t, c, z) for t in range(2) for c in range(2) for z in range(3)
    }
    assert acquired.data.dtype == np.uint16 and acquired.data.max() > 0


def test_each_filter_sees_its_own_light(tmp_path: Path) -> None:
    """Laser excites the beads: green passes; red through its filter sees nearly nothing."""
    m = built(tmp_path, "dual-camera")
    store = acquire(m, plan([Streams(detectors=["1", "2"], mapping="gfp", illuminations=[LASER])]))
    green, red = store.published[0].data[0, :, 0]
    assert np.percentile(green, 99.9) > 5 * np.percentile(red, 99.9)


def test_the_mirrored_arm_is_turned_back(tmp_path: Path) -> None:
    """The splitter's reflected arm sees the sample mirrored; merged, a bead is at one pixel.

    Green shows a bead bright, red (transmitted) the same bead dark.
    """
    m = built(tmp_path, "dual-camera")
    store = acquire(
        m,
        plan(
            [
                Streams(detectors=["camera_green"], mapping="gfp", illuminations=[LASER]),
                Streams(detectors=["camera_red"], mapping="led", illuminations=[LED]),
            ]
        ),
    )
    green, red = (
        ndimage.gaussian_filter(image.astype(float), 2.0)
        for image in store.published[0].data[0, :, 0]
    )
    merged = np.corrcoef(green.ravel(), red.ravel())[0, 1]
    assert merged < -0.5, "the beads of one channel are not where they are in the other"
    # As the camera really takes it, mirrored, it would not line up.
    mirrored = np.corrcoef(green.ravel(), red[:, ::-1].ravel())[0, 1]
    assert abs(mirrored) < 0.2


def test_positions_become_datasets_placed_in_stage_space(tmp_path: Path) -> None:
    """One dataset each; the same bead lands on the same stage micrometre in both."""
    m = built(tmp_path, "dual-camera")
    store = acquire(
        m,
        plan(
            [Streams(detectors=["camera_green"], mapping="gfp", illuminations=[LASER])],
            places=((0.0, 0.0), (60.0, 40.0)),
        ),
    )
    first, second = store.published
    assert (first.name, second.name) == ("run P1", "run P2")
    assert first.data.shape == (1, 1, 1, 512, 512)

    row, column = brightest_bead(first.data[0, 0, 0])
    expected = stage_of(first, 0, row, column)
    other_row, other_column = brightest_bead(second.data[0, 0, 0])
    found = stage_of(second, 0, other_row, other_column)
    assert found[1:] == pytest.approx(expected[1:], abs=2.0)


def test_placement_has_the_pixel_size_and_the_middle_at_the_stage(tmp_path: Path) -> None:
    """10x onto a 6.5 um pixel; every scale positive, as flips made every axis increase."""
    m = built(tmp_path, "dual-camera")
    store = acquire(
        m,
        plan(
            [Streams(detectors=["1"], mapping="gfp", illuminations=[LASER])],
            planes=[-2.0, 0.0, 2.0],
            places=((100.0, 50.0),),
        ),
    )
    (acquired,) = store.published
    z_row, y_row, x_row = acquired.to_stage
    assert z_row[0] == pytest.approx(2.0)
    assert z_row[3] == pytest.approx(-2.0)
    assert y_row[1] == pytest.approx(0.65, rel=0.02)
    assert x_row[2] == pytest.approx(0.65, rel=0.02)
    middle = stage_of(acquired, 0, 255.5, 255.5)
    assert middle[1:3] == pytest.approx([50.0, 100.0], abs=1e-6)
    assert acquired.calibrated is False


# --- an RGB camera


def test_an_rgb_camera_is_three_channels(tmp_path: Path) -> None:
    """A channel per color, of one exposure, labelled with it."""
    m = built(tmp_path, "rgb-camera")
    store = acquire(
        m,
        plan(
            [Streams(detectors=["camera"], mapping="gfp", illuminations=[LASER])],
            planes=[0.0, 1.0],
        ),
    )
    (acquired,) = store.published
    assert acquired.data.shape == (1, 3, 2, 512, 512)
    assert [c.color for c in acquired.channels] == ["r", "g", "b"]
    assert [c.label for c in acquired.channels] == ["gfp camera r", "gfp camera g", "gfp camera b"]


def test_its_colors_see_what_their_bands_let_through(tmp_path: Path) -> None:
    """A green emitter is brightest in g; red transmitted light is brightest in r."""
    m = built(tmp_path, "rgb-camera")
    store = acquire(
        m,
        plan(
            [
                Streams(detectors=["camera"], mapping="gfp", illuminations=[LASER]),
                Streams(detectors=["camera"], mapping="led", illuminations=[LED]),
            ]
        ),
    )
    data = store.published[0].data[0, :, 0]
    gfp_r, gfp_g, gfp_b = (np.percentile(data[c], 99.9) for c in range(3))
    assert gfp_g > gfp_r and gfp_g > gfp_b
    led_r, led_g, led_b = (np.median(data[c]) for c in range(3, 6))
    assert led_r > led_g and led_r > led_b


def test_alone_it_still_gives_one_image(tmp_path: Path) -> None:
    """The live view, an autofocus and a capture take one image, as of any camera."""
    m = built(tmp_path, "rgb-camera")
    assert m.detector is not None
    m.detector.activate_detector(1)
    assert m.detector.capture_image(1).data.shape == (512, 512)
    assert m.detector.capture_channels(1).shape == (3, 512, 512)
    m.detector.update_detector(1, binning=2)
    assert m.detector.capture_image(1).data.shape == (256, 256)
    assert m.detector.capture_channels(1).shape == (3, 256, 256)


# --- what is refused, before anything moves


@pytest.mark.parametrize(
    "config, finding",
    [
        (plan([Streams(detectors=["nope"], mapping="x", illuminations=[LASER])]), "No detector"),
        (plan([Streams(detectors=[], mapping="x", illuminations=[LASER])]), "names no detector"),
        (
            plan(
                [
                    Streams(
                        detectors=["1"],
                        mapping="x",
                        illuminations=[StreamIllumination("LED1", 488.0, 0.5)],
                    )
                ]
            ),
            "No light source",
        ),
        (
            plan(
                [Streams(detectors=["1"], mapping="x", illuminations=[LASER])],
                planes=[0.0, 1.0, 3.0],
            ),
            "evenly spaced",
        ),
    ],
)
def test_what_is_no_array_is_refused_before_anything_moves(
    tmp_path: Path, config: MultidimensionalAcquisition, finding: str
) -> None:
    """With the stage where it was and no dataset written."""
    m = built(tmp_path, "dual-camera")
    m.stage.move(x=7.0, is_absolute=True)  # type: ignore[union-attr]
    store = RecordingStore()
    with pytest.raises(ValueError, match=finding):
        acquire(m, config, store)
    assert m.stage_state.x == pytest.approx(7.0)
    assert store.published == []


def test_a_position_that_wanders_is_refused(tmp_path: Path) -> None:
    """One dataset is one place."""
    m = built(tmp_path, "dual-camera")
    stream = Streams(detectors=["1"], mapping="x", illuminations=[LASER])
    stack = Stack(z_offset=0.0, z_slices=[], z_step=1.0, channels=[stream])
    config = MultidimensionalAcquisition(
        timepoints=[
            Timepoint(positions=[Position(x=0.0, y=0.0, z=0.0, stacks=[stack])]),
            Timepoint(positions=[Position(x=9.0, y=0.0, z=0.0, stacks=[stack])]),
        ]
    )
    with pytest.raises(ValueError, match="moves at timepoint 2"):
        acquire(m, config)


def test_detectors_of_different_pixel_size_are_refused(tmp_path: Path) -> None:
    """One registration maps a dataset: binning one camera would make it wrong."""
    m = built(tmp_path, "dual-camera")
    assert m.detector is not None
    m.detector.update_detector(2, binning=2)
    with pytest.raises(ValueError, match="cannot share an array|one pixel size"):
        acquire(m, plan([Streams(detectors=["1", "2"], mapping="x", illuminations=[LASER])]))


def test_without_a_store_it_says_so(tmp_path: Path) -> None:
    """Before anything moves, and with what to do about it."""
    m = built(tmp_path, "dual-camera")
    config = plan([Streams(detectors=["1"], mapping="x", illuminations=[LASER])])
    with pytest.raises(RuntimeError, match="MIKRO_URL"):
        acquire(m, config, NoDatasetStore())


def test_nothing_reaches_the_local_cache(tmp_path: Path) -> None:
    """An acquisition goes to its store, and not to the frames of the expanse."""
    m = built(tmp_path, "dual-camera")
    acquire(m, plan([Streams(detectors=["1"], mapping="x", illuminations=[LASER])]))
    assert m.expanse_state.current_frames == []
    cache = tmp_path / "cache"
    assert not cache.exists() or not list(cache.iterdir())


def test_it_leaves_the_lights_off(tmp_path: Path) -> None:
    """Whatever it turned on, and only its stream's sources were on for each image."""
    m = built(tmp_path, "dual-camera")
    acquire(m, plan([Streams(detectors=["1"], mapping="x", illuminations=[LASER])]))
    assert not any(source.is_active for source in m.illumination_state.illuminations)
