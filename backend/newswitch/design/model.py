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


def build_model(dsn: str | Path) -> tuple[Path, optikit.Model]:
    """Build the design's model and write its (simplified) GLB, or reuse the one written.

    Returns:
        The GLB's path (inside the app's root) and the model: its joints and component
        nodes, which the scene blok binds.
    """
    model = optikit.build(Path(dsn))
    digest = hashlib.sha256(model.glb).hexdigest()[:16]
    path = MODEL_DIR / f"{digest}.glb"
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
        path.write_bytes(optikit.simplify(model.glb, keep=KEEP))
    return path, model
