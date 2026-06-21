"""Self-convergence tracking (Phase 6).

Every agent self-check (`compare_to_target`) appends one *round* to the
*active run*. A run is the sequence of self-checks the agent makes while
building/iterating on one chat turn. We persist runs per session so the
Insights view can draw the score curve and the "first build -> final"
delta — concrete evidence that the look -> measure -> fix loop beats a
single naked generation.

The agent loop is serialized by the agent lock in server.py, so there is at
most one active run at a time; a module-level global is safe.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STORE_PATH = Path("data/convergence.json")
MAX_RUNS_PER_SESSION = 8
MAX_WORST = 6
_AXES = ("content", "structure", "layout", "visual", "assets")

# Active run for the in-progress agent turn (None when idle).
_active: dict | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_store() -> dict[str, Any]:
    if not STORE_PATH.is_file():
        return {}
    try:
        return json.loads(STORE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_store(store: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, indent=2) + "\n")


def _reasons_from_report(report: dict) -> list[str]:
    """Human-readable why-this-score lines for the Insights panel."""
    reasons: list[str] = []
    for gf in report.get("gate_failures") or []:
        reasons.append(f"Hard gate failed: {gf}")
    for w in (report.get("worst_sections") or [])[:MAX_WORST]:
        axis = w.get("axis", "?")
        detail = w.get("detail") or w.get("section", "")
        if detail:
            reasons.append(f"Priority fix ({axis}): {detail}")
    if not reasons and report.get("verdict"):
        reasons.append(
            f"Overall verdict {report['verdict']} at {int((report.get('total') or 0) * 100)}% fidelity."
        )
    return reasons[:MAX_WORST + 3]


def _worst_detail_from_report(report: dict) -> list[dict]:
    out = []
    for w in (report.get("worst_sections") or [])[:MAX_WORST]:
        out.append(
            {
                "section": w.get("section", ""),
                "axis": w.get("axis", ""),
                "detail": w.get("detail", ""),
            }
        )
    return out


def _round_from_report(report: dict, index: int) -> dict:
    """Compact one fidelity report into a single round record."""
    axes = report.get("axes") or {}
    normalized = {}
    for axis in _AXES:
        a = axes.get(axis) or {}
        val = a.get("normalized")
        if val is not None:
            normalized[axis] = round(float(val), 4)
    worst_detail = _worst_detail_from_report(report)
    worst = [w["section"] for w in worst_detail if w.get("section")]
    return {
        "round": index,
        "ts": _now(),
        "total": report.get("total"),
        "verdict": report.get("verdict"),
        "axes": normalized,
        "worst": worst,
        "worst_detail": worst_detail,
        "gate_failures": list(report.get("gate_failures") or [])[:MAX_WORST],
        "reasons": _reasons_from_report(report),
    }


def begin_run(url: str | None, profile: str, *, session_id: str | None = None) -> None:
    """Start a fresh active run for a new agent turn."""
    global _active
    _active = {
        "session_id": session_id,
        "url": url or "",
        "profile": profile,
        "started": _now(),
        "rounds": [],
        "decisions": [],
    }


def set_active_session(session_id: str | None) -> None:
    """Attach the detected session id to the active run (idempotent)."""
    if _active is not None and session_id and not _active.get("session_id"):
        _active["session_id"] = session_id


def record_round(report: dict) -> dict | None:
    """Append one self-check round to the active run. Returns the round."""
    if _active is None or not isinstance(report, dict):
        return None
    rnd = _round_from_report(report, len(_active["rounds"]) + 1)
    _active["rounds"].append(rnd)
    return rnd


def record_decision(
    tool: str,
    tool_input: dict | None = None,
    *,
    agent_text: str | None = None,
) -> dict | None:
    """Log one agent tool call and optional stated rationale for Insights."""
    if _active is None:
        return None
    args = tool_input if isinstance(tool_input, dict) else {}
    summary = ""
    for key in ("selector", "url", "profile", "name"):
        if args.get(key):
            summary = f"{key}={args[key]}"
            break
    entry = {
        "ts": _now(),
        "tool": tool,
        "args": summary,
        "after_round": len(_active["rounds"]),
        "agent_said": (agent_text or "").strip()[:400] or None,
    }
    _active.setdefault("decisions", []).append(entry)
    return entry


def end_run() -> dict | None:
    """Persist the active run under its session and clear it."""
    global _active
    if _active is None:
        return None
    run = _active
    _active = None
    if not run["rounds"]:
        return None
    sid = run.get("session_id") or "_pending"
    run["ended"] = _now()
    store = _load_store()
    entry = store.setdefault(sid, {"runs": [], "baseline": None})
    entry["runs"].append(run)
    entry["runs"] = entry["runs"][-MAX_RUNS_PER_SESSION:]
    _save_store(store)
    return run


def set_baseline(session_id: str, report: dict, url: str | None = None) -> dict:
    """Store the naked one-shot A/B baseline for a session."""
    axes = report.get("axes") or {}
    normalized = {
        axis: round(float((axes.get(axis) or {}).get("normalized", 0) or 0), 4)
        for axis in _AXES
        if (axes.get(axis) or {}).get("normalized") is not None
    }
    baseline = {
        "total": report.get("total"),
        "verdict": report.get("verdict"),
        "axes": normalized,
        "url": url or "",
        "ts": _now(),
        "gate_failures": list(report.get("gate_failures") or [])[:MAX_WORST],
        "worst_detail": _worst_detail_from_report(report),
        "reasons": _reasons_from_report(report),
    }
    store = _load_store()
    entry = store.setdefault(session_id, {"runs": [], "baseline": None})
    entry["baseline"] = baseline
    _save_store(store)
    return baseline


def get_state(session_id: str | None) -> dict:
    """Return {runs, baseline, active} for a session for the Insights view."""
    store = _load_store()
    entry = dict(store.get(session_id or "", {"runs": [], "baseline": None}))
    # Surface the in-progress run live (before it is persisted on end_run).
    active = None
    if _active is not None and _active["rounds"]:
        if not _active.get("session_id") or _active.get("session_id") == session_id:
            active = _active
    entry["active"] = active
    entry.setdefault("runs", [])
    entry.setdefault("baseline", None)
    return entry
