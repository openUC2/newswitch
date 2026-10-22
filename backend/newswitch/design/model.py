"""The design's 3D model, as the asset its scene blok shows.

``optikit.build`` evaluates the design into one GLB with a joint per input. CAD meshes
are far too heavy for a viewer (the fluorescence design is 34 MB), so the asset is cut down
with ``optikit.simplify``. That takes seconds, so the result is kept: under
``newswitch/assets/design/`` (the app's root, where assets must live), named after the
built model's hash, and reused while the design does not change.
"""

import hashlib
import logging
from pathlib import Path

from newswitch.optikit import dsn as optikit

logger = logging.getLogger(__name__)

#: Where built models are kept: inside the app's root (``newswitch/``), as assets must be.
MODEL_DIR = Path(__file__).parent.parent / "assets" / "design"

#: The share of the CAD triangles the asset keeps (34 MB -> 0.6 MB for the fluorescence design).
KEEP = 0.05

#: Bumped when `colorize` changes, so models built with the old colours are rebuilt.
COLOURS_VERSION = "1"

#: What a part is made of, by what its node is named after: (name fragment, material).
#: CAD parts carry no materials; these are the openUC2 ones. The first match wins.
_GLASS = {"baseColorFactor": [0.78, 0.9, 1.0, 0.35], "metallicFactor": 0.0, "roughnessFactor": 0.05}
_ALUMINIUM = {
    "baseColorFactor": [0.74, 0.76, 0.79, 1.0],
    "metallicFactor": 0.85,
    "roughnessFactor": 0.35,
}
_PRINTED = {
    "baseColorFactor": [0.16, 0.17, 0.19, 1.0],
    "metallicFactor": 0.0,
    "roughnessFactor": 0.7,
}
MATERIALS: list[tuple[str, str, dict]] = [
    (
        "dichroic_filter",
        "dichroic",
        {"baseColorFactor": [1.0, 0.62, 0.2, 0.5], "metallicFactor": 0.0, "roughnessFactor": 0.1},
    ),
    (
        "emission_filter",
        "emission filter",
        {"baseColorFactor": [0.3, 0.95, 0.45, 0.5], "metallicFactor": 0.0, "roughnessFactor": 0.1},
    ),
    ("__lens__", "glass", _GLASS),
    (
        "__mirror__part",
        "mirror",
        {
            "baseColorFactor": [0.93, 0.95, 0.97, 1.0],
            "metallicFactor": 1.0,
            "roughnessFactor": 0.06,
        },
    ),
    (
        "adhesive_pad",
        "rubber",
        {"baseColorFactor": [0.08, 0.08, 0.08, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9},
    ),
    ("motor_holder", "printed", _PRINTED),
    (
        "__motor__",
        "motor",
        {"baseColorFactor": [0.2, 0.2, 0.22, 1.0], "metallicFactor": 0.6, "roughnessFactor": 0.4},
    ),
    (
        "blue_laser__laser__",
        "laser",
        {"baseColorFactor": [0.12, 0.3, 0.8, 1.0], "metallicFactor": 0.5, "roughnessFactor": 0.3},
    ),
    (
        "camera__camera__camera",
        "camera",
        {"baseColorFactor": [0.07, 0.07, 0.09, 1.0], "metallicFactor": 0.3, "roughnessFactor": 0.5},
    ),
    ("plate", "aluminium", _ALUMINIUM),
    ("rail", "aluminium", _ALUMINIUM),
    ("bracket", "aluminium", _ALUMINIUM),
    ("rotator", "aluminium", _ALUMINIUM),
    ("threaded_holder", "aluminium", _ALUMINIUM),
    ("__nut__", "aluminium", _ALUMINIUM),
    (
        "electronics_controller",
        "case",
        {"baseColorFactor": [0.9, 0.9, 0.92, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.6},
    ),
    ("", "printed", _PRINTED),
]


def colorize(glb: bytes) -> bytes:
    """The model with a material per part, by what its node is named after."""
    doc, binary = optikit._read_glb(glb, "the design's model")
    materials: list[dict] = []
    index: dict[str, int] = {}
    for node in doc.get("nodes", []):
        if "mesh" not in node:
            continue
        name = node.get("name", "")
        _, label, pbr = next(rule for rule in MATERIALS if rule[0] in name)
        if label not in index:
            index[label] = len(materials)
            material: dict = {"name": label, "pbrMetallicRoughness": pbr, "doubleSided": True}
            if pbr["baseColorFactor"][3] < 1.0:
                material["alphaMode"] = "BLEND"
            materials.append(material)
        for primitive in doc["meshes"][node["mesh"]]["primitives"]:
            primitive["material"] = index[label]
    doc["materials"] = materials
    return optikit._encode_glb(doc, bytearray(binary))


def build_model(dsn: str | Path) -> tuple[Path, optikit.Model]:
    """Build the design's model and write its (simplified) GLB, or reuse the one written.

    Returns:
        The GLB's path (inside the app's root) and the model: its joints and component
        nodes, which the scene blok binds.
    """
    model = optikit.build(Path(dsn))
    digest = hashlib.sha256(model.glb).hexdigest()[:16]
    path = MODEL_DIR / f"{digest}-c{COLOURS_VERSION}.glb"
    if not path.exists():
        try:
            import pyvista  # noqa: F401  (simplify needs it)
        except ImportError as exc:
            raise RuntimeError(
                "Showing a design's model needs the extra 'design' (pyvista): "
                "uv sync --extra design"
            ) from exc
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Simplifying the design's model (%d bytes) into %s", len(model.glb), path)
        path.write_bytes(colorize(optikit.simplify(model.glb, keep=KEEP)))
    return path, model
