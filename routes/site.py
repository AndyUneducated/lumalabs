"""Viewer HTML, live preview, static assets, and screenshot tiles."""

from __future__ import annotations

from pathlib import Path

from builder_config import OUTPUT_DIR, OUTPUT_FILE, SHOTS_DIR
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["site"])


@router.get("/", response_class=HTMLResponse)
async def viewer():
    return FileResponse("viewer.html", headers={"Cache-Control": "no-store"})


@router.get("/preview", response_class=HTMLResponse)
async def preview():
    if OUTPUT_FILE.exists():
        return FileResponse(OUTPUT_FILE, headers={"Cache-Control": "no-store"})
    return HTMLResponse("<html><body></body></html>")


@router.get("/assets/{asset_path:path}")
async def serve_asset(asset_path: str):
    base = OUTPUT_DIR / "assets"
    if asset_path.startswith("assets/"):
        asset_path = asset_path[len("assets/"):]
    file_path = (base / asset_path).resolve()
    if not str(file_path).startswith(str(base.resolve())):
        return HTMLResponse("Forbidden", status_code=403)
    if file_path.is_file():
        return FileResponse(file_path, headers={"Cache-Control": "no-store"})
    return HTMLResponse("Not found", status_code=404)


@router.get("/source")
async def get_source():
    if not OUTPUT_FILE.is_file():
        return {"html": ""}
    return {"html": OUTPUT_FILE.read_text()}


@router.get("/shots/{shot_path:path}")
async def serve_shot(shot_path: str):
    base = SHOTS_DIR.resolve()
    file_path = (SHOTS_DIR / shot_path).resolve()
    if not str(file_path).startswith(str(base)):
        return HTMLResponse("Forbidden", status_code=403)
    if file_path.is_file():
        return FileResponse(file_path, headers={"Cache-Control": "no-store"})
    return HTMLResponse("Not found", status_code=404)
