"""A multidimensional acquisition: detectors merged into channels, a dataset per position."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pytest
import yaml
from arkitekt import Task
from scipy import ndimage

from newswitch.instrument import spec
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import (
    AcquiredDataset,
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    AcquisitionStack,
)
from newswitch.protocols.dataset_store import AcquiredPosition
from newswitch.routines.acquire import acquire as run_plan
from newswitch.infra.mikro.none import NoDatasetStore
from tests.conftest import acquisition as plan
from tests.conftest import run_settings

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
LASER = {"laser_488.power": 40.0}
LED = {"led_625.power": 2.5e-5}


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


class StateStore(RecordingStore):
    """Remembers every variable at each image, as a store of a server does."""

    def __init__(self, m: Microscope) -> None:
        """Reading the values of `m`."""
        super().__init__()
        self.m = m

    def state(self) -> Mapping[str, Any]:
        """What the running microscope is set to now."""
        assert self.m.values is not None
        return self.m.values.snapshot()


def built(tmp_path: Path, name: str) -> Microscope:
    """The simulated microscope of an instrument."""
    return build_microscope(run_settings(tmp_path), spec.load(INSTRUMENTS / name))


def acquire(
    m: Microscope,
    config: AcquisitionPlan,
    store: Any = None,  # noqa: ANN401
) -> RecordingStore:
    """Run the routine on `m`, wired as the app wires it."""
    store = store or RecordingStore()
    run_plan(config, store, m.optics, m.detector, m.values, m.space, m.hooks, Task.local())
    return store


def bead_pixels(image: np.ndarray) -> np.ndarray:
    """Where each bead of `image` is, as (row, column); smoothed against noise."""
    smooth = ndimage.gaussian_filter(image.astype(float), 2.0)
    labels, count = ndimage.label(smooth > smooth.min() + (smooth.max() - smooth.min()) / 2.0)
    return np.array(ndimage.center_of_mass(smooth, labels, range(1, count + 1)))


def assert_same_beads(first: np.ndarray, second: np.ndarray, tolerance: float = 2.0) -> None:
    """Every bead of `first` well inside what `second` saw too has one of `second` just there.

    Both as (y, x) in the same stage micrometres.
    """
    margin = 15.0
    inside = np.all(
        (first > second.min(axis=0) + margin) & (first < second.max(axis=0) - margin), axis=1
    )
    assert inside.any(), "the two images share no bead to compare"
    for bead in first[inside]:
        assert np.linalg.norm(second - bead, axis=1).min() < tolerance


def stage_of(acquired: AcquiredPosition, z: int, y: float, x: float) -> np.ndarray:
    """Where a pixel is in stage micrometres, by the dataset's own placement."""
    return np.array(acquired.to_sample) @ np.array([z, y, x, 1.0])


# --- two detectors behind two filters


def test_two_detectors_of_a_channel_become_two_channels(tmp_path: Path) -> None:
    """Both cameras, one lighting: t, c, z, y, x, and a label each."""
    m = built(tmp_path, "dual-camera")
    store = acquire(
        m,
        plan(
            [
                AcquisitionChannel(
                    detectors=["camera_green", "camera_red"],
                    name="all",
                    set_to={**LASER, **LED},
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
    store = acquire(
        m,
        plan(
            [AcquisitionChannel(detectors=["camera_green", "camera_red"], name="gfp", set_to=LASER)]
        ),
    )
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
                AcquisitionChannel(detectors=["camera_green"], name="gfp", set_to=LASER),
                AcquisitionChannel(detectors=["camera_red"], name="led", set_to=LED),
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
            [AcquisitionChannel(detectors=["camera_green"], name="gfp", set_to=LASER)],
            places=((0.0, 0.0), (60.0, 40.0)),
        ),
    )
    first, second = store.published
    assert (first.name, second.name) == ("run P1", "run P2")
    assert first.data.shape == (1, 1, 1, 512, 512)

    def in_stage(acquired: AcquiredPosition) -> np.ndarray:
        return np.array(
            [
                stage_of(acquired, 0, row, column)[1:]
                for row, column in bead_pixels(acquired.data[0, 0, 0])
            ]
        )

    assert_same_beads(in_stage(first), in_stage(second))


def test_placement_has_the_pixel_size_and_the_middle_at_the_stage(tmp_path: Path) -> None:
    """10x onto a 6.5 um pixel; every scale positive, as flips made every axis increase."""
    m = built(tmp_path, "dual-camera")
    store = acquire(
        m,
        plan(
            [AcquisitionChannel(detectors=["camera_green"], name="gfp", set_to=LASER)],
            planes=[-2.0, 0.0, 2.0],
            places=((100.0, 50.0),),
        ),
    )
    (acquired,) = store.published
    z_row, y_row, x_row = acquired.to_sample
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
            [AcquisitionChannel(detectors=["camera"], name="gfp", set_to=LASER)],
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
                AcquisitionChannel(detectors=["camera"], name="gfp", set_to=LASER),
                AcquisitionChannel(detectors=["camera"], name="led", set_to=LED),
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
    assert m.detector is not None and m.values is not None
    m.detector.activate_detector("camera")
    assert m.detector.capture_image("camera").data.shape == (512, 512)
    assert m.detector.capture_channels("camera").shape == (3, 512, 512)
    m.values.set({"camera.binning": 2})
    assert m.detector.capture_image("camera").data.shape == (256, 256)
    assert m.detector.capture_channels("camera").shape == (3, 256, 256)


# --- what is refused, before anything moves


@pytest.mark.parametrize(
    "config, finding",
    [
        (plan([AcquisitionChannel(detectors=["nope"], name="x", set_to=LASER)]), "No detector"),
        (plan([AcquisitionChannel(detectors=[], name="x", set_to=LASER)]), "names no detector"),
        (
            plan([AcquisitionChannel(detectors=["camera_green"], set_to={"led1.power": 1.0})]),
            "led1.power is no variable",
        ),
        (
            plan(
                [AcquisitionChannel(detectors=["camera_green"], set_to={"laser_488.power": 900.0})]
            ),
            "goes from",
        ),
        (
            plan(
                [AcquisitionChannel(detectors=["camera_green"], name="x", set_to=LASER)],
                planes=[0.0, 1.0, 3.0],
            ),
            "evenly spaced",
        ),
    ],
)
def test_what_is_no_array_is_refused_before_anything_moves(
    tmp_path: Path, config: AcquisitionPlan, finding: str
) -> None:
    """With the stage where it was and no dataset written."""
    m = built(tmp_path, "dual-camera")
    m.values.set({"stage.x": 7.0})  # type: ignore[union-attr]
    store = RecordingStore()
    with pytest.raises(ValueError, match=finding):
        acquire(m, config, store)
    assert m.values["stage.x"] == pytest.approx(7.0)
    assert store.published == []


def test_detectors_of_different_pixel_size_are_refused(tmp_path: Path) -> None:
    """One registration maps a dataset: binning one camera would make it wrong."""
    m = built(tmp_path, "dual-camera")
    assert m.values is not None
    m.values.set({"camera_red.binning": 2})
    with pytest.raises(ValueError, match="cannot share an array|one pixel size"):
        acquire(
            m,
            plan(
                [
                    AcquisitionChannel(
                        detectors=["camera_green", "camera_red"], name="x", set_to=LASER
                    )
                ]
            ),
        )


def test_without_a_store_it_says_so(tmp_path: Path) -> None:
    """Before anything moves, and with what to do about it."""
    m = built(tmp_path, "dual-camera")
    config = plan([AcquisitionChannel(detectors=["camera_green"], name="x", set_to=LASER)])
    with pytest.raises(RuntimeError, match="MIKRO_URL"):
        acquire(m, config, NoDatasetStore())


def test_nothing_reaches_the_local_cache(tmp_path: Path) -> None:
    """An acquisition goes to its store, and not to the frames of the expanse."""
    m = built(tmp_path, "dual-camera")
    acquire(m, plan([AcquisitionChannel(detectors=["camera_green"], name="x", set_to=LASER)]))
    assert m.expanse_state.current_frames == []
    cache = tmp_path / "cache"
    assert not cache.exists() or not list(cache.iterdir())


def test_it_leaves_the_lights_off(tmp_path: Path) -> None:
    """Whatever it turned on, and only its channel's sources were on for each image."""
    m = built(tmp_path, "dual-camera")
    acquire(m, plan([AcquisitionChannel(detectors=["camera_green"], name="x", set_to=LASER)]))
    assert not any(source.on for source in m.source_state.sources.values())


# --- a plan is over variables


def test_each_channel_has_its_own_filter_and_exposure(tmp_path: Path) -> None:
    """One camera, one wheel: it is what a channel sets, and each plane records what was true."""
    m = built(tmp_path, "fake-microscope")
    open_slot, band = 1, 2
    store = acquire(
        m,
        plan(
            [
                AcquisitionChannel(
                    detectors=["camera_a"],
                    name="open",
                    set_to={
                        "laser_488.power": 20.0,
                        "filter_wheel.slot": open_slot,
                        "camera_a.exposure": 50.0,
                    },
                ),
                AcquisitionChannel(
                    detectors=["camera_a"],
                    name="band",
                    set_to={
                        "laser_488.power": 20.0,
                        "filter_wheel.slot": band,
                        "camera_a.exposure": 200.0,
                    },
                ),
            ]
        ),
        StateStore(m),
    )
    (acquired,) = store.published
    assert acquired.data.shape[1] == 2
    first, second = [plane.state for plane in acquired.planes]
    assert (first["filter_wheel.slot"], first["camera_a.exposure"]) == (open_slot, 50.0)
    assert (second["filter_wheel.slot"], second["camera_a.exposure"]) == (band, 200.0)
    assert [c.label for c in acquired.channels] == ["open camera_a", "band camera_a"]
    assert np.percentile(acquired.data[0, 1, 0], 99.9) > np.percentile(acquired.data[0, 0, 0], 99.9)


def test_a_source_a_channel_does_not_name_is_off(tmp_path: Path) -> None:
    """Whatever was on before: a channel's light is what it says."""
    m = built(tmp_path, "dual-camera")
    assert m.values is not None
    m.values.set({"led_625.power": 2.5e-5, "laser_488.power": 40.0})
    store = acquire(
        m,
        plan([AcquisitionChannel(detectors=["camera_green"], set_to={"laser_488.power": 10.0})]),
        StateStore(m),
    )
    (plane,) = store.published[0].planes
    assert plane.state["led_625.power"] == 0.0
    assert plane.state["laser_488.power"] == 10.0
    assert store.published[0].channels[0].sources == ("laser_488",)


def test_a_position_can_set_anything_and_stay_for_the_rest(tmp_path: Path) -> None:
    """A position is what to set to get there: nothing at all stays where it is."""
    m = built(tmp_path, "fake-microscope")
    assert m.values is not None
    m.values.set({"stage.x": 7.0})
    channel = AcquisitionChannel(detectors=["camera_a"], set_to={"laser_488.power": 20.0})
    store = acquire(
        m,
        AcquisitionPlan(
            channels=[channel],
            positions=[AcquisitionPosition(), AcquisitionPosition(set_to={"tube_a.dz": 1.0})],
        ),
        StateStore(m),
    )
    stayed, moved = store.published
    assert stayed.planes[0].state["stage.x"] == 7.0 and stayed.planes[0].state["tube_a.dz"] == 0.0
    assert moved.planes[0].state["tube_a.dz"] == 1.0


def test_a_stack_sweeps_what_it_is_told(tmp_path: Path) -> None:
    """Any variable that focuses; each plane records where it was."""
    m = built(tmp_path, "dual-camera")
    channel = AcquisitionChannel(detectors=["camera_green"], set_to={"laser_488.power": 20.0})
    store = acquire(
        m,
        AcquisitionPlan(
            channels=[channel],
            stack=AcquisitionStack(offsets=[-1.0, 0.0, 1.0], variable="stage.z"),
        ),
        StateStore(m),
    )
    assert [plane.state["stage.z"] for plane in store.published[0].planes] == [-1.0, 0.0, 1.0]


def test_a_stack_of_what_does_not_focus_is_refused(tmp_path: Path) -> None:
    """Before anything moves, with what does."""
    m = built(tmp_path, "dual-camera")
    channel = AcquisitionChannel(detectors=["camera_green"], set_to={"laser_488.power": 20.0})
    with pytest.raises(ValueError, match="stage.x is no focus of camera_green: that is stage.z"):
        acquire(
            m,
            AcquisitionPlan(
                channels=[channel],
                stack=AcquisitionStack(offsets=[0.0, 1.0], variable="stage.x"),
            ),
        )


def test_planes_beyond_its_travel_are_refused(tmp_path: Path) -> None:
    """Not brought back into range, which would make planes that are not where they say."""
    m = built(tmp_path, "dual-camera")
    channel = AcquisitionChannel(detectors=["camera_green"], set_to={"laser_488.power": 20.0})
    with pytest.raises(ValueError, match="stage.z goes from"):
        acquire(m, plan([channel], planes=[-1e6, 1e6]))
    assert m.values is not None and m.values["stage.z"] == 0.0


def test_a_channel_binning_differently_is_refused_before_it_is_set(tmp_path: Path) -> None:
    """What decides is what the channel would set, not what is set now."""
    m = built(tmp_path, "fake-microscope")
    assert m.values is not None
    with pytest.raises(ValueError, match="cannot share an array"):
        acquire(
            m,
            plan(
                [
                    AcquisitionChannel(detectors=["camera_a"], set_to={"laser_488.power": 20.0}),
                    AcquisitionChannel(
                        detectors=["camera_a"],
                        set_to={"laser_488.power": 20.0, "camera_a.binning": 2.0},
                    ),
                ]
            ),
        )
    assert m.values["camera_a.binning"] == 1


def test_a_channel_with_another_objective_is_refused_before_it_is_set(tmp_path: Path) -> None:
    """Another pixel size, under what the channel sets: one dataset has one."""
    m = built(tmp_path, "fake-microscope")
    assert m.values is not None
    with pytest.raises(ValueError, match="one pixel size"):
        acquire(
            m,
            plan(
                [
                    AcquisitionChannel(detectors=["camera_a"], set_to={"laser_488.power": 20.0}),
                    AcquisitionChannel(
                        detectors=["camera_a"],
                        set_to={"laser_488.power": 20.0, "objective.slot": 2.0},
                    ),
                ]
            ),
        )
    assert m.values["objective.slot"] == 1


def test_the_array_is_of_the_type_the_sensor_delivers(tmp_path: Path) -> None:
    """An 8 bit sensor is no uint16 dataset."""
    data = yaml.safe_load((INSTRUMENTS / "dual-camera" / "microscope.yml").read_text())
    data.pop("ui", None)
    for name in ("camera_green", "camera_red"):
        data["cubes"][name]["element"]["readout"] = {
            "qe": 0.8,
            "electrons_per_count": 40.0,
            "read_noise": 1.0,
            "offset": 10.0,
            "full_well": 10000,
            "bit_depth": 8,
        }
    (tmp_path / "microscope.yml").write_text(yaml.safe_dump(data))
    m = build_microscope(run_settings(tmp_path), spec.load(tmp_path))
    store = acquire(
        m, plan([AcquisitionChannel(detectors=["camera_green"], set_to={"laser_488.power": 20.0})])
    )
    assert store.published[0].data.dtype == np.uint8


def test_a_swap_is_its_slot_from_a_plans_numbers(tmp_path: Path) -> None:
    """A plan's numbers all arrive as floats, and the optics find a swap by its slot."""
    m = built(tmp_path, "fake-microscope")
    assert m.values is not None
    m.values.set({"filter_wheel.slot": 2.0})
    assert m.values["filter_wheel.slot"] == 2 and isinstance(m.values["filter_wheel.slot"], int)
    assert m.detector is not None and m.detector.capture_image("camera_a").data.size
