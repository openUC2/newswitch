"""
Broadcasters for video frame streaming.
"""

from .frame import FrameBroadcaster
from .sink import FrameSink

__all__ = [
    "FrameBroadcaster",
    "FrameSink",
]
