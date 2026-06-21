#!/usr/bin/env python3
"""Phase 5 verification: history snapshots, rollback, diff, friendly errors."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from browser import friendly_capture_error  # noqa: E402
import history  # noqa: E402


def _with_temp_output(fn):
    tmp = Path(tempfile.mkdtemp())
    orig_dir = history.OUTPUT_DIR
    orig_file = history.OUTPUT_FILE
    orig_hist = history.HISTORY_DIR
    orig_index = history.INDEX_FILE
    try:
        history.OUTPUT_DIR = tmp
        history.OUTPUT_FILE = tmp / "index.html"
        history.HISTORY_DIR = tmp / ".history"
        history.INDEX_FILE = history.HISTORY_DIR / "index.json"
        fn()
    finally:
        history.OUTPUT_DIR = orig_dir
        history.OUTPUT_FILE = orig_file
        history.HISTORY_DIR = orig_hist
        history.INDEX_FILE = orig_index
        shutil.rmtree(tmp, ignore_errors=True)


def test_save_creates_snapshots():
    def run():
        history.save_output("<html>v1</html>", "write_html")
        history.save_output("<html>v2</html>", "write_html")
        history.save_output("<html>v3</html>", "write_html")
        assert history.OUTPUT_FILE.read_text() == "<html>v3</html>"
        entries = history._load_index()
        assert len(entries) == 2
        assert entries[0]["label"] == "write_html"
        assert (history.HISTORY_DIR / entries[0]["file"]).read_text() == "<html>v1</html>"
        assert (history.HISTORY_DIR / entries[1]["file"]).read_text() == "<html>v2</html>"

    _with_temp_output(run)
    print("ok test_save_creates_snapshots")


def test_revert_last_restores_prior():
    def run():
        history.save_output("<html>v1</html>", "write_html")
        history.save_output("<html>v2</html>", "write_html")
        result = history.revert_last()
        assert "error" not in result
        assert history.OUTPUT_FILE.read_text() == "<html>v1</html>"

    _with_temp_output(run)
    print("ok test_revert_last_restores_prior")


def test_diff_non_empty_on_change():
    def run():
        history.save_output("<html>v1</html>", "write_html")
        history.save_output("<html>v2</html>", "write_html")
        text = history.diff()
        assert "v1" in text and "v2" in text

    _with_temp_output(run)
    print("ok test_diff_non_empty_on_change")


def test_diff_empty_when_identical():
    def run():
        history.save_output("<html>same</html>", "write_html")
        history.save_output("<html>same</html>", "write_html")
        text = history.diff()
        assert text == ""

    _with_temp_output(run)
    print("ok test_diff_empty_when_identical")


def test_friendly_capture_error():
    assert "too long" in friendly_capture_error("Timeout 30000ms exceeded").lower()
    assert "reach" in friendly_capture_error("net::ERR_NAME_NOT_RESOLVED").lower()
    long = "x" * 300
    assert "fallback" in friendly_capture_error(long).lower()
    print("ok test_friendly_capture_error")


def main() -> int:
    test_save_creates_snapshots()
    test_revert_last_restores_prior()
    test_diff_non_empty_on_change()
    test_diff_empty_when_identical()
    test_friendly_capture_error()
    print("All Phase 5 checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
