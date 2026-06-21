"""Version snapshots for output/index.html (Phase 5).

Every write goes through save_output(), which snapshots the prior state
before overwriting. Snapshots live under output/.history/ with index.json.
"""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from builder_config import OUTPUT_DIR, OUTPUT_FILE

HISTORY_DIR = OUTPUT_DIR / ".history"
INDEX_FILE = HISTORY_DIR / "index.json"
MAX_ENTRIES = 50


def _sanitize_label(label: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", label.strip())[:40]
    return s.strip("-") or "change"


def _load_index() -> list[dict]:
    if not INDEX_FILE.is_file():
        return []
    try:
        return json.loads(INDEX_FILE.read_text())
    except json.JSONDecodeError:
        return []


def _save_index(entries: list[dict]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(entries, indent=2) + "\n")


def _next_seq(entries: list[dict]) -> int:
    if not entries:
        return 1
    return max(int(e.get("seq", 0)) for e in entries) + 1


def _trim_entries(entries: list[dict]) -> list[dict]:
    if len(entries) <= MAX_ENTRIES:
        return entries
    drop = entries[: len(entries) - MAX_ENTRIES]
    for entry in drop:
        path = HISTORY_DIR / entry.get("file", "")
        if path.is_file():
            path.unlink(missing_ok=True)
    return entries[-MAX_ENTRIES:]


def save_output(html: str, label: str) -> dict:
    """Snapshot current output (if any), then write new html."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    entries = _load_index()
    snapshot: dict | None = None

    if OUTPUT_FILE.is_file():
        seq = _next_seq(entries)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_label = _sanitize_label(label)
        fname = f"{seq:04d}-{ts}-{safe_label}.html"
        snap_path = HISTORY_DIR / fname
        snap_path.write_text(OUTPUT_FILE.read_text())
        snapshot = {
            "seq": seq,
            "ts": ts,
            "label": label,
            "file": fname,
            "size": snap_path.stat().st_size,
        }
        entries.append(snapshot)
        entries = _trim_entries(entries)
        _save_index(entries)

    OUTPUT_FILE.write_text(html)

    return {"saved": True, "snapshot": snapshot, "bytes": len(html)}


def list_history() -> list[dict]:
    """Newest snapshot first."""
    return list(reversed(_load_index()))


def _entry_by_seq(seq: int) -> dict | None:
    for entry in _load_index():
        if int(entry.get("seq", -1)) == int(seq):
            return entry
    return None


def restore(seq: int) -> dict:
    """Restore a snapshot into output/index.html (snapshots current first)."""
    entry = _entry_by_seq(seq)
    if not entry:
        return {"error": f"Snapshot {seq} not found."}

    fname = entry.get("file")
    if not fname:
        return {"error": "Snapshot record missing file path."}

    snap_path = HISTORY_DIR / fname
    if not snap_path.is_file():
        return {"error": f"Snapshot file missing: {fname}"}

    content = snap_path.read_text()
    save_output(content, f"rollback-{seq}")
    return {"restored": seq, "label": entry.get("label", "")}


def revert_last() -> dict:
    """Restore the most recent pre-change snapshot."""
    entries = _load_index()
    if not entries:
        return {"error": "No history yet. Make an edit after the initial page."}
    last = entries[-1]
    seq = last.get("seq")
    if seq is None:
        return {"error": "History index is corrupt (missing seq)."}
    return restore(int(seq))


def diff(seq: int | None = None) -> str:
    """Unified diff between a snapshot (or latest) and current output."""
    entries = _load_index()
    if not entries:
        return ""

    if seq is None:
        entry = entries[-1]
    else:
        entry = _entry_by_seq(seq)
        if not entry:
            return f"# Snapshot {seq} not found\n"

    dfname = entry.get("file")
    if not dfname:
        return "# Snapshot record missing file path\n"

    snap_path = HISTORY_DIR / dfname
    if not snap_path.is_file():
        return f"# Snapshot file missing: {dfname}\n"

    if not OUTPUT_FILE.is_file():
        return "# No current output\n"

    from_lines = snap_path.read_text().splitlines(keepends=True)
    to_lines = OUTPUT_FILE.read_text().splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=f"snapshot-{entry.get('seq', '?')}",
            tofile="current",
            lineterm="",
        )
    )
