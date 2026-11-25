"""What the real thing hides: ``truth.yml``, beside an instrument's description.

How this copy differs from its design (a focal length off its label, a camera turned, a holder
beside its place), which only the simulator may know: the predictions must find it from images, as
the calibration does on a real instrument. Read here and nowhere else.
"""

from __future__ import annotations

from typing import Any

import yaml

from newswitch.instrument.spec import Instrument
from newswitch.instrument.tracing import Errors

#: The hidden errors, in an instrument's folder.
TRUTH = "truth.yml"


def load_truth(instrument: Instrument) -> dict[str, Any]:
    """The hidden errors of `instrument`; none when it has no truth file."""
    path = instrument.folder / TRUTH
    return (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}


def optical_errors(instrument: Instrument) -> Errors | None:
    """The errors the tracer can apply; None when there are none."""
    truth = load_truth(instrument)
    if not truth:
        return None
    return Errors(objective_focal_factor=truth.get("objective_focal_error", 1.0))
