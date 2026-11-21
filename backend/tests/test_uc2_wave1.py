"""Tests for the Wave-1 UC2 additions: reconnect, objective, filter, autofocus."""

import asyncio

import pytest

from newswitch.drivers.base import Driver
from newswitch.drivers.uc2.actuators import Turret, Wheel, WheelConfig
from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.drivers.uc2.virtual_bus import VirtualUC2Bus, VirtualUC2BusConfig
from newswitch.instrument import spec
from newswitch.models.uc2 import BusError
from newswitch.services.values import Values
from newswitch.states.uc2 import UC2State
from newswitch.states.values import MoveState, SourceState, SwapState, TuneState
from newswitch.reference import REFERENCE_INSTRUMENT


def make_virtual_bus() -> VirtualUC2Bus:
    """Create a fast virtual bus for tests."""
    return VirtualUC2Bus(
        state=UC2State(),
        config=VirtualUC2BusConfig(default_speed=1_000_000.0, update_interval_s=0.001),
    )


def reference_with(**drivers: Driver) -> Values:
    """The values of the reference microscope, these variables (`__` for `.`) through `drivers`."""
    return Values(
        spec.load(REFERENCE_INSTRUMENT),
        MoveState(),
        SwapState(),
        TuneState(),
        SourceState(),
        {name.replace("__", "."): driver for name, driver in drivers.items()},
    )


# ---------------------------------------------------------------------------
# WP1: reconnect with backoff
# ---------------------------------------------------------------------------


class FlakyCanBus(UC2CanBus):
    """UC2CanBus with a fake transport that fails twice, then connects."""

    def __init__(self) -> None:
        """Set up with a tiny backoff so the test is fast."""
        super().__init__(
            state=UC2State(),
            config=UC2CanBusConfig(reconnect_backoff_initial_s=0.01, reconnect_backoff_max_s=0.05),
        )
        self.attempts = 0
        self.recovered = asyncio.Event()

    async def _connect_and_pump(self) -> None:
        """Fail twice with a transport error, then 'connect' and idle."""
        self._broker.bind_loop()
        self.attempts += 1
        if self.attempts <= 2:
            raise ConnectionError(f"boom {self.attempts}")
        self.state.connected = True
        self._connected.set()
        self.recovered.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_can_bus_reconnects_with_backoff() -> None:
    """Transport failures publish BusError and are retried until success."""
    bus = FlakyCanBus()
    errors = []

    async def collect() -> None:
        async for event in bus.subscribe():
            if isinstance(event, BusError):
                errors.append(event)

    collector = asyncio.create_task(collect())
    background = asyncio.create_task(bus.abackground())
    await asyncio.wait_for(bus.recovered.wait(), timeout=2.0)

    assert bus.attempts == 3
    assert bus.state.connected is True
    assert bus.state.last_error == "boom 2"
    await asyncio.sleep(0)  # let queued BusError events drain
    assert len(errors) == 2

    background.cancel()
    collector.cancel()


@pytest.mark.asyncio
async def test_require_client_fails_fast_with_message() -> None:
    """_require_client raises a readable error instead of a bare timeout."""
    bus = UC2CanBus(state=UC2State())
    bus.state.last_error = "no adapter found"
    with pytest.raises(RuntimeError, match="no adapter found"):
        await bus._require_client(timeout=0.05)


def test_can_shared_node_sub_axis_mapping() -> None:
    """One board driving two motors: (node, sub) resolves to distinct axes."""
    bus = UC2CanBus(
        state=UC2State(),
        config=UC2CanBusConfig(node_x=11, node_y=11, sub_x=0, sub_y=1),
    )
    assert bus.axis_for_node(11, 0) == "X"
    assert bus.axis_for_node(11, 1) == "Y"
    assert bus.axis_for_node(11, 2) is None


# ---------------------------------------------------------------------------
# WP6: objective + filter bank over the bus
# ---------------------------------------------------------------------------


def test_a_turret_drives_the_bus_and_says_what_is_in_place() -> None:
    """A swap goes to the board's objective changer, and what it put in place is published."""
    import koil
    from koil import unkoil

    with koil.Koil():
        bus = make_virtual_bus()
        values = reference_with(objective__slot=Turret(bus))
        swap = values.swap_state.swaps["objective"]

        values.set({"objective.slot": 2})
        assert values.swap_state.swaps["objective"]["slot"].current == 2
        assert values.swap_state.swaps["objective"]["slot"].label == "f10 NA 0.4"
        assert swap["slot"].options[1].facts["magnification"] == "20x"
        assert unkoil(bus.aobjective_status)["slot"] == 2

        values.set({"objective.slot": 1})
        assert values["objective.slot"] == 1

        with pytest.raises(ValueError):
            values.set({"objective.slot": 99})


def test_a_wheel_moves_its_axis() -> None:
    """A swap positions the wheel's axis, and tracks the filter in place."""
    import koil
    from koil import unkoil

    with koil.Koil():
        bus = make_virtual_bus()
        wheel = Wheel(bus, WheelConfig(axis="A", positions={1: 0.0, 2: 120.0}))
        values = reference_with(filter_wheel__slot=wheel)

        values.set({"filter_wheel.slot": 2})
        assert values.swap_state.swaps["filter_wheel"]["slot"].current == 2
        assert unkoil(bus.aget_position, "A") == pytest.approx(120.0)

        values.set({"filter_wheel.slot": 1})
        assert unkoil(bus.aget_position, "A") == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_virtual_bus_scan_nodes() -> None:
    """Node scan returns the fake fleet and mirrors it into UC2State."""
    bus = make_virtual_bus()
    nodes = await bus.ascan_nodes()
    assert nodes == [11, 12, 13, 20, 21]
    assert bus.state.nodes_online == nodes
