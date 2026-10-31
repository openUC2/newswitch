"""The acquisition protocol: taking frames with the active detectors."""

from typing import Optional, Protocol, runtime_checkable

from newswitch.models.frames import Frame
from newswitch.protocols.base import Manager


@runtime_checkable
class AcquisitionManager(Manager, Protocol):
    """Takes frames with the active detectors, caches them and adds them to the expanse."""

    def acquire(self, names: Optional[list[str]] = None) -> list[Frame]:
        """A frame from each active detector (only those in `names`, when given)."""
        ...
