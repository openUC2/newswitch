"""Tests for choosing the detector manager (`build_detector_manager`) and closing cameras.

Cameras through uc2_cam_py are used on real hardware only, when the device configuration
maps a detector to a camera controller. The test with a real (simulated) uc2_cam_py camera
is skipped without the extra "camera".
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from rekuest_next.state.lock import acquired_locks

import newswitch.app as app_module
from newswitch.app import ImswitchConfig, build_detector_manager
from newswitch.broadcasters import FrameBroadcaster
from newswitch.config_io import NewswitchConfig, load_config
from newswitch.managers.virtual import VirtualDetectorManager
from newswitch.protocols import (
    CameraManager,
    CameraState,
    DetectorManager,
    FilterBankState,
    IlluminationState,
    ObjectiveState,
    StageState,
)

#: One small simulated uc2_cam_py camera behind a USB3 Vision controller.
CAMERA_DOC: dict[str, Any] = {
    "newswitch_version": "v1.0.2",
    "devices": {
        "cam-sdk": {
            "type": "controller",
            "connection": {"protocol": "usb3-vision"},
            "mapping": {
                "cam": {
                    "type": "usb3-vision-camera",
                    "id": 0,
                    "store_image_data": False,
                    "vendor_options": {"sensor_width": 64, "sensor_height": 48},
                }
            },
        },
        "cam": {"type": "detector", "name": "Sim", "manufacturer": "Simulated"},
    },
}

#: Modules that import uc2_cam_py; removed so a test can make the import fail.
CAMERA_MODULES = (
    "uc2_cam_py",
    "newswitch.managers.camera",
    "newswitch.managers.camera.uc2_cam_detector",
)


@pytest.fixture
def camera_devices(tmp_path: Path) -> NewswitchConfig:
    """The loaded `CAMERA_DOC`.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.

    Returns:
        The device configuration.
    """
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(CAMERA_DOC, sort_keys=False), encoding="utf-8")
    return load_config(path).config


def _build(config: ImswitchConfig, devices: NewswitchConfig | None) -> DetectorManager:
    """Call `build_detector_manager` with fresh states, holding the camera lock."""
    with acquired_locks("camera_parameters"):
        return build_detector_manager(
            config,
            devices,
            camera_state=CameraState(),
            stage_state=StageState(),
            objective_state=ObjectiveState(),
            illumination_state=IlluminationState(),
            filter_bank_state=FilterBankState(),
            broadcaster=FrameBroadcaster(),
        )


def _settings(tmp_path: Path, *, virtual: bool) -> ImswitchConfig:
    """Base settings without a device file, recording into `tmp_path`."""
    return ImswitchConfig(
        use_virtual_microscope=virtual,
        config_file=None,
        camera_recording_dir=tmp_path / "recordings",
    )


def test_virtual_microscope_keeps_the_virtual_detector(
    tmp_path: Path, camera_devices: NewswitchConfig
) -> None:
    """In the virtual microscope configured cameras are simulated by newswitch itself."""
    manager = _build(_settings(tmp_path, virtual=True), camera_devices)
    assert isinstance(manager, VirtualDetectorManager)
    assert [detector.name for detector in manager.state.detectors] == ["Sim"]


def test_real_hardware_without_cameras(tmp_path: Path) -> None:
    """Without configured cameras the virtual detector stands in on real hardware."""
    assert isinstance(_build(_settings(tmp_path, virtual=False), None), VirtualDetectorManager)


def test_missing_camera_library_falls_back(
    tmp_path: Path,
    camera_devices: NewswitchConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Configured cameras without uc2_cam_py: the virtual detector, with a warning."""
    for name in CAMERA_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "uc2_cam_py", None)  # makes the import fail
    with caplog.at_level(logging.WARNING, logger=app_module.logger.name):
        manager = _build(_settings(tmp_path, virtual=False), camera_devices)
    assert isinstance(manager, VirtualDetectorManager)
    assert "uv sync --extra camera" in caplog.text


def test_real_hardware_opens_the_cameras(tmp_path: Path, camera_devices: NewswitchConfig) -> None:
    """On real hardware configured cameras open through uc2_cam_py; shutdown closes them."""
    pytest.importorskip("uc2_cam_py")
    from newswitch.managers.camera import UC2CamDetectorManager

    manager = _build(_settings(tmp_path, virtual=False), camera_devices)
    try:
        assert isinstance(manager, UC2CamDetectorManager)
        assert isinstance(manager, CameraManager)
        (detector,) = manager.state.detectors
        assert (detector.slot, detector.name, detector.width, detector.height) == (1, "Sim", 64, 48)
        assert manager.get_camera_info(1).serial_number == "SIM-0001"
    finally:
        app_module.close_cameras(manager)
    with pytest.raises(RuntimeError, match="closed"):
        manager.start_acquisition(1)


def test_close_cameras_ignores_other_detectors(tmp_path: Path) -> None:
    """The shutdown hook leaves detector managers without cameras alone."""
    app_module.close_cameras(_build(_settings(tmp_path, virtual=True), None))
