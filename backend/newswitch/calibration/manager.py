"""What is calibrated of this copy of the microscope: kept in its store, read by the runtime.

The runtime asks it through `newswitch.protocols.calibration.CalibrationManager` (a light path's
measured matrix, a holder's measured mount); the calibration routines tell it what they measured,
and it keeps that in the store, as the deviation of this copy from its design where there is a
design value to deviate from (a holder's mount).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from newswitch.calibration.models import CalibratedMount
from newswitch.calibration.states import CalibrationState
from newswitch.calibration.store import CalibrationStore, Stored
from newswitch.instrument.spec import Instrument, Mount
from newswitch.models.light_path import CalibratedLightPath

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CalibrationManager:
    """Keeps what was measured of each light path and holder, in its store when it has one."""

    #: Called once a value of this part has changed.
    on_change: Callable[[], None] = staticmethod(lambda: None)

    def __init__(
        self,
        calibration_state: CalibrationState,
        instrument: Instrument | None = None,
        store: CalibrationStore | None = None,
    ) -> None:
        """What `store` keeps of `instrument`, applied when it is of its design; nothing kept
        without a store (what is calibrated lives as long as the run)."""
        self.state = calibration_state
        self.instrument = instrument
        self.store = store
        self.state.design = "" if instrument is None else instrument.design_hash()
        self.state.store = None if store is None else str(store.path)
        self._load()

    def _load(self) -> None:
        if self.store is None:
            return
        stored = self.store.load()
        if stored is None:
            return
        self.state.stored_design = stored.design
        self.state.saved = stored.saved
        if stored.design != self.state.design:
            self.state.stale = True
            logger.warning(
                "%s: its calibrations are of another design (%s, now %s): none is applied until "
                "they are measured again",
                self.store.path,
                stored.design[:12],
                self.state.design[:12],
            )
            return
        self.state.calibrated_light_paths = list(stored.light_paths)
        self.state.mounts = list(stored.mounts)
        logger.info(
            "%s: %d light path(s) and %d mount(s) calibrated, saved %s",
            self.store.path,
            len(stored.light_paths),
            len(stored.mounts),
            stored.saved,
        )

    def _persist(self) -> None:
        """Keep what is calibrated now; what was of another design is gone with it."""
        if self.store is None or self.instrument is None:
            return
        saved = _now()
        self.store.save(
            Stored(
                microscope=self.instrument.name,
                design=self.state.design,
                saved=saved,
                light_paths=list(self.state.calibrated_light_paths),
                mounts=list(self.state.mounts),
            )
        )
        self.state.saved = saved
        self.state.stored_design = self.state.design
        self.state.stale = False

    # --- light paths

    def light_path(self, key: str) -> CalibratedLightPath | None:
        """What was measured of the light path `key`, if it was."""
        return next(
            (known for known in self.state.calibrated_light_paths if known.key == key), None
        )

    def set_calibrated_state(self, calibrated_light_path: CalibratedLightPath) -> None:
        """Set the calibrated state for a light path configuration, replacing an earlier one, and
        keep it."""
        key = calibrated_light_path.key
        self.state.calibrated_light_paths = [
            known for known in self.state.calibrated_light_paths if known.key != key
        ] + [calibrated_light_path]
        self._persist()
        self.on_change()

    # --- mounts

    def _nominal(self, sample: str, holder: str) -> Mount:
        assert self.instrument is not None
        return self.instrument.sample_holder(sample).holders[holder].mount

    def mount(self, sample: str, holder: str) -> Mount | None:
        """Where `holder` of `sample` was measured to sit: its design's mount, off by what was
        measured; None where it was not."""
        found = next(
            (m for m in self.state.mounts if (m.sample, m.holder) == (sample, holder)), None
        )
        if found is None or self.instrument is None:
            return None
        nominal = self._nominal(sample, holder)
        return Mount.of(
            nominal.x + found.offset_x_um / 1000.0,
            nominal.y + found.offset_y_um / 1000.0,
            nominal.rotation + found.rotation_deg,
        )

    def set_mount(self, sample: str, holder: str, mount: Mount) -> str | None:
        """`holder` of `sample` was measured at `mount`: keep how far that is from its design's.
        Where it was kept; None: nowhere."""
        nominal = self._nominal(sample, holder)
        kept = CalibratedMount(
            sample=sample,
            holder=holder,
            offset_x_um=round((mount.x - nominal.x) * 1000.0, 3),
            offset_y_um=round((mount.y - nominal.y) * 1000.0, 3),
            rotation_deg=mount.rotation - nominal.rotation,
            measured=_now(),
        )
        self.state.mounts = [
            m for m in self.state.mounts if (m.sample, m.holder) != (sample, holder)
        ] + [kept]
        self._persist()
        return None if self.store is None else str(self.store.path)
