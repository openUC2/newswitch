"""Tests for the hooks of a multidimensional acquisition, by calling the routine directly."""

import pytest
from arkitekt import Task

from newswitch.microscope.parts import Microscope
from newswitch.models.acquisition import AcquiredDataset, AcquisitionChannel, AcquisitionPlan
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.hooks import SoftwareAutofocusHook, ZCalibrationHook
from newswitch.protocols import UnsupportedHook
from newswitch.protocols.dataset_store import AcquiredPosition
from newswitch.routines.acquire import acquire
from tests.conftest import acquisition


def calibrated(microscope: Microscope) -> Microscope:
    """The reference microscope with one detector active and its light path calibrated."""
    assert microscope.detector is not None
    for detector in microscope.detector_state.detectors:
        if detector.name != "camera":
            microscope.detector.deactivate_detector(detector.name)
    path = microscope.metadata.get_current_state_for_light_path(
        microscope.optics.get_light_path_for_detector("camera")
    )
    microscope.calibration.set_calibrated_state(
        CalibratedLightPath(
            key=path.key,
            affine_matrix=[
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
        )
    )
    return microscope


def single_position(z: float, **hooks: list) -> AcquisitionPlan:
    """One time, one position at `z`, one plane, one channel; hooks as given."""
    channel = AcquisitionChannel(detectors=["camera"], name="GFP", set_to={"laser_488.power": 25.0})
    return acquisition([channel], z=z, **hooks)


class Store:
    """Keeps what it is given."""

    def __init__(self) -> None:
        """Nothing yet."""
        self.published: list[AcquiredPosition] = []

    def check(self) -> None:
        """Always there."""

    def state(self) -> dict:
        """Nothing of interest here."""
        return {}

    def publish(self, acquired: AcquiredPosition) -> AcquiredDataset:
        """Keep it."""
        self.published.append(acquired)
        return AcquiredDataset(id="1", name=acquired.name, position=acquired.position)


def run(built: Microscope, config: AcquisitionPlan, store: Store | None = None) -> list:
    """Run the acquisition on the built microscope's managers."""
    return acquire(
        plan=config,
        store=store or Store(),
        task=Task.local(),
        optics_manager=built.optics,
        detector_manager=built.detector,
        values=built.values,
        space=built.space,
        hook_manager=built.hooks,
    )


def test_a_position_hook_refocuses_before_the_stack(
    microscope: Microscope,
) -> None:
    """An autofocus per position refocuses there; the stack is taken at the focus found."""
    built = calibrated(microscope)
    built.values.set({"laser_488.power": 50.0})

    datasets = run(
        built, single_position(5.0, p_hooks=[SoftwareAutofocusHook(z_range=12.0, steps=13)])
    )

    assert len(datasets) == 1
    assert abs(built.values["stage.z"]) <= 1.0


@pytest.mark.parametrize(
    "hooks",
    [
        {"z_hooks": [SoftwareAutofocusHook()]},  # would move the stack it is part of
        {"p_hooks": [ZCalibrationHook()]},  # no handler on this microscope
    ],
)
def test_hooks_that_cannot_run_are_refused_before_anything_moves(
    microscope: Microscope, hooks: dict
) -> None:
    """The acquisition refuses them up front: no frame is taken, the stage stays put."""
    built = calibrated(microscope)
    start = (built.values["stage.x"], built.values["stage.y"], built.values["stage.z"])
    store = Store()
    with pytest.raises(UnsupportedHook):
        run(built, single_position(5.0, **hooks), store)
    assert store.published == []
    assert (built.values["stage.x"], built.values["stage.y"], built.values["stage.z"]) == start
