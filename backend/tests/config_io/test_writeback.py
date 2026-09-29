"""Tests for writing runtime and firmware values back into the YAML file."""

from __future__ import annotations

import textwrap

import pytest

from newswitch.config_io import ConfigError, load_config

from .conftest import DocWriter

DOC = textwrap.dedent(
    """\
    # top comment
    newswitch_version: v1.0.0
    devices:
      mainboard:
        type: controller
        name: Board
        connection:
          protocol: uc2-rest
          transport: {type: serial, port: /dev/ttyUSB0}
        firmware: {name: fw, version: v1}

      cam:
        type: detector
        name: Cam   # inline comment
        controller: mainboard
        exposure_time_ms:
          value: 10.0
          min: 0.1
          max: 1000.0
          unit: ms
        gain_db: 2.0
        framerate_per_sec: null

      stage:
        type: stage
        name: XY
        controller: mainboard
        axes:
          - label: x
            steps_per_um: 8.0
            homing_required: true
            pos: {value: 0.0, min: 0.0, max: 1000.0, unit: um}

      wheel:
        type: revolver
        name: Wheel
        controller: mainboard
        channels: [gfp, null]

      gfp:
        type: filter
        name: GFP
        wavelength: 525
    """
)


def _saved(write_doc: DocWriter, change: object = None) -> str:
    path = write_doc(DOC)
    cfg_file = load_config()
    if callable(change):
        change(cfg_file)
    cfg_file.save(backup=False)
    return path.read_text(encoding="utf-8")


def test_scalar_and_null_phys_become_mappings(write_doc: DocWriter) -> None:
    """Unchanged, only the scalar physical value is rewritten, as a mapping."""
    text = _saved(write_doc)
    expected = DOC.replace("    gain_db: 2.0\n", "    gain_db:\n      value: 2.0\n      unit: dB\n")
    assert text == expected  # comments, blank lines and flow style survive


def test_untouched_file_is_identical(write_doc: DocWriter) -> None:
    """A file without scalar physical values survives a save byte for byte."""
    doc = DOC.replace("    gain_db: 2.0\n", "")
    path = write_doc(doc)
    load_config().save(backup=False)
    assert path.read_text(encoding="utf-8") == doc


def test_runtime_value_written(write_doc: DocWriter) -> None:
    """A value changed at runtime replaces the old one in place."""

    def change(cfg_file: object) -> None:
        cfg_file.config.devices["cam"].exposure_time_ms.value = 20.0
        cfg_file.config.devices["stage"].axes[0].pos.value = 12.5
        cfg_file.config.devices["wheel"].selected_channel = 1

    text = _saved(write_doc, change)
    assert "      value: 20.0\n      min: 0.1" in text
    assert "pos: {value: 12.5, min: 0.0, max: 1000.0, unit: um}" in text
    assert "    channels: [gfp, null]\n    selected_channel: 1\n\n  gfp:" in text


def test_firmware_limits_keep_value(write_doc: DocWriter) -> None:
    """Limits reported by the device are added; the user's value stays."""

    def change(cfg_file: object) -> None:
        cfg_file.apply_firmware(
            "cam",
            {
                "exposure_time_ms": {"value": 99.0, "max": 500.0, "inc": 0.01},
                "framerate_per_sec": {"min": 1.0, "max": 60.0, "preset_vals": [10, 30]},
                "pixelcount": [1920, 1080],
            },
        )

    text = _saved(write_doc, change)
    assert (
        "      value: 10.0\n      min: 0.1\n      max: 500.0\n      unit: ms\n      inc: 0.01"
        in text
    )
    assert (
        "framerate_per_sec:\n      min: 1.0\n      max: 60.0\n      unit: Hz\n      preset_vals: [10.0, 30.0]"
        in text
    )
    # a new key goes above the blank line that separates devices
    assert "    pixelcount: [1920, 1080]\n\n  stage:" in text


def test_firmware_full_and_units(write_doc: DocWriter) -> None:
    """Axis values are taken over completely and converted into the field's unit."""

    def change(cfg_file: object) -> None:
        cfg_file.apply_firmware(
            "stage", {"axes": {"x": {"vel": {"value": 2.0, "max": 5.0, "unit": "mm/s"}}}}
        )

    text = _saved(write_doc, change)
    assert (
        "        vel:\n          value: 2000.0\n          max: 5000.0\n          unit: um/s\n"
        in text
    )


def test_defaults_are_never_added(write_doc: DocWriter) -> None:
    """Fields the file does not state and nobody set stay absent."""
    text = _saved(write_doc)
    for key in (
        "binning:",
        "channels: 1",
        "manufacturer:",
        "acc:",
        "inverted:",
        "selected_channel:",
    ):
        assert key not in text


def test_rejects_non_firmware_fields(write_doc: DocWriter) -> None:
    """Only fields marked x_firmware can be reported."""
    write_doc(DOC)
    cfg_file = load_config()
    with pytest.raises(ConfigError, match="not a firmware-provided field"):
        cfg_file.apply_firmware("gfp", {"wavelength": 600})
    with pytest.raises(ConfigError, match="no such axis"):
        cfg_file.apply_firmware("stage", {"axes": {"z": {"vel": 1.0}}})
    with pytest.raises(ConfigError, match="invalid"):
        cfg_file.apply_firmware("cam", {"exposure_time_ms": {"max": 1.0}})  # value 10 > max


def test_invalid_runtime_state_is_not_saved(write_doc: DocWriter) -> None:
    """An out-of-range runtime value blocks the save and leaves the file alone."""
    path = write_doc(DOC)
    cfg_file = load_config()
    cfg_file.config.devices["cam"].exposure_time_ms.value = 5000.0
    with pytest.raises(ConfigError, match="refusing to save"):
        cfg_file.save()
    assert path.read_text(encoding="utf-8") == DOC


def test_backup(write_doc: DocWriter) -> None:
    """save() keeps the previous file as .bak by default."""
    path = write_doc(DOC)
    load_config().save()
    assert path.with_name(path.name + ".bak").read_text(encoding="utf-8") == DOC


def test_save_twice_writes_only_new_changes(write_doc: DocWriter) -> None:
    """After a save the snapshot is current, so a second save changes nothing."""
    path = write_doc(DOC)
    cfg_file = load_config()
    cfg_file.save(backup=False)
    first = path.read_text(encoding="utf-8")
    cfg_file.save(backup=False)
    assert path.read_text(encoding="utf-8") == first
    assert load_config().config.devices["cam"].gain_db.value == 2.0
