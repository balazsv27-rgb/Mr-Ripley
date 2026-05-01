# layer2/alignment.py
"""
Deterministic point-in-time alignment for Layer-2 snapshot building.

Purpose
-------
For each required snapshot series, select the latest valid observation known by
`clock_ts`, enforcing:

    obs_ts   <= clock_ts.date()
    as_of_ts <= clock_ts

Tie-breaking is deterministic:

    ORDER BY obs_ts DESC, as_of_ts DESC, revision_seq DESC

This version implements the missing *set-based* SQL alignment query for the
snapshot builder, rather than issuing one query per series.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.clock import get_default_policy, get_engine_clock, EngineClock  # noqa: E402
from layer2.db import get_connection, read_aligned_snapshot_rows  # noqa: E402
from layer2.config.registry import get_registry  # noqa: E402

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

CLOCK_TIMEZONE: str = os.getenv("L2_CLOCK_TIMEZONE", "UTC")
CLOCK_CUT_HOUR: int = int(os.getenv("L2_CLOCK_CUT_HOUR", "22"))
CLOCK_CUT_MINUTE: int = int(os.getenv("L2_CLOCK_CUT_MINUTE", "0"))
CLOCK_CUT_SECOND: int = int(os.getenv("L2_CLOCK_CUT_SECOND", "0"))
CLOCK_EXCEPTIONS_FILE: str = os.getenv("L2_CLOCK_EXCEPTIONS_FILE", "")
CLOCK_POLICY_VERSION: str = os.getenv("L2_CLOCK_POLICY_VERSION", "clock-v1")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] alignment: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlignedSeriesValue:
    series_id: str
    description: str
    tier: int
    group: str
    blocks_snapshot: bool
    obs_ts: Optional[date]
    as_of_ts: Optional[datetime]
    revision_seq: Optional[int]
    value: Optional[float]
    source: Optional[str]
    staleness_days: Optional[int]
    revision_risk: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_id": self.series_id,
            "description": self.description,
            "tier": self.tier,
            "group": self.group,
            "blocks_snapshot": self.blocks_snapshot,
            "obs_ts": self.obs_ts.isoformat() if self.obs_ts else None,
            "as_of_ts": self.as_of_ts.isoformat() if self.as_of_ts else None,
            "revision_seq": self.revision_seq,
            "value": self.value,
            "source": self.source,
            "staleness_days": self.staleness_days,
            "revision_risk": self.revision_risk,
        }


@dataclass(frozen=True)
class AlignmentResult:
    clock_date: date
    clock_ts: datetime
    values: List[AlignedSeriesValue]
    missing_series: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clock_date": self.clock_date.isoformat(),
            "clock_ts": self.clock_ts.isoformat(),
            "series_count": len(self.values),
            "missing_series": self.missing_series,
            "values": [v.to_dict() for v in self.values],
        }

    def values_by_series_id(self) -> Dict[str, Dict[str, Any]]:
        return {v.series_id: v.to_dict() for v in self.values}


def _snapshot_series() -> List[dict]:
    return get_registry().snapshot_series()


def _required_series_tuples(series_cfgs: List[dict]) -> List[tuple[str, str, int, str, int]]:
    return [
        (
            cfg["series_id"],
            cfg["description"],
            int(cfg["tier"]),
            cfg["group"],
            1 if cfg["blocks_snapshot"] else 0,
        )
        for cfg in series_cfgs
    ]


def align_snapshot_state(conn: sqlite3.Connection, clock: EngineClock) -> AlignmentResult:
    """
    Align all snapshot series to the governed clock timestamp using one SQL query.
    """
    series_cfgs = _snapshot_series()
    if not series_cfgs:
        return AlignmentResult(clock.clock_date, clock.clock_ts, [], [])

    revision_risk_map = {cfg["series_id"]: bool(cfg.get("revision_risk", False)) for cfg in series_cfgs}

    rows = read_aligned_snapshot_rows(conn, _required_series_tuples(series_cfgs), clock.clock_ts)

    aligned_values: List[AlignedSeriesValue] = []
    missing_series: List[str] = []

    for row in rows:
        obs_ts = _coerce_date(row["obs_ts"]) if row["obs_ts"] is not None else None
        as_of_ts = _coerce_datetime(row["as_of_ts"]) if row["as_of_ts"] is not None else None
        value = float(row["value"]) if row["value"] is not None else None
        revision_seq = int(row["revision_seq"]) if row["revision_seq"] is not None else None
        source = str(row["source"]) if row["source"] is not None else None
        staleness_days = (clock.clock_date - obs_ts).days if obs_ts is not None else None
        sid = str(row["series_id"])

        aligned = AlignedSeriesValue(
            series_id=sid,
            description=str(row["description"]),
            tier=int(row["tier"]),
            group=str(row["group_name"]),
            blocks_snapshot=bool(row["blocks_snapshot"]),
            obs_ts=obs_ts,
            as_of_ts=as_of_ts,
            revision_seq=revision_seq,
            value=value,
            source=source,
            staleness_days=staleness_days,
            revision_risk=revision_risk_map.get(sid, False),
        )

        if obs_ts is None:
            missing_series.append(aligned.series_id)
        else:
            aligned_values.append(aligned)

    return AlignmentResult(clock.clock_date, clock.clock_ts, aligned_values, sorted(missing_series))


def build_snapshot_values_payload(result: AlignmentResult) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for v in result.values:
        payload.append(
            {
                "series_id": v.series_id,
                "tier": v.tier,
                "group": v.group,
                "obs_ts": v.obs_ts.isoformat() if v.obs_ts else None,
                "value": v.value,
                "staleness_days": v.staleness_days,
                "source": v.source,
                "as_of_ts": v.as_of_ts.isoformat() if v.as_of_ts else None,
                "revision_seq": v.revision_seq,
                "revision_risk": v.revision_risk,
            }
        )
    return payload


def build_wide_state(result: AlignmentResult) -> Dict[str, float]:
    return {v.series_id: v.value for v in result.values if v.value is not None}


def render_alignment_sql_preview(clock: EngineClock) -> str:
    series_cfgs = _snapshot_series()
    tuples = _required_series_tuples(series_cfgs)
    value_rows = []
    for sid, desc, tier, group_name, blocks_snapshot in tuples:
        esc = desc.replace("'", "''")
        value_rows.append(f"('{sid}', '{esc}', {tier}, '{group_name}', {blocks_snapshot})")
    values_sql = ",\n        ".join(value_rows)
    return f"""
WITH required_series(series_id, description, tier, group_name, blocks_snapshot) AS (
    VALUES
        {values_sql}
),
eligible AS (
    SELECT
        o.series_id,
        o.obs_ts,
        o.as_of_ts,
        o.value,
        o.revision_seq,
        o.source
    FROM observations o
    JOIN required_series r
      ON r.series_id = o.series_id
    WHERE o.obs_ts <= '{clock.clock_date.isoformat()}'
      AND o.as_of_ts <= '{clock.clock_ts.isoformat()}'
),
ranked AS (
    SELECT
        e.*,
        ROW_NUMBER() OVER (
            PARTITION BY e.series_id
            ORDER BY
                e.obs_ts DESC,
                e.as_of_ts DESC,
                e.revision_seq DESC
        ) AS rn
    FROM eligible e
)
SELECT
    r.series_id,
    r.description,
    r.tier,
    r.group_name,
    r.blocks_snapshot,
    rk.obs_ts,
    rk.as_of_ts,
    rk.value,
    rk.revision_seq,
    rk.source
FROM required_series r
LEFT JOIN ranked rk
  ON r.series_id = rk.series_id
 AND rk.rn = 1
ORDER BY r.group_name, r.tier, r.series_id;
""".strip()


def print_alignment_report(result: AlignmentResult) -> None:
    log.info("=" * 72)
    log.info("ALIGNMENT REPORT")
    log.info("  clock_date: %s", result.clock_date.isoformat())
    log.info("  clock_ts:   %s", result.clock_ts.isoformat())
    log.info("=" * 72)
    current_group = None
    for v in result.values:
        if v.group != current_group:
            current_group = v.group
            log.info("  --- %s ---", current_group.upper())
        log.info(
            "  T%d %-30s obs=%-12s as_of=%-25s rev=%-3d val=%-12.6f stale=%dd",
            v.tier,
            v.series_id,
            v.obs_ts.isoformat() if v.obs_ts else "None",
            v.as_of_ts.isoformat() if v.as_of_ts else "None",
            v.revision_seq if v.revision_seq is not None else -1,
            v.value if v.value is not None else float("nan"),
            v.staleness_days if v.staleness_days is not None else -1,
        )
    if result.missing_series:
        log.warning("Missing series: %s", result.missing_series)
    else:
        log.info("Missing series: none")
    log.info("=" * 72)
    log.info("  included series: %d", len(result.values))
    log.info("  missing series:  %d", len(result.missing_series))
    log.info("=" * 72)


def _coerce_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Cannot coerce {type(value)!r} to date: {value!r}")


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Cannot coerce {type(value)!r} to datetime: {value!r}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Layer-2 deterministic alignment for snapshot building.")
    p.add_argument("--clock-date", type=str, default=None, help="Override governed clock date YYYY-MM-DD.")
    p.add_argument("--db", type=str, default=DB_PATH, help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--timezone", type=str, default=CLOCK_TIMEZONE, help=f"Clock timezone (default: {CLOCK_TIMEZONE}).")
    p.add_argument("--cut-hour", type=int, default=CLOCK_CUT_HOUR, help=f"Clock cut hour (default: {CLOCK_CUT_HOUR}).")
    p.add_argument("--cut-minute", type=int, default=CLOCK_CUT_MINUTE, help=f"Clock cut minute (default: {CLOCK_CUT_MINUTE}).")
    p.add_argument("--cut-second", type=int, default=CLOCK_CUT_SECOND, help=f"Clock cut second (default: {CLOCK_CUT_SECOND}).")
    p.add_argument("--exceptions-file", type=str, default=CLOCK_EXCEPTIONS_FILE or None, help="Optional calendar exceptions JSON file.")
    p.add_argument("--policy-version", type=str, default=CLOCK_POLICY_VERSION, help=f"Clock policy version (default: {CLOCK_POLICY_VERSION}).")
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    p.add_argument("--show-sql", action="store_true", help="Print the set-based SQL alignment query preview.")
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
    if args.show_sql:
        print(render_alignment_sql_preview(clock))
        return 0
    conn = get_connection(args.db)
    result = align_snapshot_state(conn, clock)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print_alignment_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
