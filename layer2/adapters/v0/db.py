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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Schema — canonical DDL
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def get_connection(db_path: str, *, with_snapshot_tables: bool = False) -> sqlite3.Connection:
    """
    Open (or create) the Layer-2 SQLite DB.

    Always creates the observations table.
    Pass with_snapshot_tables=True only from snapshot_publisher.py.

    Args:
        db_path:              Path to layer2_truth.db.
        with_snapshot_tables: If True, also creates snapshots + snapshot_values tables.

    Returns:
        sqlite3.Connection with WAL mode and foreign keys enabled.
    """
    conn = sqlite3.connect(db_path)  # no detect_types — all date parsing is explicit
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


# ---------------------------------------------------------------------------
# Truth-safe upsert
# ---------------------------------------------------------------------------

def upsert_observations(
    conn: sqlite3.Connection,
    rows: List[Tuple],
    *,
    dry_run: bool = False,
) -> int:
    """
    Write observation rows to DB using INSERT OR IGNORE (truth-safe).

    First write wins. Reruns never overwrite existing rev-0 data.
    To record a genuine FRED revision, use revision_seq=1 explicitly.

    Each row must be a tuple of:
        (series_id: str, obs_ts: date, as_of_ts: datetime,
         value: float, revision_seq: int, source: str)

    Returns:
        Number of rows submitted (regardless of how many were new).
    """
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


# ---------------------------------------------------------------------------
# Common query helpers
# ---------------------------------------------------------------------------

def latest_obs_date(conn: sqlite3.Connection, series_id: str) -> Optional[date]:
    """Return the most recent obs_ts for a series, or None if no data."""
    row = conn.execute(
        "SELECT MAX(obs_ts) AS d FROM observations WHERE series_id = ?",
        (series_id,),
    ).fetchone()
    if row and row["d"]:
        return _coerce_date(row["d"])
    return None


def latest_obs(
    conn: sqlite3.Connection,
    series_id: str,
) -> Tuple[Optional[date], Optional[float]]:
    """Return (latest_date, latest_value) or (None, None) if no data."""
    row = conn.execute(
        """
        SELECT obs_ts, value
        FROM observations
        WHERE series_id = ?
        ORDER BY obs_ts DESC, revision_seq DESC
        LIMIT 1
        """,
        (series_id,),
    ).fetchone()
    if row:
        return _coerce_date(row["obs_ts"]), float(row["value"])
    return None, None


def read_latest_as_of(
    conn: sqlite3.Connection,
    series_id: str,
    as_of_date: date,
) -> Optional[Tuple[date, float, str]]:
    """
    Point-in-time read: (obs_ts, value, source) where obs_ts <= as_of_date.
    Takes the highest revision_seq for each date. Returns None if no data.
    Used by snapshot_publisher for deterministic reads.
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
        (series_id, as_of_date.isoformat()),
    ).fetchone()
    if row:
        return _coerce_date(row["obs_ts"]), float(row["value"]), str(row["source"])
    return None


def count_rows(conn: sqlite3.Connection, series_id: str) -> int:
    """Return total observation count for a series."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE series_id = ?",
        (series_id,),
    ).fetchone()
    return row["n"] if row else 0


def get_existing_dates(conn: sqlite3.Connection, series_id: str) -> Set[str]:
    """
    Return the set of existing obs_ts values (as ISO strings) for a series.
    Always returns strings regardless of sqlite column type — safe for
    incremental filter comparisons.
    """
    rows = conn.execute(
        "SELECT obs_ts FROM observations WHERE series_id = ?",
        (series_id,),
    ).fetchall()
    return {
        r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0])
        for r in rows
    }


def filter_new_rows(
    conn: sqlite3.Connection,
    series_id: str,
    rows: List[Tuple],
) -> List[Tuple]:
    """
    Return only rows whose obs_ts is not already in the DB for this series.
    Compares as ISO strings to avoid date-vs-str type bugs.
    """
    existing = get_existing_dates(conn, series_id)
    return [r for r in rows if r[1].isoformat() not in existing]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coerce_date(value) -> date:
    """Normalise sqlite date return (str | datetime | date) to date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Cannot coerce {type(value)!r} to date: {value!r}")
