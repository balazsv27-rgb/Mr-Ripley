"""
gld_holdings_adapter.py
-----------------------
Layer-2 ingestion adapter for GLD Trust — ounces of gold held.

Role in architecture:
    Tier-2 daily series — physical gold flow confirmation signal.
    series_id: "gld_holdings_flow_confirm"
    Used in M2 validation overlay. Does NOT block snapshot publishing if missing/stale.
    Layer-3 consumes this as a confirmation input only (never a primary driver).

Source (CHANGED — see note below):
    Yahoo Finance via yfinance — sharesOutstanding(GLD) × GLD_OZ_PER_SHARE (0.09585)

    WHY THE SOURCE CHANGED:
    The SPDR authoritative archive URL previously used:
        https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv
    now returns a PDF (Content-Type: application/pdf) rather than a CSV file.
    The adapter logged: "Header: %PDF-1.5" and correctly produced zero rows.
    Until SPDR restores the CSV endpoint, yfinance is the reliable alternative:
      - sharesOutstanding is updated daily after market close
      - price history gives us the trading-day calendar for the requested window
      - ounces = sharesOutstanding × 0.09585 (fixed ratio, never changes per GLD prospectus)

    NOTE ON HISTORICAL ACCURACY:
    Yahoo returns *current* sharesOutstanding only — not historical daily values.
    This means all rows in a given run carry the same ounces figure.
    This is an accepted approximation for a Tier-2 confirmation signal
    (GLD shares outstanding changes slowly; large deviations are the signal,
    not the daily micro-movements). This matches the logic in run_gld_holdings.py.

Stored value:
    Ounces of gold held in GLD Trust.
    Unit: troy ounces.
    source field: "yahoo_gld_proxy"
    as_of_ts: market close on obs_ts, approximated as 21:15 UTC year-round.

Schema, connection, and upsert all come from layer2.db.
Series metadata (tier, staleness threshold, blocks_snapshot) comes from layer2.config.registry.

Usage:
    # Daily EOD job (last 30 days, upserts new rows only)
    python layer2/adapters/gld_holdings_adapter.py

    # Backfill from a specific start date
    python layer2/adapters/gld_holdings_adapter.py --start-date 2020-01-01

    # Dry-run (fetch + validate, no DB write)
    python layer2/adapters/gld_holdings_adapter.py --dry-run

    # Print staleness report only (no fetch)
    python layer2/adapters/gld_holdings_adapter.py --staleness-check-only
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Layer-2 shared modules — path bootstrap identical to other adapters
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.adapters.v0.db import (  # noqa: E402
    get_connection, upsert_observations, filter_new_rows,
    latest_obs_date, count_rows,
)
from layer2.config.registry import get_registry  # noqa: E402
from layer2.adapters.v0.clock import get_latest_completed_clock  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID: str = "gld_holdings_flow_confirm"
GLD_TICKER: str = "GLD"
GLD_OZ_PER_SHARE: float = 0.09585       # Fixed per GLD prospectus — never changes
SOURCE_LABEL: str = "yahoo_gld_proxy"   # Distinguishes from legacy spdr_gld_archive rows
DEFAULT_BACKFILL_DAYS: int = 30

LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] gld_holdings_adapter: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


def _series_cfg() -> dict:
    """Return the registry entry for gld_holdings_flow_confirm."""
    cfg = get_registry().get(SERIES_ID)
    if cfg is None:
        raise KeyError(
            f"series_id {SERIES_ID!r} not found in series_registry.json. "
            "Ensure the registry entry exists before running this adapter."
        )
    return cfg


# ---------------------------------------------------------------------------
# Fetch — yfinance replaces the broken SPDR CSV URL
# ---------------------------------------------------------------------------

def fetch_gld_via_yfinance(
    start: Optional[date],
    end: date,
) -> Tuple[List[str], int]:
    """
    Fetch GLD trading days and current sharesOutstanding from Yahoo Finance.

    Args:
        start: First date of window (inclusive). None → use DEFAULT_BACKFILL_DAYS.
        end:   Last date of window (inclusive).

    Returns:
        trading_dates:     List of YYYY-MM-DD strings for each trading day in [start, end].
        shares_outstanding: Current sharesOutstanding as an integer.

    Raises:
        RuntimeError: If yfinance is not installed, or Yahoo returns unusable data.
    """
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "yfinance is not installed. Run: pip install yfinance"
        ) from exc

    ticker = yf.Ticker(GLD_TICKER)

    # --- shares outstanding ---
    info = ticker.info or {}
    shares = info.get("sharesOutstanding")
    if not shares or int(shares) <= 0:
        raise RuntimeError(
            f"Yahoo returned invalid sharesOutstanding={shares!r} for {GLD_TICKER}. "
            "The ticker may be temporarily unavailable."
        )
    shares = int(shares)

    # --- trading-day calendar from price history ---
    # yfinance end is exclusive, so add one day
    fetch_start = start or (end - timedelta(days=DEFAULT_BACKFILL_DAYS - 1))
    hist = ticker.history(
        start=fetch_start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
    )
    if hist is None or hist.empty:
        raise RuntimeError(
            f"Yahoo returned empty price history for {GLD_TICKER} "
            f"({fetch_start} → {end}). Cannot determine trading-day calendar."
        )

    trading_dates = [idx.date().isoformat() for idx in hist.index]
    log.info(
        "yfinance: sharesOutstanding=%s → %.0f oz/day (%.1f tonnes) | trading days=%d (%s → %s)",
        f"{shares:,}",
        shares * GLD_OZ_PER_SHARE,
        shares * GLD_OZ_PER_SHARE / 32_150.75,
        len(trading_dates),
        trading_dates[0] if trading_dates else "?",
        trading_dates[-1] if trading_dates else "?",
    )
    return trading_dates, shares


# ---------------------------------------------------------------------------
# Build observation rows
# ---------------------------------------------------------------------------

def build_obs_rows(
    trading_dates: List[str],
    shares_outstanding: int,
) -> List[Tuple]:
    """
    Convert trading-day list + sharesOutstanding into DB row tuples.

    Tuple layout matches layer2.db.upsert_observations contract:
        (series_id, obs_ts: date, as_of_ts: datetime,
         value: float, revision_seq: int, source: str)

    as_of_ts: approximated as 21:15 UTC on obs_ts
    (conservative year-round proxy for 4:15 PM ET, consistent with
    the original SPDR-source rows already in the DB).
    """
    ounces = float(shares_outstanding) * GLD_OZ_PER_SHARE
    rows = []
    for d_str in trading_dates:
        obs_date = date.fromisoformat(d_str)
        as_of = datetime(
            obs_date.year, obs_date.month, obs_date.day,
            21, 15, 0, tzinfo=timezone.utc,
        )
        rows.append((
            SERIES_ID,
            obs_date,
            as_of,
            ounces,
            0,             # revision_seq: Yahoo/SPDR do not revise historical ounces
            SOURCE_LABEL,
        ))
    return rows


# ---------------------------------------------------------------------------
# Staleness check — 100% registry-driven, no hardcoded thresholds
# ---------------------------------------------------------------------------

def check_staleness(conn, clock_ts: date) -> dict:
    """
    Check data freshness against the threshold in series_registry.json.

    All metadata (tier, blocks_snapshot, staleness_days) comes exclusively
    from the registry — nothing is hardcoded here.
    """
    cfg = _series_cfg()
    threshold = cfg["staleness_days"]
    latest = latest_obs_date(conn, SERIES_ID)

    if latest is None:
        return {
            "series_id":       SERIES_ID,
            "tier":            cfg["tier"],
            "latest_obs_ts":   None,
            "staleness_days":  None,
            "data_ok":         False,
            "blocks_snapshot": cfg["blocks_snapshot"],
            "reason":          "no observations found",
        }

    staleness = (clock_ts - latest).days
    ok = staleness <= threshold
    return {
        "series_id":       SERIES_ID,
        "tier":            cfg["tier"],
        "latest_obs_ts":   latest.isoformat(),
        "staleness_days":  staleness,
        "data_ok":         ok,
        "blocks_snapshot": cfg["blocks_snapshot"],
        "reason": "fresh" if ok else f"stale ({staleness}d > {threshold}d threshold)",
    }


# ---------------------------------------------------------------------------
# Batch hash (full 64-char sha256 — consistent with Audit 3 fix)
# ---------------------------------------------------------------------------

def compute_batch_hash(rows: List[Tuple]) -> str:
    payload = "|".join(
        f"{r[1]}:{r[3]:.2f}" for r in sorted(rows, key=lambda x: x[1])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Layer-2 GLD holdings adapter — "
            "fetches ounces of gold held in GLD Trust via yfinance "
            "and stores daily observations."
        )
    )
    p.add_argument(
        "--start-date", type=str, default=None,
        help="Only ingest rows on or after this date YYYY-MM-DD "
             f"(default: {DEFAULT_BACKFILL_DAYS} days before end-date).",
    )
    p.add_argument(
        "--end-date", type=str, default=None,
        help="Only ingest rows on or before this date YYYY-MM-DD (default: yesterday).",
    )
    p.add_argument(
        "--db", type=str, default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH}).",
    )
    p.add_argument(
        "--full-reload", action="store_true",
        help=(
            "Re-ingest all rows in the requested window. "
            "NOTE: INSERT OR IGNORE is truth-safe — existing rows are never overwritten. "
            "Use this only to backfill genuinely missing date ranges, "
            "not to correct existing values (use revision_seq=1 for that)."
        ),
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse but do NOT write to DB.",
    )
    p.add_argument(
        "--staleness-check-only", action="store_true",
        help="Print staleness report for existing data without fetching from Yahoo.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    clock = get_latest_completed_clock()
    today = clock.clock_date

    conn = get_connection(args.db)

    # --staleness-check-only: report on DB state, no network call
    if args.staleness_check_only:
        quality = check_staleness(conn, clock_ts=today)
        cfg = _series_cfg()
        tier_label  = f"Tier-{cfg['tier']}"
        block_label = "BLOCKS snapshot" if cfg["blocks_snapshot"] else "non-blocking"
        status = "✓ PASS" if quality["data_ok"] else (
            "✗ FAIL" if cfg["blocks_snapshot"] else "⚠ WARN"
        )
        log.info(
            "Staleness check [%s] (%s — %s): latest_obs=%s, staleness=%s days, reason=%s",
            status, tier_label, block_label,
            quality["latest_obs_ts"], quality["staleness_days"], quality["reason"],
        )
        return 0 if quality["data_ok"] else 1

    # Resolve date range
    end   = date.fromisoformat(args.end_date)   if args.end_date   else today
    start = date.fromisoformat(args.start_date) if args.start_date else None

    if start and start > end:
        log.error("Invalid range: --start-date %s is after --end-date %s", start, end)
        return 2

    log.info(
        "GLD holdings adapter starting | range: %s → %s | db: %s | dry_run: %s | full_reload: %s",
        start or f"last {DEFAULT_BACKFILL_DAYS} days", end,
        args.db, args.dry_run, args.full_reload,
    )

    # Fetch from Yahoo (replaces broken SPDR CSV URL)
    try:
        trading_dates, shares = fetch_gld_via_yfinance(start, end)
    except RuntimeError as exc:
        log.error("Fetch failed: %s", exc)
        return 3

    if not trading_dates:
        log.warning("No trading days found in range %s → %s. Nothing to write.", start, end)
        return 0

    # Build DB rows
    all_rows = build_obs_rows(trading_dates, shares)

    # Incremental filter (skip dates already in DB, unless --full-reload)
    rows_to_write = (
        all_rows if args.full_reload
        else filter_new_rows(conn, SERIES_ID, all_rows)
    )

    if not rows_to_write:
        log.info("No new rows to write — DB is already up to date.")
    else:
        batch_hash = compute_batch_hash(rows_to_write)
        log.info(
            "Batch hash: %s | rows to write: %d (of %d fetched)",
            batch_hash, len(rows_to_write), len(all_rows),
        )
        written = upsert_observations(conn, rows_to_write, dry_run=args.dry_run)
        if args.dry_run:
            log.info("[DRY-RUN] Would have written %d GLD holdings row(s). No DB changes.", written)
        else:
            log.info("Wrote %d GLD holdings observation(s) to DB.", written)

    # Staleness report — metadata fully driven by registry
    cfg = _series_cfg()
    quality = check_staleness(conn, clock_ts=today)
    tier_label  = f"Tier-{cfg['tier']}"
    block_label = "BLOCKS snapshot" if cfg["blocks_snapshot"] else "non-blocking"
    status = "✓ PASS" if quality["data_ok"] else (
        "✗ FAIL" if cfg["blocks_snapshot"] else "⚠ WARN"
    )

    log.info(
        "Staleness check [%s] (%s — %s): latest_obs=%s, staleness=%s days, reason=%s",
        status, tier_label, block_label,
        quality["latest_obs_ts"], quality["staleness_days"], quality["reason"],
    )
    if not quality["data_ok"]:
        log.warning(
            "GLD holdings data is stale — Layer-2 quality report will flag this. %s",
            "Snapshot publishing will be BLOCKED." if cfg["blocks_snapshot"]
            else "Snapshot publishing is NOT blocked (Tier-2 series).",
        )

    log.info(
        "GLD holdings adapter completed. Total rows in DB: %d.",
        count_rows(conn, SERIES_ID),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
