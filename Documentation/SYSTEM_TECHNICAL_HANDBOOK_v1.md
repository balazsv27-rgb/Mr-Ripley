# Layer-2 Technical Handbook
## Mr. Ripley — Gold-First Decision Engine

> **Entry-point summary:** `README_v1.md`
> **Architecture reference:** `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
> **Limitations / approximations:** `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
> **Historical implementation record:** `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
> **Last updated:** 2026-03-22

---

## 1. Purpose and System Role

Layer-2 is the truth and observation layer of the Mr. Ripley gold-first decision engine.

Its responsibilities are:

- ingest market and macro time-series data from external sources
- validate freshness against governed staleness rules
- store observations in an immutable, point-in-time correct store
- publish versioned, deterministic snapshots as the stable API consumed by Layer-3

Layer-2 responsibility ends at snapshot publication.

It does **not** compute:

- features
- indices
- regimes
- supervisor decisions
- execution actions

Any downstream computation is Layer-3 work.

---

## 2. Current Architecture Position

```
Layer-1  →  Event Tagger / Narrative Risk Modifiers   (optional, disabled by default)
Layer-2  →  Ingestion + validation + snapshot store    ← THIS DOCUMENT
Layer-3  →  State-driven decision engine               (not yet built — philosophy frozen)
Layer-4  →  Execution orchestration                    (not yet built / intentionally unwired)
```

Layer-3 must consume only published snapshots. It must never query `observations` directly.

Layer-3 note: as of 2026-03-22, the Layer-3 decision philosophy is frozen as of 2026-03-22. The engine will be state-driven / event-driven, consuming Snapshot Truth from Layer-2 alongside Live Market State and Event Risk Stream as additional governed inputs. Neither of those additional inputs may touch Layer-2 storage.

---

## 3. Core Invariants

| # | Invariant | Implication |
|---|---|---|
| 1 | Registry is the single source of truth | Series metadata, thresholds, and tiering come from `series_registry.json` |
| 2 | Fail-closed publication | Tier-1 blocking failures prevent snapshot publication |
| 3 | Version-locked snapshots | `engine_version`, `config_version`, and `snapshot_id` are part of the boundary |
| 4 | Point-in-time discipline | Alignment respects governed `clock_date` / `clock_ts` boundaries |
| 5 | Snapshot-only downstream reads | Layer-3 consumes snapshots, never raw `observations` |
| 6 | snapshot_id as DecisionPacket anchor | Every Layer-3 DecisionPacket must carry the `snapshot_id` of its governing snapshot |

---

## 4. Current Layer-2 Stack

Current documented Layer-2 stack:

- `layer2/config/series_registry.json`
- `layer2/config/registry.py`
- `layer2/clock.py`
- `layer2/alignment.py`
- `layer2/adapters/quality_gate.py`
- `layer2/adapters/snapshot_publisher.py`
- `layer2/db.py`

Current adapter set in documented use:

- `gold_adapter.py`
- `move_adapter.py`
- `gld_holdings_adapter.py`
- `fred_loader.py`

---

## 5. Layer-2 → Layer-3 Handoff Gate

### Required handoff items

| Item | Status |
|---|---|
| Snapshot contract stable | ✅ Done |
| `engine_version` + `config_version` reliable in snapshot outputs | ✅ Done |
| `guards` structured object in snapshot JSON | ✅ Done |
| `reason_code` enum defined in shared constants | ✅ Done |
| Current v1 docs aligned to current contract behavior | ✅ Done |
| Layer-3 decision philosophy frozen | ✅ Done |
| Layer-3 DecisionPacket schema v0 defined | ✅ Done |

### Current gate result

The contract-side Layer-2 → Layer-3 handoff gate is now satisfied.

This means Layer-3 bootstrap may begin.

---

## 6. Snapshot Publication Boundary

### Publication preconditions

A normal non-forced publication requires:

1. governed clock resolved
2. Tier-1 freshness / completeness pass
3. no blocking fail-closed condition
4. aligned point-in-time payload available
5. no duplicate snapshot for the same `clock_ts` + `engine_version` + `config_version`

### Publication outputs

A successful publication writes:

- one row to `snapshots`
- one row per included series to `snapshot_values`
- `latest_snapshot.json`

### Observed successful publication example

- `snapshot_id`: `a562bef5b93fa07794e9b73c17a24ddad0ce271678fd52cc939ac1d4cae32526`
- `engine_version`: `gold-v3.3.0`
- `config_version`: `1.0.0`
- `clock_ts`: `2026-03-15T22:00:00+00:00`
- Tier-1 gate result: `15 / 15 PASS`

---

## 7. Current Snapshot Contract

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

Current informational fields also included:

- `run_ts`
- `published_at`
- `series_count`
- `quality_summary`
- `values_by_group`
- `values`

Current published grouped / flat value views include `as_of_ts` and `revision_seq`.

### snapshot_id as Layer-3 anchor

The `snapshot_id` is the primary contract anchor between Layer-2 and Layer-3.

Every DecisionPacket emitted by Layer-3 must carry:
- `snapshot_id` — the governing snapshot used as truth base
- `snapshot_clock_ts` — the clock timestamp of that snapshot

This ensures every decision is replayable against a specific, immutable Layer-2 publication.
Every DecisionPacket must carry `decision_id`, `asset_id`, `engine_version`, `config_version`, `decision_ts`, and `snapshot_id` as identity fields. State timestamps must include `snapshot_clock_ts`, `live_state_ts`, and `event_state_ts`. See the Layer-3 section of `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` for the full field reference.

---

## 8. Quality Gate Semantics

The quality gate is a Layer-2 truth-discipline gate.

It exists to answer:

- Is Tier-1 complete?
- Is Tier-1 fresh enough under governed thresholds?
- Is publication allowed under normal fail-closed rules?

### Current observed publication boundary result

- Tier-1 total: 15
- Tier-1 pass: 15
- Tier-1 fail: 0
- Tier-2 total: 5
- Tier-2 warnings: 2

Tier-2 warnings do not block publication.

### Relationship to Layer-3 guard fields

The Layer-2 quality gate result maps directly to Layer-3 DecisionPacket guard fields:

| Layer-2 gate result | Layer-3 guard field | Implication |
|---|---|---|
| Tier-1 all pass | `data_ok = true`, `freshness_ok = true` | Packet may be actionable if other guards pass |
| Any Tier-1 fail | `data_ok = false` or `freshness_ok = false` | Packet must not recommend aggressive new entry |
| VERDICT: FAIL (no snapshot published) | No valid snapshot → Layer-3 cannot form a packet | `NO_TRADE` is the only valid output |

---

## 9. What Is Still Not Built

The following are still not built:

- revision writer
- complete `revision_risk` tracking
- scheduler / orchestrator
- alerting / retry / kill switch
- Layer-3 Feature Builder
- Layer-3 Index Suite
- Layer-3 Regime Gate
- Layer-3 Supervisor
- Layer-3 DecisionPacket generation
- Layer-3 Live Market State adapters
- Layer-3 Event Risk Stream integration
- live execution wiring

---

## 10. Verification Status

### Current verification framing

The current v1 document set now consistently reflects:

- contract-side handoff gate satisfied
- successful non-forced Layer-2 snapshot publication observed
- Layer-3 decision philosophy frozen
- Layer-3 not yet built
- live execution not ready

### Open verification / hygiene items that still matter

| Area | Current result |
|---|---|
| Repo hygiene for runtime artifacts | Still should be treated as an active check |
| Independent line-by-line code certification | Not available from documentation alone |
| Full revision-aware backtest hardening | Not yet complete |

---

## 11. Interpretation Rule

Use this handbook as the structured engineering reference for the current system state.

For:
- status classification → use `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
- remaining risks / approximations → use `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
- Layer-3 decision model → see `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7
- Layer-3 output contract → see `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7 (DecisionPacket field reference)
- long-form history → use `SYSTEM_IMPLEMENTATION_RECORD_v1.md`

`README_LAYER2.md` is part of the canonical set — collaborator guide and living build reference.
