"""
fred_loader.py
--------------
Layer-2 ingestion adapter for all FRED series.

Role in architecture:
    Pulls daily and monthly FRED observations into the observations table.
    All series metadata (IDs, tiers, staleness thresholds, history start dates)
    is loaded from series_registry.json — no hardcoding here.

Schema, connection, and upsert all come from layer2.db.
Series metadata comes from layer2.config.registry.

Series loaded (driven by registry source="fred"):
    Daily Tier-1  (15): DFII10 DFII5 DGS10 DGS2 DGS5 T10YIE T5YIE T5YIFR
                        DFF EFFR DTWEXBGS VIXCLS SP500
    Daily Tier-2  (discontinued): DTWEXM DTWEXO TWEXB
    Monthly Tier-2: CPILFESL FEDFUNDS PCEPI PCU2122212122210

Usage:
    python layer2/adapters/fred_loader.py --backfill-days 5
    python layer2/adapters/fred_loader.py --full-history
    python layer2/adapters/fred_loader.py --series DGS10 DFII10 --backfill-days 90
    python layer2/adapters/fred_loader.py --dry-run --backfill-days 5
    python layer2/adapters/fred_loader.py --status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
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

from layer2.adapters.v0.db import (  # noqa: E402
    get_connection, upsert_observations,
    get_existing_dates, latest_obs_date, count_rows,
)
from layer2.config.registry import get_registry  # noqa: E402

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
# Registry views (computed once at module load)
# ---------------------------------------------------------------------------

def _fred_series_list() -> List[dict]:
    """All series from registry with source='fred'."""
    return get_registry().fred_series()


def _fred_series_ids() -> List[str]:
    return [s["series_id"] for s in _fred_series_list()]


def _fred_series_map() -> Dict[str, dict]:
    return {s["series_id"]: s for s in _fred_series_list()}


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
    key = p.read_text(encoding="utf-8-sig").strip()
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
    Fetch observations from FRED API. Missing values (.) are skipped.
    Returns list of (obs_date, value) tuples.
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

    results = []
    for obs in data.get("observations", []):
        val_str = obs.get("value", ".")
        if val_str == "." or not val_str:
            continue
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
    """
    Convert raw (date, value) pairs to DB row tuples, skipping already-stored dates
    unless full_reload=True. as_of_ts = 21:00 UTC on the observation date.
    """
    rows = []
    for obs_date, value in raw:
        if not full_reload and obs_date.isoformat() in existing_dates:
            continue
        as_of = datetime(obs_date.year, obs_date.month, obs_date.day,
                         21, 0, 0, tzinfo=timezone.utc)
        rows.append((series_id, obs_date, as_of, value, 0, "fred"))
    return rows


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status(conn) -> None:
    today = date.today()
    series_map = _fred_series_map()

    log.info("=" * 65)
    log.info("FRED Series Status Report")
    log.info("=" * 65)

    for sid, cfg in series_map.items():
        latest = latest_obs_date(conn, sid)
        c = count_rows(conn, sid)

        if latest is None:
            status = "NO DATA"
            staleness_str = "N/A"
        else:
            days = (today - latest).days
            staleness_str = f"{days}d"
            if days <= cfg["staleness_days"]:
                status = "PASS"
            elif cfg["blocks_snapshot"]:
                status = "FAIL"
            else:
                status = "WARN"

        log.info(
            "  %-25s T%d %s | rows=%-6d latest=%-12s staleness=%-5s [%s]",
            sid, cfg["tier"], cfg["frequency"], c,
            latest.isoformat() if latest else "none",
            staleness_str, status,
        )
    log.info("=" * 65)


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_series(
    conn,
    api_key: str,
    series_list: List[str],
    start: date,
    end: date,
    dry_run: bool = False,
    full_reload: bool = False,
) -> Dict[str, int]:
    """
    Fetch and store observations for a list of FRED series.
    Returns dict of {series_id: rows_new} (negative value = fetch error).
    """
    series_map = _fred_series_map()
    results: Dict[str, int] = {}
    total = len(series_list)

    for i, sid in enumerate(series_list, 1):
        cfg = series_map.get(sid)
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
        time.sleep(RATE_LIMIT_DELAY)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 FRED loader — pulls all FRED series into DB (driven by registry)."
    )
    p.add_argument("--series", nargs="+", default=None,
                   help="Specific series IDs to load (default: all FRED series from registry).")
    p.add_argument("--backfill-days", type=int, default=5,
                   help="Days to look back (default: 5). Use for daily EOD job.")
    p.add_argument("--full-history", action="store_true",
                   help="Load full history from each series' configured start date.")
    p.add_argument("--full-reload", action="store_true",
                   help="Re-ingest all rows even if already in DB (use for corrections).")
    p.add_argument("--start-date", type=str, default=None,
                   help="Start date YYYY-MM-DD (overrides --backfill-days and --full-history).")
    p.add_argument("--end-date", type=str, default=None,
                   help="End date YYYY-MM-DD (default: today).")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch and parse but do NOT write to DB.")
    p.add_argument("--status", action="store_true",
                   help="Print status report for all FRED series and exit.")
    p.add_argument("--db", type=str, default=DB_PATH,
                   help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--api-key-path", type=str, default=API_KEY_PATH,
                   help=f"Path to FRED API key file (default: {API_KEY_PATH}).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = get_connection(args.db)

    if args.status:
        print_status(conn)
        return 0

    try:
        api_key = load_api_key(args.api_key_path)
        log.info("FRED API key loaded from %s", args.api_key_path)
    except Exception as exc:
        log.error("Cannot load API key: %s", exc)
        return 1

    all_fred_ids = _fred_series_ids()

    # Validate any explicitly requested series
    if args.series:
        unknown = [s for s in args.series if s not in all_fred_ids]
        if unknown:
            log.error("Unknown or non-FRED series IDs: %s", unknown)
            log.error("Valid FRED series: %s", all_fred_ids)
            return 1
        series_list = args.series
    else:
        series_list = all_fred_ids

    today = date.today()
    end = date.fromisoformat(args.end_date) if args.end_date else today

    if args.start_date:
        start = date.fromisoformat(args.start_date)
        log.info("Loading %d series | range: %s -> %s | dry_run: %s",
                 len(series_list), start, end, args.dry_run)
        results_all = load_series(conn, api_key, series_list, start, end,
                                  dry_run=args.dry_run, full_reload=args.full_reload)

    elif args.full_history:
        log.info("Loading FULL HISTORY for %d series | end: %s | dry_run: %s",
                 len(series_list), end, args.dry_run)
        results_all: Dict[str, int] = {}
        series_map = _fred_series_map()
        for sid in series_list:
            cfg = series_map[sid]
            start = date.fromisoformat(cfg["full_history_start"])
            log.info("--- %s: full history from %s ---", sid, start)
            r = load_series(conn, api_key, [sid], start, end,
                            dry_run=args.dry_run, full_reload=args.full_reload)
            results_all.update(r)

    else:
        start = end - timedelta(days=args.backfill_days)
        log.info("Loading %d series | range: %s -> %s | dry_run: %s",
                 len(series_list), start, end, args.dry_run)
        results_all = load_series(conn, api_key, series_list, start, end,
                                  dry_run=args.dry_run, full_reload=args.full_reload)

    success = [s for s, n in results_all.items() if n >= 0]
    failed  = [s for s, n in results_all.items() if n < 0]
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
