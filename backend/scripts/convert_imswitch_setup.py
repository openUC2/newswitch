"""Convert an ImSwitch setup JSON into a newswitch NEWSWITCH_CONFIG file.

Maps ImSwitch's per-device managerName/managerProperties model onto the
newswitch ImswitchConfig schema (flat transport fields + nested
uc2_can/uc2_rest/uc2_stage/uc2_illumination overrides).

Usage:
    python scripts/convert_imswitch_setup.py <imswitch_setup.json> [-o out.json]

Covered: rs232devices (ESP32Manager -> rest, UC2CANOpenManager -> canopen),
positioners (stepsize -> steps_per_um incl. axis sign, limits, speeds),
lasers (channel/wavelength/value range -> illumination sources). Devices
newswitch does not model yet (detectors, LEDMatrix patterns, feature blocks)
are reported as skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STAGE_MANAGERS = {"ESP32StageManager", "UC2CANOpenStageManager", "VirtualStageManager"}
LASER_MANAGERS = {"ESP32LEDLaserManager", "UC2CANOpenLaserManager", "ESP32LightSheetManager"}


def _steps_per_unit(stepsize: "float | str | None", default: float = 3.2) -> float:
    """Convert an ImSwitch stepsize (um per step, sign = axis direction) to steps/um."""
    try:
        value = float(stepsize)
    except (TypeError, ValueError):
        return default
    if value == 0:
        return default
    return 1.0 / value  # keeps the sign: negative stepsize -> inverted axis


def convert_setup(setup: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Convert an ImSwitch setup dict; returns (newswitch config, skipped notes)."""
    skipped: list[str] = []
    config: dict[str, Any] = {"use_virtual_microscope": False}

    # -- transport from rs232devices ------------------------------------------
    transport = None
    for name, device in (setup.get("rs232devices") or {}).items():
        manager = device.get("managerName", "")
        properties = device.get("managerProperties", {}) or {}
        if manager == "UC2CANOpenManager":
            transport = "canopen"
            config["uc2_transport"] = "canopen"
            config["uc2_can_interface"] = properties.get("interface")
            config["uc2_can_channel"] = properties.get("channel")
            config["uc2_can_port"] = properties.get("port")
            can: dict[str, Any] = {}
            if "bitrate" in properties:
                can["bitrate"] = properties["bitrate"]
            for axis in ("X", "Y", "Z", "A"):
                node_key = f"nodeId{axis}"
                if node_key in properties:
                    can[f"node_{axis.lower()}"] = properties[node_key]
            if "ledNodeId" in properties:
                can["node_led"] = properties["ledNodeId"]
            if "laserNodeId" in properties:
                can["node_laser"] = properties["laserNodeId"]
            config["uc2_can"] = can
        elif manager == "ESP32Manager":
            transport = "rest"
            config["uc2_transport"] = "rest"
            serialport = properties.get("serialport")
            # ImSwitch used Windows COM ports and host IPs; keep the port only
            # if it looks like a usable device path, else fall back to autodetect.
            if isinstance(serialport, str) and serialport.startswith("/dev/"):
                config["uc2_serial_port"] = serialport
            else:
                config["uc2_serial_port"] = None
                if serialport:
                    skipped.append(
                        f"rs232 {name}: serialport {serialport!r} not portable -> autodetect"
                    )
            if "baudrate" in properties:
                config["uc2_baudrate"] = properties["baudrate"]
            rest: dict[str, Any] = {}
            if "identity" in properties:
                rest["identity"] = properties["identity"]
            config["uc2_rest"] = rest
        else:
            skipped.append(f"rs232 {name}: unsupported manager {manager}")
    if transport is None:
        skipped.append("no UC2 rs232 device found; defaulting to canopen transport")
        config["uc2_transport"] = "canopen"

    # -- stage from positioners ------------------------------------------------
    for name, positioner in (setup.get("positioners") or {}).items():
        manager = positioner.get("managerName", "")
        if manager not in STAGE_MANAGERS:
            skipped.append(f"positioner {name}: unsupported manager {manager}")
            continue
        properties = positioner.get("managerProperties", {}) or {}
        axes = positioner.get("axes") or ["X", "Y", "Z", "A"]
        config["uc2_stage"] = {"axes": [axis.upper() for axis in axes]}
        scaling: dict[str, Any] = {}
        for axis in ("X", "Y", "Z"):
            key = f"stepsize{axis}"
            if key in properties:
                scaling[f"steps_per_um_{axis.lower()}"] = _steps_per_unit(properties[key])
        if "stepsizeA" in properties:
            scaling["steps_per_deg_a"] = _steps_per_unit(properties["stepsizeA"], default=1.0)
        initial_speed = properties.get("initialSpeed") or {}
        if isinstance(initial_speed, dict) and initial_speed:
            # ImSwitch speeds are steps/s; newswitch default_speed is um/s.
            first_axis = next(iter(("X", "Y", "Z")), None)
            steps_per_um = scaling.get("steps_per_um_x") or 3.2
            speed_steps = initial_speed.get(first_axis or "X")
            if speed_steps:
                scaling["default_speed"] = abs(float(speed_steps) / steps_per_um)
        target = "uc2_can" if config.get("uc2_transport") == "canopen" else "uc2_rest"
        config.setdefault(target, {}).update(scaling)
        break  # newswitch models one stage today

    # -- illumination from lasers ---------------------------------------------
    sources: list[dict[str, Any]] = []
    slot = 0
    for name, laser in (setup.get("lasers") or {}).items():
        manager = laser.get("managerName", "")
        if manager not in LASER_MANAGERS:
            skipped.append(f"laser {name}: unsupported manager {manager}")
            continue
        properties = laser.get("managerProperties", {}) or {}
        channel = properties.get("channel_index")
        if not isinstance(channel, int):
            skipped.append(f"laser {name}: non-numeric channel {channel!r} (LED matrix?)")
            continue
        slot += 1
        sources.append(
            {
                "slot": slot,
                "channel": channel,
                "kind": "LASER" if "laser" in name.lower() or laser.get("wavelength") else "LED",
                "wavelength": float(laser.get("wavelength") or 0.0),
                "intensity": 0.0,
                "min_intensity": float(laser.get("valueRangeMin") or 0.0),
                "max_intensity": float(laser.get("valueRangeMax") or 1023.0),
                "is_active": False,
            }
        )
    if sources:
        pwm_max = int(max(source["max_intensity"] for source in sources))
        config["uc2_illumination"] = {"pwm_max": pwm_max, "sources": sources}

    for section in ("detectors", "LEDMatrixs", "galvoScanners", "rotators"):
        for name in setup.get(section) or {}:
            skipped.append(f"{section} {name}: not converted (handled elsewhere in newswitch)")

    return config, skipped


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("setup", type=Path, help="ImSwitch setup JSON file")
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args(argv)

    setup = json.loads(args.setup.read_text())
    config, skipped = convert_setup(setup)

    text = json.dumps(config, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
        print(f"wrote {args.output}")
    else:
        print(text)
    for note in skipped:
        print(f"# skipped: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
