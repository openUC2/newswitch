"""A microscope described by an optikit design: its devices, its model and its UI."""

import json
import os
from pathlib import Path

import pytest

from main_fastapi import create_fastapi_registry
from newswitch.config_io import adapters
from newswitch.config_io.devices import AxisConfig, ControllerConfig, DetectorConfig
from newswitch.design.config import DesignConfigError, design_config, device_tree
from newswitch.optikit import dsn as optikit

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


@needs_design
def test_a_built_configuration_carries_the_design_ui(tmp_path: Path) -> None:
    """The build writes the devices and the bloks; newswitch declares them as written."""
    pytest.importorskip("pyvista")
    from newswitch import config_io
    from newswitch.bloks import load_catalog
    from newswitch.design.build import build

    out = build(FLUORESCENCE, tmp_path / "newswitch-config.fluorescence.yaml")
    loaded = config_io.load_config(out).config
    assert loaded.ui is not None and "design" in loaded.assets
    assert loaded.ui.catalog == load_catalog().id
    assert loaded.ui.bloks["view-3d"].default
    assert "<Model" in loaded.ui.bloks["view-3d"].bsx

    bloks = {
        k: [b.module, b.default]
        for k, b in create_fastapi_registry(loaded).registry.get_declared_bloks().items()
    }
    assert bloks["view-3d"] == ["newswitch", True]
    assert {"view-fluorescence", "view-stage", "view-minimal", "design-camera"} <= set(bloks)
    assert "view-standard" not in bloks


def test_the_fluorescence_fragments_are_bloks() -> None:
    """Every fragment compiles on its own, and calibrating stands in for acquiring."""
    from arkitekt import bsx

    from newswitch.bloks import fluorescence

    for fragment in (
        fluorescence.ACQUIRE_OR_CALIBRATE,
        fluorescence.EXCITATION,
        fluorescence.EMISSION,
        fluorescence.DETECTION,
        fluorescence.READINESS,
    ):
        assert bsx(fragment)
    choice = json.dumps(bsx(fluorescence.ACQUIRE_OR_CALIBRATE), default=str)
    assert "calibrate_light_path" in choice and "capture_image" in choice
    assert "val.is_empty" in choice
