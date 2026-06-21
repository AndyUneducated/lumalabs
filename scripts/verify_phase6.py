#!/usr/bin/env python3
"""Phase 6 verification: self-convergence tracking + A/B baseline store."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import convergence  # noqa: E402


def _report(total, verdict, worst, gates=None):
    return {
        "total": total,
        "verdict": verdict,
        "axes": {
            "content": {"normalized": total},
            "layout": {"normalized": total},
            "visual": {"normalized": total},
        },
        "worst_sections": [{"section": s, "axis": "layout"} for s in worst],
        "gate_failures": gates or [],
    }


def _with_temp_store(fn):
    tmp = Path(tempfile.mkdtemp())
    orig = convergence.STORE_PATH
    try:
        convergence.STORE_PATH = tmp / "convergence.json"
        convergence._active = None
        fn()
    finally:
        convergence.STORE_PATH = orig
        convergence._active = None


def test_run_records_rounds_in_order():
    def body():
        convergence.begin_run("https://x.test", "balanced", session_id="s1")
        convergence.record_round(_report(0.55, "fail", ["hero", "footer"]))
        convergence.record_round(_report(0.72, "warn", ["footer"]))
        convergence.record_round(_report(0.88, "pass", []))
        run = convergence.end_run()
        assert run is not None
        totals = [r["total"] for r in run["rounds"]]
        assert totals == [0.55, 0.72, 0.88], totals
        assert run["rounds"][0]["round"] == 1
        assert run["rounds"][-1]["verdict"] == "pass"
        print("ok test_run_records_rounds_in_order")

    _with_temp_store(body)


def test_state_persists_per_session_and_live_active():
    def body():
        convergence.begin_run("https://x.test", "balanced", session_id="sA")
        convergence.record_round(_report(0.6, "fail", ["nav"]))
        # Active run is visible before end_run (live updates).
        live = convergence.get_state("sA")
        assert live["active"] is not None
        assert len(live["active"]["rounds"]) == 1
        convergence.end_run()
        saved = convergence.get_state("sA")
        assert saved["active"] is None
        assert len(saved["runs"]) == 1
        # Unrelated session is empty.
        assert convergence.get_state("other")["runs"] == []
        print("ok test_state_persists_per_session_and_live_active")

    _with_temp_store(body)


def test_baseline_stored_for_ab():
    def body():
        convergence.set_baseline(
            "sB",
            _report(0.5, "fail", [], gates=["content: low coverage"]),
            url="https://x.test",
        )
        state = convergence.get_state("sB")
        assert state["baseline"] is not None
        assert state["baseline"]["total"] == 0.5
        assert state["baseline"]["reasons"]
        print("ok test_baseline_stored_for_ab")

    _with_temp_store(body)


def test_decisions_recorded_on_active_run():
    def body():
        convergence.begin_run("https://x.test", "balanced", session_id="sD")
        convergence.record_decision("capture_site", {"url": "https://x.test"}, agent_text="I'll capture the site first.")
        convergence.record_round(_report(0.55, "fail", ["hero"]))
        run = convergence.end_run()
        assert run is not None
        assert len(run["decisions"]) == 1
        assert run["decisions"][0]["tool"] == "capture_site"
        assert run["rounds"][0]["reasons"]
        print("ok test_decisions_recorded_on_active_run")

    _with_temp_store(body)


def test_faithfulness_escalation_after_low_first_round():
    def body():
        convergence.begin_run("https://x.test", "more_faithful", session_id="sE")
        convergence.record_round(_report(0.5, "fail", ["hero"]))
        assert convergence.faithfulness_escalation_note("more_faithful") is None
        convergence.record_round(_report(0.55, "fail", ["hero"]))
        note = convergence.faithfulness_escalation_note("more_faithful")
        assert note is not None
        assert "ESCALATION MODE" in note
        assert convergence.faithfulness_escalation_note("balanced") is None
        convergence.end_run()
        print("ok test_faithfulness_escalation_after_low_first_round")

    _with_temp_store(body)


def test_faithfulness_escalation_skipped_when_first_ok():
    def body():
        convergence.begin_run("https://x.test", "more_faithful", session_id="sF")
        convergence.record_round(_report(0.85, "pass", []))
        convergence.record_round(_report(0.86, "pass", []))
        assert convergence.faithfulness_escalation_note("more_faithful") is None
        convergence.end_run()
        print("ok test_faithfulness_escalation_skipped_when_first_ok")

    _with_temp_store(body)


def test_empty_run_not_persisted():
    def body():
        convergence.begin_run("https://x.test", "balanced", session_id="sC")
        assert convergence.end_run() is None  # no rounds → nothing saved
        assert convergence.get_state("sC")["runs"] == []
        print("ok test_empty_run_not_persisted")

    _with_temp_store(body)


if __name__ == "__main__":
    test_run_records_rounds_in_order()
    test_state_persists_per_session_and_live_active()
    test_baseline_stored_for_ab()
    test_decisions_recorded_on_active_run()
    test_faithfulness_escalation_after_low_first_round()
    test_faithfulness_escalation_skipped_when_first_ok()
    test_empty_run_not_persisted()
    print("All Phase 6 checks passed.")
