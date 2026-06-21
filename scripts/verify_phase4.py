#!/usr/bin/env python3
"""Quick verification for Phase 4 exit criteria (no agent)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sections import list_sections, replace_section, section_exists  # noqa: E402


SAMPLE = """<!DOCTYPE html>
<html><body>
<section data-section="hero"><h1>Hero title</h1></section>
<section data-section="features"><p>Features here</p></section>
<footer data-section="footer"><p>Footer text</p></footer>
</body></html>
"""


def test_list_sections():
    rows = list_sections(SAMPLE)
    names = [r["selector"] for r in rows]
    assert names == ["hero", "features", "footer"]
    print("OK list_sections:", names)


def test_replace_section_hero_only():
    updated, matched = replace_section(
        SAMPLE,
        "hero",
        '<section data-section="hero"><h1>New hero headline</h1></section>',
    )
    assert matched is True
    assert "New hero headline" in updated
    assert "Features here" in updated
    assert "Footer text" in updated
    assert "Hero title" not in updated
    print("OK replace_section hero only")


def test_replace_section_missing():
    updated, matched = replace_section(SAMPLE, "cta", "<p>CTA</p>")
    assert matched is False
    assert updated == SAMPLE
    assert not section_exists(SAMPLE, "cta")
    print("OK replace_section missing selector")


def test_replace_by_id():
    html = '<div id="nav">Old</div><div data-section="hero">H</div>'
    updated, matched = replace_section(html, "#nav", '<div id="nav">New nav</div>')
    assert matched
    assert "New nav" in updated
    print("OK replace by #id")


def main():
    test_list_sections()
    test_replace_section_hero_only()
    test_replace_section_missing()
    test_replace_by_id()
    print("\nAll Phase 4 unit checks passed.")


if __name__ == "__main__":
    main()
