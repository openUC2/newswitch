"""
HTTP routes for file serving.
"""

import os
import mimetypes
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from newswitch.protocols.io import FileHandle, IOManager
from newswitch.routes.contexts import context_of_type


router = APIRouter(tags=["Files"])


def get_io_manager(request: Request) -> IOManager:
    """
    Dependency to get the IOManager from the FastAPI app state.

    The agent is set on app.state during configure_fastapi and provides
    access to context managers.
    """
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=500, detail="Agent not available")

    io_manager = context_of_type(agent, IOManager)
    if io_manager is None:
        raise HTTPException(status_code=500, detail="IO manager not available")

    return io_manager


@router.get("/files/{file_path:path}")
async def serve_file(
    file_path: str,
    io_manager: IOManager = Depends(get_io_manager),
) -> FileResponse:
    """
    Serve a file from the IO manager's storage.

    The file_path should be the path returned by a FileHandle.

    Args:
        file_path: Path to the file to serve.
        io_manager: IOManager injected via dependency.

    Returns:
        FileResponse with the file contents.
    """
    handle = FileHandle(file_path=file_path)

    if not io_manager.file_exists(handle.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    actual_path = handle.file_path
    media_type = _get_media_type(actual_path)

    return FileResponse(
        actual_path,
        media_type=media_type,
        filename=os.path.basename(actual_path),
    )


@router.get("/files/download/{file_path:path}")
async def download_file(
    file_path: str,
    io_manager: IOManager = Depends(get_io_manager),
) -> FileResponse:
    """
    Download a file (forces download instead of display).

    Args:
        file_path: Path to the file to download.
        io_manager: IOManager injected via dependency.

    Returns:
        FileResponse with content-disposition attachment header.
    """
    handle = FileHandle(file_path=file_path)

    if not io_manager.file_exists(handle.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    actual_path = handle.file_path
    media_type = _get_media_type(actual_path)
    filename = os.path.basename(actual_path)

    return FileResponse(
        actual_path,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _get_media_type(file_path: str) -> str:
    """Determine media type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()

    media_types = {
        ".npy": "application/octet-stream",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }

    return media_types.get(ext, mimetypes.guess_type(file_path)[0] or "application/octet-stream")
