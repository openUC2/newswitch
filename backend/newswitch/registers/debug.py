"""Test and demo actions: progress, failures, locks. Importing this module registers them.

They drive no hardware; they exercise the agent (progress and pause points, a failing
action that must release its locks, a critical failure, a function that never ends).
"""

import koil
from rekuest_next import pausepoint, progress
from rekuest_next.register import register

from newswitch import protocols
from newswitch.protocols import (
    CameraState,
    FilterBankState,
    IlluminationState,
    ObjectiveState,
    StageManager,
    StageState,
)


@register
def long_stuff_running() -> None:
    """A long-running function to test optimistic updates and progress."""

    for i in range(10):
        progress(i * 10, f"Long task progress: {i * 10}%")
        pausepoint()  # Await for a breakpoint to allow for testing of progress updates
        koil.sleep(0.5)


# Here we use the locks explicitly, when setting them like this we are ourselves responsible
# for ensuring that the locks are properly set for this execution context
@register(locks=["stage_position"])
def failing_camera(camera: CameraState, intensity: int) -> str:
    """A function that always fails to test lock release."""
    camera.detectors[0].current_gain += intensity  # type: igThis is just to have some side effect that we can check in the test, but the function will still fail
    return "This function should fail."


@register(
    description="Move the stage to a specified position with a long execution time to test optimistic updates."
)
def kill_benedict(stage: StageManager, kill_hard: str, die_young: bool) -> None:
    """A function that simulates a critical failure to test error handling and lock release."""
    raise RuntimeError("Benedict has been killed. This is a simulated critical failure.")


@register
def dump_states_to_stdin(
    stage_state: StageState,
    illumination_state: IlluminationState,
    camera_state: CameraState,
    objective_state: ObjectiveState,
    filter_bank_state: FilterBankState,
    expanse_state: protocols.ExpanseState,
) -> None:
    """Dump the current states of all managers for debugging purposes."""
    print("Dumping states to JSON:")
    print(len(expanse_state.current_frames))


@register
def never_ending_function() -> None:
    """A function that never ends to test how the system handles long-running functions."""
    pass
