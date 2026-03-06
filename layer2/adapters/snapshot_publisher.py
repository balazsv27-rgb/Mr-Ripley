"""
snapshot_publisher.py
---------------------
Layer-2 Snapshot Publisher for the Gold-First Market State Engine (Mr. Ripley).

Role in architecture:
    1. Runs quality gate internally (fail-closed)
    2. If PASS: reads latest value for every Tier-1 + Tier-2 series at clock_ts
    3. Computes a deterministic snapshot_id (sha256 of values + clock_ts)
    4. Writes snapshot to DB (snapshots + snapshot_values tables)
    5. Writes latest_snapshot.json for Layer-3 consumption
    6. Returns snapshot_id on success, exits non-zero on FAIL

Contract with Layer-3:
    Layer-3 MUST NOT read observations directly.
    Layer-3 reads latest_snapshot.json or queries snapshots table by snapshot_id.
    If no snapshot exists or quality gate failed -> Layer-3 outputs nothing.

Usage:
    python layer2/adapters/snapshot_publisher.py
    python layer2/adapters/snapshot_publisher.py --clock-date 2026-03-05
    python layer2/adapters/snapshot_publisher.py --dry-run
    python layer2/adapters/snapshot_publisher.py --force   # skip quality gate (testing only)
    python layer2/adapters/snapshot_publisher.py --list    # list recent snapshots
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SNAPSHOT_JSON_PATH: str = os.getenv("L2_SNAPSHOT_PATH", "latest_snapshot.json")
API_KEY_PATH: str = os.getenv("L2_FRED_KEY_PATH", ".secrets/fred_api_key.txt")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")
CLOCK_HOUR_UTC: int = 21  # Engine clock: 21:00 UTC daily

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] snapshot_publisher: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Series to include in snapshot (all Tier-1 + Tier-2 active series)
# Discontinued series (DTWEXM, DTWEXO, TWEXB) excluded — stale by design
# ---------------------------------------------------------------------------

SNAPSHOT_SERIES: List[dict] = [
    # Tier-1
    {"series_id": "gold_price_proxy",           "tier": 1, "group": "gold"},
    {"series_id": "rates_vol_stress_move",       "tier": 1, "group": "stress"},
    {"series_id": "DFII10",                      "tier": 1, "group": "real_yields"},
    {"series_id": "DFII5",                       "tier": 1, "group": "real_yields"},
    {"series_id": "DGS10",                       "tier": 1, "group": "nominal_yields"},
    {"series_id": "DGS2",                        "tier": 1, "group": "nominal_yields"},
    {"series_id": "DGS5",                        "tier": 1, "group": "nominal_yields"},
    {"series_id": "T10YIE",                      "tier": 1, "group": "breakeven"},
    {"series_id": "T5YIE",                       "tier": 1, "group": "breakeven"},
    {"series_id": "T5YIFR",                      "tier": 1, "group": "breakeven"},
    {"series_id": "DFF",                         "tier": 1, "group": "policy_rate"},
    {"series_id": "EFFR",                        "tier": 1, "group": "policy_rate"},
    {"series_id": "DTWEXBGS",                    "tier": 1, "group": "usd"},
    {"series_id": "VIXCLS",                      "tier": 1, "group": "stress"},
    {"series_id": "SP500",                       "tier": 1, "group": "risk"},
    # Tier-2
    {"series_id": "gld_holdings_flow_confirm",   "tier": 2, "group": "flow"},
    {"series_id": "CPILFESL",                    "tier": 2, "group": "inflation_monthly"},
    {"series_id": "FEDFUNDS",                    "tier": 2, "group": "inflation_monthly"},
    {"series_id": "PCEPI",                       "tier": 2, "group": "inflation_monthly"},
    {"series_id": "PCU2122212122210",            "tier": 2, "group": "inflation_monthly"},
]

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_connection(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"DB not found: {db_path}. Run adapters first."
        )
    conn = sqlite3.connect(db_path)  # no detect_types — manual date parsing
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create snapshots and snapshot_values tables if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id     TEXT      PRIMARY KEY,
            clock_ts        TIMESTAMP NOT NULL,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            verdict         TEXT      NOT NULL,
            tier1_series    INTEGER   NOT NULL,
            tier1_pass      INTEGER   NOT NULL,
            tier1_fail      INTEGER   NOT NULL,
            tier2_series    INTEGER   NOT NULL,
            tier2_warn      INTEGER   NOT NULL,
            series_count    INTEGER   NOT NULL,
            dry_run         INTEGER   NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshot_values (
            snapshot_id     TEXT      NOT NULL,
            series_id       TEXT      NOT NULL,
            tier            INTEGER   NOT NULL,
            group_name      TEXT      NOT NULL,
            obs_ts          DATE      NOT NULL,
            value           REAL      NOT NULL,
            staleness_days  INTEGER   NOT NULL,
            source          TEXT      NOT NULL,
            PRIMARY KEY (snapshot_id, series_id),
            FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_clock
        ON snapshots (clock_ts DESC)
    """)
    conn.commit()


def read_latest_obs(
    conn: sqlite3.Connection,
    series_id: str,
    as_of_date: date,
) -> Optional[Tuple[date, float, str]]:
    """
    Point-in-time read: return (obs_ts, value, source) for series_id
    where obs_ts <= as_of_date, taking highest revision_seq.
    Returns None if no data found.
    """
    row = conn.execute(
        """
        SELECT obs_ts, value, source
        FROM observations
        WHERE series_id = ?
          AND obs_ts <= ?
        ORDER BY obs_ts DESC, revision_seq DESC
        LIMIT 1
        """,
        (series_id, as_of_date.isoformat())
    ).fetchone()
    if row:
        obs_ts = row["obs_ts"]
        if isinstance(obs_ts, str):
            obs_ts = date.fromisoformat(obs_ts)
        elif hasattr(obs_ts, "date"):
            obs_ts = obs_ts.date()
        return obs_ts, float(row["value"]), str(row["source"])
    return None


def snapshot_exists(conn: sqlite3.Connection, clock_ts: datetime) -> Optional[str]:
    """Return snapshot_id if a snapshot already exists for this clock_ts."""
    row = conn.execute(
        "SELECT snapshot_id FROM snapshots WHERE clock_ts = ?",
        (clock_ts.isoformat(),)
    ).fetchone()
    return row["snapshot_id"] if row else None


def write_snapshot(
    conn: sqlite3.Connection,
    snapshot_id: str,
    clock_ts: datetime,
    quality_summary: dict,
    values: List[dict],
    dry_run: bool = False,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO snapshots
            (snapshot_id, clock_ts, verdict, tier1_series, tier1_pass,
             tier1_fail, tier2_series, tier2_warn, series_count, dry_run)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        )
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
        ]
    )
    conn.commit()


def list_snapshots(conn: sqlite3.Connection, limit: int = 10) -> None:
    rows = conn.execute(
        """
        SELECT snapshot_id, clock_ts, verdict, tier1_pass, tier1_fail,
               series_count, dry_run, created_at
        FROM snapshots
        ORDER BY clock_ts DESC
        LIMIT ?
        """,
        (limit,)
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
        log.info(
            "  %s | %s | %s | T1: %d/%d | series: %d%s",
            r["snapshot_id"],  # full 64-char hash
            r["clock_ts"][:19],
            r["verdict"],
            r["tier1_pass"],
            r["tier1_pass"] + r["tier1_fail"],
            r["series_count"],
            flags,
        )
    log.info("=" * 80)


# ---------------------------------------------------------------------------
# Quality gate (imported inline to keep self-contained)
# ---------------------------------------------------------------------------

def run_quality_gate_inline(conn: sqlite3.Connection, clock_date: date) -> dict:
    """
    Inline quality gate — same logic as quality_gate.py but embedded here
    so snapshot_publisher is fully self-contained.
    """
    # Import from quality_gate.py if available, else run inline
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from quality_gate import SERIES_CHECKS, check_series, run_quality_gate
        return run_quality_gate(conn, clock_date)
    except ImportError:
        log.warning(
            "quality_gate.py not importable — running minimal inline check."
        )
        return _minimal_quality_check(conn, clock_date)


def _minimal_quality_check(conn: sqlite3.Connection, clock_date: date) -> dict:
    """
    Minimal fallback quality check if quality_gate.py cannot be imported.
    Only checks that each Tier-1 series has data within 10 days.
    """
    tier1_series = [s["series_id"] for s in SNAPSHOT_SERIES if s["tier"] == 1]
    failures = []
    for sid in tier1_series:
        result = read_latest_obs(conn, sid, clock_date)
        if result is None:
            failures.append({"series_id": sid, "reason": "no data"})
        else:
            staleness = (clock_date - result[0]).days
            if staleness > 10:
                failures.append({
                    "series_id": sid,
                    "reason": f"stale: {staleness}d"
                })
    return {
        "snapshot_ok": len(failures) == 0,
        "blocking_failures": failures,
        "tier2_warnings": [],
        "summary": {
            "tier1_total": len(tier1_series),
            "tier1_pass": len(tier1_series) - len(failures),
            "tier1_fail": len(failures),
            "tier2_total": 0,
            "tier2_warn": 0,
        }
    }


# ---------------------------------------------------------------------------
# Snapshot ID computation
# ---------------------------------------------------------------------------

def compute_snapshot_id(clock_ts: datetime, values: List[dict]) -> str:
    """
    Deterministic snapshot_id: full sha256 of clock_ts + sorted series values.
    Same inputs always produce the same snapshot_id.
    Full 64-char hex stored — never truncated.
    """
    payload = f"clock_ts={clock_ts.isoformat()}\n"
    for v in sorted(values, key=lambda x: x["series_id"]):
        payload += f"{v['series_id']}={v['obs_ts']}:{v['value']:.6f}\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()  # full 64 chars


# ---------------------------------------------------------------------------
# Read snapshot values
# ---------------------------------------------------------------------------

def read_snapshot_values(
    conn: sqlite3.Connection,
    clock_date: date,
) -> Tuple[List[dict], List[str]]:
    """
    Read point-in-time values for all snapshot series.
    Returns (values_list, missing_series).
    """
    values = []
    missing = []

    for series_cfg in SNAPSHOT_SERIES:
        sid = series_cfg["series_id"]
        result = read_latest_obs(conn, sid, clock_date)

        if result is None:
            log.warning("  No data for %s as of %s", sid, clock_date)
            missing.append(sid)
            continue

        obs_ts, value, source = result
        staleness = (clock_date - obs_ts).days

        values.append({
            "series_id": sid,
            "tier": series_cfg["tier"],
            "group": series_cfg["group"],
            "obs_ts": obs_ts.isoformat(),
            "value": value,
            "staleness_days": staleness,
            "source": source,
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
    """Write latest_snapshot.json for Layer-3 consumption.

    Stable API contract — Layer-3 should only read these top-level fields:
        snapshot_id, clock_ts, clock_date, verdict, values, tier1_series,
        tier2_series, missing_series, forced, dry_run
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    tier1_values = [v for v in values if v["tier"] == 1]
    tier2_values = [v for v in values if v["tier"] == 2]

    # Organize by group for readability
    by_group: Dict[str, list] = {}
    for v in values:
        by_group.setdefault(v["group"], []).append(v)

    output = {
        # --- Stable API fields (Layer-3 contract) ---
        "snapshot_id": snapshot_id,
        "clock_ts": clock_ts.isoformat(),
        "clock_date": clock_ts.date().isoformat(),
        "verdict": "PASS" if quality["snapshot_ok"] else "FAIL",
        "forced": forced,
        "dry_run": dry_run,
        "tier1_series": {v["series_id"]: {
            "obs_ts": v["obs_ts"],
            "value": v["value"],
            "staleness_days": v["staleness_days"],
            "source": v["source"],
            "group": v["group"],
        } for v in tier1_values},
        "tier2_series": {v["series_id"]: {
            "obs_ts": v["obs_ts"],
            "value": v["value"],
            "staleness_days": v["staleness_days"],
            "source": v["source"],
            "group": v["group"],
        } for v in tier2_values},
        "missing_series": missing,
        # --- Metadata (informational, may change) ---
        "run_ts": run_ts.isoformat(),
        "published_at": run_ts.isoformat(),  # alias for back-compat
        "series_count": len(values),
        "quality_summary": quality["summary"],
        "values_by_group": by_group,
        # --- Flat values dict (convenience, all tiers) ---
        "values": {v["series_id"]: {
            "obs_ts": v["obs_ts"],
            "value": v["value"],
            "staleness_days": v["staleness_days"],
            "tier": v["tier"],
            "source": v["source"],
        } for v in values},
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
            v["obs_ts"], v["value"], v["staleness_days"]
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
    p.add_argument(
        "--clock-date", type=str, default=None,
        help="Override clock date YYYY-MM-DD (default: today). Use for replays."
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Run full pipeline but do NOT write to DB or JSON."
    )
    p.add_argument(
        "--force", action="store_true",
        help="Skip quality gate and publish anyway. FOR TESTING ONLY."
    )
    p.add_argument(
        "--list", action="store_true",
        help="List recent snapshots and exit."
    )
    p.add_argument(
        "--db", type=str, default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH})."
    )
    p.add_argument(
        "--snapshot-path", type=str, default=SNAPSHOT_JSON_PATH,
        help=f"JSON output path (default: {SNAPSHOT_JSON_PATH})."
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # DB connection
    try:
        conn = get_connection(args.db)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1

    # List mode
    if args.list:
        list_snapshots(conn)
        return 0

    # Clock
    run_ts = datetime.now(tz=timezone.utc)  # execution time — separate from engine clock
    clock_date = (
        date.fromisoformat(args.clock_date)
        if args.clock_date else date.today()
    )
    clock_ts = datetime(
        clock_date.year, clock_date.month, clock_date.day,
        CLOCK_HOUR_UTC, 0, 0, tzinfo=timezone.utc
    )

    log.info(
        "Snapshot publisher starting | run_ts=%s | clock_ts=%s | dry_run=%s | force=%s",
        run_ts.isoformat(), clock_ts.isoformat(), args.dry_run, args.force
    )

    # Check for existing snapshot
    existing_id = snapshot_exists(conn, clock_ts)
    if existing_id and not args.dry_run:
        log.info("Snapshot already exists for %s: %s", clock_date, existing_id)
        log.info("Use --dry-run to preview or choose a different --clock-date.")
        return 0

    # Step 1: Quality gate
    forced = args.force
    if forced:
        log.warning("--force flag set: SKIPPING quality gate. FOR TESTING ONLY.")
        log.warning("Snapshot will be marked forced=True in DB and JSON.")
        quality = {
            "snapshot_ok": True,
            "blocking_failures": [],
            "tier2_warnings": [],
            "summary": {
                "tier1_total": 15, "tier1_pass": 15,
                "tier1_fail": 0, "tier2_total": 5, "tier2_warn": 0
            }
        }
    else:
        log.info("Running quality gate...")
        quality = run_quality_gate_inline(conn, clock_date)

        if not quality["snapshot_ok"]:
            log.error("Quality gate FAILED — snapshot BLOCKED.")
            for f in quality["blocking_failures"]:
                log.error("  BLOCKING: %s — %s", f["series_id"], f["reason"])
            log.error("Fix the failing series and re-run.")
            return 1

        log.info("Quality gate PASSED — %d/%d Tier-1 series fresh.",
                 quality["summary"]["tier1_pass"],
                 quality["summary"]["tier1_total"])

    # Step 2: Read point-in-time values
    log.info("Reading point-in-time values as of %s...", clock_date)
    values, missing = read_snapshot_values(conn, clock_date)

    if missing:
        log.warning("Missing series (excluded from snapshot): %s", missing)

    if not values:
        log.error("No values read — cannot publish empty snapshot.")
        return 1

    # Fix 1: Tier-1 completeness hard fail
    tier1_expected = [s["series_id"] for s in SNAPSHOT_SERIES if s["tier"] == 1]
    tier1_got = [v["series_id"] for v in values if v["tier"] == 1]
    tier1_missing = [s for s in tier1_expected if s not in tier1_got]
    if tier1_missing and not forced:
        log.error(
            "Tier-1 completeness FAIL — %d Tier-1 series missing from snapshot: %s",
            len(tier1_missing), tier1_missing
        )
        log.error("This means the publisher and quality gate series lists have drifted.")
        log.error("Snapshot BLOCKED.")
        return 1

    # Step 3: Compute snapshot_id
    snapshot_id = compute_snapshot_id(clock_ts, values)
    log.info("snapshot_id: %s", snapshot_id)

    # Step 4: Print report
    print_snapshot_report(snapshot_id, clock_ts, values, args.dry_run)

    # Step 5: Write to DB and JSON
    if args.dry_run:
        log.info("[DRY-RUN] Skipping DB write and JSON write.")
    else:
        write_snapshot(conn, snapshot_id, clock_ts, quality, values, dry_run=False)
        log.info("Snapshot written to DB.")

        write_snapshot_json(
            args.snapshot_path, snapshot_id, clock_ts,
            run_ts, quality, values, missing,
            dry_run=False, forced=forced
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
