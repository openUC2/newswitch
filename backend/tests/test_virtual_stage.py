"""Tests for the VirtualStageManager using protocol-based testing.

This module tests the VirtualStageManager implementation to ensure it correctly
implements the StageManager protocol, including absolute and relative movement,
and homing functionality.
"""

from typing import Generator

import pytest

from newswitch.managers.virtual import VirtualStageManager
from newswitch.protocols import StageState


@pytest.fixture
def virtual_stage_manager() -> Generator[VirtualStageManager, None, None]:
    """Create a VirtualStageManager instance for testing.

    Creates a stage manager with state initialized at the origin (0, 0, 0, 0).
    States are plain until an agent adopts them, so tests write them freely.

    Yields:
        VirtualStageManager: A configured stage manager ready for testing.
    """
    stage_state = StageState(x=0.0, y=0.0, z=0.0, a=0.0)
    manager = VirtualStageManager(stage=stage_state)
    yield manager


def test_stage_protocol_compliance(virtual_stage_manager: VirtualStageManager) -> None:
    """Test that VirtualStageManager implements the StageManager protocol correctly.

    Verifies:
        - Absolute movement updates stage position correctly.
        - Relative movement adds to current position.
        - move_home() resets all axes to origin.

    Args:
        virtual_stage_manager: The stage manager fixture to test.
    """
    # Test move method
    stage = virtual_stage_manager
    stage_state = stage.state
    stage.move(x=10.0, y=20.0, z=5.0, is_absolute=True)

    # Verify state was updated
    stage_state.is_roughly_equal(x=10.0, y=20.0, z=5.0, raise_on_mismatch=True)

    # Test relative move
    stage.move(x=5.0, is_absolute=False)
    stage_state.is_roughly_equal(x=15.0, raise_on_mismatch=True)  # 10 + 5

    # Test move_home
    stage.move_home()
    stage_state.is_roughly_equal(x=0.0, y=0.0, z=0.0, a=0.0, raise_on_mismatch=True)
