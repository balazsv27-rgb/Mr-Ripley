"""
gld_holdings_adapter.py
-----------------------
Layer-2 ingestion adapter for GLD Trust — ounces of gold held.

Role in architecture:
    Tier-2 daily series — physical gold flow confirmation signal.
    series_id: "gld_holdings_flow_confirm"
    Does NOT block snapshot publishing if missing/stale (Tier-2 warns only).
    is_estimate=true — shares_outstanding applied uniformly to past dates.

Source:
    State Street / SPDR authoritative archive CSV:
        https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv

CSV column of interest (index 8):
    "Total Net Asset Value Ounces in the Trust as at 4.15 p.m. NYT"

Schema, connection, and upsert all come from layer2.db.
Series metadata comes from layer2.config.registry.

Usage:
    python layer2/adapters/gld_holdings_adapter.py
    python layer2/adapters/gld_holdings_adapter.py --backfill-days 1825
    python layer2/adapters/gld_holdings_adapter.py --dry-run
    python layer2/adapters/gld_holdings_adapter.py --staleness-check-only
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
import urllib.request
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID: str = "gld_holdings_flow_confirm"
GLD_ARCHIVE_URL: str = (
    "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv"
)
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] gld_holdings_adapter: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


def _series_cfg() -> dict:
    return get_registry().get(SERIES_ID)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_gld_archive() -> str:
    log.debug("Fetching GLD archive from: %s", GLD_ARCHIVE_URL)
    try:
        req = urllib.request.Request(
            GLD_ARCHIVE_URL, headers={"User-Agent": "L2-GLD-Holdings-Adapter/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"GLD archive fetch failed: {exc}") from exc

    if not raw.strip():
        raise ValueError("GLD archive returned empty response.")
    log.info("GLD archive fetched: %d bytes.", len(raw))
    return raw


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

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

    header_line = lines[0].lower()
    cols = [c.strip().strip('"').lower() for c in header_line.split(",")]

    date_idx = 0
    ounces_idx = None
    for i, col in enumerate(cols):
        if "ounce" in col and "trust" in col:
            ounces_idx = i
            break
    if ounces_idx is None:
        log.warning(
            "Could not identify ounces column by name — falling back to column index 8. "
            "Header: %s", lines[0][:120]
        )
        ounces_idx = 8

    log.debug("CSV: date_idx=%d, ounces_idx=%d, total_cols=%d", date_idx, ounces_idx, len(cols))

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
            log.debug("Line %d: skipping non-positive/missing ounces on %s", lineno, obs_date)
            skipped += 1
            continue

        results.append((obs_date, ounces))

    if skipped:
        log.debug("Skipped %d malformed/out-of-range rows.", skipped)
    if not results:
        raise ValueError(
            f"GLD CSV parsed but yielded no valid rows "
            f"(date range: {start} → {end}, ounces_col={ounces_idx})."
        )

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
    """
    as_of_ts: 21:15 UTC (4:15 PM ET conservative proxy — SPDR publishes at NYSE close).
    source: spdr_gld_archive (consistent with registry and README).
    """
    rows = []
    for obs_date, ounces in parsed:
        as_of = datetime(obs_date.year, obs_date.month, obs_date.day,
                         21, 15, 0, tzinfo=timezone.utc)
        rows.append((SERIES_ID, obs_date, as_of, ounces, 0, "spdr_gld_archive"))
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
            "blocks_snapshot": False,  # Tier-2 never blocks
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
        "blocks_snapshot": False,  # Tier-2 never blocks
        "reason": "fresh" if ok else f"stale ({staleness}d > {threshold}d threshold)",
    }


# ---------------------------------------------------------------------------
# Batch hash
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
        description="Layer-2 GLD holdings adapter — ounces of gold held in GLD Trust."
    )
    p.add_argument("--start-date", type=str, default=None,
                   help="Only ingest rows on or after this date YYYY-MM-DD.")
    p.add_argument("--end-date", type=str, default=None,
                   help="Only ingest rows on or before this date YYYY-MM-DD (default: today).")
    p.add_argument("--backfill-days", type=int, default=None,
                   help="Convenience: set start-date = today - N days.")
    p.add_argument("--db", type=str, default=DB_PATH,
                   help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--full-reload", action="store_true",
                   help="Re-ingest all rows (not just new ones).")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch and parse but do NOT write to DB.")
    p.add_argument("--staleness-check-only", action="store_true",
                   help="Print staleness report for existing data without fetching.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = date.today()

    conn = get_connection(args.db)

    if args.staleness_check_only:
        quality = check_staleness(conn, clock_ts=today)
        log.info("Staleness report: %s", quality)
        return 0 if quality["data_ok"] else 1

    end = date.fromisoformat(args.end_date) if args.end_date else today
    if args.backfill_days is not None:
        start = today - timedelta(days=args.backfill_days)
    elif args.start_date:
        start = date.fromisoformat(args.start_date)
    else:
        start = None  # full archive

    log.info(
        "GLD holdings adapter starting | range: %s → %s | db: %s | dry_run: %s | full_reload: %s",
        start or "all-history", end, args.db, args.dry_run, args.full_reload,
    )

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
            log.info("Wrote %d GLD holdings observation(s) to DB.", written)

    quality = check_staleness(conn, clock_ts=today)
    status = "✓ PASS" if quality["data_ok"] else "⚠ WARN"
    log.info(
        "Staleness check [%s] (Tier-2 — non-blocking): "
        "latest_obs=%s, staleness=%s days, reason=%s",
        status, quality["latest_obs_ts"], quality["staleness_days"], quality["reason"],
    )
    if not quality["data_ok"]:
        log.warning(
            "GLD holdings data is stale — Layer-2 quality report will flag this. "
            "Snapshot publishing is NOT blocked (Tier-2 series)."
        )

    log.info("GLD holdings adapter completed. Total rows in DB: %d.", count_rows(conn, SERIES_ID))
    return 0


if __name__ == "__main__":
    sys.exit(main())
