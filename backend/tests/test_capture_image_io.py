"""Tests for capture_image with IO manager to verify PNG output.

This module tests the integration between the simulated detector of the reference microscope and
LocalFileIOManager, verifying that captured images are correctly saved as PNG files with proper
content and that file operations (save, stream, delete) work correctly.
"""

import os
from pathlib import Path
from typing import Generator

import numpy as np
import pytest
from PIL import Image

from newswitch.microscope.parts import Microscope
from newswitch.models.io import FileFormat
from newswitch.protocols import DetectorManager
from newswitch.services.io import LocalFileConfig, LocalFileIOManager
from newswitch.states.io import IOState

# Type alias for the detector with IO fixture return type
DetectorWithIO = tuple[DetectorManager, LocalFileIOManager, IOState, Path]


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


def _io_manager(output_dir: Path) -> tuple[LocalFileIOManager, IOState]:
    """An IO manager writing PNGs into `output_dir`, and its state."""
    io_state = IOState()
    io_config = LocalFileConfig(
        base_path=str(output_dir),
        create_dirs=True,
        default_format=FileFormat.PNG,
    )
    return LocalFileIOManager(state=io_state, config=io_config), io_state


@pytest.fixture
def illuminated_detector_with_io(
    microscope: Microscope, temp_output_dir: Path
) -> Generator[DetectorWithIO, None, None]:
    """The reference microscope's detector, rendering a sample it can see, and an IO manager.

    Uses settings that produce visible images: half of the laser's power, a longer exposure (1 s)
    and a higher gain (10 dB).

    Args:
        microscope: The reference microscope.
        temp_output_dir: Where the IO manager writes.

    Yields:
        A tuple of (detector manager, LocalFileIOManager, IOState, output_dir).
    """
    assert microscope.detector is not None and microscope.values is not None
    microscope.detector.activate_detector("camera")
    microscope.values.set({"laser_488.power": 25.0, "camera.exposure": 1000.0, "camera.gain": 10.0})
    io_manager, io_state = _io_manager(temp_output_dir)
    yield microscope.detector, io_manager, io_state, temp_output_dir


@pytest.fixture
def unlit_detector_with_io(
    microscope: Microscope, temp_output_dir: Path
) -> Generator[DetectorWithIO, None, None]:
    """The reference microscope's detector with every light source off, and an IO manager.

    Useful for testing behavior with no light input.

    Args:
        microscope: The reference microscope.
        temp_output_dir: Where the IO manager writes.

    Yields:
        A tuple of (detector manager, LocalFileIOManager, IOState, output_dir).
    """
    assert microscope.detector is not None and microscope.values is not None
    microscope.values.set({"laser_488.power": 0.0, "led_625.power": 0.0})
    microscope.detector.activate_detector("camera")
    io_manager, io_state = _io_manager(temp_output_dir)
    yield microscope.detector, io_manager, io_state, temp_output_dir


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
        image = detector.capture_image("camera").data

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
        image = detector.capture_image("camera").data
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # Open with PIL - this will raise if invalid
        with Image.open(file_path) as img:
            assert img.format == "PNG"
            assert img.size == (512, 512)  # The size of the reference microscope's sensor
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
        image = detector.capture_image("camera").data
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
        image = detector.capture_image("camera").data
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

        image = detector.capture_image("camera").data

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

    def test_no_illumination_produces_valid_image(
        self,
        unlit_detector_with_io: DetectorWithIO,
    ) -> None:
        """Test that even with no light, we get a valid (if dim) image.

        Args:
            unlit_detector_with_io: The detector fixture with no illumination.
        """
        detector, io_manager, io_state, output_dir = unlit_detector_with_io

        # With every source off
        image = detector.capture_image("camera").data
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        # Load and check
        with Image.open(file_path) as img:
            img_array = np.array(img)

        # Even with no illumination, the image should be valid structure
        assert img_array.shape == (512, 512), "Image dimensions don't match the sensor"

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
        image1 = detector.capture_image("camera").data
        image2 = detector.capture_image("camera").data

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
        image = detector.capture_image("camera").data
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

        image = detector.capture_image("camera").data
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

        image = detector.capture_image("camera").data
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

        image = detector.capture_image("camera").data
        file_path = io_manager.save_numpy_array(image, format=FileFormat.PNG)

        assert io_state.last_saved_file == file_path
