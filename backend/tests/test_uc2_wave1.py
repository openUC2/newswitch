"""Tests for the Wave-1 UC2 additions: reconnect, objective, filter, autofocus, converter."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from newswitch.managers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.managers.uc2.filter_bank_manager import UC2FilterBankManager
from newswitch.managers.uc2.objective_manager import UC2ObjectiveManager
from newswitch.managers.uc2.virtual_bus import VirtualUC2Bus, VirtualUC2BusConfig
from newswitch.protocols.filter_bank import FilterBankState
from newswitch.protocols.objective import ObjectiveState
from newswitch.protocols.uc2 import BusError, UC2State

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from convert_imswitch_setup import convert_setup  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


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
    from rekuest_next.state.lock import acquired_locks

    with koil.Koil(), acquired_locks("objective"):
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
    from rekuest_next.state.lock import acquired_locks

    with koil.Koil(), acquired_locks("filter_bank"):
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


# ---------------------------------------------------------------------------
# WP5: ImSwitch setup converter
# ---------------------------------------------------------------------------


def test_convert_imswitch_rest_setup() -> None:
    """example_uc2.json (ESP32 serial) converts to a valid rest-transport config."""
    from newswitch.app import ImswitchConfig
    from newswitch.managers.uc2.rest_bus import UC2RestBusConfig

    setup = json.loads((FIXTURES / "example_uc2.json").read_text())
    config, skipped = convert_setup(setup)

    validated = ImswitchConfig.model_validate(config)
    assert validated.uc2_transport == "rest"
    assert validated.use_virtual_microscope is False
    # COM3 is not portable -> autodetect
    assert validated.uc2_serial_port is None

    rest_cfg = UC2RestBusConfig(**{"serialport": validated.uc2_serial_port, **validated.uc2_rest})
    # stepsizeX = -0.3125 um/step -> -3.2 steps/um (sign = axis inversion)
    assert rest_cfg.steps_per_um_x == pytest.approx(-3.2)
    assert rest_cfg.steps_per_um_z == pytest.approx(3.2)

    sources = validated.uc2_illumination["sources"]
    assert any(s["channel"] == 1 and s["wavelength"] == 532 for s in sources)
    # The non-numeric "LED" channel is skipped with a note
    assert any("LED" in note for note in skipped)


def test_convert_imswitch_canopen_setup() -> None:
    """canopen.json converts to a valid canopen-transport config."""
    from newswitch.app import ImswitchConfig
    from newswitch.managers.uc2.canopen_bus import UC2CanBusConfig

    setup = json.loads((FIXTURES / "canopen.json").read_text())
    config, _ = convert_setup(setup)

    validated = ImswitchConfig.model_validate(config)
    assert validated.uc2_transport == "canopen"
    assert validated.uc2_can_interface == "socketcan"
    assert validated.uc2_can_channel == "can0"

    can_cfg = UC2CanBusConfig(
        **{
            "interface": validated.uc2_can_interface,
            "channel": validated.uc2_can_channel,
            **validated.uc2_can,
        }
    )
    assert can_cfg.bitrate == 500000
