"""Tests for the Wave-1 UC2 additions: reconnect, objective, filter, autofocus."""

import asyncio

import pytest

from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.drivers.uc2.filter_bank_manager import UC2FilterBankManager
from newswitch.drivers.uc2.objective_manager import UC2ObjectiveManager
from newswitch.drivers.uc2.virtual_bus import VirtualUC2Bus, VirtualUC2BusConfig
from newswitch.models.uc2 import BusError
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.objective import ObjectiveState
from newswitch.states.uc2 import UC2State


def make_virtual_bus() -> VirtualUC2Bus:
    """Create a fast virtual bus for tests."""
    return VirtualUC2Bus(
        state=UC2State(),
        config=VirtualUC2BusConfig(default_speed=1_000_000.0, update_interval_s=0.001),
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


def test_objective_manager_switches_and_toggles() -> None:
    """UC2ObjectiveManager drives the bus and mirrors slot metadata into state."""
    import koil
    from koil import unkoil

    with koil.Koil():
        bus = make_virtual_bus()
        state = ObjectiveState()
        manager = UC2ObjectiveManager(objective_state=state, bus=bus)

        manager.switch_objective(2)
        assert state.slot == 2
        assert state.magnification == pytest.approx(20.0)
        assert unkoil(bus.aobjective_status)["slot"] == 2

        manager.toggle_objective()
        assert state.slot == 1

        with pytest.raises(ValueError):
            manager.switch_objective(99)


def test_filter_bank_manager_moves_wheel_axis() -> None:
    """UC2FilterBankManager positions the wheel axis and tracks the active filter."""
    import koil
    from koil import unkoil

    with koil.Koil():
        bus = make_virtual_bus()
        state = FilterBankState()
        manager = UC2FilterBankManager(filter_bank_state=state, bus=bus)

        active = manager.switch_filter(2)
        assert active.slot == 2
        assert state.current_slot == 2
        assert unkoil(bus.aget_position, "A") == pytest.approx(120.0)

        active = manager.toggle_filter()
        assert active.slot == 3
        assert unkoil(bus.aget_position, "A") == pytest.approx(240.0)

        assert manager.get_transmission_at_wavelength(605.0) == pytest.approx(1.0)
        assert manager.get_transmission_at_wavelength(450.0) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_virtual_bus_scan_nodes() -> None:
    """Node scan returns the fake fleet and mirrors it into UC2State."""
    bus = make_virtual_bus()
    nodes = await bus.ascan_nodes()
    assert nodes == [11, 12, 13, 20, 21]
    assert bus.state.nodes_online == nodes
