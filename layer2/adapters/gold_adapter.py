"""
gold_adapter.py
---------------
Layer-2 ingestion adapter for Gold price proxy (XAUUSD).

Role in architecture:
    Tier-1 daily series - PRIMARY asset state for gold-first MarketState.
    series_id: "gold_price_proxy"
    MANDATORY for M0. Missing or stale gold price = no snapshot published.

Source strategy (priority order):
    1. Local JSON file (gold_xauusd_stooq_2014_yesterday.json) - already collected
    2. Stooq live fetch (^XAUUSD) - for new daily rows after the JSON ends
    3. Yahoo Finance (GC=F gold futures) - fallback

Formula:
    Direct daily close price in USD per troy ounce.

Stored value:
    Close price in USD (e.g. 2650.50)
    series_id = "gold_price_proxy"

Usage:
    python layer2/adapters/gold_adapter.py --load-json FRED/gold_xauusd_stooq_2014_yesterday.json
    python layer2/adapters/gold_adapter.py --live --backfill-days 5
    python layer2/adapters/gold_adapter.py --load-json FRED/gold_xauusd_stooq_2014_yesterday.json --live
    python layer2/adapters/gold_adapter.py --dry-run --load-json FRED/gold_xauusd_stooq_2014_yesterday.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID: str = "gold_price_proxy"
STOOQ_TICKER: str = "^xauusd"
YAHOO_TICKER: str = "GC=F"
MAX_STALENESS_DAYS: int = 3  # Tier-1: blocks snapshot if stale
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] gold_adapter: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)  # no detect_types — date parsing handled manually
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
        d = row["d"]
        if isinstance(d, str):
            return date.fromisoformat(d)
        if hasattr(d, "date"):
            return d.date()
        return d
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
        for r in rows[:3]:
            log.info("  Sample: %s | %s | close=%.4f | source=%s", r[0], r[1], r[3], r[5])
        if len(rows) > 3:
            log.info("  ... and %d more rows.", len(rows) - 3)
        return len(rows)

    conn.executemany(
        """
        INSERT OR IGNORE INTO observations
            (series_id, obs_ts, as_of_ts, value, revision_seq, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (str(r[0]), r[1].isoformat(), r[2].isoformat(), float(r[3]), int(r[4]), str(r[5]))
            for r in rows
        ],
    )
    conn.commit()
    log.info("Wrote %d gold price observation(s) to DB.", len(rows))
    return len(rows)


def filter_new_rows(conn: sqlite3.Connection, rows: List[Tuple]) -> List[Tuple]:
    # Normalize to strings to avoid str vs date object comparison bugs
    existing = {
        r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0])
        for r in conn.execute(
            "SELECT obs_ts FROM observations WHERE series_id = ?", (SERIES_ID,)
        ).fetchall()
    }
    new = [r for r in rows if r[1].isoformat() not in existing]
    log.info("Incremental filter: %d total, %d already in DB, %d new.",
             len(rows), len(existing), len(new))
    return new


# ---------------------------------------------------------------------------
# Source A: Local JSON file
# ---------------------------------------------------------------------------

def load_from_json(json_path: str) -> List[Tuple[date, float, str]]:
    """
    Load gold prices from the local Stooq JSON file.
    Expected row format:
        {"date": "2014-01-02", "close": 1222.44, "symbol": "XAUUSD", ...}
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    log.info("Loading gold prices from local JSON: %s", path)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected a list in JSON, got {type(data).__name__}")

    results = []
    skipped = 0
    for row in data:
        try:
            obs_date = date.fromisoformat(row['date'])
            close_val = float(row['close'])
            if close_val <= 0:
                skipped += 1
                continue
            results.append((obs_date, close_val, "stooq_json"))
        except (KeyError, ValueError):
            skipped += 1
            continue

    if skipped:
        log.debug("Skipped %d invalid rows.", skipped)

    if not results:
        raise ValueError("JSON file yielded no valid gold price rows.")

    results.sort(key=lambda x: x[0])
    log.info(
        "JSON: loaded %d gold rows (%s -> %s) | first=%.2f last=%.2f",
        len(results), results[0][0], results[-1][0],
        results[0][1], results[-1][1]
    )
    return results


# ---------------------------------------------------------------------------
# Source B: Stooq live fetch
# ---------------------------------------------------------------------------

def fetch_stooq_live(start: date, end: date) -> List[Tuple[date, float, str]]:
    """Fetch XAUUSD daily closes from Stooq for a given date range."""
    url = (
        f"https://stooq.com/q/d/l/"
        f"?s={STOOQ_TICKER}"
        f"&d1={start.strftime('%Y%m%d')}"
        f"&d2={end.strftime('%Y%m%d')}"
        f"&i=d"
    )
    log.debug("Stooq URL: %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "L2-Gold-Adapter/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Stooq fetch failed: {exc}") from exc

    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    if not lines:
        raise ValueError("Stooq returned empty response.")

    header = lines[0].lower().split(",")
    if "date" not in header or "close" not in header:
        raise ValueError(f"Unexpected Stooq header: {lines[0]!r}")

    date_idx = header.index("date")
    close_idx = header.index("close")

    results = []
    for line in lines[1:]:
        parts = line.split(",")
        try:
            obs_date = date.fromisoformat(parts[date_idx])
            close_val = float(parts[close_idx])
            if close_val > 0:
                results.append((obs_date, close_val, "stooq_live"))
        except (ValueError, IndexError):
            continue

    if not results:
        raise ValueError("Stooq live fetch yielded no valid gold rows.")

    log.info("Stooq live: fetched %d rows (%s -> %s).",
             len(results), results[0][0], results[-1][0])
    return results


# ---------------------------------------------------------------------------
# Source C: Yahoo Finance fallback
# ---------------------------------------------------------------------------

def fetch_yahoo_live(start: date, end: date) -> List[Tuple[date, float, str]]:
    """Fetch gold futures (GC=F) from Yahoo Finance as fallback."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")

    log.debug("Fetching gold from Yahoo Finance GC=F (%s -> %s).", start, end)
    ticker = yf.Ticker(YAHOO_TICKER)
    df = ticker.history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
    )
    if df.empty:
        raise ValueError("Yahoo Finance returned empty DataFrame for GC=F.")

    results = []
    for idx, row in df.iterrows():
        obs_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        close_val = float(row["Close"])
        if close_val > 0:
            results.append((obs_date, close_val, "yahoo_gcf"))

    if not results:
        raise ValueError("Yahoo Finance yielded no valid gold rows.")

    log.info("Yahoo: fetched %d gold rows (%s -> %s).",
             len(results), results[0][0], results[-1][0])
    return results


# ---------------------------------------------------------------------------
# Build observation rows
# ---------------------------------------------------------------------------

def build_obs_rows(
    raw: List[Tuple[date, float, str]],
    ingestion_ts: datetime,
) -> List[Tuple]:
    """
    Convert (date, close, source) tuples into DB row tuples.
    as_of_ts = 21:00 UTC (gold market closes / FRED EOD clock)
    """
    rows = []
    for obs_date, close_val, source in raw:
        as_of = datetime(
            obs_date.year, obs_date.month, obs_date.day,
            21, 0, 0, tzinfo=timezone.utc
        )
        rows.append((SERIES_ID, obs_date, as_of, close_val, 0, source))
    return rows


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------

def check_staleness(conn: sqlite3.Connection, clock_ts: date) -> dict:
    latest = latest_obs_date(conn)
    if latest is None:
        return {
            "series_id": SERIES_ID,
            "tier": 1,
            "latest_obs_ts": None,
            "staleness_days": None,
            "data_ok": False,
            "blocks_snapshot": True,
            "reason": "no observations found",
        }
    staleness = (clock_ts - latest).days
    ok = staleness <= MAX_STALENESS_DAYS
    return {
        "series_id": SERIES_ID,
        "tier": 1,
        "latest_obs_ts": latest.isoformat(),
        "staleness_days": staleness,
        "data_ok": ok,
        "blocks_snapshot": not ok,
        "reason": "fresh" if ok else f"stale ({staleness}d > {MAX_STALENESS_DAYS}d threshold)",
    }


# ---------------------------------------------------------------------------
# Batch hash
# ---------------------------------------------------------------------------

def compute_batch_hash(rows: List[Tuple]) -> str:
    payload = "|".join(
        f"{r[1]}:{r[3]:.4f}"
        for r in sorted(rows, key=lambda x: x[1])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 Gold price adapter - XAUUSD daily close."
    )
    p.add_argument(
        "--load-json", type=str, default=None,
        help="Path to local JSON file (e.g. FRED/gold_xauusd_stooq_2014_yesterday.json)."
    )
    p.add_argument(
        "--live", action="store_true",
        help="Fetch latest rows from Stooq/Yahoo (use after JSON backfill)."
    )
    p.add_argument(
        "--backfill-days", type=int, default=5,
        help="How many days to fetch in live mode (default: 5)."
    )
    p.add_argument(
        "--db", type=str, default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH})."
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse but do NOT write to DB."
    )
    p.add_argument(
        "--staleness-check-only", action="store_true",
        help="Print staleness report only."
    )
    p.add_argument(
        "--full-reload", action="store_true",
        help="Re-ingest all rows even if already in DB."
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = date.today()
    yesterday = today - timedelta(days=1)

    conn = get_connection(args.db)

    # Staleness only mode
    if args.staleness_check_only:
        quality = check_staleness(conn, clock_ts=today)
        log.info("Staleness report: %s", quality)
        return 0 if quality["data_ok"] else 1

    if not args.load_json and not args.live:
        log.error("Must specify --load-json and/or --live. Use --help for usage.")
        return 1

    ingestion_ts = datetime.now(tz=timezone.utc)
    all_raw: List[Tuple[date, float, str]] = []

    # Step 1: Load local JSON
    if args.load_json:
        try:
            raw_json = load_from_json(args.load_json)
            all_raw.extend(raw_json)
        except Exception as exc:
            log.error("JSON load failed: %s", exc)
            return 2

    # Step 2: Live fetch for recent rows
    if args.live:
        end = yesterday
        start = end - timedelta(days=max(0, args.backfill_days - 1))

        # Try Stooq first, Yahoo as fallback
        try:
            live_raw = fetch_stooq_live(start, end)
        except Exception as stooq_exc:
            log.warning("Stooq live failed: %s — trying Yahoo.", stooq_exc)
            try:
                live_raw = fetch_yahoo_live(start, end)
            except Exception as yahoo_exc:
                log.error("All live sources failed. Stooq: %s | Yahoo: %s",
                          stooq_exc, yahoo_exc)
                live_raw = []

        if live_raw:
            all_raw.extend(live_raw)
            log.info("Live fetch added %d rows.", len(live_raw))

    if not all_raw:
        log.error("No gold data collected from any source.")
        return 3

    # Deduplicate by date (keep last seen per date)
    deduped = {}
    for obs_date, close_val, source in all_raw:
        deduped[obs_date] = (obs_date, close_val, source)
    all_raw = sorted(deduped.values(), key=lambda x: x[0])
    log.info("After dedup: %d unique gold rows (%s -> %s).",
             len(all_raw), all_raw[0][0], all_raw[-1][0])

    # Build DB rows
    all_rows = build_obs_rows(all_raw, ingestion_ts)

    # Incremental filter
    rows_to_write = all_rows if args.full_reload else filter_new_rows(conn, all_rows)

    if not rows_to_write:
        log.info("No new rows to write - DB is already up to date.")
    else:
        batch_hash = compute_batch_hash(rows_to_write)
        log.info("Batch hash: %s | rows to write: %d", batch_hash, len(rows_to_write))
        upsert_observations(conn, rows_to_write, dry_run=args.dry_run)

    # Staleness report
    quality = check_staleness(conn, clock_ts=today)
    status = "PASS" if quality["data_ok"] else "FAIL"
    log.info(
        "Staleness [%s] (Tier-1 BLOCKS snapshot if fail): "
        "latest=%s, staleness=%sd, reason=%s",
        status, quality["latest_obs_ts"],
        quality["staleness_days"], quality["reason"]
    )
    if not quality["data_ok"]:
        log.warning("Gold price is STALE - snapshot publishing will be blocked.")
        return 4

    log.info("Gold adapter completed. Total rows in DB: %d.", count_existing(conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
