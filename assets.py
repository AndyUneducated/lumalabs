"""Download and mirror page assets for faithful reproduction (Phase 2.5)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page

from browser import NAV_TIMEOUT_MS, _browser_lock, _navigate, _new_page, _slug_from_url

ASSETS_DIR = Path("output") / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
MANIFEST_PATH = ASSETS_DIR / "manifest.json"
MAX_URL_ASSETS = 110
MAX_INLINE_SVGS = 14
MAX_FONTS = 10

_EXTRACT_ASSETS_JS = """
() => {
  const abs = (u) => {
    try { return new URL(u, location.href).href; } catch { return null; }
  };
  const seen = new Set();
  const urls = [];
  const addUrl = (raw, role, meta = {}) => {
    const u = abs(raw);
    if (!u || u.startsWith('data:') || seen.has(u)) return;
    seen.add(u);
    urls.push({ url: u, role, ...meta });
  };

  const logoHint = (s) => /\\b(logo|logotype|brand-?mark|site-?logo|header-?logo)\\b/i.test(s)
    || /\\/[^/]*logo[^/]*\\.[a-z0-9]+$/i.test(s);

  const roleFromBlob = (blob, rect) => {
    if (logoHint(blob)) return 'logo';
    if (rect.top < 600 && rect.width >= 48 && rect.height >= 24) return 'hero';
    return 'image';
  };

  const icon = document.querySelector('link[rel~="icon"], link[rel="shortcut icon"]');
  if (icon && icon.href) addUrl(icon.href, 'favicon', { hint: 'favicon' });

  for (const l of document.querySelectorAll('link[rel~="apple-touch-icon"]')) {
    if (l.href) addUrl(l.href, 'favicon', { hint: 'apple-touch-icon' });
  }
  for (const m of document.querySelectorAll('meta[property="og:image"], meta[name="og:image"]')) {
    const c = m.getAttribute('content');
    if (c) addUrl(c, 'hero', { hint: 'og-image' });
  }

  for (const link of document.querySelectorAll('link[rel="preload"][as="font"]')) {
    if (link.href) addUrl(link.href, 'font', { family: null });
  }

  let imgCount = 0;
  for (const img of document.querySelectorAll('img')) {
    if (imgCount++ > 120) break;
    const rect = img.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    const id = (img.id || '').toLowerCase();
    const cls = String(img.className || '').toLowerCase();
    const alt = (img.alt || '').toLowerCase();
    const srcAttr = (img.getAttribute('src') || '').toLowerCase();
    let urlPath = '';
    const primary = img.currentSrc || img.src
      || img.getAttribute('data-src')
      || img.getAttribute('data-original')
      || img.getAttribute('data-lazy-src')
      || '';
    try { urlPath = new URL(primary, location.href).pathname.toLowerCase(); } catch (_) {}
    const blob = [id, cls, alt, srcAttr, urlPath].join(' ');
    const role = roleFromBlob(blob, rect);
    const meta = { alt: img.alt || null, w: rect.width, h: rect.height, top: rect.top };
    if (primary) addUrl(primary, role, meta);
    const srcset = img.getAttribute('srcset');
    if (srcset) {
      for (const part of srcset.split(',')) {
        const u = part.trim().split(/\\s+/)[0];
        if (u) addUrl(u, role, meta);
      }
    }
  }

  for (const src of document.querySelectorAll('picture > source')) {
    const sset = src.getAttribute('srcset');
    const single = src.getAttribute('src');
    const raw = (sset || single || '').split(',')[0].trim().split(/\\s+/)[0];
    if (raw) addUrl(raw, 'image', { w: 0, h: 0, top: 0, hint: 'picture-source' });
  }
  for (const v of document.querySelectorAll('video[poster]')) {
    const p = v.getAttribute('poster');
    if (p) addUrl(p, 'hero', { hint: 'video-poster', w: 0, h: 0, top: 0 });
  }

  let bgCount = 0;
  for (const el of document.querySelectorAll('*')) {
    if (bgCount++ > 420) break;
    const rect = el.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) continue;
    const cs = getComputedStyle(el);
    const bg = cs.backgroundImage;
    if (!bg || bg === 'none') continue;
    const matches = bg.match(/url\\(["']?([^"')]+)/g) || [];
    for (const m of matches) {
      const inner = m.match(/url\\(["']?([^"')]+)/);
      if (!inner) continue;
      let urlPath = '';
      try { urlPath = new URL(inner[1], location.href).pathname.toLowerCase(); } catch (_) {}
      const blob = (el.id || '') + String(el.className || '') + urlPath;
      const role = logoHint(blob) ? 'logo' : (rect.top < 600 && rect.width >= 80 ? 'hero' : 'background');
      addUrl(inner[1], role, { w: rect.width, h: rect.height, top: rect.top });
    }
  }

  const inlineSvgs = [];
  let svgCount = 0;
  for (const svg of document.querySelectorAll('svg')) {
    if (svgCount++ > 28) break;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) continue;
    let role = 'icon';
    if (rect.top < 250 && rect.width < 320) role = 'logo';
    else if (rect.top < 600 && rect.width >= 80) role = 'hero';
    try {
      const xml = new XMLSerializer().serializeToString(svg);
      if (xml && xml.length > 40) {
        inlineSvgs.push({ xml, role, w: rect.width, h: rect.height, top: rect.top });
      }
    } catch (_) {}
  }

  const fontUrls = [];
  const fontSeen = new Set();
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (_) { continue; }
    if (!rules) continue;
    for (const rule of rules) {
      if (rule.type !== CSSRule.FONT_FACE_RULE) continue;
      const family = (rule.style.getPropertyValue('font-family') || '')
        .replace(/['"]/g, '').split(',')[0].trim();
      const src = rule.style.getPropertyValue('src') || '';
      const urlMatch = src.match(/url\\(["']?([^"')]+)/);
      if (!urlMatch) continue;
      const u = abs(urlMatch[1]);
      if (!u || fontSeen.has(u)) continue;
      fontSeen.add(u);
      fontUrls.push({ url: u, family: family || null });
    }
  }

  return { urls, inlineSvgs, fontUrls };
}
"""


@dataclass
class AssetExtractResult:
    manifest: dict
    manifest_path: Path
    downloaded: int = 0
    error: str | None = None
    source: str = ""


def _ext_from_url(url: str, content_type: str | None) -> str:
    path = urlparse(url).path.lower()
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff2", ".woff", ".ttf", ".otf"):
        if path.endswith(ext):
            return ext.lstrip(".")
    if content_type:
        ct = content_type.lower()
        if "woff2" in ct:
            return "woff2"
        if "woff" in ct:
            return "woff"
        if "ttf" in ct or "truetype" in ct:
            return "ttf"
        if "otf" in ct or "opentype" in ct:
            return "otf"
        if "png" in ct:
            return "png"
        if "jpeg" in ct or "jpg" in ct:
            return "jpg"
        if "svg" in ct:
            return "svg"
        if "webp" in ct:
            return "webp"
        if "icon" in ct or "ico" in ct:
            return "ico"
    return "png"


def _url_suggests_logo(url: str) -> bool:
    path = urlparse(url).path.lower()
    return bool(re.search(r"logo|brand|mark", path))


def _entry(local_rel: str, **extra) -> dict:
    """Build manifest entry with preview_path under /assets/.

    local_rel is relative to output/ (e.g. "assets/foo.png" or
    "assets/fonts/x.woff2"). The /assets/{path} route maps straight to
    output/assets/, so the URL is just "/" + local_rel — prepending another
    "assets/" segment would produce a 404 (/assets/assets/...).
    """
    local = local_rel.replace("\\", "/")
    preview = "/" + local
    return {
        "local": local,
        "preview_path": preview,
        **extra,
    }


async def _download_asset(page: Page, url: str, dest: Path) -> bool:
    try:
        resp = await page.request.get(url, timeout=NAV_TIMEOUT_MS)
        if not resp.ok:
            return False
        body = await resp.body()
        if len(body) < 16:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        return True
    except Exception:
        return False


async def _scroll_for_lazy_assets(page: Page) -> None:
    """Scroll so lazy-loaded images and backgrounds resolve."""
    try:
        for _ in range(10):
            await page.mouse.wheel(0, 1200)
            await asyncio.sleep(0.1)
        await page.evaluate("() => window.scrollTo(0, 0)")
        await asyncio.sleep(0.15)
    except Exception:
        pass


def _pick_best_role(entries: list[dict], role: str) -> dict | None:
    candidates = [e for e in entries if e.get("role") == role]
    if not candidates:
        return None
    if role in ("logo", "hero"):
        candidates.sort(
            key=lambda x: (x.get("w", 0) or 0) * (x.get("h", 0) or 0),
            reverse=True,
        )
    return candidates[0]


def _build_assets_map(
    downloaded_files: list[dict],
    font_entries: list[dict],
) -> dict[str, dict]:
    assets_map: dict[str, dict] = {}
    for role in ("favicon", "logo", "hero"):
        best = _pick_best_role(downloaded_files, role)
        if best:
            assets_map[role] = best

    if "logo" not in assets_map:
        for entry in downloaded_files:
            if entry.get("role") == "logo" or _url_suggests_logo(entry.get("url", "")):
                assets_map["logo"] = entry
                break

    if font_entries:
        assets_map["font"] = font_entries[0]

    return assets_map


async def extract_assets_from_page(page: Page, source_url: str) -> AssetExtractResult:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug_from_url(source_url)
    await _scroll_for_lazy_assets(page)
    raw = await page.evaluate(_EXTRACT_ASSETS_JS)

    downloaded_files: list[dict] = []
    font_entries: list[dict] = []

    for item in raw.get("urls") or []:
        if len(downloaded_files) >= MAX_URL_ASSETS:
            break
        url = item["url"]
        role = item.get("role", "image")
        digest = hashlib.sha256(url.encode()).hexdigest()[:10]
        ext = _ext_from_url(url, None)
        filename = f"{slug}-{role}-{digest}.{ext}"
        dest = ASSETS_DIR / filename
        if dest.is_file() or await _download_asset(page, url, dest):
            downloaded_files.append(
                {
                    "url": url,
                    "original_url": url,
                    "role": role,
                    "type": "url",
                    "top": item.get("top"),
                    "hint": item.get("hint"),
                    "w": item.get("w"),
                    "h": item.get("h"),
                    **_entry(f"assets/{filename}", alt=item.get("alt")),
                }
            )

    for i, svg_item in enumerate(raw.get("inlineSvgs") or []):
        if i >= MAX_INLINE_SVGS:
            break
        xml = svg_item.get("xml") or ""
        if len(xml) < 40:
            continue
        role = svg_item.get("role", "icon")
        digest = hashlib.sha256(xml.encode()).hexdigest()[:10]
        filename = f"{slug}-{role}-inline-{digest}.svg"
        dest = ASSETS_DIR / filename
        dest.write_text(xml, encoding="utf-8")
        downloaded_files.append(
            {
                "role": role,
                "type": "inline_svg",
                "top": svg_item.get("top"),
                "w": svg_item.get("w"),
                "h": svg_item.get("h"),
                **_entry(f"assets/{filename}", w=svg_item.get("w"), h=svg_item.get("h")),
            }
        )

    for i, font_item in enumerate(raw.get("fontUrls") or []):
        if i >= MAX_FONTS:
            break
        url = font_item["url"]
        family = font_item.get("family") or "font"
        safe_family = re.sub(r"[^a-zA-Z0-9_-]+", "-", family).strip("-") or "font"
        digest = hashlib.sha256(url.encode()).hexdigest()[:8]
        ext = _ext_from_url(url, None)
        rel = f"assets/fonts/{slug}-{safe_family}-{digest}.{ext}"
        dest = Path("output") / rel
        if dest.is_file() or await _download_asset(page, url, dest):
            css_family = family or safe_family
            font_face = (
                f"@font-face {{ font-family: '{css_family}'; "
                f"src: url('/assets/fonts/{dest.name}') format('{ext}'); "
                f"font-display: swap; }}"
            )
            font_entries.append(
                {
                    "family": css_family,
                    "url": url,
                    "original_url": url,
                    "type": "font",
                    "top": 0.0,
                    "font_face": font_face,
                    **_entry(rel),
                }
            )

    assets_map = _build_assets_map(downloaded_files, font_entries)
    total = len(downloaded_files) + len(font_entries)

    ordered = sorted(
        [f for f in downloaded_files if f.get("preview_path")],
        key=lambda x: (
            float(x["top"])
            if isinstance(x.get("top"), (int, float))
            else 1e9,
            -((x.get("w") or 0) * (x.get("h") or 0)),
            x.get("preview_path") or "",
        ),
    )
    clone_paths_ordered = [x["preview_path"] for x in ordered]

    manifest = {
        "source": source_url,
        "assets": assets_map,
        "fonts": font_entries,
        "files": downloaded_files,
        "hints": {
            "use_preview_paths": True,
            "clone_paths_ordered": clone_paths_ordered,
            "mirrored_url_count": len(downloaded_files),
            "inline_svg": [f for f in downloaded_files if f.get("type") == "inline_svg"],
            "font_faces": [f.get("font_face") for f in font_entries if f.get("font_face")],
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    return AssetExtractResult(
        manifest=manifest,
        manifest_path=MANIFEST_PATH,
        downloaded=total,
        source=source_url,
    )


async def extract_assets_url(url: str) -> AssetExtractResult:
    """Navigate to URL and mirror key assets locally."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")

    async with _browser_lock:
        page = await _new_page()
        try:
            await _navigate(page, url)
            return await extract_assets_from_page(page, url)
        except Exception as e:
            return AssetExtractResult(
                manifest={"source": url, "assets": {}, "fonts": [], "files": []},
                manifest_path=MANIFEST_PATH,
                downloaded=0,
                error=str(e),
                source=url,
            )
        finally:
            await page.context.close()


def load_manifest(path: Path | None = None) -> dict | None:
    p = path or MANIFEST_PATH
    if not p.is_file():
        return None
    return json.loads(p.read_text())


def asset_referenced_in_html(manifest_entry: dict, html: str) -> bool:
    """True if output HTML references this mirrored asset (path, inline, or font-family)."""
    local = manifest_entry.get("local", "")
    preview = manifest_entry.get("preview_path", "")
    basename = Path(local).name if local else ""
    if not basename and not manifest_entry.get("family"):
        return False

    patterns = [
        local,
        preview,
        basename,
        f"/assets/{basename}",
        f"assets/{basename}",
    ]
    if local.startswith("assets/fonts/"):
        patterns.append(f"/assets/fonts/{basename}")
        patterns.append(f"assets/fonts/{basename}")

    family = manifest_entry.get("family")
    if family:
        patterns.append(f"font-family:{family}")
        patterns.append(f"font-family: {family}")
        patterns.append(f"'{family}'")
        patterns.append(f'"{family}"')

    html_lower = html.lower()
    return any(p and str(p).lower() in html_lower for p in patterns)

