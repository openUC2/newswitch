"""A microscope described by an optikit design: its devices, its model and its UI."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from newswitch.config_io import adapters
from newswitch.config_io.devices import AxisConfig, ControllerConfig, DetectorConfig
from newswitch.optikit import dsn as optikit
from newswitch.design.config import DesignConfigError, design_config, device_tree

FLUORESCENCE = Path(
    os.environ.get(
        "NEWSWITCH_TEST_DSN",
        Path.home() / "Code/testing/testdata/optikit/examples/designs/microscopes/fluorescence.dsn",
    )
)
needs_design = pytest.mark.skipif(
    not FLUORESCENCE.is_dir(), reason=f"no optikit design at {FLUORESCENCE}"
)


def device(id: str, type: str, config: dict, bindings: dict | None = None) -> optikit.Device:  # noqa: A002
    """A device as `optikit.devices` finds one in a design."""
    return optikit.Device(
        id=id, type=type, path=f"{id}/drivers", component=id, config=config, bindings=bindings or {}
    )


def test_an_earlier_device_file_is_translated_to_the_current_schema() -> None:
    """optikit's v0.1 camera, laser, stage and controller files become newswitch devices."""
    tree = device_tree(
        [
            device(
                "cam",
                "camera",
                {
                    "name": "C",
                    "pixelcount": {
                        "x": 64,
                        "y": 48,
                        "pixelpitch_um": {"x": 5.0},
                        "exposure_time_ms": {"value": 10, "min": 1, "max": 100},
                    },
                },
            ),
            device("las", "laser", {"wavelength_nm": 488, "max_power_mw": 50}),
            device(
                "stg",
                "stage",
                {
                    "axes": [
                        {"label": "x", "travel_um": 1000, "steps_per_um": 8},
                        {"label": "z", "travel_um": 500, "steps_per_um": 25, "inverted": True},
                    ]
                },
                bindings={"x": "sample-x"},
            ),
            device(
                "brd",
                "controller",
                {
                    "protocol": "uc2-rest",
                    "uc2-rest": {
                        "transport": "serial",
                        "serial": {"device-pattern": "/dev/ttyUSB*", "baudrate": 115200},
                    },
                },
            ),
        ]
    )
    from newswitch.config_io import parse_tree

    config = parse_tree(tree)
    assert isinstance(config.devices["cam"], DetectorConfig)
    assert config.devices["cam"].pixelcount == (64, 48)
    assert adapters.illuminations(config)[0].wavelength == 488
    assert isinstance(config.devices["stg-x"], AxisConfig)
    assert config.devices["stg-x"].extras["optikit_dsn_variable"] == "sample-x"
    assert config.devices["stg-z"].inverted is True
    assert adapters.motion_stage(config)[1].axes == {"x": "stg-x", "z": "stg-z"}
    assert isinstance(config.devices["brd"], ControllerConfig)
    assert adapters.serial_settings(config).baudrate == 115200


def test_a_device_file_in_the_current_schema_is_taken_as_it_is() -> None:
    """A device file written for newswitch passes through, without its provenance keys."""
    tree = device_tree(
        [
            device(
                "las",
                "lightsource",
                {
                    "newswitch_version": "v1.0.2",
                    "type": "lightsource",
                    "wavelength": 561,
                    "device_id": "las",
                },
            )
        ]
    )
    assert tree["devices"]["las"] == {"type": "lightsource", "wavelength": 561}


def test_a_device_newswitch_cannot_translate_is_named() -> None:
    """An unknown kind of an earlier schema is refused, with the device named."""
    with pytest.raises(DesignConfigError, match="pump"):
        device_tree([device("pump", "pump", {})])


@needs_design
def test_the_fluorescence_design_is_a_newswitch_configuration() -> None:
    """Camera, laser, an xyz stage on its design inputs, and the mainboard."""
    config = design_config(FLUORESCENCE)
    kinds = sorted(type(d).__name__ for d in config.devices.values())
    assert kinds == [
        "AxisConfig",
        "AxisConfig",
        "AxisConfig",
        "ControllerConfig",
        "DetectorConfig",
        "LightsourceConfig",
        "StageConfig",
    ]
    variables = {
        d.extras.get("optikit_dsn_variable")
        for d in config.devices.values()
        if isinstance(d, AxisConfig)
    }
    assert variables == {"sample-x", "sample-y", "sample-z"}
    assert adapters.objective_lenses(config) is None and adapters.filters(config) is None


def declared_bloks(**config: str) -> dict:
    """The bloks a fresh process declares for a config: one UI per process."""
    code = (
        "import json, newswitch.app\n"
        "from newswitch.arkitekt_app import nsapp\n"
        "from newswitch.bloks import declare_ui\n"
        "from newswitch.config import ImswitchConfig\n"
        f"declare_ui(ImswitchConfig(config_file=None, **{config!r}))\n"
        "print(json.dumps({k: [b.catalog, b.default] for k, b in nsapp.registry.get_declared_bloks().items()}))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_ui_minimal_shows_the_minimal_view_first() -> None:
    """ui=minimal: the minimal view is the default, the standard one a tab beside it."""
    bloks = declared_bloks(ui="minimal")
    assert bloks["view-minimal"] == ["newswitch", True]
    assert bloks["view-standard"] == ["newswitch", False]


@needs_design
def test_the_design_ui_shows_the_designs_devices() -> None:
    """ui=design declares the design's UI and a card per device it has."""
    pytest.importorskip("pyvista")
    bloks = declared_bloks(ui="design", design=str(FLUORESCENCE))
    assert bloks["view-3d"] == ["newswitch", True]
    assert bloks["view-stage"] == ["newswitch", False]
    assert bloks["view-minimal"] == ["newswitch", False]
    assert {"design-camera", "design-laser", "design-stage"} <= set(bloks)
    assert "view-standard" not in bloks
