"""Unit tests for the software autofocus routine against the virtual microscope."""

import numpy as np
import pytest
from rekuest_next.state.lock import acquired_locks

from newswitch.broadcasters import FrameBroadcaster
from newswitch.managers.virtual import VirtualStageManager
from newswitch.managers.virtual.virtual_detector import VirtualDetectorManager
from newswitch.managers.virtual.virtual_stage import StageConfig
from newswitch.protocols import (
    CameraState,
    FilterBankState,
    IlluminationState,
    ObjectiveState,
    StageState,
)
from newswitch.routines.autofocus import autofocus_sweep, compute_focus_metric


def test_compute_focus_metric_prefers_sharp_images() -> None:
    """A sharp checkerboard scores higher than its blurred version."""
    from scipy import ndimage

    rng = np.random.default_rng(42)
    sharp = (rng.random((64, 64)) > 0.5).astype(np.float32) * 255
    blurred = ndimage.gaussian_filter(sharp, sigma=3.0)

    assert compute_focus_metric(sharp) > compute_focus_metric(blurred)
    assert compute_focus_metric(sharp, "intensity_variance") > compute_focus_metric(
        blurred, "intensity_variance"
    )
    with pytest.raises(ValueError):
        compute_focus_metric(sharp, "no_such_metric")


def test_autofocus_sweep_finds_focus_on_virtual_microscope() -> None:
    """The sweep finds the virtual detector's focal plane (z=0) from a defocused start.

    The virtual detector blurs frames with sigma = 1 + |z| * 0.1, so the
    sharpest plane in any symmetric sweep is the one closest to z = 0.
    """
    with acquired_locks(
        "stage_position", "illumination", "filter_bank", "objective", "camera_parameters"
    ):
        stage_state = StageState(z=6.0)
        illumination_state = IlluminationState()
        camera_state = CameraState()
        objective_state = ObjectiveState()
        filter_bank_state = FilterBankState()

        stage = VirtualStageManager(
            stage=stage_state,
            config=StageConfig(simulated_pos_sleep_per_micrometer=0.0),
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            stage_state=stage_state,
            illumination_state=illumination_state,
            broadcaster=FrameBroadcaster(),
            objective_state=objective_state,
            filter_bank_state=filter_bank_state,
        )
        detector.activate_detector(slot=1)

        # 13 planes from -6..+6 um around z=6-6=0-centered grid
        z_positions = [-6.0 + index * 1.0 for index in range(13)]
        best_z, metrics = autofocus_sweep(stage, detector, z_positions, detector_slot=1)

        assert len(metrics) == len(z_positions)
        # Best plane must be within one grid step of the true focus at z=0.
        assert abs(best_z) <= 1.0
        # And the stage is parked where the sweep ended; the routine moves it
        # to best_z afterwards (covered by the agent-level test).
