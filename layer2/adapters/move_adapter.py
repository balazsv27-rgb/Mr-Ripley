"""
move_adapter.py
---------------
Layer-2 ingestion adapter for the MOVE Index (Merrill Lynch Option Volatility Estimate).

Role in architecture:
    Tier-1 daily series — rates-vol / bond-stress sensor.
    A missing or stale MOVE observation = NO snapshot published (fail-closed).

Source strategy (priority order):
    1. Stooq CSV download  — ticker: ^move  (free, reliable, T+1 EOD)
    2. Yahoo Finance        — ticker: ^MOVE  (reliable fallback; confirmed working on weekends)
    3. Manual CSV drop      — place file at MOVE_MANUAL_CSV_PATH (emergency override)

Note: Stooq is unreliable for ^move on weekends — Yahoo is confirmed working.
If running a daily job, prefer --source yahoo for robustness.

Schema, connection, and upsert all come from layer2.db.
Series metadata comes from layer2.config.registry.

Usage:
    python layer2/adapters/move_adapter.py --source yahoo
    python layer2/adapters/move_adapter.py --source yahoo --backfill-days 1825
    python layer2/adapters/move_adapter.py --staleness-check
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
# Layer-2 shared modules
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.db import get_connection, upsert_observations, filter_new_rows, latest_obs_date, count_rows  # noqa: E402
from layer2.config.registry import get_registry  # noqa: E402
from layer2.clock import get_latest_completed_clock  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID: str = "rates_vol_stress_move"
STOOQ_TICKER: str = "^move"
YAHOO_TICKER: str = "^MOVE"
MOVE_MANUAL_CSV_PATH: str = os.getenv("MOVE_MANUAL_CSV_PATH", "")
DEFAULT_SOURCE_PRIORITY: List[str] = ["stooq", "yahoo", "manual"]
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] move_adapter: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


def _series_cfg() -> dict:
    return get_registry().get(SERIES_ID)


# ---------------------------------------------------------------------------
# Source: Stooq
# ---------------------------------------------------------------------------

def fetch_stooq(start: date, end: date) -> List[Tuple[date, float, str]]:
    import urllib.request

    url = (
        f"https://stooq.com/q/d/l/"
        f"?s={STOOQ_TICKER}"
        f"&d1={start.strftime('%Y%m%d')}"
        f"&d2={end.strftime('%Y%m%d')}"
        f"&i=d"
    )
    log.debug("Stooq URL: %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "L2-MOVE-Adapter/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Stooq fetch failed: {exc}") from exc

    return _parse_stooq_csv(raw)


def _parse_stooq_csv(raw: str) -> List[Tuple[date, float, str]]:
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    if not lines:
        raise ValueError("Stooq returned empty response.")

    header = lines[0].lower().split(",")
    if "date" not in header or "close" not in header:
        raise ValueError(f"Unexpected Stooq CSV header: {lines[0]!r}")

    date_idx = header.index("date")
    close_idx = header.index("close")

    results = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= max(date_idx, close_idx):
            continue
        try:
            obs_date = date.fromisoformat(parts[date_idx])
            close_val = float(parts[close_idx])
            if close_val <= 0:
                log.warning("Skipping non-positive MOVE value on %s: %s", obs_date, close_val)
                continue
            results.append((obs_date, close_val, "stooq"))
        except (ValueError, IndexError) as exc:
            log.debug("Skipping malformed CSV row %r: %s", line, exc)

    if not results:
        raise ValueError("Stooq CSV parsed but yielded no valid MOVE rows.")
    log.info("Stooq: parsed %d MOVE rows (%s → %s).",
             len(results), results[0][0], results[-1][0])
    return results


# ---------------------------------------------------------------------------
# Source: Yahoo Finance
# ---------------------------------------------------------------------------

def fetch_yahoo(start: date, end: date) -> List[Tuple[date, float, str]]:
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError(
            "yfinance is not installed. Run: pip install yfinance"
        )

    log.debug("Fetching MOVE from Yahoo Finance (%s → %s).", start, end)
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
        if close_val <= 0:
            log.warning("Skipping non-positive MOVE value on %s: %s", obs_date, close_val)
            continue
        results.append((obs_date, close_val, "yahoo"))

    if not results:
        raise ValueError("Yahoo Finance yielded no valid MOVE rows.")
    log.info("Yahoo: parsed %d MOVE rows (%s → %s).",
             len(results), results[0][0], results[-1][0])
    return results


# ---------------------------------------------------------------------------
# Source: Manual CSV
# ---------------------------------------------------------------------------

def fetch_manual_csv(csv_path: str, start: date, end: date) -> List[Tuple[date, float, str]]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Manual CSV not found: {csv_path}")

    log.info("Reading MOVE from manual CSV: %s", path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        raise ValueError(f"Manual CSV is empty: {csv_path}")

    header = lines[0].lower().split(",")
    date_col = next((i for i, h in enumerate(header) if "date" in h), None)
    val_col = next((i for i, h in enumerate(header) if h in ("close", "value", "move")), None)
    if date_col is None or val_col is None:
        raise ValueError(
            f"Manual CSV must have 'date' and 'close'/'value' columns. Got: {lines[0]!r}"
        )

    results = []
    for line in lines[1:]:
        parts = line.split(",")
        try:
            obs_date = date.fromisoformat(parts[date_col].strip())
            close_val = float(parts[val_col].strip())
        except (ValueError, IndexError):
            continue
        if start <= obs_date <= end and close_val > 0:
            results.append((obs_date, close_val, "manual"))

    if not results:
        raise ValueError(f"Manual CSV yielded no valid rows in [{start}, {end}].")
    log.info("Manual CSV: parsed %d MOVE rows.", len(results))
    return results


# ---------------------------------------------------------------------------
# Fetch orchestrator
# ---------------------------------------------------------------------------

def fetch_move(
    start: date,
    end: date,
    source_priority: List[str],
    manual_csv_path: str = "",
) -> List[Tuple[date, float, str]]:
    errors = {}
    for source in source_priority:
        try:
            if source == "stooq":
                return fetch_stooq(start, end)
            elif source == "yahoo":
                return fetch_yahoo(start, end)
            elif source == "manual":
                csv = manual_csv_path or MOVE_MANUAL_CSV_PATH
                if not csv:
                    log.debug("Manual CSV source selected but no path configured — skipping.")
                    continue
                return fetch_manual_csv(csv, start, end)
            else:
                log.warning("Unknown source %r in priority list — skipping.", source)
        except Exception as exc:
            log.warning("Source %r failed: %s", source, exc)
            errors[source] = str(exc)

    raise RuntimeError(f"All MOVE sources failed. Errors: {errors}")


# ---------------------------------------------------------------------------
# Build observation rows
# ---------------------------------------------------------------------------

def build_obs_rows(
    raw: List[Tuple[date, float, str]],
    ingestion_ts: datetime,
) -> List[Tuple]:
    rows = []
    for obs_date, value, source in raw:
        rows.append((SERIES_ID, obs_date, ingestion_ts, value, 0, source))
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
            "latest_obs_ts": None,
            "staleness_days": None,
            "data_ok": False,
            "reason": "no observations found",
        }
    staleness = (clock_ts - latest).days
    ok = staleness <= threshold
    return {
        "series_id": SERIES_ID,
        "latest_obs_ts": latest.isoformat(),
        "staleness_days": staleness,
        "data_ok": ok,
        "reason": "fresh" if ok else f"stale ({staleness}d > {threshold}d threshold)",
    }


# ---------------------------------------------------------------------------
# Batch hash
# ---------------------------------------------------------------------------

def compute_batch_hash(rows: List[Tuple]) -> str:
    payload = "|".join(
        f"{r[1]}:{r[3]:.6f}" for r in sorted(rows, key=lambda x: x[1])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 MOVE index adapter — fetches and stores daily MOVE closes."
    )
    p.add_argument("--backfill-days", type=int, default=1,
                   help="Calendar days to backfill (default: 1 = yesterday only).")
    p.add_argument("--start-date", type=str, default=None,
                   help="Explicit start date YYYY-MM-DD (overrides --backfill-days).")
    p.add_argument("--end-date", type=str, default=None,
                   help="Explicit end date YYYY-MM-DD (default: yesterday).")
    p.add_argument("--db", type=str, default=DB_PATH,
                   help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--source", type=str, default=None,
                   help="Force a specific source: stooq | yahoo | manual.")
    p.add_argument("--csv-path", type=str, default="",
                   help="Path to manual CSV file (only with --source manual).")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch and validate but do NOT write to DB.")
    p.add_argument("--staleness-check", action="store_true",
                   help="After ingestion, print staleness report vs today.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    clock = get_latest_completed_clock()
    today = clock.clock_date
    yesterday = today

    end = date.fromisoformat(args.end_date) if args.end_date else yesterday
    if args.start_date:
        start = date.fromisoformat(args.start_date)
    else:
        start = end - timedelta(days=max(0, args.backfill_days - 1))

    if start > end:
        log.error("start_date %s is after end_date %s — aborting.", start, end)
        return 1

    log.info("MOVE adapter starting | range: %s → %s | db: %s | dry_run: %s",
             start, end, args.db, args.dry_run)

    priority = [args.source] if args.source else DEFAULT_SOURCE_PRIORITY

    try:
        raw = fetch_move(start, end, priority, manual_csv_path=args.csv_path)
    except RuntimeError as exc:
        log.error("MOVE fetch failed: %s", exc)
        return 2

    if not raw:
        log.error("Fetch succeeded but returned zero rows — aborting.")
        return 3

    ingestion_ts = datetime.now(tz=timezone.utc)
    rows = build_obs_rows(raw, ingestion_ts)
    batch_hash = compute_batch_hash(rows)
    log.info("Batch hash (SHA-256): %s | rows: %d", batch_hash, len(rows))

    conn = get_connection(args.db)
    rows_to_write = filter_new_rows(conn, SERIES_ID, rows)

    if not rows_to_write:
        log.info("No new rows to write — DB is already up to date.")
    else:
        written = upsert_observations(conn, rows_to_write, dry_run=args.dry_run)
        if not args.dry_run:
            log.info("Wrote %d MOVE observation(s) to DB.", written)

    if args.staleness_check or not args.dry_run:
        quality = check_staleness(conn, clock_ts=today)
        status = "✓ PASS" if quality["data_ok"] else "✗ FAIL"
        log.info(
            "Staleness check [%s]: latest_obs=%s, staleness=%s days, reason=%s",
            status, quality["latest_obs_ts"], quality["staleness_days"], quality["reason"],
        )
        if not quality["data_ok"]:
            log.warning(
                "MOVE is STALE — Layer-2 quality gate will block snapshot publishing."
            )
            return 4

    log.info("MOVE adapter completed. Rows in DB: %d.", count_rows(conn, SERIES_ID))
    return 0


if __name__ == "__main__":
    sys.exit(main())
