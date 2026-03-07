"""
snapshot_publisher.py
---------------------
Layer-2 Snapshot Publisher for the Gold-First Market State Engine (Mr. Ripley).

Role in architecture:
    1. Runs quality gate internally (fail-closed)
    2. If PASS: reads latest value for every snapshot series at clock_ts
    3. Computes a deterministic snapshot_id (sha256 of values + clock_ts)
    4. Writes snapshot to DB (snapshots + snapshot_values tables)
    5. Writes latest_snapshot.json for Layer-3 consumption

All series metadata (which series, tiers, groups, staleness) comes from
series_registry.json via layer2.config.registry. No hardcoded SNAPSHOT_SERIES
list here — add or remove series by editing the registry JSON.

Contract with Layer-3:
    Layer-3 MUST NOT read observations directly.
    Layer-3 reads latest_snapshot.json or queries snapshots table by snapshot_id.
    If no snapshot exists or quality gate failed -> Layer-3 outputs nothing.

Usage:
    python layer2/adapters/snapshot_publisher.py
    python layer2/adapters/snapshot_publisher.py --clock-date 2026-03-05
    python layer2/adapters/snapshot_publisher.py --dry-run
    python layer2/adapters/snapshot_publisher.py --force
    python layer2/adapters/snapshot_publisher.py --list
"""

from __future__ import annotations

import argparse
import hashlib
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

from layer2.adapters.v0.db import get_connection, read_latest_as_of  # noqa: E402
from layer2.config.registry import get_registry           # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SNAPSHOT_JSON_PATH: str = os.getenv("L2_SNAPSHOT_PATH", "latest_snapshot.json")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")
CLOCK_HOUR_UTC: int = 21

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] snapshot_publisher: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry helpers — replace the old hardcoded SNAPSHOT_SERIES list
# ---------------------------------------------------------------------------

def _snapshot_series() -> List[dict]:
    """
    Return all series to include in the snapshot, from the registry.
    This is the authoritative list — includes Tier-1 + active Tier-2
    with include_in_snapshot=True. Discontinued series excluded by registry flag.
    """
    return get_registry().snapshot_series()


def _tier1_required_ids() -> List[str]:
    """series_id list of all Tier-1 series. Used for completeness hard-fail."""
    return get_registry().tier1_required_ids()


# ---------------------------------------------------------------------------
# DB helpers (snapshot tables only — observations come from layer2.db)
# ---------------------------------------------------------------------------

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
        flags = ""
        if r["dry_run"]:
            flags += " [DRY-RUN]"
        if r["forced"]:
            flags += " [FORCED]"
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


# ---------------------------------------------------------------------------
# Quality gate (imported from quality_gate.py — self-contained fallback below)
# ---------------------------------------------------------------------------

def _run_quality_gate(conn, clock_date: date) -> dict:
    """
    Run the quality gate. Imports from quality_gate.py if available.
    Falls back to a minimal inline check so the publisher stays self-contained.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from quality_gate import run_quality_gate
        return run_quality_gate(conn, clock_date)
    except ImportError:
        log.warning("quality_gate.py not importable — running minimal inline check.")
        return _minimal_quality_check(conn, clock_date)


def _minimal_quality_check(conn, clock_date: date) -> dict:
    """
    Minimal fallback quality check using registry thresholds.
    Checks that each Tier-1 series has data within its staleness threshold.
    """
    reg = get_registry()
    tier1 = reg.tier1_series()
    failures = []

    for s in tier1:
        sid = s["series_id"]
        result = read_latest_as_of(conn, sid, clock_date)
        if result is None:
            failures.append({"series_id": sid, "reason": "no data"})
        else:
            staleness = (clock_date - result[0]).days
            threshold = s["staleness_days"]
            if staleness > threshold:
                failures.append({
                    "series_id": sid,
                    "reason": f"stale: {staleness}d > {threshold}d threshold",
                })

    return {
        "snapshot_ok": len(failures) == 0,
        "blocking_failures": failures,
        "tier2_warnings": [],
        "summary": {
            "tier1_total": len(tier1),
            "tier1_pass":  len(tier1) - len(failures),
            "tier1_fail":  len(failures),
            "tier2_total": 0,
            "tier2_warn":  0,
        },
    }


# ---------------------------------------------------------------------------
# Snapshot ID computation
# ---------------------------------------------------------------------------

def compute_snapshot_id(clock_ts: datetime, values: List[dict]) -> str:
    """
    Deterministic full 64-char sha256 of clock_ts + sorted series values.
    Same inputs always produce the same snapshot_id. Never truncated.
    """
    payload = f"clock_ts={clock_ts.isoformat()}\n"
    for v in sorted(values, key=lambda x: x["series_id"]):
        payload += f"{v['series_id']}={v['obs_ts']}:{v['value']:.6f}\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Read point-in-time snapshot values (registry-driven)
# ---------------------------------------------------------------------------

def read_snapshot_values(
    conn,
    clock_date: date,
) -> Tuple[List[dict], List[str]]:
    """
    Point-in-time read of all snapshot series using registry as the authoritative
    list. Returns (values_list, missing_series_ids).
    """
    values = []
    missing = []

    for series_cfg in _snapshot_series():
        sid = series_cfg["series_id"]
        result = read_latest_as_of(conn, sid, clock_date)

        if result is None:
            log.warning("  No data for %s as of %s", sid, clock_date)
            missing.append(sid)
            continue

        obs_ts, value, source = result
        staleness = (clock_date - obs_ts).days

        values.append({
            "series_id":     sid,
            "tier":          series_cfg["tier"],
            "group":         series_cfg["group"],
            "obs_ts":        obs_ts.isoformat(),
            "value":         value,
            "staleness_days": staleness,
            "source":        source,
        })

    return values, missing


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def write_snapshot_json(
    path: str,
    snapshot_id: str,
    clock_ts: datetime,
    run_ts: datetime,
    quality: dict,
    values: List[dict],
    missing: List[str],
    dry_run: bool = False,
    forced: bool = False,
) -> None:
    """
    Write latest_snapshot.json for Layer-3 consumption.

    Stable API contract — Layer-3 reads only these top-level fields:
        snapshot_id, clock_ts, clock_date, verdict, tier1_series,
        tier2_series, missing_series, forced, dry_run
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    tier1_values = [v for v in values if v["tier"] == 1]
    tier2_values = [v for v in values if v["tier"] == 2]

    by_group: Dict[str, list] = {}
    for v in values:
        by_group.setdefault(v["group"], []).append(v)

    output = {
        # --- Stable API fields (Layer-3 contract) ---
        "snapshot_id":  snapshot_id,
        "clock_ts":     clock_ts.isoformat(),
        "clock_date":   clock_ts.date().isoformat(),
        "verdict":      "PASS" if quality["snapshot_ok"] else "FAIL",
        "forced":       forced,
        "dry_run":      dry_run,
        "tier1_series": {
            v["series_id"]: {
                "obs_ts":        v["obs_ts"],
                "value":         v["value"],
                "staleness_days": v["staleness_days"],
                "source":        v["source"],
                "group":         v["group"],
            }
            for v in tier1_values
        },
        "tier2_series": {
            v["series_id"]: {
                "obs_ts":        v["obs_ts"],
                "value":         v["value"],
                "staleness_days": v["staleness_days"],
                "source":        v["source"],
                "group":         v["group"],
            }
            for v in tier2_values
        },
        "missing_series": missing,
        # --- Metadata (informational, may change) ---
        "run_ts":         run_ts.isoformat(),
        "published_at":   run_ts.isoformat(),
        "series_count":   len(values),
        "quality_summary": quality["summary"],
        "values_by_group": by_group,
        # --- Flat dict (convenience, all tiers) ---
        "values": {
            v["series_id"]: {
                "obs_ts":        v["obs_ts"],
                "value":         v["value"],
                "staleness_days": v["staleness_days"],
                "tier":          v["tier"],
                "source":        v["source"],
            }
            for v in values
        },
    }

    with open(p, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    log.info("Snapshot JSON written to: %s", p)


# ---------------------------------------------------------------------------
# Print snapshot report
# ---------------------------------------------------------------------------

def print_snapshot_report(
    snapshot_id: str,
    clock_ts: datetime,
    values: List[dict],
    dry_run: bool,
) -> None:
    log.info("=" * 68)
    log.info("SNAPSHOT REPORT%s", " [DRY-RUN]" if dry_run else "")
    log.info("  snapshot_id: %s", snapshot_id)
    log.info("  clock_ts:    %s", clock_ts.isoformat())
    log.info("=" * 68)

    current_group = None
    for v in values:
        if v["group"] != current_group:
            current_group = v["group"]
            log.info("  --- %s ---", current_group.upper())
        log.info(
            "  T%d %-30s obs=%-12s val=%-12.4f stale=%dd",
            v["tier"], v["series_id"],
            v["obs_ts"], v["value"], v["staleness_days"],
        )

    log.info("=" * 68)
    log.info("  Series included: %d", len(values))
    log.info("  snapshot_id:     %s", snapshot_id)
    if dry_run:
        log.info("  [DRY-RUN] Nothing written to DB or JSON.")
    log.info("=" * 68)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Layer-2 Snapshot Publisher — runs quality gate and publishes "
            "a point-in-time snapshot for Layer-3 consumption."
        )
    )
    p.add_argument("--clock-date", type=str, default=None,
                   help="Override clock date YYYY-MM-DD (default: today). Use for replays.")
    p.add_argument("--dry-run", action="store_true",
                   help="Run full pipeline but do NOT write to DB or JSON.")
    p.add_argument("--force", action="store_true",
                   help="Gate still runs — FAIL does not block. FOR TESTING ONLY.")
    p.add_argument("--list", action="store_true",
                   help="List recent snapshots and exit.")
    p.add_argument("--db", type=str, default=DB_PATH,
                   help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--snapshot-path", type=str, default=SNAPSHOT_JSON_PATH,
                   help=f"JSON output path (default: {SNAPSHOT_JSON_PATH}).")
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

    run_ts = datetime.now(tz=timezone.utc)
    clock_date = (
        date.fromisoformat(args.clock_date) if args.clock_date else date.today()
    )
    clock_ts = datetime(
        clock_date.year, clock_date.month, clock_date.day,
        CLOCK_HOUR_UTC, 0, 0, tzinfo=timezone.utc,
    )

    log.info(
        "Snapshot publisher starting | run_ts=%s | clock_ts=%s | dry_run=%s | force=%s",
        run_ts.isoformat(), clock_ts.isoformat(), args.dry_run, args.force,
    )

    # Check for existing snapshot
    existing_id = _snapshot_exists(conn, clock_ts)
    if existing_id and not args.dry_run:
        log.info("Snapshot already exists for %s: %s", clock_date, existing_id)
        log.info("Use --dry-run to preview or choose a different --clock-date.")
        return 0

    # Step 1: Quality gate — always runs, even with --force
    forced = args.force
    log.info("Running quality gate...")
    quality = _run_quality_gate(conn, clock_date)

    if not quality["snapshot_ok"]:
        if forced:
            log.warning(
                "--force flag set: quality gate FAILED but proceeding anyway. "
                "Snapshot will be marked forced=True in DB and JSON. FOR TESTING ONLY."
            )
            for f in quality["blocking_failures"]:
                log.warning("  WOULD BLOCK: %s — %s", f["series_id"], f["reason"])
        else:
            log.error("Quality gate FAILED — snapshot BLOCKED.")
            for f in quality["blocking_failures"]:
                log.error("  BLOCKING: %s — %s", f["series_id"], f["reason"])
            log.error("Fix the failing series and re-run.")
            return 1
    else:
        log.info(
            "Quality gate PASSED — %d/%d Tier-1 series fresh.",
            quality["summary"]["tier1_pass"],
            quality["summary"]["tier1_total"],
        )
        if forced:
            log.warning("--force flag set but gate passed — snapshot marked forced=True anyway.")

    # Step 2: Read point-in-time values (registry-driven)
    log.info("Reading point-in-time values as of %s...", clock_date)
    values, missing = read_snapshot_values(conn, clock_date)

    if missing:
        log.warning("Missing series (excluded from snapshot): %s", missing)

    if not values:
        log.error("No values read — cannot publish empty snapshot.")
        return 1

    # Step 3: Tier-1 completeness hard-fail (registry is the source)
    tier1_expected = _tier1_required_ids()
    tier1_got = [v["series_id"] for v in values if v["tier"] == 1]
    tier1_missing = [s for s in tier1_expected if s not in tier1_got]
    if tier1_missing and not forced:
        log.error(
            "Tier-1 completeness FAIL — %d Tier-1 series missing from snapshot: %s",
            len(tier1_missing), tier1_missing,
        )
        log.error("Snapshot BLOCKED.")
        return 1

    # Step 4: Compute snapshot_id
    snapshot_id = compute_snapshot_id(clock_ts, values)
    log.info("snapshot_id: %s", snapshot_id)

    # Step 5: Print report
    print_snapshot_report(snapshot_id, clock_ts, values, args.dry_run)

    # Step 6: Write to DB and JSON
    if args.dry_run:
        log.info("[DRY-RUN] Skipping DB write and JSON write.")
    else:
        _write_snapshot(conn, snapshot_id, clock_ts, quality, values,
                        dry_run=False, forced=forced)
        log.info("Snapshot written to DB.")

        write_snapshot_json(
            args.snapshot_path, snapshot_id, clock_ts,
            run_ts, quality, values, missing,
            dry_run=False, forced=forced,
        )

    log.info("=" * 50)
    log.info("Snapshot publisher complete.")
    log.info("  snapshot_id: %s", snapshot_id)
    log.info("  run_ts:      %s", run_ts.isoformat())
    log.info("  clock_ts:    %s", clock_ts.isoformat())
    log.info("  series:      %d", len(values))
    log.info("  forced:      %s", forced)
    if not args.dry_run:
        log.info("  DB:          written")
        log.info("  JSON:        %s", args.snapshot_path)
    log.info("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
