"Routine for performing a multidimensional acquisition with multiple timepoints, positions, z-stacks, and channels."

import logging
import random
import time
from datetime import datetime

from arkitekt import Task

from newswitch import protocols
from newswitch.models.acquisition import (
    MultidimensionalAcquisition,
    PositionOrder,
    Stack,
    StreamIllumination,
)
from newswitch.models.frames import Frame
from newswitch.routines.common import acquire_step

logger = logging.getLogger(__name__)


def acquire_multidimensional_acquisition(
    config: MultidimensionalAcquisition,
    acquisition_manager: protocols.AcquisitionManager,
    io_manager: protocols.IOManager,
    light_path_manager: protocols.LightPathManager,
    detector_manager: protocols.DetectorManager,
    stage_manager: protocols.StageManager,
    illumination_manager: protocols.IlluminationManager,
    expanse_manager: protocols.ExpanseManager,
    metadata_manager: protocols.MetadataManager,
    hook_manager: protocols.HookManager,
    task: Task,
) -> list[Frame]:
    """Acquire a multidimensional dataset: timepoints x positions x z stacks x channels.

    Per timepoint the stage visits each position, then each plane of its stacks, and every
    stream's detector acquires a frame there; hooks (`m_hooks`, `t_hooks`, `p_hooks`,
    `z_hooks`) run at the start, per timepoint, per position and per plane.

    Returns:
        The frames, in the order acquired.
    """
    acquired: list[Frame] = []

    # Every hook must be able to run where it is asked for, before anything moves
    hook_manager.check(config.m_hooks or [], "m")
    for timepoint in config.timepoints or []:
        hook_manager.check(timepoint.t_hooks or [], "t")
        for position in timepoint.positions or []:
            hook_manager.check(position.p_hooks or [], "p")
            for stack in position.stacks or []:
                hook_manager.check(stack.z_hooks or [], "z")

    hook_manager.execute_all(config.m_hooks or [])

    # Calculate total number of images to acquire for progress tracking
    total_images = 0
    for timepoint in config.timepoints or []:
        for position in timepoint.positions or []:
            for stack in position.stacks or []:
                z_count = len(_resolve_z_positions(0, stack))
                channel_count = len(stack.channels or [])
                total_images += z_count * channel_count

    current_image = 0

    task.progress(0, message=f"Starting acquisition: {total_images} images to capture")

    for time_index, timepoint in enumerate(config.timepoints):
        if timepoint.time and timepoint.time > datetime.now():
            time.sleep((timepoint.time - datetime.now()).total_seconds())

        hook_manager.execute_all(timepoint.t_hooks or [])

        positions = list(timepoint.positions or [])
        if timepoint.position_order == PositionOrder.RANDOM:
            positions = random.sample(positions, k=len(positions))

        logger.info("Timepoint %d: %d positions", time_index, len(positions))

        for position_index, position in enumerate(positions):
            task.progress(
                int((current_image / total_images * 100)) if total_images > 0 else 0,
                message=f"T{time_index + 1}/{len(config.timepoints)} | Position {position_index + 1}/{len(positions)} | Moving to ({position.x:.1f}, {position.y:.1f}, {position.z:.1f})",
            )
            stage_manager.move(
                x=position.x, y=position.y, z=position.z, is_absolute=True, task=task
            )
            # Position hooks run there (an autofocus may refocus); the stacks are centred
            # on where the stage is afterwards.
            hook_manager.execute_all(position.p_hooks or [])
            base_z = stage_manager.state.z

            for stack in position.stacks or []:
                z_positions = _resolve_z_positions(base_z, stack)

                for z_index, z_pos in enumerate(z_positions):
                    stage_manager.move(
                        x=position.x,
                        y=position.y,
                        z=z_pos,
                        is_absolute=True,
                        task=task,
                    )

                    hook_manager.execute_all(stack.z_hooks or [])

                    for stream_index, stream in enumerate(stack.channels or []):
                        channels_to_disable: list[int] = []

                        for illumination in stream.illuminations or []:
                            channel = _resolve_illumination_channel(illumination)
                            # turn_on activates the channel and sets intensity
                            illumination_manager.turn_on(
                                channel=channel,
                                intensity=illumination.intensity,
                            )
                            channels_to_disable.append(channel)

                        slot = _resolve_detector_slot(stream.detector, detector_manager)
                        detector_state = detector_manager.get_detector_state(slot)
                        if detector_state is None or not detector_state.is_active:
                            detector_manager.activate_detector(slot)

                        current_image += 1
                        acquired.extend(
                            acquire_step(
                                acquisition_manager,
                                task,
                                current_image,
                                total_images,
                                f"Acquired image {current_image}/{total_images} (T{time_index + 1}, P{position_index + 1}, Z{z_index + 1}, Stream{stream_index + 1})",
                                slots=[slot],
                            )
                        )

                        for channel in channels_to_disable:
                            illumination_manager.turn_off_channel(channel)

    task.progress(100, message=f"Acquisition complete: {len(acquired)} images captured")
    return acquired


def _resolve_z_positions(base_z: float, stack: Stack) -> list[float]:
    if stack.z_slices:
        return [base_z + z for z in stack.z_slices]
    if stack.z_step and stack.z_offset:
        return [base_z + stack.z_offset]
    return [base_z]


def _resolve_illumination_channel(illumination: StreamIllumination) -> int:
    digits = "".join(ch for ch in illumination.source if ch.isdigit())
    if digits:
        return int(digits)
    return 1


def _resolve_detector_slot(detector: str, detector_manager: protocols.DetectorManager) -> int:
    if detector.isdigit():
        return int(detector)

    for available in detector_manager.list_available_detectors():
        if available.name == detector:
            return available.slot
    return 1
