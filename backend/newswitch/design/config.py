"""The newswitch device configuration an optikit design describes.

A design's parts that are devices carry a newswitch device file (``optikit.devices``).
Their configs become one newswitch configuration in the current schema, validated like a
file (``config_io.parse_tree``), so a design can stand in for ``newswitch-config.yaml``.

A device file written in the newswitch schema (``newswitch_version: v1...``) is taken as it
is. optikit's earlier device files (``newswitch-version: v0.1...``: ``camera``, ``laser``,
``stage`` with inline axes, ``controller`` with ``protocol``) are translated.
"""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from newswitch import config_io
from newswitch.optikit import dsn as optikit

#: Keys of a device file that only say where it came from.
_PROVENANCE = ("device_id", "controller", "newswitch_version", "newswitch-version")


def _schema_version() -> str:
    """The ``newswitch_version`` a generated configuration states: the running newswitch."""
    try:
        return f"v{version('newswitch')}"
    except PackageNotFoundError:
        return "v1.0.2"


class DesignConfigError(ValueError):
    """The design's devices do not make a newswitch configuration."""


def _is_current(config: dict[str, Any]) -> bool:
    """Whether a device file is already in the newswitch schema."""
    return str(config.get("newswitch_version", "")).startswith("v1")


def _common(config: dict[str, Any]) -> dict[str, Any]:
    return {key: config[key] for key in ("name", "manufacturer", "tags") if config.get(key)}


def _phys(spec: Any, unit: str) -> dict[str, Any] | None:  # noqa: ANN401 - raw yaml
    """A v0.1 ``{value, min, max, increment}`` as a newswitch physical value."""
    if not isinstance(spec, dict):
        return None
    phys = {key: spec[key] for key in ("value", "min", "max") if spec.get(key) is not None}
    if spec.get("increment") is not None:
        phys["inc"] = spec["increment"]
    return {**phys, "unit": unit} if phys else None


def _camera(config: dict[str, Any]) -> dict[str, Any]:
    pixels = config.get("pixelcount") or {}
    detector: dict[str, Any] = {"type": "detector", **_common(config)}
    if pixels.get("x") and pixels.get("y"):
        detector["pixelcount"] = [int(pixels["x"]), int(pixels["y"])]
    pitch = (pixels.get("pixelpitch_um") or {}).get("x")
    if pitch:
        detector["pixelpitch_um"] = float(pitch)
    for key, unit in (("exposure_time_ms", "ms"), ("framerate_per_sec", "Hz"), ("gain_db", "dB")):
        phys = _phys(pixels.get(key), unit)
        if phys:
            detector[key] = phys
    for key in ("channels", "binning", "trigger"):
        if pixels.get(key) is not None:
            detector[key] = pixels[key]
    return detector


def _laser(config: dict[str, Any]) -> dict[str, Any]:
    source: dict[str, Any] = {"type": "lightsource", **_common(config), "coherence": "coherent"}
    if config.get("wavelength_nm"):
        source["wavelength"] = float(config["wavelength_nm"])
    if config.get("max_power_mw"):
        source["max_power_mw"] = float(config["max_power_mw"])  # kept as an extra
    return source


def _input_reach_um(inputs: dict[str, Any], name: str | None) -> float | None:
    """How far a design input reaches, in um (its ``max`` in its ``units``), if it says."""
    declared = inputs.get(name or "") or {}
    unit = optikit.LENGTH_UNITS.get(str(declared.get("units") or "mm"))
    if declared.get("max") is None or unit is None:
        return None
    return float(declared["max"]) * unit * 1000.0  # LENGTH_UNITS are mm per unit


def _stage(
    key: str, config: dict[str, Any], bindings: dict[str, str], inputs: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """A v0.1 stage: one ``axis`` device per axis, and the ``stage`` naming them.

    An axis reaches as far as the device travels and the design's input allows, whichever
    is less: the model only shows the stage within the design's range.
    """
    devices: dict[str, dict[str, Any]] = {}
    axes: dict[str, str] = {}
    speed = config.get("max_speed_um_per_sec")
    for axis in config.get("axes") or []:
        label = str(axis["label"])
        axis_key = f"{key}-{label}"
        travel = float(axis.get("travel_um") or 0.0)
        reach = _input_reach_um(inputs, bindings.get(label))
        if reach is not None:
            travel = min(travel, reach) if travel else reach
        device: dict[str, Any] = {
            "type": "axis",
            "steps_per_um": axis.get("steps_per_um"),
            "inverted": bool(axis.get("inverted", False)),
            "homing_required": bool(config.get("homing_required", False)),
            "pos": {"min": 0.0, "max": travel, "unit": "um"},
        }
        if speed:
            device["vel"] = {"value": float(speed), "unit": "um/s"}
        if label in bindings:
            # The design input that moves this axis in the model (and in optikit).
            device["optikit_dsn_variable"] = bindings[label]
        devices[axis_key] = device
        axes[label] = axis_key
    devices[key] = {"type": "stage", **_common(config), "axes": axes}
    return devices


def _controller(config: dict[str, Any]) -> dict[str, Any]:
    protocol = config.get("protocol")
    settings = config.get(str(protocol)) or {}
    serial = settings.get("serial") or {}
    if protocol != "uc2-rest" or settings.get("transport") != "serial":
        raise DesignConfigError(
            f"controller protocol {protocol!r} over {settings.get('transport')!r} "
            "cannot be translated; write its device file in the newswitch schema"
        )
    transport: dict[str, Any] = {"type": "serial"}
    if serial.get("device-pattern"):
        transport["port_pattern"] = serial["device-pattern"]
    if serial.get("baudrate"):
        transport["baudrate"] = int(serial["baudrate"])
    controller: dict[str, Any] = {
        "type": "controller",
        **_common(config),
        "connection": {"protocol": "uc2-rest", "transport": transport},
        # v0.1 files carry no addresses: which output drives which device is unknown.
        "mapping": {},
    }
    if config.get("firmware"):
        controller["firmware"] = config["firmware"]
    return controller


def device_tree(
    design_devices: list[optikit.Device], inputs: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The newswitch configuration document for a design's devices.

    ``inputs`` are the design's input declarations (their ranges limit the stage axes).
    """
    inputs = inputs or {}
    devices: dict[str, Any] = {}
    for device in design_devices:
        config = dict(device.config)
        if _is_current(config):
            devices[device.id] = {
                key: value for key, value in config.items() if key not in _PROVENANCE
            }
        elif device.type == "camera":
            devices[device.id] = _camera(config)
        elif device.type == "laser":
            devices[device.id] = _laser(config)
        elif device.type == "stage":
            devices.update(_stage(device.id, config, device.bindings, inputs))
        elif device.type == "controller":
            devices[device.id] = _controller(config)
        else:
            raise DesignConfigError(
                f"{device.id} ({device.path}) is a {device.type!r} device file of an "
                "earlier schema newswitch cannot translate; write it in the newswitch schema"
            )
    return {"newswitch_version": _schema_version(), "devices": devices}


def design_config(dsn: str | Path) -> config_io.NewswitchConfig:
    """The newswitch configuration of the design at ``dsn``, validated.

    Raises:
        DesignConfigError: A device cannot be translated.
        config_io.ConfigError: The result does not validate.
    """
    dsn = Path(dsn)
    tree = device_tree(optikit.devices(dsn), optikit.load_design(dsn).inputs)
    return config_io.parse_tree(tree, name=f"design {dsn.name}")
