"""
quality_gate.py
---------------
Layer-2 Quality Gate for the Gold-First Market State Engine (Mr. Ripley).

Role in architecture:
    Reads the observations DB, checks staleness of every Tier-1 and Tier-2
    series, and decides whether a snapshot can be published.

    PASS -> all Tier-1 series are fresh -> snapshot_publisher.py may run
    FAIL -> at least one Tier-1 series is stale/missing -> publish NOTHING

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
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

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
# Series definitions
# All Tier-1 series must PASS for snapshot_ok = True
# Tier-2 series produce warnings only
# ---------------------------------------------------------------------------

SERIES_CHECKS = [
    # --- Tier-1: Gold (primary asset state) ---
    {
        "series_id": "gold_price_proxy",
        "description": "Gold price XAUUSD",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "gold",
    },
    # --- Tier-1: Rates stress ---
    {
        "series_id": "rates_vol_stress_move",
        "description": "MOVE Index (bond stress)",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "stress",
    },
    # --- Tier-1: Real yields ---
    {
        "series_id": "DFII10",
        "description": "10Y TIPS real yield",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "real_yields",
    },
    {
        "series_id": "DFII5",
        "description": "5Y TIPS real yield",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "real_yields",
    },
    # --- Tier-1: Nominal yields ---
    {
        "series_id": "DGS10",
        "description": "10Y Treasury nominal yield",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "nominal_yields",
    },
    {
        "series_id": "DGS2",
        "description": "2Y Treasury nominal yield",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "nominal_yields",
    },
    {
        "series_id": "DGS5",
        "description": "5Y Treasury nominal yield",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "nominal_yields",
    },
    # --- Tier-1: Breakeven inflation ---
    {
        "series_id": "T10YIE",
        "description": "10Y breakeven inflation",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "breakeven",
    },
    {
        "series_id": "T5YIE",
        "description": "5Y breakeven inflation",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "breakeven",
    },
    {
        "series_id": "T5YIFR",
        "description": "5Y/5Y forward inflation",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "breakeven",
    },
    # --- Tier-1: Policy rate ---
    {
        "series_id": "DFF",
        "description": "Effective fed funds rate",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "policy_rate",
    },
    {
        "series_id": "EFFR",
        "description": "NY Fed EFFR",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "policy_rate",
    },
    # --- Tier-1: USD ---
    {
        "series_id": "DTWEXBGS",
        "description": "Broad USD index (goods)",
        "tier": 1,
        "staleness_days": 10,  # FRED publishes with ~1 week structural lag
        "blocks_snapshot": True,
        "group": "usd",
    },
    # --- Tier-1: Risk/stress ---
    {
        "series_id": "VIXCLS",
        "description": "VIX equity implied volatility",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "stress",
    },
    {
        "series_id": "SP500",
        "description": "S&P 500 index",
        "tier": 1,
        "staleness_days": 3,
        "blocks_snapshot": True,
        "group": "risk",
    },
    # --- Tier-2: GLD holdings (flow confirmation) ---
    {
        "series_id": "gld_holdings_flow_confirm",
        "description": "GLD Trust ounces held",
        "tier": 2,
        "staleness_days": 5,
        "blocks_snapshot": False,
        "group": "flow",
    },
    # --- Tier-2: Monthly inflation ---
    {
        "series_id": "CPILFESL",
        "description": "Core CPI",
        "tier": 2,
        "staleness_days": 45,
        "blocks_snapshot": False,
        "group": "inflation_monthly",
    },
    {
        "series_id": "FEDFUNDS",
        "description": "Fed funds rate (monthly avg)",
        "tier": 2,
        "staleness_days": 45,
        "blocks_snapshot": False,
        "group": "inflation_monthly",
    },
    {
        "series_id": "PCEPI",
        "description": "Headline PCE",
        "tier": 2,
        "staleness_days": 45,
        "blocks_snapshot": False,
        "group": "inflation_monthly",
    },
    {
        "series_id": "PCU2122212122210",
        "description": "PPI: Gold ore mining (discontinued 2017)",
        "tier": 2,
        "staleness_days": 9999,  # Discontinued series - staleness check disabled
        "blocks_snapshot": False,
        "group": "inflation_monthly",
    },
]

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_connection(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"DB not found: {db_path}. "
            f"Run the adapters first to create it."
        )
    conn = sqlite3.connect(db_path)  # no detect_types — date parsing handled manually
    conn.row_factory = sqlite3.Row
    return conn


def latest_obs(conn: sqlite3.Connection, series_id: str):
    """Return (latest_date, latest_value) or (None, None) if no data."""
    row = conn.execute(
        """
        SELECT obs_ts, value
        FROM observations
        WHERE series_id = ?
        ORDER BY obs_ts DESC, revision_seq DESC
        LIMIT 1
        """,
        (series_id,)
    ).fetchone()
    if row:
        obs_ts = row["obs_ts"]
        if isinstance(obs_ts, str):
            obs_ts = date.fromisoformat(obs_ts)
        elif hasattr(obs_ts, "date"):
            obs_ts = obs_ts.date()
        return obs_ts, float(row["value"])
    return None, None


def count_rows(conn: sqlite3.Connection, series_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE series_id = ?",
        (series_id,)
    ).fetchone()
    return row["n"] if row else 0


# ---------------------------------------------------------------------------
# Core quality check
# ---------------------------------------------------------------------------

def check_series(
    conn: sqlite3.Connection,
    check: dict,
    clock_date: date,
) -> dict:
    """Run quality check for a single series. Returns result dict."""
    sid = check["series_id"]
    latest_date, latest_value = latest_obs(conn, sid)
    rows = count_rows(conn, sid)

    if latest_date is None:
        return {
            "series_id": sid,
            "description": check["description"],
            "tier": check["tier"],
            "group": check["group"],
            "blocks_snapshot": check["blocks_snapshot"],
            "rows_in_db": 0,
            "latest_obs_date": None,
            "latest_value": None,
            "staleness_days": None,
            "staleness_threshold": check["staleness_days"],
            "data_ok": False,
            "status": "FAIL" if check["blocks_snapshot"] else "WARN",
            "reason": "no data in DB",
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
        "series_id": sid,
        "description": check["description"],
        "tier": check["tier"],
        "group": check["group"],
        "blocks_snapshot": check["blocks_snapshot"],
        "rows_in_db": rows,
        "latest_obs_date": latest_date.isoformat(),
        "latest_value": latest_value,
        "staleness_days": staleness,
        "staleness_threshold": check["staleness_days"],
        "data_ok": ok,
        "status": status,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Run full quality gate
# ---------------------------------------------------------------------------

def run_quality_gate(
    conn: sqlite3.Connection,
    clock_date: date,
) -> dict:
    """
    Run all series checks and compute overall snapshot_ok.
    Returns full quality report dict.
    """
    run_ts = datetime.now(tz=timezone.utc)
    results = []

    for check in SERIES_CHECKS:
        result = check_series(conn, check, clock_date)
        results.append(result)

    # Overall decision
    tier1_results = [r for r in results if r["tier"] == 1]
    tier2_results = [r for r in results if r["tier"] == 2]

    tier1_pass = [r for r in tier1_results if r["status"] == "PASS"]
    tier1_fail = [r for r in tier1_results if r["status"] == "FAIL"]
    tier2_warn = [r for r in tier2_results if r["status"] == "WARN"]

    snapshot_ok = len(tier1_fail) == 0

    report = {
        "run_ts": run_ts.isoformat(),
        "clock_date": clock_date.isoformat(),
        "snapshot_ok": snapshot_ok,
        "verdict": "PASS - snapshot may be published" if snapshot_ok
                   else "FAIL - snapshot blocked",
        "summary": {
            "tier1_total": len(tier1_results),
            "tier1_pass": len(tier1_pass),
            "tier1_fail": len(tier1_fail),
            "tier2_total": len(tier2_results),
            "tier2_warn": len(tier2_warn),
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

    return report


# ---------------------------------------------------------------------------
# Print report to terminal
# ---------------------------------------------------------------------------

def print_report(report: dict) -> None:
    log.info("=" * 68)
    log.info("QUALITY GATE REPORT")
    log.info("  Clock date:   %s", report["clock_date"])
    log.info("  Run time:     %s", report["run_ts"])
    log.info("=" * 68)

    # Group output
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
            latest, value, staleness, r["rows_in_db"]
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

    if report["tier2_warnings"]:
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
        description="Layer-2 Quality Gate — checks all series before snapshot publishing."
    )
    p.add_argument(
        "--clock-date", type=str, default=None,
        help="Override clock date YYYY-MM-DD (default: today). "
             "Use for replays or testing."
    )
    p.add_argument(
        "--db", type=str, default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH})."
    )
    p.add_argument(
        "--report-path", type=str, default=REPORT_PATH,
        help=f"JSON report output path (default: {REPORT_PATH})."
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress detailed per-series output. Show verdict only."
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Clock date
    clock_date = (
        date.fromisoformat(args.clock_date)
        if args.clock_date
        else date.today()
    )

    # DB connection
    try:
        conn = get_connection(args.db)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1

    # Run gate
    log.info("Running quality gate | clock_date=%s | db=%s",
             clock_date, args.db)
    report = run_quality_gate(conn, clock_date)

    # Print to terminal
    if not args.quiet:
        print_report(report)
    else:
        if report["snapshot_ok"]:
            log.info("VERDICT: PASS — snapshot may be published")
        else:
            log.error("VERDICT: FAIL — snapshot BLOCKED | failures: %s",
                      [f["series_id"] for f in report["blocking_failures"]])

    # Save JSON report
    save_report(report, args.report_path)

    # Exit code: 0 = PASS, 1 = FAIL
    return 0 if report["snapshot_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
