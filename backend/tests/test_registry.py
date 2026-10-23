"""The app registry holds what the device configuration's microscope has, and nothing else."""

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from newswitch import config_io
from main_fastapi import create_app
from newswitch.accounts.auth import AllowAllAuthenticator
from newswitch.settings import Settings
from tests.conftest import registry_names

CONFIGS = Path(__file__).parent.parent / "configs"
ASSETS = Path(__file__).parent.parent / "newswitch"

DEVICE_STATES = {
    "StageState",
    "IlluminationState",
    "CameraState",
    "ObjectiveState",
    "FilterBankState",
    "UC2State",
}
CORE_STATES = {
    "IOState",
    "HookState",
    "ExpanseState",
    "CalibrationState",
    "LightPathState",
}


def app_for(name: str, tmp_path: Path) -> FastAPI:
    """The virtual app of a shipped configuration, writing back into `tmp_path`."""
    return create_app(
        Settings(
            use_virtual_microscope=True,
            static_config_path=CONFIGS / name,
            persistent_config_path=tmp_path / "persistent.yaml",
            load_from_static_config_path=True,
            db_path=str(tmp_path / "agent.db"),
        ),
        AllowAllAuthenticator(),
    )


def registered(name: str | None) -> tuple[set[str], set[str]]:
    """The state and action names a shipped configuration (None: none) registers."""
    return registry_names(None if name is None else config_io.load_config(CONFIGS / name).config)


def test_a_complete_microscope_registers_every_part() -> None:
    """The default configuration has every part: every state and action."""
    states, actions = registered("newswitch-config.yaml")
    assert DEVICE_STATES | CORE_STATES | {"AutofocusState"} <= states
    assert {
        "move_stage",
        "switch_objective",
        "switch_filter",
        "home_stage",
    } <= actions


def test_a_camera_alone_registers_no_stage() -> None:
    """One camera: its state and actions, the core, nothing of a stage or light source."""
    states, actions = registered("camTest_config.yaml")
    assert states == CORE_STATES | {"CameraState"}
    assert {"capture_image", "start_live_view"} <= actions
    assert not {"move_stage", "calibrate_light_path", "scan_region", "switch_objective"} & actions


def test_the_fluorescence_microscope_has_no_objective_or_filters() -> None:
    """The design's microscope: stage, laser, camera and UC2 board, no objective or filters."""
    if not (ASSETS / "assets" / "design").is_dir():
        pytest.skip("the design's model is not built here: just build-design")
    states, actions = registered("newswitch-config.fluorescence.yaml")
    assert states == CORE_STATES | {
        "StageState",
        "IlluminationState",
        "CameraState",
        "UC2State",
        "AutofocusState",
    }
    assert not {"switch_objective", "toggle_objective", "switch_filter", "toggle_filter"} & actions
    assert {"move_stage", "calibrate_light_path", "acquire_multidimensional_acquisition"} <= actions


def test_the_parts_it_registers_are_the_parts_it_starts(tmp_path: Path) -> None:
    """Started, the agent publishes the configured parts' states, and no others."""
    app = app_for("camTest_config.yaml", tmp_path)
    with TestClient(app) as client:
        # The startup hooks run once the agent is up; wait for what they publish.
        published: set[str] = set()
        for _ in range(250):
            states = client.get("/states").json()["states"]
            published = {name for name, state in states.items() if state["initialized"]}
            if "CameraState" in published:  # the detector's hook runs after the core's
                break
            time.sleep(0.02)
        assert published == CORE_STATES | {"CameraState"}
        assert client.get("/states/CameraState").status_code == 200
        assert client.get("/states/StageState").status_code == 404


def test_without_a_configuration_only_the_core() -> None:
    """No device configuration: no devices, so only the core."""
    states, actions = registered(None)
    assert states == CORE_STATES
    assert actions == {"clear_expanse"}


def test_the_committed_schema_export_is_current(tmp_path: Path) -> None:
    """The frontend generates its hooks from frontend/schemas: it must match the backend."""
    from newswitch.tools.export_schemas import SCHEMA_DIR, export

    for written in export(tmp_path):
        committed = SCHEMA_DIR / written.name
        assert committed.read_text() == written.read_text(), (
            f"{committed} is stale: run just export-schemas"
        )


def test_the_schema_export_refuses_an_incomplete_microscope(tmp_path: Path) -> None:
    """A part missing from the export would drop its hooks from the frontend."""
    from newswitch.tools.export_schemas import export

    with pytest.raises(ValueError, match="objective"):
        export(tmp_path, CONFIGS / "newswitch-config.fluorescence.yaml")


def test_hardware_parts_need_a_uc2_board(tmp_path: Path) -> None:
    """On hardware a stage is driven through a UC2 board: without one, startup refuses."""
    from newswitch.microscope.parts import build_microscope

    devices = config_io.load_config(CONFIGS / "newswitch-config.fluorescence.yaml").config
    devices.devices = {
        key: device for key, device in devices.devices.items() if device.type != "controller"
    }
    settings = Settings(use_virtual_microscope=False, config_file=None, camera_debug_window=False)
    with pytest.raises(config_io.ConfigError, match="stage, illumination need a UC2 board"):
        build_microscope(settings, devices)


def test_with_a_uc2_board_the_bus_runs() -> None:
    """A UC2 board is provided and its bus pumped: both are registered with it."""
    states, actions = registered("newswitch-config.yaml")
    assert "UC2State" in states and "home_stage" in actions


def test_a_camera_alone_acquires(settings: Settings) -> None:
    """Without stage, objective or filters (camTest) capture_image takes an uncalibrated image.

    Its light path is the detector alone; the frame gets the detector's nominal pixel size.
    (Called directly: the in-process agent test client can stall on this action's result,
    which a real server delivers; see the serving tests for the agent path.)
    """
    from newswitch.actions.detector import capture_image
    from newswitch.microscope.parts import build_microscope

    devices = config_io.load_config(CONFIGS / "camTest_config.yaml").config
    built = build_microscope(settings, devices)
    assert built.detector is not None and built.acquisition is not None
    assert [[k.kube_id for k in p.kubes] for p in built.light_path.state.light_paths] == [
        ["detector_1"]
    ]

    frames = capture_image(built.detector, built.acquisition)

    assert len(frames) == 1
    detector = built.camera_state.detectors[0]
    assert frames[0].metadata.fov_width == pytest.approx(detector.pixel_size_um * detector.width)
