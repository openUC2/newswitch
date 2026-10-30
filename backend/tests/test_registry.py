"""The app registry holds what the instrument has, and nothing else."""

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main_fastapi import create_app
from newswitch.accounts.auth import AllowAllAuthenticator
from newswitch.instrument import spec
from newswitch.settings import Settings
from newswitch.tools.export_schemas import REFERENCE_INSTRUMENT
from tests.conftest import registry_names, run_settings

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
CAM_TEST = INSTRUMENTS / "cam-test"

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


def app_for(instrument: Path, tmp_path: Path) -> FastAPI:
    """The simulated app of an instrument, writing into `tmp_path`."""
    return create_app(
        run_settings(tmp_path, instrument=instrument),
        AllowAllAuthenticator(),
    )


def registered(instrument: Path | None) -> tuple[set[str], set[str]]:
    """The state and action names an instrument (None: none) registers."""
    return registry_names(None if instrument is None else spec.load(instrument))


def test_a_complete_microscope_registers_every_part() -> None:
    """The reference microscope has every part: every state and action."""
    states, actions = registered(REFERENCE_INSTRUMENT)
    assert DEVICE_STATES | CORE_STATES | {"AutofocusState"} <= states
    assert {
        "move_stage",
        "switch_objective",
        "switch_filter",
        "home_stage",
    } <= actions


def test_a_camera_alone_registers_no_stage() -> None:
    """One camera: its state and actions, the core, nothing of a stage or light source."""
    states, actions = registered(CAM_TEST)
    assert states == CORE_STATES | {"CameraState"}
    assert {"capture_image", "start_live_view"} <= actions
    assert not {"move_stage", "calibrate_light_path", "scan_region", "switch_objective"} & actions


def test_the_parts_it_registers_are_the_parts_it_starts(tmp_path: Path) -> None:
    """Started, the agent publishes the states of the parts it has, and no others."""
    app = app_for(CAM_TEST, tmp_path)
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


def test_without_an_instrument_only_the_core() -> None:
    """No instrument: no devices, so only the core."""
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

    with pytest.raises(ValueError, match="ObjectiveState"):
        export(tmp_path, CAM_TEST)


def test_with_a_uc2_board_the_bus_runs() -> None:
    """A UC2 board is provided and its bus pumped: both are registered with it."""
    states, actions = registered(REFERENCE_INSTRUMENT)
    assert "UC2State" in states and "home_stage" in actions


def test_a_camera_alone_acquires(settings: Settings) -> None:
    """Without stage, objective or filters (cam-test) capture_image takes an uncalibrated image.

    Its light path is the detector alone; the frame gets the size its optics predict: lenses that
    magnify by one, so the sensor's own.
    (Called directly: the in-process agent test client can stall on this action's result,
    which a real server delivers; see the serving tests for the agent path.)
    """
    from newswitch.actions.detector import capture_image
    from newswitch.microscope.parts import build_microscope

    built = build_microscope(settings, spec.load(CAM_TEST))
    assert built.detector is not None and built.acquisition is not None
    assert [[k.kube_id for k in p.kubes] for p in built.light_path.state.light_paths] == [
        ["detector_1"]
    ]

    frames = capture_image(built.detector, built.acquisition)

    assert len(frames) == 1
    detector = built.camera_state.detectors[0]
    assert frames[0].metadata.fov_width == pytest.approx(
        detector.pixel_size_um * detector.width, rel=0.01
    )


def test_a_part_reached_twice_counts_once() -> None:
    """Focus and acquisition both bring stage and detector: one hook of each, one state."""
    from main_fastapi import create_fastapi_registry

    registry = create_fastapi_registry(spec.load(REFERENCE_INSTRUMENT)).registry
    hooks = registry.hooks_registry.startup_hooks
    assert {"provide_core", "provide_stage", "provide_detector", "provide_focus"} <= set(hooks)
    assert list(registry.states).count("StageState") == 1


def test_two_apps_share_no_microscope(tmp_path: Path) -> None:
    """Every run holds its own build; the part registries hold none."""
    from newswitch.microscope.run import Run

    settings = run_settings(tmp_path, instrument=REFERENCE_INSTRUMENT)
    first, second = Run.of(settings), Run.of(settings)
    assert first.microscope is first.microscope
    assert first.microscope is not second.microscope
    assert first.microscope.stage_state is not second.microscope.stage_state


def test_merging_leaves_the_parts_as_they_are() -> None:
    """Parts live as long as the process, so one instrument must not leak into the next app."""
    from main_fastapi import create_fastapi_registry
    from newswitch.microscope.apps import stage

    before = set(stage.app.registry.hooks_registry.startup_hooks)
    create_fastapi_registry(spec.load(REFERENCE_INSTRUMENT))
    assert set(stage.app.registry.hooks_registry.startup_hooks) == before
    assert not {"provide_frame_broadcaster", "provide_focus"} & before
    states, _ = registered(CAM_TEST)
    assert "StageState" not in states
