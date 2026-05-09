"""
spy_adapter.py
--------------
Layer-2 ingestion adapter for SP500_PROXY via Yahoo Finance SPY adjusted close.

Role in architecture:
    Tier-1 daily equity proxy series for long-history S&P 500 exposure.
    series_id: "SP500_PROXY"

This adapter intentionally does NOT replace the existing FRED SP500 series.
It writes a separate SP500_PROXY series sourced from SPY adjusted close data so
Layer-2 preserves source semantics and downstream systems can choose explicitly
between the official FRED index and the tradable long-history proxy.

Source:
    Yahoo Finance via yfinance, ticker: SPY
    Stored value: adjusted close proxy produced by yfinance with auto_adjust=True.
    source field: "yahoo_spy"
    as_of_ts: 21:00 UTC on observation date.

Schema, connection, and upsert all come from layer2.db.
Series metadata comes from layer2.config.registry.

Usage:
    # One-time historical backfill
    python layer2/adapters/spy_adapter.py --backfill-start 2005-01-03

    # Daily EOD top-up
    python layer2/adapters/spy_adapter.py --backfill-days 7

    # Dry-run
    python layer2/adapters/spy_adapter.py --backfill-start 2005-01-03 --dry-run

    # Staleness check only
    python layer2/adapters/spy_adapter.py --staleness-check-only
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Layer-2 shared modules
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.db import (  # noqa: E402
    count_rows,
    filter_new_rows,
    get_connection,
    latest_obs_date,
    upsert_observations,
)
from layer2.config.registry import get_registry  # noqa: E402
from layer2.clock import get_latest_completed_clock  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID: str = "SP500_PROXY"
YAHOO_TICKER: str = "SPY"
SOURCE_LABEL: str = "yahoo_spy"
DEFAULT_BACKFILL_DAYS: int = 7
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] spy_adapter: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


def _series_cfg() -> dict:
    """Return the registry entry for SP500_PROXY."""
    cfg = get_registry().get(SERIES_ID)
    if cfg is None:
        raise KeyError(
            f"series_id {SERIES_ID!r} not found in series_registry.json. "
            "Apply the SP500_PROXY registry patch before running this adapter."
        )
    return cfg


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_spy_yahoo(start: date, end: date) -> List[Tuple[date, float, str]]:
    """Fetch SPY adjusted close rows from Yahoo Finance."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:
        raise RuntimeError("yfinance is not installed. Run: pip install yfinance") from exc

    log.info("Fetching SPY adjusted close from Yahoo: %s -> %s", start, end)
    df = yf.download(
        YAHOO_TICKER,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
        interval="1d",
        auto_adjust=True,
        progress=False,
    )

    if df is None or df.empty:
        raise RuntimeError(f"Yahoo returned empty SPY history for {start} -> {end}")

    close = df["Close"] if "Close" in df.columns else None
    if close is None:
        raise RuntimeError("Yahoo SPY history missing required Close column")

    # yfinance may return a DataFrame for Close when columns are MultiIndex.
    if hasattr(close, "columns"):
        if YAHOO_TICKER in close.columns:
            close = close[YAHOO_TICKER]
        else:
            close = close.iloc[:, 0]

    results: List[Tuple[date, float, str]] = []
    for idx, value in close.items():
        obs_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        try:
            close_val = float(value)
        except (TypeError, ValueError):
            continue
        if close_val > 0:
            results.append((obs_date, close_val, SOURCE_LABEL))

    if not results:
        raise RuntimeError("Yahoo SPY fetch yielded no valid positive close values")

    results.sort(key=lambda x: x[0])
    log.info(
        "Fetched %d SPY row(s) (%s -> %s)",
        len(results),
        results[0][0],
        results[-1][0],
    )
    return results


# ---------------------------------------------------------------------------
# Build observation rows
# ---------------------------------------------------------------------------


def build_obs_rows(raw: List[Tuple[date, float, str]]) -> List[Tuple]:
    """
    Convert raw SPY data to observations table rows.

    Point-in-time convention:
        as_of_ts = 21:00 UTC on observation date.

    This matches the SP500 history-gap plan and keeps provenance explicit via
    source='yahoo_spy'. Existing SP500/FRED observations remain untouched.
    """
    rows = []
    for obs_date, close_val, source in raw:
        as_of = datetime(
            obs_date.year,
            obs_date.month,
            obs_date.day,
            21,
            0,
            0,
            tzinfo=timezone.utc,
        )
        rows.append((SERIES_ID, obs_date, as_of, close_val, 0, source))
    return rows


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------


def check_staleness(conn, clock_date: date) -> dict:
    """Check SP500_PROXY freshness against its registry threshold."""
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

    staleness = (clock_date - latest).days
    ok = staleness <= threshold
    return {
        "series_id": SERIES_ID,
        "tier": cfg["tier"],
        "latest_obs_ts": latest.isoformat(),
        "staleness_days": staleness,
        "data_ok": ok,
        "blocks_snapshot": cfg["blocks_snapshot"],
        "reason": "fresh" if ok else f"stale ({staleness}d > {threshold}d threshold)",
    }


# ---------------------------------------------------------------------------
# Batch hash
# ---------------------------------------------------------------------------


def compute_batch_hash(rows: List[Tuple]) -> str:
    payload = "|".join(
        f"{r[1]}:{float(r[3]):.6f}" for r in sorted(rows, key=lambda x: x[1])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 SP500_PROXY adapter — SPY adjusted close via Yahoo Finance."
    )
    p.add_argument(
        "--backfill-start",
        type=str,
        default=None,
        help="First date to ingest, YYYY-MM-DD. Use 2005-01-03 for full SP500_PROXY history.",
    )
    p.add_argument(
        "--backfill-days",
        type=int,
        default=DEFAULT_BACKFILL_DAYS,
        help=f"Calendar days to backfill when --backfill-start is omitted (default: {DEFAULT_BACKFILL_DAYS}).",
    )
    p.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Last date to ingest, YYYY-MM-DD (default: latest completed engine clock date).",
    )
    p.add_argument(
        "--db",
        type=str,
        default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate but do NOT write to DB.",
    )
    p.add_argument(
        "--staleness-check-only",
        action="store_true",
        help="Print staleness report only — no fetch.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    clock = get_latest_completed_clock()
    today = clock.clock_date

    conn = get_connection(args.db)

    if args.staleness_check_only:
        quality = check_staleness(conn, clock_date=today)
        status = "✓ PASS" if quality["data_ok"] else "✗ FAIL"
        log.info("Staleness check [%s]: %s", status, quality)
        return 0 if quality["data_ok"] else 1

    end = date.fromisoformat(args.end_date) if args.end_date else today
    if args.backfill_start:
        start = date.fromisoformat(args.backfill_start)
    else:
        start = end - timedelta(days=max(0, args.backfill_days - 1))

    if start > end:
        log.error("start_date %s is after end_date %s — aborting.", start, end)
        return 1

    log.info(
        "SPY adapter starting | range: %s -> %s | db: %s | dry_run: %s",
        start,
        end,
        args.db,
        args.dry_run,
    )

    try:
        raw = fetch_spy_yahoo(start, end)
    except RuntimeError as exc:
        log.error("SPY fetch failed: %s", exc)
        return 2

    rows = build_obs_rows(raw)
    batch_hash = compute_batch_hash(rows)
    log.info("Batch hash (SHA-256): %s | rows: %d", batch_hash, len(rows))

    rows_to_write = filter_new_rows(conn, SERIES_ID, rows)

    if not rows_to_write:
        log.info("No new rows to write — DB is already up to date.")
    else:
        log.info("Writing %d new SP500_PROXY row(s).", len(rows_to_write))
        written = upsert_observations(conn, rows_to_write, dry_run=args.dry_run)
        if args.dry_run:
            log.info("[DRY-RUN] Would write %d SP500_PROXY observation(s).", written)
        else:
            log.info("Wrote %d SP500_PROXY observation(s) to DB.", written)

    if not args.dry_run:
        quality = check_staleness(conn, clock_date=today)
        status = "✓ PASS" if quality["data_ok"] else "✗ FAIL"
        log.info(
            "Staleness check [%s]: latest_obs=%s, staleness=%s days, reason=%s",
            status,
            quality["latest_obs_ts"],
            quality["staleness_days"],
            quality["reason"],
        )
        if not quality["data_ok"]:
            log.warning("SP500_PROXY is STALE — Layer-2 quality gate will block snapshots.")
            return 4

    log.info("SPY adapter completed. Rows in DB: %d.", count_rows(conn, SERIES_ID))
    return 0


if __name__ == "__main__":
    sys.exit(main())
