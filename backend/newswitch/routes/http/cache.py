"""
HTTP routes for cache serving,
this should only be done if we
cant serve it directly via nginx
or another static file server.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from newswitch.protocols.cache import CacheManager
from newswitch.routes.contexts import context_of_type


router = APIRouter(tags=["Cache"])


def get_cache_manager(request: Request) -> CacheManager:
    """
    Dependency to get the CacheManager from the FastAPI app state.

    The agent is set on app.state during configure_fastapi and provides
    access to context managers.
    """
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=500, detail="Agent not available")

    cache_manager = context_of_type(agent, CacheManager)
    if cache_manager is None:
        raise HTTPException(status_code=500, detail="Cache manager not available")

    return cache_manager


@router.get("/cache/{store_id}/{key:path}")
async def serve_zarr_store(
    store_id: str, key: str, cache_manager: CacheManager = Depends(get_cache_manager)
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
