"""The frame cache (Zarr stores), served over HTTP for the frontend's viewer (FastAPI mode)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from newswitch.routes import running_context
from newswitch.protocols.cache import CacheManager

router = APIRouter(tags=["Cache"])


def cache_manager_of(request: Request) -> CacheManager:
    """The running agent's CacheManager (503 before it started)."""
    return running_context(request, CacheManager)


@router.get("/cache/{store_id}/{key:path}")
async def serve_zarr_store(
    store_id: str, key: str, cache_manager: CacheManager = Depends(cache_manager_of)
) -> FileResponse:
    """
    Serves Zarr metadata and chunk files.

    Args:
        store_id: The name of the Zarr store folder (e.g., 'frame_001.zarr')
        key: The internal Zarr path requested by Zarrita (e.g., 'zarr.json' or 'c/0/0/0/0')
    """
    # 1. Construct the target file path

    store_dir = cache_manager.get_frame_store_dir(store_id)

    target_path = (store_dir / key).resolve()

    # 2. Security Check: Prevent directory traversal attacks (e.g., passing "../../etc/passwd" as the key)
    try:
        # is_relative_to is available in Python 3.9+
        if not target_path.is_relative_to(store_dir):
            raise HTTPException(status_code=403, detail="Access denied")
    except AttributeError:
        # Fallback for older Python versions
        if store_dir not in target_path.parents:
            raise HTTPException(status_code=403, detail="Access denied")

    # 3. Check if the file (chunk or metadata) actually exists
    if not target_path.exists() or not target_path.is_file():
        # Returning a 404 is strictly required by the Zarr spec for missing chunks.
        # The frontend Zarrita client will catch this and inject the 'fill_value'.
        raise HTTPException(status_code=404, detail="Chunk or metadata not found")

    # 4. Return the file
    # FileResponse automatically handles streaming the bytes and setting content-length
    # For .json files it sets application/json, for chunks it defaults to application/octet-stream
    return FileResponse(path=target_path)
