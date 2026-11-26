"""How newswitch runs: the ``settings`` section of the instrument it runs on.

``NEWSWITCH_CONFIG`` names the instrument (``instruments/<name>/microscope.yml``, or its folder;
relative paths are taken relative to ``backend/``). There is no other file: everything about the
microscope, how it runs included, is read from its description, and only ever read. What changes
while it runs lives in its states.

`Run` holds them, as the app context of the registry (`newswitch.microscope.run`).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal, Optional, TYPE_CHECKING, get_args

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

if TYPE_CHECKING:
    from newswitch.instrument.spec import Instrument

#: Where relative paths start.
BACKEND_DIR = Path(__file__).parent.parent
#: Names the instrument newswitch runs on.
CONFIG_ENV_VAR = "NEWSWITCH_CONFIG"
#: Runs the description named with another `Settings.simulate` than it states: ``virtual`` runs a
#: rig's description as its digital twin, without touching the file. Read by the entry files
#: (``app.py``, ``main_fastapi.py``), which pass it to `load_settings`.
SIMULATE_ENV_VAR = "NEWSWITCH_SIMULATE"

Simulate = Literal["everything", "virtual", "debug", "unwired", "nothing"]
#: The modes in which no hardware is reached at all.
SIMULATED: tuple[str, ...] = ("everything", "virtual", "debug")


class Settings(BaseModel):
    """The ``settings`` section of a description; every key but `instrument` must be there."""

    # a misspelled key is an error, not ignored
    model_config = ConfigDict(extra="forbid")

    simulate: Simulate
    """What has no hardware: all of it, to run a description dry (``everything``: its variables
    simulated, its ``hardware`` section left aside); all of it, but with its drivers running on
    virtual boards and simulated cameras (``virtual``: the digital twin of a rig, its homing and
    wiring included); all of it, as ``everything``, but each camera's stream sending the time it
    sends instead of the camera's frames (``debug``: to test the network, `infra.streaming.
    test_pattern`); what its ``hardware``
    section does not wire, so that a real camera can sit beside a simulated stage (``unwired``);
    or nothing, so that what is not wired is refused.
    ``$NEWSWITCH_SIMULATE`` overrides it for a run (`load_settings`)."""
    db_path: str
    """SQLite file of the arkitekt agent (state history, journal); relative to the working
    directory."""
    image_dir: Path
    """Folder the file IO writes into (`services.io.LocalFileIOManager`)."""
    cache_dir: Path
    """Folder acquired frames are cached in (`services.cache.LocalCacheManager`); cleared
    when the microscope starts."""
    calibration_dir: Path
    """Folder the calibration store is kept in (`newswitch.calibration.store`): what was measured
    of this copy of the microscope, one file per microscope (``<name>.yml``), applied at every
    start while the design is the one it was measured on. Kept: never cleared."""
    camera_recording_dir: Optional[Path]
    """Folder the cameras record into (see `drivers.uc2.uc2_detector`). null: the default of
    uc2_cam_py (``~/UC2_recordings``)."""
    camera_debug_window: StrictBool
    """Show every camera's newest image in a window of uc2_cam_py (debugging without the
    frontend); the cameras then acquire from startup on."""

    instrument: Optional[Path] = None
    """The description these come from, set by `load_settings`. None: no devices, the core only."""

    @property
    def test_pattern(self) -> bool:
        """Whether each camera's stream sends a test pattern instead of its frames (``debug``)."""
        return self.simulate == "debug"

    @field_validator("instrument", "camera_recording_dir", "image_dir", "cache_dir", "calibration_dir")
    @classmethod
    def _relative_to_backend(cls, path: Optional[Path]) -> Optional[Path]:
        if path is None or path.is_absolute():
            return path
        return BACKEND_DIR / path


def load_settings(named: Optional[str] = None, simulate: Optional[str] = None) -> Settings:
    """The ``settings`` of the instrument `named` (default: ``$NEWSWITCH_CONFIG``), run in the
    mode `simulate` where one is given (the entry files pass ``$NEWSWITCH_SIMULATE``): a run in
    another mode than its description states gets files of its own (`_apart`).

    Raises:
        SpecError: None is named, what is named is no valid description, or `simulate` is no
            simulation mode.
    """
    #TODO: no local imports
    from newswitch.instrument import spec
    from newswitch.instrument.errors import SpecError

    named = named if named is not None else os.environ.get(CONFIG_ENV_VAR)
    if not named:
        raise SpecError(
            f"{CONFIG_ENV_VAR} names no instrument: set it to instruments/<name>/microscope.yml"
        )
    path = Path(named).expanduser()
    if not path.is_absolute():
        path = BACKEND_DIR / path
    settings = spec.load(path).settings.model_copy(update={"instrument": path}) #TODO: this is weird
    if simulate:
        if simulate not in get_args(Simulate):
            raise SpecError(
                f"simulate={simulate!r} is no simulation mode: one of "
                f"{', '.join(get_args(Simulate))}"
            )
        if simulate != settings.simulate:
            logging.getLogger(__name__).info(
                "%s: simulate %s instead of %s, with files of its own",
                path.name,
                simulate,
                settings.simulate,
            )
            settings = settings.model_copy(update={"simulate": simulate, **_apart(settings, simulate)})
    return settings


def _apart(settings: Settings, mode: str) -> dict[str, object]:
    """The files of a run in `mode` beside the one its description is for: its own agent database,
    image, cache and calibration folders (the cache is cleared on start), so a twin running beside
    the rig disturbs none of the rig's, and what it calibrates is never taken for the rig's."""
    db = Path(settings.db_path)
    return {
        "db_path": str(db.with_name(f"{db.stem}.{mode}{db.suffix}")),
        "image_dir": settings.image_dir / mode,
        "cache_dir": settings.cache_dir / mode,
        "calibration_dir": settings.calibration_dir / mode,
    }


def load_devices(config: Settings) -> Instrument:
    """The instrument `config` came from: every run is of one.

    Raises:
        SpecError: `config` came from none.
    """
    from newswitch.instrument import spec
    from newswitch.instrument.errors import SpecError

    if config.instrument is None:
        raise SpecError(
            f"the settings name no instrument: set {CONFIG_ENV_VAR} to instruments/<name>/microscope.yml"
        )
    return spec.load(config.instrument)
