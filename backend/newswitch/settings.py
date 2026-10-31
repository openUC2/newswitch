"""How newswitch runs: the ``settings`` section of the instrument it runs on.

``NEWSWITCH_CONFIG`` names the instrument (``instruments/<name>/microscope.yml``, or its folder;
relative paths are taken relative to ``backend/``). There is no other file: everything about the
microscope, how it runs included, is read from its description, and only ever read. What changes
while it runs lives in its states.

`Settings` is the app context of the registry, so every action and startup hook can take it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

if TYPE_CHECKING:
    from newswitch.instrument.spec import Instrument

#: Where relative paths start.
BACKEND_DIR = Path(__file__).parent.parent
#: Names the instrument newswitch runs on.
CONFIG_ENV_VAR = "NEWSWITCH_CONFIG"


class Settings(BaseModel):
    """The ``settings`` section of a description; every key but `instrument` must be there."""

    # a misspelled key is an error, not ignored
    model_config = ConfigDict(extra="forbid")

    use_virtual_microscope: StrictBool
    """Simulated, or the real hardware of the description's ``hardware`` section."""
    simulation: str
    """Which of the sample holder's ``simulations`` is on it: what a simulation draws, and what
    predictions assume, on real hardware too."""
    db_path: str
    """SQLite file of the arkitekt agent (state history, journal); relative to the working
    directory."""
    image_dir: Path
    """Folder the file IO writes into (`services.io.LocalFileIOManager`)."""
    cache_dir: Path
    """Folder acquired frames are cached in (`services.cache.LocalCacheManager`); cleared
    when the microscope starts."""
    camera_recording_dir: Optional[Path]
    """Folder the cameras record into (see `drivers.uc2.uc2_detector`). null: the default of
    uc2_cam_py (``~/UC2_recordings``)."""
    camera_debug_window: StrictBool
    """Show every camera's newest image in a window of uc2_cam_py (debugging without the
    frontend); the cameras then acquire from startup on."""

    instrument: Optional[Path] = None
    """The description these come from, set by `load_settings`. None: no devices, the core only."""

    @field_validator("instrument", "camera_recording_dir", "image_dir", "cache_dir")
    @classmethod
    def _relative_to_backend(cls, path: Optional[Path]) -> Optional[Path]:
        if path is None or path.is_absolute():
            return path
        return BACKEND_DIR / path


def load_settings(named: Optional[str] = None) -> Settings:
    """The ``settings`` of the instrument `named` (default: ``$NEWSWITCH_CONFIG``).

    Raises:
        SpecError: None is named, or what is named is no valid description.
    """
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
    return spec.load(path).settings.model_copy(update={"instrument": path})


def load_devices(config: Settings) -> Instrument | None:
    """The instrument `config` came from; None when it came from none."""
    from newswitch.instrument import spec

    return None if config.instrument is None else spec.load(config.instrument)
