"""YAML-to-driver integration with fake hardware: no port is opened by these tests."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from rekuest_next.state.lock import acquired_locks

from newswitch.config_io import parse_tree, ConfigError
from newswitch.managers.uc2.yaml_runtime import YamlUC2Bus
from newswitch.managers.uc2.canopen_bus import UC2CanBus
from newswitch.managers.uc2.rest_bus import UC2RestBus
from newswitch.managers.uc2.illumination_manager import UC2IlluminationManager
from newswitch.protocols.illumination import IlluminationState
from newswitch.protocols.uc2 import UC2State, UC2BusManager, HomingChanged, PositionUpdate

DEMOS = Path(__file__).parent.parent / "configs" / "demos"


def document(mode: str = "canopen") -> dict:
    """Return an independent demo so tests may alter addresses and settings."""
    return yaml.safe_load((DEMOS / f"uc2-{mode}.yaml").read_text())


def runtime(doc: dict | str = "canopen") -> YamlUC2Bus:
    """Validate through the real config pipeline, then build unopened drivers."""
    return YamlUC2Bus(parse_tree(document(doc) if isinstance(doc, str) else doc), UC2State())


def attach(driver: UC2CanBus | UC2RestBus, **methods: object) -> SimpleNamespace:
    """Make a fake client immediately available without the connection loop."""
    client = SimpleNamespace(**methods)
    driver._client = client
    driver.state.connected = True
    driver._connected.set()
    return client


@pytest.mark.parametrize("mode,driver", [("serial", UC2RestBus), ("canopen", UC2CanBus)])
def test_demos_pool_connections_and_start_off(mode: str, driver: type) -> None:
    """Application slots stay independent of channels, nodes and spectral count."""
    bus = runtime(mode)
    assert isinstance(bus, UC2BusManager)
    assert len(bus.buses) == 1
    assert isinstance(next(iter(bus.buses.values())), driver)
    assert list(bus.axes) == ["X", "Z"]
    assert bus.stage_config.home_axes == ["Z", "X"]
    assert len(bus.lights) == 3
    assert all(s.intensity == 0 and not s.is_active for s in bus.illumination_config.sources)
    assert [s.channel for s in bus.illumination_config.sources] == [1, 2, 3]


@pytest.mark.asyncio
async def test_can_mapping_drives_custom_node_subaxis_and_motion_parameters() -> None:
    """Changing YAML changes the actual client arguments, including mechanical scaling."""
    doc = document()
    d = doc["devices"]
    mapping = d["my-hat-board-via-can"]["mapping"]
    mapping["my-first-axis"].update(id=44, subid=2)
    d["my-first-axis"].update(move_timeout_s=7)
    d["my-first-axis"]["acc"] = {"value": 1000, "unit": "um/s**2"}
    bus = runtime(doc)
    route = bus.axes["X"]
    route.homed = True
    done, started = asyncio.Event(), asyncio.Event()

    async def move(**kwargs: object) -> int:
        assert kwargs == dict(
            axis=2,
            position=800,
            speed=40000,
            acceleration=8000,
            is_absolute=True,
            node_id=44,
            timeout=7,
        )
        started.set()
        await done.wait()
        return 800

    attach(route.bus, move_and_wait=move)
    task = asyncio.create_task(bus.amove_axis("X", 100, is_absolute=True))
    await asyncio.wait_for(started.wait(), 1)
    assert not task.done()
    done.set()
    assert await task == 100


@pytest.mark.asyncio
async def test_serial_motor_id_is_independent_of_logical_direction() -> None:
    """Logical X can map to master stepper 2 without accidentally sending stepper 1."""
    doc = document("serial")
    doc["devices"]["my-standalone-board"]["mapping"]["my-first-axis"]["id"] = 2
    bus = runtime(doc)
    bus.axes["X"].homed = True
    client = attach(
        bus.axes["X"].bus,
        move_axis=AsyncMock(return_value=[{"done": 1}]),
        get_positions=AsyncMock(return_value=[0, 0, 800, 0]),
    )
    assert await bus.amove_axis("X", 100, is_absolute=True) == 100
    assert client.move_axis.await_args.kwargs["axis"] == "Y"
    assert client.move_axis.await_args.kwargs["steps"] == 800


@pytest.mark.asyncio
async def test_light_routes_and_matrix_commands() -> None:
    """Individual light mappings, not a global default node, drive PWM/RGB."""
    doc = document()
    m = doc["devices"]["my-hat-board-via-can"]["mapping"]
    m["my-laser-serial"].update(id=31, subid=2, pwm_max=4095)
    m["led-matrix"]["id"] = 35
    bus = runtime(doc)
    driver = next(iter(bus.buses.values()))
    c = attach(driver, laser_set=AsyncMock(), led_fill=AsyncMock(), led_off=AsyncMock())
    await bus.aset_laser(1, 2048)
    c.laser_set.assert_awaited_once_with(channel=2, pwm=2048, node_id=31)
    await bus.aset_laser(2, 100)
    c.laser_set.assert_awaited_with(channel=0, pwm=100, node_id=21)
    await bus.aset_laser(3, 64)
    c.led_fill.assert_awaited_with(r=64, g=64, b=64, node_id=35)
    await bus.aled_fill(10, 20, 30)
    c.led_fill.assert_awaited_with(r=10, g=20, b=30, node_id=35)
    await bus.aled_off()
    c.led_off.assert_awaited_once_with(node_id=35)
    with pytest.raises(ValueError, match="PWM"):
        await bus.aset_laser(1, 4096)


@pytest.mark.asyncio
async def test_serial_pwm_and_matrix_use_distinct_commands() -> None:
    """Serial light channels and RGB matrix calls use separate APIs."""
    bus = runtime("serial")
    c = attach(next(iter(bus.buses.values())), set_laser=AsyncMock(), led_fill=AsyncMock())
    await bus.aset_laser(2, 512)
    c.set_laser.assert_awaited_once_with(channel=3, value=512)
    await bus.aled_fill(2, 4, 8)
    c.led_fill.assert_awaited_once_with(r=2, g=4, b=8)


def test_intensity_manager_uses_mapping_pwm_range() -> None:
    """A logical 50 percent becomes the configured half-scale PWM value."""
    import koil

    doc = document()
    doc["devices"]["my-hat-board-via-can"]["mapping"]["my-laser-serial"]["pwm_max"] = 4095
    bus = runtime(doc)
    bus.aset_laser = AsyncMock()
    with koil.Koil(), acquired_locks("illumination"):
        manager = UC2IlluminationManager(IlluminationState(), bus, bus.illumination_config)
        manager.set_intensity(50, channel=1)
    bus.aset_laser.assert_awaited_once_with(1, 2048)


@pytest.mark.asyncio
async def test_homing_required_and_can_settings() -> None:
    """Homing gates movement and passes the per-axis firmware parameters."""
    doc = document()
    doc["devices"]["my-first-axis"].update(
        homing_speed_steps=8000, homing_direction=1, homing_timeout_ms=4000
    )
    bus = runtime(doc)
    with pytest.raises(ValueError, match="must be homed"):
        await bus.amove_axis("X", 1, is_absolute=True)
    c = attach(bus.axes["X"].bus, home_and_wait=AsyncMock(return_value=True))
    await bus.ahome_axis("X")
    assert bus.axes["X"].homed
    c.home_and_wait.assert_awaited_once_with(
        axis=0, speed=8000, direction=1, timeout_ms=4000, node_id=11, timeout=14
    )


@pytest.mark.asyncio
async def test_serial_home_acknowledgement_is_not_completion() -> None:
    """An acknowledgement does not establish that homing has finished."""
    bus = runtime("serial")
    driver = bus.axes["X"].bus
    ack = asyncio.Event()

    async def call(*args: object, **kwargs: object) -> list:
        assert kwargs["axis"] == 1
        ack.set()
        return [{"return": 1}]

    attach(
        driver,
        call=call,
        stop=AsyncMock(),
        sync=SimpleNamespace(home=SimpleNamespace(home=lambda: None)),
    )
    task = asyncio.create_task(bus.ahome_axis("X"))
    await asyncio.wait_for(ack.wait(), 1)
    assert not task.done()
    driver._broker.publish(HomingChanged(axis="X", status=2))
    await asyncio.wait_for(task, 1)
    assert bus.axes["X"].homed


@pytest.mark.asyncio
async def test_inversion_limits_and_unknown_axes() -> None:
    """Limits reject invalid commands before dispatch and inversion is applied."""
    doc = document()
    doc["devices"]["my-first-axis"]["inverted"] = True
    bus = runtime(doc)
    r = bus.axes["X"]
    r.homed = True
    r.bus.amove_axis = AsyncMock(return_value=-5)
    with pytest.raises(ValueError, match="travel limits"):
        await bus.amove_axis("X", 100001, is_absolute=True)
    r.bus.amove_axis.assert_not_awaited()
    assert await bus.amove_axis("X", 5, is_absolute=True) == 5
    assert r.bus.amove_axis.await_args.args == ("X", -5)
    with pytest.raises(ValueError, match="not configured"):
        await bus.amove_axis("Y", 1)


@pytest.mark.asyncio
async def test_two_commands_on_one_axis_are_serialized() -> None:
    """A second command cannot overtake a running command on the same motor."""
    bus = runtime()
    r = bus.axes["X"]
    r.homed = True
    started, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def move(axis: str, target: float, **kwargs: object) -> float:
        calls.append(target)
        started.set()
        await finish.wait()
        return target

    r.bus.amove_axis = move
    first = asyncio.create_task(bus.amove_axis("X", 1, is_absolute=True))
    await asyncio.wait_for(started.wait(), 1)
    second = asyncio.create_task(bus.amove_axis("X", 2, is_absolute=True))
    await asyncio.sleep(0)
    assert calls == [1]
    finish.set()
    await asyncio.gather(first, second)
    assert calls == [1, 2]


@pytest.mark.parametrize("mode", ["serial", "canopen"])
@pytest.mark.asyncio
async def test_real_startup_constructs_only_configured_devices(mode: str, tmp_path: Path) -> None:
    """Exercise the app's real startup hook, leaving client background loops stopped."""
    from newswitch.app import ImswitchConfig, provide_managers
    from newswitch.protocols.detector import CameraState

    path = tmp_path / "machine.yaml"
    path.write_text(yaml.safe_dump(document(mode)))
    results = await provide_managers(ImswitchConfig(config_file=path, use_virtual_microscope=False))
    router = next(item for item in results if isinstance(item, YamlUC2Bus))
    assert set(router.axes) == {"X", "Z"}
    cameras = next(item for item in results if isinstance(item, CameraState))
    assert cameras.detectors == []
    assert not path.with_name("machine.persistent.yaml").exists()


def test_serial_motor_and_light_namespaces_allow_same_id() -> None:
    """A laser and motor share ID 1; duplicate lasers remain an error."""
    doc = document("serial")
    doc["devices"]["my-standalone-board"]["mapping"]["my-laser-serial"]["id"] = 1
    bus = runtime(doc)
    assert bus.axes["X"].hardware_axis == "X"
    assert bus.lights[1].binding.id == 1
    doc["devices"]["my-standalone-board"]["mapping"]["top-illumination-LED"]["id"] = 1
    with pytest.raises(ConfigError, match="is used by"):
        runtime(doc)


@pytest.mark.parametrize(
    "change,match",
    [
        ("missing", "no controller mapping"),
        ("bridge", "no defined master-ID"),
        ("node", "1..127"),
        ("motor", "0..3"),
        ("kind", "incompatible"),
    ],
)
def test_invalid_mappings_fail_before_hardware_opens(change: str, match: str) -> None:
    """Ambiguous and unsupported addressing never opens a device."""
    doc = document("serial" if change == "bridge" else "canopen")
    controller = doc["devices"][
        "my-standalone-board" if change == "bridge" else "my-hat-board-via-can"
    ]
    mapping = controller["mapping"]
    if change == "missing":
        del mapping["my-first-axis"]
    elif change == "bridge":
        mapping["my-first-axis"].update(type="canopen-motor", id=0, subid=2)
    elif change == "node":
        mapping["my-first-axis"]["id"] = 0
    elif change == "motor":
        mapping["my-first-axis"]["subid"] = 4
    elif change == "kind":
        mapping["my-first-axis"].update(type="serial-motor")
    with pytest.raises(ValueError, match=match):
        runtime(doc)


@pytest.mark.asyncio
async def test_stage_axes_can_use_different_controllers() -> None:
    """One stage has X on Serial, Z on CAN, and lights share the CAN connection."""
    doc = document("serial")
    d = doc["devices"]
    m = d["my-standalone-board"]["mapping"]
    del m["my-second-axis"]
    for key in ["my-laser-serial", "top-illumination-LED", "led-matrix"]:
        del m[key]
    can = deepcopy(document()["devices"]["my-hat-board-via-can"])
    del can["mapping"]["my-first-axis"]
    d["direct-can"] = can
    bus = runtime(doc)
    assert len(bus.buses) == 2
    assert isinstance(bus.axes["X"].bus, UC2RestBus)
    assert isinstance(bus.axes["Z"].bus, UC2CanBus)
    assert bus.axes["Z"].bus is bus.lights[1].bus
    attach(bus.axes["X"].bus, get_positions=AsyncMock(return_value=[0, 80, 0, 0]))
    attach(bus.axes["Z"].bus, get_position=AsyncMock(return_value=160))
    assert await bus.aget_position("X") == 10
    assert await bus.aget_position("Z") == 20


@pytest.mark.asyncio
async def test_serial_event_is_remapped_to_logical_axis() -> None:
    """Feedback follows the mapping in the reverse direction."""
    doc = document("serial")
    doc["devices"]["my-standalone-board"]["mapping"]["my-first-axis"]["id"] = 2
    bus = runtime(doc)
    driver = bus.axes["X"].bus
    event_task = asyncio.create_task(bus._forward(driver))
    result = asyncio.create_task(anext(bus.subscribe()))
    await asyncio.sleep(0)
    driver._broker.publish(PositionUpdate(axis="Y", position=14))
    try:
        event = await asyncio.wait_for(result, 1)
        assert event == PositionUpdate(axis="X", position=14)
    finally:
        event_task.cancel()
        await asyncio.gather(event_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_connection_initialization_switches_outputs_off() -> None:
    """Reconnect disables configured outputs and invalidates reference state."""
    bus = runtime()
    driver = bus.axes["X"].bus
    c = attach(driver, laser_set=AsyncMock(), led_off=AsyncMock())
    bus.axes["X"].homed = True
    await driver.on_connected()
    assert not bus.axes["X"].homed
    c.laser_set.assert_any_await(channel=1, pwm=0, node_id=21)
    c.laser_set.assert_any_await(channel=0, pwm=0, node_id=21)
    c.led_off.assert_awaited_once_with(node_id=20)


@pytest.mark.asyncio
async def test_movement_timeout_stops_motor_and_invalidates_homing() -> None:
    """The YAML deadline caps the client and attempts a stop before releasing the axis."""
    doc = document()
    doc["devices"]["my-first-axis"]["move_timeout_s"] = 0.01
    bus = runtime(doc)
    route = bus.axes["X"]
    route.homed = True

    async def wait_forever(**kwargs: object) -> int:
        await asyncio.Event().wait()

    client = attach(route.bus, move_and_wait=wait_forever, stop=AsyncMock())
    with pytest.raises(TimeoutError):
        await bus.amove_axis("X", 5, is_absolute=True)
    client.stop.assert_awaited_once_with(axis=0, node_id=11)
    assert not route.homed


@pytest.mark.asyncio
async def test_cancellation_stops_motor_without_waiting_for_axis_lock() -> None:
    """A cancelled command stops the same physical motor it started."""
    bus = runtime()
    route = bus.axes["X"]
    route.homed = True
    started = asyncio.Event()

    async def wait_forever(**kwargs: object) -> int:
        started.set()
        await asyncio.Event().wait()

    client = attach(route.bus, move_and_wait=wait_forever, stop=AsyncMock())
    task = asyncio.create_task(bus.amove_axis("X", 5, is_absolute=True))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.stop.assert_awaited_once_with(axis=0, node_id=11)
    assert not route.homed


@pytest.mark.asyncio
async def test_serial_empty_completion_and_invalid_position_are_errors() -> None:
    """Missing hardware responses are not converted to invented success or zero."""
    bus = runtime("serial")
    route = bus.axes["X"]
    route.homed = True
    client = attach(
        route.bus,
        move_axis=AsyncMock(return_value=[]),
        stop=AsyncMock(),
        get_positions=AsyncMock(return_value=None),
    )
    with pytest.raises(RuntimeError, match="no completion"):
        await bus.amove_axis("X", 5, is_absolute=True)
    with pytest.raises(RuntimeError, match="Invalid position"):
        await bus.aget_position("X")
    client.stop.assert_awaited_once_with(axis="X")


def test_controllers_on_same_physical_can_link_share_client() -> None:
    """Two logical controllers do not open the same CAN interface twice."""
    doc = document()
    original = doc["devices"]["my-hat-board-via-can"]
    second = deepcopy(original)
    second["mapping"] = {"my-laser-serial": original["mapping"].pop("my-laser-serial")}
    doc["devices"]["second-controller"] = second
    bus = runtime(doc)
    assert len(bus.buses) == 1
    assert bus.lights[1].bus is bus.axes["X"].bus


def test_duplicate_outputs_across_controllers_on_shared_bus_are_rejected() -> None:
    """Resource pooling also validates addresses across controller boundaries."""
    doc = document()
    original = doc["devices"]["my-hat-board-via-can"]
    second = deepcopy(original)
    original["mapping"].pop("top-illumination-LED")
    second["mapping"] = {"top-illumination-LED": deepcopy(original["mapping"]["my-laser-serial"])}
    doc["devices"]["second-controller"] = second
    with pytest.raises(ValueError, match="already mapped"):
        runtime(doc)


@pytest.mark.asyncio
async def test_driver_initializes_outputs_before_publishing_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real connection lifecycle invokes output reset and closes its client on cancellation."""
    AsyncUC2Client = pytest.importorskip("uc2canopen.aio").AsyncUC2Client

    bus = runtime()
    driver = bus.axes["X"].bus
    initialized = asyncio.Event()

    async def set_light(**kwargs: object) -> None:
        assert not driver._connected.is_set()
        assert not driver.state.connected

    async def events() -> AsyncIterator[object]:
        initialized.set()
        await asyncio.Event().wait()
        yield None

    client = SimpleNamespace(
        sync=object(),
        laser_set=AsyncMock(side_effect=set_light),
        led_off=AsyncMock(),
        events=events,
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(AsyncUC2Client, "create", AsyncMock(return_value=client))
    background = asyncio.create_task(driver._connect_and_pump())
    try:
        await asyncio.wait_for(initialized.wait(), 1)
        assert driver.state.connected
        assert driver._connected.is_set()
        assert client.laser_set.await_count == 2
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)
    assert not driver.state.connected
    assert not driver._connected.is_set()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_initialization_closes_link_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed startup write leaves the bus unavailable and the client closed."""
    AsyncUC2Client = pytest.importorskip("uc2canopen.aio").AsyncUC2Client

    bus = runtime()
    driver = bus.axes["X"].bus
    client = SimpleNamespace(
        sync=object(),
        laser_set=AsyncMock(side_effect=ConnectionError("write failed")),
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(AsyncUC2Client, "create", AsyncMock(return_value=client))
    with pytest.raises(ConnectionError, match="write failed"):
        await driver._connect_and_pump()
    assert not driver.state.connected
    assert not driver._connected.is_set()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_emergency_stop_blocks_move_before_dispatch() -> None:
    """A latched e-stop prevents even non-homing-required axes from starting."""
    bus = runtime()
    route = bus.axes["Z"]
    route.bus.state.estop_active = True
    route.bus.amove_axis = AsyncMock()
    with pytest.raises(RuntimeError, match="Emergency stop"):
        await bus.amove_axis("Z", 1, is_absolute=True)
    route.bus.amove_axis.assert_not_awaited()


@pytest.mark.asyncio
async def test_custom_yaml_selection_and_writeback_preserve_static_file(tmp_path: Path) -> None:
    """An explicit demo path wins over base settings and writes only a persistent sibling."""
    from newswitch.app import ImswitchConfig, save_device_config
    from newswitch.protocols.detector import CameraState
    from newswitch.protocols.objective import ObjectiveState
    from newswitch.protocols.filter_bank import FilterBankState
    from newswitch.protocols.stage import StageState

    source = tmp_path / "my-machine.yaml"
    original = yaml.safe_dump(document())
    source.write_text(original)
    settings = ImswitchConfig(config_file=source)
    assert settings.open_device_config().path == source
    save_device_config(settings, CameraState(), ObjectiveState(), FilterBankState(), StageState())
    assert source.read_text() == original
    assert (tmp_path / "my-machine.persistent.yaml").exists()


def test_entrypoint_selects_device_yaml_and_rejects_legacy_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real entrypoint honors YAML selection without constructing an actual app."""
    import importlib.util
    import newswitch.app as app_module

    monkeypatch.setattr(app_module, "create_app", lambda config: config)
    source = tmp_path / "instrument.yaml"
    source.write_text(yaml.safe_dump(document()))
    monkeypatch.setenv("NEWSWITCH_CONFIG", str(source))
    monkeypatch.setenv("NEWSWITCH_MODE", "hardware")
    spec = importlib.util.spec_from_file_location(
        "yaml_entrypoint_test", DEMOS.parents[1] / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.app.use_virtual_microscope is False
    assert module.app.config_file == source
    assert module.app.persistent_config_path == tmp_path / "instrument.persistent.yaml"
    monkeypatch.setenv("NEWSWITCH_CONFIG", str(tmp_path / "legacy.json"))
    with pytest.raises(ValueError, match="YAML"):
        module.load_config()


@pytest.mark.asyncio
async def test_parallel_homing_and_sibling_cancellation() -> None:
    """Model null order starts homing together; a failed operation cancels its sibling."""
    from newswitch.managers.uc2.stage_manager import UC2StageManager
    from newswitch.protocols.stage import StageState

    doc = document()
    doc["devices"]["just-some-boring-stage"]["homing_order"] = None
    bus = runtime(doc)
    started = set()
    both = asyncio.Event()
    cancelled = asyncio.Event()

    async def home(axis: str) -> None:
        started.add(axis)
        if len(started) == 2:
            both.set()
        await both.wait()
        if axis == "X":
            raise RuntimeError("home failed")
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    bus.ahome_axis = home
    manager = UC2StageManager(StageState(), bus, bus.stage_config)
    with pytest.raises(RuntimeError, match="home failed"):
        await asyncio.wait_for(manager._ahome(), 1)
    assert started == {"X", "Z"}
    assert cancelled.is_set()


def test_duplicate_logical_direction_is_rejected() -> None:
    """Different casing cannot silently replace a configured logical axis."""
    doc = document()
    stage = doc["devices"]["just-some-boring-stage"]
    stage["axes"]["X"] = stage["axes"].pop("z")
    stage["homing_order"] = ["x", "X"]
    with pytest.raises(ValueError, match="Duplicate logical"):
        runtime(doc)


def test_serial_selectors_resolving_same_port_share_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Different selector spellings cannot open the same Serial device twice."""
    doc = document("serial")
    original = doc["devices"]["my-standalone-board"]
    second = deepcopy(original)
    second["connection"]["transport"].pop("port")
    second["connection"]["transport"]["port_pattern"] = "/dev/serial/by-id/*"
    second["mapping"] = {"my-laser-serial": original["mapping"].pop("my-laser-serial")}
    doc["devices"]["second-controller"] = second
    monkeypatch.setattr(
        "newswitch.managers.uc2.yaml_runtime.glob.glob", lambda pattern: ["/dev/ttyUSB0"]
    )
    bus = runtime(doc)
    assert len(bus.buses) == 1
    assert bus.lights[1].bus is bus.axes["X"].bus


@pytest.mark.asyncio
@pytest.mark.parametrize("with_motion", [False, True])
async def test_camera_selection_coexists_with_yaml_hardware(
    with_motion: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Startup retains main's camera selection alongside mapped motion and illumination."""
    import sys
    from newswitch.app import ImswitchConfig, provide_managers, close_detector

    doc = document() if with_motion else {"newswitch_version": "v1.0.2", "devices": {}}
    doc["devices"].update(
        {
            "camera-controller": {
                "type": "controller",
                "connection": {"protocol": "usb3-vision"},
                "mapping": {"camera": {"type": "usb3-vision-camera", "id": 0}},
            },
            "camera": {"type": "detector", "manufacturer": "Simulated", "pixelcount": [64, 48]},
        }
    )
    selected = []

    def camera_manager(**kwargs: object) -> SimpleNamespace:
        kwargs["camera_state"].detectors = kwargs["cameras"]
        manager = SimpleNamespace(
            state=kwargs["camera_state"], close=lambda: selected.append("closed")
        )
        selected.append(kwargs)
        return manager

    monkeypatch.setitem(
        sys.modules,
        "newswitch.managers.uc2.uc2_detector",
        SimpleNamespace(UC2DetectorManager=camera_manager),
    )
    source = tmp_path / "combined.yaml"
    source.write_text(yaml.safe_dump(doc))
    settings = ImswitchConfig(
        config_file=source,
        use_virtual_microscope=False,
        camera_recording_dir=tmp_path / "recordings",
        camera_debug_window=False,
    )
    managers = await provide_managers(settings)
    router = next(value for value in managers if isinstance(value, YamlUC2Bus))
    assert set(router.axes) == ({"X", "Z"} if with_motion else set())
    assert len(router.lights) == (3 if with_motion else 0)
    assert selected[0]["recording_dir"] == tmp_path / "recordings"
    detector = next(
        value
        for value in managers
        if isinstance(value, SimpleNamespace) and hasattr(value, "close")
    )
    assert detector.state.detectors[0].manufacturer == "Simulated"
    close_detector(detector)
    assert selected[-1] == "closed"


def test_pi_profile_four_axes_and_one_led() -> None:
    """The physical Pi profile preserves four motor channels without a matrix."""
    doc = yaml.safe_load((DEMOS.parent / "machines" / "openuc2-first-cord-30059.yaml").read_text())
    bus = runtime(doc)
    assert set(bus.axes) == {"X", "Y", "Z", "A"}
    assert bus.axes["A"].hardware_axis == "A"
    assert bus.axes["A"].bus.config.steps_per_deg_a == pytest.approx(1 / 0.396)
    assert bus.stage_config.registered_step_sizes == [1, 10, 100]
    assert len(bus.lights) == 1
    assert bus.lights[1].pwm_max == 1023


@pytest.mark.asyncio
async def test_serial_home_passes_endstop_polarity() -> None:
    """Forward the configured switch polarity to the firmware home command."""
    doc = document("serial")
    doc["devices"]["my-first-axis"]["homing_endstop_polarity"] = -1
    bus = runtime(doc)
    driver = bus.axes["X"].bus

    async def call(*args: object, **kwargs: object) -> list:
        assert kwargs["endstoppolarity"] == -1
        driver._broker.publish(HomingChanged(axis="X", status=2))
        return [{"return": 1}]

    attach(
        driver,
        call=call,
        stop=AsyncMock(),
        sync=SimpleNamespace(home=SimpleNamespace(home=lambda: None)),
    )
    await asyncio.wait_for(bus.ahome_axis("X"), 1)


def test_serial_stable_symlink_resolves_for_uc2_port_lookup(tmp_path: Path) -> None:
    """The upstream client compares enumerated device paths, not persistent symlinks."""
    target = tmp_path / "ttyUSB0"
    target.touch()
    stable = tmp_path / "stable-usb"
    stable.symlink_to(target)
    doc = document("serial")
    doc["devices"]["my-standalone-board"]["connection"]["transport"]["port"] = str(stable)
    bus = runtime(doc)
    assert bus.axes["X"].bus.config.serialport == str(target)
