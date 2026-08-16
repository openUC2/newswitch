"""Tests for the multidimensional acquisition routine with a small timeseries.

This module tests the multidimensional acquisition routine to verify proper
image capture across multiple timepoints by calling the function directly.
"""

from pathlib import Path
from typing import Any, Generator, cast

import pytest
from rekuest_next.state.lock import acquired_locks

from newswitch.broadcasters import FrameBroadcaster
from newswitch.managers.acquistion_manager import AcquistionManager
from newswitch.managers.cache.local_cache import LocalCacheConfig, LocalCacheManager
from newswitch.managers.calibration import CalibrationManager
from newswitch.managers.expanse_manager import ExpanseManager
from newswitch.managers.light_path import LightPathManager
from newswitch.managers.virtual import (
    VirtualDetectorManager,
    VirtualLEDManager,
    VirtualStageManager,
    VirtualFilterBankManager,
    VirtualObjectiveManager,
)
from newswitch.managers.io import LocalFileConfig, LocalFileIOManager
from newswitch.managers.metadata_manager import MetadataManager
from newswitch.managers.python_hook_manager import PythonHookManager
from newswitch.managers.virtual.virtual_detector import DetectorConfig
from newswitch.managers.virtual.virtual_setup import SceneConfig, VirtualSetup
from newswitch.protocols import (
    CameraState,
    CalibrationState,
    ExpanseState,
    FilterBankState,
    HookContext,
    IOState,
    IlluminationState,
    LightPathState,
    StageState,
)
from newswitch.protocols.calibration import CalibratedLightPath
from newswitch.protocols.illumination import Illumination as IlluminationProto
from newswitch.protocols.objective import ObjectiveState
from newswitch.routines.multidimensional_acquisition import (
    MultidimensionalAcquisition,
    Timepoint,
    Position,
    Stack,
    Streams,
    Illumination,
    acquire_multidimensional_acquisition,
)


@pytest.fixture
def acquisition_setup(
    tmp_path: Path,
) -> Generator[
    tuple[
        VirtualDetectorManager,
        VirtualStageManager,
        VirtualLEDManager,
        LocalFileIOManager,
        PythonHookManager,
        AcquistionManager,
        LightPathManager,
        ExpanseManager,
        MetadataManager,
    ],
    None,
    None,
]:
    """Create a complete test setup for multidimensional acquisition.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.

    Yields:
        A tuple of managers needed for acquisition testing.
    """
    with acquired_locks(
        "camera_parameters",
        "stage_position",
        "io",
        "expanse_state",
        "filter_bank",
        "objective",
        "illumination",
    ):
        # Create states
        camera_state = CameraState()
        stage_state = StageState()
        stage_state.x = 0.0
        stage_state.y = 0.0
        stage_state.z = 0.0
        stage_state.a = 0.0
        objective_state = ObjectiveState(slot=1, magnification=10.0, name="10x Air")
        illumination_state = IlluminationState(
            illuminations=[
                IlluminationProto(
                    slot=1,
                    intensity=1000.0,
                    wavelength=488.0,
                    max_intensity=10000.0,
                    is_active=False,
                )
            ],
        )
        io_state = IOState()
        filter_bank_state = FilterBankState()
        broadcaster = FrameBroadcaster()

        # Create managers
        setup = VirtualSetup(
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            config=SceneConfig(sample_type="cells"),
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            broadcaster=broadcaster,
            frame_source=setup,
            config=DetectorConfig(width=256, height=256),
        )
        detector.deactivate_detector(2)
        detector.deactivate_detector(3)

        stage = VirtualStageManager(
            stage=stage_state,
        )

        led = VirtualLEDManager(
            illumination_state=illumination_state,
        )
        # Constructed for its side effect: __init__ populates `filter_bank_state` with the
        # default filters and activates the default slot, which the light path and metadata
        # managers below depend on. The manager itself is not otherwise used by the tests.
        _filter_bank = VirtualFilterBankManager(filter_bank_state=filter_bank_state)

        objective = VirtualObjectiveManager(
            objective_state=objective_state,
        )

        io_manager = LocalFileIOManager(
            state=io_state,
            config=LocalFileConfig(base_path=str(tmp_path)),
        )

        hook_manager = PythonHookManager(
            context=HookContext(
                stage_manager=stage,
                detector_manager=detector,
                illumination_manager=led,
                objective_manager=objective,
                io_manager=io_manager,
            )
        )

        expanse_manager = ExpanseManager(expanse=ExpanseState())
        calibration_manager = CalibrationManager(calibration_state=CalibrationState())
        light_path_manager = LightPathManager(
            light_path_state=LightPathState(),
            objective_state=objective_state,
            illumination_state=illumination_state,
            camera_state=camera_state,
            filter_bank_state=filter_bank_state,
        )
        light_path_manager.calculate_possible_light_paths()

        metadata_manager = MetadataManager(
            objective_state=objective_state,
            stage_state=stage_state,
            filter_bank_state=filter_bank_state,
            illumination_state=illumination_state,
            camera_state=camera_state,
            calibration_state=calibration_manager.state,
        )

        current_light_path_state = metadata_manager.get_current_state_for_light_path(
            light_path_manager.get_light_path_for_detector(1)
        )
        calibration_manager.set_calibrated_state(
            CalibratedLightPath(
                light_path_state_hash=current_light_path_state.hash,
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

        acquisition_manager = AcquistionManager(
            expanse_manager=expanse_manager,
            detector_manager=detector,
            metadata_manager=metadata_manager,
            light_path_manager=light_path_manager,
            cache_manager=cast(
                Any,
                LocalCacheManager(config=LocalCacheConfig(base_path=str(tmp_path / "cache"))),
            ),
        )

        yield (
            detector,
            stage,
            led,
            io_manager,
            hook_manager,
            acquisition_manager,
            light_path_manager,
            expanse_manager,
            metadata_manager,
        )


def test_small_timeseries_acquisition(
    acquisition_setup: tuple[
        VirtualDetectorManager,
        VirtualStageManager,
        VirtualLEDManager,
        LocalFileIOManager,
        PythonHookManager,
        AcquistionManager,
        LightPathManager,
        ExpanseManager,
        MetadataManager,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test multidimensional acquisition side effects with the current manager stack.

    The current implementation records captured data on the expanse state rather than
    returning populated `Image` objects from `acquire_multidimensional_acquisition()`.
    This test exercises the full manager wiring and verifies the persisted frames.
    """
    (
        detector,
        stage,
        led,
        io_manager,
        hook_manager,
        acquisition_manager,
        light_path_manager,
        expanse_manager,
        metadata_manager,
    ) = acquisition_setup

    def _no_sleep(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("newswitch.routines.multidimensional_acquisition.time.sleep", _no_sleep)

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
                                            Illumination(
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
                                            Illumination(
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
                                            Illumination(
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
        acquisition_manager=acquisition_manager,
        io_manager=io_manager,
        light_path_manager=light_path_manager,
        detector_manager=detector,
        stage_manager=stage,
        illumination_manager=led,
        expanse_manager=expanse_manager,
        metadata_manager=metadata_manager,
        hook_manager=hook_manager,
    )

    assert len(acquired_frames) == 3, (
        "Expected acquire_multidimensional_acquisition to return an empty list due to current implementation"
    )

    captured_frames = expanse_manager.state.current_frames
    assert len(captured_frames) == 3, f"Expected 3 frames, got {len(captured_frames)}"

    for i, frame in enumerate(captured_frames):
        assert frame.id, f"Frame {i} is missing a cache id"
        assert frame.array_metadata.max_value >= frame.array_metadata.min_value
        assert frame.metadata.fov_width > 0
        assert frame.metadata.fov_height > 0
