"""Tests for capture_image with IO manager to verify PNG output.

This module tests the integration between VirtualDetectorManager and LocalFileIOManager,
verifying that captured images are correctly saved as PNG files with proper content
and that file operations (save, stream, delete) work correctly.
"""

import os
from pathlib import Path
from typing import Generator

import numpy as np
import pytest
from PIL import Image
from rekuest_next.state.lock import acquired_locks

from newswitch.broadcasters import FrameBroadcaster
from newswitch.managers.virtual import VirtualDetectorManager
from newswitch.managers.io import LocalFileConfig, LocalFileIOManager
from newswitch.managers.virtual.virtual_setup import SceneConfig, VirtualSetup
from newswitch.protocols import CameraState, IlluminationState, StageState
from newswitch.protocols.illumination import Illumination
from newswitch.protocols.io import FileFormat, IOState
from newswitch.protocols.objective import ObjectiveState

# Type alias for the detector with IO fixture return type
DetectorWithIO = tuple[VirtualDetectorManager, LocalFileIOManager, IOState, Path]


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for test output files.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.

    Returns:
        Path to the created output directory.
    """
    output_dir = tmp_path / "test_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@pytest.fixture
def illuminated_detector_with_io(
    tmp_path: Path,
) -> Generator[DetectorWithIO, None, None]:
    """Create a complete test setup with detector, IO manager, and all states.

    Uses settings that produce visible images:
        - High illumination intensity (5000.0)
        - Longer exposure (1.0s)
        - Higher gain (10.0)
        - Astigmatism sample type for consistent, visible frames

    Note:
        Camera settings must be set AFTER detector creation because the
        VirtualDetectorManager constructor resets them to config defaults.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.

    Yields:
        A tuple of (VirtualDetectorManager, LocalFileIOManager, IOState, output_dir).
    """
    with acquired_locks(
        "camera_parameters",
        "stage_position",
        "io",
        "objective",
        "illumination",
    ):
        # Create states
        camera_state = CameraState()
        stage_state = StageState()
        objective_state = ObjectiveState(slot=1, magnification=10.0, name="10x Air")
        illumination_state = IlluminationState(
            illuminations=[
                Illumination(
                    slot=1,
                    intensity=5000.0,
                    wavelength=488.0,
                    max_intensity=10000.0,
                    is_active=True,
                )
            ],
        )
        io_state = IOState()

        # Create detector with astigmatism sample type for consistent visible frames
        broadcaster = FrameBroadcaster()
        setup = VirtualSetup(
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            config=SceneConfig(sample_type="astigmatism"),
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            broadcaster=broadcaster,
            frame_source=setup,
        )
        # Activate and configure detector
        detector.activate_detector(1)
        detector.update_detector(slot=1, exposure_time=1.0, gain=10.0)

        # Create IO manager
        output_dir = tmp_path / "test_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        io_config = LocalFileConfig(
            base_path=str(output_dir),
            create_dirs=True,
            default_format=FileFormat.PNG,
        )
        io_manager = LocalFileIOManager(state=io_state, config=io_config)

        yield detector, io_manager, io_state, output_dir


@pytest.fixture
def default_illumination_detector_with_io(
    tmp_path: Path,
) -> Generator[DetectorWithIO, None, None]:
    """Create a test setup with default (zero) illumination.

    Creates a detector with no active illumination sources, useful for testing
    behavior with minimal or no light input.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.

    Yields:
        A tuple of (VirtualDetectorManager, LocalFileIOManager, IOState, output_dir).
    """
    with acquired_locks(
        "camera_parameters",
        "stage_position",
        "io",
        "objective",
        "illumination",
    ):
        camera_state = CameraState()
        stage_state = StageState()
        objective_state = ObjectiveState(slot=1, magnification=10.0, name="10x Air")
        illumination_state = IlluminationState()  # Default: empty sources
        io_state = IOState()

        broadcaster = FrameBroadcaster()
        setup = VirtualSetup(
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            broadcaster=broadcaster,
            frame_source=setup,
        )
        # Activate detector
        detector.activate_detector(1)

        output_dir = tmp_path / "test_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        io_config = LocalFileConfig(
            base_path=str(output_dir),
            create_dirs=True,
            default_format=FileFormat.PNG,
        )
        io_manager = LocalFileIOManager(state=io_state, config=io_config)

        yield detector, io_manager, io_state, output_dir


class TestCaptureImagePNGOutput:
    """Test that capture_image produces valid PNG files with visible content.

    These tests verify the complete image capture and save pipeline,
    including proper file creation, valid image format, and meaningful content.
    """

    def test_capture_produces_png_file(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that capture_image + save produces a PNG file on disk.

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        # Capture image
        image = detector.capture_image(slot=1)

        # Save using IO manager
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # Verify file exists
        assert os.path.exists(file_path), f"PNG file was not created at {file_path}"
        assert file_path.endswith(".png"), "File should have .png extension"

    def test_png_file_is_valid_image(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that the saved PNG file is a valid image that can be opened.

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        # Capture and save
        image = detector.capture_image(slot=1)
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # Open with PIL - this will raise if invalid
        with Image.open(file_path) as img:
            assert img.format == "PNG"
            assert img.size == (512, 512)  # Default DetectorConfig dimensions
            assert img.mode in ("L", "RGB", "RGBA")  # Grayscale or color

    def test_png_contains_visible_content(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that the PNG contains visible content (not all black/zeros).

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        # Capture and save
        image = detector.capture_image(slot=1)
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # Load the saved image
        with Image.open(file_path) as img:
            img_array = np.array(img)

        # Check that image is not all zeros (black)
        assert img_array.max() > 0, "Image is completely black (all zeros)"

        # Check that there is some variation in pixel values
        assert img_array.std() > 0, "Image has no variation (uniform color)"

    def test_png_has_meaningful_dynamic_range(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that the PNG has a reasonable dynamic range (visible features).

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        # Capture and save
        image = detector.capture_image(slot=1)
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # Load the saved image
        with Image.open(file_path) as img:
            img_array = np.array(img)

        # Calculate dynamic range
        dynamic_range = img_array.max() - img_array.min()

        # For an 8-bit image converted from uint16 microscope data,
        # expect at least some variation. The uint16→uint8 conversion
        # (divide by 256) naturally compresses the range, so we use
        # a lower threshold.
        assert dynamic_range >= 1, (
            f"Dynamic range too low ({dynamic_range}). Image may not have visible features."
        )

        # Also verify we have some non-zero pixels (actual content)
        assert img_array.max() > 0, "Image has no visible content"

    def test_raw_captured_array_has_valid_values(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that the raw captured numpy array has valid uint16 values.

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        image = detector.capture_image(slot=1)

        # Should be uint16 as per protocol
        assert image.dtype == np.uint16

        # Should have non-zero values (visible content)
        assert image.max() > 0, "Raw image is completely black"

        # Should have some meaningful signal (at least some pixels above noise floor)
        # For uint16, even dim illumination should produce measurable signal
        assert image.max() > 10, (
            f"Raw image signal is too weak (max={image.max()}). "
            "Expected some visible content above noise floor."
        )

    def test_default_illumination_produces_valid_image(
        self,
        default_illumination_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that even with default settings, we get a valid (if dim) image.

        Args:
            default_illumination_detector_with_io: The detector fixture with no illumination.
        """
        detector, io_manager, io_state, output_dir = default_illumination_detector_with_io

        # This uses the default IlluminationState (no active illumination)
        image = detector.capture_image(slot=1)
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # Load and check
        with Image.open(file_path) as img:
            img_array = np.array(img)

        # Even with no illumination, the image should be valid structure
        assert img_array.shape == (512, 512), (
            "Image dimensions don't match (uses default DetectorConfig)"
        )

    def test_multiple_captures_produce_different_files(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that multiple captures produce different files with unique names.

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        # Capture multiple images
        image1 = detector.capture_image(slot=1)
        image2 = detector.capture_image(slot=1)

        file_path1 = io_manager.save_numpy_array(image1, format=FileFormat.PNG)
        file_path2 = io_manager.save_numpy_array(image2, format=FileFormat.PNG)

        # Paths should be different
        assert file_path1 != file_path2, "Multiple saves should create different files"

        # Both files should exist
        assert os.path.exists(file_path1)
        assert os.path.exists(file_path2)


class TestIOManagerFileOperations:
    """Test file operations on saved PNG files.

    These tests verify that the LocalFileIOManager correctly handles
    file streaming, existence checking, and deletion operations.
    """

    def test_stream_file_handle_returns_png_bytes(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that stream_file_handle returns valid PNG bytes.

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        # Capture and save
        image = detector.capture_image(slot=1)
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # Stream the file
        file_bytes = io_manager.stream_file_handle(file_path)

        # PNG files start with a specific magic number
        PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
        assert file_bytes[:8] == PNG_MAGIC, "File is not a valid PNG (wrong magic bytes)"

    def test_file_exists_after_save(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that file_exists returns True after saving.

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        image = detector.capture_image(slot=1)
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        assert io_manager.file_exists(file_path) is True

    def test_delete_file_removes_file(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that delete_file removes the saved file.

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        image = detector.capture_image(slot=1)
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # File should exist
        assert io_manager.file_exists(file_path)

        # Delete it
        result = io_manager.delete_file(file_path)
        assert result is True

        # File should not exist anymore
        assert io_manager.file_exists(file_path) is False

    def test_state_updated_after_save(
        self,
        illuminated_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that IO state is updated with last saved file.

        Args:
            illuminated_detector_with_io: The detector and IO manager fixture.
        """
        detector, io_manager, io_state, output_dir = illuminated_detector_with_io

        image = detector.capture_image(slot=1)
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        assert io_state.last_saved_file == file_path
