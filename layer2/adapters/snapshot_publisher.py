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

Stable API fields in snapshot JSON:
    snapshot_id     — 64-char SHA-256 hash (deterministic)
    clock_ts        — governed cut timestamp (ISO-8601, UTC)
    clock_date      — calendar date of the clock tick
    verdict         — PASS | FAIL
    forced          — True if published with --force (gate bypassed)
    dry_run         — True if --dry-run was used (not written to DB)
    guards          — hard veto conditions for Layer-3 (see layer2/constants.py)
                      data_ok is the only field Layer-2 sets authoritatively;
                      all others are stubs for Layer-3 to evaluate
    tier1_series    — dict of Tier-1 series values at clock_ts
    tier2_series    — dict of Tier-2 series values at clock_ts
    missing_series  — list of series IDs absent from aligned payload
    layer1_events   — always [] from Layer-2; forward-compatible slot for Layer-1

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

from layer2.db import get_connection, read_latest_as_of  # noqa: E402
from layer2.config.registry import get_registry           # noqa: E402
from layer2.constants import ReasonCode, build_guards     # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SNAPSHOT_JSON_PATH: str = os.getenv("L2_SNAPSHOT_PATH", "latest_snapshot.json")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")
CLOCK_HOUR_UTC: int = 22  # 22:00 UTC — per handbook §4; was 21, corrected


def _get_engine_version() -> str:
    """
    Read engine version from L2_ENGINE_VERSION env var.
    Raises RuntimeError if unset or empty — every snapshot must be version-locked.
    """
    v = os.getenv("L2_ENGINE_VERSION", "").strip()
    if not v:
        raise RuntimeError(
            "L2_ENGINE_VERSION is not set. "
            "Every snapshot must carry an engine version. "
            "Set it before publishing: export L2_ENGINE_VERSION=gold-v3.3.0"
        )
    return v


def _get_config_version() -> str:
    """
    Read config version from series_registry.json (registry_version key).
    Falls back to registry object attribute, then direct JSON read.
    Raises RuntimeError if unresolvable — every snapshot must be version-locked.
    """
    # Primary: registry singleton already loaded
    try:
        reg = get_registry()
        # Try attribute first (registry.py exposes .version)
        v = getattr(reg, "version", None)
        if v:
            return str(v)
        # Try dict-style access
        v = reg.summary().get("registry_version")
        if v:
            return str(v)
    except Exception:
        pass

    # Fallback: read the JSON file directly
    registry_path = os.getenv("L2_REGISTRY_PATH", "layer2/config/series_registry.json")
    for candidate in [
        Path(registry_path),
        Path(__file__).parent.parent / "config" / "series_registry.json",
        Path("series_registry.json"),
    ]:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                v = data.get("registry_version")
                if v:
                    return str(v)
            except Exception:
                pass

    raise RuntimeError(
        "Cannot resolve config_version: registry_version key not found in "
        "series_registry.json and L2_REGISTRY_PATH is not set or unreadable."
    )

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

def _snapshot_exists(
    conn,
    clock_ts: datetime,
    engine_version: str,
    config_version: str,
) -> Optional[str]:
    """
    Three-way dedup: same clock_ts can produce multiple valid snapshots under
    different engine or config versions (e.g. after a hotfix or registry change).
    This prevents both silent overwrites and false "already exists" blocks.
    """
    row = conn.execute(
        """
        SELECT snapshot_id FROM snapshots
        WHERE clock_ts = ? AND engine_version = ? AND config_version = ?
        """,
        (clock_ts.isoformat(), engine_version, config_version),
    ).fetchone()
    return row["snapshot_id"] if row else None


def _write_snapshot(
    conn,
    snapshot_id: str,
    clock_ts: datetime,
    engine_version: str,
    config_version: str,
    quality_summary: dict,
    values: List[dict],
    dry_run: bool = False,
    forced: bool = False,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO snapshots
            (snapshot_id, clock_ts, engine_version, config_version,
             verdict, tier1_series, tier1_pass, tier1_fail,
             tier2_series, tier2_warn, series_count, dry_run, forced)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            clock_ts.isoformat(),
            engine_version,
            config_version,
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

def compute_snapshot_id(
    clock_ts: datetime,
    engine_version: str,
    config_version: str,
    values: List[dict],
) -> str:
    """
    Deterministic 64-char SHA-256 snapshot identity hash.

    Hash payload (one line each, sorted by series_id):
        clock_ts=<ISO-8601>
        engine_version=<string>
        config_version=<string>
        <series_id>=<obs_ts>:<value:.6f>:<as_of_ts>:<revision_seq>
        ...

    Same clock_ts + same engine_version + same config_version + same aligned
    series state (obs_ts, value, as_of_ts, revision_seq) → same snapshot_id.

    Two runs with different as_of_ts values (e.g. after a late FRED revision)
    produce different snapshot_ids even for the same clock_ts — this is correct
    and intentional: "same data" means "same aligned series state."
    """
    lines = [
        f"clock_ts={clock_ts.isoformat()}",
        f"engine_version={engine_version}",
        f"config_version={config_version}",
    ]
    for v in sorted(values, key=lambda x: x["series_id"]):
        as_of = v.get("as_of_ts", "")
        rev   = v.get("revision_seq", 0)
        lines.append(
            f"{v['series_id']}={v['obs_ts']}:{v['value']:.6f}:{as_of}:{rev}"
        )
    payload = "\n".join(lines) + "\n"
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
    engine_version: str,
    config_version: str,
    quality: dict,
    values: List[dict],
    missing: List[str],
    dry_run: bool = False,
    forced: bool = False,
) -> None:
    """
    Write latest_snapshot.json for Layer-3 consumption.

    Stable API fields (Layer-3 contract — these never change without a version bump):
        snapshot_id     — 64-char SHA-256 (deterministic; includes engine+config version)
        engine_version  — value of L2_ENGINE_VERSION at publish time
        config_version  — registry_version from series_registry.json at publish time
        clock_ts        — governed cut timestamp (ISO-8601, UTC)
        clock_date      — calendar date of the clock tick
        verdict         — PASS | FAIL
        forced          — True if published with --force
        guards          — hard veto object; data_ok is Layer-2-authoritative,
                          all other fields are stubs for Layer-3 to override
        tier1_series    — dict of Tier-1 series values at clock_ts
        tier2_series    — dict of Tier-2 series values at clock_ts
        missing_series  — series IDs absent from aligned payload
        layer1_events   — always [] from Layer-2; forward-compatible Layer-1 slot

    Layer-3 MUST validate engine_version and config_version before consuming
    snapshot values. Treat any forced=True snapshot as non-compliant data.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    tier1_values = [v for v in values if v["tier"] == 1]
    tier2_values = [v for v in values if v["tier"] == 2]

    by_group: Dict[str, list] = {}
    for v in values:
        by_group.setdefault(v["group"], []).append(v)

    # Determine whether any Tier-1 series are missing from the payload
    tier1_expected = _tier1_required_ids()
    tier1_got = {v["series_id"] for v in tier1_values}
    missing_tier1 = any(sid not in tier1_got for sid in tier1_expected)

    # Build guards — Layer-2 populates data_ok; others are stubs for Layer-3
    guards = build_guards(
        snapshot_ok=quality["snapshot_ok"],
        forced=forced,
        missing_tier1=missing_tier1,
    )

    output = {
        # --- Stable API fields (Layer-3 contract) ---
        "snapshot_id":    snapshot_id,
        "engine_version": engine_version,
        "config_version": config_version,
        "clock_ts":       clock_ts.isoformat(),
        "clock_date":     clock_ts.date().isoformat(),
        "verdict":        "PASS" if quality["snapshot_ok"] else "FAIL",
        "forced":         forced,
        "dry_run":        dry_run,
        # guards — Layer-3 evaluates hard veto conditions from this object.
        # data_ok is the only field Layer-2 can authoritatively populate.
        # All other fields are stubs that Layer-3 must override.
        "guards": guards,
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
        # layer1_events — forward-compatible slot for Layer-1 event hooks.
        # Layer-1 is optional and disabled by default; Layer-2 always emits [].
        "layer1_events": [],
        # --- Metadata (informational, may change without version bump) ---
        "run_ts":          run_ts.isoformat(),
        "published_at":    run_ts.isoformat(),
        "series_count":    len(values),
        "quality_summary": quality["summary"],
        "values_by_group": by_group,
        # --- Flat convenience dict (all tiers) ---
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

    # Resolve engine_version and config_version up front — both must be present
    # before any DB connection is opened. Fail fast here, not mid-publish.
    try:
        engine_version = _get_engine_version()
        config_version = _get_config_version()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    try:
        conn = get_connection(args.db, with_snapshot_tables=True)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1

    if args.list:
        _list_snapshots(conn)
        return 0
    
    from layer2.clock import get_engine_clock
    
    run_ts = datetime.now(tz=timezone.utc)
    clock = get_engine_clock(args.clock_date)

    clock_date = clock.clock_date
    clock_ts   = clock.clock_ts
    log.info(
        "Snapshot publisher starting | run_ts=%s | clock_ts=%s | "
        "engine=%s | config=%s | dry_run=%s | force=%s",
        run_ts.isoformat(), clock_ts.isoformat(),
        engine_version, config_version,
        args.dry_run, args.force,
    )

    # Three-way dedup: clock_ts + engine_version + config_version
    existing_id = _snapshot_exists(conn, clock_ts, engine_version, config_version)
    if existing_id and not args.dry_run:
        log.info(
            "Snapshot already exists for %s / %s / %s: %s",
            clock_date, engine_version, config_version, existing_id,
        )
        log.info("Use --dry-run to preview or choose a different --clock-date.")
        return 0

    # Step 1: Quality gate — always runs, even with --force
    forced = args.force
    log.info("Running quality gate...")
    quality = _run_quality_gate(conn, clock)

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

    # Step 3: Tier-1 completeness hard-fail
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

    # Step 4: Compute snapshot_id (includes engine_version + config_version)
    snapshot_id = compute_snapshot_id(clock_ts, engine_version, config_version, values)
    log.info("snapshot_id: %s", snapshot_id)

    # Step 5: Print report
    print_snapshot_report(snapshot_id, clock_ts, values, args.dry_run)

    # Step 6: Write to DB and JSON
    if args.dry_run:
        log.info("[DRY-RUN] Skipping DB write and JSON write.")
    else:
        _write_snapshot(
            conn, snapshot_id, clock_ts,
            engine_version, config_version,
            quality, values,
            dry_run=False, forced=forced,
        )
        log.info("Snapshot written to DB.")

        write_snapshot_json(
            args.snapshot_path, snapshot_id, clock_ts, run_ts,
            engine_version, config_version,
            quality, values, missing,
            dry_run=False, forced=forced,
        )

    log.info("=" * 50)
    log.info("Snapshot publisher complete.")
    log.info("  snapshot_id:    %s", snapshot_id)
    log.info("  engine_version: %s", engine_version)
    log.info("  config_version: %s", config_version)
    log.info("  run_ts:         %s", run_ts.isoformat())
    log.info("  clock_ts:       %s", clock_ts.isoformat())
    log.info("  series:         %d", len(values))
    log.info("  forced:         %s", forced)
    if not args.dry_run:
        log.info("  DB:             written")
        log.info("  JSON:           %s", args.snapshot_path)
    log.info("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
