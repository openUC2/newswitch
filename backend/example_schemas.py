"""Worked example: importing, inspecting and storing device configs.

Run it from `backend/`::

    uv run python example_schemas.py

It walks through the whole surface of `newswitch.schemas` against the sample files in
`Configs/`, and writes its output files to `Configs/data/`. Nothing here is a test —
it is meant to be read alongside its output. The unit tests live in `tests/`.
"""

from __future__ import annotations

from newswitch.config import get_paths
from newswitch.schemas import (
    CameraSchema,
    ConfigError,
    describe,
    dump_config,
    export_camera_schema,
    export_devices_schema,
    load_camera,
    load_config,
    load_device,
    read_document,
    validate_registry,
)


def section(title: str) -> None:
    """Print a section header.

    Args:
        title: Text of the header.
    """
    print(f"\n=== {title} ===")


def show_folders() -> None:
    """1. Where the schemas package looks for files."""
    section("1. folders (newswitch/config.py)")
    paths = get_paths()
    print(f"config_dir: {paths.config_dir}")
    print(f"schema_dir: {paths.schema_dir}")
    print(f"data_dir:   {paths.data_dir}")


def load_same_camera_twice() -> None:
    """2. The same camera from YAML and from JSON, plus the derived values."""
    section("2. one camera, two formats")
    from_yaml = load_camera("hik_mv_ca023_10um.yaml")
    from_json = load_camera("hik_mv_ca023_10um.json")

    # Same model class, same fields, one code path -- the parser is picked by suffix.
    # The two sample files are not byte-equivalent though: the JSON one adds a
    # `$schema` pointer for editor autocomplete and writes gain as the bare-number
    # shorthand instead of the full {value, min, max, increment} block.
    yaml_fields, json_fields = from_yaml.model_dump(), from_json.model_dump()
    differing = sorted(k for k in yaml_fields if yaml_fields[k] != json_fields[k])
    print(f"fields that differ between the two files: {differing}")
    print(f"gain_db  yaml: {from_yaml.gain_db}")
    print(f"gain_db  json: {from_json.gain_db}   <- scalar shorthand, same model")
    print(f"name:            {from_yaml.name} ({from_yaml.manufacturer})")
    print(f"pixelpitch y:    {from_yaml.pixelpitch_um.y}  <- derived from x")
    print(f"pixelsize:       {from_yaml.pixelsize_um}  <- defaults to the pitch")
    print(f"sensor_size_mm:  {from_yaml.sensor_size_mm}")
    print(f"fill_factor:     {from_yaml.fill_factor:.2f}")


def load_whole_setup() -> None:
    """3. A multi-device file, and the registry lookups it enables."""
    section("3. a whole setup (Devices.yml)")
    registry = load_config("Devices.yml")
    print(describe(registry))
    cameras = registry.by_type("camera")
    print(f"\ncameras: {[c.name for c in cameras]}")


def one_call_for_both_layouts() -> None:
    """4./5. `load_device` reads single-device files and registries alike."""
    section("4. single-device file, name without extension")
    # "hik_mv_ca023_10um" -> Configs/hik_mv_ca023_10um.yaml, and the file has no
    # `type:` key at all -- a bare device document is read as a camera.
    camera = load_device("hik_mv_ca023_10um", expect="camera")
    print(f"{type(camera).__name__}: {camera.name}")

    section("5. one device out of a registry")
    laser = load_device("Devices.yml", "laser-488-001")
    print(f"{type(laser).__name__}: {laser.name} @ {laser.wavelength_nm:.0f} nm")

    stage = load_device("Devices.yml", "stage-xy-001")
    print(f"{type(stage).__name__}: axes {'/'.join(a.label for a in stage.axes)}")

    # Asking for the wrong type, or for a device that is not there, is an error
    # rather than a surprise later on.
    for key, expect in (("laser-488-001", "camera"), ("nope-001", None)):
        try:
            load_device("Devices.yml", key, expect=expect)
        except ConfigError as exc:
            print(f"refused: {exc}")


def limits_of_a_parameter() -> None:
    """6. `Bounded` carries the device's own limits, not just a value."""
    section("6. exposure limits (Bounded)")
    # load_camera() is the camera-only entry point, so the result is a CameraSchema
    # rather than the device union -- no narrowing needed.
    exposure = load_camera("hik_mv_ca023_10um").exposure_time_ms
    assert exposure is not None, "the sample file defines exposure limits"
    print(f"exposure:            {exposure}")
    print(f"clamp(1e6):          {exposure.clamp(1e6)}      <- clamped to max")
    print(f"clamp(10.00047):     {exposure.clamp(10.00047)}       <- snapped to the grid")
    print(f"supports(10.0005):   {exposure.supports(10.0005)}     <- not on the grid")
    print(f"supports(10.001):    {exposure.supports(10.001)}")


def report_broken_file() -> None:
    """7. What a broken file looks like: one message per problem."""
    section("7. error reporting (Devices_broken.yml)")
    for error in validate_registry(read_document("Devices_broken.yml")):
        print(f"  - {error}")


def store_and_reload() -> None:
    """8. Change something, store it in both formats, read it back."""
    section("8. storing")
    registry = load_config("Devices.yml")

    # `devices` is a discriminated union, so narrow before touching camera fields --
    # a type checker then knows exactly which attributes exist.
    camera = next(dev for dev in registry.devices if isinstance(dev, CameraSchema))
    assert camera.exposure_time_ms is not None, "the sample file defines exposure limits"

    # validate_assignment=True, so this is checked against the device's own limits.
    camera.exposure_time_ms.value = 25.0

    out_dir = get_paths().data_dir
    for suffix in (".yml", ".json"):
        target = dump_config(registry, out_dir / f"Devices.modified{suffix}")
        reloaded = load_config(target)
        same = reloaded == registry
        print(f"wrote {target} -> reload matches: {same}")

    single = dump_config(camera, out_dir / "hik_mv_ca023_10um.modified.yaml")
    print(f"wrote {single} -> exposure {load_camera(single).exposure_time_ms.value}")

    # Out-of-range assignments are refused. Note the caveat: Pydantic assigns first
    # and validates after, so the object keeps the rejected value and has to be
    # discarded (or reset) rather than reused -- see tests/test_bounded.py.
    try:
        camera.exposure_time_ms.value = 99_999.0
    except ValueError as exc:
        print(f"refused: {str(exc).splitlines()[1].strip()}")
    print(f"but the model now holds: {camera.exposure_time_ms.value} -> reload before reuse")


def refresh_exported_schemas() -> None:
    """9. Regenerate the JSON Schemas other tools and editors consume."""
    section("9. exported JSON Schemas")
    print(f"wrote {export_camera_schema()}")
    print(f"wrote {export_devices_schema()}")


def main() -> None:
    """Run every step of the example."""
    show_folders()
    load_same_camera_twice()
    load_whole_setup()
    one_call_for_both_layouts()
    limits_of_a_parameter()
    report_broken_file()
    store_and_reload()
    refresh_exported_schemas()


if __name__ == "__main__":
    main()
