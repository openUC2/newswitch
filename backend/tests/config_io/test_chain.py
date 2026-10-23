"""End-to-end: static/persistent files -> managers -> firmware and runtime changes -> save.

Runs on ``data/Test-Config-static.yaml`` and ``data/Test-Config-persistent.yaml``, whose
controllers are all simulated. Both are copied into a temporary folder first, so the
repository is never written.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator

import pytest

from newswitch.config_io import (
    AxisConfig,
    ConfigFile,
    DetectorConfig,
    LightsourceConfig,
    adapters,
    open_config,
)
from newswitch.states.detector import CameraState
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.objective import ObjectiveState
from newswitch.states.stage import StageState

from .conftest import get_device

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def _locks() -> Iterator[None]:
    """Hold the state locks, as a registered function would, so states can be changed."""
    yield


@pytest.fixture
def static(config_dir: Path) -> Path:
    """The static test configuration, copied into the temporary config folder.

    Args:
        config_dir: The temporary config directory fixture.

    Returns:
        Its path.
    """
    return Path(shutil.copy(DATA / "Test-Config-static.yaml", config_dir / "static.yaml"))


@pytest.fixture
def persistent(config_dir: Path) -> Path:
    """The persistent test configuration (an earlier session), copied likewise.

    Args:
        config_dir: The temporary config directory fixture.

    Returns:
        Its path.
    """
    return Path(shutil.copy(DATA / "Test-Config-persistent.yaml", config_dir / "persistent.yaml"))


def _run_session(cfg_file: ConfigFile) -> None:
    """Start the managers from the configuration, change things at runtime, save.

    The simulated controllers report firmware values first (as a real board would on
    connect); then the user changes exposure, stage position, filter and objective.

    Args:
        cfg_file: The opened configuration.
    """
    cfg_file.apply_firmware(
        "cam", {"exposure_time_ms": {"min": 0.05, "max": 2000.0}, "manufacturer": "SimCam"}
    )
    cfg_file.apply_firmware("x-axis", {"vel": {"max": 20.0, "unit": "mm/s"}})
    config = cfg_file.config

    camera_state = CameraState()
    detectors = adapters.detectors(config)
    assert detectors is not None
    camera_state.detectors = detectors
    stage_state = StageState()
    adapters.apply_stage_limits(config, stage_state)
    assert (stage_state.max_x, stage_state.max_y) == (100_000.0, 100_000.0)

    camera_state.detectors[0].current_exposure_time = 0.04  # s
    stage_state.x = 1500.0
    filter_slot = config.slot_of("flt-tritc")
    objective_slot = config.slot_of("obj-40x")
    adapters.sync_runtime_state(
        config,
        camera_state,
        ObjectiveState(slot=objective_slot),
        FilterBankState(current_slot=filter_slot),
        stage_state,
    )
    cfg_file.save()


def test_from_static_writes_only_persistent(static: Path, persistent: Path) -> None:
    """Reading the static file: its state is used, every change lands in persistent."""
    static_bytes = static.read_bytes()
    cfg_file = open_config(static, persistent, from_static=True)
    assert cfg_file.path == static and cfg_file.target == persistent
    cam = get_device(cfg_file.config, "cam", DetectorConfig)
    assert cam.exposure_time_ms is not None and cam.exposure_time_ms.value == 25.0  # static
    filters = adapters.filters(cfg_file.config)
    assert filters is not None and filters[1] == cfg_file.config.slot_of("flt-gfp")

    _run_session(cfg_file)

    assert static.read_bytes() == static_bytes  # never written
    text = persistent.read_text(encoding="utf-8")
    assert text.startswith("# Test-Config-static")  # overwritten from static, comments kept
    assert "optikit_dsn_variable: sample-x   # a key newswitch does not know" in text

    reloaded = open_config(static, persistent, from_static=False).config
    exposure = get_device(reloaded, "cam", DetectorConfig).exposure_time_ms
    assert exposure is not None
    assert (exposure.value, exposure.min, exposure.max) == pytest.approx((40.0, 0.05, 2000.0))
    assert get_device(reloaded, "cam", DetectorConfig).manufacturer == "SimCam"
    x_axis = get_device(reloaded, "x-axis", AxisConfig)
    assert x_axis.pos is not None and x_axis.pos.value == pytest.approx(1500.0)
    assert x_axis.vel is not None and x_axis.vel.max == pytest.approx(20_000.0)
    assert x_axis.extras == {"optikit_dsn_variable": "sample-x"}
    filter_pos = get_device(reloaded, "filter-axis", AxisConfig).pos
    assert filter_pos is not None and (filter_pos.selected_index, filter_pos.value) == (2, 2000.0)
    turret_pos = get_device(reloaded, "turret-axis", AxisConfig).pos
    assert turret_pos is not None and turret_pos.selected_index == 1
    assert get_device(reloaded, "led-top", LightsourceConfig).name == "led-top"


def test_from_persistent_uses_its_state(static: Path, persistent: Path) -> None:
    """Reading the persistent file: the earlier session's state applies, not the static one."""
    static_bytes = static.read_bytes()
    cfg_file = open_config(static, persistent, from_static=False)
    assert cfg_file.path == persistent == cfg_file.target
    config = cfg_file.config

    detectors = adapters.detectors(config)
    assert detectors is not None and detectors[0].current_exposure_time == pytest.approx(0.05)
    filters = adapters.filters(config)
    assert filters is not None and filters[1] == config.slot_of("flt-tritc")
    lenses = adapters.objective_lenses(config)
    assert lenses is not None and lenses[1] == config.slot_of("obj-40x")
    x_axis = get_device(config, "x-axis", AxisConfig)
    assert x_axis.pos is not None and x_axis.pos.value == 2000.0

    _run_session(cfg_file)

    assert static.read_bytes() == static_bytes
    text = persistent.read_text(encoding="utf-8")
    assert text.startswith("# Test-Config-persistent")  # written back in place
    exposure = get_device(
        open_config(static, persistent, from_static=False).config, "cam", DetectorConfig
    ).exposure_time_ms
    assert exposure is not None and exposure.value == pytest.approx(40.0)


def test_missing_persistent_starts_as_static(static: Path, config_dir: Path) -> None:
    """Without a persistent file, it is created as an exact copy of the static one."""
    persistent = config_dir / "new" / "persistent.yaml"
    cfg_file = open_config(static, persistent, from_static=False)
    assert persistent.read_bytes() == static.read_bytes()
    assert cfg_file.path == persistent

    static_bytes = static.read_bytes()
    _run_session(cfg_file)
    assert static.read_bytes() == static_bytes
    assert persistent.read_bytes() != static_bytes


def test_controllers_and_mapping(static: Path, persistent: Path) -> None:
    """Every active device is reachable through exactly one simulated controller."""
    config = open_config(static, persistent, from_static=True).config
    assert adapters.serial_settings(config) is None  # simulated: no port to open
    found = config.controller_of("turret-axis")
    assert found is not None and found[0] == "sim-can-hat" and found[1].address == (4, 2)
    cam_entry = config.controller_of("cam")
    assert cam_entry is not None and cam_entry[1].extras == {"serial_number": "SIM-0001"}
    xyz = config.stage_axes(config.stages[0])
    assert list(xyz) == ["x", "y", "z"]
    assert xyz["z"].steps_per_um is None and xyz["z"].inverted is True
