"""CAN light outputs can share the bus with motors without losing their addresses."""

from __future__ import annotations

from typing import Any

import pytest

from newswitch.config_io import ConfigError, load_config

from .conftest import DocWriter


def _can_bus() -> dict[str, Any]:
    return {
        "protocol": "can-bus",
        "transport": {"type": "can", "interface": "socketcan", "channel": "can0"},
    }


def test_stage_lasers_and_led_share_can_bus(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """Motors, lasers and an LED matrix can have distinct addresses on one bus."""
    stage = minimal_doc["devices"]["stage"]
    del stage["controller"]
    stage["connection"] = _can_bus()
    stage["axes"][1]["steps_per_um"] = 8.0
    for axis, node in zip(stage["axes"], (11, 13), strict=True):
        axis["binding"] = {"type": "canopen-motor", "node_id": node}
    laser = minimal_doc["devices"]["laser"]
    del laser["controller"]
    laser["connection"] = _can_bus()
    laser["binding"] = {"type": "canopen-laser", "node_id": 21, "channel": 0}
    led = minimal_doc["devices"]["led"]
    del led["controller"]
    led["connection"] = _can_bus()
    led["wavelength"] = 0
    led["binding"] = {"type": "canopen-led-matrix", "node_id": 20}

    config = load_config(write_doc(minimal_doc)).config
    assert config.devices["laser"].binding.node_id == 21
    assert config.devices["led"].binding.node_id == 20
    assert config.devices["led"].wavelength == 0


def test_duplicate_laser_output_is_rejected(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """Two light sources cannot claim the same laser node and channel."""
    for source_name in ("laser", "led"):
        source = minimal_doc["devices"][source_name]
        del source["controller"]
        source["connection"] = _can_bus()
        source["binding"] = {"type": "canopen-laser", "node_id": 21, "channel": 0}
    with pytest.raises(ConfigError, match="CAN light output is already used"):
        load_config(write_doc(minimal_doc))


def test_can_light_requires_can_connection(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """A CAN address is invalid when the source resolves to a serial controller."""
    minimal_doc["devices"]["laser"]["binding"] = {
        "type": "canopen-laser",
        "node_id": 21,
        "channel": 0,
    }
    with pytest.raises(ConfigError, match="CAN light binding requires a CAN connection"):
        load_config(write_doc(minimal_doc))
