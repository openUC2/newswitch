"""Where what was calibrated of a microscope is kept: one YAML file per microscope, in
``settings.calibration_dir``, never in its description.

What it holds is of one design (`Instrument.design_hash`): a calibration measures how this copy
differs from what it is built as, and a changed design voids all of it. It is written whole each
time something is calibrated, atomically: a file half written is never read.

```yaml
microscope: johannes-frame
design: 3f9a...                  # Instrument.design_hash()
saved: 2026-11-25T10:31:04Z
light_paths:                     # the pixel-to-stage matrix measured, by what it depends on
  - {key: 1a2b..., affine_matrix: [[...], ...]}
mounts:                          # how far each holder sits from its design's mount
  - {sample: stage, holder: slides, offset_um: [-11.0, 7.0], rotation_deg: 0.0, measured: ...}
```
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from newswitch.calibration.models import CalibratedMount
from newswitch.models.light_path import CalibratedLightPath


@dataclass
class Stored:
    """What a store holds."""

    microscope: str
    design: str
    saved: str
    light_paths: list[CalibratedLightPath] = field(default_factory=list)
    mounts: list[CalibratedMount] = field(default_factory=list)


class CalibrationStore:
    """The calibrations of the microscope `name`, in `folder`."""

    def __init__(self, folder: Path, name: str) -> None:
        """The store ``<folder>/<name>.yml``; nothing is read or written yet."""
        self.path = Path(folder) / f"{name}.yml"

    def load(self) -> Stored | None:
        """What is kept; None: nothing is.

        Raises:
            ValueError: The file is not a calibration store.
        """
        if not self.path.is_file():
            return None
        data: dict[str, Any] = yaml.safe_load(self.path.read_text()) or {}
        try:
            return Stored(
                microscope=str(data["microscope"]),
                design=str(data["design"]),
                saved=str(data.get("saved", "")),
                light_paths=[
                    CalibratedLightPath(
                        affine_matrix=[[float(v) for v in row] for row in entry["affine_matrix"]],
                        key=str(entry["key"]),
                    )
                    for entry in data.get("light_paths") or []
                ],
                mounts=[
                    CalibratedMount(
                        sample=str(entry["sample"]),
                        holder=str(entry["holder"]),
                        offset_x_um=float(entry["offset_um"][0]),
                        offset_y_um=float(entry["offset_um"][1]),
                        rotation_deg=float(entry.get("rotation_deg", 0.0)),
                        measured=str(entry.get("measured", "")),
                    )
                    for entry in data.get("mounts") or []
                ],
            )
        except (KeyError, TypeError, IndexError, ValueError) as error:
            raise ValueError(f"{self.path}: no calibration store ({error!r})") from error

    def save(self, stored: Stored) -> None:
        """Keep `stored`, replacing what was: written beside it, then moved over it."""
        data = {
            "microscope": stored.microscope,
            "design": stored.design,
            "saved": stored.saved,
            "light_paths": [
                {"key": entry.key, "affine_matrix": [list(map(float, row)) for row in entry.affine_matrix]}
                for entry in stored.light_paths
            ],
            "mounts": [
                {
                    "sample": entry.sample,
                    "holder": entry.holder,
                    "offset_um": [entry.offset_x_um, entry.offset_y_um],
                    "rotation_deg": entry.rotation_deg,
                    "measured": entry.measured,
                }
                for entry in stored.mounts
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w") as file:
                yaml.safe_dump(data, file, sort_keys=False)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
