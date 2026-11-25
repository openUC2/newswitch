"""What is calibrated of this copy of the microscope, as the runtime reads it.

Implemented by `newswitch.calibration.manager.CalibrationManager`; the runtime never imports
`newswitch.calibration`, only this.
"""

from collections.abc import Callable
from typing import Optional, Protocol, runtime_checkable

from newswitch.instrument.spec import Mount
from newswitch.models.light_path import CalibratedLightPath
from newswitch.protocols.base import Manager


@runtime_checkable
class CalibrationManager(Manager, Protocol):
    """What was measured of the light paths and the holders, and keeping what is measured."""

    on_change: Callable[[], None]

    def light_path(self, key: str) -> Optional[CalibratedLightPath]:
        """What was measured of the light path `key` (`LightPathSnapshot.key`), if it was."""
        ...

    def set_calibrated_state(self, calibrated_light_path: CalibratedLightPath) -> None:
        """Keep what was measured of a light path, replacing what was of it."""
        ...

    def mount(self, sample: str, holder: str) -> Optional[Mount]:
        """Where `holder` of `sample` was measured to sit, if it was."""
        ...

    def set_mount(self, sample: str, holder: str, mount: Mount) -> Optional[str]:
        """Keep where `holder` of `sample` was measured to sit; where it was kept, if anywhere."""
        ...
