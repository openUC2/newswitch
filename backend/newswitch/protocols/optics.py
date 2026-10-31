"""
Optics Manager Protocol

Defines the protocol for what the optics find, and the light paths they make.
"""

from typing import Protocol, runtime_checkable

from newswitch.models.light_path import LightPath, LightPathSnapshot
from newswitch.protocols.base import Manager


@runtime_checkable
class OpticsManager(Manager, Protocol):
    """Protocol defining the interface for the manager of what the optics find."""

    def refresh(self) -> None:
        """Publish what the optics find under the current values."""
        ...

    def get_light_path_for_detector(self, detector_slot: int) -> LightPath:
        """The light path of the detector in a slot, as things are now."""
        ...

    def snapshot(self, path: LightPath) -> LightPathSnapshot:
        """`path` as things are now, keyed by what a calibration of it depends on."""
        ...

    def depth_of_field_um(self, detector_slot: int) -> float:
        """How deep what the detector in a slot sees sharply is, from its objective's NA."""
        ...
