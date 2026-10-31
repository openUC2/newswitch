"""Tests for the hooks of a multidimensional acquisition, by calling the routine directly."""

import pytest
from arkitekt import Task

from newswitch.microscope.parts import Microscope
from newswitch.models.acquisition import (
    AcquiredDataset,
    MultidimensionalAcquisition,
    Position,
    Stack,
    StreamIllumination,
    Streams,
    Timepoint,
)
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.hooks import SoftwareAutofocusHook, ZCalibrationHook
from newswitch.protocols import UnsupportedHook
from newswitch.protocols.dataset_store import AcquiredPosition
from newswitch.routines.multidimensional_acquisition import acquire_multidimensional_acquisition


def calibrated(microscope: Microscope) -> Microscope:
    """The reference microscope with one detector active and its light path calibrated."""
    assert microscope.detector is not None
    for detector in microscope.camera_state.detectors:
        if detector.slot != 1:
            microscope.detector.deactivate_detector(detector.slot)
    path = microscope.metadata.get_current_state_for_light_path(
        microscope.optics.get_light_path_for_detector(1)
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
            fov_width=10.0,
            fov_height=10.0,
        )
    )
    return microscope


def single_position(z: float, **hooks: list) -> MultidimensionalAcquisition:
    """One timepoint, one position at `z`, one plane, one stream; hooks as given."""
    p_hooks = hooks.pop("p_hooks", [])
    z_hooks = hooks.pop("z_hooks", [])
    stream = Streams(
        detectors=["1"],
        mapping="GFP",
        illuminations=[StreamIllumination(source="1", wavelength=488.0, intensity=0.8)],
    )
    stack = Stack(z_offset=0.0, z_slices=[0.0], z_step=1.0, channels=[stream], z_hooks=z_hooks)
    position = Position(x=0.0, y=0.0, z=z, stacks=[stack], p_hooks=p_hooks)
    return MultidimensionalAcquisition(timepoints=[Timepoint(positions=[position])], **hooks)


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


def run(built: Microscope, config: MultidimensionalAcquisition, store: Store | None = None) -> list:
    """Run the acquisition on the built microscope's managers."""
    return acquire_multidimensional_acquisition(
        config=config,
        store=store or Store(),
        task=Task.local(),
        optics_manager=built.optics,
        detector_manager=built.detector,
        stage_manager=built.stage,
        illumination_manager=built.illumination,
        illumination_state=built.illumination_state,
        calibration_state=built.calibration_state,
        metadata_manager=built.metadata,
        hook_manager=built.hooks,
    )


def test_a_position_hook_refocuses_before_the_stack(
    microscope: Microscope,
) -> None:
    """An autofocus per position refocuses there; the stack is taken at the focus found."""
    built = calibrated(microscope)
    built.illumination.turn_on(channel=1, intensity=100.0)

    datasets = run(
        built, single_position(5.0, p_hooks=[SoftwareAutofocusHook(z_range=12.0, steps=13)])
    )

    assert len(datasets) == 1
    assert abs(built.stage_state.z) <= 1.0


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
    start = (built.stage_state.x, built.stage_state.y, built.stage_state.z)
    store = Store()
    with pytest.raises(UnsupportedHook):
        run(built, single_position(5.0, **hooks), store)
    assert store.published == []
    assert (built.stage_state.x, built.stage_state.y, built.stage_state.z) == start
