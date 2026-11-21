"""How the frames detectors acquire are watched: the `FrameSink`s of the two ways of serving.

The protocol a detector streams to is the microscope's (`newswitch.protocols.frame_sink`); what is
here implements it: the websocket live view's `FrameBroadcaster` (``main_fastapi.py``, encoded by
`wire`) and lovekit streams (`lovekit`, ``app.py``, not imported here: it needs the extra
``agent``).
"""

from .frame import FrameBroadcaster

__all__ = [
    "FrameBroadcaster",
]
