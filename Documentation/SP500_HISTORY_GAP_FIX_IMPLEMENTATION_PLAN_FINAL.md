# Quick Fix: SP500 Historical Data Gap in Layer-2

## Fix Explanation

### What This Fix Does

This fix adds a **new equity proxy series** called `SP500_PROXY` to Layer-2, sourced from Yahoo Finance SPY adjusted close data spanning **2005 to present**. The existing `SP500` series, which comes from FRED and starts around 2016, remains **completely unchanged** — no rows are modified, no snapshots are invalidated, and no downstream consumers are broken.

The fix introduces:
- A new series ID: `SP500_PROXY`
- A new adapter: `spy_adapter.py`
- A new registry entry with `include_in_snapshot: true`
- Backfilled historical data from 2005-01-03 onward

---

### Why It's Necessary

#### The Current Gap

| Aspect | Current State | Problem |
|--------|---------------|---------|
| **SP500 data start** | ~2016 | Missing 11+ years of market history |
| **Missing periods** | 2008 crisis, 2011 gold peak, 2015 China shock | Cannot validate regime behavior during stress |
| **Layer-3 dependency** | Needs continuous equity signal for regime detection | Cannot calibrate or backtest properly |
| **Backtest window** | Starts 2014 per documentation | Gap overlaps with required calibration period |

#### Why Replacement Is Not an Option

Many would simply replace `SP500` with SPY data. This is **incorrect** for a truth layer:

| Property | SP500 (FRED) | SPY (Yahoo) | Why They Differ |
|----------|--------------|-------------|-----------------|
| **Type** | Economic index | Tradable ETF | Different construction methodologies |
| **Dividends** | Not included | Included in adjusted close | SPY total return differs from price index |
| **Governance** | FRED published | Yahoo calculated | Different revision policies |
| **Meaning** | "The S&P 500 level" | "What SPY traded at" | Semantic difference matters for audit |

**Example:** On a given date, SP500 might be 1500.00 while SPY adjusted close is 145.30 — different numbers, different meanings. Replacing would corrupt historical truth.

#### The Correct Approach

Layer-2 is a **truth layer**, not a convenience layer. Its job is to preserve original sources with clear provenance. Therefore:
- `SP500` remains the FRED index (official reference)
- `SP500_PROXY` becomes the SPY adjusted close (tradable proxy)

This gives downstream systems an **explicit choice** between the official index and a long-history tradable proxy.

---

### How It Resolves the Problem

#### Before the Fix

observations table:
┌─────────────┬────────────┬──────────┐
│ series_id │ first_obs │ last_obs │
├─────────────┼────────────┼──────────┤
│ SP500 │ 2016-02-22 │ today │
│ gold_price │ 2014-01-02 │ today │
│ VIXCLS │ 2005-01-03 │ today │
└─────────────┴────────────┴──────────┘

Gap: 2005-2016 has NO equity data

#### After the Fix

observations table:
┌───────────────┬────────────┬──────────┐
│ series_id │ first_obs │ last_obs │
├───────────────┼────────────┼──────────┤
│ SP500 │ 2016-02-22 │ today │ ← unchanged
│ SP500_PROXY │ 2005-01-03 │ today │ ← NEW: continuous from 2005
│ gold_price │ 2014-01-02 │ today │
│ VIXCLS │ 2005-01-03 │ today │
└───────────────┴────────────┴──────────┘

Result: Equity data now spans 2005-present


#### What Changes and What Doesn't

| Component | Changes? | Explanation |
|-----------|----------|-------------|
| `SP500` rows in DB | ❌ No | Preserved exactly as from FRED |
| Existing snapshots | ❌ No | Immutable by design |
| `alignment.py` | ❌ No | Already queries any series in registry |
| `quality_gate.py` | ❌ No | Registry-driven; new series appears automatically |
| `snapshot_publisher.py` | ❌ No | Uses aligned payload; no code change |
| `fred_loader.py` | ❌ No | SP500 remains in FRED loader |
| Snapshot contract | ❌ No | New series appears in `values` and `values_by_group` |

#### Behavior Guarantees

- **Deterministic:** Same backfill command produces identical rows
- **Idempotent:** Re-running backfill does not duplicate rows (`INSERT OR IGNORE`)
- **Fail-closed:** If SPY fetch fails, staleness triggers quality gate `FAIL`, blocking snapshots
- **Auditable:** Each observation has `source='yahoo_spy'` for provenance
- **Point-in-time correct:** `as_of_ts = 21:00 UTC` on observation date

---

## Quick Steps

- **Step 1:** Add `SP500_PROXY` entry to `series_registry.json` with all required fields
- **Step 2:** Increment `registry_version` (e.g., `1.0.0` → `1.1.0`)
- **Step 3:** Create `spy_adapter.py` with Yahoo Finance fetch and 21:00 UTC `as_of_ts`
- **Step 4:** Run one-time historical backfill from `2005-01-03`
- **Step 5:** Validate via registry check, quality gate, and snapshot dry-run

---

## Detailed Step-by-Step

### Step 1: Add SP500_PROXY to Series Registry

**File:** `[repo_root]/layer2/config/series_registry.json`

**Action:** Add the following entry **after** the existing `SP500` entry. Do **NOT** modify or delete the existing `SP500` entry.

```json
{
  "series_id": "SP500_PROXY",
  "description": "S&P 500 proxy via SPY ETF adjusted close",
  "tier": 1,
  "frequency": "D",
  "staleness_days": 3,
  "blocks_snapshot": true,
  "group": "risk",
  "source": "yahoo_spy",
  "full_history_start": "2005-01-03",
  "discontinued": false,
  "is_estimate": false,
  "include_in_snapshot": true,
  "revision_risk": false,
  "notes": "Yahoo Finance SPY adjusted close. Long-history equity proxy from 2005. Does not replace FRED SP500."
}

Field-by-field explanation:

Field	Value	Why
tier	1	Equity is core regime input — must be fresh
blocks_snapshot	true	Tier-1 failure blocks snapshot publication (fail-closed)
staleness_days	3	Accommodates weekends and market holidays
include_in_snapshot	true	Appears in every published snapshot
revision_risk	false	Adjusted close restated, but accepted as point-in-time
source	yahoo_spy	Provenance for audit queries
Verification command:

bash
python -m layer2.config.registry --validate
Expected output:

text
Registry VALID
Common pitfalls:

Missing include_in_snapshot → series will not appear in snapshots

Missing revision_risk → registry validation fails

Duplicate series_id → validation error

Trailing comma after last entry → invalid JSON

Step 2: Increment Registry Version
File: [repo_root]/layer2/config/series_registry.json (root level)

Action: Locate the registry_version field at the top of the file and increment it.

Before:

json
{
  "registry_version": "1.0.0",
  "series": [
    ...
  ]
}
After:

json
{
  "registry_version": "1.1.0",
  "series": [
    ...
  ]
}
Why this matters: The snapshot publisher reads registry_version and stores it as config_version in every snapshot. This enables version-locked replay — you can later determine exactly which registry configuration produced a given snapshot.

Verification command:

bash
python -m layer2.config.registry --summary
Expected output includes:

text
registry_version: 1.1.0
total_series: 24
tier1_count: 16
tier2_count: 8
Pitfall: Forgetting to increment means new snapshots will have the same config_version as old ones, breaking version-locking.

Step 3: Create SPY Adapter
File: [repo_root]/layer2/adapters/spy_adapter.py

Action: Create a new adapter following the pattern of move_adapter.py and gold_adapter.py.

Complete Adapter Code
python
"""
spy_adapter.py — SP500_PROXY equity proxy via Yahoo Finance SPY adjusted close.
Tier-1 daily series. Provides continuous history from 2005 onward.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

# Path bootstrap
_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.db import get_connection, upsert_observations, filter_new_rows, latest_obs_date, count_rows
from layer2.config.registry import get_registry
from layer2.clock import get_latest_completed_clock

# Configuration
DB_PATH = os.getenv("L2_DB_PATH", "layer2_truth.db")
SERIES_ID = "SP500_PROXY"
YAHOO_TICKER = "SPY"
SOURCE_LABEL = "yahoo_spy"
DEFAULT_BACKFILL_DAYS = 7

logging.basicConfig(
    level=getattr(logging, os.getenv("L2_LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] spy_adapter: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


def _series_cfg() -> dict:
    cfg = get_registry().get(SERIES_ID)
    if cfg is None:
        raise KeyError(f"series_id {SERIES_ID!r} not found in series_registry.json")
    return cfg


def fetch_spy_yahoo(start: date, end: date) -> List[Tuple[date, float, str]]:
    """Fetch SPY adjusted close from Yahoo Finance."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance") from exc

    log.info("Fetching SPY from Yahoo: %s → %s", start, end)

    df = yf.download(
        YAHOO_TICKER,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=True,  # Handles splits and dividends
        progress=False,
    )

    if df is None or df.empty:
        raise RuntimeError(f"Yahoo returned empty SPY history for {start} → {end}")

    if "Close" not in df.columns:
        raise RuntimeError("Yahoo SPY history missing required Close column")

    results: List[Tuple[date, float, str]] = []
    for idx, row in df.iterrows():
        obs_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        value = float(row["Close"])
        if value > 0:
            results.append((obs_date, value, SOURCE_LABEL))

    results.sort(key=lambda x: x[0])
    log.info("Fetched %d SPY rows from %s to %s", len(results), results[0][0], results[-1][0])
    return results


def build_obs_rows(raw: List[Tuple[date, float, str]]) -> List[Tuple]:
    """
    Convert raw SPY data to observations table rows.

    CRITICAL: as_of_ts = 21:00 UTC on observation date.
    This matches the convention used by gold_adapter, move_adapter, and fred_loader.
    """
    rows = []
    for obs_date, value, source in raw:
        as_of = datetime(
            obs_date.year,
            obs_date.month,
            obs_date.day,
            21, 0, 0,
            tzinfo=timezone.utc,
        )
        rows.append((SERIES_ID, obs_date, as_of, value, 0, source))
    return rows


def check_staleness(conn, clock_date: date) -> dict:
    cfg = _series_cfg()
    threshold = cfg["staleness_days"]
    latest = latest_obs_date(conn, SERIES_ID)

    if latest is None:
        return {
            "series_id": SERIES_ID,
            "data_ok": False,
            "staleness_days": None,
            "reason": "no observations found",
        }

    staleness = (clock_date - latest).days
    ok = staleness <= threshold

    return {
        "series_id": SERIES_ID,
        "data_ok": ok,
        "staleness_days": staleness,
        "reason": "fresh" if ok else f"stale ({staleness}d > {threshold}d)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SP500_PROXY adapter via Yahoo SPY")
    parser.add_argument("--backfill-start", type=str, help="YYYY-MM-DD (overrides --backfill-days)")
    parser.add_argument("--backfill-days", type=int, default=DEFAULT_BACKFILL_DAYS)
    parser.add_argument("--db", type=str, default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--staleness-check-only", action="store_true")
    args = parser.parse_args()

    conn = get_connection(args.db)
    clock = get_latest_completed_clock()
    today = clock.clock_date

    if args.staleness_check_only:
        result = check_staleness(conn, today)
        log.info("Staleness: %s", result)
        return 0 if result["data_ok"] else 1

    # Determine date range
    if args.backfill_start:
        start = date.fromisoformat(args.backfill_start)
        end = today
    else:
        end = today
        start = end - timedelta(days=args.backfill_days - 1)

    if start > end:
        log.error("Invalid range: start=%s > end=%s", start, end)
        return 1

    log.info("Range: %s → %s | dry_run=%s", start, end, args.dry_run)

    # Fetch and write
    raw = fetch_spy_yahoo(start, end)
    if not raw:
        log.error("No data fetched — aborting")
        return 1

    rows = build_obs_rows(raw)
    new_rows = filter_new_rows(conn, SERIES_ID, rows)

    if not new_rows:
        log.info("No new rows to write — DB already up to date")
    else:
        log.info("Writing %d new rows", len(new_rows))
        if not args.dry_run:
            upsert_observations(conn, new_rows)
            log.info("Wrote %d SP500_PROXY rows", len(new_rows))
        else:
            log.info("[DRY-RUN] Would write %d rows", len(new_rows))

    # Final staleness report
    result = check_staleness(conn, today)
    log.info("Staleness after run: %s", result["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
Verification after creation:

bash
python -c "import layer2.adapters.spy_adapter; print('OK')"
Expected output:

text
OK
Troubleshooting: If import fails, ensure layer2/__init__.py exists and the path bootstrap is correct.

Step 4: Run Historical Backfill
Command:

bash
python layer2/adapters/spy_adapter.py --backfill-start 2005-01-03
Expected output:

text
2026-05-01T10:00:00Z [INFO] spy_adapter: Range: 2005-01-03 → 2026-05-01 | dry_run=False
2026-05-01T10:00:01Z [INFO] spy_adapter: Fetching SPY from Yahoo: 2005-01-03 → 2026-05-01
2026-05-01T10:00:02Z [INFO] spy_adapter: Fetched 4321 SPY rows from 2005-01-03 to 2026-04-30
2026-05-01T10:00:02Z [INFO] spy_adapter: Writing 4321 new rows
2026-05-01T10:00:03Z [INFO] spy_adapter: Wrote 4321 SP500_PROXY rows
2026-05-01T10:00:03Z [INFO] spy_adapter: Staleness after run: fresh
Verification queries:

sql
-- Check earliest date
SELECT MIN(obs_ts) FROM observations WHERE series_id = 'SP500_PROXY';
-- Expected: 2005-01-03

-- Check row count by year
SELECT strftime('%Y', obs_ts) AS year, COUNT(*) AS rows
FROM observations WHERE series_id = 'SP500_PROXY'
GROUP BY year ORDER BY year;

-- Verify SP500 untouched
SELECT series_id, source, COUNT(*)
FROM observations WHERE series_id IN ('SP500', 'SP500_PROXY')
GROUP BY series_id, source;
Expected pattern for yearly counts:

text
2005|252
2006|251
2007|251
2008|253
...
2026|85 (partial year)
Troubleshooting:

SSL/Certificate errors: Run pip install --upgrade certifi

Rate limiting: Add time.sleep(1) between requests if needed

Empty result: Check Yahoo API status; the adapter will return [] and exit with code 1

Step 5: Validate Quality Gate and Snapshot
Step 5.1: Run Quality Gate
bash
python layer2/adapters/quality_gate.py
Expected output:

text
2026-05-01T10:05:00Z [INFO] quality_gate: VERDICT: PASS — snapshot may be published
2026-05-01T10:05:00Z [INFO] quality_gate:   Tier-1: 16/16 PASS | 0 FAIL
2026-05-01T10:05:00Z [INFO] quality_gate:   SP500_PROXY: PASS (fresh)
If quality gate fails with SP500_PROXY stale: Re-run backfill with --backfill-days to catch recent days.

Step 5.2: Set Engine Version
PowerShell:

powershell
$env:L2_ENGINE_VERSION="gold-v3.3.0"
Bash:

bash
export L2_ENGINE_VERSION="gold-v3.3.0"
Step 5.3: Run Snapshot Dry-Run
bash
python layer2/adapters/snapshot_publisher.py --dry-run
Expected output contains:

text
SNAPSHOT REPORT [DRY-RUN]
  series_id: SP500_PROXY
  value: [numeric value]
  staleness_days: 0
Step 5.4: Verify Snapshot JSON Contains SP500_PROXY
bash
python -c "import json; s=json.load(open('latest_snapshot.json')); print('SP500_PROXY' in s['values'])"
Expected output:

text
True
Summary
This fix adds SP500_PROXY as a long-history equity proxy while preserving the original SP500 FRED index unchanged. The implementation is non-breaking (no existing data modified), idempotent (re-runs safe), and fully integrated with Layer-2's registry-driven, fail-closed architecture. After deployment, Layer-2 provides continuous equity-market context from 2005 onward, enabling proper regime detection, backtesting, and calibration for downstream systems.

text

---

## Option 2: Save Using Command Line

If you're on a Unix-like system (Linux/macOS) or use WSL on Windows:

```bash
# Create the file
cat > SP500_HISTORY_GAP_FIX_QUICK_FIX.md << 'EOF'
[PASTE THE ENTIRE MARKDOWN CONTENT ABOVE HERE]
EOF
Option 3: Save Using PowerShell (Windows)
powershell
# Create the file
New-Item -Path "SP500_HISTORY_GAP_FIX_QUICK_FIX.md" -ItemType File -Force

# Then open in notepad and paste the content
notepad SP500_HISTORY_GAP_FIX_QUICK_FIX.md
Recommended File Naming
Purpose	Suggested Filename
Quick reference / daily use	SP500_HISTORY_GAP_FIX_QUICK_FIX.md
Full implementation guide (from earlier)	SP500_HISTORY_GAP_FIX_IMPLEMENTATION_PLAN_FINAL.md
Summary cheat sheet	SP500_HISTORY_GAP_FIX_FULL.md
Once you save the file, it will render properly in any Markdown viewer (GitHub, VS Code, Obsidian, Typora, etc.). The document includes proper code blocks with syntax highlighting, tables, and hierarchical headers for easy navigation.