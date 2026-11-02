"""Instruments the code was never told about: what is new about each is only in its description.

No generic code knows a second wheel, a piezo, an objective that focuses, or two sizes of camera. If
one of these needs a change anywhere but here, the knowledge is in the wrong place.
"""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from newswitch.instrument import spec
from newswitch.instrument.tracing import collected
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.models.acquisition import (
    AcquisitionChannel,
    AcquisitionPlan,
    AcquisitionPosition,
    AcquisitionStack,
)
from newswitch.routines.autofocus import autofocus_sweep
from newswitch.routines.calibration import calibrate_light_path
from newswitch.services.stage import stage_of
from tests.conftest import run_settings
from tests.test_acquire import StateStore, acquire

INSTRUMENTS = Path(__file__).parent.parent / "instruments"


def described(tmp_path: Path, change: Callable[[dict[str, Any]], Any]) -> Microscope:
    """A running microscope of dual-camera, as changed by `change`."""
    data = yaml.safe_load((INSTRUMENTS / "dual-camera" / spec.DESCRIPTION).read_text())
    data.pop("ui", None)
    data.pop("agent_ui", None)
    change(data)
    (tmp_path / spec.DESCRIPTION).write_text(yaml.safe_dump(data))
    return build_microscope(run_settings(tmp_path), spec.load(tmp_path))


def lit(*detectors: str, **set_to: float) -> AcquisitionChannel:
    """A channel of `detectors` with the laser on; dots in a variable's name are written as `__`."""
    return AcquisitionChannel(
        detectors=list(detectors),
        set_to={"laser_488.power": 20.0, **{k.replace("__", "."): v for k, v in set_to.items()}},
    )


# --- two wheels, and a filter per channel


def two_wheels(data: dict[str, Any]) -> None:
    """An excitation wheel and an emission wheel, of the same three filters."""
    filters = {
        1: {"kind": "filter", "name": "Open"},
        2: {"kind": "filter", "name": "BP 525/50", "curve": "bp_525_50"},
        3: {"kind": "filter", "name": "BP 625/50", "curve": "bp_625_50"},
    }
    wheel = {"swaps": {"slot": {"initial": 1, "slots": filters}}}
    data["cubes"]["excitation_wheel"] = copy.deepcopy(wheel)
    data["cubes"]["emission_wheel"] = copy.deepcopy(wheel)
    illumination = data["illumination"]
    illumination[0] = {"from": "laser_488", "to": "excitation_wheel"}
    illumination.insert(1, {"from": "excitation_wheel", "to": "dichroic"})
    detection = data["detection"]
    at = next(i for i, e in enumerate(detection) if e["to"] == "splitter")
    detection[at : at + 1] = [
        {"from": "dichroic", "via": "transmit", "to": "emission_wheel", "distance": "15 mm"},
        {"from": "emission_wheel", "to": "splitter", "distance": "15 mm"},
    ]


def test_two_wheels_each_have_a_control(tmp_path: Path) -> None:
    """A second wheel is one more entry."""
    m = described(tmp_path, two_wheels)
    assert set(m.swap_state.swaps) == {"excitation_wheel", "emission_wheel"}
    assert m.values is not None
    m.values.set({"emission_wheel.slot": 2, "excitation_wheel.slot": 3})
    swaps = m.swap_state.swaps
    assert swaps["emission_wheel"]["slot"].label == "BP 525/50"
    assert swaps["excitation_wheel"]["slot"].label == "BP 625/50"


def test_each_wheel_does_what_it_is_for(tmp_path: Path) -> None:
    """Found from the optics: blocking the laser on its way in, or the emission on its way out."""
    m = described(tmp_path, two_wheels)
    assert m.values is not None
    m.values.set({"laser_488.power": 20.0})
    counts = lambda: m.optics_state.detectors["camera_green"].expected_counts  # noqa: E731
    open_counts = counts()
    assert open_counts > 0
    m.values.set({"emission_wheel.slot": 3})  # passes no green
    assert counts() < 0.1 * open_counts
    m.values.set({"emission_wheel.slot": 1, "excitation_wheel.slot": 3})  # passes no blue
    assert counts() < 0.1 * open_counts


def test_a_filter_per_channel_is_what_a_channel_sets(tmp_path: Path) -> None:
    """Which no acquisition could do before: one camera, the same plane, two filters."""
    m = described(tmp_path, two_wheels)
    store = acquire(
        m,
        AcquisitionPlan(
            channels=[
                lit("camera_green", emission_wheel__slot=2.0),
                lit("camera_green", emission_wheel__slot=3.0),
            ]
        ),
        StateStore(m),
    )
    (acquired,) = store.published
    assert [plane.state["emission_wheel.slot"] for plane in acquired.planes] == [2, 3]
    passes, blocks = acquired.data[0, 0, 0], acquired.data[0, 1, 0]
    assert np.percentile(passes, 99.9) > 5 * np.percentile(blocks, 99.9)


# --- a piezo beside a coarse z


def with_a_piezo(data: dict[str, Any]) -> None:
    """A fine move along the axis, beside the coarse one."""
    data["cubes"]["stage"]["moves"]["piezo"] = {
        "along": "axis",
        "initial": "0 um",
        "step": "0.01 um",
        "min": "-100 um",
        "max": "100 um",
    }


def test_a_piezo_is_found_to_focus_though_its_step_is_tiny(tmp_path: Path) -> None:
    """A step too small to see says nothing about what a move is for."""
    m = described(tmp_path, with_a_piezo)
    assert m.values is not None
    names = {move.name for move in m.values.roles.focuses("camera_green")}
    assert names == {"stage.z", "stage.piezo"}


def test_two_things_that_focus_are_not_guessed_between(tmp_path: Path) -> None:
    """An autofocus or a stack stops, and lists them, rather than moving the wrong one."""
    m = described(tmp_path, with_a_piezo)
    assert m.values is not None
    with pytest.raises(ValueError, match=r"stage\.piezo, stage\.z"):
        stage_of(m.values, "camera_green")
    with pytest.raises(ValueError, match=r"stage\.piezo, stage\.z"):
        acquire(
            m, AcquisitionPlan(channels=[lit("camera_green")], stack=AcquisitionStack([0.0, 1.0]))
        )


def test_a_stack_can_name_the_piezo_and_the_coarse_stays(tmp_path: Path) -> None:
    """Each plane says where the piezo was."""
    m = described(tmp_path, with_a_piezo)
    store = acquire(
        m,
        AcquisitionPlan(
            channels=[lit("camera_green")],
            stack=AcquisitionStack(offsets=[-1.0, 0.0, 1.0], variable="stage.piezo"),
        ),
        StateStore(m),
    )
    planes = store.published[0].planes
    assert [plane.state["stage.piezo"] for plane in planes] == [-1.0, 0.0, 1.0]
    assert {plane.state["stage.z"] for plane in planes} == {0.0}


def test_an_autofocus_can_name_the_piezo(tmp_path: Path) -> None:
    """And finds focus with it."""
    m = described(tmp_path, with_a_piezo)
    assert m.values is not None and m.detector is not None
    m.values.set({"laser_488.power": 20.0, "stage.piezo": 30.0})
    stage = stage_of(m.values, "camera_green", "stage.piezo")
    sweep = [30.0 + offset for offset in np.linspace(-40.0, 40.0, 17)]
    best, _ = autofocus_sweep(stage, m.detector, sweep, "camera_green")
    assert abs(best) <= 5.0
    assert m.values["stage.z"] == 0.0


# --- an objective that focuses, and a stage that does not


def objective_focuses(data: dict[str, Any]) -> None:
    """A stage that only moves sideways, and an objective that moves along the axis."""
    del data["cubes"]["stage"]["moves"]["z"]
    data["cubes"]["objective"]["moves"] = {
        "z": {
            "actuator": "stg-z",
            "along": "axis",
            "initial": "0 um",
            "step": "100 um",
            "min": "-500 um",
            "max": "500 um",
        }
    }


def test_an_objective_can_be_what_focuses(tmp_path: Path) -> None:
    """Nothing says what a stage is: what focuses is whatever is found to."""
    m = described(tmp_path, objective_focuses)
    assert m.values is not None
    found = m.values.roles.found["camera_green"]["objective.z"]
    assert "blur" in found
    assert [move.name for move in m.values.roles.focuses("camera_green")] == ["objective.z"]
    assert m.optics_state.detectors["camera_green"].defocus_um == 0.0
    m.values.set({"objective.z": 100.0})
    assert m.optics_state.detectors["camera_green"].defocus_um == pytest.approx(100.0)


def test_a_stack_sweeps_the_objective(tmp_path: Path) -> None:
    """With no z on the stage to go to."""
    m = described(tmp_path, objective_focuses)
    store = acquire(
        m,
        AcquisitionPlan(
            channels=[lit("camera_green")], stack=AcquisitionStack([-100.0, 0.0, 100.0])
        ),
        StateStore(m),
    )
    assert [p.state["objective.z"] for p in store.published[0].planes] == [-100.0, 0.0, 100.0]


# --- cameras of different sizes


def two_sizes(data: dict[str, Any]) -> None:
    """A square camera, and a wide one of twice as many pixels each way or more."""
    data["cubes"]["camera_red"]["element"]["axes"] = {
        "x": {"size": 2048, "pitch": "6.5 um"},
        "y": {"size": 1024, "pitch": "6.5 um"},
    }


def test_each_camera_has_the_size_it_states(tmp_path: Path) -> None:
    """The simulated detectors used to have one size between them."""
    m = described(tmp_path, two_sizes)
    assert m.detector is not None
    assert m.detector.capture_image("camera_green").data.shape == (512, 512)
    assert m.detector.capture_image("camera_red").data.shape == (1024, 2048)
    fields = m.optics_state.detectors
    assert fields["camera_red"].field_width_um == pytest.approx(
        4 * fields["camera_green"].field_width_um, rel=0.01
    )


def test_they_calibrate_each_with_its_own_frame(tmp_path: Path) -> None:
    """The moves are sized by each one's own."""
    m = described(tmp_path, two_sizes)
    assert m.values is not None and m.detector is not None
    m.values.set({"laser_488.power": 20.0, "led_625.power": 4.0e-5})
    done = calibrate_light_path(
        m.optics, m.metadata, m.calibration, m.values, m.detector, m.detector_state
    )
    assert len(done) == 2
    assert all(d.calibrated for d in m.optics_state.detectors.values())


def test_a_camera_that_sees_nothing_does_not_cost_the_others_theirs(tmp_path: Path) -> None:
    """Blue light through a red filter tells nothing: it says so, and the green camera has its."""
    m = described(tmp_path, two_sizes)
    assert m.values is not None and m.detector is not None
    m.values.set({"laser_488.power": 20.0})
    with pytest.raises(ValueError, match=r"camera_red .*\(1 calibrated all the same\)"):
        calibrate_light_path(
            m.optics, m.metadata, m.calibration, m.values, m.detector, m.detector_state
        )
    found = m.optics_state.detectors
    assert found["camera_green"].calibrated and not found["camera_red"].calibrated


def test_cameras_of_two_sizes_make_a_record_each(tmp_path: Path) -> None:
    """An array is regular, so each camera is a record of its own size."""
    m = described(tmp_path, two_sizes)
    green, red = acquire(m, AcquisitionPlan(channels=[lit("camera_green", "camera_red")])).published
    assert red.data.shape[-2:] == (1024, 2048)
    assert green.data.shape[-2:] != red.data.shape[-2:]


# --- oil


def oil(data: dict[str, Any]) -> None:
    """The same focal length, so the same pixels, gathering through oil."""
    data["cubes"]["objective"]["element"].update(na=1.4, immersion="oil")


def test_an_oil_objective_is_described_and_gathers_what_it_should(tmp_path: Path) -> None:
    """An NA above 1, which the air everything used to be in could not have."""
    m = described(tmp_path, oil)
    lens = m.values.instrument.cubes["objective"].element  # type: ignore[union-attr]
    assert lens.index == pytest.approx(1.515)
    # By hand: asin(1.4 / 1.515) is 67.5 degrees, and (1 - cos) / 2 of that is 0.309.
    assert collected(lens) == pytest.approx(0.309, abs=0.002)
    found = m.optics_state.detectors["camera_green"]
    # By hand: 0.525 um x 1.515 / 1.4^2 is 0.406 um.
    assert found.depth_of_field_um == pytest.approx(0.406, rel=0.05)


def test_it_is_brighter_than_a_dry_one_by_what_it_gathers(tmp_path: Path) -> None:
    """Same laser, same field: only how much of what is emitted the lens takes in differs."""
    dry = described(tmp_path, lambda data: None)
    other = tmp_path / "oil"
    other.mkdir()
    wet = described(other, oil)
    for m in (dry, wet):
        assert m.values is not None
        m.values.set({"laser_488.power": 20.0})
    ratio = (
        wet.optics_state.detectors["camera_green"].expected_counts
        / dry.optics_state.detectors["camera_green"].expected_counts
    )
    gathered = 0.309 / ((1.0 - np.cos(np.arcsin(0.25))) / 2.0)
    assert ratio == pytest.approx(gathered, rel=0.3)


def test_a_position_can_be_anything_that_moves(tmp_path: Path) -> None:
    """A dataset per what a position sets, on any instrument."""
    m = described(tmp_path, with_a_piezo)
    store = acquire(
        m,
        AcquisitionPlan(
            channels=[lit("camera_green")],
            positions=[
                AcquisitionPosition(set_to={"stage.piezo": 5.0}),
                AcquisitionPosition(set_to={"stage.x": 100.0, "stage.piezo": -5.0}),
            ],
        ),
        StateStore(m),
    )
    first, second = store.published
    assert first.planes[0].state["stage.piezo"] == 5.0
    assert second.planes[0].state["stage.x"] == 100.0
