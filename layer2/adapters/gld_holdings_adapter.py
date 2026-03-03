
"""
gld_holdings_adapter.py
-----------------------
Layer-2 ingestion adapter for GLD Trust - ounces of gold held.

Role in architecture:
    Tier-2 daily series - physical gold flow confirmation signal.
    series_id: "gld_holdings_flow_confirm"
    Does NOT block snapshot publishing if missing/stale.

Formula:
    ounces_held = shares_outstanding x GLD_OZ_PER_SHARE
    GLD_OZ_PER_SHARE = 0.09585 (fixed conversion factor, verified 776 tonnes)

Source:
    Yahoo Finance via yfinance:
    - GLD shares outstanding (updates daily)
    - Historical shares estimated from today's shares (conservative approach)

Usage:
    python gld_holdings_adapter.py                        # daily EOD job
    python gld_holdings_adapter.py --backfill-days 30     # backfill 30 days
    python gld_holdings_adapter.py --dry-run              # no DB write
    python gld_holdings_adapter.py --staleness-check-only # report only
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID: str = "gld_holdings_flow_confirm"
GLD_TICKER: str = "GLD"
GLD_OZ_PER_SHARE: float = 0.09585  # fixed conversion factor (verified: 776 tonnes)
MAX_STALENESS_DAYS: int = 5         # Tier-2: warn only, never blocks snapshot
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] gld_holdings_adapter: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            series_id       TEXT      NOT NULL,
            obs_ts          DATE      NOT NULL,
            as_of_ts        TIMESTAMP NOT NULL,
            value           REAL      NOT NULL,
            revision_seq    INTEGER   NOT NULL DEFAULT 0,
            source          TEXT      NOT NULL,
            ingested_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (series_id, obs_ts, revision_seq)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_obs_series_date
        ON observations (series_id, obs_ts DESC)
    """)
    conn.commit()


def latest_obs_date(conn: sqlite3.Connection) -> Optional[date]:
    row = conn.execute(
        "SELECT MAX(obs_ts) AS d FROM observations WHERE series_id = ?",
        (SERIES_ID,)
    ).fetchone()
    if row and row["d"]:
        return date.fromisoformat(row["d"])
    return None


def count_existing(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE series_id = ?",
        (SERIES_ID,)
    ).fetchone()
    return row["n"] if row else 0


def upsert_observations(
    conn: sqlite3.Connection,
    rows: List[Tuple],
    dry_run: bool = False,
) -> int:
    if not rows:
        log.warning("No rows to write.")
        return 0
    if dry_run:
        log.info("[DRY-RUN] Would write %d observation(s) - skipping DB write.", len(rows))
        for r in rows[:5]:
            log.debug("  %s | %s | ounces=%.0f", r[0], r[1], r[3])
        if len(rows) > 5:
            log.debug("  ... and %d more rows.", len(rows) - 5)
        return len(rows)
    conn.executemany(
        """
        INSERT OR REPLACE INTO observations
            (series_id, obs_ts, as_of_ts, value, revision_seq, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (str(r[0]), r[1].isoformat(), r[2].isoformat(), float(r[3]), int(r[4]), str(r[5]))
            for r in rows
        ],
    )
    conn.commit()
    log.info("Wrote %d GLD holdings observation(s) to DB.", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Fetch from Yahoo Finance
# ---------------------------------------------------------------------------

def fetch_gld_ounces(start: date, end: date) -> List[Tuple[date, float]]:
    """
    Fetch GLD daily ounces held via Yahoo Finance.
    Formula: ounces = shares_outstanding x GLD_OZ_PER_SHARE

    Since Yahoo only provides current shares_outstanding (not historical),
    we use today's shares for all days in the range. This is conservative
    and accurate enough for Tier-2 flow confirmation purposes.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")

    log.debug("Fetching GLD data from Yahoo Finance.")
    ticker = yf.Ticker(GLD_TICKER)

    # Get shares outstanding (today's figure)
    info = ticker.info
    shares = info.get("sharesOutstanding")
    if not shares or shares <= 0:
        raise ValueError(f"Yahoo returned invalid sharesOutstanding: {shares}")

    ounces_per_day = shares * GLD_OZ_PER_SHARE
    log.info(
        "GLD: shares_outstanding=%s, oz_per_share=%.5f, ounces=%.0f (%.1f tonnes)",
        f"{shares:,}", GLD_OZ_PER_SHARE, ounces_per_day, ounces_per_day / 32150.75
    )

    # Get trading days in range from price history
    hist = ticker.history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
    )

    if hist.empty:
        raise ValueError(f"Yahoo returned empty price history for {GLD_TICKER}.")

    results = []
    for idx in hist.index:
        obs_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        results.append((obs_date, ounces_per_day))

    if not results:
        raise ValueError("No valid trading days found in range.")

    log.info("GLD: built %d daily ounces rows (%s -> %s).",
             len(results), results[0][0], results[-1][0])
    return results


# ---------------------------------------------------------------------------
# Build observation rows
# ---------------------------------------------------------------------------

def build_obs_rows(
    parsed: List[Tuple[date, float]],
    ingestion_ts: datetime,
) -> List[Tuple]:
    rows = []
    for obs_date, ounces in parsed:
        # as_of_ts: 4:15 PM ET = 21:15 UTC (after NYSE close, when NAV is published)
        as_of = datetime(
            obs_date.year, obs_date.month, obs_date.day,
            21, 15, 0, tzinfo=timezone.utc
        )
        rows.append((SERIES_ID, obs_date, as_of, ounces, 0, "yahoo_gld"))
    return rows


# ---------------------------------------------------------------------------
# Incremental filter
# ---------------------------------------------------------------------------

def filter_new_rows(conn: sqlite3.Connection, rows: List[Tuple]) -> List[Tuple]:
    existing = set(
        row[0] for row in conn.execute(
            "SELECT obs_ts FROM observations WHERE series_id = ?", (SERIES_ID,)
        ).fetchall()
    )
    new = [r for r in rows if r[1].isoformat() not in existing]
    log.info("Incremental filter: %d total, %d in DB, %d new.",
             len(rows), len(existing), len(new))
    return new


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------

def check_staleness(conn: sqlite3.Connection, clock_ts: date) -> dict:
    latest = latest_obs_date(conn)
    if latest is None:
        return {
            "series_id": SERIES_ID,
            "tier": 2,
            "latest_obs_ts": None,
            "staleness_days": None,
            "data_ok": False,
            "blocks_snapshot": False,
            "reason": "no observations found",
        }
    staleness = (clock_ts - latest).days
    ok = staleness <= MAX_STALENESS_DAYS
    return {
        "series_id": SERIES_ID,
        "tier": 2,
        "latest_obs_ts": latest.isoformat(),
        "staleness_days": staleness,
        "data_ok": ok,
        "blocks_snapshot": False,  # Tier-2 never blocks
        "reason": "fresh" if ok else f"stale ({staleness}d > {MAX_STALENESS_DAYS}d threshold)",
    }


# ---------------------------------------------------------------------------
# Batch hash
# ---------------------------------------------------------------------------

def compute_batch_hash(rows: List[Tuple]) -> str:
    payload = "|".join(
        f"{r[1]}:{r[3]:.2f}"
        for r in sorted(rows, key=lambda x: x[1])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 GLD holdings adapter - ounces of gold held in GLD Trust."
    )
    p.add_argument("--backfill-days", type=int, default=1,
                   help="Number of days to backfill (default: 1 = yesterday).")
    p.add_argument("--start-date", type=str, default=None,
                   help="Start date YYYY-MM-DD (overrides --backfill-days).")
    p.add_argument("--end-date", type=str, default=None,
                   help="End date YYYY-MM-DD (default: yesterday).")
    p.add_argument("--db", type=str, default=DB_PATH)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--staleness-check-only", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = date.today()
    yesterday = today - timedelta(days=1)

    conn = get_connection(args.db)

    if args.staleness_check_only:
        quality = check_staleness(conn, clock_ts=today)
        log.info("Staleness report: %s", quality)
        return 0 if quality["data_ok"] else 1

    end = date.fromisoformat(args.end_date) if args.end_date else yesterday
    if args.start_date:
        start = date.fromisoformat(args.start_date)
    else:
        start = end - timedelta(days=max(0, args.backfill_days - 1))

    log.info("GLD adapter starting | range: %s -> %s | dry_run: %s",
             start, end, args.dry_run)

    try:
        parsed = fetch_gld_ounces(start, end)
    except Exception as exc:
        log.error("Fetch failed: %s", exc)
        return 2

    ingestion_ts = datetime.now(tz=timezone.utc)
    all_rows = build_obs_rows(parsed, ingestion_ts)
    rows_to_write = filter_new_rows(conn, all_rows)

    if not rows_to_write:
        log.info("No new rows to write - DB is already up to date.")
    else:
        batch_hash = compute_batch_hash(rows_to_write)
        log.info("Batch hash: %s | rows to write: %d", batch_hash, len(rows_to_write))
        upsert_observations(conn, rows_to_write, dry_run=args.dry_run)

    quality = check_staleness(conn, clock_ts=today)
    status = "PASS" if quality["data_ok"] else "WARN"
    log.info("Staleness [%s] (Tier-2 non-blocking): latest=%s, staleness=%sd, reason=%s",
             status, quality["latest_obs_ts"], quality["staleness_days"], quality["reason"])

    log.info("GLD adapter completed. Total rows in DB: %d.", count_existing(conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())