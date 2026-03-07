"""
layer2/db.py
------------
Canonical database layer for all Layer-2 adapters.

Single source of truth for:
  - Observations table schema (shared by every adapter)
  - Snapshots + snapshot_values table schema (publisher only)
  - Connection factory
  - Truth-safe upsert (INSERT OR IGNORE — first write wins)
  - Common query helpers

No adapter should define its own schema or write its own upsert logic.
All adapters import from this module.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import List, Optional, Set, Tuple

_DDL_OBSERVATIONS = """
CREATE TABLE IF NOT EXISTS observations (
    series_id       TEXT      NOT NULL,
    obs_ts          DATE      NOT NULL,
    as_of_ts        TIMESTAMP NOT NULL,
    value           REAL      NOT NULL,
    revision_seq    INTEGER   NOT NULL DEFAULT 0,
    source          TEXT      NOT NULL,
    ingested_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (series_id, obs_ts, revision_seq)
);
"""

_DDL_OBS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_obs_series_date
ON observations (series_id, obs_ts DESC);
"""

_DDL_SNAPSHOTS = """
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
    dry_run         INTEGER   NOT NULL DEFAULT 0,
    forced          INTEGER   NOT NULL DEFAULT 0
);
"""

_DDL_SNAPSHOTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_snapshots_clock
ON snapshots (clock_ts DESC);
"""

_DDL_SNAPSHOT_VALUES = """
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
);
"""


def get_connection(db_path: str, *, with_snapshot_tables: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    _ensure_observations(conn)
    if with_snapshot_tables:
        _ensure_snapshot_tables(conn)
    return conn


def _ensure_observations(conn: sqlite3.Connection) -> None:
    conn.execute(_DDL_OBSERVATIONS)
    conn.execute(_DDL_OBS_INDEX)
    conn.commit()


def _ensure_snapshot_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_DDL_SNAPSHOTS)
    conn.execute(_DDL_SNAPSHOTS_INDEX)
    conn.execute(_DDL_SNAPSHOT_VALUES)
    conn.commit()


def upsert_observations(conn: sqlite3.Connection, rows: List[Tuple], *, dry_run: bool = False) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)
    conn.executemany(
        """
        INSERT OR IGNORE INTO observations
            (series_id, obs_ts, as_of_ts, value, revision_seq, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                str(r[0]),
                r[1].isoformat(),
                r[2].isoformat(),
                float(r[3]),
                int(r[4]),
                str(r[5]),
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


def latest_obs_date(conn: sqlite3.Connection, series_id: str) -> Optional[date]:
    row = conn.execute(
        "SELECT MAX(obs_ts) AS d FROM observations WHERE series_id = ?",
        (series_id,),
    ).fetchone()
    if row and row["d"]:
        return _coerce_date(row["d"])
    return None


def latest_obs(conn: sqlite3.Connection, series_id: str) -> Tuple[Optional[date], Optional[float]]:
    row = conn.execute(
        """
        SELECT obs_ts, value
        FROM observations
        WHERE series_id = ?
        ORDER BY obs_ts DESC, as_of_ts DESC, revision_seq DESC
        LIMIT 1
        """,
        (series_id,),
    ).fetchone()
    if row:
        return _coerce_date(row["obs_ts"]), float(row["value"])
    return None, None


def read_latest_as_of(conn: sqlite3.Connection, series_id: str, as_of_date: date) -> Optional[Tuple[date, float, str]]:
    row = conn.execute(
        """
        SELECT obs_ts, value, source
        FROM observations
        WHERE series_id = ?
          AND obs_ts <= ?
        ORDER BY obs_ts DESC, as_of_ts DESC, revision_seq DESC
        LIMIT 1
        """,
        (series_id, as_of_date.isoformat()),
    ).fetchone()
    if row:
        return _coerce_date(row["obs_ts"]), float(row["value"]), str(row["source"])
    return None


def read_latest_as_of_ts(conn: sqlite3.Connection, series_id: str, as_of_ts: datetime) -> Optional[Tuple[date, float, str, datetime, int]]:
    """
    Point-in-time read using the full governed clock timestamp.

    Select the latest observation known by `as_of_ts`, enforcing both:
      - obs_ts <= as_of_ts.date()
      - recorded as_of_ts <= governed clock_ts

    Ties are broken deterministically by:
      obs_ts DESC, as_of_ts DESC, revision_seq DESC
    """
    row = conn.execute(
        """
        SELECT obs_ts, value, source, as_of_ts, revision_seq
        FROM observations
        WHERE series_id = ?
          AND obs_ts <= ?
          AND as_of_ts <= ?
        ORDER BY obs_ts DESC, as_of_ts DESC, revision_seq DESC
        LIMIT 1
        """,
        (series_id, as_of_ts.date().isoformat(), as_of_ts.isoformat()),
    ).fetchone()
    if row:
        return (
            _coerce_date(row["obs_ts"]),
            float(row["value"]),
            str(row["source"]),
            _coerce_datetime(row["as_of_ts"]),
            int(row["revision_seq"]),
        )
    return None


def count_rows(conn: sqlite3.Connection, series_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE series_id = ?",
        (series_id,),
    ).fetchone()
    return row["n"] if row else 0


def get_existing_dates(conn: sqlite3.Connection, series_id: str) -> Set[str]:
    rows = conn.execute(
        "SELECT obs_ts FROM observations WHERE series_id = ?",
        (series_id,),
    ).fetchall()
    return {r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]) for r in rows}


def filter_new_rows(conn: sqlite3.Connection, series_id: str, rows: List[Tuple]) -> List[Tuple]:
    existing = get_existing_dates(conn, series_id)
    return [r for r in rows if r[1].isoformat() not in existing]




def read_aligned_snapshot_rows(conn: sqlite3.Connection, required_series: List[Tuple[str, str, int, str, int]], clock_ts: datetime):
    """
    Execute the canonical set-based snapshot alignment query.

    Parameters
    ----------
    required_series:
        List of tuples: (series_id, description, tier, group_name, blocks_snapshot)
    clock_ts:
        Governed cut time.

    Returns
    -------
    sqlite3.Row list with one row per required series.
    """
    if not required_series:
        return []

    placeholders = ",\n        ".join(["(?, ?, ?, ?, ?)"] * len(required_series))
    sql = f"""
    WITH required_series(series_id, description, tier, group_name, blocks_snapshot) AS (
        VALUES
        {placeholders}
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
        WHERE o.obs_ts <= ?
          AND o.as_of_ts <= ?
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
    ORDER BY r.group_name, r.tier, r.series_id
    """
    params = []
    for rs in required_series:
        params.extend(rs)
    params.extend([clock_ts.date().isoformat(), clock_ts.isoformat()])
    return conn.execute(sql, params).fetchall()
def _coerce_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Cannot coerce {type(value)!r} to date: {value!r}")


def _coerce_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Cannot coerce {type(value)!r} to datetime: {value!r}")
