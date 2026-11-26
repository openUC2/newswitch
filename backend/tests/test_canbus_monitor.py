"""The CAN bus monitor decodes what the Pi sends and the nodes answer (`newswitch.tools.canbus`)."""

import pytest

from newswitch.tools.canbus import Decoder, ObjectType, node_names

TYPES = {
    0x2000: ObjectType("motor_target_position", "i"),
    0x2016: ObjectType("homing_status", "B"),
    0x2500: ObjectType("firmware_version"),
}


def decoder() -> Decoder:
    """A decoder with a few of the firmware's objects, and the frame's motors."""
    return Decoder(TYPES, motors={10, 11, 12, 13})


def frame(text: str) -> bytes:
    """A frame's data, written as candump shows it."""
    return bytes.fromhex(text)


def test_a_write_and_its_answer_are_named_by_the_object() -> None:
    """An expedited write goes out with its value, its answer comes in."""
    sdo = decoder()
    write = sdo.decode(0x60D, frame("23 00 20 01 00 fb ff ff"))
    assert (write.sent, write.node, write.text) == (
        True,
        13,
        "write motor_target_position[1] = -1280",
    )
    answer = sdo.decode(0x58D, frame("60 00 20 01 00 00 00 00"))
    assert (answer.sent, answer.text) == (False, "ok, motor_target_position[1] written")


def test_a_read_answer_is_unpacked_as_its_type() -> None:
    """A value is unpacked as the dictionary types it, and a homing status named."""
    sdo = decoder()
    assert sdo.decode(0x60D, frame("40 16 20 01 00 00 00 00")).text == "read homing_status[1]"
    answer = sdo.decode(0x58D, frame("4f 16 20 01 02 00 00 00"))
    assert answer.text == "homing_status[1] = 2 (done)"


def test_a_segmented_read_is_shown_as_the_one_value_it_makes() -> None:
    """The segments of a string are parts; the last shows the whole string."""
    sdo = decoder()
    sdo.decode(0x60D, frame("40 00 25 00 00 00 00 00"))
    started = sdo.decode(0x58D, frame("41 00 25 00 0b 00 00 00"))
    assert started.part
    assert sdo.decode(0x60D, frame("60 00 00 00 00 00 00 00")).part
    first = sdo.decode(0x58D, frame("00 76 32 30 32 36 2e 30"))  # "v2026.0", 7 bytes, more to come
    assert first.part
    sdo.decode(0x60D, frame("70 00 00 00 00 00 00 00"))
    last = sdo.decode(0x58D, frame("17 2e 31 2d 62 00 00 00"))  # ".1-b", 4 bytes, the last
    assert not last.part and last.text == "firmware_version = 'v2026.0.1-b'"


def test_an_abort_says_why() -> None:
    """An SDO abort is an alarm, with its reason in words."""
    abort = decoder().decode(0x58D, frame("80 00 20 01 02 00 01 06"))
    assert abort.alarm and "read-only object" in abort.text


def test_a_motor_reports_its_position_other_nodes_their_bytes() -> None:
    """A motor's TPDO1 is a position; a laser's is shown as it is."""
    sdo = decoder()
    motor = sdo.decode(0x18D, frame("00 fb ff ff 01 02 00 00"))
    assert motor.periodic and motor.text == "at -1280 steps, running, homing done"
    laser = sdo.decode(0x194, frame("00 00 00 00 02 00 00 00"))
    assert laser.text == "00 00 00 00 02 00 00 00"


def test_heartbeats_nmt_and_sync() -> None:
    """Heartbeats come in and repeat, a boot-up does not; NMT and SYNC go out."""
    sdo = decoder()
    beat = sdo.decode(0x70D, frame("05"))
    assert (beat.sent, beat.periodic, beat.text) == (False, True, "operational")
    assert not sdo.decode(0x70D, frame("00")).periodic  # a boot-up is news every time
    start = sdo.decode(0x000, frame("01 00"))
    assert (start.sent, start.node, start.text) == (True, 0, "start (every node)")
    assert sdo.decode(0x080, b"").sent


def test_a_block_write_ends_with_the_servers_answer() -> None:
    """A block transfer's frames are parts until the server ends it."""
    sdo = decoder()
    assert (
        sdo.decode(0x60D, frame("c6 00 25 00 00 01 00 00")).text == "block write firmware_version"
    )
    assert sdo.decode(0x58D, frame("a4 00 25 00 7f 00 00 00")).part
    assert sdo.decode(0x60D, frame("01 de ad be ef 00 11 22")).part  # data, whatever its first byte
    assert sdo.decode(0x60D, frame("c9 00 00 00 00 00 00 00")).part  # the client's end
    done = sdo.decode(0x58D, frame("a1 00 00 00 00 00 00 00"))
    assert not done.part and done.text.startswith("block write of firmware_version done")
    assert sdo.decode(0x60D, frame("40 00 25 00 00 00 00 00")).text == "read firmware_version"


def test_nodes_are_named_by_the_board_and_share_an_id() -> None:
    """The board's node map names the nodes; two on one id share it."""
    names = node_names({"node_a": 10, "node_laser": 20, "node_led": 20})
    assert names[10] == "A" and names[20] == "laser/led" and names[1] == "master"
    assert names[13] == "Z"  # left out: uc2canopen's default


def test_the_firmwares_objects_are_named_and_typed() -> None:
    """uc2canopen's dictionary names and types the objects, CANopen's own are named."""
    pytest.importorskip("uc2canopen")
    from newswitch.tools.canbus import object_types

    types = object_types()
    assert types[0x2000] == ObjectType("motor_target_position", "i")
    assert types[0x2500].name == "firmware_version" and types[0x2500].fmt is None
    assert types[0x260F].name == "galvo_camera_trigger_mode"  # not its deprecated alias
    assert types[0x1017].name == "heartbeat_time"
