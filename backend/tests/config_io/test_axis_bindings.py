"""Axis addresses must resolve to the right transport and a unique motor."""

from __future__ import annotations

from typing import Any

import pytest

from newswitch.config_io import ConfigError, load_config

from .conftest import DocWriter


def test_canopen_axes_on_shared_bus(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """One CAN bus can serve distinct motor nodes without a per-stage node ID."""
    stage = minimal_doc["devices"]["stage"]
    stage["axes"][1]["steps_per_um"] = 8.0
    del stage["controller"]
    stage["connection"] = {
        "protocol": "can-bus",
        "transport": {"type": "can", "interface": "socketcan", "channel": "can0"},
    }
    stage["axes"][0]["binding"] = {"type": "canopen-motor", "node_id": 11, "sub_axis": 0}
    stage["axes"][1]["binding"] = {"type": "canopen-motor", "node_id": 12, "sub_axis": 0}
    config = load_config(write_doc(minimal_doc)).config
    assert config.stages[0].axes[1].binding.node_id == 12


def test_duplicate_can_motor_rejected(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Two logical axes cannot accidentally drive the same physical motor."""
    minimal_doc["devices"]["stage"]["axes"][1]["steps_per_um"] = 8.0
    for axis in minimal_doc["devices"]["stage"]["axes"]:
        axis["binding"] = {"type": "canopen-motor", "node_id": 11, "sub_axis": 0}
    with pytest.raises(ConfigError, match="same motor"):
        load_config(write_doc(minimal_doc))


def test_binding_must_match_connection(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A serial UC2 master cannot accept a CANopen axis address."""
    minimal_doc["devices"]["stage"]["axes"][1]["steps_per_um"] = 8.0
    for index, axis in enumerate(minimal_doc["devices"]["stage"]["axes"]):
        axis["binding"] = {"type": "canopen-motor", "node_id": index + 11}
    with pytest.raises(ConfigError, match="requires a CAN connection"):
        load_config(write_doc(minimal_doc))


def test_serial_stepper_id_must_match_current_driver(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """The current serial driver has a fixed X/Y/Z/A to stepper-ID mapping."""
    stage = minimal_doc["devices"]["stage"]
    stage["axes"][1]["steps_per_um"] = 8.0
    stage["axes"][0]["binding"] = {"type": "uc2-master", "stepper_id": 2}
    stage["axes"][1]["binding"] = {"type": "uc2-master", "stepper_id": 3}
    with pytest.raises(ConfigError, match="uses 1 for axis 'x'"):
        load_config(write_doc(minimal_doc))


def test_waveshare_needs_port(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A Waveshare CAN connection needs the serial device used by the adapter."""
    stage = minimal_doc["devices"]["stage"]
    del stage["controller"]
    stage["connection"] = {
        "protocol": "can-bus",
        "transport": {"type": "can", "interface": "waveshare"},
    }
    with pytest.raises(ConfigError, match="waveshare CAN interface needs a serial port"):
        load_config(write_doc(minimal_doc))
