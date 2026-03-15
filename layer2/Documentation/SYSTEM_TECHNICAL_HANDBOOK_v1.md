# Layer-2 Technical Handbook
## Mr. Ripley — Gold-First Decision Engine

> **Entry-point summary:** `README_v1.md`
> **Architecture reference:** `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
> **Limitations / approximations:** `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
> **Historical implementation record:** `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
> **Last updated:** 2026-03-07

---

## 1. Purpose and System Role

Layer-2 is the **truth and observation layer** of the Mr. Ripley gold-first decision engine.

Its responsibilities are:
- Ingest market and macro time-series data from external sources
- Validate data freshness against governed staleness rules
- Store observations in an immutable, point-in-time correct store
- Publish versioned, deterministic snapshots as the stable API consumed by Layer-3

Layer-2 responsibility ends at snapshot publication. It does not compute features, indices, regimes, or decisions. Any downstream computation is Layer-3 work.

### Where Layer-2 sits

```
Layer-1  →  Event Tagger / Narrative Risk Modifiers   (optional, disabled by default)
Layer-2  →  Ingestion + validation + snapshot store    ← THIS DOCUMENT
Layer-3  →  Feature builder + index suite + decision engine   (not yet built)
Layer-4  →  Execution orchestration                   (intentionally unwired)
```

Layer-3 must consume only published snapshots. It must never query the `observations` table directly. This boundary is non-negotiable.

---

## 2. Core Invariants

These rules are non-negotiable. Every design decision in Layer-2 exists to protect them. Any change that weakens one of these rules is an architectural regression.

| # | Invariant | Implication |
|---|---|---|
| 1 | **Registry is the single source of truth** — series metadata, staleness thresholds, and tier assignments come exclusively from `series_registry.json` | Adapters must never hardcode series config; drift across files is prevented at source |
| 2 | **Fail-closed** — any Tier-1 staleness failure blocks snapshot publication entirely | Layer-3 receives nothing rather than stale or incomplete data |
| 3 | **Immutable observations** — `INSERT OR IGNORE` throughout; rev-0 rows are never overwritten | Reruns and backfills cannot silently corrupt history; corrections require `revision_seq=1` (schema reserved; writer not yet built) |
| 4 | **Point-in-time alignment** — `obs_ts <= clock_date` AND `as_of_ts <= clock_ts` enforced jointly in a single set-based SQL query; tie-breaking is deterministic (`obs_ts DESC, as_of_ts DESC, revision_seq DESC`) | Replays produce identical results; no "latest observation" leak |
| 5 | **Deterministic snapshot identity** — same `clock_ts` + same aligned series state + same `engine_version` + same `config_version` → same `snapshot_id` | Snapshots are replayable and auditable |
| 6 | **Layer boundary** — Layer-3 reads only published snapshots; direct `observations` access is forbidden | Prevents bypassing the quality gate and the versioned contract |
| 7 | **Version-locked contract** — every snapshot carries `engine_version` and `config_version`; gate logic is version-locked to `engine_version` | Snapshot consumers can validate they are consuming data produced by a known, compatible engine state |

---

## 3. Architecture Position and Handoff Boundary

### What "Layer-2 closed for Layer-3 bootstrap" means

Layer-2 is considered ready for Layer-3 bootstrap when it is a **registry-driven, fail-closed, version-locked snapshot system that Layer-3 can consume as a stable API.**

This is a narrow handoff definition. It does not mean:
- Layer-2 data coverage is complete
- Operational readiness (scheduler, alerting, retry, kill switch) is in place
- Calibration or paper validation is done
- Live execution is allowed

### What the handoff gate requires

From `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` §6, the contract handoff gate requires all of:

| Item | Status |
|---|---|
| Snapshot contract stable | ✅ Done |
| `engine_version` + `config_version` reliable in snapshot outputs | ✅ Done |
| `guards` structured object in snapshot JSON | ⬜ Not yet built |
| `reason_code` enum defined in shared constants | ⬜ Not yet built |
| README and code in sync on contract behavior | ⬜ Doc/code sync pass pending |

Recommended but not mandatory for bootstrap start: simple orchestrator, `layer1_events: []` stub, basic scheduler.

### What does not block Layer-3 bootstrap

The following Layer-2 work continues in parallel after the handoff gate is passed. Neither track blocks Layer-3 core build. Both block live execution.

- **Data integrity:** SP500 history gap, `revision_risk`, revision writer, discontinued USD cleanup, gold history extension
- **Operational readiness:** daily scheduler, alerting, retry with cap, kill switch, orchestration hardening

### Live execution is a separate and later gate

Passing the contract handoff gate unlocks Layer-3 development. It does not unlock live execution. Live execution requires completed paper-mode validation, calibration, frozen DecisionPacket schema, tested kill switch, and full operational readiness.

---

## 4. Temporal Model and Alignment Rules

### Clock model

The engine clock produces one governed `clock_ts` per day. Default: 22:00 UTC — an operational policy choice timed after US market close and primary vendor data refresh windows. This is configurable via `L2_CLOCK_CUT_HOUR` and is not a fixed system constant.

Key clock properties:
- **`clock_date`** — the calendar date of the clock tick
- **`clock_ts`** — the governed cut timestamp (datetime, timezone-aware)
- **`run_ts`** — when the code actually executed; always distinct from `clock_ts` and never confused with it
- **Clock never goes backwards** — replays use the original `clock_ts`, not the replay execution time

### Alignment logic

For each required series, the alignment query selects the latest observation satisfying both constraints:

```
obs_ts   <= clock_date
as_of_ts <= clock_ts
```

Tie-breaking is fully deterministic:

```sql
ORDER BY obs_ts DESC, as_of_ts DESC, revision_seq DESC
```

This is executed as a single set-based SQL query across all required series — not one query per series. Alignment is computed once per run inside `quality_gate.py` and the result is passed directly to `snapshot_publisher.py`. Alignment is never computed twice per publish cycle.

### Replay implications

Because `clock_ts` is fixed and alignment is deterministic, any replay of a past date with the same `engine_version` and `config_version` produces an identical `snapshot_id`. This holds as long as the `observations` table has not been modified for that date range — which is protected by `INSERT OR IGNORE` immutability.

### Weekend and holiday behavior

The clock ticks daily including weekends. Staleness thresholds are sized to absorb weekend and holiday gaps without producing false failures. A 3-day Tier-1 threshold covers a two-day weekend plus one day of FRED release lag.

---

## 5. Registry Model and Series Governance

### Role of the registry

`series_registry.json` is the single source of truth for all series configuration. All six adapters import from `registry.py` and consume the registry at runtime. No series metadata is hardcoded in any adapter.

The registry is validated on load (fail-fast). Invalid entries — duplicate IDs, wrong types, Tier-1 series marked as estimates, discontinued series marked as blockers — are caught immediately.

`series_registry.json` must contain a `registry_version` key. This value is read by `snapshot_publisher.py` as `config_version` for every published snapshot. If the key is absent, `_get_config_version()` raises `RuntimeError` and publishing is blocked.

### Tier definitions

| Tier | Effect if stale | Purpose |
|---|---|---|
| **Tier-1** | Blocks snapshot publication entirely | Primary asset state and macro drivers — must be fresh for any snapshot to be valid |
| **Tier-2** | Warning only — never blocks | Confirmation signals and lower-frequency macro series |

### Current series

**Tier-1 (15 series — block snapshot if stale):**

| series_id | Description | Source | Staleness threshold |
|---|---|---|---|
| `gold_price_proxy` | Gold spot XAUUSD | Stooq JSON + Yahoo fallback | 3 days |
| `rates_vol_stress_move` | MOVE Index bond stress | Yahoo (`^MOVE`) | 3 days |
| `DFII10` | 10Y TIPS real yield | FRED | 3 days |
| `DFII5` | 5Y TIPS real yield | FRED | 3 days |
| `DGS10` | 10Y Treasury nominal yield | FRED | 3 days |
| `DGS2` | 2Y Treasury nominal yield | FRED | 3 days |
| `DGS5` | 5Y Treasury nominal yield | FRED | 3 days |
| `T10YIE` | 10Y breakeven inflation | FRED | 3 days |
| `T5YIE` | 5Y breakeven inflation | FRED | 3 days |
| `T5YIFR` | 5Y/5Y forward inflation | FRED | 3 days |
| `DFF` | Effective fed funds rate | FRED | 3 days |
| `EFFR` | NY Fed EFFR | FRED | 3 days |
| `DTWEXBGS` | Broad USD index (goods) | FRED | **10 days** (structural publish lag) |
| `VIXCLS` | VIX equity implied vol | FRED | 3 days |
| `SP500` | S&P 500 index | FRED | 3 days |

**Tier-2 (5 series — warn only):**

| series_id | Description | Source | Staleness threshold |
|---|---|---|---|
| `gld_holdings_flow_confirm` | GLD Trust ounces held | Yahoo via yfinance | 5 days |
| `CPILFESL` | Core CPI | FRED | 45 days |
| `FEDFUNDS` | Fed funds rate monthly avg | FRED | 45 days |
| `PCEPI` | Headline PCE | FRED | 45 days |
| `PCU2122212122210` | PPI: Gold ore mining (discontinued 2017) | FRED | disabled |

### Staleness threshold rationale

- **3 days** for daily FRED series: covers a two-day weekend plus one day of FRED release lag
- **10 days** for DTWEXBGS: FRED publishes this series with a structural ~1 week lag; 10 days is not generous, it reflects the source's actual publication cadence
- **45 days** for monthly macro series: BLS/BEA release cycle; WARN status on these is expected and correct behavior, not a fault
- **disabled** for PCU2122212122210: discontinued 2017; staleness check is meaningless

---

## 6. Data Sources and Adapter Responsibilities

### A. Gold Adapter (`gold_adapter.py`) — Tier-1

**Role:** Primary asset state. Missing or stale = no snapshot published.

**Source cascade (priority order):**
1. Local JSON file (`gold_xauusd_stooq_2014_yesterday.json`) — bulk history backfill
2. gold-api.com spot price — free, no API key, stdlib only
3. Yahoo Finance (`GC=F` futures) — fallback, requires yfinance
4. Stooq (`^xauusd`) — last-resort fallback

**Caveat:** Gold history starts 2014-01-02. Target is 2005 for broader calibration coverage (2008 crisis, 2011 peak). This is a known data gap, not an implementation error.

---

### B. MOVE Adapter (`move_adapter.py`) — Tier-1

**Role:** Rates-vol / bond-stress sensor. Missing or stale = no snapshot published.

**Source:** Yahoo Finance (`^MOVE`) is the primary and recommended source. Stooq (`^move`) is unreliable on weekends and returns "No data" intermittently. Yahoo is confirmed working on weekends.

**History:** Starts 2021-03-06.

---

### C. GLD Holdings Adapter (`gld_holdings_adapter.py`) — Tier-2

**Role:** Physical gold flow confirmation signal. Non-blocking — never prevents snapshot publication.

**Source:** Yahoo Finance via yfinance. `source` label stored in DB: `yahoo_gld_proxy`.

**⚠️ Known approximation:**
```
ounces = shares_outstanding × 0.09585
```
Yahoo returns *current* `shares_outstanding` only, not historical per-day values. This figure is applied uniformly across all requested dates. The 0.09585 ratio is fixed per GLD prospectus and does not change. `is_estimate=true` is set in the registry. This approximation is accepted for a Tier-2 confirmation signal — large deviations are the signal, not the daily micro-movements.

Verified March 2026: 260,300,000 × 0.09585 = 24,949,755 oz = 776.0 tonnes.

Any backtest output using this series must label it as an approximation.

---

### D. FRED Loader (`fred_loader.py`) — Tier-1 + Tier-2

**Role:** Loads all 20 FRED series (15 Tier-1 + 5 Tier-2) from the FRED API.

**Source:** FRED API. Requires a free API key at `fredaccount.stlouisfed.org/apikeys`, stored in `.secrets/fred_api_key.txt`.

**Rate limit:** 0.5 second delay between API calls (FRED limit: 120 requests/minute).

**Notable behavior:**
- `--full-history` loads each series from its configured start date in the registry
- `--backfill-days N` loads the last N days (used for daily EOD top-ups)
- DTWEXBGS has a structural ~1 week FRED publish lag — this is expected; 10-day threshold accounts for it
- PCU2122212122210 is discontinued (2017); its staleness check is disabled in the registry

**Key env vars:**

| Variable | Default | Description |
|---|---|---|
| `L2_FRED_KEY_PATH` | `.secrets/fred_api_key.txt` | Path to FRED API key file |
| `L2_DB_PATH` | `layer2_truth.db` | SQLite DB path |

---

### E. Quality Gate (`quality_gate.py`) — Snapshot gatekeeper

**Role:** Evaluates all 23 series for staleness, computes a PASS/FAIL verdict, and exposes the aligned payload for the snapshot publisher to reuse.

**Behavior:**
- Alignment is computed once per run inside the gate
- The aligned payload is passed directly to `snapshot_publisher.py` via the quality report dict — alignment is never computed twice per publish cycle
- Exit code: 0 = PASS, 1 = FAIL
- Output: `layer2_quality_report.json` (gitignored, generated fresh each run)

**`--force` behavior:** The quality gate always runs. `--force` logs `WOULD BLOCK` warnings but does not abort. The resulting snapshot is permanently marked `forced=True` in DB and JSON. Forced snapshots should be filtered out of backtests and replay analysis.

---

### F. Snapshot Publisher (`snapshot_publisher.py`) — Layer-3 contract boundary

**Role:** Runs the quality gate internally, then publishes a point-in-time snapshot. This is the only write path to the Layer-3 contract.

**Exit codes:** 0 = snapshot published or already exists; 1 = quality gate FAIL or Tier-1 completeness error.

**Key environment variables:**

| Variable | Default | Description |
|---|---|---|
| `L2_ENGINE_VERSION` | `gold-v3.3.0` | Engine version tag stored in every snapshot |
| `L2_REGISTRY_PATH` | `series_registry.json` | Path to registry file for `config_version` resolution |
| `L2_DB_PATH` | `layer2_truth.db` | SQLite DB path |
| `L2_SNAPSHOT_PATH` | `latest_snapshot.json` | JSON output path |
| `L2_CLOCK_TIMEZONE` | `UTC` | Clock timezone |
| `L2_CLOCK_CUT_HOUR` | `22` | Daily cut hour (policy choice, not a constant) |

**CLI flags (v2):** `--date` (was `--clock-date`), `--db-path` (was `--db`). Update any scheduler scripts using the old names.

---

## 7. Database Schema and Truth-Layer Storage Rules

### Storage engine

SQLite (`layer2_truth.db`). WAL journal mode. Foreign keys enforced.

### `observations` table — immutable truth store

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

**Key storage rules:**

- **`INSERT OR IGNORE`** — the only write operation. First write wins. Reruns are idempotent and cannot silently overwrite history.
- **`revision_seq = 0`** for all current ingestion. If FRED revises a historical value, the correction is written as `revision_seq = 1` (same `series_id`, `obs_ts`), leaving the original rev-0 row intact. The revision writer (`rev=1` path) is not yet built. FRED corrections are currently silently dropped.
- **`as_of_ts`** records when the observation was known / published, not when it was ingested. This is the "vintage" timestamp used in point-in-time alignment.

### `snapshots` table — published snapshot registry

```sql
CREATE TABLE snapshots (
    snapshot_id     TEXT      PRIMARY KEY,
    clock_ts        TIMESTAMP NOT NULL,
    engine_version  TEXT      NOT NULL,
    config_version  TEXT      NOT NULL,
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
CREATE INDEX idx_snapshots_clock_engine_config
    ON snapshots (clock_ts DESC, engine_version, config_version);
```

**Key fields:**
- `engine_version`: value of `L2_ENGINE_VERSION` env var at publish time
- `config_version`: `registry_version` value from `series_registry.json` at publish time
- `forced`: permanently `1` if published with `--force`; use this to exclude from backtest analysis
- `dry_run`: permanently `1` if run with `--dry-run`

**Auto-migration:** Existing DBs created before `engine_version`/`config_version` were added are automatically migrated on next `get_connection(with_snapshot_tables=True)` call via `_ensure_snapshot_schema_migrations()`. Migrated rows receive sentinel values `UNKNOWN_ENGINE_VERSION` / `UNKNOWN_CONFIG_VERSION` — identifiable and filterable in replay queries.

### `snapshot_values` table — per-series snapshot data

```sql
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

One row per series per snapshot. Joined to `snapshots` by `snapshot_id`.

### Deduplication logic

`_snapshot_exists()` checks three fields before writing: `clock_ts`, `engine_version`, and `config_version`. The same `clock_ts` can legitimately yield multiple valid snapshots under different engine or config versions (e.g., after a hotfix). Three-way dedup prevents both silent overwrites and false "already exists" blocks.

---

## 8. Quality Gate and Snapshot Publication

### Quality gate rules

| Tier | Series count | Staleness threshold | Effect if stale |
|---|---|---|---|
| Tier-1 | 15 | 3 days (DTWEXBGS: 10 days) | Blocks snapshot — nothing published |
| Tier-2 | 5 | 5–45 days | Warning only — never blocks |

Any single Tier-1 FAIL produces verdict `FAIL` → `snapshot_publisher.py` blocks publication → Layer-3 receives nothing.

### Publication preconditions

The snapshot publisher checks all of the following before writing:

1. Quality gate verdict is PASS (or `--force` is set)
2. `engine_version` is non-empty (resolved from `L2_ENGINE_VERSION`)
3. `config_version` is resolvable (from `registry_version` in `series_registry.json`)
4. Tier-1 series completeness: all required Tier-1 series are present in the aligned payload; any missing series blocks publication unless `--force` is set
5. Snapshot does not already exist for this `clock_ts` + `engine_version` + `config_version` combination

### Snapshot publication outputs

On a successful publish:
- One row written to `snapshots` table
- One row per series written to `snapshot_values` table
- `latest_snapshot.json` written to disk

`latest_snapshot.json` is the convenience handoff interface. It is gitignored and regenerated on each publish.

### `--force` behavior

`--force` does not skip the quality gate. The gate always runs. With `--force`, a FAIL verdict produces `WOULD BLOCK` log warnings but does not abort. The snapshot is published and permanently marked `forced=True` in the DB and JSON. Forced snapshots should not be used in backtests or calibration without explicit filtering.

---

## 9. Versioning, Determinism, and Snapshot Identity

### `engine_version`

Set via the `L2_ENGINE_VERSION` environment variable (default: `gold-v3.3.0`). Stored in every snapshot row and included in the `snapshot_id` hash. Gate logic downstream must be version-locked to this value to maintain replay integrity.

### `config_version`

Derived from `registry_version` in `series_registry.json`. Resolved by `_get_config_version()` using a multi-path fallback chain: registry object attribute → `to_dict()` method → direct JSON file read. Raises `RuntimeError` if unresolvable. Any change to series metadata that results in a new `registry_version` value produces a distinct `config_version` in all subsequent snapshots — making each snapshot traceable to the exact registry state that produced it.

### `snapshot_id` computation

```
SHA-256 of:
  clock_ts=<ISO-8601>
  engine_version=<string>
  config_version=<string>
  <series_id>=<obs_ts>:<value:.6f>:<as_of_ts>:<revision_seq>
  ... (one line per series, sorted by series_id)
```

The hash payload includes the full aligned series state — `obs_ts`, `value`, `as_of_ts`, and `revision_seq` per series. "Same data" is therefore more precisely "same aligned series state." Two runs with different `as_of_ts` values (e.g., after a late FRED revision) will produce different `snapshot_id` values even for the same `clock_ts`.

### Downstream trust requirements

For Layer-3 to trust a snapshot as deterministic and replayable, it must:
- Validate `engine_version` matches the expected value before consuming
- Validate `config_version` matches the expected registry state
- Treat any `forced=True` snapshot as potentially non-compliant data

---

## 10. Current Implementation State

*As of 2026-03-07 — current documented implementation status.*

### Current documented status — complete

| Component | Notes |
|---|---|
| All 6 adapters | Gold, MOVE, GLD, FRED loader, quality gate, snapshot publisher |
| Registry wiring — all 6 adapters | Documented as complete; registry imports confirmed present in all adapter files per `SYSTEM_IMPLEMENTATION_RECORD_v1.md` §14 |
| Quality gate | 15/15 Tier-1 PASS as of last documented run (2026-03-06) |
| Snapshot publisher | Produces versioned, deterministic snapshots |
| `engine_version` + `config_version` in snapshots | `db.py` v2, `snapshot_publisher.py` v2 |
| Three-way snapshot dedup | `clock_ts + engine_version + config_version` |
| Auto-migration for existing DBs | `_ensure_snapshot_schema_migrations()` |

### Required before Layer-3 bootstrap starts

| Item | Why |
|---|---|
| `guards` structured object in snapshot JSON | Layer-3 evaluates hard veto conditions (`data_ok`, `idempotent_ok`) from this field |
| `reason_code` enum in shared constants | Prevents free-text at the execution boundary |
| README and code in sync on contract behavior | Confirmed doc/code sync pass required per `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` §6 |

### Recommended but not mandatory for bootstrap start

- Simple end-to-end orchestrator script
- `layer1_events: []` stub in snapshot JSON (forward-compatible interface slot)
- Basic scheduler

### Required before live execution only

- Daily scheduler
- Alerting / notification on adapter failure
- Retry logic with cap
- Kill switch (fail-closed)
- Full operational hardening

These items do not block Layer-3 core development. They block connecting any live execution path.

---

## 11. Known Gaps and Approximations

### Approximations — accepted estimates, not bugs

Label all of these explicitly in any backtest output.

| Item | Approximation | Impact |
|---|---|---|
| GLD holdings (`gld_holdings_flow_confirm`) | `shares_outstanding` applied uniformly to past dates; not true per-day historical | Tier-2 signal only; never blocks snapshot |
| Gold history | Backfill starts 2014-01-02; target is 2005 | Pre-2014 calibration window unavailable (2008 crisis, 2011 peak missing) |
| SP500 history | FRED data starts 2016-02-22; backtest needs 2014 | 2015 China shock and early 2016 selloff excluded from calibration window |
| Monthly macro series (CPI, PCE) | FRED may revise; `revision_risk` not yet tracked in `observations` | Downstream confidence penalty not yet applied; revision exposure unacknowledged |

### Structural gaps

| Item | Severity | Notes |
|---|---|---|
| `guards` object absent from snapshot JSON | **High** | Blocks Layer-3 bootstrap gate |
| `reason_code` enum not defined | **High** | Blocks Layer-3 bootstrap gate |
| SP500 history gap (2014–2016) | **High** | Fix via SPY/Yahoo planned |
| `revision_risk` column not in `observations` | Medium | Architecture requires marking revision-exposed series; not yet implemented |
| Revision writer not built | Medium | `revision_seq=1` write path absent; FRED corrections silently dropped |
| No end-to-end orchestrator | Medium | Pipeline run manually per step |
| No scheduler, alerting, or kill switch | Medium | Required before any live operation |
| `--full-reload` help text stale | Low | Describes deprecated `INSERT OR REPLACE` behavior; now uses `INSERT OR IGNORE` |
| Discontinued USD series in DB | Low | DTWEXM, DTWEXO, TWEXB (discontinued 2019–2020) — bridge or drop |
| Gold history starts 2014 | Low | Target 2005 for complete crisis coverage |

---

## 12. Layer-3 Bootstrap Gate

### What Layer-3 receives from Layer-2

Layer-3 must consume only `latest_snapshot.json` or the `snapshots` + `snapshot_values` DB tables via `snapshot_id`. Direct `observations` access is forbidden.

**Stable contract fields:**

```json
{
  "snapshot_id":    "<64-char SHA-256>",
  "engine_version": "gold-v3.3.0",
  "config_version": "<registry_version>",
  "clock_ts":       "<date>T22:00:00+00:00",
  "clock_date":     "<date>",
  "verdict":        "PASS | FAIL",
  "forced":         false,
  "tier1_series":   { "<series_id>": { "obs_ts", "value", "staleness_days", "source" } },
  "tier2_series":   { "<series_id>": { "obs_ts", "value", "staleness_days", "source" } },
  "missing_series": []
}
```

*22:00 UTC is the default cut time — configurable via `L2_CLOCK_CUT_HOUR`.*

**Consumption interfaces:**
- **Canonical (persisted):** query `snapshots` + `snapshot_values` by `snapshot_id`
- **Convenience (handoff):** read `latest_snapshot.json`
- **Forbidden:** querying `observations` directly

### Still needed in snapshot output for bootstrap

| Item | Status | Why Layer-3 needs it |
|---|---|---|
| `guards` structured object | ⬜ Not yet built | Layer-3 evaluates `data_ok`, `idempotent_ok`, `cooldown_ok`, `risk_ok`, `supervisor_veto` hard veto conditions from this |
| `reason_code` enum | ⬜ Not yet built | Layer-3 must emit only enumerated reason codes; no free text at execution boundary |
| `layer1_events: []` stub | ⬜ Optional | Forward-compatible slot for future Layer-1 event hooks; recommended for interface stability |

### Layer-3 bootstrap build sequence (planned — not yet started)

From `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` §7 (target, not current implementation):

1. Snapshot consumer — reads snapshot, validates `engine_version` + `config_version`
2. Feature builder stub — 2–3 deterministic calculations only
3. DecisionPacket skeleton — `action: NOTHING`, `reason_code: NO_SIGNAL`, all guards false
4. NO_TRADE default path

**Example first calculations (deterministic, no regime logic):**
- Real yield spread (DFII10 − DGS10)
- Inflation expectation spread (T10YIE − T5YIE)
- Stress placeholder (VIXCLS + MOVE combined)

**Phase 1 non-goals:** full regime engine, calibration, supervisor policy, live execution.

---

## 13. Live Execution Boundary

Live execution is a **separate and later gate** from Layer-3 bootstrap. These two gates must not be conflated.

### What belongs to the live execution gate (not Layer-2, not Layer-3 bootstrap)

From `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` §15:

- Layer-3 paper-mode validation complete
- Calibration criteria met (≥100–300 decision ticks; monotonic calibration holds; Brier score, CVaR, regime breakdown validated)
- DecisionPacket schema frozen
- Zapier-style validation harness passing end-to-end
- Kill switch tested and confirmed fail-closed
- Full operational readiness in place (scheduler, alerting, retry with cap)

### Session-aware execution policy

Session-aware execution policy — determining whether a decision is `ALLOWED`, `REDUCED_ONLY`, `PAPER_ONLY`, or `BLOCKED` for the current session, liquidity, or operational state — is an execution-layer concern. It belongs to live execution readiness, not Layer-2 or Layer-3 bootstrap.

Layer-3 defines signal intent through the deterministic `DecisionPacket`. Session-aware policy determines execution permissibility downstream of that intent. It must not invent direction or override `reason_code` semantics.

Layer-4 (execution orchestration) is intentionally unwired until the live execution gate is satisfied.

---

## 14. Documentation and Integrity Notes

### What reflects current documented behavior

The following represent current documented technical status as recorded in `SYSTEM_IMPLEMENTATION_RECORD_v1.md`. These reflect the state of the codebase as described in the project's own documentation and audit log — not an independently certified verification.

- All 6 adapters functional and registry-wired
- `engine_version` + `config_version` in snapshot schema, JSON, and `snapshot_id` hash
- Three-way snapshot dedup
- Auto-migration for existing DBs
- `INSERT OR IGNORE` immutability throughout
- Quality gate documented to produce PASS/FAIL verdicts based on registry-governed staleness rules
- Alignment query documented as deterministic for the same governed clock state
- `guards` object present in snapshot JSON
- `reason_code` enum present in shared constants
- `layer1_events: []` present in snapshot JSON
- A successful non-forced snapshot publication has been observed, with the snapshot written to DB and `latest_snapshot.json`

### What is forward-looking or not yet implemented

The following items are documented in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` as part of the target architecture but are **not yet implemented in Layer-2**:

- `revision_risk` tracking
- Revision writer (`revision_seq=1` path)
- Session-aware execution policy (belongs to Layer-4, not Layer-2)
- Layer-3 Feature Builder, Index Suite, Regime Gate, Supervisor Engine, Decision Engine

### Code integrity log summary

Five audit cycles were completed between 2026-03-05 and 2026-03-07. Key resolved issues:

| Audit | Critical/High fixes |
|---|---|
| Audit 1 | `INSERT OR REPLACE` → `INSERT OR IGNORE`; date type normalization; Python 3.12 compatibility |
| Audit 2 | `snapshot_id` extended to 64-char SHA-256; `run_ts` separated from `clock_ts`; registry introduced as single source of truth |
| Audit 3 | `forced` column added to schema; batch hash truncation fixed |
| Audit 4 | `--force` now runs real gate (hardcoded summary eliminated); GLD source label made consistent |
| Audit 5 | `engine_version` + `config_version` added to schema, hash, and JSON; auto-migration added; three-way dedup implemented |

Full audit log: `SYSTEM_IMPLEMENTATION_RECORD_v1.md` §14.

The current `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` is the classification layer for current documentation claims. A future deeper line-by-line implementation verification artifact would still be the appropriate place to formally confirm each claim against specific file, function, and schema references.

### Verification Status

> **Canonical interim verification status for the v1 documentation set** — until a formal Documentation Verification Matrix exists, use this subsection as the single reference for open verification-state items.

| Area | Scope | Date | Current result |
|---|---|---|---|
| Repo hygiene | Verify whether `layer2_truth.db` and related runtime artifacts are excluded from the repository as intended | 2026-03-14 | ⬜ Not yet re-verified; treat repo-hygiene status as open until explicitly checked |
| Doc/code sync | Confirm that `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, and the documented Layer-2 → Layer-3 handoff contract remain in sync | 2026-03-14 | ⬜ Not yet completed; remains required before Layer-3 bootstrap |

### Open repo-hygiene verification issue

`layer2_truth.db` is documented as gitignored, but the file was observed committed in the repository as of 2026-03-07. This is an open inconsistency between the documented intent and the observed repo state — it has not been resolved or confirmed fixed. Verify that `.gitignore` is correctly applied to all runtime artifacts before the next collaborator onboards.

---

*This handbook covers Layer-2 current state as of 2026-03-16. For architecture sequencing and Layer-3 / Layer-4 target design, see `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`.*
