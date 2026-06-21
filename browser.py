"""Playwright browser helpers for Phase 1 visual loop.

Reuses one Chromium instance. Screenshots are tiled vertically so each PNG
stays sharp and within vision model size limits.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, Page, Playwright, async_playwright

VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900
TILE_HEIGHT = 1400
MAX_TILES = 4
NAV_TIMEOUT_MS = 30_000
SHOTS_DIR = Path("output") / ".shots"

_browser_lock = asyncio.Lock()
_playwright: Playwright | None = None
_browser: Browser | None = None


@dataclass
class CaptureResult:
    """Result of a page capture attempt."""

    paths: list[Path] = field(default_factory=list)
    styles: dict | None = None
    dom_only: bool = False
    error: str | None = None
    source: str = ""


async def _ensure_browser() -> Browser:
    global _playwright, _browser
    if _browser is not None:
        return _browser
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True)
    return _browser


async def close_browser() -> None:
    """Shut down Playwright (call from server lifespan shutdown)."""
    global _playwright, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None


def _slug_from_url(url: str) -> str:
    host = urlparse(url).netloc or "local"
    return re.sub(r"[^a-zA-Z0-9.-]+", "-", host).strip("-") or "page"


def _shot_prefix(source: str) -> tuple[Path, str]:
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slug_from_url(source)
    return SHOTS_DIR, f"{slug}-{ts}"


async def _new_page() -> Page:
    browser = await _ensure_browser()
    context = await browser.new_context(
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        device_scale_factor=1,
    )
    return await context.new_page()


async def _tile_screenshot(page: Page, prefix: str) -> list[Path]:
    """Capture the page in vertical tiles using clip."""
    _, base = _shot_prefix(prefix)
    page_height = await page.evaluate(
        "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
    )
    page_height = max(int(page_height), VIEWPORT_HEIGHT)

    tiles_needed = min(MAX_TILES, max(1, (page_height + TILE_HEIGHT - 1) // TILE_HEIGHT))
    paths: list[Path] = []

    for i in range(tiles_needed):
        y = i * TILE_HEIGHT
        height = min(TILE_HEIGHT, page_height - y)
        if height <= 0:
            break
        out = SHOTS_DIR / f"{base}-{i + 1}.png"
        await page.screenshot(
            path=str(out),
            clip={"x": 0, "y": y, "width": VIEWPORT_WIDTH, "height": height},
            type="png",
        )
        paths.append(out)

    return paths


_EXTRACT_STYLES_JS = """
() => {
  const colorCount = {};
  const bump = (c) => {
    if (!c || c === 'transparent' || c === 'rgba(0, 0, 0, 0)') return;
    colorCount[c] = (colorCount[c] || 0) + 1;
  };
  const topColors = (n = 8) =>
    Object.entries(colorCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, n)
      .map(([color, count]) => ({ color, count }));

  const sample = (sel, limit = 12) => {
    const out = [];
    for (const el of document.querySelectorAll(sel)) {
      if (out.length >= limit) break;
      const cs = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) continue;
      bump(cs.backgroundColor);
      bump(cs.color);
      out.push({
        tag: el.tagName.toLowerCase(),
        text: (el.innerText || '').trim().slice(0, 80),
        color: cs.color,
        backgroundColor: cs.backgroundColor,
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
        borderRadius: cs.borderRadius,
        padding: cs.padding,
      });
    }
    return out;
  };

  const h1 = document.querySelector('h1');
  const body = document.body;
  const h1cs = h1 ? getComputedStyle(h1) : null;
  const bcs = body ? getComputedStyle(body) : null;
  const btn = document.querySelector('a, button, [role="button"]');
  const btncs = btn ? getComputedStyle(btn) : null;

  const sections = [];
  for (const el of document.querySelectorAll('section, header, footer, main, nav, [data-section]')) {
    if (sections.length >= 20) break;
    const cs = getComputedStyle(el);
    sections.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      className: (el.className && String(el.className).slice(0, 120)) || null,
      backgroundColor: cs.backgroundColor,
    });
  }

  return {
    title: document.title,
    sectionCount: sections.length,
    sections,
    palette: topColors(10),
    typography: {
      bodyFontFamily: bcs ? bcs.fontFamily : null,
      bodyFontSize: bcs ? bcs.fontSize : null,
      bodyColor: bcs ? bcs.color : null,
      bodyBackground: bcs ? bcs.backgroundColor : null,
      h1FontFamily: h1cs ? h1cs.fontFamily : null,
      h1FontSize: h1cs ? h1cs.fontSize : null,
      h1FontWeight: h1cs ? h1cs.fontWeight : null,
      h1Color: h1cs ? h1cs.color : null,
    },
    buttonSample: btncs && btn ? {
      tag: btn.tagName.toLowerCase(),
      text: (btn.innerText || '').trim().slice(0, 60),
      color: btncs.color,
      backgroundColor: btncs.backgroundColor,
      borderRadius: btncs.borderRadius,
      fontSize: btncs.fontSize,
      fontWeight: btncs.fontWeight,
    } : null,
    headings: sample('h1, h2, h3'),
    links: sample('a', 8),
  };
}
"""


async def _extract_styles(page: Page) -> dict:
    return await page.evaluate(_EXTRACT_STYLES_JS)


async def _navigate(page: Page, url: str) -> None:
    await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)


async def _capture_loaded_page(page: Page, source: str) -> CaptureResult:
    styles = await _extract_styles(page)
    paths = await _tile_screenshot(page, source)
    return CaptureResult(paths=paths, styles=styles, source=source)


async def capture_url(url: str) -> CaptureResult:
    """Screenshot a remote URL with tiled PNGs and style extraction."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")

    async with _browser_lock:
        page = await _new_page()
        try:
            await _navigate(page, url)
            return await _capture_loaded_page(page, url)
        except Exception as e:
            try:
                styles = await _extract_styles(page)
                outline = await page.evaluate(
                    "() => document.body ? document.body.innerText.slice(0, 4000) : ''"
                )
                return CaptureResult(
                    paths=[],
                    styles={**(styles or {}), "textOutline": outline},
                    dom_only=True,
                    error=str(e),
                    source=url,
                )
            except Exception as inner:
                return CaptureResult(
                    paths=[],
                    styles=None,
                    dom_only=True,
                    error=f"{e}; fallback failed: {inner}",
                    source=url,
                )
        finally:
            await page.context.close()


async def capture_file(file_path: Path) -> CaptureResult:
    """Screenshot a local HTML file (e.g. output/index.html)."""
    resolved = file_path.resolve()
    if not resolved.is_file():
        return CaptureResult(
            paths=[],
            dom_only=True,
            error=f"File not found: {resolved}",
            source=str(resolved),
        )

    file_url = resolved.as_uri()
    async with _browser_lock:
        page = await _new_page()
        try:
            await page.goto(file_url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
            return await _capture_loaded_page(page, file_url)
        except Exception as e:
            return CaptureResult(
                paths=[],
                dom_only=True,
                error=str(e),
                source=file_url,
            )
        finally:
            await page.context.close()
