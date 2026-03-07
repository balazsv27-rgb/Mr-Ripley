"""
quality_gate.py
---------------
Layer-2 Quality Gate for the Gold-First Market State Engine (Mr. Ripley).

Role in architecture:
    Reads the observations DB, checks staleness of every Tier-1 and Tier-2
    series, and decides whether a snapshot can be published.

    PASS -> all Tier-1 series fresh -> snapshot_publisher.py may run
    FAIL -> at least one Tier-1 series stale/missing -> publish NOTHING

All series metadata (IDs, tiers, staleness thresholds, group names) comes
from series_registry.json via layer2.config.registry. No hardcoded lists here.

Output:
    1. Terminal log (always)
    2. JSON report file (default: layer2_quality_report.json)

Usage:
    python layer2/adapters/quality_gate.py
    python layer2/adapters/quality_gate.py --report-path reports/quality.json
    python layer2/adapters/quality_gate.py --clock-date 2026-03-03
    python layer2/adapters/quality_gate.py --quiet
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Layer-2 shared modules
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.db import get_connection, latest_obs, count_rows  # noqa: E402
from layer2.config.registry import get_registry               # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
REPORT_PATH: str = os.getenv("L2_REPORT_PATH", "layer2_quality_report.json")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] quality_gate: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Build checks list from registry (replaces hardcoded SERIES_CHECKS)
# ---------------------------------------------------------------------------

def _build_checks() -> List[dict]:
    """
    Return a list of check dicts built from the registry.
    Only includes series with include_in_snapshot=True (the 20 active series).
    Discontinued series are included with their staleness effectively disabled
    (threshold=9999 in registry).
    """
    reg = get_registry()
    checks = []
    for s in reg.snapshot_series():
        checks.append({
            "series_id":       s["series_id"],
            "description":     s["description"],
            "tier":            s["tier"],
            "staleness_days":  s["staleness_days"],
            "blocks_snapshot": s["blocks_snapshot"],
            "group":           s["group"],
        })
    return checks


# ---------------------------------------------------------------------------
# Core quality check
# ---------------------------------------------------------------------------

def check_series(
    conn,
    check: dict,
    clock_date: date,
) -> dict:
    """Run quality check for a single series. Returns result dict."""
    sid = check["series_id"]
    latest_date, latest_value = latest_obs(conn, sid)
    rows = count_rows(conn, sid)

    if latest_date is None:
        return {
            "series_id":           sid,
            "description":         check["description"],
            "tier":                check["tier"],
            "group":               check["group"],
            "blocks_snapshot":     check["blocks_snapshot"],
            "rows_in_db":          0,
            "latest_obs_date":     None,
            "latest_value":        None,
            "staleness_days":      None,
            "staleness_threshold": check["staleness_days"],
            "data_ok":             False,
            "status":              "FAIL" if check["blocks_snapshot"] else "WARN",
            "reason":              "no data in DB",
        }

    staleness = (clock_date - latest_date).days
    ok = staleness <= check["staleness_days"]

    if ok:
        status = "PASS"
        reason = "fresh"
    elif check["blocks_snapshot"]:
        status = "FAIL"
        reason = f"stale: {staleness}d > {check['staleness_days']}d threshold"
    else:
        status = "WARN"
        reason = f"stale: {staleness}d > {check['staleness_days']}d threshold"

    return {
        "series_id":           sid,
        "description":         check["description"],
        "tier":                check["tier"],
        "group":               check["group"],
        "blocks_snapshot":     check["blocks_snapshot"],
        "rows_in_db":          rows,
        "latest_obs_date":     latest_date.isoformat(),
        "latest_value":        latest_value,
        "staleness_days":      staleness,
        "staleness_threshold": check["staleness_days"],
        "data_ok":             ok,
        "status":              status,
        "reason":              reason,
    }


# ---------------------------------------------------------------------------
# Run full quality gate
# ---------------------------------------------------------------------------

def run_quality_gate(conn, clock_date: date) -> dict:
    """
    Run all checks from the registry and compute snapshot_ok verdict.
    Returns full quality report dict compatible with snapshot_publisher.
    """
    run_ts = datetime.now(tz=timezone.utc)
    checks = _build_checks()
    results = [check_series(conn, c, clock_date) for c in checks]

    tier1_results = [r for r in results if r["tier"] == 1]
    tier2_results = [r for r in results if r["tier"] == 2]

    tier1_pass = [r for r in tier1_results if r["status"] == "PASS"]
    tier1_fail = [r for r in tier1_results if r["status"] == "FAIL"]
    tier2_warn = [r for r in tier2_results if r["status"] == "WARN"]

    snapshot_ok = len(tier1_fail) == 0

    return {
        "run_ts":       run_ts.isoformat(),
        "clock_date":   clock_date.isoformat(),
        "snapshot_ok":  snapshot_ok,
        "verdict": (
            "PASS - snapshot may be published"
            if snapshot_ok
            else "FAIL - snapshot blocked"
        ),
        "summary": {
            "tier1_total": len(tier1_results),
            "tier1_pass":  len(tier1_pass),
            "tier1_fail":  len(tier1_fail),
            "tier2_total": len(tier2_results),
            "tier2_warn":  len(tier2_warn),
        },
        "blocking_failures": [
            {"series_id": r["series_id"], "reason": r["reason"]}
            for r in tier1_fail
        ],
        "tier2_warnings": [
            {"series_id": r["series_id"], "reason": r["reason"]}
            for r in tier2_warn
        ],
        "series": results,
    }


# ---------------------------------------------------------------------------
# Print report to terminal
# ---------------------------------------------------------------------------

def print_report(report: dict) -> None:
    log.info("=" * 68)
    log.info("QUALITY GATE REPORT")
    log.info("  Clock date:   %s", report["clock_date"])
    log.info("  Run time:     %s", report["run_ts"])
    log.info("=" * 68)

    current_group = None
    for r in report["series"]:
        if r["group"] != current_group:
            current_group = r["group"]
            log.info("  --- %s ---", current_group.upper())

        status_str = r["status"]
        latest = r["latest_obs_date"] or "NO DATA"
        value = f"{r['latest_value']:.4f}" if r["latest_value"] is not None else "N/A"
        staleness = f"{r['staleness_days']}d" if r["staleness_days"] is not None else "N/A"

        log.info(
            "  [%s] T%d %-30s latest=%-12s val=%-10s stale=%-5s rows=%d",
            status_str, r["tier"], r["series_id"],
            latest, value, staleness, r["rows_in_db"],
        )

    log.info("=" * 68)
    s = report["summary"]
    log.info("  Tier-1: %d/%d PASS | %d FAIL",
             s["tier1_pass"], s["tier1_total"], s["tier1_fail"])
    log.info("  Tier-2: %d WARN", s["tier2_warn"])
    log.info("=" * 68)

    if report["snapshot_ok"]:
        log.info("  VERDICT: ✓ PASS — snapshot may be published")
    else:
        log.error("  VERDICT: ✗ FAIL — snapshot BLOCKED")
        for f in report["blocking_failures"]:
            log.error("    BLOCKING: %s — %s", f["series_id"], f["reason"])

    for w in report["tier2_warnings"]:
        log.warning("    WARNING:  %s — %s", w["series_id"], w["reason"])

    log.info("=" * 68)


# ---------------------------------------------------------------------------
# Save JSON report
# ---------------------------------------------------------------------------

def save_report(report: dict, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("Quality report saved to: %s", p)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Layer-2 Quality Gate — checks all registry series before "
            "snapshot publishing."
        )
    )
    p.add_argument("--clock-date", type=str, default=None,
                   help="Override clock date YYYY-MM-DD (default: today).")
    p.add_argument("--db", type=str, default=DB_PATH,
                   help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--report-path", type=str, default=REPORT_PATH,
                   help=f"JSON report output path (default: {REPORT_PATH}).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress detailed per-series output. Show verdict only.")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    clock_date = (
        date.fromisoformat(args.clock_date) if args.clock_date else date.today()
    )

    try:
        conn = get_connection(args.db)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1

    log.info("Running quality gate | clock_date=%s | db=%s", clock_date, args.db)
    report = run_quality_gate(conn, clock_date)

    if not args.quiet:
        print_report(report)
    else:
        if report["snapshot_ok"]:
            log.info("VERDICT: PASS — snapshot may be published")
        else:
            log.error("VERDICT: FAIL — snapshot BLOCKED | failures: %s",
                      [f["series_id"] for f in report["blocking_failures"]])

    save_report(report, args.report_path)
    return 0 if report["snapshot_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
