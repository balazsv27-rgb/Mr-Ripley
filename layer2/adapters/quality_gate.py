"""
quality_gate.py
---------------
Layer-2 Quality Gate for the Gold-First Market State Engine (Mr. Ripley).

This version consumes layer2.alignment directly so freshness and completeness
are evaluated against the same deterministic point-in-time aligned state used
for snapshot building.

It also exposes the aligned payload directly in the quality report so downstream
consumers (e.g. snapshot_publisher.py) can reuse the same aligned state without
running alignment twice.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.clock import get_default_policy, get_engine_clock  # noqa: E402
from layer2.db import get_connection, count_rows  # noqa: E402
from layer2.alignment import align_snapshot_state, build_snapshot_values_payload  # noqa: E402
from layer2.config.registry import get_registry  # noqa: E402

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
REPORT_PATH: str = os.getenv("L2_REPORT_PATH", "layer2_quality_report.json")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

CLOCK_TIMEZONE: str = os.getenv("L2_CLOCK_TIMEZONE", "UTC")
CLOCK_CUT_HOUR: int = int(os.getenv("L2_CLOCK_CUT_HOUR", "22"))
CLOCK_CUT_MINUTE: int = int(os.getenv("L2_CLOCK_CUT_MINUTE", "0"))
CLOCK_CUT_SECOND: int = int(os.getenv("L2_CLOCK_CUT_SECOND", "0"))
CLOCK_EXCEPTIONS_FILE: str = os.getenv("L2_CLOCK_EXCEPTIONS_FILE", "")
CLOCK_POLICY_VERSION: str = os.getenv("L2_CLOCK_POLICY_VERSION", "clock-v1")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] quality_gate: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


def _build_checks() -> List[dict]:
    reg = get_registry()
    return [
        {
            "series_id": s["series_id"],
            "description": s["description"],
            "tier": s["tier"],
            "staleness_days": s["staleness_days"],
            "blocks_snapshot": s["blocks_snapshot"],
            "group": s["group"],
        }
        for s in reg.snapshot_series()
    ]


def run_quality_gate(conn, clock) -> dict:
    """
    Run the governed quality gate against the aligned point-in-time state.

    The alignment layer is the single source of truth for:
    - admissible rows by clock_ts
    - deterministic tie-breaking
    - missing series detection

    This function now also returns the aligned payload directly so the snapshot
    publisher can reuse it without rerunning alignment.
    """
    run_ts = datetime.now(tz=timezone.utc)
    checks = _build_checks()

    aligned = align_snapshot_state(conn, clock)
    aligned_by_id = {v.series_id: v for v in aligned.values}
    aligned_payload = build_snapshot_values_payload(aligned)

    results: List[dict] = []

    for check in checks:
        sid = check["series_id"]
        rows = count_rows(conn, sid)
        aligned_value = aligned_by_id.get(sid)

        if aligned_value is None:
            results.append(
                {
                    "series_id": sid,
                    "description": check["description"],
                    "tier": check["tier"],
                    "group": check["group"],
                    "blocks_snapshot": check["blocks_snapshot"],
                    "rows_in_db": rows,
                    "latest_obs_date": None,
                    "latest_value": None,
                    "latest_as_of_ts": None,
                    "revision_seq": None,
                    "source": None,
                    "staleness_days": None,
                    "staleness_threshold": check["staleness_days"],
                    "data_ok": False,
                    "status": "FAIL" if check["blocks_snapshot"] else "WARN",
                    "reason": "no point-in-time data available by clock_ts",
                }
            )
            continue

        staleness = aligned_value.staleness_days
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

        results.append(
            {
                "series_id": sid,
                "description": check["description"],
                "tier": check["tier"],
                "group": check["group"],
                "blocks_snapshot": check["blocks_snapshot"],
                "rows_in_db": rows,
                "latest_obs_date": aligned_value.obs_ts.isoformat(),
                "latest_value": aligned_value.value,
                "latest_as_of_ts": aligned_value.as_of_ts.isoformat(),
                "revision_seq": aligned_value.revision_seq,
                "source": aligned_value.source,
                "staleness_days": staleness,
                "staleness_threshold": check["staleness_days"],
                "data_ok": ok,
                "status": status,
                "reason": reason,
            }
        )

    tier1_results = [r for r in results if r["tier"] == 1]
    tier2_results = [r for r in results if r["tier"] == 2]
    tier1_pass = [r for r in tier1_results if r["status"] == "PASS"]
    tier1_fail = [r for r in tier1_results if r["status"] == "FAIL"]
    tier2_warn = [r for r in tier2_results if r["status"] == "WARN"]

    snapshot_ok = len(tier1_fail) == 0

    rr_series = sorted(v["series_id"] for v in aligned_payload if v.get("revision_risk"))

    return {
        "run_ts": run_ts.isoformat(),
        "clock_date": clock.clock_date.isoformat(),
        "clock_ts": clock.clock_ts.isoformat(),
        "clock_meta": clock.to_dict(),
        "alignment_summary": {
            "aligned_series": len(aligned.values),
            "missing_series": aligned.missing_series,
        },
        "aligned_payload": aligned_payload,
        "snapshot_ok": snapshot_ok,
        "verdict": "PASS - snapshot may be published" if snapshot_ok else "FAIL - snapshot blocked",
        "summary": {
            "tier1_total": len(tier1_results),
            "tier1_pass": len(tier1_pass),
            "tier1_fail": len(tier1_fail),
            "tier2_total": len(tier2_results),
            "tier2_warn": len(tier2_warn),
            "revision_risk_series_count": len(rr_series),
            "revision_risk_series": rr_series,
        },
        "blocking_failures": [{"series_id": r["series_id"], "reason": r["reason"]} for r in tier1_fail],
        "tier2_warnings": [{"series_id": r["series_id"], "reason": r["reason"]} for r in tier2_warn],
        "series": results,
    }


def print_report(report: dict) -> None:
    log.info("=" * 68)
    log.info("QUALITY GATE REPORT")
    log.info("  Clock date:   %s", report["clock_date"])
    log.info("  Clock ts:     %s", report["clock_ts"])
    log.info("  Run time:     %s", report["run_ts"])
    log.info("=" * 68)

    current_group = None
    for r in report["series"]:
        if r["group"] != current_group:
            current_group = r["group"]
            log.info("  --- %s ---", current_group.upper())

        latest = r["latest_obs_date"] or "NO DATA"
        value = f"{r['latest_value']:.4f}" if r["latest_value"] is not None else "N/A"
        staleness = f"{r['staleness_days']}d" if r["staleness_days"] is not None else "N/A"

        log.info(
            "  [%s] T%d %-30s latest=%-12s val=%-10s stale=%-5s rows=%d",
            r["status"],
            r["tier"],
            r["series_id"],
            latest,
            value,
            staleness,
            r["rows_in_db"],
        )

    s = report["summary"]
    log.info("=" * 68)
    log.info("  Tier-1: %d/%d PASS | %d FAIL", s["tier1_pass"], s["tier1_total"], s["tier1_fail"])
    log.info("  Tier-2: %d WARN", s["tier2_warn"])
    log.info("  Aligned series: %d", report["alignment_summary"]["aligned_series"])
    if report["alignment_summary"]["missing_series"]:
        log.warning("  Missing series: %s", report["alignment_summary"]["missing_series"])
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


def save_report(report: dict, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("Quality report saved to: %s", p)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 Quality Gate — governed by layer2.clock and layer2.alignment."
    )
    p.add_argument("--clock-date", type=str, default=None, help="Override clock date YYYY-MM-DD.")
    p.add_argument("--db", type=str, default=DB_PATH, help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument(
        "--report-path",
        type=str,
        default=REPORT_PATH,
        help=f"JSON report output path (default: {REPORT_PATH}).",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress detailed per-series output. Show verdict only.")
    p.add_argument("--timezone", type=str, default=CLOCK_TIMEZONE, help=f"Clock timezone (default: {CLOCK_TIMEZONE}).")
    p.add_argument("--cut-hour", type=int, default=CLOCK_CUT_HOUR, help=f"Clock cut hour (default: {CLOCK_CUT_HOUR}).")
    p.add_argument("--cut-minute", type=int, default=CLOCK_CUT_MINUTE, help=f"Clock cut minute (default: {CLOCK_CUT_MINUTE}).")
    p.add_argument("--cut-second", type=int, default=CLOCK_CUT_SECOND, help=f"Clock cut second (default: {CLOCK_CUT_SECOND}).")
    p.add_argument("--exceptions-file", type=str, default=CLOCK_EXCEPTIONS_FILE or None, help="Optional calendar exceptions JSON file.")
    p.add_argument("--policy-version", type=str, default=CLOCK_POLICY_VERSION, help=f"Clock policy version (default: {CLOCK_POLICY_VERSION}).")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    policy = get_default_policy(
        timezone_name=args.timezone,
        cut_hour=args.cut_hour,
        cut_minute=args.cut_minute,
        cut_second=args.cut_second,
        exceptions_path=args.exceptions_file,
        policy_version=args.policy_version,
    )
    clock = get_engine_clock(args.clock_date, policy=policy)

    try:
        conn = get_connection(args.db)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1

    log.info("Running quality gate | clock_ts=%s | db=%s", clock.clock_ts.isoformat(), args.db)
    report = run_quality_gate(conn, clock)

    if not args.quiet:
        print_report(report)
    else:
        if report["snapshot_ok"]:
            log.info("VERDICT: PASS — snapshot may be published")
        else:
            log.error(
                "VERDICT: FAIL — snapshot BLOCKED | failures: %s",
                [f["series_id"] for f in report["blocking_failures"]],
            )

    save_report(report, args.report_path)
    return 0 if report["snapshot_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
