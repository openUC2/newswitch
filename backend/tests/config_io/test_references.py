"""Cross-device checks: stage axes, controller mappings and shared physical resources."""

from __future__ import annotations

import copy
from typing import Any, Callable

import pytest

from newswitch.config_io import ConfigError, ConfigWarning, load_config

from .conftest import CONTROLLER, DocWriter

Change = Callable[[dict[str, Any]], None]


def _problems(write_doc: DocWriter, doc: dict[str, Any]) -> list[str]:
    with pytest.raises(ConfigError) as info:
        load_config(write_doc(doc))
    return info.value.problems


def _serial(port: str, baudrate: int = 115200) -> dict[str, Any]:
    return {
        "protocol": "uc2-rest",
        "transport": {"type": "serial", "port": port, "baudrate": baudrate},
    }


def _second_board(devices: dict[str, Any], **changes: Any) -> None:  # noqa: ANN401
    devices["board2"] = {**copy.deepcopy(CONTROLLER), "mapping": {}, **changes}


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda d: d["stage"]["axes"].update(y="missing"),
            "devices.stage.axes.y: no device 'missing'",
        ),
        (
            lambda d: d["stage"]["axes"].update(y="cam"),
            "devices.stage.axes.y: 'cam' is a detector, expected axis",
        ),
        (
            lambda d: d["turret"]["axes"].update(x="ax-x"),
            "'ax-x' appears in more than one stage: devices.stage.axes.x, devices.turret.axes.x",
        ),
        (
            lambda d: d["stage"]["axes"].update(y="ax-x"),
            "'ax-x' appears in more than one stage: devices.stage.axes.x, devices.stage.axes.y",
        ),
        (
            lambda d: _second_board(d, mapping={"cam": {"type": "camera", "id": 7}}),
            "'cam' appears in more than one controller mapping: "
            "devices.mainboard.mapping.cam, devices.board2.mapping.cam",
        ),
    ],
)
def test_reference_errors(
    write_doc: DocWriter, minimal_doc: dict[str, Any], change: Change, expected: str
) -> None:
    """Dangling or mistyped stage axes and devices claimed twice are errors."""
    change(minimal_doc["devices"])
    assert expected in _problems(write_doc, minimal_doc)


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("ghost", "devices.mainboard.mapping.ghost: no device 'ghost'"),
        ("gfp", "devices.mainboard.mapping.gfp: 'gfp' is a filter, expected lightsource or"),
    ],
)
def test_mapping_problems_only_warn(
    write_doc: DocWriter, minimal_doc: dict[str, Any], entry: str, expected: str
) -> None:
    """A mapping entry naming no mappable device is a warning; the file still loads."""
    minimal_doc["devices"]["mainboard"]["mapping"][entry] = {"type": "x", "id": 99}
    with pytest.warns(ConfigWarning, match=expected):
        config = load_config(write_doc(minimal_doc)).config
    assert entry in config.controllers[0].mapping


def test_stage_may_be_mapped(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A whole stage (e.g. a wheel driven as one unit) is a valid mapping target."""
    minimal_doc["devices"]["mainboard"]["mapping"]["turret"] = {"type": "revolver", "id": 5}
    load_config(write_doc(minimal_doc))


def test_address_clash_names_the_device(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Two devices on one id/subid fail with the controller's path."""
    minimal_doc["devices"]["mainboard"]["mapping"]["ax-z"]["id"] = 11
    problems = _problems(write_doc, minimal_doc)
    assert problems == [
        "devices.mainboard: Value error, mapping: id 11/subid 0 is used by ax-x, ax-z"
    ]


def test_same_address_on_two_controllers_is_fine(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """Addresses only need to be unique per controller."""
    minimal_doc["devices"]["gfp-axis"] = {"type": "axis", "steps_per_um": 1.0}
    _second_board(minimal_doc["devices"], mapping={"gfp-axis": {"type": "motor", "id": 11}})
    load_config(write_doc(minimal_doc))


def test_shared_resource_conflict(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Two controllers on one port must agree on its settings."""
    minimal_doc["devices"]["mainboard"]["connection"] = _serial("/dev/ttyUSB0")
    _second_board(minimal_doc["devices"], connection=_serial("/dev/ttyUSB0", 9600))
    problems = _problems(write_doc, minimal_doc)
    assert any("shared resource" in p and "baudrate" in p for p in problems), problems


def test_controllers_on_separate_ports(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Different ports are different resources."""
    minimal_doc["devices"]["mainboard"]["connection"] = _serial("/dev/ttyUSB0")
    _second_board(minimal_doc["devices"], connection=_serial("/dev/ttyUSB1", 9600))
    load_config(write_doc(minimal_doc))


def test_simulated_controllers_share_nothing(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """Simulated controllers occupy no physical resource, so any number may coexist."""
    _second_board(minimal_doc["devices"])
    minimal_doc["devices"]["board3"] = {**copy.deepcopy(CONTROLLER), "mapping": {}}
    load_config(write_doc(minimal_doc))


@pytest.mark.parametrize(
    ("connection", "expected"),
    [
        (
            {"protocol": "can-bus", "transport": {"type": "can"}},
            "devices.mainboard.connection.protocol: 'can-bus' is not a known protocol",
        ),
        (
            {"protocol": "canopen"},
            "devices.mainboard.connection: 'transport' is a required property",
        ),
        (
            {"protocol": "canopen", "transport": {"type": "can", "interface": "waveshare"}},
            "waveshare CAN interface needs a serial port",
        ),
        (
            {"protocol": "uc2-rest", "transport": {"type": "can"}},
            "devices.mainboard.connection.transport.type: 'can' is not a known type",
        ),
        (
            {"protocol": "simulated", "transport": {"type": "simulated", "port": "x"}},
            "devices.mainboard.connection.transport: Additional properties are not allowed",
        ),
    ],
)
def test_connection_errors(
    write_doc: DocWriter, minimal_doc: dict[str, Any], connection: dict[str, Any], expected: str
) -> None:
    """Connections stay strict, and errors name the offending protocol or transport."""
    minimal_doc["devices"]["mainboard"]["connection"] = connection
    problems = _problems(write_doc, minimal_doc)
    assert any(p.startswith(expected) or expected in p for p in problems), problems


def test_canopen_controller(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """CAN controllers speak canopen; nodes are addressed by the mapping, not the connection."""
    minimal_doc["devices"]["mainboard"]["connection"] = {
        "protocol": "canopen",
        "transport": {"type": "can", "interface": "socketcan", "channel": "can0"},
    }
    config = load_config(write_doc(minimal_doc)).config
    controller = config.controller_of("ax-z")
    assert controller is not None and controller[1].address == (13, 0)
