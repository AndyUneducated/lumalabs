"""HTML section anchors and partial edits (Phase 4)."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag


def _preview_text(el: Tag, limit: int = 60) -> str:
    text = el.get_text(" ", strip=True)
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def list_sections(html: str) -> list[dict[str, Any]]:
    """List all elements with data-section anchors."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for el in soup.find_all(attrs={"data-section": True}):
        name = el.get("data-section")
        if not name:
            continue
        rows.append(
            {
                "selector": str(name),
                "tag": el.name,
                "preview": _preview_text(el),
            }
        )
    return rows


def _find_element(soup: BeautifulSoup, selector: str) -> Tag | None:
    sel = selector.strip()
    if not sel:
        return None

    if sel.startswith("[") or sel.startswith(".") or " " in sel:
        return soup.select_one(sel)

    if sel.startswith("#"):
        return soup.select_one(sel)

    by_ds = soup.select_one(f'[data-section="{sel}"]')
    if by_ds:
        return by_ds

    by_id = soup.select_one(f"#{sel}")
    if by_id:
        return by_id

    return soup.find(sel)


def _fragment_nodes(new_html: str) -> list:
    frag = BeautifulSoup(new_html, "html.parser")
    if frag.body:
        return [c for c in frag.body.children if not isinstance(c, NavigableString) or str(c).strip()]
    return [c for c in frag.children if not isinstance(c, NavigableString) or str(c).strip()]


def replace_section(html: str, selector: str, new_html: str) -> tuple[str, bool]:
    """Replace the first element matching selector with new_html fragment.

    Resolution order: explicit CSS selector → data-section → #id → tag name.
    """
    soup = BeautifulSoup(html, "html.parser")
    el = _find_element(soup, selector)
    if el is None:
        return html, False

    nodes = _fragment_nodes(new_html)
    if not nodes:
        el.decompose()
    elif len(nodes) == 1:
        el.replace_with(nodes[0])
    else:
        el.replace_with(*nodes)

    return str(soup), True


def section_exists(html: str, selector: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return _find_element(soup, selector) is not None
