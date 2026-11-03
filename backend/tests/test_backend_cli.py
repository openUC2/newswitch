"""Tests for the debug console `backend_cli`: what it calls, how it reads its input, and
where the backend's output goes.

No server: the start/stop decisions work on CameraState as a plain dict, and the console
runs against a fake client that applies the calls to such a dict.
"""

import io
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

import backend_cli
from backend_cli import (
    ActionError,
    BackendClient,
    Console,
    Json,
    Step,
    parse_optional_float,
    parse_optional_int,
    parse_roi,
    plan_start,
    plan_stop,
    step_done,
)


def camera_state(is_acquiring: bool, active: dict[int, bool]) -> Json:
    """A CameraState with one detector per slot in `active` (slot -> is_active)."""
    return {
        "is_acquiring": is_acquiring,
        "detectors": [
            {"slot": slot, "name": f"cam {slot}", "is_active": is_active}
            for slot, is_active in active.items()
        ],
    }


class FakeClient:
    """Applies the detector actions to a CameraState dict and records them."""

    def __init__(self, state: Json) -> None:
        """Start from `state`."""
        self.state = state
        self.calls: list[Step] = []

    def camera_state(self) -> Json:
        """The current state."""
        return self.state

    def call(self, action: str, **args: object) -> object:
        """Record the call and apply its effect."""
        self.calls.append(Step(action, dict(args)))
        if action == "start_live_view":
            self.state["is_acquiring"] = True
        elif action == "stop_live_view":
            self.state["is_acquiring"] = False
        else:
            for detector in self.state["detectors"]:
                if detector["slot"] == args["slot"]:
                    detector["is_active"] = action == "activate_detector"
        return None


ACTIVATE_1 = Step("activate_detector", {"slot": 1})
DEACTIVATE_1 = Step("deactivate_detector", {"slot": 1})
START = Step("start_live_view")
STOP = Step("stop_live_view")


@pytest.mark.parametrize(
    ("is_acquiring", "is_active", "expected"),
    [
        (False, False, [ACTIVATE_1, START]),
        (False, True, [START]),
        (True, False, [ACTIVATE_1]),
    ],
)
def test_plan_start(is_acquiring: bool, is_active: bool, expected: list[Step]) -> None:
    """Starting activates an inactive detector and starts a live view that is off."""
    state = camera_state(is_acquiring, {1: is_active, 2: False})
    assert plan_start(state, 1) == expected


@pytest.mark.parametrize(
    ("activated_by_start", "other_active", "expected_steps", "also_stopped"),
    [
        (True, True, [DEACTIVATE_1], []),
        (True, False, [STOP, DEACTIVATE_1], []),
        (False, True, [STOP], [2]),
        (False, False, [STOP], []),
    ],
)
def test_plan_stop(
    activated_by_start: bool,
    other_active: bool,
    expected_steps: list[Step],
    also_stopped: list[int],
) -> None:
    """Stopping deactivates what start activated, and leaves other streams running if it can."""
    state = camera_state(True, {1: True, 2: other_active, 3: False})
    assert plan_stop(state, 1, activated_by_start) == (expected_steps, also_stopped)


def test_step_done_reads_camera_state() -> None:
    """Each live and activation call is done once CameraState shows its effect."""
    state = camera_state(True, {1: True})
    assert step_done(state, START)
    assert not step_done(state, STOP)
    assert step_done(state, ACTIVATE_1)
    assert not step_done(state, DEACTIVATE_1)


def test_step_done_compares_update_detector_with_its_return() -> None:
    """update_detector is done once CameraState holds the values it returned."""
    settings = {
        "current_exposure_time": 0.1,
        "current_gain": 1.0,
        "current_frame_rate": None,
        "current_binning": 1,
        "current_roi": None,
        "width": 640,
        "height": 480,
    }
    state = camera_state(True, {1: True})
    state["detectors"][0].update(settings)
    step = Step("update_detector", {"slot": 1, "binning": 2})

    assert step_done(state, step, settings)
    assert not step_done(state, step, {**settings, "current_binning": 2, "width": 320})


def test_start_then_stop_restores_an_inactive_detector() -> None:
    """A detector that start activated is inactive again after stop."""
    client = FakeClient(camera_state(False, {1: False}))
    console = Console(client)  # type: ignore[arg-type]  (duck-typed stand-in)
    console.slot = 1

    console.toggle_live(client.camera_state())
    assert client.calls == [ACTIVATE_1, START]
    console.toggle_live(client.camera_state())

    assert client.calls[2:] == [STOP, DEACTIVATE_1]
    assert client.state == camera_state(False, {1: False})
    assert console.activated_by_start == set()


def test_start_then_stop_keeps_an_active_detector_active() -> None:
    """A detector that was active before start stays active after stop."""
    client = FakeClient(camera_state(False, {1: True}))
    console = Console(client)  # type: ignore[arg-type]  (duck-typed stand-in)
    console.slot = 1

    console.toggle_live(client.camera_state())
    console.toggle_live(client.camera_state())

    assert client.calls == [START, STOP]
    assert client.state == camera_state(False, {1: True})


def test_activating_by_hand_clears_the_start_mark() -> None:
    """After a manual (de)activation, stop no longer deactivates the detector."""
    client = FakeClient(camera_state(False, {1: False}))
    console = Console(client)  # type: ignore[arg-type]  (duck-typed stand-in)
    console.slot = 1
    console.toggle_live(client.camera_state())
    console.toggle_activation(client.camera_state())  # deactivates: the stream ends
    console.toggle_activation(client.camera_state())  # active again, now by hand

    console.toggle_live(client.camera_state())  # stop

    assert client.calls[-1] == STOP
    assert client.state["detectors"][0]["is_active"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", None),
        ("full", [0, 0, 0, 0]),
        ("FULL", [0, 0, 0, 0]),
        ("10 20 300 200", [10, 20, 300, 200]),
        ("10,20, 300,200", [10, 20, 300, 200]),
    ],
)
def test_parse_roi(text: str, expected: list[int] | None) -> None:
    """A region is four whole numbers or ``full``; empty keeps it."""
    assert parse_roi(text) == expected


@pytest.mark.parametrize("text", ["10 20 300", "a b c d", "1 2 3 4.5"])
def test_parse_roi_rejects(text: str) -> None:
    """Anything but four whole numbers is refused."""
    with pytest.raises(ValueError):
        parse_roi(text)


def test_parse_numbers() -> None:
    """Empty keeps the value; 0 is a value (frame rate 0 removes the limit)."""
    assert parse_optional_float("") is None
    assert parse_optional_float("0") == 0.0
    assert parse_optional_float("0.25") == 0.25
    assert parse_optional_int("") is None
    assert parse_optional_int("2") == 2
    with pytest.raises(ValueError):
        parse_optional_int("2.5")


def test_divert_backend_output_catches_every_writer(tmp_path: Path) -> None:
    """Prints, a handler holding the old stderr and native writes land in the log only.

    Runs in a subprocess: diverting the file descriptors here would take them from pytest.
    """
    log_file = tmp_path / "logs" / "backend.log"
    script = textwrap.dedent(
        f"""
        import logging, os
        from pathlib import Path
        import backend_cli

        early = logging.getLogger("early")
        early.addHandler(logging.StreamHandler())  # keeps the old sys.stderr
        terminal = backend_cli.divert_backend_output(Path({str(log_file)!r}))
        print("from print")
        early.warning("from a handler")
        os.write(2, b"from native code\\n")
        backend_cli._terminal = terminal
        backend_cli.show("from the console")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(backend_cli.__file__).parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "from the console\n"
    assert result.stderr == ""
    log = log_file.read_text()
    for line in ("from print", "from a handler", "from native code"):
        assert line in log
    assert "from the console" not in log


def test_show_writes_to_the_terminal_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Console output goes to the stream `main` set, prompts without a line break."""
    terminal = io.StringIO()
    monkeypatch.setattr(backend_cli, "_terminal", terminal)

    backend_cli.show("menu")
    backend_cli.show("> ", end="")

    assert terminal.getvalue() == "menu\n> "


def answer_after_500s(failures: int) -> tuple[httpx.MockTransport, list[int]]:
    """A backend that answers the first `failures` POSTs with 500, then takes the call."""
    statuses: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        status = 500 if len(statuses) < failures else 200
        statuses.append(status)
        return httpx.Response(status, json={"status": "submitted", "task_id": "task-1"})

    return httpx.MockTransport(handle), statuses


def test_call_retries_while_the_backend_answers_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent takes calls only after its states exist; a 500 is retried, not reported."""
    monkeypatch.setattr(backend_cli, "SUBMIT_RETRY_INTERVAL_S", 0.0)
    transport, statuses = answer_after_500s(failures=2)
    client = BackendClient("http://backend", "token", transport=transport)
    events = client._events_for("task-1")
    events.put({"type": "YIELD", "task": "task-1", "returns": {"return0": "done"}})
    events.put({"type": "COMPLETED", "task": "task-1"})

    assert client.call("start_live_view") == "done"
    assert statuses == [500, 500, 200]


def test_call_gives_up_on_a_lasting_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """After `SUBMIT_RETRY_S` a lasting 500 becomes an ActionError."""
    monkeypatch.setattr(backend_cli, "SUBMIT_RETRY_INTERVAL_S", 0.0)
    monkeypatch.setattr(backend_cli, "SUBMIT_RETRY_S", 0.0)
    transport, statuses = answer_after_500s(failures=100)
    client = BackendClient("http://backend", "token", transport=transport)

    with pytest.raises(ActionError, match="HTTP 500"):
        client.call("start_live_view")
    assert statuses == [500]
