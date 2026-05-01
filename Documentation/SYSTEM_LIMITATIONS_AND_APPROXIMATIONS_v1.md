# Known Gaps and Approximations
## Mr. Ripley — Layer-2 Truth Layer

> **Last updated:** 2026-05-01
> **Primary sources:** `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
> **Supporting sources:** `SYSTEM_IMPLEMENTATION_RECORD_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `README_LAYER2.md`

---

## 1. Why This Document Exists

Layer-2 is now operational as a truth-layer foundation and has successfully executed a non-forced snapshot publication.

It is still **not** a fully hardened or complete system.

This document is part of the canonical current-state set.
For limitation and approximation claims, this document is the preferred role-matched source.

This document tracks:

- known limitations
- accepted approximations
- future work
- operational gaps
- remaining Layer-2 hardening items
- items that still block live execution readiness

---

## 2. What Is No Longer a Bootstrap Blocker

The following were previously contract-side blockers for Layer-3 bootstrap and are now resolved:

| Item | Current status | Notes |
|---|---|---|
| `guards` structured object in snapshot JSON | ✅ Implemented | Present in current snapshot outputs |
| `reason_code` enum in shared constants | ✅ Implemented | Shared constants now define enumerated reason codes |
| `layer1_events: []` stub | ✅ Implemented | Forward-compatible snapshot slot |
| `engine_version` in snapshot output | ✅ Implemented | Present in current published snapshot shape |
| `config_version` in snapshot output | ✅ Implemented | Present in current published snapshot shape |
| Operational Layer-2 snapshot publication path | ✅ Implemented | Successful non-forced publish observed |
| Layer-3 decision philosophy frozen | ✅ Implemented | State-driven / event-driven model. Three governed inputs: Snapshot Truth, Live Market State, Event Risk Stream. |
| Layer-3 DecisionPacket schema v0 defined | ✅ Implemented | Governed action contract with identity, state, action, guard, reason, and invalidation fields. |

These items should no longer be described as open Layer-3 bootstrap blockers.

---

## 3. Current Real Limitations

### 3.1 Revision / vintage limitations

| Item | Why it matters | Current status |
|---|---|---|
| `revision_risk` flag in snapshot JSON | Monthly macro series (CPILFESL, PCEPI, FEDFUNDS, PCU2122212122210) carry `revision_risk=true` in aligned payload and snapshot JSON. Flag is interpretive metadata — does not block publication. Registry-driven, validated as required bool field. | ✅ Implemented (2026-05-01) |
| Revision writer not built | Historical corrections cannot yet be written as explicit higher revision rows (`revision_seq=1`). The current path always writes `revision_seq=0`. | ⬜ Open |

### 3.2 Operational limitations

| Item | Why it matters | Current status |
|---|---|---|
| No single orchestrator / end-to-end runner | Full daily workflow remains operator-driven | ⬜ Open |
| No scheduler | Daily refresh and publication are manual | ⬜ Open |
| No alerting / notification | Failures require active operator monitoring | ⬜ Open |
| No capped retry logic | Transient source failures remain manual recovery events | ⬜ Open |
| No kill switch | Required before any live execution path | ⬜ Open |

Note: the state-driven / event-driven Layer-3 model makes orchestration more important, not less. A multi-speed state model with Snapshot Truth, Live Market State, and Event Risk Stream inputs requires explicit scheduler discipline for each refresh cadence. These gaps should be prioritized before Layer-3 goes beyond bootstrap.

### 3.3 Layer boundary limitations

| Item | Why it matters | Current status |
|---|---|---|
| Layer-3 components not built | Feature / regime / supervisor / DecisionPacket stack does not yet exist | ⬜ Open |
| Live Market State adapters not built | Fast market state layer required for Layer-3 trigger detection | ⬜ Open |
| Event Risk Stream not built | Structured event risk input required for Layer-3 uncertainty escalation | ⬜ Open |
| Live execution not wired | System ends at validated snapshot publication | ⬜ Open |

### 3.4 Data limitations

| Item | Why it matters | Current status |
|---|---|---|
| SP500 history gap | FRED SP500 starts 2016. Intraday/fast-market state for Layer-3 may require SPY via Yahoo instead | ⬜ High priority |

### 3.5 Repo / operator ergonomics

| Item | Why it matters | Current status |
|---|---|---|
| Runtime artifact hygiene | `layer2_truth.db` and `latest_snapshot.json` should remain local runtime artifacts unless intentionally committed | ⬜ Active hygiene concern |
| Gold adapter local JSON path usability | Current workflow may require explicit path handling | ⬜ Non-blocking usability issue |

---

## 4. Accepted Approximations

These are deliberate approximations, not hidden defects.

| Item | Current interpretation |
|---|---|
| `gld_holdings_flow_confirm` | Treated as Tier-2 / flow confirmation signal. Yahoo shares_outstanding applied backward — not a true historized series. Governs: `preferred_action` mildly, never blocks DecisionPacket alone. |
| Monthly macro series staleness | Monthly series can appear old in calendar days without being operationally broken |
| `DTWEXBGS` structural lag sensitivity | This series may appear relatively old in calendar days due to source lag, but remains governed by its own threshold / policy treatment |
| Discontinued legacy USD / PPI series | Retained historically, but must not be over-interpreted as current real-time truth |

---

## 5. Layer-3 Build Dependencies Still Open

These are Layer-2-owned items that Layer-3 will eventually need, but that do not block bootstrap.

| Item | Why Layer-3 needs it | Current status |
|---|---|---|
| Index Suite values in snapshot | Layer-3 UnknownMode evaluation requires Stress, Drift, CorrBreak index values from Layer-2 | ⬜ Future Layer-2 extension — after Index Suite is built |
| SP500 history gap | FRED SP500 starts 2016 only. Intraday / fast-market state may require SPY via Yahoo | ⬜ High priority for Layer-3 live market inputs |

Layer-3 implementation risks (live state leakage, event noise, trigger conflation, calibration) are tracked in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 8, not here. This document tracks Layer-2 gaps only.

---

## 6. What the Current Successful Publish Does Not Prove

A successful non-forced Layer-2 publish proves:

- ingestion is currently functioning
- quality gate is functioning
- snapshot publication is functioning
- the Layer-2 contract boundary is currently operational

It does **not** prove:

- Layer-3 exists
- revision handling is complete
- backtest integrity is fully hardened for all revision-sensitive cases
- operational readiness is complete
- live execution is ready
- Live Market State or Event Risk Stream adapters are built or validated

---

## 7. Summary

Current state:

- Layer-2 operational snapshot boundary: ✅
- Layer-3 bootstrap contract blockers: resolved
- Layer-3 decision philosophy: frozen ✅
- Layer-3 DecisionPacket schema v0: defined ✅
- Layer-3 implementation: not built ⬜
- Live Market State adapters: not built ⬜
- Event Risk Stream: not built ⬜
- Live readiness: not ready ⬜
- Remaining operational work: real, downstream of working Layer-2 publish boundary
