"""Guards against drift between the models and the files that ship next to them.

Two kinds of drift are possible once schemas are exported to disk:

1. `Configs/schemas/*.json` no longer matches the model it was generated from —
   editors and non-Python consumers then validate against a stale contract.
2. A sample config in `Configs/` no longer loads — the documentation would be
   describing something that does not work.

Both checks read the development-only `Configs/` folder (see `Configs/__note__.md`),
so every test here skips when that folder is gone. Regenerate with
``uv run python example_schemas.py`` or `export_camera_schema()` /
`export_devices_schema()`.
"""

import json
from pathlib import Path

import pytest

from newswitch.config import Paths
from newswitch.schemas import CameraSchema, DeviceRegistry, load_config, load_device

DRAFT = "https://json-schema.org/draft/2020-12/schema"

CONFIG_DIR = Paths().config_dir
SCHEMA_DIR = Paths().schema_dir

pytestmark = pytest.mark.skipif(
    not CONFIG_DIR.is_dir(), reason=f"development config folder {CONFIG_DIR} is not present"
)


def _requires(path: Path) -> Path:
    """Skip the test when a sample file is not part of this checkout.

    Args:
        path: The file the test needs.

    Returns:
        The same path, when it exists.
    """
    if not path.is_file():
        pytest.skip(f"{path.name} is not present")
    return path


@pytest.mark.parametrize(
    ("model", "file_name"),
    [(CameraSchema, "camera.schema.json"), (DeviceRegistry, "devices.schema.json")],
)
def test_exported_schema_matches_the_model(model: type, file_name: str) -> None:
    """The checked-in JSON Schema is exactly what the model generates today.

    Args:
        model: The Pydantic model the schema was exported from.
        file_name: Name of the exported schema in the schema directory.
    """
    on_disk = json.loads(_requires(SCHEMA_DIR / file_name).read_text(encoding="utf-8"))

    expected = model.model_json_schema()
    expected["$schema"] = DRAFT

    assert on_disk == expected, (
        f"{file_name} is stale; regenerate it with uv run python example_schemas.py"
    )


def test_sample_registry_still_loads() -> None:
    """`Devices.yml` is the file the README walks through — it has to work."""
    registry = load_config(_requires(CONFIG_DIR / "Devices.yml"))

    assert registry.setup == "openUC2-bench-01"
    assert len(registry.by_type("camera")) == 2
    assert registry.get("laser-488-001").name == "LD-488-100"


@pytest.mark.parametrize("file_name", ["hik_mv_ca023_10um.yaml", "hik_mv_ca023_10um.json"])
def test_sample_camera_still_loads(file_name: str) -> None:
    """The single-device sample loads in both formats, with `type` omitted.

    Args:
        file_name: The sample file under test.
    """
    camera = load_device(_requires(CONFIG_DIR / file_name), expect="camera")

    assert camera.name == "MV-CA023-10UM"
    assert camera.pixelpitch_um.y == 10.0  # derived from x
    assert camera.sensor_size_mm == pytest.approx((19.2, 12.0))


def test_broken_sample_is_still_broken() -> None:
    """`Devices_broken.yml` exists to demonstrate the error output."""
    from newswitch.schemas import ConfigError

    with pytest.raises(ConfigError, match="failed validation"):
        load_config(_requires(CONFIG_DIR / "Devices_broken.yml"))
