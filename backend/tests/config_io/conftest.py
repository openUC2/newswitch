"""Fixtures for the `newswitch.config_io` tests.

Documents are built in the tests themselves instead of reading ``backend/configs``,
which is a development-only folder; only ``test_schema_drift.py`` looks at the real
files. They are written into `config_dir`, a temporary folder from the top-level conftest.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Protocol, TypeVar

import pytest
import yaml

from newswitch.config_io import DeviceBase, NewswitchConfig

T = TypeVar("T", bound=DeviceBase)

#: File name `write_doc` uses when no other name is given.
DOC_NAME = "newswitch-config.yaml"


class DocWriter(Protocol):
    """The `write_doc` helper: (document, file name) -> path written to."""

    def __call__(self, document: Any, name: str = ...) -> Path:  # noqa: ANN401
        """Write ``document`` as ``name`` (default: `DOC_NAME`) into `config_dir`."""
        ...


def get_device(config: NewswitchConfig, key: str, cls: type[T]) -> T:
    """Look up a device and narrow it to the class the test expects.

    Args:
        config: The loaded configuration.
        key: Key in ``config.devices``.
        cls: The expected device dataclass, e.g. `DetectorConfig`.

    Returns:
        The device, typed as ``cls``.
    """
    device = config.devices[key]
    assert isinstance(device, cls)
    return device


#: Connection of a simulated controller: valid, but opens no hardware.
SIMULATED: dict[str, Any] = {"protocol": "simulated", "transport": {"type": "simulated"}}

CONTROLLER: dict[str, Any] = {
    "type": "controller",
    "name": "UC2-Mainboard-v4",
    "connection": SIMULATED,
    "firmware": {"name": "esp32-uc2", "version": "v1"},
    "mapping": {
        "led": {"type": "pwm-led", "id": 1, "pwm_max": 1023},
        "laser": {"type": "serial-laser", "id": 2, "pwm_max": 1023},
        "cam": {"type": "simulated-camera", "id": 0},
        "ax-x": {"type": "canopen-motor", "id": 11},
        "ax-z": {"type": "canopen-motor", "id": 13},
        "turret-axis": {"type": "canopen-revolver", "id": 4},
    },
}


@pytest.fixture
def minimal_doc() -> dict[str, Any]:
    """A valid document with one device of every type, behind one simulated controller.

    The objective turret is a stage with one axis whose presets name the objectives.

    Returns:
        A fresh plain dict; tests may modify it freely.
    """
    return copy.deepcopy(
        {
            "newswitch_version": "v1.0.0",
            "devices": {
                "mainboard": CONTROLLER,
                "led": {"type": "lightsource", "name": "LED", "wavelength": 470},
                "laser": {
                    "type": "lightsource",
                    "name": "Laser",
                    "wavelength": 638,
                    "coherence": "coherent",
                },
                "cam": {
                    "type": "detector",
                    "name": "Cam",
                    "pixelcount": [640, 480],
                    "pixelpitch_um": 5.0,
                    "exposure_time_ms": {"value": 10.0, "min": 0.1, "max": 1000.0},
                },
                "stage": {"type": "stage", "name": "XYZ", "axes": {"x": "ax-x", "z": "ax-z"}},
                "ax-x": {"type": "axis", "steps_per_um": 8.0, "homing_required": True},
                "ax-z": {"type": "axis", "steps_per_um": None},
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
                "turret": {"type": "stage", "name": "Turret", "axes": {"rz": "turret-axis"}},
                "turret-axis": {
                    "type": "axis",
                    "steps_per_um": 8.0,
                    "pos": {
                        "preset_vals": {0: "obj10", 1000: "null", 2000: "obj40"},
                        "selected_index": 2,
                    },
                },
                "gfp": {"type": "filter", "name": "GFP", "wavelength": 525, "bandwidth": 50},
            },
        }
    )


@pytest.fixture
def config_path(config_dir: Path) -> Path:
    """Where `write_doc` puts a document by default.

    Args:
        config_dir: The temporary config directory fixture.

    Returns:
        ``config_dir / DOC_NAME``.
    """
    return config_dir / DOC_NAME


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

    def _write(document: Any, name: str = DOC_NAME) -> Path:  # noqa: ANN401
        path = config_dir / name
        if isinstance(document, str):
            path.write_text(document, encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return path

    return _write
