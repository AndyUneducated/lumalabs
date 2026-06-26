"""Job handlers executed by the capture worker pool."""

from __future__ import annotations

from browser import capture_url


async def handle_capture(payload: dict) -> dict:
    url = payload.get("url", "")
    result = await capture_url(url)
    return {
        "source": result.source,
        "dom_only": result.dom_only,
        "error": result.error,
        "shot_count": len(result.paths),
        "shots": [p.name for p in result.paths],
        "has_styles": result.styles is not None,
    }
