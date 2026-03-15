# Mr. Ripley — Layer-2 Truth Layer

> **Repo:** [github.com/balazsv27-rgb/Mr-Ripley](https://github.com/balazsv27-rgb/Mr-Ripley)
> **Last updated:** 2026-03-07
> **Architecture reference:** `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
> **Full technical handbook:** `SYSTEM_TECHNICAL_HANDBOOK_v1.md`

---

## Project Purpose

Layer-2 is the **data ingestion and truth store** for the Mr. Ripley gold-first decision engine.

It ingests market and macro data, validates it against governed staleness rules, and publishes point-in-time immutable snapshots that Layer-3 consumes as a stable versioned API.

Layer-2 ends at snapshot publication. It does not compute features, regimes, or decisions.

---

## What Layer-2 Is

- **Registry-driven** — all series metadata, staleness thresholds, and tier assignments come exclusively from `series_registry.json`
- **Fail-closed** — any Tier-1 data failure blocks snapshot publication; Layer-3 receives nothing rather than stale or incomplete data
- **Version-locked** — every snapshot carries `engine_version`, `config_version`, and a deterministic `snapshot_id` (SHA-256)
- **Point-in-time disciplined** — alignment enforces `obs_ts <= clock_date` AND `as_of_ts <= clock_ts` in a single set-based SQL query; tie-breaking is deterministic
- **Immutable** — `INSERT OR IGNORE` throughout; rev-0 observation rows are never overwritten

---

## What Layer-2 Is Not

- Not a feature engineering layer
- Not a regime detection or decision layer
- Not a live execution system
- Not a source of direct "latest" reads for downstream consumers

> **Layer-3 must never query the `observations` table directly.**
> It may only consume published snapshots via `snapshot_id`.

---

## Architecture Position

```
Layer-1  →  Event Tagger / Narrative Risk Modifiers   (optional, disabled by default)
Layer-2  →  Ingestion + validation + snapshot store    ← YOU ARE HERE
Layer-3  →  Feature builder + index suite + decision engine   (not yet built)
Layer-4  →  Execution orchestration                   (intentionally unwired)
```

Layer-2 is considered closed for Layer-3 bootstrap when it is a **registry-driven, fail-closed, version-locked snapshot system that Layer-3 can consume as a stable API.** This is a narrow handoff definition — it does not mean Layer-2 hardening is complete.

---

## Core Invariants

Non-negotiable. Every design decision in Layer-2 exists to protect these.

| # | Invariant |
|---|---|
| 1 | **Registry is the single source of truth** — series metadata, staleness thresholds, and tier assignments come only from `series_registry.json` |
| 2 | **Fail-closed** — any Tier-1 staleness failure blocks snapshot publication; nothing is published rather than publishing unsafe data |
| 3 | **Immutable observations** — `INSERT OR IGNORE`; rev-0 rows are never overwritten; corrections use `revision_seq=1` (schema reserved; writer not yet built) |
| 4 | **Point-in-time alignment** — `obs_ts <= clock_date` AND `as_of_ts <= clock_ts` enforced jointly; results are deterministic and replay-safe |
| 5 | **Deterministic snapshots** — same `clock_ts` + same aligned series state + same `engine_version` + same `config_version` → same `snapshot_id` |
| 6 | **Layer boundary** — Layer-3 reads only published snapshots; direct `observations` access is forbidden |
| 7 | **Version-locked contract** — every snapshot carries `engine_version` and `config_version`; gate logic is version-locked to `engine_version` |

---

## Known Approximations

Accepted estimates — not bugs. Label explicitly in any backtest output.

| Item | Approximation | Impact |
|---|---|---|
| GLD holdings | `ounces = shares_outstanding × 0.09585` — current `shares_outstanding` applied uniformly to past dates; not true per-day historical | Tier-2 signal only; never blocks snapshot |
| Gold history | Backfill starts 2014-01-02; target is 2005 | Pre-2014 calibration window unavailable |
| SP500 history | FRED data from 2016-02-22; backtest needs 2014 | 2015 China shock and early 2016 selloff missing |
| Monthly macro (CPI, PCE) | FRED may revise; `revision_risk` not yet tracked | Downstream confidence penalty not yet applied |

---

## Current Status

*As of 2026-03-07 — current documented implementation status.*

| Item | Status |
|---|---|
| All 6 adapters | ✅ Done |
| Registry wiring — all adapters | ✅ Done — confirmed code audit 2026-03-07 |
| Quality gate | ✅ Done — 15/15 Tier-1 PASS |
| Snapshot publisher | ✅ Done |
| `engine_version` + `config_version` in snapshots | ✅ Done |
| Three-way snapshot dedup | ✅ Done |
| Auto-migration for existing DBs | ✅ Done |
| `guards` object in snapshot JSON | ⬜ Required — before Layer-3 start |
| `reason_code` enum in shared constants | ⬜ Required — before Layer-3 start |
| README and code in sync on contract behavior | ⬜ Required — before Layer-3 start (see `SYSTEM_TECHNICAL_HANDBOOK_v1.md` §14, "Verification Status") |
| `layer1_events: []` stub in snapshot JSON | ⬜ Optional — recommended for interface stability |
| Simple end-to-end orchestrator script | ⬜ Recommended — before Layer-3 start |
| Daily scheduler | ⬜ Required — before live execution only |
| Alerting / retry / kill switch | ⬜ Required — before live execution only |

*Self-assessed readiness: 8.86 / 10 — see §15 of `SYSTEM_IMPLEMENTATION_RECORD_v1.md` for preserved domain breakdown and methodology.*

---

## Known Gaps & Limitations

| Item | Severity | Notes |
|---|---|---|
| `guards` object absent from snapshot JSON | **High** | Blocks Layer-3 bootstrap start gate |
| `reason_code` enum not defined | **High** | Blocks Layer-3 bootstrap start gate |
| SP500 history gap (2014–2016) | **High** | Affects calibration validity — fix via SPY/Yahoo planned |
| `revision_risk` not tracked | Medium | Monthly FRED series carry unacknowledged revision exposure |
| Revision writer not built | Medium | `revision_seq=1` path absent; FRED corrections silently dropped |
| No end-to-end orchestrator | Medium | Pipeline run manually per step |
| No scheduler, alerting, or kill switch | Medium | Required before any live operation |
| `layer2_truth.db` repo state | Medium | README states gitignored; file was observed committed in repo — see `SYSTEM_TECHNICAL_HANDBOOK_v1.md` §14 ("Verification Status") for the current interim status |
| Gold history starts 2014 | Low | Target 2005 for 2008 crisis and 2011 peak coverage |
| Discontinued USD series in DB | Low | DTWEXM, DTWEXO, TWEXB — bridge or drop |

---

## Repository Structure

```
Mr-Ripley/
├── layer2/
│   ├── adapters/
│   │   ├── gold_adapter.py            # Gold XAUUSD — Tier-1
│   │   ├── move_adapter.py            # MOVE index — Tier-1
│   │   ├── gld_holdings_adapter.py    # GLD ounces held — Tier-2 (approximation)
│   │   ├── fred_loader.py             # 20 FRED series — Tier-1 + Tier-2
│   │   ├── quality_gate.py            # Staleness gate + snapshot verdict
│   │   └── snapshot_publisher.py      # Layer-3 contract boundary
│   └── config/
│       ├── series_registry.json       # ★ Single source of truth — must contain registry_version key
│       └── registry.py               # Loader + validator
├── FRED/
│   └── gold_xauusd_stooq_2014_yesterday.json   # Gold backfill (3,132 rows, 2014–present)
├── .secrets/fred_api_key.txt          # FRED API key — not committed
├── SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md   # Architecture specification
├── SYSTEM_TECHNICAL_HANDBOOK_v1.md               # Full technical handbook
└── SYSTEM_IMPLEMENTATION_RECORD_v1.md            # Historical implementation record
```

*`layer2_truth.db`, `layer2_quality_report.json`, and `latest_snapshot.json` are intended runtime artifacts and should normally be rebuilt locally by each developer.*

---

## Setup / Run

**Prerequisites:** Python 3.10+, FRED API key (free at [fredaccount.stlouisfed.org/apikeys](https://fredaccount.stlouisfed.org/apikeys))

```bash
git clone https://github.com/balazsv27-rgb/Mr-Ripley.git
cd Mr-Ripley
python -m venv venv && .\venv\Scripts\activate   # Windows
# source venv/bin/activate                       # Mac/Linux
pip install yfinance

mkdir .secrets
echo your_key_here > .secrets\fred_api_key.txt

# Verify registry (confirms registry_version key is present)
python -m layer2.config.registry --validate

# First-time data load
python layer2\adapters\gold_adapter.py --load-json .\FRED\gold_xauusd_stooq_2014_yesterday.json --live
python layer2\adapters\move_adapter.py --source yahoo --backfill-days 1825
python layer2\adapters\gld_holdings_adapter.py --start-date 2021-01-01
python layer2\adapters\fred_loader.py --full-history

# Verify and publish
python layer2\adapters\quality_gate.py
set L2_ENGINE_VERSION=gold-v3.3.0    # Windows / export on Mac/Linux
python layer2\adapters\snapshot_publisher.py --dry-run
python layer2\adapters\snapshot_publisher.py
```

*Daily EOD run and full adapter reference: see `SYSTEM_TECHNICAL_HANDBOOK_v1.md` and `SYSTEM_IMPLEMENTATION_RECORD_v1.md`.*

---

## Layer-3 Readiness Status

### Snapshot contract — stable fields Layer-3 may depend on

```json
{
  "snapshot_id":    "<64-char SHA-256>",
  "engine_version": "gold-v3.3.0",
  "config_version": "<registry_version>",
  "clock_ts":       "<date>T22:00:00+00:00",
  "verdict":        "PASS | FAIL",
  "forced":         false,
  "tier1_series":   { "<series_id>": { "obs_ts", "value", "staleness_days", "source" } },
  "tier2_series":   { "<series_id>": { "obs_ts", "value", "staleness_days", "source" } },
  "missing_series": []
}
```

*22:00 UTC is the default cut time — configurable via `L2_CLOCK_CUT_HOUR`.*

**Consumption rules:**
- Canonical: query `snapshots` + `snapshot_values` by `snapshot_id`
- Convenience: read `latest_snapshot.json`
- Forbidden: querying `observations` directly

### Required before Layer-3 bootstrap starts

| Item | Why |
|---|---|
| `guards` object in snapshot JSON | Layer-3 evaluates hard veto conditions (`data_ok`, `idempotent_ok`) from this |
| `reason_code` enum defined | Prevents free-text at execution boundary |
| README and code in sync | Confirmed doc/code sync pass required |

*Optional but recommended: `layer1_events: []` stub, simple orchestrator.*

### What does NOT block Layer-3 bootstrap

Operational readiness (scheduler, alerting, retry, kill switch) and data integrity work (SP500 history, `revision_risk`, revision writer) continue in parallel after the bootstrap gate passes. Neither track blocks Layer-3 core build. Both block live execution.

### Live execution gate — separate and later

Layer-3 bootstrap readiness is **not** live execution readiness. Live execution requires completed paper-mode validation, calibration, frozen DecisionPacket schema, tested kill switch, and full operational readiness. Session-aware execution policy (ALLOWED / REDUCED_ONLY / PAPER_ONLY / BLOCKED) is an execution-layer concern — it is not a bootstrap requirement.

---

## Supporting Docs

| Document | Purpose |
|---|---|
| `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Full technical handbook — schema, adapter responsibilities, alignment rules, quality gate detail, handoff gate, live-execution boundary |
| `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Historical implementation record — preserved long-form build notes, code integrity log, readiness scorecard, roadmap |
| `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architecture specification — layer framing, DecisionPacket contract, Layer-3 build sequence, calibration protocol, live execution gate |

---

*Read this before touching any code. For questions open a GitHub Issue on the repo.*
