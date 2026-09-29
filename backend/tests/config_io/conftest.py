"""Fixtures for the `newswitch.config_io` tests.

Documents are built in the tests themselves instead of reading ``backend/Configs``,
which is a development-only folder; only ``test_schema_drift.py`` looks at the real
files. `config_dir` (from the top-level conftest) redirects the managed paths.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

# (document, file name) -> path written to
DocWriter = Callable[[Any, str], Path]

CONTROLLER: dict[str, Any] = {
    "type": "controller",
    "name": "UC2-Mainboard-v4",
    "connection": {
        "protocol": "uc2-rest",
        "transport": {"type": "serial", "port": "/dev/ttyUSB0"},
    },
    "firmware": {"name": "esp32-uc2", "version": "v1"},
}


@pytest.fixture
def minimal_doc() -> dict[str, Any]:
    """A valid document with one device of every type.

    Returns:
        A fresh plain dict; tests may modify it freely.
    """
    return copy.deepcopy(
        {
            "newswitch_version": "v1.0.0",
            "devices": {
                "mainboard": CONTROLLER,
                "led": {
                    "type": "lightsource",
                    "name": "LED",
                    "wavelength": 470,
                    "controller": "mainboard",
                },
                "laser": {
                    "type": "lightsource",
                    "name": "Laser",
                    "wavelength": 638,
                    "coherence": "coherent",
                    "controller": "mainboard",
                },
                "cam": {
                    "type": "detector",
                    "name": "Cam",
                    "connection": {"protocol": "gige-vision", "serial_number": "123"},
                    "pixelcount": [640, 480],
                    "pixelpitch_um": 5.0,
                    "exposure_time_ms": {"value": 10.0, "min": 0.1, "max": 1000.0},
                },
                "stage": {
                    "type": "stage",
                    "name": "XYZ",
                    "controller": "mainboard",
                    "axes": [
                        {"label": "x", "steps_per_um": 8.0, "homing_required": True},
                        {"label": "z", "steps_per_um": None, "homing_required": False},
                    ],
                },
                "obj10": {
                    "type": "objective",
                    "name": "10x",
                    "magnification": 10,
                    "na": 0.3,
                    "wd": 10,
                },
                "obj40": {
                    "type": "objective",
                    "name": "40x",
                    "magnification": 40,
                    "na": 1.0,
                    "wd": 0.3,
                },
                "turret": {
                    "type": "revolver",
                    "name": "Turret",
                    "controller": "mainboard",
                    "channels": ["obj10", None, "obj40"],
                    "selected_channel": 2,
                },
                "gfp": {"type": "filter", "name": "GFP", "wavelength": 525, "bandwidth": 50},
            },
        }
    )


@pytest.fixture
def write_doc(config_dir: Path) -> DocWriter:
    """Return a helper that writes a document as YAML into the temporary config dir.

    A string is written verbatim (for tests about comments and layout), anything else
    is dumped with PyYAML.

    Args:
        config_dir: The temporary config directory fixture.

    Returns:
        A callable ``(document, name) -> Path``.
    """

    def _write(document: Any, name: str = "newswitch-config.yaml") -> Path:  # noqa: ANN401
        path = config_dir / name
        if isinstance(document, str):
            path.write_text(document, encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return path

    return _write
