"""Tests for the multidimensional acquisition routine with a small timeseries.

This module tests the multidimensional acquisition routine to verify proper
image capture across multiple timepoints by calling the function directly.
"""

import pytest
from arkitekt import Task

from newswitch.microscope.parts import Microscope
from newswitch.models.acquisition import (
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
from newswitch.routines.multidimensional_acquisition import acquire_multidimensional_acquisition


def calibrated(microscope: Microscope) -> Microscope:
    """The reference microscope with one detector active and its light path calibrated."""
    assert microscope.detector is not None
    for detector in microscope.camera_state.detectors:
        if detector.slot != 1:
            microscope.detector.deactivate_detector(detector.slot)
    path = microscope.metadata.get_current_state_for_light_path(
        microscope.light_path.get_light_path_for_detector(1)
    )
    microscope.calibration.set_calibrated_state(
        CalibratedLightPath(
            light_path_state_hash=path.hash,
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


def test_small_timeseries_acquisition(
    microscope: Microscope,
) -> None:
    """Test multidimensional acquisition side effects with the current manager stack.

    The current implementation records captured data on the expanse state rather than
    returning populated `Image` objects from `acquire_multidimensional_acquisition()`.
    This test exercises the full manager wiring and verifies the persisted frames.
    """
    built = calibrated(microscope)
    assert built.detector and built.stage and built.illumination and built.acquisition

    # Create a simple timeseries acquisition config
    # 3 timepoints, 1 position each, 1 z-slice, 1 channel (GFP)
    config = MultidimensionalAcquisition(
        timepoints=[
            Timepoint(
                positions=[
                    Position(
                        x=0.0,
                        y=0.0,
                        z=0.0,
                        stacks=[
                            Stack(
                                z_offset=0.0,
                                z_slices=[0.0],
                                z_step=1.0,
                                channels=[
                                    Streams(
                                        detector="1",
                                        mapping="GFP",
                                        illuminations=[
                                            StreamIllumination(
                                                source="LED1",
                                                wavelength=488.0,
                                                intensity=0.8,
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            ),
            Timepoint(
                positions=[
                    Position(
                        x=10.0,
                        y=10.0,
                        z=0.0,
                        stacks=[
                            Stack(
                                z_offset=0.0,
                                z_slices=[0.0],
                                z_step=1.0,
                                channels=[
                                    Streams(
                                        detector="1",
                                        mapping="GFP",
                                        illuminations=[
                                            StreamIllumination(
                                                source="LED1",
                                                wavelength=488.0,
                                                intensity=0.8,
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            ),
            Timepoint(
                positions=[
                    Position(
                        x=20.0,
                        y=20.0,
                        z=0.0,
                        stacks=[
                            Stack(
                                z_offset=0.0,
                                z_slices=[0.0],
                                z_step=1.0,
                                channels=[
                                    Streams(
                                        detector="1",
                                        mapping="GFP",
                                        illuminations=[
                                            StreamIllumination(
                                                source="LED1",
                                                wavelength=488.0,
                                                intensity=0.8,
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            ),
        ],
        file_name="timeseries_test",
        file_format="TIFF",
    )

    # Run the acquisition directly
    acquired_frames = acquire_multidimensional_acquisition(
        config=config,
        task=Task.local(),
        acquisition_manager=built.acquisition,
        io_manager=built.io,
        light_path_manager=built.light_path,
        detector_manager=built.detector,
        stage_manager=built.stage,
        illumination_manager=built.illumination,
        expanse_manager=built.expanse,
        metadata_manager=built.metadata,
        hook_manager=built.hooks,
    )

    assert len(acquired_frames) == 3, (
        "Expected acquire_multidimensional_acquisition to return an empty list due to current implementation"
    )

    captured_frames = built.expanse_state.current_frames
    assert len(captured_frames) == 3, f"Expected 3 frames, got {len(captured_frames)}"

    for i, frame in enumerate(captured_frames):
        assert frame.id, f"Frame {i} is missing a cache id"
        assert frame.array_metadata.max_value >= frame.array_metadata.min_value
        assert frame.metadata.fov_width > 0
        assert frame.metadata.fov_height > 0


def single_position(z: float, **hooks: list) -> MultidimensionalAcquisition:
    """One timepoint, one position at `z`, one plane, one stream; hooks as given."""
    p_hooks = hooks.pop("p_hooks", [])
    z_hooks = hooks.pop("z_hooks", [])
    stream = Streams(
        detector="1",
        mapping="GFP",
        illuminations=[StreamIllumination(source="LED1", wavelength=488.0, intensity=0.8)],
    )
    stack = Stack(z_offset=0.0, z_slices=[0.0], z_step=1.0, channels=[stream], z_hooks=z_hooks)
    position = Position(x=0.0, y=0.0, z=z, stacks=[stack], p_hooks=p_hooks)
    return MultidimensionalAcquisition(timepoints=[Timepoint(positions=[position])], **hooks)


def run(built: Microscope, config: MultidimensionalAcquisition) -> list:
    """Run the acquisition on the built microscope's managers."""
    return acquire_multidimensional_acquisition(
        config=config,
        task=Task.local(),
        acquisition_manager=built.acquisition,
        io_manager=built.io,
        light_path_manager=built.light_path,
        detector_manager=built.detector,
        stage_manager=built.stage,
        illumination_manager=built.illumination,
        expanse_manager=built.expanse,
        metadata_manager=built.metadata,
        hook_manager=built.hooks,
    )


def test_a_position_hook_refocuses_before_the_stack(
    microscope: Microscope,
) -> None:
    """An autofocus per position refocuses there; the stack is taken at the focus found."""
    built = calibrated(microscope)
    built.detector.config.focal_plane_z = 50.0

    frames = run(
        built, single_position(55.0, p_hooks=[SoftwareAutofocusHook(z_range=12.0, steps=13)])
    )

    assert len(frames) == 1
    assert abs(built.stage_state.z - 50.0) <= 1.0


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
    with pytest.raises(UnsupportedHook):
        run(built, single_position(5.0, **hooks))
    assert built.expanse_state.current_frames == []
    assert (built.stage_state.x, built.stage_state.y, built.stage_state.z) == start
