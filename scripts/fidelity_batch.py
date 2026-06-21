#!/usr/bin/env python3
"""Batch fidelity scoring and calibration for benchmark sites.

Usage:
  python scripts/fidelity_batch.py output/index.html
  python scripts/fidelity_batch.py output/index.html --url https://example.com
  python scripts/fidelity_batch.py --calibrate output/index.html
  python scripts/fidelity_batch.py --generate [--profile balanced]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.pop("CLAUDECODE", None)

from browser import capture_compare, close_browser  # noqa: E402
from compare import default_config, fidelity_report, load_config  # noqa: E402

BENCHMARKS = ROOT / "data" / "benchmarks.json"
REPORT_OUT = ROOT / "data" / "fidelity_report.json"
REGRESSION_OUT = ROOT / "data" / "regression_report.json"
OUTPUT_FILE = ROOT / "output" / "index.html"


async def _capture_pair(url: str, html_path: Path):
    target = await capture_compare(url, is_file=False)
    output = await capture_compare(str(html_path.resolve()), is_file=True)
    return target, output


def _report_from_captures(
    url: str, site_id: str, target, output, profile: str | None = None
) -> dict:
    if target.compare_payload is None or output.compare_payload is None:
        from browser import friendly_capture_error

        return {
            "id": site_id or url,
            "url": url,
            "error": "compare payload unavailable",
            "target_error": friendly_capture_error(target.error),
            "output_error": friendly_capture_error(output.error),
        }
    cfg = load_config(profile=profile) if profile else load_config()
    report = fidelity_report(
        target.compare_payload,
        output.compare_payload,
        target.paths,
        output.paths,
        cfg,
    )
    return {"id": site_id or url, "url": url, **report}


async def _run_report_async(
    url: str, html_path: Path, site_id: str = "", profile: str | None = None
) -> dict:
    target, output = await _capture_pair(url, html_path)
    return _report_from_captures(url, site_id, target, output, profile=profile)


def _run_report(url: str, html_path: Path, site_id: str = "") -> dict:
    return asyncio.run(_run_report_async(url, html_path, site_id))


def _print_table(rows: list[dict]) -> None:
    header = (
        f"{'site':<12} {'verdict':<8} {'total':>6} "
        f"{'content':>8} {'struct':>8} {'layout':>8} {'visual':>8}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        if "error" in row:
            print(f"{row.get('id', '?'):<12} ERROR    {row.get('error', '')}")
            continue
        axes = row.get("axes", {})
        print(
            f"{row.get('id', '?'):<12} "
            f"{row.get('verdict', '?'):<8} "
            f"{row.get('total', 0):>6.3f} "
            f"{axes.get('content', {}).get('raw', 0):>8.3f} "
            f"{axes.get('structure', {}).get('raw', 0):>8.3f} "
            f"{axes.get('layout', {}).get('raw', 0):>8.3f} "
            f"{axes.get('visual', {}).get('raw', 0):>8.3f}"
        )


def _axis_raw(report: dict, axis: str) -> float:
    return report.get("axes", {}).get(axis, {}).get("raw", 0.0)


async def _calibrate_async(html_path: Path) -> dict:
    benchmarks = json.loads(BENCHMARKS.read_text())
    cfg = default_config()

    # Ceil: self-compare on first benchmark target
    first_url = benchmarks[0]["url"]
    target = await capture_compare(first_url, is_file=False)
    if target.compare_payload:
        self_report = fidelity_report(
            target.compare_payload,
            target.compare_payload,
            target.paths,
            target.paths,
            cfg,
        )
        for axis in ("content", "structure", "layout", "visual"):
            cfg["bands"][axis]["ceil"] = round(_axis_raw(self_report, axis), 4)

    # Floor: mismatched pairs (site A target vs same output HTML)
    mismatch_scores: dict[str, list[float]] = {
        axis: [] for axis in ("content", "structure", "layout", "visual")
    }
    for bench in benchmarks[1:3]:
        other = await capture_compare(bench["url"], is_file=False)
        out = await capture_compare(str(html_path.resolve()), is_file=True)
        if other.compare_payload and out.compare_payload:
            rep = fidelity_report(
                other.compare_payload,
                out.compare_payload,
                other.paths,
                out.paths,
                cfg,
            )
            for axis in mismatch_scores:
                mismatch_scores[axis].append(_axis_raw(rep, axis))

    for axis, scores in mismatch_scores.items():
        if scores:
            floor = min(scores) * 0.95
            cfg["bands"][axis]["floor"] = round(max(0.0, floor), 4)

    # Realistic medians from benchmark targets vs shared output
    realistic: dict[str, list[float]] = {
        axis: [] for axis in ("content", "structure", "layout", "visual")
    }
    for bench in benchmarks:
        target = await capture_compare(bench["url"], is_file=False)
        out = await capture_compare(str(html_path.resolve()), is_file=True)
        if target.compare_payload and out.compare_payload:
            rep = fidelity_report(
                target.compare_payload,
                out.compare_payload,
                target.paths,
                out.paths,
                cfg,
            )
            for axis in realistic:
                realistic[axis].append(_axis_raw(rep, axis))

    medians = {
        axis: round(statistics.median(vals), 4) if vals else None
        for axis, vals in realistic.items()
    }

    totals = []
    for bench in benchmarks:
        target = await capture_compare(bench["url"], is_file=False)
        out = await capture_compare(str(html_path.resolve()), is_file=True)
        if target.compare_payload and out.compare_payload:
            rep = fidelity_report(
                target.compare_payload,
                out.compare_payload,
                target.paths,
                out.paths,
                cfg,
            )
            totals.append(rep.get("total", 0))

    if totals:
        med_total = statistics.median(totals)
        cfg["thresholds"]["pass"] = round(max(0.75, med_total - 0.05), 2)
        cfg["thresholds"]["warn"] = round(max(0.55, med_total - 0.20), 2)

    return {
        "suggested_config": cfg,
        "realistic_medians": medians,
        "note": "Paste suggested_config into data/fidelity.json after review.",
    }


async def _run_agent_for_url(url: str, profile: str) -> None:
    """Run the website builder agent end-to-end for one benchmark URL."""
    from claude_agent_sdk import ClaudeSDKClient
    from agent_loop import _build_agent_options
    from tools import set_fidelity_profile, set_notify_fn

    set_notify_fn(lambda _e=None: None)
    set_fidelity_profile(profile)
    opts = _build_agent_options(fidelity_profile=profile)
    message = (
        f"Build a landing page template inspired by this URL: {url}\n"
        "Follow the full workflow: capture_site, build with write_html, "
        "self-check with compare_to_target, and iterate up to 2 rounds."
    )
    async with ClaudeSDKClient(options=opts) as client:
        await client.query(message)
        async for _msg in client.receive_response():
            pass


async def _generate_regression(profile: str) -> list[dict]:
    benchmarks = json.loads(BENCHMARKS.read_text())
    rows: list[dict] = []
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    for bench in benchmarks:
        site_id = bench["id"]
        url = bench["url"]
        print(f"[generate] {site_id}: {url}", file=sys.stderr)

        if OUTPUT_FILE.is_file():
            OUTPUT_FILE.unlink()

        try:
            await _run_agent_for_url(url, profile)
        except Exception as e:
            rows.append({"id": site_id, "url": url, "error": f"agent failed: {e}"})
            continue

        if not OUTPUT_FILE.is_file():
            rows.append({"id": site_id, "url": url, "error": "no output generated"})
            continue

        backup = OUTPUT_FILE.parent / f"regression-{site_id}.html"
        shutil.copy(OUTPUT_FILE, backup)
        row = await _run_report_async(url, OUTPUT_FILE, site_id, profile=profile)
        row["output_backup"] = str(backup.relative_to(ROOT))
        rows.append(row)

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Fidelity batch scoring")
    parser.add_argument(
        "html",
        nargs="?",
        default="output/index.html",
        help="Path to output HTML to compare",
    )
    parser.add_argument("--url", help="Single target URL (skip benchmark list)")
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Suggest floor/ceil/thresholds from benchmarks",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Run agent per benchmark URL, score, write regression_report.json",
    )
    parser.add_argument(
        "--profile",
        default="balanced",
        help="Fidelity profile for --generate (default: balanced)",
    )
    parser.add_argument(
        "--output",
        default=str(REPORT_OUT),
        help="JSON report output path",
    )
    args = parser.parse_args()

    html_path = Path(args.html)
    if not args.calibrate and not args.generate and not html_path.is_file():
        print(f"HTML not found: {html_path}", file=sys.stderr)
        return 1

    try:
        if args.generate:
            rows = asyncio.run(_generate_regression(args.profile))
            _print_table(rows)
            payload = {
                "profile": args.profile,
                "generated_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "sites": rows,
            }
            REGRESSION_OUT.write_text(json.dumps(payload, indent=2) + "\n")
            print(f"\nWrote {REGRESSION_OUT}")
            return 0

        if args.calibrate:
            if not html_path.is_file():
                print(f"HTML required for calibration: {html_path}", file=sys.stderr)
                return 1
            result = asyncio.run(_calibrate_async(html_path))
            print(json.dumps(result, indent=2))
            return 0

        rows: list[dict] = []
        if args.url:
            rows.append(_run_report(args.url, html_path))
        else:
            benchmarks = json.loads(BENCHMARKS.read_text())
            for bench in benchmarks:
                rows.append(_run_report(bench["url"], html_path, bench["id"]))

        _print_table(rows)
        out_path = Path(args.output)
        out_path.write_text(json.dumps(rows, indent=2) + "\n")
        print(f"\nWrote {out_path}")
        return 0
    finally:
        async def _shutdown() -> None:
            await asyncio.wait_for(close_browser(), timeout=15.0)

        try:
            asyncio.run(_shutdown())
        except (asyncio.TimeoutError, Exception):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
