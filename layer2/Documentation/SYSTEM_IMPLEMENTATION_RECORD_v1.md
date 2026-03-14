# SYSTEM_IMPLEMENTATION_RECORD_v1
## Mr. Ripley — Build Record and Implementation Notes

> **Document role:** detailed implementation record and historical technical reference
> **Status:** retained as a long-form build / implementation document
> **Current entry-point document:** `README_v1.md`
> **Current engineering reference:** `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
> **Current limitations / approximations doc:** `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
> **Current architecture / sequencing doc:** `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`

This document is retained as a **detailed implementation record** for the Mr. Ripley system.
It contains long-form technical detail such as:
- Layer-2 build state and implementation notes
- adapter usage and source-specific caveats
- schema and storage details
- quality gate and snapshot publication notes
- audit / integrity history
- revision history and build evolution

This document is **not** the primary entry-point document and should **not** be treated as the single source of truth for current-state interpretation.

If this document conflicts with the v1 documentation set, the **v1 documents take precedence** for current-state interpretation.

---

## Document Position in the Documentation Set

Use the documentation set as follows:

| Document | Role |
|---|---|
| `README_v1.md` | Short entry-point summary for engineers onboarding into the repo |
| `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Structured engineering reference for the current system state |
| `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Explicit record of known gaps, approximations, and interpretation risks |
| `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architecture framing, handoff sequencing, Layer-3 bootstrap boundary, and later live-execution gate |
| `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Long-form build record, implementation notes, audit history, and detailed technical reference |

### Interpretation rule

- Use the **README** for the current short-form project position.
- Use the **Technical Handbook** for structured engineering truth.
- Use the **Limitations / Approximations** document for risk-aware interpretation.
- Use the **Architecture / Build Sequence** document for target architecture and sequencing boundaries.
- Use **this document** for historical build detail, implementation notes, and long-form technical record.

### Precedence rule

If a statement in this document conflicts with the current v1 documentation set, prefer:

1. `README_v1.md`
2. `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
3. `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
4. `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`

This document remains useful as a detailed build record, but it is no longer the canonical short-form current-state document.

## What This Document Preserves

This file preserves the detailed build and implementation history of the Mr. Ripley truth-layer foundation.
It is intentionally longer and more detailed than the current README and technical handbook.
Its purpose is to retain:
- implementation-level notes
- adapter and schema detail
- build-state context
- audit and integrity history
- evolution of the Layer-2 truth-layer foundation

It may also include references to Layer-3 bootstrap needs and later execution boundaries where those were relevant to implementation decisions, but it should not be read as the canonical source for current system-wide status.

For current-state interpretation, use the v1 document set first.

## How to Use This Document

Read this document when you need:
- implementation detail beyond the entry-point README
- historical build context
- adapter-by-adapter operational notes
- schema-level or pipeline-level detail
- audit-history context for why the current Layer-2 system looks the way it does

Do not use this document alone to determine current bootstrap readiness, live execution readiness, or final contract interpretation.
For those, consult the v1 documentation set first.

---

# System Implementation Record — Retained Implementation Detail
## (Original: README_LAYER2_v10.md — preserved as long-form reference)


> **For:** Friend / collaborator reading this on GitHub
> **Repo:** https://github.com/balazsv27-rgb/Mr-Ripley
> **Last updated:** 2026-03-07
> **Preserved original body version:** v10 — see Section 18 (Revision Log) for preserved change summary

---

## Preserved Original Revision Summary (v8 → v9)

The following changes were made in this revision.

| # | Section | Change | Reason |
|---|---|---|---|
| 1 | NEW §17 | Added "Roadmap Project Management" section | Practical PM-style roadmap was missing as a standalone section |
| 2 | §17 (was) | Renumbered "Revision Log" from §17 → §18 | Required by insertion of new §17 |
| 3 | §18 (was) | Renumbered "Useful Links" from §18 → §19 | Required by insertion of new §17 |
| 4 | §18 | Added v9 entry to Revision Log | Version tracking |

---

## 1. What Is Layer-2?

Layer-2 is the **data ingestion and truth store** for the Gold-First Market State Engine (Mr. Ripley).

```
Layer-1  ->  Event Tagger / Narrative Risk Modifiers (optional, disabled by default)
Layer-2  ->  Ingestion + validation + immutable snapshots  <- YOU ARE HERE
Layer-3  ->  Feature builder + index suite + decision engine
```

**The golden rule of Layer-2:**
Layer-3 is NEVER allowed to read "latest" data directly. It can ONLY consume a published
`snapshot_id`. If data is missing or stale → no snapshot is published → Layer-3 outputs
nothing. This is called **fail-closed** behavior.

---

## 1a. TL;DR — Critical Rules (Read This First)

> These five rules are non-negotiable. Everything else in this document supports them.

| # | Rule |
|---|---|
| 1 | **Validate registry first** — run `python -m layer2.config.registry --validate` before any publish |
| 2 | **Run quality gate** — `quality_gate.py` must PASS before a snapshot is published |
| 3 | **Publish snapshot** — `snapshot_publisher.py` is the only write path to the Layer-3 contract |
| 4 | **Layer-3 reads snapshots only** — consume `latest_snapshot.json` or query `snapshots`+`snapshot_values` by `snapshot_id` |
| 5 | **Never query `observations` directly** — this is forbidden for any Layer-3 consumer |

> **Layer-2 non-goals:** Layer-2 does not compute regimes, make supervisor decisions,
> or generate execution actions. It ends at validated snapshot publication.
> Everything beyond that boundary belongs to Layer-3.

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
│   │   │                              #   Must contain "registry_version" key — consumed
│   │   │                              #   by snapshot_publisher as config_version
│   │   └── registry.py               # Registry loader + validator
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

> **Note:** Row counts and date ranges below are a point-in-time example from a local rebuild
> on 2026-03-07. Your counts may differ slightly after additional backfills or daily top-ups.
> The series list and tier assignments are the authoritative reference; the numbers are illustrative.

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
**   SP500: FRED only has data from 2016. Known gap — fix via SPY (Yahoo) planned. [HIGH PRIORITY]
***  CPILFESL/PCEPI: BLS/BEA monthly release lag. Warnings expected and correct.
**** PCU2122212122210: Discontinued 2017. Staleness check disabled (threshold=9999d).
```

**Quality gate verdict as of 2026-03-06: ✅ PASS — 15/15 Tier-1 series fresh**

**snapshots table:** `engine_version` and `config_version` columns now present.
Existing rows auto-migrated to `UNKNOWN_ENGINE_VERSION` / `UNKNOWN_CONFIG_VERSION`
on next `get_connection(with_snapshot_tables=True)` call (handled by `_ensure_snapshot_schema_migrations()`).

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
| `gld_holdings_flow_confirm` | GLD Trust ounces held | Yahoo (`GLD` via yfinance) | 5 days | 2021-present |
| `CPILFESL` | Core CPI | FRED API | 45 days | 2005-present |
| `FEDFUNDS` | Fed funds rate monthly avg | FRED API | 45 days | 2005-present |
| `PCEPI` | Headline PCE | FRED API | 45 days | 2005-present |
| `PCU2122212122210` | PPI: Gold ore mining | FRED API | disabled | 2005-2017 |

> **GLD note:** Source is Yahoo Finance via yfinance (`source="yahoo_gld_proxy"`).
> Formula: `ounces = shares_outstanding × 0.09585` (fixed per GLD prospectus).
> Verified March 2026: 260,300,000 × 0.09585 = 24,949,755 oz = 776.0 tonnes.
> `is_estimate=true` in registry — shares_outstanding applied uniformly to past dates,
> not true historical per-day data. Label clearly in any backtest output.

---

## 5. Known Gaps & Issues

| Series / Area | Issue | Priority | Fix needed |
|---|---|---|---|
| SP500 | Only goes back to 2016; backtest needs 2014 | **HIGH** | Use SPY via Yahoo (goes to 1993) |
| Gold history | Starts 2014, target is 2005 | Medium | Extend backfill via Stooq |
| DTWEXM / DTWEXO / TWEXB | Discontinued series in DB | Low | Bridge with DTWEXBGS or drop |
| GLD history | Approximation only — uniform shares across dates | Low | Accept or find paid source |
| AlphaVantage | `alphavangtage.json` unused | Low | Wire into observations table |
| `revision_risk` | Not tracked; monthly macro series carry unacknowledged revision exposure | Medium | Add column to `observations`; populate for FRED monthly series |
| Revision writer | `revision_seq=1` path not built; FRED corrections silently dropped | Medium | Implement rev-1 write path |
| `--full-reload` help text | Describes deprecated `INSERT OR REPLACE` behavior | Low | Update help text across all 4 adapters |

**Backtest start date:** `2014-01-02` — limited by gold JSON.
**SP500 gap is HIGH priority** — 2015 China shock and early 2016 selloff fall in the missing window,
affecting calibration validity.

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
-- engine_version and config_version added in db.py v2 (2026-03-07)
-- Existing DBs are auto-migrated via _ensure_snapshot_schema_migrations()
CREATE TABLE snapshots (
    snapshot_id     TEXT      PRIMARY KEY,
    clock_ts        TIMESTAMP NOT NULL,
    engine_version  TEXT      NOT NULL,   -- e.g. "gold-v3.3.0" — set via L2_ENGINE_VERSION env var
    config_version  TEXT      NOT NULL,   -- registry_version from series_registry.json
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

-- Composite index for version-locked replay queries
CREATE INDEX idx_snapshots_clock_engine_config
ON snapshots (clock_ts DESC, engine_version, config_version);

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

> **Important — `series_registry.json` must contain `registry_version`:**
> `snapshot_publisher.py` reads `registry_version` from the registry JSON file and
> stores it as `config_version` in every snapshot. If this key is missing,
> `_get_config_version()` raises `RuntimeError` and publishing is blocked.
> Run `python -m layer2.config.registry --validate` to confirm the key is present
> before publishing.

> **Layer-3 contract — two valid interfaces, one forbidden:**
> - **DB interface:** query `snapshots` by `snapshot_id`, then join `snapshot_values` for series values — this is the **canonical persisted interface**
> - **File interface:** read `latest_snapshot.json` (stable top-level fields: `snapshot_id`,
>   `engine_version`, `config_version`, `clock_ts`, `verdict`, `tier1_series`, `tier2_series`,
>   `missing_series`) — this is the **convenience handoff interface**
> - **Forbidden:** querying `observations` directly — Layer-3 must never do this

---

## 7. The Six Adapters

### A. Gold Adapter (`gold_adapter.py`) — Tier-1, M0

**Primary asset state. Missing or stale = NO snapshot published.**

Source: Local JSON → gold-api.com spot → Yahoo Finance (GC=F) → Stooq

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

Source: Yahoo Finance via yfinance (`source="yahoo_gld_proxy"`). Stores `is_estimate=true`.

Formula: `ounces = shares_outstanding × 0.09585`
Verified March 2026: 260,300,000 × 0.09585 = 24,949,755 oz = 776.0 tonnes
⚠️ Approximation — shares_outstanding applied uniformly to past dates, not true historical per-day data.

```bash
# Daily EOD job
python layer2\adapters\gld_holdings_adapter.py

# Backfill 5 years (run once after setup)
python layer2\adapters\gld_holdings_adapter.py --start-date 2021-01-01

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

**Runs quality gate internally, then publishes a point-in-time snapshot.
Layer-3 reads this — nothing else.**

Exit code: 0 = snapshot published (or already exists), 1 = quality gate FAIL or completeness error.

**Environment variables (set before running in production):**

| Variable | Default | Description |
|---|---|---|
| `L2_ENGINE_VERSION` | `gold-v3.3.0` | Engine version tag — stored in every snapshot |
| `L2_REGISTRY_PATH` | `series_registry.json` | Path to registry file for config_version resolution |
| `L2_DB_PATH` | `layer2_truth.db` | SQLite DB path |
| `L2_SNAPSHOT_PATH` | `latest_snapshot.json` | JSON output path |
| `L2_CLOCK_TIMEZONE` | `UTC` | Clock timezone |
| `L2_CLOCK_CUT_HOUR` | `22` | Daily cut hour |

```bash
# Preview without writing anything
python layer2\adapters\snapshot_publisher.py --dry-run

# Publish snapshot for today
python layer2\adapters\snapshot_publisher.py

# Publish for a specific past date (replay)
python layer2\adapters\snapshot_publisher.py --date 2026-03-05

# List recent snapshots (now shows engine_version + config_version)
python layer2\adapters\snapshot_publisher.py --list

# Skip quality gate block (TESTING ONLY — snapshot flagged forced=True)
python layer2\adapters\snapshot_publisher.py --force
```

> **CLI flag change (v2):** `--clock-date` is now `--date`. `--db` is now `--db-path`.
> Update any scheduler scripts that use the old flag names.

**Outputs:**
- `snapshots` table in DB — one row per published snapshot (includes `engine_version`, `config_version`)
- `snapshot_values` table in DB — one row per series per snapshot
- `latest_snapshot.json` — stable JSON for Layer-3 consumption (gitignored)

**Key fields in `latest_snapshot.json`:**
```json
{
  "snapshot_id": "<64-char sha256>",
  "engine_version": "gold-v3.3.0",
  "config_version": "<registry_version from series_registry.json>",
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

**Snapshot ID computation (v2):**
The `snapshot_id` SHA-256 hash now includes `engine_version` and `config_version`
in its payload, in addition to `clock_ts` and series values. This means two snapshots
for the same `clock_ts` but different engine or config versions produce different IDs.
Snapshot deduplication also checks all three fields — the same `clock_ts` can have
multiple valid snapshots under different versions.

---

## 8. Engine Clock & Alignment Rules

- **One clock per day:** 22:00 UTC (configurable via `L2_CLOCK_CUT_HOUR`) — this is an operational policy choice timed after US market close and primary vendor data refresh windows, not a universal natural truth
- **Alignment:** latest observation where `obs_ts <= clock_date` AND `as_of_ts <= clock_ts`
- **Tie-break:** `obs_ts DESC, as_of_ts DESC, revision_seq DESC` — fully deterministic
- **Clock never goes backwards** — replays always use original `clock_ts`
- **Weekend behavior:** clock ticks daily; staleness window absorbs weekend gaps
- **Aligned payload reuse:** quality gate computes alignment once; publisher reuses the result — alignment is never computed twice per run

---

## 9. Quality Gate Rules

| Tier | Series | Staleness threshold | Effect if stale |
|---|---|---|---|
| Tier-1 | gold, MOVE, yields, USD, VIX, SP500 | 3 days (DTWEXBGS: 10 days) | Blocks snapshot |
| Tier-2 | GLD, CPI, PCE, FEDFUNDS | 5–45 days | Warning only |

**Fail-closed:** any Tier-1 FAIL → publish NOTHING → Layer-3 outputs nothing.
**`--force` behavior:** quality gate always runs; `--force` logs `WOULD BLOCK` warnings
but does not abort. Snapshot is marked `forced=True` permanently in DB and JSON.
Forced snapshots should be filtered out of backtests.

> **Trading-calendar note:** Staleness thresholds are intentionally sized to absorb expected
> weekend, holiday, and trading-calendar gaps. A 3-day threshold covers a standard two-day
> weekend plus one day of FRED release lag — this prevents false Tier-1 failures on
> Monday mornings and after market holidays.

---

## 10. What Still Needs to Be Built

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  LAYER-2 REMAINING ITEMS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Layer-2 — Already Done

| Component | Status | Notes |
|---|---|---|
| Gold adapter | ✅ DONE | |
| MOVE adapter | ✅ DONE | |
| GLD holdings adapter | ✅ DONE | |
| FRED loader (20 series) | ✅ DONE | |
| Quality gate | ✅ DONE | |
| Snapshot publisher | ✅ DONE | |
| Series registry JSON | ✅ DONE | Must contain `registry_version` key |
| Registry loader + validator | ✅ DONE | |
| Registry wiring — all 6 adapters | ✅ DONE | Confirmed in code audit 2026-03-07 |
| `engine_version` in snapshot schema + JSON | ✅ DONE | `db.py` v2, `snapshot_publisher.py` v2 |
| `config_version` in snapshot schema + JSON | ✅ DONE | Resolved from `registry_version` |
| Auto-migration for existing DBs | ✅ DONE | `_ensure_snapshot_schema_migrations()` |
| Three-way snapshot dedup | ✅ DONE | `clock_ts + engine_version + config_version` |

---

### Layer-2 Milestone A — Contract Handoff *(prerequisite for Layer-3 core build)*

> These items complete the Layer-2 → Layer-3 handoff gate:
> `guards` and `reason_code` are **required**; `layer1_events: []` stub is **optional but recommended**
> for forward-compatible interface stability.
> Layer-3 core development may begin once the two required items are done.
> Data integrity and operational readiness work may continue in parallel.

| Component | Status | Priority | Notes |
|---|---|---|---|
| `guards` structured object in snapshot JSON | ⬜ TODO | **High** | Required before Layer-3 gate evaluation |
| `reason_code` enum in shared constants file | ⬜ TODO | **High** | Prevents free-text at execution boundary |
| `layer1_events: []` stub in snapshot JSON | ⬜ TODO | Low | Optional — recommended for forward-compatible interface stability |

---

### Layer-2 Milestone B — Data Integrity *(runs in parallel with Layer-3; affects calibration quality)*

| Component | Status | Priority | Notes |
|---|---|---|---|
| SP500 history fix (use SPY via Yahoo) | ⬜ TODO | **High** | Affects calibration validity — 2014–2016 gap |
| `revision_risk` column in `observations` | ⬜ TODO | Medium | Architecture4 vintage discipline requirement |
| Revision writer (`revision_seq=1` path) | ⬜ TODO | Medium | FRED corrections currently silently dropped |
| `--full-reload` CLI help text update | ⬜ TODO | Low | Now uses `INSERT OR IGNORE`, not `INSERT OR REPLACE` |
| Fix/replace discontinued USD series | ⬜ TODO | Low | DTWEXM, DTWEXO, TWEXB bridge or drop |
| Extend gold history to 2005 | ⬜ TODO | Low | Target: 2008 crisis + 2011 peak coverage |

---

### Layer-2 Milestone C — Operational Readiness *(blocks live execution; does NOT block Layer-3 core build)*

| Component | Status | Priority | Notes |
|---|---|---|---|
| Daily scheduler (Windows Task Scheduler) | ⬜ TODO | Medium | Required before any live operation |
| Alerting / notification on adapter failure | ⬜ TODO | Medium | Architecture4 requires alert within 60s |
| Retry logic with cap | ⬜ TODO | Medium | Architecture4 requires capped idempotent retries |
| Kill switch | ⬜ TODO | Medium | Architecture4 requires fail-closed kill switch |
| Orchestrator / end-to-end pipeline runner | ⬜ TODO | Medium | No script currently runs the full pipeline |

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  LAYER-3 ITEMS (not Layer-2 work — see §16)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

| Component | Status | Notes |
|---|---|---|
| Feature Builder | ⬜ TODO | Depends on Layer-2 contract handoff milestone (Milestone A) being complete |
| Index Suite (Stress, Drift, CorrBreak) | ⬜ TODO | Depends on Feature Builder |
| Decision Engine | ⬜ TODO | Depends on Index Suite + calibration |
| `UnknownMode` inputs exposed in snapshot | ⬜ TODO | Layer-2 must expose index values once Index Suite is built |

> **See Section 16 for full Layer-3 readiness and dependency map.**

---

## 11. "Layer-3 Ready" Checklist

```
Step 1: quality_gate.py runs
        → VERDICT: PASS (15/15 Tier-1 fresh)              ✅ WORKING

Step 2: snapshot_publisher.py runs
        → Runs quality gate internally (self-contained)
        → Reads DB at fixed clock_ts (22:00 UTC daily)
        → Resolves engine_version (L2_ENGINE_VERSION env var)
        → Resolves config_version (registry_version from series_registry.json)
        → Computes snapshot_id (SHA-256 of clock_ts + engine + config + values)
        → Three-way dedup (clock_ts + engine_version + config_version)
        → Writes to DB (snapshots + snapshot_values tables)
        → Writes latest_snapshot.json                      ✅ WORKING
           Snapshot: feb94eb7dc719c0e2779456964f74d0454cbbcfcab64ad6f5665f4f0972b204d
           Published: 2026-03-06T21:00:00+00:00

Step 3: Layer-3 reads snapshot_id                          ⬜ NOT BUILT YET
        → Reads latest_snapshot.json or queries snapshots table by snapshot_id
        → Validates engine_version and config_version match expected values
        → Never reads observations directly
        → If no snapshot_id exists → Layer-3 outputs nothing

Current state: Steps 1 and 2 complete and version-locked.
Step 3 not yet built. guards object and reason_code enum needed before Step 3 starts.
Operational readiness items (scheduler, alerting, retry, kill switch) do NOT block Step 3 — they block live execution only.
```

---

## 12. How to Set Up Locally

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

# Step 5: Verify series_registry.json contains registry_version
python -m layer2.config.registry --validate

# Step 6: Load gold backfill (first time only)
python layer2\adapters\gold_adapter.py --load-json FRED\2014GOLD\gold_xauusd_stooq_2014_yesterday.json --live

# Step 7: Load MOVE and GLD
python layer2\adapters\move_adapter.py --source yahoo --backfill-days 1825
python layer2\adapters\gld_holdings_adapter.py --start-date 2021-01-01

# Step 8: Load all 20 FRED series (full history — ~20 seconds)
python layer2\adapters\fred_loader.py --full-history

# Step 9: Verify everything
python layer2\adapters\quality_gate.py

# Step 10: Publish first snapshot (set engine version)
set L2_ENGINE_VERSION=gold-v3.3.0   # Windows
export L2_ENGINE_VERSION=gold-v3.3.0 # Mac/Linux

python layer2\adapters\snapshot_publisher.py --dry-run   # preview first
python layer2\adapters\snapshot_publisher.py             # publish for real
```

**You should see:**
```
VERDICT: ✓ PASS — snapshot may be published
engine_version: gold-v3.3.0
config_version: <value from registry_version in series_registry.json>
snapshot_id: <64-char hash>
```

---

## 13. Key Decisions & Why

| Decision | Why |
|---|---|
| SQLite for DB | Simple, portable, no server. Can migrate to Postgres later. |
| Yahoo for MOVE | Stooq `^move` returns "No data" on weekends. Yahoo confirmed working. |
| GLD source = `yahoo_gld_proxy` | SPDR State Street CSV endpoint now returns PDF. yfinance is the reliable replacement. Formula verified: 776 tonnes. |
| GLD `is_estimate=true` | `shares_outstanding` applied uniformly to past dates — not true per-day historical. Registry, adapter, and README consistent. |
| Gold from JSON + live top-up | Avoids Stooq rate limits for 12 years of history. |
| FRED for 20 series | Single API, free, full history for all target series. |
| DTWEXBGS threshold = 10 days | Structural ~1 week FRED publish lag. Not a data error. |
| PCU2122212122210 disabled | Discontinued 2017. Staleness check meaningless. |
| Tier-1 staleness = 3 days | Covers weekends (2 days) + 1 day FRED release lag. |
| Fail-closed snapshots | Prevents Layer-3 deciding on stale or incomplete data. |
| Backtest start = 2014-01-02 | Limited by gold JSON. Extend to 2005 when possible. |
| `.secrets/` gitignored | API keys must never be committed to GitHub. |
| `layer2_truth.db` gitignored | Local DB. Each developer rebuilds from adapters. |
| `quality_report.json` gitignored | Generated fresh each run. Committed file would be stale. |
| `INSERT OR IGNORE` not `INSERT OR REPLACE` | Truth-layer discipline: once written, a rev-0 row is immutable. Reruns never silently overwrite history. |
| No `detect_types` in `sqlite3.connect()` | Deprecated in Python 3.12+. All date parsing handled explicitly. |
| Incremental filters normalized to strings | Prevents silent str-vs-date type mismatch bugs. |
| `revision_seq` reserved for future revisions | If FRED revises a value, write `revision_seq=1` — not an overwrite of `rev=0`. Not yet implemented but schema supports it. |
| `series_registry.json` as single source of truth | Prevents staleness thresholds, tier assignments, and snapshot inclusion rules from drifting across adapters. |
| Registry validates on load (fail-fast) | Invalid entries caught immediately — not silently ignored. |
| `snapshot_id` is full 64-char SHA-256 | Truncating hashes creates unnecessary collision risk. |
| `engine_version` in snapshot + hash | Architecture4 requires gate logic version-locked to `engine_version`. Enables deterministic replay against a specific engine release. |
| `config_version` = `registry_version` | Any series metadata change produces a new `config_version`, making the snapshot that consumed it traceable and replayable. |
| Three-way snapshot dedup | Same `clock_ts` can legitimately yield multiple snapshots under different engine or config versions (e.g., after a hotfix). Dedup on all three prevents both silent overwrites and false "already exists" blocks. |
| Auto-migration via `_ensure_snapshot_schema_migrations()` | Existing DBs gain `engine_version` / `config_version` columns without destructive rebuild. Migrated rows get `UNKNOWN_*` sentinel values — identifiable and filterable in replay queries. |
| `run_ts` separate from `clock_ts` in snapshots | `clock_ts` = engine point-in-time (22:00 UTC). `run_ts` = when the code actually executed. These are different and must not be confused. |
| `forced=True` flag in snapshot DB + JSON | Snapshots created with `--force` are permanently marked so they can be filtered out of backtests. |
| Tier-1 completeness hard fail in publisher | If publisher's series list drifts from gate's list, the snapshot is blocked rather than silently publishing an incomplete view. |
| Aligned payload reused from quality gate | Alignment is computed once per run inside `quality_gate.py` and passed to `snapshot_publisher.py` via the report dict. No double-alignment per publish cycle. |

---

## 14. Code Integrity Log

### Audit 1 — 2026-03-05

| Issue | Severity | Fix applied |
|---|---|---|
| `INSERT OR REPLACE` destroys history | Critical | Changed to `INSERT OR IGNORE` across all 5 files |
| Incremental filters: str vs date type mismatch | High | Normalized all `existing_dates` sets to strings via `.isoformat()` |
| `detect_types=sqlite3.PARSE_DECLTYPES` deprecated in Python 3.12+ | Medium | Removed from all `get_connection()` calls |
| `latest_obs_date()` returned raw sqlite value without type safety | Medium | All date returns now handle `str`, `datetime`, and `date` objects |

**Known remaining items from Audit 1:**
- `--full-reload` help text still describes deprecated overwrite behavior ⬜
- Revision writer (`revision_seq=1`) not yet built ⬜

---

### Audit 2 — 2026-03-06

| Issue | Severity | Fix applied |
|---|---|---|
| `snapshot_id` truncated to 32 chars | Medium | Now full 64-char SHA-256 stored everywhere |
| `run_ts` not logged separately from `clock_ts` | Medium | `run_ts` added to logs and JSON output |
| `--force` produced misleading "valid-looking" snapshots | Medium | `forced=True` stored in DB and JSON permanently |
| JSON missing stable API fields for Layer-3 | Medium | `tier1_series`, `tier2_series`, `missing_series` added as stable top-level fields |
| Tier-1 list could drift between gate and publisher | Medium | Hard fail added: Tier-1 count mismatch → snapshot blocked |
| Staleness rules split across files | High | `series_registry.json` created; `registry.py` loader and validator built |

---

### Audit 3 — 2026-03-06

| Issue | Severity | Fix applied |
|---|---|---|
| `forced` flag claimed stored but `snapshots` table had no `forced` column | High | Column added to schema + `_write_snapshot()` + `_list_snapshots()` |
| Batch hash truncated `[:16]` in three adapters | Medium | All batch hashes now full 64-char SHA-256 |
| Section 7 titled "Five Adapters" but had six | Minor | Renamed to "The Six Adapters" |
| Schema section only showed `observations` table | Minor | `snapshots` and `snapshot_values` added |

---

### Audit 4 — 2026-03-06

| Issue | Severity | Fix applied |
|---|---|---|
| `--force` path fabricated hardcoded summary instead of running real gate | High | Gate always runs; `--force` logs warnings but does not abort |
| GLD source inconsistency across registry / adapter / README | Medium | Source label corrected to `yahoo_gld_proxy` across registry, adapter, and README — consistent with current yfinance-based fetch path |

---

### Audit 5 — 2026-03-07

| Issue | Severity | Fix applied |
|---|---|---|
| `engine_version` absent from `snapshots` schema and JSON | Critical | Added to `_DDL_SNAPSHOTS`, `_write_snapshot()`, `write_snapshot_json()`, `compute_snapshot_id()` |
| `config_version` absent from `snapshots` schema and JSON | Critical | Resolved from `registry_version` via `_get_config_version()` with multi-path fallback |
| No auto-migration for existing DBs | High | `_ensure_snapshot_schema_migrations()` added — uses `PRAGMA table_info` + `ALTER TABLE` |
| No composite index for version-locked replay queries | Medium | `idx_snapshots_clock_engine_config` added |
| `_snapshot_exists()` dedup only on `clock_ts` | Medium | Upgraded to three-way dedup: `clock_ts + engine_version + config_version` |
| `_list_snapshots()` did not show version fields | Low | Updated to display `engine_version` and `config_version` |
| `compute_snapshot_id()` did not include version fields | Medium | Both version fields now included in hash payload |
| CLI flags `--clock-date` / `--db` inconsistent with codebase | Low | Renamed to `--date` / `--db-path` |
| README to-do list showed registry wiring as pending | Low | Corrected — wiring confirmed complete in code audit |

**Known remaining items from Audit 5:**
- `guards` structured object not yet in snapshot output (required before Layer-3) ⬜
- `reason_code` enum not defined (required before Layer-3) ⬜
- SP500 history gap 2014–2016 (HIGH priority for calibration) ⬜
- `revision_risk` column not in `observations` table ⬜
- `layer1_events: []` stub not in snapshot JSON ⬜
- Operational readiness (scheduler, alerting, retry, kill switch) not built ⬜

---

## 15. Layer-2 Readiness Scorecard

*Last scored: 2026-03-07. Methodology: 0–10 per domain, weighted total.*

| Domain | Score | Weight | Weighted |
|---|---|---|---|
| Data Ingestion & Coverage | 8.5 | 15% | 1.28 |
| Registry & Configuration | 9.5 | 10% | 0.95 |
| Truth-Layer Integrity | 9.0 | 15% | 1.35 |
| Point-in-Time Alignment | 9.5 | 15% | 1.43 |
| Clock & Calendar Governance | 9.5 | 10% | 0.95 |
| Quality Gate | 8.5 | 15% | 1.28 |
| Snapshot Publisher & Layer-3 Contract | 9.0 | 15% | 1.35 |
| Operational Readiness | 5.5 | 5% | 0.28 |
| **TOTAL** | **8.86 / 10** | 100% | **8.86** |

### Gate verdicts

| Gate | Score | Ready? |
|---|---|---|
| Continue Layer-2 daily operations | 8.86 | ✅ Yes |
| Publish production snapshots | 9.1 (domains 1–6) | ✅ Yes |
| Begin Layer-3 development | 9.0 (domain 7) | ✅ Yes — after Layer-2 contract handoff milestone (Milestone A) is complete; Layer-2 ops work continues in parallel |
| Connect any live execution path | 5.5 (domain 8) | ❌ No — scheduler, alerting, retry, kill switch absent |

### Key open items by score impact

| Item | Domain affected | Score impact if fixed |
|---|---|---|
| SP500 history gap | Data Ingestion | +0.5 |
| `guards` object in snapshot | Snapshot Publisher | +0.25 |
| `revision_risk` tracking | Truth-Layer + Quality Gate | +0.25 each |
| Daily scheduler + orchestrator | Operational Readiness | +1.5 |
| Alerting + retry + kill switch | Operational Readiness | +1.5 |

---

## 16. Layer-3 Readiness & Dependency Map

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  LAYER-3 IS NOT BUILT. THIS SECTION DEFINES WHAT IS NEEDED.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### What Layer-3 receives from Layer-2 (the contract)

Layer-3 must consume only `latest_snapshot.json` or the `snapshots` + `snapshot_values`
DB tables via `snapshot_id`. It must never read `observations` directly.

**Stable fields Layer-3 may depend on:**

```json
{
  "snapshot_id":    "<64-char sha256>",
  "engine_version": "gold-v3.3.0",
  "config_version": "<registry_version>",
  "clock_ts":       "2026-03-06T22:00:00+00:00",
  "clock_date":     "2026-03-06",
  "verdict":        "PASS | FAIL",
  "forced":         false,
  "tier1_series":   { "<series_id>": { "obs_ts", "value", "staleness_days", "source" } },
  "tier2_series":   { "<series_id>": { "obs_ts", "value", "staleness_days", "source" } },
  "missing_series": []
}
```

### What Layer-3 still needs from Layer-2 (not yet built)

| Item | Why Layer-3 needs it | Layer-2 owner | Priority |
|---|---|---|---|
| `guards` object in snapshot | Layer-3 evaluates `data_ok`, `idempotent_ok` hard veto conditions from snapshot | `snapshot_publisher.py` | **High** |
| `reason_code` enum defined | Layer-3 must emit only enumerated reason codes — no free text at execution boundary | shared constants file | **High** |
| `layer1_events: []` stub | Optional — recommended for forward-compatible interface stability; Layer-3 interface should have a defined (empty) slot for future Layer-1 event hooks | `snapshot_publisher.py` | Low |
| Index Suite values in snapshot | Layer-3 `UnknownMode` evaluation requires Stress, Drift, CorrBreak index values from Layer-2 | Future Layer-2 extension | After Index Suite built |

---

### ★ Layer-2 → Layer-3 Handoff Gate

> **Layer-3 core development may begin once the two required items below are complete.**
> (`layer1_events: []` stub is optional but recommended for forward-compatible interface stability.)
> Layer-2 data integrity work (SP500, revision_risk, gold history) and operational
> readiness work (scheduler, alerting, retry, kill switch, orchestrator) continue as
> separate Layer-2 milestones in parallel — they do NOT block Layer-3 core build.
> They DO block connecting any live execution path.

```
Handoff gate checklist:
  ✅ snapshot_publisher produces engine_version + config_version
  ✅ Layer-3 contract fields are stable (snapshot_id, clock_ts, verdict, tier1/tier2_series)
  ⬜ guards object in snapshot JSON        ← Layer-2 Milestone A item
  ⬜ reason_code enum defined              ← Layer-2 Milestone A item
  ⬜ layer1_events: [] stub (optional but recommended before Layer-3 starts)
```

Once the gate above is passed → Layer-3 core build may begin.
Live execution gate remains separate (see Section 15).

### Layer-3 build order (begin after contract handoff gate is passed)

```
then build in this order:
  1. Feature Builder
     - reads from latest_snapshot.json
     - computes standardized multi-horizon feature vectors
     - validates engine_version + config_version before consuming
     - must support point-in-time reconstruction (use obs_ts, not ingest date)

  2. Index Suite
     - StressIndex (0–100)
     - DriftIndex (0–100)
     - CorrBreakIndex (0–100)
     - DataFreshnessPenalty (0–100)
     - Indices must be frozen via calibration before use in gate logic
     - Null or unfrozen indices → supervisor degrades confidence

  3. Regime Gate
     - Consumes Feature Builder output
     - Regime confidence < threshold → UnknownMode activated
     - UnknownMode: confidence=0, uncertainty=U_max, cooldown++, no directional execution

  4. Supervisor Engine
     - Hard veto (non-negotiable): data_ok=false, idempotent_ok=false,
       UnknownMode active, uncertainty > U_max → NO TRADE
     - Soft constraints: stress/drift/corrbreak high → shrink position

  5. Decision Engine → DecisionPacket (deterministic, no free text)
     {
       "engine_version":  "gold-v3.3.0",
       "config_version":  "<registry_version>",
       "action":          "BUY | SELL | NOTHING",
       "confidence":      0.0,
       "uncertainty":     0.0,
       "reason_code":     "<ENUM_ONLY>",
       "guards":          { "data_ok", "idempotent_ok", "cooldown_ok",
                            "risk_ok", "supervisor_veto" }
     }

  6. Zapier-style validation harness
     - Trigger → Fetch → Call Engine → Schema Validate → Gate → Route
       → Paper Execute → Immutable Log → Post-Session Analysis
     - Gate allows execution only if all guards pass AND
       confidence >= C_min AND uncertainty <= U_max

  7. Calibration (thresholds are not theater)
     - ≥ 100–300 decision ticks before freezing C_min / U_max
     - ≥ 30–100 executed paper trades
     - Monotonic calibration: higher confidence → better outcomes
     - Required metrics: reliability curve, Brier score, drawdown, CVaR,
       regime breakdown, calibration error
     - PnL alone is insufficient
```

### Layer-3 activation criteria (all must be met)

```
⬜ Feature Builder tested and stable
⬜ Index Suite frozen and calibrated (not just built)
⬜ ≥ 100 decision ticks in paper mode
⬜ ≥ 30 executed paper trades with adequate sample
⬜ Monotonic calibration holds
⬜ DecisionPacket schema frozen (no free-text fields)
⬜ Zapier-style harness passing end-to-end
⬜ Kill switch tested and confirmed fail-closed
```

---

## 17. Roadmap Project Management

> This section describes the practical project roadmap in project-management terms:
> what must still be done to close Layer-2, what starts in Layer-3 immediately after
> the handoff gate passes, and what Layer-2 work continues in parallel without blocking
> Layer-3 bootstrap.

---

### Layer-2 Closure Definition

> Layer-2 is considered finished for Layer-3 bootstrap when it is a **registry-driven,
> fail-closed, version-locked snapshot system that Layer-3 can consume as a stable API.**

This definition is intentionally narrow. It does not require operational perfection —
it requires contract stability and data integrity sufficient for Layer-3 to build against.

---

### Sprint 1 — Layer-2 Closure *(short-term focus)*

**Must be complete before Layer-3 bootstrap:**

| Item | Status | Notes |
|---|---|---|
| Snapshot contract stable | ✅ DONE | Confirmed in code audit 2026-03-07 |
| `engine_version` + `config_version` in snapshot outputs | ✅ DONE | `db.py` v2, `snapshot_publisher.py` v2 |
| Quality gate and snapshot publisher contract-consistent | ✅ DONE | Registry-driven, confirmed in code audit |
| `guards` structured object in snapshot JSON | ⬜ TODO | Required before Layer-3 gate evaluation |
| `reason_code` enum in shared constants | ⬜ TODO | Prevents free-text at execution boundary |
| README and code in sync on contract behavior | ⬜ TODO | Doc/code sync pass to be completed |

**Strongly recommended in the same sprint:**

| Item | Status | Notes |
|---|---|---|
| Simple orchestrator / end-to-end runner | ⬜ TODO | Single script running all adapters → gate → publish |
| `layer1_events: []` stub in snapshot JSON | ⬜ TODO | Optional — forward-compatible interface stability |
| Doc/code sync pass completed | ⬜ TODO | Confirm README claims match current code |

---

### What Does NOT Block Layer-2 Closure

These remain important but do not block Layer-3 bootstrap:

- Full revision system / revision writer (`revision_seq=1`)
- `revision_risk` column in observations
- SP500 full historical gap closure (2014–2016)
- Extended gold history to 2005
- Full alerting / notification stack
- Full retry framework
- Full operational polish
- Mature regime logic or calibration logic

---

### Layer-3 Start Gate

Layer-3 bootstrap may begin when:

```
Required:
  ✅ Snapshot contract stable
  ✅ engine_version + config_version reliable in snapshot outputs
  ⬜ guards object added to snapshot JSON
  ⬜ reason_code enum defined
  ⬜ README and code in sync on contract behavior

Recommended but not mandatory for bootstrap start:
  ⬜ Simple orchestrator / end-to-end runner
  ⬜ layer1_events: [] stub
  ⬜ Basic scheduler

NOT required for Layer-3 bootstrap — required later for live execution:
  ⬜ Full scheduler
  ⬜ Alerting / notification
  ⬜ Retry with cap
  ⬜ Kill switch
  ⬜ Broader operational hardening
```

> **Layer-3 bootstrap readiness is NOT the same as live execution readiness.**
> Live execution remains disabled until operational readiness and sufficient
> paper-mode validation are complete (see Section 16 activation criteria).

---

### Sprint 2 — Layer-3 Bootstrap Phase 1 *(begin after start gate passes)*

Phase 1 is intentionally simple. Do not jump to regime math.

**Build in this order:**

| Step | Component | Notes |
|---|---|---|
| 1 | Snapshot consumer | Reads `latest_snapshot.json`; validates `engine_version` + `config_version` |
| 2 | Feature builder stub | 2–3 fully deterministic calculations only |
| 3 | DecisionPacket skeleton | `action: NOTHING`, all guards false, `reason_code: NO_SIGNAL` |
| 4 | NO_TRADE default path | System produces output without executing anything |

**Example first calculations (deterministic, no regime logic):**
- Real yield spread (DFII10 − DGS10)
- Inflation expectation spread (T10YIE − T5YIE)
- Stress placeholder (VIXCLS + MOVE index combined)

**Non-goals of Phase 1:**
- Full regime engine
- Full mathematical calibration
- Full supervisor policy set
- Live execution connection
- Over-optimized signal logic

---

### Parallel Layer-2 Work After Layer-3 Starts

Once the Layer-3 start gate passes, Layer-2 continues in two parallel tracks.
Neither track blocks Layer-3 core build — both improve calibration quality and
operational robustness over time.

**Layer-2 Data Integrity (Milestone B — see §10):**
- SP500 history gap (2014–2016)
- `revision_risk` column in observations
- Revision writer (`revision_seq=1` path)
- Discontinued USD series cleanup
- Extended gold history toward 2005

**Layer-2 Operational Readiness (Milestone C — see §10):**
- Daily scheduler
- Alerting / notification on adapter failure
- Retry logic with cap
- Kill switch
- Orchestration hardening

---

### Live Execution Gate *(separate and later)*

> This gate is **distinct** from the Layer-3 bootstrap gate.
> Do not conflate them.

Live execution may be connected only when:
- Layer-3 paper-mode validation is complete
- Calibration criteria are met (see §16 activation criteria)
- Operational readiness is in place (scheduler, alerting, retry, kill switch)
- DecisionPacket schema is frozen
- Zapier-style harness is passing end-to-end

> **Session-aware execution policy** — determining whether a decision is ALLOWED,
> REDUCED_ONLY, PAPER_ONLY, or BLOCKED for the current session, liquidity, or
> operational state — is an execution-layer policy that belongs here, at live execution
> readiness. It does not invent or override signal direction; Layer-3 defines deterministic
> signal intent through DecisionPacket. Session-aware policy is NOT part of the minimum
> Layer-3 bootstrap gate.

---

## 18. Revision Log

| Version | Date | Author | Summary |
|---|---|---|---|
| v1 | 2026-03-05 | @balazsv27-rgb | Initial Layer-2 documentation |
| v2 | 2026-03-06 | @balazsv27-rgb | Post-Audit 2: snapshot publisher, registry, schema |
| v3 | 2026-03-06 | @balazsv27-rgb | Post-Audit 3: forced column, batch hash, schema docs |
| v4 | 2026-03-06 | @balazsv27-rgb | Post-Audit 4: force flag behavior, GLD source fix |
| v5 | 2026-03-07 | Architecture audit | Post-Audit 5: engine_version/config_version, scorecard, Layer-3 separation, stale to-do corrections |
| v6 | 2026-03-07 | Architecture audit | TL;DR/non-goals added, DB state disclaimer, canonical interface clarified, 22:00 UTC policy framing, trading-calendar nuance, Audit 4 GLD source fossil corrected |
| v7 | 2026-03-07 | Architecture audit | Milestone-separation applied: Layer-2 items split into Contract Handoff / Data Integrity / Ops Readiness; explicit L2→L3 handoff gate added to §16; ops items decoupled from Layer-3 start gate |
| v8 | 2026-03-07 | Architecture audit | `layer1_events` inconsistency resolved: optional/required distinction now consistent across §10 Milestone A, §16 handoff gate, and §16 needs table |
| v9 | 2026-03-07 | Architecture audit | New §17 "Roadmap Project Management" added; §17 Revision Log renumbered to §18; §18 Useful Links renumbered to §19 |
| v10 | 2026-03-07 | Architecture audit | Minimal patch: session-aware execution policy clarification added to Live Execution Gate in §17 |

---

## 19. Useful Links

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

*Read this before touching any code. For questions open a GitHub Issue on the repo.*
