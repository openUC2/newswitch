"""Dispatch of spontaneous UC2 hardware events into shared reactive states.

This is the §6.4 path: telemetry that belongs to no task (live positions,
e-stop, buttons, node discovery) is mirrored into ``@state`` objects so the
frontend updates via JSON-patch without any polling. The apply function is
pure enough to unit-test without an arkitekt agent.
"""

from __future__ import annotations

import logging


from newswitch.protocols.stage import StageState
from newswitch.protocols.uc2 import (
    BusError,
    ButtonPressed,
    EStopChanged,
    MotionDone,
    NodeSeen,
    PositionUpdate,
    UC2BusManager,
    UC2Event,
    UC2State,
)

logger = logging.getLogger(__name__)

_AXIS_TO_STATE_FIELD = {"X": "x", "Y": "y", "Z": "z", "A": "a"}


# TODO: @Johannes this needs critical review
def apply_uc2_event(event: UC2Event, stage_state: StageState, uc2_state: UC2State) -> None:
    """Apply one hardware event to the shared states."""
    if isinstance(event, (PositionUpdate, MotionDone)):
        field = _AXIS_TO_STATE_FIELD.get(event.axis.upper())
        if field is not None:
            setattr(stage_state, field, event.position)
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


async def dispatch_uc2_events(
    bus: UC2BusManager, stage_state: StageState, uc2_state: UC2State
) -> None:
    """Consume the bus event stream forever, mirroring it into states.

    It writes ``StageState`` while a move may hold ``stage_position``: a lock keeps
    two actions from commanding the stage at once, it does not guard the state,
    so the reported position streams in alongside a running move.
    """
    async for event in bus.subscribe():
        try:
            apply_uc2_event(event, stage_state, uc2_state)
        except Exception:
            logger.exception("Failed to apply UC2 event %r", event)
