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

_BROWSER_ERROR_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("timeout", "timed out"), "This page took too long to load. We saved whatever we could from the DOM."),
    (("err_name_not_resolved", "dns"), "We could not reach that URL. Check the address and your network."),
    (("connection refused", "err_connection_refused"), "The server refused the connection. The site may be down."),
    (("err_cert", "ssl", "certificate"), "Secure connection failed. The site certificate may be invalid."),
    (("net::err_", "navigation"), "The browser could not open that page. Try a different URL."),
]


def friendly_capture_error(err: str | Exception | None) -> str:
    """Map Playwright/network failures to plain user-facing copy (no stack traces)."""
    if err is None:
        return "Could not capture this page."
    raw = str(err).strip()
    if not raw:
        return "Could not capture this page."
    lower = raw.lower()
    for needles, message in _BROWSER_ERROR_PATTERNS:
        if any(n in lower for n in needles):
            return message
    if "not found" in lower and "file" in lower:
        return "Output file not found yet. Generate a page first."
    if len(raw) > 200 or "traceback" in lower:
        return "Capture failed. We used a DOM-only fallback when possible."
    return f"Capture issue: {raw[:180]}"


_browser_lock = asyncio.Lock()
_playwright: Playwright | None = None
_browser: Browser | None = None


@dataclass
class CaptureResult:
    """Result of a page capture attempt."""

    paths: list[Path] = field(default_factory=list)
    styles: dict | None = None
    compare_payload: dict | None = None
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


async def _safe_close_page_context(page: Page) -> None:
    """Close the page's browser context; ignore if already closed (hot-reload / shutdown)."""
    try:
        await page.context.close()
    except Exception:
        pass


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
        # full_page=True is required so clip can address rows below the
        # viewport; without it a clip at y>=viewport height (or taller than
        # the viewport) raises "Clipped area is ... outside the resulting image".
        await page.screenshot(
            path=str(out),
            full_page=True,
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
  const card = document.querySelector('section, article, .card, [class*="card"]');
  const cardcs = card ? getComputedStyle(card) : null;

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
      bodyLineHeight: bcs ? bcs.lineHeight : null,
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
      boxShadow: btncs.boxShadow,
      padding: btncs.padding,
      fontSize: btncs.fontSize,
      fontWeight: btncs.fontWeight,
    } : null,
    cardSample: cardcs && card ? {
      tag: card.tagName.toLowerCase(),
      borderRadius: cardcs.borderRadius,
      boxShadow: cardcs.boxShadow,
      padding: cardcs.padding,
      backgroundColor: cardcs.backgroundColor,
    } : null,
    headings: sample('h1, h2, h3'),
    links: sample('a', 8),
  };
}
"""


_EXTRACT_COMPARE_JS = """
() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const vw = window.innerWidth || 1280;
  const scrollH = Math.max(
    document.body ? document.body.scrollHeight : 0,
    document.documentElement ? document.documentElement.scrollHeight : 0,
    window.innerHeight
  );

  const text = [];
  const seen = new Set();
  const textSel = 'h1, h2, h3, h4, p, li, button, a, label, span';
  for (const el of document.querySelectorAll(textSel)) {
    if (text.length >= 80) break;
    const t = norm(el.innerText || el.textContent || '');
    if (t.length < 3 || seen.has(t)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 && rect.height < 2) continue;
    seen.add(t);
    text.push(t);
  }

  const skeletonTags = new Set([
    'header', 'nav', 'main', 'section', 'footer',
    'h1', 'h2', 'h3', 'button', 'a', 'img',
  ]);
  const skeleton = [];
  const walk = (root) => {
    const iter = document.createNodeIterator(root, NodeFilter.SHOW_ELEMENT);
    let node;
    while ((node = iter.nextNode()) && skeleton.length < 120) {
      const tag = node.tagName.toLowerCase();
      if (skeletonTags.has(tag) || node.hasAttribute('data-section')) {
        skeleton.push(tag === 'img' ? 'img' : tag);
      }
    }
  };
  walk(document.body || document.documentElement);

  const sections = [];
  for (const el of document.querySelectorAll(
    'header, nav, main, section, footer, [data-section]'
  )) {
    if (sections.length >= 24) break;
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    const absY = rect.top + window.scrollY;
    sections.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      box: {
        x: rect.left / vw,
        y: absY / scrollH,
        w: rect.width / vw,
        h: rect.height / scrollH,
      },
    });
  }

  return {
    text,
    skeleton,
    sections,
    viewport: { width: vw, scrollHeight: scrollH },
  };
}
"""


async def _extract_styles(page: Page) -> dict:
    return await page.evaluate(_EXTRACT_STYLES_JS)


async def _extract_compare(page: Page) -> dict:
    return await page.evaluate(_EXTRACT_COMPARE_JS)


async def _navigate(page: Page, url: str) -> None:
    # Heavy-JS sites often never reach "networkidle" due to long-polling.
    await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    await asyncio.sleep(0.8)


async def _capture_loaded_page(page: Page, source: str) -> CaptureResult:
    styles = await _extract_styles(page)
    paths = await _tile_screenshot(page, source)
    return CaptureResult(paths=paths, styles=styles, source=source)


async def _capture_loaded_page_compare(page: Page, source: str) -> CaptureResult:
    styles = await _extract_styles(page)
    compare_payload = await _extract_compare(page)
    paths = await _tile_screenshot(page, source)
    return CaptureResult(
        paths=paths,
        styles=styles,
        compare_payload=compare_payload,
        source=source,
    )


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
                    error=friendly_capture_error(e),
                    source=url,
                )
            except Exception as inner:
                return CaptureResult(
                    paths=[],
                    styles=None,
                    dom_only=True,
                    error=friendly_capture_error(f"{e}; fallback failed: {inner}"),
                    source=url,
                )
        finally:
            await _safe_close_page_context(page)


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
            await _navigate(page, file_url)
            return await _capture_loaded_page(page, file_url)
        except Exception as e:
            return CaptureResult(
                paths=[],
                dom_only=True,
                error=friendly_capture_error(e),
                source=file_url,
            )
        finally:
            await _safe_close_page_context(page)


async def capture_compare(source: str, *, is_file: bool = False) -> CaptureResult:
    """Capture page for fidelity compare: tiles, styles, and compare payload."""
    if is_file:
        resolved = Path(source).resolve()
        if not resolved.is_file():
            return CaptureResult(
                paths=[],
                dom_only=True,
                error=f"File not found: {resolved}",
                source=str(resolved),
            )
        target = resolved.as_uri()
    else:
        target = source
        if not target.startswith(("http://", "https://")):
            target = "https://" + target.lstrip("/")

    async with _browser_lock:
        page = await _new_page()
        try:
            await _navigate(page, target)
            return await _capture_loaded_page_compare(page, target)
        except Exception as e:
            try:
                styles = await _extract_styles(page)
                compare_payload = await _extract_compare(page)
                outline = await page.evaluate(
                    "() => document.body ? document.body.innerText.slice(0, 4000) : ''"
                )
                if compare_payload is not None:
                    compare_payload = {**compare_payload, "textOutline": outline}
                return CaptureResult(
                    paths=[],
                    styles={**(styles or {}), "textOutline": outline},
                    compare_payload=compare_payload,
                    dom_only=True,
                    error=friendly_capture_error(e),
                    source=target,
                )
            except Exception as inner:
                return CaptureResult(
                    paths=[],
                    styles=None,
                    compare_payload=None,
                    dom_only=True,
                    error=friendly_capture_error(f"{e}; fallback failed: {inner}"),
                    source=target,
                )
        finally:
            await _safe_close_page_context(page)
