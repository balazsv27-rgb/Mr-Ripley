"""
fred_loader.py
--------------
Layer-2 ingestion adapter for all FRED series.

Role in architecture:
    Pulls daily and monthly FRED observations into the observations table.
    Same schema as move_adapter, gold_adapter, gld_holdings_adapter.

Series loaded:
    Daily (Tier-1):
        DFII10, DFII5, DGS10, DGS2, DGS5
        T10YIE, T5YIE, T5YIFR
        DFF, EFFR
        DTWEXBGS, DTWEXM, DTWEXO, TWEXB
        VIXCLS, SP500

    Monthly (Tier-2):
        CPILFESL, FEDFUNDS, PCEPI, PCU2122212122210

Usage:
    python layer2/adapters/fred_loader.py --backfill-days 30
    python layer2/adapters/fred_loader.py --full-history
    python layer2/adapters/fred_loader.py --series DGS10 DFII10 --backfill-days 90
    python layer2/adapters/fred_loader.py --dry-run --backfill-days 5
    python layer2/adapters/fred_loader.py --status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
API_KEY_PATH: str = os.getenv("L2_FRED_KEY_PATH", ".secrets/fred_api_key.txt")
FRED_BASE_URL: str = "https://api.stlouisfed.org/fred/series/observations"
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")
RATE_LIMIT_DELAY: float = 0.5  # seconds between API calls (FRED limit: 120/min)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] fred_loader: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Series definitions
# ---------------------------------------------------------------------------

# as_of_ts hour (UTC) for each series:
# Daily series: 21:00 UTC (FRED EOD release)
# Monthly series: 21:00 UTC on release date (we use obs date + 21h as proxy)

SERIES_CONFIG: Dict[str, dict] = {
    # --- Tier-1 Daily: Real yields ---
    "DFII10": {
        "description": "10Y TIPS real yield",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2003-01-02",
    },
    "DFII5": {
        "description": "5Y TIPS real yield",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2003-01-02",
    },
    # --- Tier-1 Daily: Nominal yields ---
    "DGS10": {
        "description": "10Y Treasury nominal yield",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    "DGS2": {
        "description": "2Y Treasury nominal yield",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    "DGS5": {
        "description": "5Y Treasury nominal yield",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    # --- Tier-1 Daily: Breakeven inflation ---
    "T10YIE": {
        "description": "10Y breakeven inflation",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2003-01-02",
    },
    "T5YIE": {
        "description": "5Y breakeven inflation",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2003-01-02",
    },
    "T5YIFR": {
        "description": "5Y/5Y forward inflation",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2003-01-02",
    },
    # --- Tier-1 Daily: Policy rate ---
    "DFF": {
        "description": "Effective fed funds rate (daily)",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    "EFFR": {
        "description": "NY Fed EFFR",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    # --- Tier-1 Daily: USD ---
    "DTWEXBGS": {
        "description": "Broad trade-weighted USD index (goods)",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2006-01-02",
    },
    "DTWEXM": {
        "description": "USD vs major currencies (discontinued 2019)",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    "DTWEXO": {
        "description": "USD vs other partners (discontinued 2019)",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    "TWEXB": {
        "description": "Broad USD index goods+services (discontinued 2020)",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    # --- Tier-1 Daily: Risk/stress ---
    "VIXCLS": {
        "description": "VIX equity implied volatility",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2005-01-03",
    },
    "SP500": {
        "description": "S&P 500 index",
        "tier": 1, "frequency": "D",
        "staleness_days": 3, "blocks_snapshot": True,
        "full_history_start": "2016-02-22",  # FRED only has from 2016
    },
    # --- Tier-2 Monthly: Inflation ---
    "CPILFESL": {
        "description": "Core CPI (less food and energy)",
        "tier": 2, "frequency": "M",
        "staleness_days": 45, "blocks_snapshot": False,
        "full_history_start": "2005-01-01",
    },
    "FEDFUNDS": {
        "description": "Fed funds rate (monthly average)",
        "tier": 2, "frequency": "M",
        "staleness_days": 45, "blocks_snapshot": False,
        "full_history_start": "2005-01-01",
    },
    "PCEPI": {
        "description": "Headline PCE price index",
        "tier": 2, "frequency": "M",
        "staleness_days": 45, "blocks_snapshot": False,
        "full_history_start": "2005-01-01",
    },
    "PCU2122212122210": {
        "description": "PPI: Gold ore mining",
        "tier": 2, "frequency": "M",
        "staleness_days": 45, "blocks_snapshot": False,
        "full_history_start": "2005-01-01",
    },
}

ALL_SERIES = list(SERIES_CONFIG.keys())
DAILY_SERIES = [s for s, c in SERIES_CONFIG.items() if c["frequency"] == "D"]
MONTHLY_SERIES = [s for s, c in SERIES_CONFIG.items() if c["frequency"] == "M"]

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


def latest_obs_date(conn: sqlite3.Connection, series_id: str) -> Optional[date]:
    row = conn.execute(
        "SELECT MAX(obs_ts) AS d FROM observations WHERE series_id = ?",
        (series_id,)
    ).fetchone()
    if row and row["d"]:
        return date.fromisoformat(row["d"])
    return None


def count_rows(conn: sqlite3.Connection, series_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE series_id = ?",
        (series_id,)
    ).fetchone()
    return row["n"] if row else 0


def get_existing_dates(conn: sqlite3.Connection, series_id: str) -> set:
    rows = conn.execute(
        "SELECT obs_ts FROM observations WHERE series_id = ?",
        (series_id,)
    ).fetchall()
    return {row[0] for row in rows}


def upsert_observations(
    conn: sqlite3.Connection,
    rows: List[Tuple],
    dry_run: bool = False,
) -> int:
    if not rows:
        return 0
    if dry_run:
        log.info("[DRY-RUN] Would write %d row(s).", len(rows))
        return len(rows)
    conn.executemany(
        """
        INSERT OR REPLACE INTO observations
            (series_id, obs_ts, as_of_ts, value, revision_seq, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (str(r[0]), r[1].isoformat(), r[2].isoformat(),
             float(r[3]), int(r[4]), str(r[5]))
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

def load_api_key(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"FRED API key not found at {path}. "
            f"Create it with your key from https://fredaccount.stlouisfed.org/apikeys"
        )
    key = p.read_text(encoding="utf-8").strip()
    if not key or len(key) < 20:
        raise ValueError(f"FRED API key at {path} looks invalid: {key!r}")
    return key


# ---------------------------------------------------------------------------
# FRED API fetch
# ---------------------------------------------------------------------------

def fetch_fred_observations(
    series_id: str,
    api_key: str,
    start: date,
    end: date,
) -> List[Tuple[date, float]]:
    """
    Fetch observations from FRED API for a given series and date range.
    Returns list of (obs_date, value) tuples. Missing values (.) are skipped.
    """
    url = (
        f"{FRED_BASE_URL}"
        f"?series_id={series_id}"
        f"&observation_start={start.isoformat()}"
        f"&observation_end={end.isoformat()}"
        f"&api_key={api_key}"
        f"&file_type=json"
        f"&sort_order=asc"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mr-Ripley-L2/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"FRED HTTP error {e.code} for {series_id}: {e.reason}")
    except Exception as exc:
        raise RuntimeError(f"FRED fetch failed for {series_id}: {exc}")

    observations = data.get("observations", [])
    results = []
    for obs in observations:
        val_str = obs.get("value", ".")
        if val_str == "." or not val_str:
            continue  # FRED uses "." for missing values
        try:
            obs_date = date.fromisoformat(obs["date"])
            value = float(val_str)
            results.append((obs_date, value))
        except (KeyError, ValueError):
            continue

    return results


# ---------------------------------------------------------------------------
# Build observation rows
# ---------------------------------------------------------------------------

def build_obs_rows(
    series_id: str,
    raw: List[Tuple[date, float]],
    existing_dates: set,
    full_reload: bool = False,
) -> List[Tuple]:
    rows = []
    for obs_date, value in raw:
        if not full_reload and obs_date.isoformat() in existing_dates:
            continue
        as_of = datetime(
            obs_date.year, obs_date.month, obs_date.day,
            21, 0, 0, tzinfo=timezone.utc
        )
        rows.append((series_id, obs_date, as_of, value, 0, "fred"))
    return rows


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status(conn: sqlite3.Connection) -> None:
    today = date.today()
    log.info("=" * 65)
    log.info("FRED Series Status Report")
    log.info("=" * 65)

    for sid, cfg in SERIES_CONFIG.items():
        latest = latest_obs_date(conn, sid)
        count = count_rows(conn, sid)

        if latest is None:
            status = "NO DATA"
            staleness = "N/A"
        else:
            days = (today - latest).days
            staleness = f"{days}d"
            if days <= cfg["staleness_days"]:
                status = "PASS"
            else:
                status = "FAIL" if cfg["blocks_snapshot"] else "WARN"

        tier = f"T{cfg['tier']}"
        freq = cfg["frequency"]
        log.info(
            "  %-25s %s %s | rows=%-6d latest=%-12s staleness=%-5s [%s]",
            sid, tier, freq, count,
            latest.isoformat() if latest else "none",
            staleness, status
        )
    log.info("=" * 65)


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_series(
    conn: sqlite3.Connection,
    api_key: str,
    series_list: List[str],
    start: date,
    end: date,
    dry_run: bool = False,
    full_reload: bool = False,
) -> Dict[str, int]:
    results = {}
    total = len(series_list)

    for i, sid in enumerate(series_list, 1):
        cfg = SERIES_CONFIG.get(sid)
        if not cfg:
            log.warning("Unknown series: %s — skipping.", sid)
            continue

        log.info("[%d/%d] Fetching %s (%s) from %s to %s ...",
                 i, total, sid, cfg["description"], start, end)

        try:
            raw = fetch_fred_observations(sid, api_key, start, end)
        except Exception as exc:
            log.error("  FAILED: %s", exc)
            results[sid] = -1
            time.sleep(RATE_LIMIT_DELAY)
            continue

        if not raw:
            log.info("  No observations returned (may be weekend/holiday gap).")
            results[sid] = 0
            time.sleep(RATE_LIMIT_DELAY)
            continue

        existing = set() if full_reload else get_existing_dates(conn, sid)
        rows = build_obs_rows(sid, raw, existing, full_reload)

        new_count = len(rows)
        if new_count == 0:
            log.info("  Already up to date (%d obs returned, 0 new).", len(raw))
        else:
            written = upsert_observations(conn, rows, dry_run=dry_run)
            latest = max(r[1] for r in rows)
            log.info("  Wrote %d new rows | total returned: %d | latest: %s",
                     written, len(raw), latest)

        results[sid] = new_count
        time.sleep(RATE_LIMIT_DELAY)  # be polite to FRED API

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 FRED observation loader — pulls all target series into DB."
    )
    p.add_argument(
        "--series", nargs="+", default=None,
        help="Specific series IDs to load (default: all). E.g. --series DGS10 DFII10"
    )
    p.add_argument(
        "--backfill-days", type=int, default=5,
        help="Number of days to look back (default: 5). Use with daily EOD job."
    )
    p.add_argument(
        "--full-history", action="store_true",
        help="Load full history from each series' configured start date."
    )
    p.add_argument(
        "--full-reload", action="store_true",
        help="Re-ingest all rows even if already in DB (use for corrections)."
    )
    p.add_argument(
        "--start-date", type=str, default=None,
        help="Start date YYYY-MM-DD (overrides --backfill-days and --full-history)."
    )
    p.add_argument(
        "--end-date", type=str, default=None,
        help="End date YYYY-MM-DD (default: today)."
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse but do NOT write to DB."
    )
    p.add_argument(
        "--status", action="store_true",
        help="Print status report for all series and exit."
    )
    p.add_argument(
        "--db", type=str, default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH})."
    )
    p.add_argument(
        "--api-key-path", type=str, default=API_KEY_PATH,
        help=f"Path to FRED API key file (default: {API_KEY_PATH})."
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = get_connection(args.db)

    # Status report only
    if args.status:
        print_status(conn)
        return 0

    # Load API key
    try:
        api_key = load_api_key(args.api_key_path)
        log.info("FRED API key loaded from %s", args.api_key_path)
    except Exception as exc:
        log.error("Cannot load API key: %s", exc)
        return 1

    # Determine series list
    series_list = args.series if args.series else ALL_SERIES

    # Validate series names
    unknown = [s for s in series_list if s not in SERIES_CONFIG]
    if unknown:
        log.error("Unknown series IDs: %s", unknown)
        log.error("Valid series: %s", ALL_SERIES)
        return 1

    # Determine date range
    today = date.today()
    end = date.fromisoformat(args.end_date) if args.end_date else today

    if args.start_date:
        # Use explicit start date for all series
        results_all = {}
        start = date.fromisoformat(args.start_date)
        log.info("Loading %d series | range: %s -> %s | dry_run: %s",
                 len(series_list), start, end, args.dry_run)
        results_all = load_series(
            conn, api_key, series_list, start, end,
            dry_run=args.dry_run, full_reload=args.full_reload
        )
    elif args.full_history:
        # Each series uses its own configured start date
        log.info("Loading FULL HISTORY for %d series | end: %s | dry_run: %s",
                 len(series_list), end, args.dry_run)
        results_all = {}
        for sid in series_list:
            cfg = SERIES_CONFIG[sid]
            start = date.fromisoformat(cfg["full_history_start"])
            log.info("--- %s: full history from %s ---", sid, start)
            r = load_series(
                conn, api_key, [sid], start, end,
                dry_run=args.dry_run, full_reload=args.full_reload
            )
            results_all.update(r)
    else:
        # Rolling backfill
        start = end - timedelta(days=args.backfill_days)
        log.info("Loading %d series | range: %s -> %s | dry_run: %s",
                 len(series_list), start, end, args.dry_run)
        results_all = load_series(
            conn, api_key, series_list, start, end,
            dry_run=args.dry_run, full_reload=args.full_reload
        )

    # Summary
    success = [s for s, n in results_all.items() if n >= 0]
    failed = [s for s, n in results_all.items() if n < 0]
    total_new = sum(n for n in results_all.values() if n > 0)

    log.info("=" * 50)
    log.info("FRED loader complete.")
    log.info("  Series attempted: %d", len(results_all))
    log.info("  Successful:       %d", len(success))
    log.info("  Failed:           %d", len(failed))
    log.info("  New rows written: %d", total_new)
    if failed:
        log.warning("  Failed series: %s", failed)
    log.info("=" * 50)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
