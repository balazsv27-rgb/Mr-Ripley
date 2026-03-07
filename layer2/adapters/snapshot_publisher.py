"""
snapshot_publisher.py
---------------------
Layer-2 Snapshot Publisher integrated with layer2.clock and layer2.alignment.

This version reuses the aligned payload exposed by quality_gate.py so alignment
is computed once per run and then shared between the gate and publisher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.clock import get_default_policy, get_engine_clock  # noqa: E402
from layer2.db import get_connection  # noqa: E402
from layer2.alignment import align_snapshot_state, build_snapshot_values_payload  # noqa: E402
from layer2.config.registry import get_registry  # noqa: E402

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SNAPSHOT_JSON_PATH: str = os.getenv("L2_SNAPSHOT_PATH", "latest_snapshot.json")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

CLOCK_TIMEZONE: str = os.getenv("L2_CLOCK_TIMEZONE", "UTC")
CLOCK_CUT_HOUR: int = int(os.getenv("L2_CLOCK_CUT_HOUR", "22"))
CLOCK_CUT_MINUTE: int = int(os.getenv("L2_CLOCK_CUT_MINUTE", "0"))
CLOCK_CUT_SECOND: int = int(os.getenv("L2_CLOCK_CUT_SECOND", "0"))
CLOCK_EXCEPTIONS_FILE: str = os.getenv("L2_CLOCK_EXCEPTIONS_FILE", "")
CLOCK_POLICY_VERSION: str = os.getenv("L2_CLOCK_POLICY_VERSION", "clock-v1")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] snapshot_publisher: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


def _tier1_required_ids() -> List[str]:
    return get_registry().tier1_required_ids()


def _snapshot_exists(conn, clock_ts: datetime) -> Optional[str]:
    row = conn.execute(
        "SELECT snapshot_id FROM snapshots WHERE clock_ts = ?",
        (clock_ts.isoformat(),),
    ).fetchone()
    return row["snapshot_id"] if row else None


def _write_snapshot(
    conn,
    snapshot_id: str,
    clock_ts: datetime,
    quality_summary: dict,
    values: List[dict],
    *,
    dry_run: bool = False,
    forced: bool = False,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO snapshots
            (snapshot_id, clock_ts, verdict, tier1_series, tier1_pass,
             tier1_fail, tier2_series, tier2_warn, series_count, dry_run, forced)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            clock_ts.isoformat(),
            "PASS" if quality_summary["snapshot_ok"] else "FAIL",
            quality_summary["summary"]["tier1_total"],
            quality_summary["summary"]["tier1_pass"],
            quality_summary["summary"]["tier1_fail"],
            quality_summary["summary"]["tier2_total"],
            quality_summary["summary"]["tier2_warn"],
            len(values),
            1 if dry_run else 0,
            1 if forced else 0,
        ),
    )

    conn.executemany(
        """
        INSERT OR IGNORE INTO snapshot_values
            (snapshot_id, series_id, tier, group_name, obs_ts, value,
             staleness_days, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                snapshot_id,
                v["series_id"],
                v["tier"],
                v["group"],
                v["obs_ts"],
                v["value"],
                v["staleness_days"],
                v["source"],
            )
            for v in values
        ],
    )
    conn.commit()


def _list_snapshots(conn, limit: int = 10) -> None:
    rows = conn.execute(
        """
        SELECT snapshot_id, clock_ts, verdict, tier1_pass, tier1_fail,
               series_count, dry_run, forced, created_at
        FROM snapshots
        ORDER BY clock_ts DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not rows:
        log.info("No snapshots found in DB.")
        return

    log.info("=" * 80)
    log.info("Recent Snapshots (last %d)", limit)
    log.info("=" * 80)
    for r in rows:
        flags = (" [DRY-RUN]" if r["dry_run"] else "") + (" [FORCED]" if r["forced"] else "")
        log.info(
            "  %s | %s | %s | T1: %d/%d | series: %d%s",
            r["snapshot_id"],
            r["clock_ts"][:19],
            r["verdict"],
            r["tier1_pass"],
            r["tier1_pass"] + r["tier1_fail"],
            r["series_count"],
            flags,
        )
    log.info("=" * 80)


def _run_quality_gate(conn, clock) -> dict:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from quality_gate import run_quality_gate
        return run_quality_gate(conn, clock)
    except ImportError:
        log.warning("quality_gate.py not importable — running minimal inline check.")
        return _minimal_quality_check(conn, clock)


def _minimal_quality_check(conn, clock) -> dict:
    aligned = align_snapshot_state(conn, clock)
    aligned_by_id = {v.series_id: v for v in aligned.values}
    aligned_payload = build_snapshot_values_payload(aligned)

    failures = []
    tier1 = get_registry().tier1_series()

    for s in tier1:
        aligned_value = aligned_by_id.get(s["series_id"])
        if aligned_value is None:
            failures.append({"series_id": s["series_id"], "reason": "no data by clock_ts"})
            continue

        staleness = aligned_value.staleness_days
        if staleness > s["staleness_days"]:
            failures.append(
                {
                    "series_id": s["series_id"],
                    "reason": f"stale: {staleness}d > {s['staleness_days']}d threshold",
                }
            )

    return {
        "snapshot_ok": len(failures) == 0,
        "blocking_failures": failures,
        "tier2_warnings": [],
        "summary": {
            "tier1_total": len(tier1),
            "tier1_pass": len(tier1) - len(failures),
            "tier1_fail": len(failures),
            "tier2_total": 0,
            "tier2_warn": 0,
        },
        "alignment_summary": {
            "aligned_series": len(aligned.values),
            "missing_series": aligned.missing_series,
        },
        "aligned_payload": aligned_payload,
    }


def _extract_aligned_payload(conn, clock, quality: dict) -> tuple[list[dict], list[str]]:
    """
    Reuse the aligned payload from the quality report when available.
    Fall back to direct alignment only if the report does not expose it.
    """
    values = quality.get("aligned_payload")
    if values is not None:
        missing = quality.get("alignment_summary", {}).get("missing_series", [])
        return values, missing

    log.warning("Quality report did not expose aligned payload; falling back to direct alignment.")
    aligned = align_snapshot_state(conn, clock)
    return build_snapshot_values_payload(aligned), aligned.missing_series


def compute_snapshot_id(clock_ts: datetime, values: List[dict]) -> str:
    payload = f"clock_ts={clock_ts.isoformat()}\n"
    for v in sorted(values, key=lambda x: x["series_id"]):
        payload += (
            f"{v['series_id']}="
            f"{v['obs_ts']}:{v['value']:.6f}:"
            f"{v['as_of_ts']}:{v['revision_seq']}\n"
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_snapshot_json(
    path: str,
    snapshot_id: str,
    clock,
    run_ts: datetime,
    quality: dict,
    values: List[dict],
    missing: List[str],
    *,
    dry_run: bool = False,
    forced: bool = False,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    tier1_values = [v for v in values if v["tier"] == 1]
    tier2_values = [v for v in values if v["tier"] == 2]

    by_group: Dict[str, list] = {}
    for v in values:
        by_group.setdefault(v["group"], []).append(v)

    output = {
        "snapshot_id": snapshot_id,
        "clock_ts": clock.clock_ts.isoformat(),
        "clock_date": clock.clock_date.isoformat(),
        "verdict": "PASS" if quality["snapshot_ok"] else "FAIL",
        "forced": forced,
        "dry_run": dry_run,
        "clock_meta": clock.to_dict(),
        "tier1_series": {
            v["series_id"]: {
                "obs_ts": v["obs_ts"],
                "value": v["value"],
                "staleness_days": v["staleness_days"],
                "source": v["source"],
                "group": v["group"],
                "as_of_ts": v["as_of_ts"],
                "revision_seq": v["revision_seq"],
            }
            for v in tier1_values
        },
        "tier2_series": {
            v["series_id"]: {
                "obs_ts": v["obs_ts"],
                "value": v["value"],
                "staleness_days": v["staleness_days"],
                "source": v["source"],
                "group": v["group"],
                "as_of_ts": v["as_of_ts"],
                "revision_seq": v["revision_seq"],
            }
            for v in tier2_values
        },
        "missing_series": missing,
        "run_ts": run_ts.isoformat(),
        "published_at": run_ts.isoformat(),
        "series_count": len(values),
        "quality_summary": quality["summary"],
        "values_by_group": by_group,
        "values": {
            v["series_id"]: {
                "obs_ts": v["obs_ts"],
                "value": v["value"],
                "staleness_days": v["staleness_days"],
                "tier": v["tier"],
                "source": v["source"],
                "group": v["group"],
                "as_of_ts": v["as_of_ts"],
                "revision_seq": v["revision_seq"],
            }
            for v in values
        },
    }

    with open(p, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    log.info("Snapshot JSON written to: %s", p)


def print_snapshot_report(snapshot_id: str, clock, values: List[dict], dry_run: bool) -> None:
    log.info("=" * 68)
    log.info("SNAPSHOT REPORT%s", " [DRY-RUN]" if dry_run else "")
    log.info("  snapshot_id: %s", snapshot_id)
    log.info("  clock_ts:    %s", clock.clock_ts.isoformat())
    log.info("=" * 68)

    current_group = None
    for v in values:
        if v["group"] != current_group:
            current_group = v["group"]
            log.info("  --- %s ---", current_group.upper())

        log.info(
            "  T%d %-30s obs=%-12s val=%-12.4f stale=%dd",
            v["tier"],
            v["series_id"],
            v["obs_ts"],
            v["value"],
            v["staleness_days"],
        )

    log.info("=" * 68)
    log.info("  Series included: %d", len(values))
    log.info("  snapshot_id:     %s", snapshot_id)
    if dry_run:
        log.info("  [DRY-RUN] Nothing written to DB or JSON.")
    log.info("=" * 68)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 Snapshot Publisher — governed by layer2.clock and layer2.alignment."
    )
    p.add_argument("--clock-date", type=str, default=None, help="Override clock date YYYY-MM-DD. Use for replays.")
    p.add_argument("--dry-run", action="store_true", help="Run full pipeline but do NOT write to DB or JSON.")
    p.add_argument("--force", action="store_true", help="Gate still runs — FAIL does not block. FOR TESTING ONLY.")
    p.add_argument("--list", action="store_true", help="List recent snapshots and exit.")
    p.add_argument("--db", type=str, default=DB_PATH, help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--snapshot-path", type=str, default=SNAPSHOT_JSON_PATH, help=f"JSON output path (default: {SNAPSHOT_JSON_PATH}).")
    p.add_argument("--timezone", type=str, default=CLOCK_TIMEZONE, help=f"Clock timezone (default: {CLOCK_TIMEZONE}).")
    p.add_argument("--cut-hour", type=int, default=CLOCK_CUT_HOUR, help=f"Clock cut hour (default: {CLOCK_CUT_HOUR}).")
    p.add_argument("--cut-minute", type=int, default=CLOCK_CUT_MINUTE, help=f"Clock cut minute (default: {CLOCK_CUT_MINUTE}).")
    p.add_argument("--cut-second", type=int, default=CLOCK_CUT_SECOND, help=f"Clock cut second (default: {CLOCK_CUT_SECOND}).")
    p.add_argument("--exceptions-file", type=str, default=CLOCK_EXCEPTIONS_FILE or None, help="Optional calendar exceptions JSON file.")
    p.add_argument("--policy-version", type=str, default=CLOCK_POLICY_VERSION, help=f"Clock policy version (default: {CLOCK_POLICY_VERSION}).")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        conn = get_connection(args.db, with_snapshot_tables=True)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1

    if args.list:
        _list_snapshots(conn)
        return 0

    policy = get_default_policy(
        timezone_name=args.timezone,
        cut_hour=args.cut_hour,
        cut_minute=args.cut_minute,
        cut_second=args.cut_second,
        exceptions_path=args.exceptions_file,
        policy_version=args.policy_version,
    )
    clock = get_engine_clock(args.clock_date, policy=policy)
    run_ts = datetime.now(tz=timezone.utc)

    log.info(
        "Snapshot publisher starting | run_ts=%s | clock_ts=%s | dry_run=%s | force=%s",
        run_ts.isoformat(),
        clock.clock_ts.isoformat(),
        args.dry_run,
        args.force,
    )

    existing_id = _snapshot_exists(conn, clock.clock_ts)
    if existing_id and not args.dry_run:
        log.info("Snapshot already exists for %s: %s", clock.clock_date, existing_id)
        log.info("Use --dry-run to preview or choose a different --clock-date.")
        return 0

    forced = args.force

    log.info("Running quality gate...")
    quality = _run_quality_gate(conn, clock)

    if not quality["snapshot_ok"]:
        if forced:
            log.warning(
                "--force flag set: quality gate FAILED but proceeding anyway. Snapshot will be marked forced=True."
            )
            for f in quality["blocking_failures"]:
                log.warning("  WOULD BLOCK: %s — %s", f["series_id"], f["reason"])
        else:
            log.error("Quality gate FAILED — snapshot BLOCKED.")
            for f in quality["blocking_failures"]:
                log.error("  BLOCKING: %s — %s", f["series_id"], f["reason"])
            return 1
    else:
        log.info(
            "Quality gate PASSED — %d/%d Tier-1 series fresh.",
            quality["summary"]["tier1_pass"],
            quality["summary"]["tier1_total"],
        )
        if forced:
            log.warning("--force flag set but gate passed — snapshot marked forced=True anyway.")

    log.info("Reusing aligned point-in-time values from quality gate report...")
    values, missing = _extract_aligned_payload(conn, clock, quality)

    if missing:
        log.warning("Missing series (excluded from snapshot): %s", missing)

    if not values:
        log.error("No values read — cannot publish empty snapshot.")
        return 1

    tier1_expected = _tier1_required_ids()
    tier1_got = [v["series_id"] for v in values if v["tier"] == 1]
    tier1_missing = [s for s in tier1_expected if s not in tier1_got]

    if tier1_missing and not forced:
        log.error(
            "Tier-1 completeness FAIL — %d Tier-1 series missing from snapshot: %s",
            len(tier1_missing),
            tier1_missing,
        )
        return 1

    snapshot_id = compute_snapshot_id(clock.clock_ts, values)
    log.info("snapshot_id: %s", snapshot_id)
    print_snapshot_report(snapshot_id, clock, values, args.dry_run)

    if args.dry_run:
        log.info("[DRY-RUN] Skipping DB write and JSON write.")
    else:
        _write_snapshot(
            conn,
            snapshot_id,
            clock.clock_ts,
            quality,
            values,
            dry_run=False,
            forced=forced,
        )
        log.info("Snapshot written to DB.")
        write_snapshot_json(
            args.snapshot_path,
            snapshot_id,
            clock,
            run_ts,
            quality,
            values,
            missing,
            dry_run=False,
            forced=forced,
        )

    log.info("=" * 50)
    log.info("Snapshot publisher complete.")
    log.info("  snapshot_id: %s", snapshot_id)
    log.info("  run_ts:      %s", run_ts.isoformat())
    log.info("  clock_ts:    %s", clock.clock_ts.isoformat())
    log.info("  series:      %d", len(values))
    log.info("  forced:      %s", forced)
    if not args.dry_run:
        log.info("  DB:          written")
        log.info("  JSON:        %s", args.snapshot_path)
    log.info("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
