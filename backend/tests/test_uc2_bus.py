"""Tests for the UC2 hardware bus layer (virtual transport + event dispatch)."""

import asyncio

import pytest
from koil import Koil

from newswitch.actions.uc2 import home_objective
from newswitch.drivers.uc2.actuators import Stepper, StepperConfig, Turret
from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.drivers.uc2.dispatch import apply_uc2_event
from newswitch.drivers.uc2.virtual_bus import VirtualUC2Bus, VirtualUC2BusConfig
from newswitch.instrument import spec
from newswitch.models.uc2 import BusError, EStopChanged, MotionDone, NodeSeen, PositionUpdate
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.services.values import Values
from newswitch.states.uc2 import UC2State
from newswitch.states.values import MoveState, SourceState, SwapState, TuneState
from newswitch.reference import REFERENCE_INSTRUMENT


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


def test_apply_uc2_event_updates_states() -> None:
    """Dispatch mirrors hardware events into what moved and the bus state, by the axis of each."""
    bus = make_virtual_bus()
    values = Values(
        spec.load(REFERENCE_INSTRUMENT),
        MoveState(),
        SwapState(),
        TuneState(),
        SourceState(),
        {
            "stage.x": Stepper(bus, StepperConfig(axis="X", steps_per_um=3.2), None),
            "stage.z": Stepper(bus, StepperConfig(axis="Z", steps_per_um=3.2), None),
        },
    )
    uc2_state = UC2State()

    apply_uc2_event(PositionUpdate(axis="X", position=42.0), values, uc2_state)
    assert values["stage.x"] == pytest.approx(42.0)
    assert values.move_state.moves["stage"]["x"].current == pytest.approx(42.0)

    apply_uc2_event(MotionDone(axis="Z", position=-7.5), values, uc2_state)
    assert values["stage.z"] == pytest.approx(-7.5)

    apply_uc2_event(EStopChanged(active=True), values, uc2_state)
    assert uc2_state.estop_active is True

    apply_uc2_event(NodeSeen(node_id=11, nmt_state=5), values, uc2_state)
    apply_uc2_event(NodeSeen(node_id=11, nmt_state=5), values, uc2_state)
    assert uc2_state.nodes_online == [11]

    apply_uc2_event(BusError(message="boom"), values, uc2_state)
    assert uc2_state.last_error == "boom"


def test_what_moved_by_itself_reaches_the_optics() -> None:
    """A spontaneous move is known about like a commanded one, or what is published goes stale."""
    bus = make_virtual_bus()
    values = Values(
        spec.load(REFERENCE_INSTRUMENT),
        MoveState(),
        SwapState(),
        TuneState(),
        SourceState(),
        {"stage.z": Stepper(bus, StepperConfig(axis="Z", steps_per_um=3.2), None)},
    )
    told: list[float] = []
    values.on_change = lambda: told.append(values["stage.z"])
    apply_uc2_event(MotionDone(axis="Z", position=-7.5), values, UC2State())
    assert told == [-7.5]


def test_homing_the_objective_changer_says_where_it_is_now() -> None:
    """Its first slot, whichever it was on: the board does not report it."""
    bus = make_virtual_bus()
    values = Values(
        spec.load(REFERENCE_INSTRUMENT),
        MoveState(),
        SwapState(),
        TuneState(),
        SourceState(),
        {"objective.slot": Turret(bus)},
    )
    values.stepped("objective.slot", 2)
    with Koil():
        home_objective(bus, values)
    assert values.swap_state.swaps["objective"]["slot"].current == 1
