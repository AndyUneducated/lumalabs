"""MCP tool responses: image compression and capture-style content blocks."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from browser import CaptureResult, friendly_capture_error

_MCP_IMAGE_BUDGET_BYTES = 600_000
_MCP_IMAGE_MAX_WIDTH = 960


def normalize_tool_result(result: Any) -> dict:
    if isinstance(result, dict) and "content" in result:
        return result
    if isinstance(result, list):
        return {"content": result}
    return {"content": [{"type": "text", "text": str(result)}]}


def encode_image_for_mcp(path: Path, *, max_width: int = _MCP_IMAGE_MAX_WIDTH) -> tuple[str, str]:
    with Image.open(path) as img:
        img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize(
                (max_width, max(1, int(img.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        quality = 82
        while quality >= 45:
            buf.seek(0)
            buf.truncate(0)
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            if buf.tell() <= 140_000:
                break
            quality -= 12
            if quality < 45 and img.width > 480:
                img = img.resize(
                    (max(480, img.width // 2), max(1, img.height // 2)),
                    Image.Resampling.LANCZOS,
                )
                quality = 82
        data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        return data, "image/jpeg"


def paths_to_image_blocks(paths: list[Path]) -> list[dict]:
    blocks: list[dict] = []
    budget = _MCP_IMAGE_BUDGET_BYTES
    omitted: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            data, mime = encode_image_for_mcp(path)
        except OSError:
            omitted.append(str(path))
            continue
        if len(data) > budget:
            omitted.append(str(path))
            continue
        blocks.append({"type": "image", "data": data, "mimeType": mime})
        budget -= len(data)
    if omitted:
        blocks.append(
            {
                "type": "text",
                "text": (
                    "Additional full-resolution tiles saved on disk (not embedded): "
                    + ", ".join(omitted)
                ),
            }
        )
    return blocks


def capture_to_content(result: CaptureResult, label: str) -> dict:
    content: list[dict] = []

    if result.dom_only:
        content.append(
            {
                "type": "text",
                "text": (
                    f"{label} — DOM-only fallback (screenshot failed).\n"
                    f"Error: {friendly_capture_error(result.error)}\n"
                    "Use the style JSON and text outline below. Do not guess colors from memory."
                ),
            }
        )
    elif result.paths:
        paths_str = ", ".join(str(p) for p in result.paths)
        content.append(
            {
                "type": "text",
                "text": (
                    f"{label} — {len(result.paths)} screenshot tile(s), top to bottom.\n"
                    f"Saved to: {paths_str}"
                ),
            }
        )
    else:
        content.append({"type": "text", "text": f"{label} — no screenshots captured."})

    if result.styles is not None:
        content.append(
            {
                "type": "text",
                "text": "Extracted styles (JSON):\n" + json.dumps(result.styles, indent=2),
            }
        )

    content.extend(paths_to_image_blocks(result.paths))
    return {"content": content}
