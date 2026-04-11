"""
snapshot_publisher.py
---------------------
Layer-2 Snapshot Publisher for the Gold-First Market State Engine (Mr. Ripley).

Role in architecture:
    1. Runs quality gate internally (fail-closed)
    2. Reuses the exact aligned payload returned by quality_gate.py
    3. Computes a deterministic snapshot_id
    4. Writes snapshot to DB (snapshots + snapshot_values tables)
    5. Writes latest_snapshot.json for Layer-3 consumption

All series metadata (which series, tiers, groups, staleness) comes from
series_registry.json via layer2.config.registry. No hardcoded SNAPSHOT_SERIES
list here — add or remove series by editing the registry JSON.

Contract with Layer-3:
    Layer-3 MUST NOT read observations directly.
    Layer-3 reads latest_snapshot.json or queries snapshots table by snapshot_id.
    If no snapshot exists or quality gate failed -> Layer-3 outputs nothing.
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
from layer2.config.registry import get_registry          # noqa: E402
from layer2.constants import build_guards                # noqa: E402
from layer2.clock import get_engine_clock               # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SNAPSHOT_JSON_PATH: str = os.getenv("L2_SNAPSHOT_PATH", "latest_snapshot.json")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")


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
            "Set it before publishing. "
            "PowerShell: $env:L2_ENGINE_VERSION=\"gold-v3.3.0\""
        )
    return v


def _get_config_version() -> str:
    """
    Read config version from series_registry.json (registry_version key).
    Falls back to registry object attribute, then direct JSON read.
    Raises RuntimeError if unresolvable — every snapshot must be version-locked.
    """
    try:
        reg = get_registry()

        v = getattr(reg, "version", None)
        if v:
            return str(v)

        summary = reg.summary()
        v = summary.get("registry_version")
        if v:
            return str(v)
    except Exception:
        pass

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
# Registry helpers
# ---------------------------------------------------------------------------

def _tier1_required_ids() -> List[str]:
    return get_registry().tier1_required_ids()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _snapshot_exists(
    conn,
    clock_ts: datetime,
    engine_version: str,
    config_version: str,
) -> Optional[str]:
    """
    Three-way dedup: same clock_ts can produce multiple valid snapshots under
    different engine or config versions.
    """
    row = conn.execute(
        """
        SELECT snapshot_id
        FROM snapshots
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
    *,
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
               series_count, engine_version, config_version,
               dry_run, forced, created_at
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
            "  %s | %s | %s | T1: %d/%d | series: %d | eng=%s cfg=%s%s",
            r["snapshot_id"],
            r["clock_ts"][:19],
            r["verdict"],
            r["tier1_pass"],
            r["tier1_pass"] + r["tier1_fail"],
            r["series_count"],
            r["engine_version"],
            r["config_version"],
            flags,
        )
    log.info("=" * 80)


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

def _run_quality_gate(conn, clock) -> dict:
    """
    Run the quality gate with the canonical EngineClock object.
    Falls back to a minimal inline check if quality_gate.py is unavailable.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from quality_gate import run_quality_gate
        return run_quality_gate(conn, clock)
    except ImportError:
        log.warning("quality_gate.py not importable — running minimal inline check.")
        return _minimal_quality_check(conn, clock)


def _minimal_quality_check(conn, clock) -> dict:
    """
    Minimal fallback quality check using registry thresholds.
    This path exists only so the publisher remains self-contained if imports fail.
    """
    reg = get_registry()
    tier1 = reg.tier1_series()
    failures = []
    aligned_payload: List[dict] = []
    missing_series: List[str] = []

    for s in tier1:
        sid = s["series_id"]
        result = read_latest_as_of(conn, sid, clock.clock_date)

        if result is None:
            failures.append(
                {"series_id": sid, "reason": "no point-in-time data available by clock_ts"}
            )
            missing_series.append(sid)
            continue

        obs_ts, value, source = result
        staleness = (clock.clock_date - obs_ts).days
        threshold = s["staleness_days"]

        aligned_payload.append(
            {
                "series_id": sid,
                "tier": s["tier"],
                "group": s["group"],
                "obs_ts": obs_ts.isoformat(),
                "value": value,
                "staleness_days": staleness,
                "source": source,
                "as_of_ts": None,
                "revision_seq": 0,
            }
        )

        if staleness > threshold:
            failures.append(
                {
                    "series_id": sid,
                    "reason": f"stale: {staleness}d > {threshold}d threshold",
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
        "aligned_payload": aligned_payload,
        "alignment_summary": {
            "aligned_series": len(aligned_payload),
            "missing_series": missing_series,
        },
    }


# ---------------------------------------------------------------------------
# Snapshot ID
# ---------------------------------------------------------------------------

def compute_snapshot_id(
    clock_ts: datetime,
    engine_version: str,
    config_version: str,
    values: List[dict],
) -> str:
    """
    Deterministic 64-char SHA-256 snapshot identity hash.

    Hash payload:
        clock_ts=<ISO-8601>
        engine_version=<string>
        config_version=<string>
        <series_id>=<obs_ts>:<value:.6f>:<as_of_ts>:<revision_seq>
    """
    lines = [
        f"clock_ts={clock_ts.isoformat()}",
        f"engine_version={engine_version}",
        f"config_version={config_version}",
    ]

    for v in sorted(values, key=lambda x: x["series_id"]):
        as_of = v.get("as_of_ts", "") or ""
        rev = v.get("revision_seq", 0)
        lines.append(
            f"{v['series_id']}={v['obs_ts']}:{float(v['value']):.6f}:{as_of}:{rev}"
        )

    payload = "\n".join(lines) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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

    tier1_expected = _tier1_required_ids()
    tier1_got = {v["series_id"] for v in tier1_values}
    missing_tier1 = any(sid not in tier1_got for sid in tier1_expected)

    guards = build_guards(
        snapshot_ok=quality["snapshot_ok"],
        forced=forced,
        missing_tier1=missing_tier1,
    )

    output = {
        "snapshot_id": snapshot_id,
        "engine_version": engine_version,
        "config_version": config_version,
        "clock_ts": clock_ts.isoformat(),
        "clock_date": clock_ts.date().isoformat(),
        "verdict": "PASS" if quality["snapshot_ok"] else "FAIL",
        "forced": forced,
        "dry_run": dry_run,
        "guards": guards,
        "tier1_series": {
            v["series_id"]: {
                "obs_ts": v["obs_ts"],
                "value": v["value"],
                "staleness_days": v["staleness_days"],
                "source": v["source"],
                "group": v["group"],
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
            }
            for v in tier2_values
        },
        "missing_series": missing,
        "layer1_events": [],
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
                "as_of_ts": v.get("as_of_ts"),
                "revision_seq": v.get("revision_seq"),
            }
            for v in values
        },
    }

    with open(p, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    log.info("Snapshot JSON written to: %s", p)


# ---------------------------------------------------------------------------
# Report
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
            v["tier"],
            v["series_id"],
            v["obs_ts"],
            float(v["value"]),
            v["staleness_days"],
        )

    log.info("=" * 68)
    log.info("  Series included: %d", len(values))
    log.info("  snapshot_id:     %s", snapshot_id)
    if dry_run:
        log.info("  [DRY-RUN] Nothing written to DB or JSON.")
    log.info("=" * 68)


def _log_quality_gate_summary(quality: dict) -> None:
    summary = quality.get("summary", {})
    tier1_total = summary.get("tier1_total", 0)
    tier1_pass = summary.get("tier1_pass", 0)
    tier1_fail = summary.get("tier1_fail", 0)
    tier2_total = summary.get("tier2_total", 0)
    tier2_warn = summary.get("tier2_warn", 0)

    log.info(
        "Quality gate summary | Tier-1 pass=%d fail=%d total=%d | Tier-2 warn=%d total=%d",
        tier1_pass,
        tier1_fail,
        tier1_total,
        tier2_warn,
        tier2_total,
    )


def _log_next_steps_hint(quality: dict) -> None:
    failures = quality.get("blocking_failures", [])
    has_missing_pit = any(
        f.get("series_id") == "DTWEXBGS" and "no point-in-time data available" in f.get("reason", "")
        for f in failures
    )

    log.error("Next step: refresh the affected adapters, then re-run the publisher.")
    log.error(
        "Suggested order: gold_adapter.py, move_adapter.py, fred_loader.py, then snapshot_publisher.py --dry-run"
    )
    if has_missing_pit:
        log.error(
            "DTWEXBGS note: this is a missing point-in-time record at the current clock boundary, not a simple stale-value warning."
        )


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
        "--clock-date",
        type=str,
        default=None,
        help="Override clock date YYYY-MM-DD (default: today). Use for replays.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run full pipeline but do NOT write to DB or JSON.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Gate still runs — FAIL does not block. FOR TESTING ONLY.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List recent snapshots and exit.",
    )
    p.add_argument(
        "--db",
        type=str,
        default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH}).",
    )
    p.add_argument(
        "--snapshot-path",
        type=str,
        default=SNAPSHOT_JSON_PATH,
        help=f"JSON output path (default: {SNAPSHOT_JSON_PATH}).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

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

    run_ts = datetime.now(tz=timezone.utc)
    clock = get_engine_clock(args.clock_date)
    clock_date = clock.clock_date
    clock_ts = clock.clock_ts

    log.info(
        "Snapshot publisher starting | run_ts=%s | clock_ts=%s | "
        "engine=%s | config=%s | dry_run=%s | force=%s",
        run_ts.isoformat(),
        clock_ts.isoformat(),
        engine_version,
        config_version,
        args.dry_run,
        args.force,
    )

    existing_id = _snapshot_exists(conn, clock_ts, engine_version, config_version)
    if existing_id and not args.dry_run:
        log.info(
            "Snapshot already exists for %s / %s / %s: %s",
            clock_date,
            engine_version,
            config_version,
            existing_id,
        )
        log.info("Use --dry-run to preview or choose a different --clock-date.")
        return 0

    forced = args.force
    log.info("Running quality gate...")
    quality = _run_quality_gate(conn, clock)
    _log_quality_gate_summary(quality)

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
            _log_next_steps_hint(quality)
            return 1
    else:
        log.info(
            "Quality gate PASSED — %d/%d Tier-1 series fresh.",
            quality["summary"]["tier1_pass"],
            quality["summary"]["tier1_total"],
        )
        if forced:
            log.warning("--force flag set but gate passed — snapshot marked forced=True anyway.")

    log.info("Using aligned payload from quality gate...")
    values = quality.get("aligned_payload", [])
    missing = quality.get("alignment_summary", {}).get("missing_series", [])

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
        log.error("Snapshot BLOCKED.")
        return 1

    snapshot_id = compute_snapshot_id(clock_ts, engine_version, config_version, values)
    log.info("snapshot_id: %s", snapshot_id)

    print_snapshot_report(snapshot_id, clock_ts, values, args.dry_run)

    if args.dry_run:
        log.info("[DRY-RUN] Skipping DB write and JSON write.")
    else:
        _write_snapshot(
            conn,
            snapshot_id,
            clock_ts,
            engine_version,
            config_version,
            quality,
            values,
            dry_run=False,
            forced=forced,
        )
        log.info("Snapshot written to DB.")

        write_snapshot_json(
            args.snapshot_path,
            snapshot_id,
            clock_ts,
            run_ts,
            engine_version,
            config_version,
            quality,
            values,
            missing,
            dry_run=False,
            forced=forced,
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
