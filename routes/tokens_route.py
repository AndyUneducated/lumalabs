"""Design token read/update from the viewer panel (no LLM)."""

from __future__ import annotations

import server_state
from builder_config import OUTPUT_FILE
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["tokens"])


class TokenUpdateRequest(BaseModel):
    updates: dict[str, str]


@router.get("/tokens")
async def get_tokens():
    from tokens import list_tokens_from_html

    if not OUTPUT_FILE.is_file():
        return {"tokens": []}
    html = OUTPUT_FILE.read_text()
    return {"tokens": list_tokens_from_html(html)}


@router.post("/tokens")
async def update_tokens(req: TokenUpdateRequest):
    from history import save_output
    from tokens import list_tokens_from_html, parse_root_vars, patch_root_vars

    if not OUTPUT_FILE.is_file():
        return {"tokens": [], "error": "no output yet"}
    html = OUTPUT_FILE.read_text()
    if not parse_root_vars(html):
        return {"tokens": [], "error": "no :root block in output/index.html"}
    patched = patch_root_vars(html, req.updates)
    save_output(patched, "tokens-panel")
    server_state.notify("html_updated")
    return {"tokens": list_tokens_from_html(patched)}
