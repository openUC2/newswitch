"""What one run of newswitch has: the app context every startup hook takes.

A hook is handed only the app context, and sees no other hook's result, yet the parts depend on each
other (the simulated detector reads every variable;
acquisition and hooks use several managers; the UC2 parts share one bus). So the context holds the
one `build_microscope` they all hand out, made when the first hook asks. Every app has its own
`Run`: two apps share nothing.
"""

from dataclasses import dataclass
from functools import cached_property
from typing import Optional

from newswitch.instrument.spec import Instrument
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.services.mikro_connection import MikroConnection
from newswitch.settings import Settings, load_devices


@dataclass
class Run:
    """The settings of one run, what it runs on, and what that built."""

    settings: Settings
    instrument: Optional[Instrument] = None
    mikro: Optional[MikroConnection] = None
    """Where a mikro is, in FastAPI mode (`newswitch.services.mikro_app`)."""

    @classmethod
    def of(cls, settings: Settings, mikro: Optional[MikroConnection] = None) -> "Run":
        """The run of `settings`, on the instrument they came from."""
        return cls(settings, load_devices(settings), mikro)

    @cached_property
    def microscope(self) -> Microscope:
        """The managers and states of this run, built on the first startup hook."""
        return build_microscope(self.settings, self.instrument)
