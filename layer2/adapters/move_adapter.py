"""
Layer-2 ingestion adapter for the MOVE Index (Merrill Lynch Option Volatility Estimate).

Role in architecture:
    Tier-1 daily series - rates-vol / bond-stress sensor.
    Feeds StressIndex, UnknownMode, and position-shrink governance in Layer-3.
    A missing or stale MOVE observation sets data_ok=False -> NO snapshot published.

Source strategy (priority order):
    1. Stooq CSV download  - ticker: ^MOVE  (free, reliable, T+1 EOD)
    2. Yahoo Finance        - ticker: ^MOVE  (fallback; check for gaps)
    3. Manual CSV drop      - place file at MOVE_MANUAL_CSV_PATH (emergency override)

Storage contract:
    Writes to the shared `observations` table:

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

Usage:
    python move_adapter.py                        # daily EOD job
    python move_adapter.py --backfill-days 90     # backfill 90 days
    python move_adapter.py --dry-run              # fetch only, no DB write
    python move_adapter.py --source stooq         # force stooq source
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
SERIES_ID: str = "rates_vol_stress_move"
STOOQ_TICKER: str = "^move"
YAHOO_TICKER: str = "^MOVE"
MOVE_MANUAL_CSV_PATH: str = os.getenv("MOVE_MANUAL_CSV_PATH", "")
DEFAULT_SOURCE_PRIORITY: List[str] = ["stooq", "yahoo", "manual"]
MAX_STALENESS_DAYS: int = 3
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] move_adapter: %(message)s",
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


def upsert_observations(
    conn: sqlite3.Connection,
    rows: List[Tuple],
    dry_run: bool = False,
) -> int:
    if not rows:
        log.warning("upsert_observations called with empty rows - nothing to write.")
        return 0

    if dry_run:
        log.info("[DRY-RUN] Would write %d observation(s) - skipping DB write.", len(rows))
        for r in rows:
            log.debug("  %s | %s | value=%.4f | source=%s", r[0], r[1], r[3], r[5])
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
    log.info("Wrote %d MOVE observation(s) to DB.", len(rows))
    return len(rows)


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
                continue
            results.append((obs_date, close_val, "stooq"))
        except (ValueError, IndexError):
            continue
    if not results:
        raise ValueError("Stooq CSV yielded no valid MOVE rows.")
    log.info("Stooq: parsed %d MOVE rows (%s -> %s).", len(results), results[0][0], results[-1][0])
    return results


# ---------------------------------------------------------------------------
# Source: Yahoo Finance
# ---------------------------------------------------------------------------

def fetch_yahoo(start: date, end: date) -> List[Tuple[date, float, str]]:
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")
    log.debug("Fetching MOVE from Yahoo Finance (%s -> %s).", start, end)
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
            continue
        results.append((obs_date, close_val, "yahoo"))
    if not results:
        raise ValueError("Yahoo Finance yielded no valid MOVE rows.")
    log.info("Yahoo: parsed %d MOVE rows.", len(results))
    return results


# ---------------------------------------------------------------------------
# Source: Manual CSV
# ---------------------------------------------------------------------------

def fetch_manual_csv(csv_path: str, start: date, end: date) -> List[Tuple[date, float, str]]:
    from pathlib import Path
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Manual CSV not found: {csv_path}")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        raise ValueError(f"Manual CSV is empty: {csv_path}")
    header = lines[0].lower().split(",")
    date_col = next((i for i, h in enumerate(header) if "date" in h), None)
    val_col = next((i for i, h in enumerate(header) if h in ("close", "value", "move")), None)
    if date_col is None or val_col is None:
        raise ValueError(f"Manual CSV must have date and close/value columns. Got: {lines[0]!r}")
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
                    continue
                return fetch_manual_csv(csv, start, end)
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
# Staleness check
# ---------------------------------------------------------------------------

def check_staleness(conn: sqlite3.Connection, clock_ts: date) -> dict:
    latest = latest_obs_date(conn)
    if latest is None:
        return {
            "series_id": SERIES_ID,
            "latest_obs_ts": None,
            "staleness_days": None,
            "data_ok": False,
            "reason": "no observations found",
        }
    staleness = (clock_ts - latest).days
    ok = staleness <= MAX_STALENESS_DAYS
    return {
        "series_id": SERIES_ID,
        "latest_obs_ts": latest.isoformat(),
        "staleness_days": staleness,
        "data_ok": ok,
        "reason": "fresh" if ok else f"stale ({staleness}d > {MAX_STALENESS_DAYS}d threshold)",
    }


# ---------------------------------------------------------------------------
# Batch hash
# ---------------------------------------------------------------------------

def compute_batch_hash(rows: List[Tuple]) -> str:
    payload = "|".join(
        f"{r[1]}:{r[3]:.6f}"
        for r in sorted(rows, key=lambda x: x[1])
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Layer-2 MOVE index adapter.")
    p.add_argument("--backfill-days", type=int, default=1)
    p.add_argument("--start-date", type=str, default=None)
    p.add_argument("--end-date", type=str, default=None)
    p.add_argument("--db", type=str, default=DB_PATH)
    p.add_argument("--source", type=str, default=None)
    p.add_argument("--csv-path", type=str, default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--staleness-check", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = date.today()
    yesterday = today - timedelta(days=1)
    end = date.fromisoformat(args.end_date) if args.end_date else yesterday
    if args.start_date:
        start = date.fromisoformat(args.start_date)
    else:
        start = end - timedelta(days=max(0, args.backfill_days - 1))
    if start > end:
        log.error("start_date %s is after end_date %s - aborting.", start, end)
        return 1
    log.info("MOVE adapter starting | range: %s -> %s | dry_run: %s", start, end, args.dry_run)
    priority = [args.source] if args.source else DEFAULT_SOURCE_PRIORITY
    try:
        raw = fetch_move(start, end, priority, manual_csv_path=args.csv_path)
    except RuntimeError as exc:
        log.error("MOVE fetch failed: %s", exc)
        return 2
    if not raw:
        log.error("Fetch returned zero rows - aborting.")
        return 3
    ingestion_ts = datetime.now(tz=timezone.utc)
    rows = build_obs_rows(raw, ingestion_ts)
    batch_hash = compute_batch_hash(rows)
    log.info("Batch hash: %s | rows: %d", batch_hash, len(rows))
    conn = get_connection(args.db)
    written = upsert_observations(conn, rows, dry_run=args.dry_run)
    quality = check_staleness(conn, clock_ts=today)
    status = "PASS" if quality["data_ok"] else "FAIL"
    log.info("Staleness [%s]: latest=%s, staleness=%sd, reason=%s",
             status, quality["latest_obs_ts"], quality["staleness_days"], quality["reason"])
    if not quality["data_ok"]:
        log.warning("MOVE is STALE - snapshot publishing will be blocked.")
        return 4
    log.info("MOVE adapter completed. Rows written: %d.", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())