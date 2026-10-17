"""Tests for the UC2 hardware bus layer (virtual transport + event dispatch)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from rekuest_next.state.lock import acquired_locks

from newswitch.managers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.managers.uc2.rest_bus import UC2RestBusConfig
from newswitch.managers.uc2.dispatch import apply_uc2_event
from newswitch.managers.uc2.stage_manager import UC2StageConfig, UC2StageManager
from newswitch.managers.uc2.virtual_bus import VirtualUC2Bus, VirtualUC2BusConfig
from newswitch.protocols.stage import StageState
from newswitch.protocols.uc2 import (
    BusError,
    EStopChanged,
    MotionDone,
    NodeSeen,
    PositionUpdate,
    UC2BusManager,
    UC2State,
)


def make_virtual_bus() -> VirtualUC2Bus:
    """Create a fast-moving virtual bus for tests."""
    return VirtualUC2Bus(
        state=UC2State(),
        config=VirtualUC2BusConfig(default_speed=1_000_000.0, update_interval_s=0.001),
    )


def test_virtual_bus_satisfies_protocol() -> None:
    """The virtual bus structurally implements UC2BusManager."""
    assert isinstance(make_virtual_bus(), UC2BusManager)


def test_canopen_bus_satisfies_protocol() -> None:
    """The CANopen bus structurally implements UC2BusManager (no I/O needed)."""
    assert isinstance(UC2CanBus(state=UC2State()), UC2BusManager)


@pytest.mark.asyncio
async def test_virtual_move_emits_events_and_moves() -> None:
    """A simulated move ends at the target and emits telemetry + MotionDone."""
    bus = make_virtual_bus()
    events = []

    async def collect() -> None:
        async for event in bus.subscribe():
            events.append(event)
            if isinstance(event, MotionDone):
                return

    collector = asyncio.create_task(collect())
    await asyncio.sleep(0)  # let the collector subscribe first
    final = await bus.amove_axis("X", 100.0, is_absolute=True)
    await asyncio.wait_for(collector, timeout=2.0)

    assert final == pytest.approx(100.0)
    assert await bus.aget_position("X") == pytest.approx(100.0)
    assert any(isinstance(e, PositionUpdate) for e in events)
    done = [e for e in events if isinstance(e, MotionDone)]
    assert done and done[-1].position == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_virtual_relative_move() -> None:
    """Relative moves accumulate on top of the current position."""
    bus = make_virtual_bus()
    await bus.amove_axis("Z", 50.0, is_absolute=True)
    final = await bus.amove_axis("Z", -20.0, is_absolute=False)
    assert final == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_virtual_home_returns_to_zero() -> None:
    """Homing drives the axis back to zero."""
    bus = make_virtual_bus()
    await bus.amove_axis("Y", 500.0, is_absolute=True)
    await bus.ahome_axis("Y")
    assert await bus.aget_position("Y") == pytest.approx(0.0)


def test_canopen_unit_conversion_roundtrip() -> None:
    """Micrometer→steps→micrometer conversion respects per-axis scaling."""
    bus = UC2CanBus(
        state=UC2State(),
        config=UC2CanBusConfig(steps_per_um_x=12.5, steps_per_um_z=0.5),
    )
    assert bus.to_steps("X", 10.0) == 125
    assert bus.to_units("X", 125) == pytest.approx(10.0)
    assert bus.to_steps("Z", 10.0) == 5
    assert bus.node_for_axis("Y") == 12
    assert bus.axis_for_node(13) == "Z"
    assert bus.axis_for_node(99) is None


def test_uc2_stage_exposes_configured_jog_distances() -> None:
    """Hardware setups publish practical XY jog distances to the frontend."""
    stage_state = StageState()

    UC2StageManager(
        stage_state=stage_state,
        bus=make_virtual_bus(),
        config=UC2StageConfig(registered_step_sizes=[10.0, 100.0, 1000.0, 10000.0]),
    )

    assert stage_state.registered_step_sizes == [10.0, 100.0, 1000.0, 10000.0]


def test_uc2_stage_rejects_invalid_jog_distances() -> None:
    """Zero or negative jog distances cannot be exposed to the controls."""
    with pytest.raises(ValueError, match="positive values"):
        UC2StageManager(
            stage_state=StageState(),
            bus=make_virtual_bus(),
            config=UC2StageConfig(registered_step_sizes=[100.0, 0.0]),
        )


def test_apply_uc2_event_updates_states() -> None:
    """Dispatch mirrors hardware events into stage and bus states."""
    stage_state = StageState()
    uc2_state = UC2State()

    # StageState requires the stage_position lock for writes (as in dispatch).
    with acquired_locks("stage_position"):
        apply_uc2_event(PositionUpdate(axis="X", position=42.0), stage_state, uc2_state)
        assert stage_state.x == pytest.approx(42.0)

        apply_uc2_event(MotionDone(axis="Z", position=-7.5), stage_state, uc2_state)
    assert stage_state.z == pytest.approx(-7.5)

    apply_uc2_event(EStopChanged(active=True), stage_state, uc2_state)
    assert uc2_state.estop_active is True

    apply_uc2_event(NodeSeen(node_id=11, nmt_state=5), stage_state, uc2_state)
    apply_uc2_event(NodeSeen(node_id=11, nmt_state=5), stage_state, uc2_state)
    assert uc2_state.nodes_online == [11]

    apply_uc2_event(BusError(message="boom"), stage_state, uc2_state)
    assert uc2_state.last_error == "boom"


def test_shipped_config_files_load() -> None:
    """The example setup JSONs parse into ImswitchConfig and typed bus configs."""
    from newswitch.app import ImswitchConfig

    configs_dir = Path(__file__).parent.parent / "configs"

    serial_cfg = ImswitchConfig.model_validate_json((configs_dir / "uc2_serial.json").read_text())
    assert serial_cfg.use_virtual_microscope is False
    assert serial_cfg.uc2_transport == "rest"
    rest_kwargs: dict[str, Any] = {
        "serialport": serial_cfg.uc2_serial_port,
        "baudrate": serial_cfg.uc2_baudrate,
        **serial_cfg.uc2_rest,
    }
    rest_bus_cfg = UC2RestBusConfig(**rest_kwargs)
    assert rest_bus_cfg.serialport == "/dev/cu.SLAB_USBtoUART"
    assert rest_bus_cfg.baudrate == 921600
    assert rest_bus_cfg.require_master is True
    assert rest_bus_cfg.steps_per_um_x == pytest.approx(3.2)
    assert serial_cfg.uc2_stage["home_axes"] == ["Z", "X", "Y"]
    assert serial_cfg.uc2_stage["registered_step_sizes"] == [10.0, 100.0, 1000.0, 10000.0]
    assert len(serial_cfg.uc2_illumination["sources"]) == 3

    can_cfg = ImswitchConfig.model_validate_json((configs_dir / "uc2_canopen.json").read_text())
    assert can_cfg.uc2_transport == "canopen"
    can_kwargs: dict[str, Any] = {
        "interface": can_cfg.uc2_can_interface,
        "channel": can_cfg.uc2_can_channel,
        "port": can_cfg.uc2_can_port,
        **can_cfg.uc2_can,
    }
    can_bus_cfg = UC2CanBusConfig(**can_kwargs)
    assert can_bus_cfg.interface == "socketcan"
    assert can_bus_cfg.channel == "can0"
    assert can_bus_cfg.node_x == 11
    assert can_bus_cfg.node_galvo == 30
