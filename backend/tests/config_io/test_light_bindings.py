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


def test_named_can_connection_is_shared_by_stage_and_lights(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """One named bus resolves for both a motor binding and laser bindings."""
    minimal_doc["connections"] = {"main-can": _can_bus()}
    stage = minimal_doc["devices"]["stage"]
    del stage["controller"]
    stage["connection"] = "main-can"
    stage["axes"][1]["steps_per_um"] = 8.0
    for axis, node in zip(stage["axes"], (11, 13), strict=True):
        axis["binding"] = {"type": "canopen-motor", "node_id": node}
    laser = minimal_doc["devices"]["laser"]
    del laser["controller"]
    laser["connection"] = "main-can"
    laser["binding"] = {"type": "canopen-laser", "node_id": 21, "channel": 0}

    config = load_config(write_doc(minimal_doc)).config
    assert config.connection_for(config.devices["stage"]) is config.connections["main-can"]
    assert config.connection_for(config.devices["laser"]) is config.connections["main-can"]


def test_unknown_named_connection_is_rejected(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """A mistyped connection name must fail before hardware initialization."""
    stage = minimal_doc["devices"]["stage"]
    del stage["controller"]
    stage["connection"] = "missing-can"
    with pytest.raises(ConfigError, match="no named connection 'missing-can'"):
        load_config(write_doc(minimal_doc))


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


def test_serial_master_laser_and_led_bindings(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """A serial master uses laser channels while its LED matrix needs no channel."""
    minimal_doc["devices"]["laser"]["binding"] = {
        "type": "uc2-master-laser",
        "channel": 1,
    }
    minimal_doc["devices"]["led"]["binding"] = {"type": "uc2-master-led-matrix"}
    config = load_config(write_doc(minimal_doc)).config
    assert config.devices["laser"].binding.channel == 1
    assert config.devices["led"].binding.type == "uc2-master-led-matrix"


def test_duplicate_serial_laser_channel_is_rejected(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """Two laser sources cannot claim one output channel on the same master."""
    for source_name in ("laser", "led"):
        minimal_doc["devices"][source_name]["binding"] = {
            "type": "uc2-master-laser",
            "channel": 1,
        }
    with pytest.raises(ConfigError, match="UC2 master light output is already used"):
        load_config(write_doc(minimal_doc))
