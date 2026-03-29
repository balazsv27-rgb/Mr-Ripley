# Mr. Ripley — Layer-2 Truth Layer

> **Repo:** `github.com/balazsv27-rgb/Mr-Ripley`
> **Last updated:** 2026-03-22
> **Architecture reference:** `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
> **Engineering reference:** `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
> **Limitations / approximations:** `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`

---

## 1. Project Purpose

Layer-2 is the **data ingestion and truth store** for the Mr. Ripley gold-first decision engine.

Its job is to:

- ingest governed market and macro data
- validate freshness and completeness
- align data point-in-time against a governed clock boundary
- publish deterministic snapshots that Layer-3 consumes as a stable API

Layer-2 ends at snapshot publication. It does **not** compute features, regimes, supervisor decisions, or execution actions.

---

## 2. Current Operational Status

**Current status as of 2026-03-22:**

- Layer-2 ingestion adapters are operational
- quality gate is operational
- canonical clock path is operational
- snapshot publisher is operational
- a **successful non-forced snapshot publication** has been executed
- `latest_snapshot.json` has been generated successfully
- Layer-2 → Layer-3 handoff contract is now operational
- Layer-3 is **not yet built**
- Layer-3 decision philosophy is now frozen: state-driven / event-driven, not timeframe-driven
- Layer-3 DecisionPacket schema v0 is now defined as a governed action contract

### Verified publication example

A successful non-forced snapshot publication was executed with:

- `snapshot_id`: `a562bef5b93fa07794e9b73c17a24ddad0ce271678fd52cc939ac1d4cae32526`
- `engine_version`: `gold-v3.3.0`
- `config_version`: `1.0.0`
- `clock_ts`: `2026-03-15T22:00:00+00:00`
- `verdict`: `PASS`
- `forced`: `false`

At that publication boundary, the quality gate reported:

- Tier-1: `15 / 15 PASS`
- Tier-2: `2 warnings / 5 total`

---

## 3. What Layer-2 Is

Layer-2 is:

- **Registry-driven** — series metadata, tiering, thresholds, and snapshot inclusion come from `series_registry.json`
- **Fail-closed** — any Tier-1 blocking failure prevents snapshot publication
- **Version-locked** — every snapshot carries `engine_version`, `config_version`, and deterministic `snapshot_id`
- **Point-in-time disciplined** — alignment is governed by `obs_ts <= clock_date` and `as_of_ts <= clock_ts`
- **Immutable by default** — rev-0 observations are not silently overwritten
- **A snapshot boundary** — Layer-3 may consume snapshots, not raw `observations`

---

## 4. What Layer-2 Is Not

Layer-2 is **not**:

- a feature engineering layer
- an index suite
- a regime engine
- a supervisor engine
- a DecisionPacket generator
- a live execution system

Layer-3 must never query `observations` directly.

---

## 5. Architecture Position

```
Layer-1  →  Event Tagger / Narrative Risk Modifiers   (optional, disabled by default)
Layer-2  →  Ingestion + validation + snapshot store    ← YOU ARE HERE
Layer-3  →  State-driven decision engine               (not yet built — philosophy frozen)
Layer-4  →  Execution orchestration                    (not yet built / intentionally unwired)
```

Layer-3 note: the decision engine is **state-driven / event-driven**, not timeframe-driven.
It will consume three governed inputs: Snapshot Truth, Live Market State, and Event Risk Stream.
The engine consumes three governed inputs: Snapshot Truth (authoritative replayable base from Layer-2), Live Market State (fast intraday triggers), and Event Risk Stream (penalty and override only — never directional). It decides because state changed materially, not because time passed.

---

## 6. Core Components

Current Layer-2 components:

- `layer2/config/series_registry.json` — registry single source of truth
- `layer2/config/registry.py` — registry loader / validator
- `layer2/clock.py` — canonical engine clock
- `layer2/alignment.py` — point-in-time alignment
- `layer2/adapters/quality_gate.py` — completeness / freshness gate
- `layer2/adapters/snapshot_publisher.py` — snapshot publication boundary
- `layer2/db.py` — observation and snapshot persistence helpers

Current adapters in active use:

- `gold_adapter.py`
- `move_adapter.py`
- `gld_holdings_adapter.py`
- `fred_loader.py`

---

## 7. Snapshot Contract

Current published snapshot fields include:

- `snapshot_id`
- `engine_version`
- `config_version`
- `clock_ts`
- `clock_date`
- `verdict`
- `forced`
- `dry_run`
- `guards`
- `tier1_series`
- `tier2_series`
- `missing_series`
- `layer1_events`

Additional informational fields currently included:

- `run_ts`
- `published_at`
- `series_count`
- `quality_summary`
- `values_by_group`
- `values`

The published snapshot also exposes `as_of_ts` and `revision_seq` inside grouped / flat value views.

The `snapshot_id` field is the **primary anchor** for Layer-3 DecisionPackets. Every DecisionPacket must carry the `snapshot_id` of the governing snapshot used as its truth base..

---

## 8. Handoff Gate Status

The Layer-2 → Layer-3 handoff gate is now satisfied at the snapshot-contract level.

Specifically:

- snapshot contract is stable enough to be consumed as an API
- `engine_version` and `config_version` are present in outputs
- `guards` object exists in snapshot JSON
- `reason_code` shared enum exists
- a successful real snapshot publish has been observed

This means **Layer-3 bootstrap may begin**.

This does **not** mean:

- Layer-3 exists already
- revision handling is complete
- scheduler / alerting / retry / kill switch are in place
- live execution is allowed

---

## 9. Layer-3 Design Status (updated 2026-03-22)

The Layer-3 decision philosophy is now frozen as of 2026-03-22: state-driven / event-driven model, three governed inputs, explicit trigger taxonomy, governed action contract output.

Key points relevant to Layer-2:

- Layer-3 consumes the **Snapshot Truth** from Layer-2 published snapshots — this is unchanged
- Layer-3 will also consume **Live Market State** and **Event Risk Stream** as governed inputs
- neither of those additional inputs may rewrite Layer-2 truth history or bypass the snapshot boundary
- `snapshot_id` anchors every DecisionPacket to a specific Layer-2 publication
- the fail-closed principle extends into Layer-3: if `data_ok = false` or `freshness_ok = false`, the packet must not recommend aggressive new entry

Layer-2 does not need to change to support the new Layer-3 design. The snapshot contract is sufficient.

---

## 10. Current Known Risks (Short Form)

These remain real, open items:

- `revision_risk` tracking is not complete
- revision writer is not built
- scheduler / orchestrator is not built
- alerting / retry / kill switch are not built
- Layer-3 components are not built
- SP500 history gap (FRED from 2016 only — SPY migration planned)
- repo hygiene for runtime artifacts should still be treated as an active check

See `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` for the full list.

---

## 11. Recommended Local Run Sequence

```bash
# Gold JSON source currently used successfully:
python layer2/adapters/gold_adapter.py --load-json ./FRED/gold_xauusd_stooq_2014_yesterday.json --live

python layer2/adapters/move_adapter.py --source yahoo --backfill-days 30
python layer2/adapters/fred_loader.py --full-history

# Validate / publish
python layer2/adapters/snapshot_publisher.py --dry-run
python layer2/adapters/snapshot_publisher.py
```

---

## 12. Interpretation Rule

Use the current canonical document set for current-state interpretation:

1. `README_v1.md` — entry point summary
2. `SYSTEM_TECHNICAL_HANDBOOK_v1.md` — Layer-2 engineering reference
3. `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` — gaps and open items
4. `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` — target architecture and build sequence
5. `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` — claim classification and document role map
6. `SYSTEM_IMPLEMENTATION_RECORD_v1.md` — canonical implementation record and realized-state reference
7. `README_LAYER2.md` — canonical collaborator guide and living Layer-2 reference