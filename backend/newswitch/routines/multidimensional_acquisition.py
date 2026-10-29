"Routine for performing a multidimensional acquisition with multiple timepoints, positions, z-stacks, and channels."

import logging
from datetime import datetime
import random
from enum import Enum
from rekuest_next import progress
from rekuest_next import model
from newswitch import protocols
from newswitch.protocols.core import Frame
from newswitch.protocols.hook_manager import Hook
from rekuest_next.api.schema import ValidatorInput
from rekuest_next.scalars import ValidatorFunction
from rekuest_next.structures.model import model_field
import time
from rekuest_next import pausepoint

logger = logging.getLogger(__name__)


class PositionOrder(str, Enum):
    """Defines the order in which stage positions are visited during acquisition."""

    SEQUENTIAL = "sequential"
    RANDOM = "random"


@model
class Illumination:
    """Represents an illumination channel to acquire."""

    source: str  # Name of the illumination source (e.g., "LED1", "Laser2")
    wavelength: float  # Wavelength of the illumination in nm
    intensity: float  # Intensity of the illumination (0-1)


@model
class Streams:
    """Represents which channels to acquire at each position."""

    detector: str = model_field(
        description="Name or slot of the detector to use for this stream (e.g., 'Camera1' or '1')"
    )
    mapping: str = model_field(
        description="Mapping name for this stream (e.g., 'GFP', 'RFP') to be used in file naming and metadata"
    )
    # This is using a validator input, which will run on the frontend to ensure the user has entered at least one illumination with valid intensity before allowing them to start the acquisition
    illuminations: list[Illumination] = model_field(
        default_factory=list,
        validators=[
            ValidatorInput(
                function=ValidatorFunction.validate("(context) => context.self.length > 0"),
                errorMessage="We need at least one illumination channel to acquire this stream",
            )
        ],
        description="List of illuminations to use for this stream (e.g., [{'source': 'LED1', 'wavelength': 488, 'intensity': 0.8}])",
    )


@model
class Stack:
    """Represents a stack of images at different z-slices."""

    z_offset: float  # Offset from the current z position
    z_slices: list[float]  # List of z-slice positions
    z_step: float  # Step size between z-slices
    channels: list[Streams]  # List of channels to acquire at each z-slice
    z_hooks: list[Hook] = model_field(
        default_factory=list,
        description="List of hooks to execute at each z-slice (e.g., 'autofocus', 'z_calibration')",
    )  # List of hooks to execute at each z-slice (e.g., "autofocus", "z_calibration")


@model
class Position:
    """Represents a position in 3D space."""

    x: float
    y: float
    z: float
    stacks: list[Stack]
    p_hooks: list[Hook] = model_field(
        default_factory=list,
        description="List of hooks to execute at each position (e.g., 'autofocus', 'z_calibration')",
    )


@model
class Timepoint:
    """Represents a timepoint in a temporal sequence."""

    time: datetime | None = model_field(
        default=None,
        description="Absolute time to acquire this timepoint (e.g., '2024-01-01T12:00:00') or None to acquire immediately after the previous timepoint",
    )
    positions: list[Position] = model_field(
        default_factory=list,
        description="List of stage positions to acquire at this timepoint",
    )
    position_order: PositionOrder = model_field(
        default=PositionOrder.SEQUENTIAL,
        description="Order in which to visit stage positions (e.g., 'sequential', 'random')",
    )
    t_hooks: list[Hook] = model_field(
        default_factory=list,
        description="List of hooks to execute at each timepoint (e.g., 'autofocus', 'z_calibration')",
    )


@model
class MultidimensionalAcquisition:
    """Configuration for a multidimensional acquisition."""

    timepoints: list[Timepoint] = model_field(
        default_factory=list,
        description="List of timepoints to acquire, each with its own stage positions and hooks",
        validators=[
            ValidatorInput(
                function=ValidatorFunction.validate("(context) => context.self.length > 0"),
                errorMessage="You need at least one timepoint to perform an acquisition",
            )
        ],
    )
    file_name: str = model_field(
        default="acquisition",
        description="Base file name for acquired images (e.g., 'experiment1')",
    )
    file_format: str = model_field(
        default="TIFF",
        description="File format for saving acquired images (e.g., 'TIFF', 'PNG')",
    )
    m_hooks: list[Hook] = model_field(
        default_factory=list,
        description="List of hooks to execute at the start of the acquisition (e.g., 'autofocus', 'z_calibration')",
    )


def acquire_multidimensional_acquisition(
    config: MultidimensionalAcquisition,
    acquisition_manager: protocols.AcquistionManager,
    io_manager: protocols.IOManager,
    light_path_manager: protocols.LightPathManager,
    detector_manager: protocols.DetectorManager,
    stage_manager: protocols.StageManager,
    illumination_manager: protocols.IlluminationManager,
    expanse_manager: protocols.ExpanseManager,
    metadata_manager: protocols.MetadataManager,
    hook_manager: protocols.HookManager,
) -> list[Frame]:
    """Simulate the acquisition of a multidimensional dataset based on the provided configuration.

    Args:
        config (MultidimensionalAcquisition): Configuration for the acquisition.

    Returns:
        list[AcquiredImage]: List of acquired images with metadata.
    """
    acquired: list[Frame] = []
    logger.info("Starting acquisition with config: %s", config)

    hook_manager.execute_all(config.m_hooks or [])

    logger.info("Executing acquisition hooks: %s", config.m_hooks)

    # Calculate total number of images to acquire for progress tracking
    total_images = 0
    for timepoint in config.timepoints or []:
        for position in timepoint.positions or []:
            for stack in position.stacks or []:
                z_count = len(_resolve_z_positions(0, stack))
                channel_count = len(stack.channels or [])
                total_images += z_count * channel_count

    current_image = 0

    progress(0, message=f"Starting acquisition: {total_images} images to capture")

    for time_index, timepoint in enumerate(config.timepoints):
        if timepoint.time and timepoint.time > datetime.now():
            time.sleep((timepoint.time - datetime.now()).total_seconds())
        else:
            time.sleep(2)

        hook_manager.execute_all(timepoint.t_hooks or [])

        positions = list(timepoint.positions or [])
        if timepoint.position_order == PositionOrder.RANDOM:
            positions = random.sample(positions, k=len(positions))

        logger.info(
            "Acquiring timepoint %s with positions: %s and hooks: %s",
            time_index,
            positions,
            timepoint.t_hooks,
        )

        for position_index, position in enumerate(positions):
            hook_manager.execute_all(position.p_hooks or [])

            progress(
                int((current_image / total_images * 100)) if total_images > 0 else 0,
                message=f"T{time_index + 1}/{len(config.timepoints)} | Position {position_index + 1}/{len(positions)} | Moving to ({position.x:.1f}, {position.y:.1f}, {position.z:.1f})",
            )

            for stack in position.stacks or []:
                z_positions = _resolve_z_positions(position.z, stack)

                for z_index, z_pos in enumerate(z_positions):
                    stage_manager.move(
                        x=position.x,
                        y=position.y,
                        z=z_pos,
                        is_absolute=True,
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
                        pausepoint()
                        images = acquisition_manager.acquire()

                        acquired.extend(images)

                        # Update progress
                        progress(
                            int(((current_image) / total_images * 100)) if total_images > 0 else 0,
                            f"Acquired image {current_image}/{total_images} (T{time_index + 1}, P{position_index + 1}, Z{z_index + 1}, Stream{stream_index + 1})",
                        )

                        logger.debug("streaming acquired image data...")
                        for channel in channels_to_disable:
                            illumination_manager.turn_off_channel(channel)

    progress(100, message=f"Acquisition complete: {len(acquired)} images captured")
    return acquired


def _resolve_z_positions(base_z: float, stack: Stack) -> list[float]:
    if stack.z_slices:
        return [base_z + z for z in stack.z_slices]
    if stack.z_step and stack.z_offset:
        return [base_z + stack.z_offset]
    return [base_z]


def _resolve_illumination_channel(illumination: Illumination) -> int:
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
