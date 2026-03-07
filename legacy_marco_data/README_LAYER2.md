# Mr. Ripley — Layer-2 Truth Layer
## What We Built & How to Use It

> **For:** Friend / collaborator reading this on GitHub  
> **Repo:** https://github.com/balazsv27-rgb/Mr-Ripley  
> **Last updated:** 2026-03-06

---

## 1. What Is Layer-2?

Layer-2 is the **data ingestion and truth store** for the Gold-First Market State Engine (Mr. Ripley).

```
Layer-1  ->  Raw data sources (FRED, Yahoo, Stooq, State Street)
Layer-2  ->  Ingestion + validation + immutable snapshots  <- YOU ARE HERE
Layer-3  ->  Feature builder + index suite + decision engine
```

**The golden rule of Layer-2:**  
Layer-3 is NEVER allowed to read "latest" data directly. It can ONLY consume a published
`snapshot_id`. If data is missing or stale -> no snapshot is published -> Layer-3 outputs
nothing. This is called **fail-closed** behavior.

---

## 2. Folder Structure

```
Mr-Ripley/
├── FRED/                              # Historical FRED data dumps
│   ├── 2014GOLD/                      # Gold price backfill data
│   │   ├── gold_xauusd_stooq_2014_yesterday.json  # 3,132 daily gold prices
│   │   └── backfill_gold_stooq.py                 # Script used to collect it
│   ├── all_series_merged.json         # FRED metadata catalogue (149,595 series)
│   └── gold_sereies.json              # FRED gold series metadata
│                                      # note: filename has a typo — do not rename
├── .secrets/                          # API keys (NOT in GitHub — gitignored)
│   └── fred_api_key.txt               # Your FRED API key goes here
├── layer2/                            # Everything we built
│   ├── adapters/
│   │   ├── gold_adapter.py            # Gold price XAUUSD ingestion (Tier-1)
│   │   ├── move_adapter.py            # MOVE index ingestion (Tier-1)
│   │   ├── gld_holdings_adapter.py    # GLD ounces held (Tier-2)
│   │   ├── fred_loader.py             # FRED 20-series loader (Tier-1 + Tier-2)
│   │   ├── quality_gate.py            # Staleness checker + snapshot verdict
│   │   └── snapshot_publisher.py      # Publishes point-in-time snapshots for Layer-3
│   ├── config/
│   │   ├── __init__.py                # Makes config a Python package
│   │   ├── series_registry.json       # ★ Single source of truth for all series metadata
│   │   └── registry.py               # Registry loader + validator (run: python -m layer2.config.registry --validate)
│   └── README_LAYER2.md               # This file
├── layer2_truth.db                    # SQLite DB (local only — gitignored)
├── layer2_quality_report.json         # Quality gate output (local only — gitignored)
├── latest_snapshot.json               # Latest published snapshot (local only — gitignored)
├── alphavangtage.json                 # AlphaVantage daily data (unused, future use)
├── fix_encoding.py                    # Utility: fixes special characters in .py files
├── fix_docstring.py                   # Utility: fixes missing docstring quotes
└── venv/                              # Python virtual environment (local only)
```

---

## 3. Current DB State (as of March 2026)

```
observations table — ~85,703 rows across 23 series

series_id                   rows    date range                    tier  status
────────────────────────────────────────────────────────────────────────────────
gold_price_proxy            3,141   2014-01-02 -> 2026-03-05     T1    PASS
rates_vol_stress_move       1,245   2021-03-06 -> 2026-03-04     T1    PASS
DFII10                      5,794   2003-01-02 -> 2026-03-03     T1    PASS
DFII5                       5,794   2003-01-02 -> 2026-03-03     T1    PASS
DGS10                       5,294   2005-01-03 -> 2026-03-03     T1    PASS
DGS2                        5,294   2005-01-03 -> 2026-03-03     T1    PASS
DGS5                        5,294   2005-01-03 -> 2026-03-03     T1    PASS
T10YIE                      5,795   2003-01-02 -> 2026-03-04     T1    PASS
T5YIE                       5,795   2003-01-02 -> 2026-03-04     T1    PASS
T5YIFR                      5,795   2003-01-02 -> 2026-03-04     T1    PASS
DFF                         7,730   2005-01-03 -> 2026-03-03     T1    PASS
EFFR                        5,315   2005-01-03 -> 2026-03-04     T1    PASS
DTWEXBGS                    5,052   2006-01-02 -> 2026-02-27     T1    PASS*
VIXCLS                      5,354   2005-01-03 -> 2026-03-04     T1    PASS
SP500                       2,513   2016-02-22 -> 2026-03-04     T1    PASS**
gld_holdings_flow_confirm   1,254   2021-03-08 -> 2026-03-04     T2    PASS
CPILFESL                      252   2005-01-01 -> 2026-01-01     T2    WARN***
FEDFUNDS                      254   2005-01-01 -> 2026-02-01     T2    PASS
PCEPI                         252   2005-01-01 -> 2025-12-01     T2    WARN***
PCU2122212122210              156   2005-01-01 -> 2017-12-01     T2    PASS****
DTWEXM                      3,775   2005-01-03 -> 2019-12-31     --    discontinued
DTWEXO                      3,775   2005-01-03 -> 2019-12-31     --    discontinued
TWEXB                         783   2005-01-03 -> 2020-01-01     --    discontinued

*    DTWEXBGS: FRED publishes with ~1 week structural lag. Threshold = 10 days.
**   SP500: FRED only has data from 2016. Known gap — fix via SPY (Yahoo) planned.
***  CPILFESL/PCEPI: BLS/BEA monthly release lag. Warnings expected and correct.
**** PCU2122212122210: Discontinued 2017. Staleness check disabled (threshold=9999d).
```

**Quality gate verdict as of 2026-03-06: ✅ PASS — 15/15 Tier-1 series fresh**

---

## 4. Series Registry

### Tier-1 Series (block snapshot if stale)

| series_id | Description | Source | Threshold | History |
|---|---|---|---|---|
| `gold_price_proxy` | Gold spot XAUUSD | Stooq JSON + Yahoo | 3 days | 2014-present |
| `rates_vol_stress_move` | MOVE Index bond stress | Yahoo (`^MOVE`) | 3 days | 2021-present |
| `DFII10` | 10Y TIPS real yield | FRED API | 3 days | 2003-present |
| `DFII5` | 5Y TIPS real yield | FRED API | 3 days | 2003-present |
| `DGS10` | 10Y Treasury nominal yield | FRED API | 3 days | 2005-present |
| `DGS2` | 2Y Treasury nominal yield | FRED API | 3 days | 2005-present |
| `DGS5` | 5Y Treasury nominal yield | FRED API | 3 days | 2005-present |
| `T10YIE` | 10Y breakeven inflation | FRED API | 3 days | 2003-present |
| `T5YIE` | 5Y breakeven inflation | FRED API | 3 days | 2003-present |
| `T5YIFR` | 5Y/5Y forward inflation | FRED API | 3 days | 2003-present |
| `DFF` | Effective fed funds rate | FRED API | 3 days | 2005-present |
| `EFFR` | NY Fed EFFR | FRED API | 3 days | 2005-present |
| `DTWEXBGS` | Broad USD index (goods) | FRED API | **10 days** | 2006-present |
| `VIXCLS` | VIX equity implied vol | FRED API | 3 days | 2005-present |
| `SP500` | S&P 500 index | FRED API | 3 days | 2016-present |

### Tier-2 Series (warn only — never block snapshot)

| series_id | Description | Source | Threshold | History |
|---|---|---|---|---|
| `gld_holdings_flow_confirm` | GLD Trust ounces held | SPDR archive CSV | 5 days | 2021-present |
| `CPILFESL` | Core CPI | FRED API | 45 days | 2005-present |
| `FEDFUNDS` | Fed funds rate monthly avg | FRED API | 45 days | 2005-present |
| `PCEPI` | Headline PCE | FRED API | 45 days | 2005-present |
| `PCU2122212122210` | PPI: Gold ore mining | FRED API | disabled | 2005-2017 |

> **GLD note:** Source is the SPDR State Street archive CSV (`source="spdr_gld_archive"`). Formula: `ounces = shares_outstanding x 0.09585`. Verified March 2026: 260,300,000 × 0.09585 = 24,949,755 oz = 776.0 tonnes. This is an approximation — shares_outstanding applied uniformly to past dates, not true historical per-day data. `is_estimate=true` in registry. Label clearly in any backtest output.

---

## 5. Known Gaps & Issues

| Series | Issue | Fix needed |
|---|---|---|
| SP500 | Only goes back to 2016 | Use SPY via Yahoo (goes to 1993) |
| DTWEXM | Discontinued 2019, in DB | Bridge with DTWEXBGS or drop |
| DTWEXO | Discontinued 2019, in DB | Bridge with DTWEXBGS or drop |
| TWEXB | Discontinued 2020, weekly | Bridge with DTWEXBGS or drop |
| Gold history | Starts 2014, target is 2005 | Extend backfill via Stooq |
| GLD history | Approximation only | Accept or find paid source |
| AlphaVantage | `alphavangtage.json` unused | Wire into observations table |

**Backtest start date:** `2014-01-02` — limited by gold JSON.  
Target: extend gold to 2005 to gain 2008 crisis + 2011 peak.

---

## 6. Database Schema

Local SQLite: `layer2_truth.db` — **not in GitHub** (gitignored).

```sql
-- Core observations store (immutable, rev-0 only for now)
CREATE TABLE observations (
    series_id       TEXT      NOT NULL,
    obs_ts          DATE      NOT NULL,
    as_of_ts        TIMESTAMP NOT NULL,
    value           REAL      NOT NULL,
    revision_seq    INTEGER   NOT NULL DEFAULT 0,
    source          TEXT      NOT NULL,
    ingested_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (series_id, obs_ts, revision_seq)
);

CREATE INDEX idx_obs_series_date ON observations (series_id, obs_ts DESC);

-- Snapshot registry (one row per published snapshot)
CREATE TABLE snapshots (
    snapshot_id     TEXT      PRIMARY KEY,
    clock_ts        TIMESTAMP NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verdict         TEXT      NOT NULL,
    tier1_series    INTEGER   NOT NULL,
    tier1_pass      INTEGER   NOT NULL,
    tier1_fail      INTEGER   NOT NULL,
    tier2_series    INTEGER   NOT NULL,
    tier2_warn      INTEGER   NOT NULL,
    series_count    INTEGER   NOT NULL,
    dry_run         INTEGER   NOT NULL DEFAULT 0,
    forced          INTEGER   NOT NULL DEFAULT 0
);

CREATE INDEX idx_snapshots_clock ON snapshots (clock_ts DESC);

-- Snapshot values (one row per series per snapshot)
CREATE TABLE snapshot_values (
    snapshot_id     TEXT      NOT NULL,
    series_id       TEXT      NOT NULL,
    tier            INTEGER   NOT NULL,
    group_name      TEXT      NOT NULL,
    obs_ts          DATE      NOT NULL,
    value           REAL      NOT NULL,
    staleness_days  INTEGER   NOT NULL,
    source          TEXT      NOT NULL,
    PRIMARY KEY (snapshot_id, series_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
);
```

> **Layer-3 contract — two valid interfaces, one forbidden:**
> - **DB interface:** query `snapshots` by `snapshot_id`, then join `snapshot_values` for series values
> - **File interface:** read `latest_snapshot.json` (stable top-level fields: `snapshot_id`, `clock_ts`, `verdict`, `tier1_series`, `tier2_series`, `missing_series`)
> - **Forbidden:** querying `observations` directly — Layer-3 must never do this
>
> Both DB and file interfaces are valid. Choose one consistently per consumer.

---

## 7. The Six Adapters

### A. Gold Adapter (`gold_adapter.py`) — Tier-1, M0

**Primary asset state. Missing or stale = NO snapshot published.**

Source: Local JSON -> Stooq live -> Yahoo Finance (GC=F)

```bash
# First-time setup
python layer2\adapters\gold_adapter.py --load-json FRED\2014GOLD\gold_xauusd_stooq_2014_yesterday.json --live

# Daily EOD job
python layer2\adapters\gold_adapter.py --live --backfill-days 5

# Staleness check
python layer2\adapters\gold_adapter.py --staleness-check-only
```

---

### B. MOVE Adapter (`move_adapter.py`) — Tier-1, M1

**Rates-vol / bond-stress sensor. Missing = NO snapshot published.**

Source: Yahoo Finance (`^MOVE`). Stooq unreliable on weekends.

```bash
# Daily EOD job
python layer2\adapters\move_adapter.py --source yahoo

# Backfill 5 years (run once after setup)
python layer2\adapters\move_adapter.py --source yahoo --backfill-days 1825

# Staleness check
python layer2\adapters\move_adapter.py --staleness-check
```

---

### C. GLD Holdings Adapter (`gld_holdings_adapter.py`) — Tier-2, M2

**Flow confirmation only. Never blocks snapshot.**

Source: SPDR State Street archive CSV (`source="spdr_gld_archive"`). Stores `is_estimate=true`.

Formula: `ounces = shares_outstanding x 0.09585`  
Verified March 2026: 260,300,000 x 0.09585 = 24,949,755 oz = 776.0 tonnes  
⚠️ Approximation — shares_outstanding applied uniformly to past dates, not true historical per-day data.

```bash
# Daily EOD job
python layer2\adapters\gld_holdings_adapter.py

# Backfill 5 years (run once after setup)
python layer2\adapters\gld_holdings_adapter.py --backfill-days 1825

# Staleness check
python layer2\adapters\gld_holdings_adapter.py --staleness-check-only
```

---

### D. FRED Loader (`fred_loader.py`) — Tier-1 + Tier-2

**Loads all 20 FRED series. Requires FRED API key in `.secrets/fred_api_key.txt`**

Get a free key at: https://fredaccount.stlouisfed.org/apikeys

```bash
# Full history load (first time — ~20 seconds, 80,000+ rows)
python layer2\adapters\fred_loader.py --full-history

# Daily EOD top-up
python layer2\adapters\fred_loader.py --backfill-days 5

# Single series refresh
python layer2\adapters\fred_loader.py --series DGS10 DFII10 --backfill-days 30

# Status report
python layer2\adapters\fred_loader.py --status

# Dry-run
python layer2\adapters\fred_loader.py --backfill-days 5 --dry-run
```

---

### E. Quality Gate (`quality_gate.py`) — Snapshot gatekeeper

**Checks all 23 series, computes verdict, saves JSON report.**  
Run before any snapshot is published. Exit code: 0 = PASS, 1 = FAIL.

```bash
# Run quality gate (standard)
python layer2\adapters\quality_gate.py

# Override clock date (replay / testing)
python layer2\adapters\quality_gate.py --clock-date 2026-03-03

# Quiet mode (verdict only)
python layer2\adapters\quality_gate.py --quiet

# Custom report path
python layer2\adapters\quality_gate.py --report-path reports\quality.json
```

**Expected output (healthy):**
```
[INFO] Tier-1: 15/15 PASS | 0 FAIL
[INFO] VERDICT: ✓ PASS — snapshot may be published
[INFO] Quality report saved to: layer2_quality_report.json
```

> `layer2_quality_report.json` is gitignored — generated fresh on each run.

---

### F. Snapshot Publisher (`snapshot_publisher.py`) — Layer-3 contract boundary

**Runs quality gate internally, then publishes a point-in-time snapshot. Layer-3 reads this — nothing else.**

Exit code: 0 = snapshot published (or already exists), 1 = quality gate FAIL or completeness error.

```bash
# Preview without writing anything
python layer2\adapters\snapshot_publisher.py --dry-run

# Publish snapshot for today
python layer2\adapters\snapshot_publisher.py

# Publish for a specific past date (replay)
python layer2\adapters\snapshot_publisher.py --clock-date 2026-03-05

# List recent snapshots
python layer2\adapters\snapshot_publisher.py --list

# Skip quality gate (TESTING ONLY — snapshot flagged forced=True)
python layer2\adapters\snapshot_publisher.py --force
```

**Outputs:**
- `snapshots` table in DB — one row per published snapshot
- `snapshot_values` table in DB — one row per series per snapshot
- `latest_snapshot.json` — stable JSON for Layer-3 consumption (gitignored)

**Key fields in `latest_snapshot.json`:**
```json
{
  "snapshot_id": "<64-char sha256>",
  "clock_ts": "2026-03-06T21:00:00+00:00",
  "clock_date": "2026-03-06",
  "verdict": "PASS",
  "forced": false,
  "tier1_series": { ... },
  "tier2_series": { ... },
  "missing_series": []
}
```

> `latest_snapshot.json` is gitignored — generated fresh on each publish.

---

## 8. Engine Clock & Alignment Rules

- **One clock per day:** 21:00 UTC (NYSE close + FRED EOD release window)
- **Alignment:** latest observation where `obs_ts <= clock_ts`
- **Tie-break:** highest `revision_seq` wins. Equal -> latest `ingested_at` wins.
- **Clock never goes backwards** — replays always use original `clock_ts`
- **Weekend behavior:** clock ticks daily; staleness window absorbs weekend gaps

---

## 9. Quality Gate Rules

| Tier | Series | Staleness threshold | Effect if stale |
|---|---|---|---|
| Tier-1 | gold, MOVE, yields, USD, VIX, SP500 | 3 days (DTWEXBGS: 10 days) | Blocks snapshot |
| Tier-2 | GLD, CPI, PCE, FEDFUNDS | 5-45 days | Warning only |

**Fail-closed:** any Tier-1 FAIL -> publish NOTHING -> Layer-3 outputs nothing.

---

## 10. What Still Needs to Be Built

| Component | Status | Priority |
|---|---|---|
| Gold adapter | ✅ DONE | - |
| MOVE adapter | ✅ DONE | - |
| GLD holdings adapter | ✅ DONE | - |
| FRED loader (20 series) | ✅ DONE | - |
| Quality gate | ✅ DONE | - |
| Snapshot publisher (`snapshot_publisher.py`) | ✅ DONE | - |
| Series registry JSON (`series_registry.json`) | ✅ DONE | - |
| Registry loader + validator (`registry.py`) | ✅ DONE | - |
| Wire `snapshot_publisher.py` → registry | ⬜ NEXT — do first | **High** |
| Wire `quality_gate.py` → registry | ⬜ NEXT | **High** |
| Wire `fred_loader.py` → registry | ⬜ NEXT | **High** |
| `--full-reload` CLI help text update (behavior changed under `INSERT OR IGNORE`) | ⬜ TODO | Medium |
| Revision writer (`revision_seq=1` path for FRED corrections) | ⬜ TODO | Medium |
| Daily scheduler (Windows Task Scheduler) | ⬜ TODO | Medium |
| Extend gold history to 2005 | ⬜ TODO | Medium |
| Fix SP500 history (use SPY via Yahoo) | ⬜ TODO | Medium |
| Fix/replace discontinued USD series | ⬜ TODO | Low |
| Feature Builder (Layer-3) | ⬜ TODO | After registry wiring done |
| Index Suite (Layer-3) | ⬜ TODO | After Feature Builder |
| Decision Engine (Layer-3) | ⬜ TODO | After Index Suite |

### Next session — do in this exact order:
1. **`snapshot_publisher.py`** — wire to registry first (it is the contract boundary toward Layer-3 — most important to get right)
2. **`quality_gate.py`** — replace `SERIES_CHECKS` with registry
3. **`fred_loader.py`** — replace `SERIES_CONFIG` with registry

Why this order: `snapshot_publisher.py` defines what Layer-3 sees — if its series list is wrong, Layer-3 gets wrong data. Registry bugs are caught by `python -m layer2.config.registry --validate` before any wiring. The gate and loader are wired second and third because they are internal components that feed the publisher, not the boundary itself.

---

## 11. "Layer-3 Ready" Checklist

Layer-3 must never read "latest" data directly. This checklist defines what "ready" means:

```
Step 1: quality_gate.py runs
        -> VERDICT: PASS (15/15 Tier-1 fresh)        ✅ WORKING

Step 2: snapshot_publisher.py runs
        -> Runs quality gate internally (self-contained)
        -> Reads DB at fixed clock_ts (21:00 UTC daily)
        -> Computes snapshot_id (full sha256, deterministic)
        -> Writes to DB (snapshots + snapshot_values tables)
        -> Writes latest_snapshot.json                ✅ WORKING
           First snapshot: feb94eb7dc719c0e2779456964f74d0454cbbcfcab64ad6f5665f4f0972b204d
           Published:      2026-03-06T21:00:00+00:00

Step 3: Layer-3 reads snapshot_id                    ⬜ NOT BUILT YET
        -> Reads latest_snapshot.json or queries snapshots table by snapshot_id
        -> Never reads observations directly
        -> Consumes only the published snapshot
        -> If no snapshot_id exists -> Layer-3 outputs nothing

Current state: Steps 1 and 2 complete. Step 3 not yet built.
Registry is built and validated. Three adapters not yet wired to it.
```

---

## 12. How to Set Up Locally (for your friend)

### Prerequisites
- Python 3.10+ installed
- Git installed
- Free FRED API key from https://fredaccount.stlouisfed.org/apikeys

### Step-by-step

```bash
# Step 1: Clone
git clone https://github.com/balazsv27-rgb/Mr-Ripley.git
cd Mr-Ripley

# Step 2: Create venv
python -m venv venv
.\venv\Scripts\activate        # Windows
source venv/bin/activate       # Mac/Linux

# Step 3: Install dependencies
pip install yfinance

# Step 4: Add FRED API key
mkdir .secrets
echo your_fred_api_key_here > .secrets\fred_api_key.txt

# Step 5: Load gold backfill (first time only)
python layer2\adapters\gold_adapter.py --load-json FRED\2014GOLD\gold_xauusd_stooq_2014_yesterday.json --live

# Step 6: Load MOVE and GLD (5 year backfill)
python layer2\adapters\move_adapter.py --source yahoo --backfill-days 1825
python layer2\adapters\gld_holdings_adapter.py --backfill-days 1825

# Step 7: Load all 20 FRED series (full history — ~20 seconds)
python layer2\adapters\fred_loader.py --full-history

# Step 8: Verify everything
python layer2\adapters\quality_gate.py

# Step 9: Validate the series registry
python -m layer2.config.registry --validate

# Step 10: Publish first snapshot
python layer2\adapters\snapshot_publisher.py --dry-run   # preview first
python layer2\adapters\snapshot_publisher.py             # publish for real
```

**You should see: `VERDICT: ✓ PASS — snapshot may be published`**  
**Then: `snapshot_id: <64-char hash>` and `latest_snapshot.json` written.**

---

## 13. Key Decisions & Why

| Decision | Why |
|---|---|
| SQLite for DB | Simple, portable, no server. Can migrate to Postgres later. |
| Yahoo for MOVE | Stooq `^move` returns "No data" on weekends. Yahoo confirmed working. |
| GLD ounces = shares x 0.09585 | State Street CSV broke (returns PDF). Formula verified: 776 tonnes. |
| GLD source = `spdr_gld_archive` | SPDR State Street archive CSV is the actual fetch source. `is_estimate=true` because shares_outstanding applied uniformly to past dates — not true per-day historical. Registry, adapter, and README now consistent. |
| Gold from JSON + live top-up | Avoids Stooq rate limits for 12 years of history. |
| FRED for 20 series | Single API, free, full history for all target series. |
| DTWEXBGS threshold = 10 days | Structural ~1 week FRED publish lag. Not a data error. |
| PCU2122212122210 disabled | Discontinued 2017. Staleness check meaningless. |
| Tier-1 staleness = 3 days | Covers weekends (2 days) + 1 day FRED release lag. |
| Fail-closed snapshots | Prevents Layer-3 deciding on stale or incomplete data. |
| Backtest start = 2014-01-02 | Limited by gold JSON. Extend to 2005 when possible. |
| .secrets/ gitignored | API keys must never be committed to GitHub. |
| layer2_truth.db gitignored | Local DB. Each developer rebuilds from adapters. |
| quality_report.json gitignored | Generated fresh each run. Committed file would be stale. |
| `INSERT OR IGNORE` not `INSERT OR REPLACE` | Truth-layer discipline: once written, a rev-0 row is immutable. Reruns never silently overwrite history. |
| No `detect_types` in sqlite3.connect() | Deprecated in Python 3.12+. All date parsing is now handled explicitly and consistently. |
| Incremental filters normalized to strings | Prevents silent str-vs-date type mismatch bugs that could cause repeated overwrites or missed dedup. |
| `revision_seq` reserved for future revisions | If FRED revises a historical value, it gets written as `revision_seq=1` — not an overwrite of `rev=0`. Not yet implemented but schema supports it. |
| `series_registry.json` as single source of truth | Prevents staleness thresholds, tier assignments, and snapshot inclusion rules from drifting across three separate files. |
| Registry validates on load (fail-fast) | Invalid entries (duplicate IDs, wrong types, Tier-1 as estimate, discontinued as blocker) are caught immediately — not silently ignored. |
| `snapshot_id` is full 64-char sha256 | Truncating hashes creates unnecessary collision risk. Full hash stored everywhere. |
| `run_ts` separate from `clock_ts` in snapshots | `clock_ts` = engine point-in-time (21:00 UTC). `run_ts` = when the code actually executed. These are different and must not be confused. |
| `forced=True` flag in snapshot DB + JSON | Snapshots created with `--force` (skipping quality gate) are permanently marked so they can be filtered out of backtests. |
| Tier-1 completeness hard fail in publisher | If publisher's series list drifts from gate's list, the snapshot is blocked rather than silently publishing an incomplete view. |

---

## 14. Code Integrity Log

This section records formal audits and fixes applied to the codebase.

### Audit 1 — 2026-03-05 (Friend's review)

Reviewer identified four issues in all adapters:

| Issue | Severity | Fix applied |
|---|---|---|
| `INSERT OR REPLACE` destroys history — not a truth store | Critical | Changed to `INSERT OR IGNORE` across all 5 files |
| Incremental filters: str vs date type mismatch causes silent overwrite risk | High | Normalized all `existing_dates` sets to strings via `.isoformat()` |
| `detect_types=sqlite3.PARSE_DECLTYPES` deprecated in Python 3.12+ | Medium | Removed from all `get_connection()` calls — date parsing now explicit |
| `latest_obs_date()` returned raw sqlite value without type safety | Medium | All date returns now handle `str`, `datetime`, and `date` objects |

**Result:** All 4 issues resolved. Quality gate confirmed PASS 15/15 after fixes. No DeprecationWarning.

**Known remaining items from audit:**

- **`--full-reload` behavioral change** — this flag previously re-wrote all rows via `INSERT OR REPLACE`. After the fix it now silently skips existing rows via `INSERT OR IGNORE`. CLI help text needs updating. Until fixed, use `--full-reload` only for backfilling missing date ranges, not for correcting existing values. ⬜ Not yet fixed.
- **Revision writer (`revision_seq=1`)** — if FRED revises a historical value, the current system ignores the revision silently. Rule when implemented: if `value differs AND (series_id, obs_ts, rev=0) already exists` → write `(series_id, obs_ts, current_as_of_ts, new_value, rev=1, source)`. ⬜ Not yet built.
- **System is currently rev-0 only** — all historical corrections are silently dropped until the revision writer is built. Acceptable for now (FRED rarely revises) but noted clearly.
- ~~Centralized staleness registry~~ — ✅ Resolved in Audit 2 below.

---

### Audit 2 — 2026-03-06 (Friend's review of snapshot_publisher + README)

Reviewer identified six issues in `snapshot_publisher.py` and one structural gap:

| Issue | Severity | Fix applied |
|---|---|---|
| `snapshot_id` truncated to 32 chars — unnecessary collision risk | Medium | Now full 64-char sha256 stored everywhere |
| `run_ts` (execution time) not logged separately from `clock_ts` (engine time) | Medium | `run_ts` added to logs and JSON output (not stored in DB — DB uses `created_at`) |
| `--force` flag produces misleading "valid-looking" snapshots | Medium | `forced=True` flag stored in DB and JSON permanently. ⚠️ Gate still skipped in this version — see Audit 4. |
| JSON missing stable API fields — Layer-3 would need to query DB | Medium | Added `tier1_series`, `tier2_series`, `missing_series` as stable top-level fields |
| Tier-1 list could drift between gate and publisher silently | Medium | Hard fail added: if Tier-1 count in snapshot < expected → snapshot blocked |
| Staleness rules split across `quality_gate.py`, `fred_loader.py`, `snapshot_publisher.py` — can drift | High | `series_registry.json` created as single source of truth. `registry.py` loader + validator built. Three adapters not yet wired (planned next session). |

**Result:** All 6 issues addressed. First real snapshot published successfully. Note: registry introduced as structural fix — consumer wiring (`snapshot_publisher.py`, `quality_gate.py`, `fred_loader.py`) still pending next session.
```
snapshot_id: feb94eb7dc719c0e2779456964f74d0454cbbcfcab64ad6f5665f4f0972b204d
clock_ts:    2026-03-06T21:00:00+00:00
series:      20
verdict:     PASS
```

**Known remaining items from audit:**
- Registry wiring — `snapshot_publisher.py`, `quality_gate.py`, `fred_loader.py` not yet reading from registry. Planned next session in that order.
- `registry_version` should be included in snapshot metadata so each snapshot records the exact config state used to produce it. Not yet implemented.

---

### Audit 3 — 2026-03-06 (Self-audit after Audit 2)

Internal review of all output files against actual terminal output found three issues:

| Issue | Severity | Fix applied |
|---|---|---|
| `forced` flag claimed stored in DB but `snapshots` table had no `forced` column | High | Added `forced INTEGER NOT NULL DEFAULT 0` to schema + `write_snapshot()` + `list_snapshots()`. One-time DB migration run: `ALTER TABLE snapshots ADD COLUMN forced`. |
| Batch hash truncated `[:16]` in `move_adapter.py`, `gold_adapter.py`, `gld_holdings_adapter.py` | Medium | All batch hashes now full 64-char sha256, consistent with `snapshot_publisher.py` |
| Section 7 titled "The Five Adapters" but contained six (A–F) | Minor | Renamed to "The Six Adapters" |
| DB schema section only showed `observations` table — `snapshots` and `snapshot_values` missing | Minor | Both tables added to schema documentation with full column list |

**Result:** All 4 issues fixed. `--list` confirmed working with `forced` column post-migration.

---

### Audit 4 — 2026-03-06 (Friend's second pass)

Two issues found that survived previous audits:

| Issue | Severity | Fix applied |
|---|---|---|
| `--force` path fabricated a hardcoded summary (`tier1_total: 15`, `tier2_total: 5`) instead of running the real gate and merely bypassing blocking | High | Quality gate now always runs. With `--force`, a FAIL verdict logs `WOULD BLOCK` warnings but does not abort. Real gate numbers always stored in DB and JSON. Hardcoded summary eliminated. |
| GLD source inconsistency: README said Yahoo, registry said `yahoo_gld_estimate`, adapter stores `spdr_gld_archive` | Medium | Registry `source` corrected to `spdr_gld_archive`. README Tier-2 table, GLD note, Section C, and Key Decisions all updated to match. All three now consistent. |

**Result:** Both issues fixed. `--force` now runs a real gate on every call. GLD source label consistent across registry, adapter, and README.

---

## 15. Useful Links

| Resource | URL |
|---|---|
| GitHub Repo | https://github.com/balazsv27-rgb/Mr-Ripley |
| FRED API | https://fred.stlouisfed.org |
| FRED API Keys | https://fredaccount.stlouisfed.org/apikeys |
| Yahoo Finance (MOVE) | https://finance.yahoo.com/quote/%5EMOVE |
| Yahoo Finance (GLD) | https://finance.yahoo.com/quote/GLD |
| Yahoo Finance (Gold futures) | https://finance.yahoo.com/quote/GC%3DF |
| GLD Trust Info | https://www.spdrgoldshares.com |
| yfinance docs | https://ranaroussi.github.io/yfinance |

---

## 16. Contact & Collaboration

- **Mr. Ripley repo owner:** @balazsv27-rgb
- **Architecture decisions:** Documented in `architecture4.md.txt`, `architeture.md`
- **Questions:** Open a GitHub Issue on the repo

---

*Read this before touching any code. For questions open a GitHub Issue on the repo.*

