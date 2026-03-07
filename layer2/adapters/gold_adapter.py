"""
gold_adapter.py
---------------
Layer-2 ingestion adapter for Gold price proxy (XAUUSD).

Role in architecture:
    Tier-1 daily series — PRIMARY asset state for gold-first MarketState.
    series_id: "gold_price_proxy"
    A missing or stale gold price = no snapshot published (fail-closed).

Source strategy (priority order):
    1. Local JSON file (gold_xauusd_stooq_2014_yesterday.json) — bulk history
    2. gold-api.com (XAU/USD spot) — primary live source, free, no API key, stdlib only
    3. Yahoo Finance (GC=F gold futures) — fallback, requires yfinance
    4. Stooq (^xauusd) — last-resort fallback

Schema, connection, and upsert all come from layer2.db.
Series metadata (staleness threshold, tier, group) comes from layer2.config.registry.

Usage:
    python layer2/adapters/gold_adapter.py --load-json FRED/2014GOLD/gold_xauusd_stooq_2014_yesterday.json --live
    python layer2/adapters/gold_adapter.py --live --backfill-days 5
    python layer2/adapters/gold_adapter.py --dry-run --load-json FRED/2014GOLD/gold_xauusd_stooq_2014_yesterday.json
    python layer2/adapters/gold_adapter.py --staleness-check-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Layer-2 shared modules
# ---------------------------------------------------------------------------

# Allow running as a script from repo root or from layer2/adapters/
_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.adapters.v0.db import get_connection, upsert_observations, filter_new_rows, latest_obs_date, count_rows  # noqa: E402
from layer2.config.registry import get_registry  # noqa: E402
from layer2.adapters.v0.clock import get_latest_completed_clock  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID: str = "gold_price_proxy"
STOOQ_TICKER: str = "^xauusd"
YAHOO_TICKER: str = "GC=F"        # gold futures — fallback only
GOLD_API_URL: str = "https://api.gold-api.com/price/XAU"  # free, no key, real-time spot
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] gold_adapter: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


def _series_cfg() -> dict:
    """Return the registry entry for gold_price_proxy."""
    return get_registry().get(SERIES_ID)


# ---------------------------------------------------------------------------
# Source A: Local JSON file
# ---------------------------------------------------------------------------

def load_from_json(json_path: str) -> List[Tuple[date, float, str]]:
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    log.info("Loading gold prices from local JSON: %s", path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected a list in JSON, got {type(data).__name__}")

    results = []
    skipped = 0
    for row in data:
        try:
            obs_date = date.fromisoformat(row["date"])
            close_val = float(row["close"])
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
        results[0][1], results[-1][1],
    )
    return results


# ---------------------------------------------------------------------------
# Source B: gold-api.com (free, no key, real-time spot)
# ---------------------------------------------------------------------------

def fetch_goldapi_live(start: date, end: date) -> List[Tuple[date, float, str]]:
    """
    Fetch today's spot price from gold-api.com.
    This endpoint returns only the current price — not a date range —
    so it is used to fill in dates from start to end (inclusive of today).
    Only called when the date range includes today or yesterday.
    """
    log.debug("Fetching spot gold from gold-api.com ...")
    try:
        req = urllib.request.Request(
            GOLD_API_URL,
            headers={"User-Agent": "Mr-Ripley-L2/1.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.load(resp)
    except Exception as exc:
        raise RuntimeError(f"gold-api.com fetch failed: {exc}") from exc

    price = data.get("price")
    if not price or float(price) <= 0:
        raise ValueError(f"gold-api.com returned no valid price: {data!r}")

    price = float(price)

    # The API returns today's live price. We assign it to every missing
    # trading date in [start, end] — typically just yesterday / today.
    results = []
    current = start
    today = date.today()
    while current <= min(end, today):
        if current.weekday() < 5:  # Mon-Fri only
            results.append((current, price, "goldapi_com"))
        current += timedelta(days=1)

    if not results:
        raise ValueError("gold-api.com: no weekdays in requested range.")

    log.info("gold-api.com: price=%.2f, assigned to %d date(s) (%s -> %s).",
             price, len(results), results[0][0], results[-1][0])
    return results


# ---------------------------------------------------------------------------
# Source C: Yahoo Finance GC=F futures (fallback)
# ---------------------------------------------------------------------------

def fetch_yahoo_live(start: date, end: date) -> List[Tuple[date, float, str]]:
    """Fetch gold futures (GC=F) from Yahoo Finance. Fallback only."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")

    log.debug("Fetching gold from Yahoo Finance %s (%s -> %s).", YAHOO_TICKER, start, end)
    ticker = yf.Ticker(YAHOO_TICKER)
    df = ticker.history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
    )
    if df.empty:
        raise ValueError(f"Yahoo Finance returned empty DataFrame for {YAHOO_TICKER}.")

    results = []
    for idx, row in df.iterrows():
        obs_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        close_val = float(row["Close"])
        if close_val > 0:
            results.append((obs_date, close_val, "yahoo_gcf"))

    if not results:
        raise ValueError("Yahoo Finance yielded no valid gold rows.")
    log.info("Yahoo GC=F: fetched %d gold rows (%s -> %s).",
             len(results), results[0][0], results[-1][0])
    return results


# ---------------------------------------------------------------------------
# Source D: Stooq (last-resort fallback)
# ---------------------------------------------------------------------------

def fetch_stooq_live(start: date, end: date) -> List[Tuple[date, float, str]]:
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

    date_idx  = header.index("date")
    close_idx = header.index("close")

    results = []
    for line in lines[1:]:
        parts = line.split(",")
        try:
            obs_date  = date.fromisoformat(parts[date_idx])
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
# Build observation rows
# ---------------------------------------------------------------------------

def build_obs_rows(
    raw: List[Tuple[date, float, str]],
    ingestion_ts: datetime,
) -> List[Tuple]:
    """Convert raw (date, close, source) to DB row tuples. as_of_ts = 21:00 UTC."""
    rows = []
    for obs_date, close_val, source in raw:
        as_of = datetime(obs_date.year, obs_date.month, obs_date.day,
                         21, 0, 0, tzinfo=timezone.utc)
        rows.append((SERIES_ID, obs_date, as_of, close_val, 0, source))
    return rows


# ---------------------------------------------------------------------------
# Staleness check (uses registry threshold)
# ---------------------------------------------------------------------------

def check_staleness(conn, clock_ts: date) -> dict:
    cfg = _series_cfg()
    threshold = cfg["staleness_days"]
    latest = latest_obs_date(conn, SERIES_ID)
    if latest is None:
        return {
            "series_id": SERIES_ID,
            "tier": cfg["tier"],
            "latest_obs_ts": None,
            "staleness_days": None,
            "data_ok": False,
            "blocks_snapshot": cfg["blocks_snapshot"],
            "reason": "no observations found",
        }
    staleness = (clock_ts - latest).days
    ok = staleness <= threshold
    return {
        "series_id": SERIES_ID,
        "tier": cfg["tier"],
        "latest_obs_ts": latest.isoformat(),
        "staleness_days": staleness,
        "data_ok": ok,
        "blocks_snapshot": not ok,
        "reason": "fresh" if ok else f"stale ({staleness}d > {threshold}d threshold)",
    }


# ---------------------------------------------------------------------------
# Batch hash
# ---------------------------------------------------------------------------

def compute_batch_hash(rows: List[Tuple]) -> str:
    payload = "|".join(
        f"{r[1]}:{r[3]:.4f}" for r in sorted(rows, key=lambda x: x[1])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 Gold price adapter — XAUUSD daily close."
    )
    p.add_argument("--load-json", type=str, default=None,
                   help="Path to local JSON file.")
    p.add_argument("--live", action="store_true",
                   help="Fetch latest rows from Stooq/Yahoo after JSON backfill.")
    p.add_argument("--backfill-days", type=int, default=5,
                   help="Days to fetch in live mode (default: 5).")
    p.add_argument("--db", type=str, default=DB_PATH,
                   help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch and parse but do NOT write to DB.")
    p.add_argument("--staleness-check-only", action="store_true",
                   help="Print staleness report only — no fetch.")
    p.add_argument("--full-reload", action="store_true",
                   help="Re-ingest all rows even if already in DB.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    clock = get_latest_completed_clock()
    today = clock.clock_date
    yesterday = today

    conn = get_connection(args.db)

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
            all_raw.extend(load_from_json(args.load_json))
        except Exception as exc:
            log.error("JSON load failed: %s", exc)
            return 2

    # Step 2: Live fetch — three-source cascade (no API key required for primary)
    #   B: gold-api.com spot (free, no key, stdlib only)  ← primary
    #   C: Yahoo Finance GC=F (requires yfinance)         ← fallback 1
    #   D: Stooq ^xauusd                                  ← fallback 2
    if args.live:
        end = yesterday
        start = end - timedelta(days=max(0, args.backfill_days - 1))
        live_raw: List[Tuple[date, float, str]] = []
        last_exc: Optional[Exception] = None

        for fetch_fn, label in [
            (lambda s, e: fetch_goldapi_live(s, e),  "gold-api.com"),
            (lambda s, e: fetch_yahoo_live(s, e),    "Yahoo GC=F"),
            (lambda s, e: fetch_stooq_live(s, e),    "Stooq"),
        ]:
            try:
                live_raw = fetch_fn(start, end)
                break
            except Exception as exc:
                log.warning("%s failed: %s", label, exc)
                last_exc = exc

        if not live_raw:
            log.error("All live sources failed. Last error: %s", last_exc)
        else:
            all_raw.extend(live_raw)
            log.info("Live fetch added %d rows.", len(live_raw))

    if not all_raw:
        log.error("No gold data collected from any source.")
        return 3

    # Deduplicate by date
    deduped = {}
    for obs_date, close_val, source in all_raw:
        deduped[obs_date] = (obs_date, close_val, source)
    all_raw = sorted(deduped.values(), key=lambda x: x[0])
    log.info("After dedup: %d unique gold rows (%s -> %s).",
             len(all_raw), all_raw[0][0], all_raw[-1][0])

    all_rows = build_obs_rows(all_raw, ingestion_ts)
    rows_to_write = (
        all_rows if args.full_reload
        else filter_new_rows(conn, SERIES_ID, all_rows)
    )

    if not rows_to_write:
        log.info("No new rows to write — DB is already up to date.")
    else:
        batch_hash = compute_batch_hash(rows_to_write)
        log.info("Batch hash: %s | rows to write: %d", batch_hash, len(rows_to_write))
        written = upsert_observations(conn, rows_to_write, dry_run=args.dry_run)
        if not args.dry_run:
            log.info("Wrote %d gold price observation(s) to DB.", written)

    quality = check_staleness(conn, clock_ts=today)
    status = "PASS" if quality["data_ok"] else "FAIL"
    log.info(
        "Staleness [%s] (Tier-1 BLOCKS snapshot if FAIL): "
        "latest=%s, staleness=%sd, reason=%s",
        status, quality["latest_obs_ts"], quality["staleness_days"], quality["reason"],
    )
    if not quality["data_ok"]:
        log.warning("Gold price is STALE — snapshot publishing will be blocked.")
        return 4

    log.info("Gold adapter completed. Total rows in DB: %d.", count_rows(conn, SERIES_ID))
    return 0


if __name__ == "__main__":
    sys.exit(main())
