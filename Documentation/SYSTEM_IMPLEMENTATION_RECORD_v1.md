# SYSTEM_IMPLEMENTATION_RECORD_v1
## Mr. Ripley — Build Record and Implementation Notes

> **Document role:** canonical implementation record, realized-state reference, and long-form technical history
> **Status:** retained as a long-form build / implementation document
> **Current entry-point document:** `README_v1.md`
> **Current engineering reference:** `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
> **Current limitations / approximations doc:** `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
> **Current architecture / sequencing doc:** `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
> **Last updated:** 2026-03-22

This document preserves long-form Layer-2 build history, implementation detail, realized-state evidence, and audit context.

It is part of the canonical current-state set, but its authority is role-specific.
Use this document for implementation-state and realized-build questions, not as a blanket override for architecture, limitations, or collaborator workflow.
If this document conflicts with a more role-matched canonical document on those topics, the role-matched canonical document takes precedence.

---

## 1. Document Position in the Documentation Set

| Document | Role |
|---|---|
| `README_v1.md` | Short entry-point summary for engineers onboarding into the repo |
| `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Structured engineering reference for the current system state |
| `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Explicit record of known gaps, approximations, and interpretation risks |
| `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architecture framing, handoff sequencing, Layer-3 bootstrap boundary, and later live-execution gate |
| Layer-3 decision philosophy | State-driven / event-driven model — frozen 2026-03-22. Full detail in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7. |
| Layer-3 DecisionPacket schema v0 | Governed action contract — frozen 2026-03-22. Full field reference in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7. |
| Architecture change rationale | Timeframe-centered model replaced by state-driven model. Change recorded in 2026-03-22 addendum below. |
| `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Classification layer for current doc claims |
| `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Long-form build record, implementation notes, audit history, and detailed technical reference |

---

## 2. Current-State Addendum (2026-05-01)

### 2.0-A revision_risk contract completion — Phase 1 (2026-05-01)

Implemented the minimal contract-complete `revision_risk` patch for Layer-2 snapshot JSON handoff:

- `series_registry.json`: `revision_risk` added as a required `bool` field on all 23 series. Monthly macro series (`CPILFESL`, `PCEPI`, `FEDFUNDS`, `PCU2122212122210`) set `true`; all daily market/yield/price series and discontinued series set `false`.
- `layer2/config/registry.py`: `revision_risk: bool` added to `_REQUIRED_FIELDS` (validation enforced at load time). `revision_risk(series_id)` lookup method added.
- `layer2/alignment.py`: `AlignedSeriesValue` extended with `revision_risk: bool`. `to_dict()` and `build_snapshot_values_payload()` include it. `align_snapshot_state()` looks up `revision_risk` from registry at alignment time — no DB column added.
- `layer2/adapters/quality_gate.py`: `run_quality_gate()` returns `revision_risk_series_count` and `revision_risk_series` in `summary`.
- `layer2/adapters/snapshot_publisher.py`: `write_snapshot_json()` emits `revision_policy`, `revision_risk_summary`, and per-series `revision_risk` in `values`, `tier1_series`, and `tier2_series`. Minimal quality check fallback propagates `revision_risk` from registry.
- `tests/layer2/test_revision_risk.py`: 19 tests covering registry validation, canonical classification, alignment payload, quality gate summary, and snapshot JSON contract.

Constraints honored:
- `revision_risk=true` does not block snapshot publication.
- `snapshot_id` hash unchanged (revision_risk is not a hash input — it is registry metadata, not observation data).
- Tier-1 fail-closed behavior unchanged.
- No DB schema changes.
- Layer-3 not built.
- Revision writer (`revision_seq=1` write path) not implemented.

---

## 3. Current-State Addendum (2026-04-18)

This addendum supersedes earlier addenda where they conflict.

### 2.0 Layer-2 refactor (2026-04-18)

- All four ingestion adapters (`gold_adapter.py`, `move_adapter.py`, `fred_loader.py`, `gld_holdings_adapter.py`) migrated from `layer2.adapters.v0.db` / `layer2.adapters.v0.clock` to canonical `layer2.db` / `layer2.clock`
- `layer2/adapters/v0/` directory removed (zero external dependencies confirmed)
- `layer2/index_suite.py` canonically classified as a Layer-2 internal pre-publication computation tool (distinct from the planned Layer-3 Index Suite)

### 2.1 Layer-2 status (unchanged from 2026-03-15 / 2026-03-16)

The following remain true:

- `guards` object is present in snapshot JSON
- `reason_code` enum exists in shared constants
- `layer1_events: []` stub is present in snapshot JSON
- canonical `layer2/clock.py` governs current clock semantics
- snapshot publisher uses the aligned quality-gate payload path
- a successful **non-forced snapshot publication** has been executed
- snapshot publication wrote both a DB snapshot record and `latest_snapshot.json`
- `layer2/index_suite.py` computes provisional M1 indices (stress, drift, correlation-break, data-freshness) from point-in-time aligned observations — classified as a **Layer-2 internal pre-publication computation tool**, distinct from the planned Layer-3 Index Suite (which will consume published snapshots, not raw observations)

Observed successful publication:

- `snapshot_id`: `a562bef5b93fa07794e9b73c17a24ddad0ce271678fd52cc939ac1d4cae32526`
- `engine_version`: `gold-v3.3.0`
- `config_version`: `1.0.0`
- `clock_ts`: `2026-03-15T22:00:00+00:00`
- Tier-1 gate result: `15 / 15 PASS`

### 2.2 Layer-3 philosophy frozen (new as of 2026-03-22)

The Layer-3 decision philosophy has been frozen as of 2026-03-22.

Key decision recorded here for historical reference:

**Previous implicit direction:** Layer-3 framing still contained timeframe-centered execution language (e.g. explicit `timeframe: "5m"` field in example DecisionPacket).

**New frozen direction:** Layer-3 is a **state-driven / event-driven decision system**. The canonical principle: *the system decides because state changed enough to justify governed action — not because a fixed amount of time elapsed.*

The rationale: fixed-timeframe decision logic is too rigid for material non-time-based market regime changes. The system must react to state changes, not clock cycles. Replayability, fail-closed discipline, and supervisor governance are preserved unchanged.

### 2.3 DecisionPacket schema v0 defined (new as of 2026-03-22)

The Layer-3 DecisionPacket schema v0 defines the governed action contract. Full field reference is in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7.

Key changes from the earlier example packet preserved in `README_LAYER2.md` section 16:

| Earlier example packet field | v0 schema field | Change |
|---|---|---|
| `action: "BUY \| SELL \| NOTHING"` | `preferred_action` from `allowed_actions` set | Richer, explicit allowed-set semantics |
| `timeframe: "5m"` | Removed | Timeframe is not a governed concept in state-driven design |
| `guards: {data_ok, idempotent_ok, ...}` | `data_ok`, `freshness_ok`, `supervisor_ok`, `cooldown_ok`, `duplicate_ok`, `operational_ok` | Expanded guard taxonomy |
| `reason_code: "<ENUM_ONLY>"` | `reason_code` + `reason_detail_codes` + `no_trade_reason` | Structured reason hierarchy |
| No cooldown / duplicate fields | `cooldown_until`, `duplicate_protection_key`, `max_valid_until`, `invalidation_condition` | Explicit timing / deduplication controls |

The `snapshot_id` anchor was already present in the earlier model and remains mandatory in v0.

---

## 3. Interpretation Rule

Read this document when you need:

- implementation detail beyond the entry-point README
- historical build context
- schema-level and pipeline-level detail
- adapter usage detail
- audit history and rationale

Do **not** use this document alone to determine:
- current bootstrap readiness
- current handoff-gate truth
- live execution readiness
- Layer-3 design decisions

Use the current v1 document set first.

---

## 4. Preserved Historical Body

The remainder of this document intentionally preserves the retained implementation record.

It remains useful for:

- historical reasoning
- migration context
- adapter-by-adapter detail
- preserved audit trail

Where the preserved historical body still describes now-resolved contract blockers as open, the current v1 documents and the addenda above override it.

Where the preserved historical body describes Layer-3 in timeframe-centered terms (e.g. `timeframe: "5m"` in the DecisionPacket example in section 16), those descriptions are superseded. The current Layer-3 design is documented in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7.
