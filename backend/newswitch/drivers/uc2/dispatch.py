"""Dispatch of spontaneous UC2 hardware events into shared reactive states.

This is the §6.4 path: telemetry that belongs to no task (live positions,
e-stop, buttons, node discovery) is mirrored into states so the
frontend updates via JSON-patch without any polling. The apply function is
pure enough to unit-test without an arkitekt agent.
"""

from __future__ import annotations

import logging

from newswitch.models.uc2 import (
    BusError,
    ButtonPressed,
    EStopChanged,
    MotionDone,
    NodeSeen,
    PositionUpdate,
    UC2Event,
)
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.drivers.uc2.actuators import Stepper
from newswitch.services.values import Values
from newswitch.states.uc2 import UC2State

logger = logging.getLogger(__name__)


def apply_uc2_event(event: UC2Event, values: Values, uc2_state: UC2State) -> None:
    """Apply one hardware event to the shared states."""
    if isinstance(event, (PositionUpdate, MotionDone)):
        for name, driver in values.drivers.items():
            if isinstance(driver, Stepper) and driver.config.axis == event.axis.upper():
                values.stepped(name, event.position)
    elif isinstance(event, EStopChanged):
        uc2_state.estop_active = event.active
    elif isinstance(event, NodeSeen):
        if event.node_id not in uc2_state.nodes_online:
            uc2_state.nodes_online = sorted(set(uc2_state.nodes_online) | {event.node_id})
    elif isinstance(event, BusError):
        uc2_state.last_error = event.message
    elif isinstance(event, ButtonPressed):
        # Button policy (e.g. snap on press) belongs to hooks; just log here.
        logger.info("UC2 button event: key=%s data=%s", event.key, event.data)


async def dispatch_uc2_events(bus: UC2BusManager, values: Values, uc2_state: UC2State) -> None:
    """Consume the bus event stream forever, mirroring it into states.

    It writes what moved while a move may hold ``motion``: a lock keeps
    two actions from commanding the stage at once, it does not guard the state,
    so the reported position streams in alongside a running move.
    """
    async for event in bus.subscribe():
        try:
            apply_uc2_event(event, values, uc2_state)
        except Exception:
            logger.exception("Failed to apply UC2 event %r", event)
