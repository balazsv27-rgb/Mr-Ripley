# Mr. Ripley — Layer-2 Truth Layer
## What We Built & How to Use It

> **For:** Friend / collaborator reading this on GitHub  
> **Repo:** https://github.com/balazsv27-rgb/Mr-Ripley  
> **Last updated:** March 2026

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
│   │   └── quality_gate.py            # Staleness checker + snapshot verdict
│   ├── config/
│   │   └── series_registry.json       # Series metadata (MOVE + GLD entries)
│   └── README_LAYER2.md               # This file
├── layer2_truth.db                    # SQLite DB (local only — gitignored)
├── layer2_quality_report.json         # Quality gate output (local only — gitignored)
├── alphavangtage.json                 # AlphaVantage daily data (unused, future use)
├── fix_encoding.py                    # Utility: fixes special characters in .py files
├── fix_docstring.py                   # Utility: fixes missing docstring quotes
└── venv/                              # Python virtual environment (local only)
```

---

## 3. Current DB State (as of March 2026)

```
observations table — ~85,700 rows across 23 series

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

**Quality gate verdict as of 2026-03-05: ✅ PASS — 15/15 Tier-1 series fresh**

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
| `gld_holdings_flow_confirm` | GLD Trust ounces held | Yahoo (`GLD`) | 5 days | 2021-present |
| `CPILFESL` | Core CPI | FRED API | 45 days | 2005-present |
| `FEDFUNDS` | Fed funds rate monthly avg | FRED API | 45 days | 2005-present |
| `PCEPI` | Headline PCE | FRED API | 45 days | 2005-present |
| `PCU2122212122210` | PPI: Gold ore mining | FRED API | disabled | 2005-2017 |

> **GLD note:** Yahoo gives today's `shares_outstanding` only — not true historical.
> Applied uniformly to past dates using `ounces = shares_outstanding x 0.09585`.
> This is an approximation. Label clearly in any backtest output.

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
```

---

## 7. The Five Adapters

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

Formula: `ounces = shares_outstanding x 0.09585`  
Verified March 2026: 260,300,000 x 0.09585 = 24,949,755 oz = 776.0 tonnes

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
| Snapshot publisher (`snapshot_publisher.py`) | NOT STARTED | **High — blocks Layer-3** |
| Centralize staleness registry (one config feeds gate + adapters) | NOT STARTED | Medium |
| `--full-reload` CLI help text update (behavior changed under `INSERT OR IGNORE`) | NOT STARTED | Medium |
| Revision writer (`revision_seq=1` path for FRED corrections) | NOT STARTED | Medium |
| Daily scheduler (Windows Task Scheduler) | NOT STARTED | Medium |
| Extend gold history to 2005 | NOT STARTED | Medium |
| Fix SP500 history (use SPY via Yahoo) | NOT STARTED | Medium |
| Fix/replace discontinued USD series | NOT STARTED | Low |
| Feature Builder (Layer-3) | NOT STARTED | After snapshots |
| Index Suite (Layer-3) | NOT STARTED | After Feature Builder |
| Decision Engine (Layer-3) | NOT STARTED | After Index Suite |

---

## 10a. "Layer-3 Ready" Checklist

Layer-3 must never read "latest" data directly. This checklist defines what "ready" means:

```
Step 1: quality_gate.py runs
        -> VERDICT: PASS (15/15 Tier-1 fresh)

Step 2: snapshot_publisher.py runs   <- NOT BUILT YET
        -> Reads DB at fixed clock_ts
        -> Writes snapshot_id (hash of series values + clock_ts)
        -> Stores snapshot to snapshots table

Step 3: Layer-3 reads snapshot_id    <- NOT BUILT YET
        -> Never reads observations directly
        -> Consumes only the published snapshot
        -> If no snapshot_id exists -> outputs nothing

Current state: Step 1 complete. Steps 2 and 3 not yet built.
Layer-3 is NOT yet ready to consume data.
```

---

## 11. How to Set Up Locally (for your friend)

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
```

**You should see: `VERDICT: ✓ PASS — snapshot may be published`**

---

## 12. Key Decisions & Why

| Decision | Why |
|---|---|
| SQLite for DB | Simple, portable, no server. Can migrate to Postgres later. |
| Yahoo for MOVE | Stooq `^move` returns "No data" on weekends. Yahoo confirmed working. |
| GLD ounces = shares x 0.09585 | State Street CSV broke (returns PDF). Formula verified: 776 tonnes. |
| GLD is approximation | Yahoo gives today's shares only. Applied to past dates uniformly. |
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

---

## 13. Code Integrity Log

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

- **Centralized staleness registry** — one config feeds both gate + adapters. Currently thresholds are hardcoded in two places and can drift. Not yet built.
- **`--full-reload` behavioral change** — this flag previously re-wrote all rows via `INSERT OR REPLACE`. After the fix it now silently skips existing rows via `INSERT OR IGNORE`. The flag name implies a full reload but no longer delivers one. CLI help text needs updating. Until fixed, use `--full-reload` only for backfilling missing date ranges, not for correcting existing values.
- **Revision writer (`revision_seq=1`)** — if FRED revises a historical value, the current system ignores the revision silently (INSERT OR IGNORE drops it). A revision writer needs to detect value changes and write `revision_seq=1` rows instead. Rule when implemented: if `value differs AND (series_id, obs_ts, rev=0) already exists` → write `(series_id, obs_ts, current_as_of_ts, new_value, rev=1, source)`.
- **System is currently rev-0 only** — all historical corrections are silently dropped until the revision writer is built. This is acceptable for now as FRED rarely revises, but must be noted clearly.

---

## 14. Useful Links

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

## 15. Contact & Collaboration

- **Mr. Ripley repo owner:** @balazsv27-rgb
- **Architecture decisions:** Documented in `architecture4.md.txt`, `architeture.md`
- **Questions:** Open a GitHub Issue on the repo

---

*Read this before touching any code. For questions open a GitHub Issue on the repo.*

