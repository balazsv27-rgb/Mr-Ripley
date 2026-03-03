
"""
gld_holdings_adapter.py
-----------------------
Layer-2 ingestion adapter for GLD Trust — ounces of gold held.

Role in architecture:
    Tier-2 daily series — physical gold flow confirmation signal.
    series_id: "gld_holdings_flow_confirm"
    Used in M2 validation overlay. Does NOT block snapshot publishing if missing/stale.

Source:
    State Street / SPDR authoritative archive CSV:
        https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv
    No login required. Updated each business day. Full history back to 18-Nov-2004.

Usage:
    python gld_holdings_adapter.py                        # daily EOD job
    python gld_holdings_adapter.py --full-reload          # initial backfill
    python gld_holdings_adapter.py --dry-run              # no DB write
    python gld_holdings_adapter.py --staleness-check-only # report only
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID: str = "gld_holdings_flow_confirm"
GLD_ARCHIVE_URL: str = (
    "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv"
)
MAX_STALENESS_DAYS: int = 5
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
        log.info("[DRY-RUN] Would write %d observation(s) — skipping DB write.", len(rows))
        for r in rows[:5]:
            log.debug("  %s | %s | ounces=%.2f | source=%s", r[0], r[1], r[3], r[5])
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
# Fetch + parse
# ---------------------------------------------------------------------------

def fetch_gld_archive() -> str:
    log.debug("Fetching GLD archive from: %s", GLD_ARCHIVE_URL)
    try:
        req = urllib.request.Request(
            GLD_ARCHIVE_URL,
            headers={"User-Agent": "L2-GLD-Holdings-Adapter/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"GLD archive fetch failed: {exc}") from exc
    if not raw.strip():
        raise ValueError("GLD archive returned empty response.")
    log.info("GLD archive fetched: %d bytes.", len(raw))
    return raw


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip().strip('"')
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return date.fromisoformat(raw)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if m:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    try:
        return datetime.strptime(raw, "%d-%b-%Y").date()
    except ValueError:
        pass
    return None


def _parse_ounces(raw: str) -> Optional[float]:
    clean = raw.strip().strip('"').replace(",", "").replace("$", "").replace("%", "").strip()
    if not clean or clean in ("-", "N/A", ""):
        return None
    try:
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def parse_gld_csv(
    raw: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> List[Tuple[date, float]]:
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    if not lines:
        raise ValueError("GLD CSV is empty after stripping.")
    header = lines[0].lower()
    cols = [c.strip().strip('"').lower() for c in header.split(",")]
    date_idx = 0
    ounces_idx = None
    for i, col in enumerate(cols):
        if "ounce" in col and "trust" in col:
            ounces_idx = i
            break
    if ounces_idx is None:
        log.warning("Could not identify ounces column by name — falling back to column index 8.")
        ounces_idx = 8
    log.debug("CSV: date_idx=%d, ounces_idx=%d", date_idx, ounces_idx)
    results = []
    skipped = 0
    for lineno, line in enumerate(lines[1:], start=2):
        parts = line.split(",")
        if len(parts) <= max(date_idx, ounces_idx):
            skipped += 1
            continue
        obs_date = _parse_date(parts[date_idx])
        if obs_date is None:
            skipped += 1
            continue
        if start and obs_date < start:
            continue
        if end and obs_date > end:
            continue
        ounces = _parse_ounces(parts[ounces_idx])
        if ounces is None:
            skipped += 1
            continue
        results.append((obs_date, ounces))
    if skipped:
        log.debug("Skipped %d malformed/out-of-range rows.", skipped)
    if not results:
        raise ValueError("GLD CSV parsed but yielded no valid rows.")
    results.sort(key=lambda x: x[0])
    log.info("GLD CSV: parsed %d ounces-held rows (%s → %s).",
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
        as_of = datetime(
            obs_date.year, obs_date.month, obs_date.day,
            21, 15, 0, tzinfo=timezone.utc
        )
        rows.append((SERIES_ID, obs_date, as_of, ounces, 0, "spdr_gld_archive"))
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
    log.info("Incremental filter: %d total, %d already in DB, %d new.",
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
        "blocks_snapshot": False,
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
        description="Layer-2 GLD holdings adapter — ounces of gold held in GLD Trust."
    )
    p.add_argument("--start-date", type=str, default=None)
    p.add_argument("--end-date", type=str, default=None)
    p.add_argument("--db", type=str, default=DB_PATH)
    p.add_argument("--full-reload", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--staleness-check-only", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = date.today()
    conn = get_connection(args.db)

    if args.staleness_check_only:
        quality = check_staleness(conn, clock_ts=today)
        log.info("Staleness report: %s", quality)
        return 0 if quality["data_ok"] else 1

    start = date.fromisoformat(args.start_date) if args.start_date else None
    end = date.fromisoformat(args.end_date) if args.end_date else today

    log.info("GLD holdings adapter starting | range: %s → %s | dry_run: %s | full_reload: %s",
             start or "all-history", end, args.dry_run, args.full_reload)

    try:
        raw_csv = fetch_gld_archive()
    except RuntimeError as exc:
        log.error("Fetch failed: %s", exc)
        return 2

    try:
        parsed = parse_gld_csv(raw_csv, start=start, end=end)
    except ValueError as exc:
        log.error("Parse failed: %s", exc)
        return 3

    ingestion_ts = datetime.now(tz=timezone.utc)
    all_rows = build_obs_rows(parsed, ingestion_ts)
    rows_to_write = all_rows if args.full_reload else filter_new_rows(conn, all_rows)

    if not rows_to_write:
        log.info("No new rows to write — DB is already up to date.")
    else:
        batch_hash = compute_batch_hash(rows_to_write)
        log.info("Batch hash: %s | rows to write: %d", batch_hash, len(rows_to_write))
        upsert_observations(conn, rows_to_write, dry_run=args.dry_run)

    quality = check_staleness(conn, clock_ts=today)
    status = "PASS" if quality["data_ok"] else "WARN"
    log.info("Staleness [%s] (Tier-2 non-blocking): latest=%s, staleness=%sd, reason=%s",
             status, quality["latest_obs_ts"], quality["staleness_days"], quality["reason"])
    if not quality["data_ok"]:
        log.warning("GLD holdings stale — flagged in quality report. Snapshot NOT blocked (Tier-2).")

    log.info("GLD holdings adapter completed. Total rows in DB: %d.", count_existing(conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())