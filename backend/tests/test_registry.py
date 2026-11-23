"""The app registry holds every part, whatever the instrument has: one static app."""

import time
from typing import Any
from pathlib import Path

import pytest
from fastapi import FastAPI
from arkitekt_fastapi.testing import AsyncAgentTestClient
from fastapi.testclient import TestClient

from main_fastapi import create_app
from newswitch.infra.accounts.auth import AllowAllAuthenticator
from newswitch.instrument import spec
from newswitch.settings import Settings
from newswitch.reference import REFERENCE_INSTRUMENT
from tests.conftest import collect_until_completed, registry_names, run_settings

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
CAM_TEST = INSTRUMENTS / "cam-test"

VALUE_STATES = {"MoveState", "SwapState", "TuneState", "SourceState"}
DEVICE_STATES = VALUE_STATES | {"DetectorState", "UC2State", "MountCalibrationState"}
CORE_STATES = {
    "IOState",
    "HookState",
    "ExpanseState",
    "CalibrationState",
    "SpaceState",
    "OpticsState",
}


def app_for(instrument: Path, tmp_path: Path) -> FastAPI:
    """The simulated app of an instrument, writing into `tmp_path`."""
    return create_app(
        run_settings(tmp_path, instrument=instrument),
        AllowAllAuthenticator(),
    )


EVERY_STATE = DEVICE_STATES | CORE_STATES | {"AutofocusState"}


def test_every_part_is_registered() -> None:
    """One static app, whatever the instrument: every state and every action."""
    states, actions = registry_names()
    assert states == EVERY_STATE
    assert {"move", "move_one", "move_home", "swap", "tune", "home_stage", "galvo_stop"} <= actions
    assert {"capture_image", "run_autofocus", "scan_region", "acquire", "acquire_mda"} <= actions


def test_a_camera_alone_starts_every_state(tmp_path: Path) -> None:
    """Started on one camera (no stage, no board), the agent publishes every state all the same:
    what the camera lacks is an empty one."""
    app = app_for(CAM_TEST, tmp_path)
    with TestClient(app) as client:
        # The startup hooks run once the agent is up; wait for what they publish.
        published: set[str] = set()
        for _ in range(250):
            states = client.get("/states").json()["states"]
            published = {name for name, state in states.items() if state["initialized"]}
            if published == EVERY_STATE:
                break
            time.sleep(0.02)
        assert published == EVERY_STATE
        assert client.get("/states/UC2State").status_code == 200


@pytest.mark.asyncio
async def test_an_action_of_a_part_it_lacks_fails_when_called(tmp_path: Path) -> None:
    """No board: its context is not provided, so its actions fail, and the rest work."""
    async with AsyncAgentTestClient(app_for(CAM_TEST, tmp_path)) as client:
        lacking = await client.assign("home_stage", {})
        events = await collect_until_completed(client, lacking.task_id)
        assert events and events[-1].event_type in ("FAILED", "CRITICAL"), events
        assert "uc2_bus_manager not found" in str(events[-1]), events[-1]

        working = await client.assign("activate_detector", {"name": "sim_cam"})
        events = await collect_until_completed(client, working.task_id)
        assert events and events[-1].event_type == "COMPLETED", events[-1]


def test_the_committed_schema_export_is_current(tmp_path: Path) -> None:
    """The frontend generates its hooks from frontend/schemas: it must match the backend."""
    from newswitch.infra.export_schemas import SCHEMA_DIR, export

    for written in export(tmp_path):
        committed = SCHEMA_DIR / written.name
        assert committed.read_text() == written.read_text(), (
            f"{committed} is stale: run just export-schemas"
        )


def test_without_a_board_its_bus_is_not_built(tmp_path: Path) -> None:
    """A part the instrument lacks is None: its startup hook provides no context, so arkitekt
    starts none of its background tasks."""
    from newswitch.microscope.parts import build_microscope

    built = build_microscope(run_settings(tmp_path), spec.load(CAM_TEST))
    assert built.uc2_bus is None and built.detector is not None
    assert build_microscope(run_settings(tmp_path / "ref"), spec.load(REFERENCE_INSTRUMENT)).uc2_bus


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
    assert [[e.name for e in p.path.elements] for p in built.optics.state.detectors.values()] == [
        ["sample", "lens_a", "lens_b", "sim_cam"]
    ]

    frames = capture_image(built.detector, built.acquisition)

    assert len(frames) == 1
    detector = built.detector_state.detectors[0]
    assert frames[0].metadata.fov_width == pytest.approx(
        built.optics_state.detectors["sim_cam"].pixel_um * detector.plane()[1], rel=0.01
    )


def test_a_part_reached_twice_counts_once() -> None:
    """Focus and acquisition both bring stage and detector: one hook of each, one state."""
    from main_fastapi import create_fastapi_registry

    registry = create_fastapi_registry(None).registry
    hooks = registry.hooks_registry.startup_hooks
    assert {"provide_core", "provide_values", "provide_detector", "provide_focus"} <= set(hooks)
    assert list(registry.states).count("MoveState") == 1


def test_two_apps_share_no_microscope(tmp_path: Path) -> None:
    """Every run holds its own build; the part registries hold none."""
    from newswitch.microscope.run import Run

    settings = run_settings(tmp_path, instrument=REFERENCE_INSTRUMENT)
    first, second = Run.of(settings), Run.of(settings)
    assert first.microscope is first.microscope
    assert first.microscope is not second.microscope
    assert first.microscope.move_state is not second.microscope.move_state


def test_merging_leaves_the_parts_as_they_are() -> None:
    """Parts live as long as the process, so what one app adds must not leak into the next."""
    from main_fastapi import create_fastapi_registry
    from newswitch.microscope import registry
    from newswitch.microscope.apps import values

    before = set(values.app.registry.hooks_registry.startup_hooks)
    microscope = set(registry.app.registry.hooks_registry.startup_hooks)
    create_fastapi_registry(spec.load(REFERENCE_INSTRUMENT), with_mikro=True)
    assert set(values.app.registry.hooks_registry.startup_hooks) == before
    assert set(registry.app.registry.hooks_registry.startup_hooks) == microscope
    assert not {"provide_frame_broadcaster", "provide_focus"} & before
    assert not {"provide_frame_broadcaster", "provide_mikro"} & microscope
    assert registry.app.registry.get_declared_bloks() == {}


def test_the_agent_declares_what_fastapi_declares() -> None:
    """``app.py`` registers every part directly; FastAPI through the part registries. Both declare
    the same actions, with the same locks and definitions, the same states, and the same models."""
    pytest.importorskip("lovekit")
    from app import app as agent
    from main_fastapi import create_fastapi_registry

    served = agent.registry.snapshot()
    fastapi = create_fastapi_registry(None).registry.snapshot()

    def actions(registry: Any) -> dict[str, Any]:  # noqa: ANN401
        return {
            impl.interface or impl.definition.name: impl.model_dump(mode="json")
            for impl in registry.get_implementations()
        }

    assert actions(served) == actions(fastapi)
    assert set(served.states) == set(fastapi.states) | {"CameraStreams"}
    assert {lock.key for lock in served.get_locks()} == {lock.key for lock in fastapi.get_locks()}
    hooks = set(agent.registry.hooks_registry.startup_hooks)
    assert {
        "provide_core",
        "provide_values",
        "provide_detector",
        "provide_focus",
        "provide_uc2",
    } <= hooks
