"""Debug console: boot the backend like main.py, then drive the detectors from the terminal.

Like the frontend, the console only uses what the backend registers: actions (``POST
/<action>``, their results over ``/ws``) and states (``GET /states/CameraState``). It never
touches a manager, so whatever works here works for the frontend too.

    cd backend
    uv run -q python backend_cli.py
    NEWSWITCH_CONFIG=configs/camTest.json uv run -q python backend_cli.py

Settings, host and port are those of main.py (base_config.yaml, NEWSWITCH_CONFIG,
BACKEND_HOST / BACKEND_PORT, default port 8099). With BACKEND_PORT=8069 the frontend
(`just dev-frontend`) can connect at the same time. The login comes from NEWSWITCH_CLI_USER /
NEWSWITCH_CLI_PASSWORD, otherwise it is asked for.

Everything the backend writes to the terminal (prints, logs, warnings, tracebacks, native
libraries) goes to data/backend_cli.log instead, so the menu stays readable; follow it with
``tail -f data/backend_cli.log``. ``--verbose`` leaves it in the terminal. ``-q`` keeps uv's
own warnings out.

The backend knows one live view for all active detectors (start_live_view / stop_live_view).
`plan_start` and `plan_stop` map starting and stopping a single detector onto it.
"""

from __future__ import annotations

import argparse
import getpass
import io
import json
import os
import queue
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO, TypeVar

import httpx
import uvicorn
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

# newswitch.app is imported in `start_backend`, after the output is diverted: importing it
# already prints warnings.
from newswitch.protocols.detector import FULL_SENSOR

#: A JSON object as the backend sends it.
Json = dict[str, Any]
T = TypeVar("T")

STARTUP_TIMEOUT_S = 120.0
"""Time the backend may take until CameraState exists (opening cameras takes a while)."""
ACTION_TIMEOUT_S = 60.0
STATE_TIMEOUT_S = 5.0
"""Time CameraState may lag behind an action: its patches arrive after the action ends."""
POLL_INTERVAL_S = 0.05
SUBMIT_RETRY_S = 10.0
"""How long a call is retried while the backend answers HTTP 500. The agent publishes its
states before it accepts calls; a 500 means the call was not queued, so retrying is safe."""
SUBMIT_RETRY_INTERVAL_S = 0.2
MAX_BUFFERED_TASKS = 200
"""Tasks whose events are kept; the socket also carries tasks of other clients."""

SETTING_KEYS = (
    "current_exposure_time",
    "current_gain",
    "current_frame_rate",
    "current_binning",
    "current_roi",
    "width",
    "height",
)
"""Detector fields update_detector sets; CameraState is current once they match its return."""

END_EVENTS = frozenset(
    {"COMPLETED", "CRITICAL", "FAILED", "CANCELLED", "APP_CANCELLED", "INTERRUPTED"}
)
TASK_EVENTS = END_EVENTS | {"YIELD"}

LOG_FILE = Path(__file__).resolve().parent / "data" / "backend_cli.log"
"""Where the backend's terminal output goes (rewritten on every start; data/ is gitignored)."""

_terminal: TextIO | None = None
"""Where the console writes; None: sys.stdout. Set by `main` when it diverts the output."""


class ActionError(Exception):
    """A registered action failed, was cancelled or did not answer."""


@dataclass(frozen=True)
class Step:
    """One call of a registered action."""

    action: str
    args: Json = field(default_factory=dict)

    def __str__(self) -> str:
        """The call as it reads in Python, e.g. ``activate_detector(slot=1)``."""
        args = ", ".join(f"{key}={value!r}" for key, value in self.args.items())
        return f"{self.action}({args})"


# ====================
# Client
# ====================


class BackendClient:
    """Talks to the backend the way the frontend does: HTTP for calls, ``/ws`` for results."""

    def __init__(
        self, base_url: str, token: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        """Prepare the client; `connect` opens the event socket.

        Args:
            base_url: E.g. ``http://127.0.0.1:8099``.
            token: Bearer token from ``/auth/login``.
            transport: For tests: replaces the network.
        """
        self._base_url = base_url
        self._token = token
        # No keep-alive: after an unhandled error uvicorn drops the connection without saying
        # so, and the next request on it would fail with "connection reset by peer".
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
            limits=httpx.Limits(max_keepalive_connections=0),
            transport=transport,
        )
        self._socket: ClientConnection | None = None
        self._reader: threading.Thread | None = None
        self._events: dict[str, queue.Queue[Json]] = {}
        self._events_lock = threading.Lock()

    def connect(self) -> None:
        """Open ``/ws`` and collect the task events in a background thread."""
        url = self._base_url.replace("http", "ws", 1) + "/ws"
        # No size limit: the first message is a snapshot of every state.
        self._socket = connect(url, max_size=None)
        self._socket.send(json.dumps({"type": "INIT", "token": self._token}))
        self._reader = threading.Thread(target=self._read_events, name="cli-events", daemon=True)
        self._reader.start()

    def close(self) -> None:
        """Close the event socket and the HTTP client."""
        if self._socket is not None:
            self._socket.close()
        if self._reader is not None:
            self._reader.join(timeout=5.0)
        self._http.close()

    def camera_state(self) -> Json:
        """Return the current CameraState (``is_acquiring``, ``detectors``)."""
        response = self._http.get("/states/CameraState")
        response.raise_for_status()
        return response.json()["state"]

    def wait_until_ready(self) -> None:
        """Wait until the backend has set up its states (they start after the server).

        Raises:
            SystemExit: CameraState does not appear within `STARTUP_TIMEOUT_S`.
        """
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._http.get("/states/CameraState").status_code == 200:
                return
            time.sleep(0.2)
        raise SystemExit(f"CameraState did not appear within {STARTUP_TIMEOUT_S:.0f} s")

    def call(self, action: str, **args: object) -> object:
        """Run a registered action and wait for its end.

        Args:
            action: Name of the action, e.g. ``activate_detector``.
            **args: Its arguments.

        Returns:
            What the action returned (``return0``), None when it returns nothing.

        Raises:
            ActionError: The action failed, was cancelled, did not end within
                `ACTION_TIMEOUT_S`, or the backend did not take it (HTTP 500 for
                `SUBMIT_RETRY_S`).
        """
        task_id = self._submit(action, args)
        events = self._events_for(task_id)
        returns: Json = {}
        deadline = time.monotonic() + ACTION_TIMEOUT_S
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ActionError(f"{action}: no answer within {ACTION_TIMEOUT_S:.0f} s")
                try:
                    event = events.get(timeout=remaining)
                except queue.Empty:
                    continue
                kind = event["type"]
                if kind == "YIELD":
                    returns = event.get("returns") or {}
                elif kind == "COMPLETED":
                    return returns.get("return0")
                else:
                    raise ActionError(f"{action}: {kind} {event.get('error') or ''}".rstrip())
        finally:
            with self._events_lock:
                self._events.pop(task_id, None)

    def _submit(self, action: str, args: Json) -> str:
        """POST the action and return its task id; retry while the backend answers HTTP 500."""
        deadline = time.monotonic() + SUBMIT_RETRY_S
        while True:
            response = self._http.post(
                f"/{action}",
                json={
                    "args": args,
                    "cached": False,
                    "log": False,
                    "capture": False,
                    "ephemeral": False,
                },
            )
            if response.status_code != 500 or time.monotonic() >= deadline:
                break
            time.sleep(SUBMIT_RETRY_INTERVAL_S)
        if response.status_code == 500:
            raise ActionError(f"{action}: HTTP 500 from the backend, see its output")
        response.raise_for_status()
        return response.json()["task_id"]

    def _events_for(self, task_id: str) -> queue.Queue[Json]:
        """The event queue of a task, created on first use by either side."""
        with self._events_lock:
            events = self._events.get(task_id)
            if events is None:
                if len(self._events) >= MAX_BUFFERED_TASKS:
                    self._events.pop(next(iter(self._events)))
                events = self._events[task_id] = queue.Queue()
            return events

    def _read_events(self) -> None:
        """Sort the task events by task. Events may arrive before the POST answers."""
        if self._socket is None:
            return
        try:
            for raw in self._socket:
                message = json.loads(raw)
                if not isinstance(message, dict) or message.get("type") not in TASK_EVENTS:
                    continue
                task_id = message.get("task")
                if task_id:
                    self._events_for(task_id).put(message)
        except ConnectionClosed:
            pass


def login(base_url: str) -> str:
    """Log in at ``/auth/login`` and return the token.

    Raises:
        SystemExit: The login failed (three tries when asked for, one from the environment).
    """
    user = os.environ.get("NEWSWITCH_CLI_USER")
    password = os.environ.get("NEWSWITCH_CLI_PASSWORD")
    tries = 1 if user and password else 3
    for _ in range(tries):
        name = user or ask("User [admin]: ", str) or "admin"
        # getpass reads from /dev/tty when there is one; `stream` is its fallback.
        secret = password if password is not None else getpass.getpass("Password: ", _terminal)
        response = httpx.post(f"{base_url}/auth/login", auth=(name, secret), timeout=10.0)
        if response.status_code == 200:
            return response.json()["token"]
        show(f"Login failed ({response.status_code}).")
    raise SystemExit("login failed")


# ====================
# What to call
# ====================


def find_detector(state: Json, slot: int) -> Json:
    """The detector in `slot` from a CameraState.

    Raises:
        ValueError: No detector in `slot`.
    """
    for detector in state["detectors"]:
        if detector["slot"] == slot:
            return detector
    raise ValueError(f"no detector in slot {slot}")


def is_live(state: Json, detector: Json) -> bool:
    """Whether the detector streams: the live view runs and the detector is active.

    `Detector.is_acquiring` is never set by the managers, so it is not used.
    """
    return bool(state["is_acquiring"] and detector["is_active"])


def plan_start(state: Json, slot: int) -> list[Step]:
    """Calls that start the detector in `slot`: activate it if needed, start the live view."""
    steps: list[Step] = []
    if not find_detector(state, slot)["is_active"]:
        steps.append(Step("activate_detector", {"slot": slot}))
    if not state["is_acquiring"]:
        steps.append(Step("start_live_view"))
    return steps


def plan_stop(state: Json, slot: int, activated_by_start: bool) -> tuple[list[Step], list[int]]:
    """Calls that stop the detector in `slot`, as far as a global live view allows.

    A detector that `plan_start` activated is deactivated again. If other detectors stream,
    deactivating it is enough and they keep streaming; otherwise the live view stops, and
    with it every detector.

    Args:
        state: The current CameraState.
        slot: The detector to stop.
        activated_by_start: Starting it activated it.

    Returns:
        The calls, and the slots of the other detectors that stop with it.
    """
    others = [
        detector["slot"]
        for detector in state["detectors"]
        if detector["slot"] != slot and is_live(state, detector)
    ]
    if activated_by_start and others:
        return [Step("deactivate_detector", {"slot": slot})], []
    steps = [Step("stop_live_view")]
    if activated_by_start:
        steps.append(Step("deactivate_detector", {"slot": slot}))
    return steps, others


def step_done(state: Json, step: Step, result: object = None) -> bool:
    """Whether a CameraState already shows the effect of `step`.

    Args:
        state: The CameraState.
        step: The call.
        result: What it returned; for update_detector the applied detector.
    """
    if step.action == "start_live_view":
        return bool(state["is_acquiring"])
    if step.action == "stop_live_view":
        return not state["is_acquiring"]
    if step.action in ("activate_detector", "deactivate_detector"):
        active = find_detector(state, step.args["slot"])["is_active"]
        return active == (step.action == "activate_detector")
    if step.action == "update_detector" and isinstance(result, dict):
        detector = find_detector(state, step.args["slot"])
        return all(detector[key] == result[key] for key in SETTING_KEYS)
    return True


# ====================
# Terminal
# ====================


def divert_backend_output(log_file: Path) -> TextIO:
    """Send everything written to stdout and stderr into `log_file`, by Python or native code.

    Works on the file descriptors 1 and 2, so it also catches logging handlers that keep the
    old ``sys.stderr`` and C libraries. The file is rewritten.

    Returns:
        A stream to the terminal for the console's own output (see `show`).
    """
    sys.stdout.flush()
    sys.stderr.flush()
    terminal = open(  # stays open until the process ends
        os.dup(1), "w", buffering=1, encoding=sys.stdout.encoding, errors="replace"
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w", encoding="utf-8") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
    if isinstance(sys.stdout, io.TextIOWrapper):
        # Piped stdout is block-buffered; line by line, `tail -f` follows the log live.
        sys.stdout.reconfigure(line_buffering=True)
    return terminal


def show(text: str = "", end: str = "\n") -> None:
    """Write console output to the terminal, past a diverted stdout."""
    stream = _terminal or sys.stdout
    stream.write(text + end)
    stream.flush()


# ====================
# Input
# ====================


def parse_optional_float(text: str) -> float | None:
    """A number, or None for an empty input (keep the value)."""
    return float(text) if text else None


def parse_optional_int(text: str) -> int | None:
    """A whole number, or None for an empty input (keep the value)."""
    return int(text) if text else None


def parse_roi(text: str) -> list[int] | None:
    """``x y width height`` (spaces or commas), ``full`` for the whole sensor, empty: keep.

    Raises:
        ValueError: Not four whole numbers.
    """
    if not text:
        return None
    if text.lower() == "full":
        return list(FULL_SENSOR)
    parts = text.replace(",", " ").split()
    if len(parts) != 4:
        raise ValueError("expected x y width height, or 'full'")
    return [int(part) for part in parts]


def ask(prompt: str, parse: Callable[[str], T]) -> T:
    """Ask until `parse` accepts the input."""
    while True:
        # Not input(prompt): with stdout diverted it writes the prompt into the log.
        show(prompt, end="")
        text = input().strip()
        try:
            return parse(text)
        except ValueError as exc:
            show(f"  invalid input: {exc}")


def yes_no(value: bool) -> str:
    """``yes`` or ``no``."""
    return "yes" if value else "no"


def number(value: float | None, unit: str = "") -> str:
    """A value with its unit, ``?`` when unknown."""
    return "?" if value is None else f"{value:g}{unit}"


def describe(state: Json, detector: Json) -> str:
    """One status line: slot, name, activated, acquiring."""
    return (
        f"slot {detector['slot']}: {detector['name']:<20}"
        f" activated: {yes_no(detector['is_active']):<4}"
        f" acquiring: {yes_no(is_live(state, detector))}"
    )


def describe_settings(detector: Json) -> str:
    """The current exposure, gain, frame rate, binning, region and image size."""
    frame_rate = detector["current_frame_rate"]
    roi = detector["current_roi"]
    return (
        f"exposure {number(detector['current_exposure_time'], ' s')},"
        f" gain {number(detector['current_gain'])},"
        f" frame rate {'unlimited' if frame_rate is None else number(frame_rate, ' fps')},"
        f" binning {detector['current_binning']},"
        f" roi {'full sensor' if roi is None else roi},"
        f" image {detector['width']} x {detector['height']}"
    )


# ====================
# Console
# ====================


class Console:
    """The menu. Works on one chosen detector at a time."""

    def __init__(self, client: BackendClient) -> None:
        """Start without a chosen detector; `run` asks for one first."""
        self.client = client
        self.slot = 0
        self.activated_by_start: set[int] = set()
        """Slots that `start` activated; `stop` deactivates them again."""

    def run(self) -> None:
        """Choose a detector, then serve the menu until ``q``."""
        state = self.client.camera_state()
        if not state["detectors"]:
            show("No detectors configured.")
            return
        self.choose_detector(state)
        actions: dict[str, Callable[[Json], None]] = {
            "1": self.show_status,
            "2": self.toggle_activation,
            "3": self.toggle_live,
            "4": self.change_settings,
            "5": self.choose_detector,
        }
        while True:
            try:
                state = self.client.camera_state()
            except httpx.HTTPError as exc:
                show(f"  ! reading CameraState failed: {exc}")
                if ask("  Enter retries, q quits: ", str).lower() == "q":
                    return
                continue
            choice = ask(self.menu(state), lambda text: self._menu_choice(text, actions))
            if choice == "q":
                return
            try:
                actions[choice](state)
            except (ActionError, httpx.HTTPError, ValueError) as exc:
                show(f"  ! {exc}")

    @staticmethod
    def _menu_choice(text: str, actions: dict[str, Callable[[Json], None]]) -> str:
        """The menu key, ``q`` included."""
        if text.lower() == "q" or text in actions:
            return text.lower()
        raise ValueError("choose 1-5 or q")

    def menu(self, state: Json) -> str:
        """The menu text, with the actions that fit the chosen detector's status."""
        detector = find_detector(state, self.slot)
        live = is_live(state, detector)
        return (
            f"\n--- slot {self.slot}: {detector['name']}"
            f" (activated: {yes_no(detector['is_active'])}, acquiring: {yes_no(live)}) ---\n"
            "  1  status of all detectors\n"
            f"  2  {'deactivate' if detector['is_active'] else 'activate'}\n"
            f"  3  {'stop' if live else 'start'}\n"
            "  4  settings (exposure, gain, frame rate, binning, roi)\n"
            "  5  choose another detector\n"
            "  q  quit\n"
            "> "
        )

    def choose_detector(self, state: Json) -> None:
        """List the detectors and ask which one to work on."""
        show("\nDetectors:")
        for detector in state["detectors"]:
            show(f"  {describe(state, detector)}  model: {detector['model'] or '?'}")
        slots = [detector["slot"] for detector in state["detectors"]]

        def parse_slot(text: str) -> int:
            if not text and len(slots) == 1:
                return slots[0]
            slot = int(text)
            find_detector(state, slot)
            return slot

        self.slot = ask(f"Slot {slots}: ", parse_slot)

    def show_status(self, state: Json) -> None:
        """Print every detector; the chosen one is marked."""
        show(f"\nlive view: {'on' if state['is_acquiring'] else 'off'}")
        for detector in state["detectors"]:
            marker = "*" if detector["slot"] == self.slot else " "
            show(f" {marker} {describe(state, detector)}")

    def toggle_activation(self, state: Json) -> None:
        """Activate the chosen detector, or deactivate it when it is active."""
        active = find_detector(state, self.slot)["is_active"]
        action = "deactivate_detector" if active else "activate_detector"
        self.activated_by_start.discard(self.slot)
        self.run_step(Step(action, {"slot": self.slot}))

    def toggle_live(self, state: Json) -> None:
        """Start the chosen detector, or stop it when it streams (see `plan_start`/`plan_stop`)."""
        if is_live(state, find_detector(state, self.slot)):
            steps, also_stopped = plan_stop(state, self.slot, self.slot in self.activated_by_start)
            if also_stopped:
                show(f"  note: the live view is global, slots {also_stopped} stop as well")
            for step in steps:
                self.run_step(step)
            self.activated_by_start.discard(self.slot)
        else:
            for step in plan_start(state, self.slot):
                self.run_step(step)
                if step.action == "activate_detector":
                    self.activated_by_start.add(self.slot)

    def change_settings(self, state: Json) -> None:
        """Ask for each setting (Enter keeps it) and send them in one update_detector."""
        detector = find_detector(state, self.slot)
        show(f"\nnow: {describe_settings(detector)}")
        show("Enter keeps a value.")
        changes: dict[str, object] = {}

        def setting(key: str, can_set: str, prompt: str, parse: Callable[[str], object]) -> None:
            if not detector[can_set]:
                show(f"  {key}: cannot be set on this detector")
                return
            value = ask(f"  {prompt}: ", parse)
            if value is not None:
                changes[key] = value

        frame_rate = detector["current_frame_rate"]
        roi = detector["current_roi"]
        setting(
            "exposure_time",
            "can_set_exposure",
            f"exposure time [s] ({number(detector['min_exposure_time'])} .. "
            f"{number(detector['max_exposure_time'])}, now "
            f"{number(detector['current_exposure_time'])})",
            parse_optional_float,
        )
        setting(
            "gain",
            "can_set_gain",
            f"gain ({number(detector['min_gain'])} .. {number(detector['max_gain'])}, now "
            f"{number(detector['current_gain'])})",
            parse_optional_float,
        )
        setting(
            "frame_rate",
            "can_set_frame_rate",
            f"frame rate [fps] ({number(detector['min_frame_rate'])} .. "
            f"{number(detector['max_frame_rate'])}, 0 = unlimited, now "
            f"{'unlimited' if frame_rate is None else number(frame_rate)})",
            parse_optional_float,
        )
        setting(
            "binning",
            "can_set_binning",
            f"binning ({', '.join(str(b) for b in detector['available_binnings'])};"
            f" now {detector['current_binning']})",
            parse_optional_int,
        )
        setting(
            "roi",
            "can_set_roi",
            f"roi x y width height (sensor {detector['sensor_width']} x "
            f"{detector['sensor_height']}, 'full' = whole sensor, now "
            f"{'full' if roi is None else ' '.join(str(v) for v in roi)})",
            parse_roi,
        )
        if not changes:
            show("  nothing changed")
            return
        result = self.run_step(Step("update_detector", {"slot": self.slot, **changes}))
        if isinstance(result, dict):
            show(f"  applied: {describe_settings(result)}")

    def run_step(self, step: Step) -> object:
        """Call the action, then wait until CameraState shows its effect."""
        show(f"  -> {step}")
        result = self.client.call(step.action, **step.args)
        deadline = time.monotonic() + STATE_TIMEOUT_S
        while not step_done(self.client.camera_state(), step, result):
            if time.monotonic() >= deadline:
                show(f"  ! CameraState does not show {step.action} after {STATE_TIMEOUT_S:g} s")
                break
            time.sleep(POLL_INTERVAL_S)
        return result


# ====================
# Main
# ====================


def start_backend(host: str, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    """Build the app as main.py does and serve it in a background thread.

    Raises:
        SystemExit: The server stopped before it was up (e.g. the port is taken).
    """
    from newswitch.app import create_app, load_app_config

    app = create_app(load_app_config())
    # No access log: every call of the console would add a line (with --verbose: to its menu).
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="backend", daemon=True)
    thread.start()
    try:
        while not server.started:
            if not thread.is_alive():
                raise SystemExit("the backend did not start")
            time.sleep(POLL_INTERVAL_S)
    except KeyboardInterrupt:
        stop_backend(server, thread)
        raise
    return server, thread


def stop_backend(server: uvicorn.Server, thread: threading.Thread) -> None:
    """Shut the server down, so the shutdown hooks run; a second Ctrl+C forces it."""
    server.should_exit = True
    try:
        thread.join()
    except KeyboardInterrupt:
        server.force_exit = True
        thread.join(timeout=10.0)


def main(argv: list[str] | None = None) -> int:
    """Entry point: divert the backend's output unless ``--verbose``, then `serve_console`.

    Errors that end the console show up in the terminal as one line, their traceback goes to
    the log.
    """
    global _terminal
    parser = argparse.ArgumentParser(
        prog="backend_cli.py",
        description="Start the backend and drive its detectors from the terminal.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=f"show the backend's output in the terminal instead of writing it to {LOG_FILE}",
    )
    args = parser.parse_args(argv)
    log_file = None if args.verbose else LOG_FILE
    if log_file is not None:
        _terminal = divert_backend_output(log_file)
        show(f"Backend output goes to {log_file}")
    try:
        serve_console()
    except KeyboardInterrupt:
        show()
        return 130
    except SystemExit as exc:
        if not isinstance(exc.code, str):
            raise
        report_failure(exc.code, log_file)
        return 1
    except Exception as exc:
        traceback.print_exc()
        report_failure(f"{type(exc).__name__}: {exc}", log_file)
        return 1
    return 0


def report_failure(message: str, log_file: Path | None) -> None:
    """Show why the console ended, and where the details are."""
    show(f"! {message}")
    if log_file is not None:
        show(f"  details: {log_file}")


def serve_console() -> None:
    """Backend up, log in, console, backend down."""
    host = os.environ.get("BACKEND_HOST", "0.0.0.0")
    port = int(os.environ.get("BACKEND_PORT", "8099"))
    base_url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::', '') else host}:{port}"
    server, thread = start_backend(host, port)
    show(f"Backend on {base_url}")
    try:
        client = BackendClient(base_url, login(base_url))
        try:
            show("Waiting for the backend to set up the devices...")
            client.wait_until_ready()
            client.connect()
            Console(client).run()
        finally:
            client.close()
    except (KeyboardInterrupt, EOFError):
        show()
    finally:
        show("Shutting the backend down...")
        stop_backend(server, thread)


if __name__ == "__main__":
    raise SystemExit(main())
