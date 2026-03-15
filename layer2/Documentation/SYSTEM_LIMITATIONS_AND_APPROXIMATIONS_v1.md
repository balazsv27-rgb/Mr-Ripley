# Known Gaps and Approximations
## Mr. Ripley — Layer-2 Truth Layer

> **Last updated:** 2026-03-16
> **Primary sources:** `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
> **Supporting sources:** `SYSTEM_IMPLEMENTATION_RECORD_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`

---

## 1. Why This Document Exists

Layer-2 is now operational as a truth-layer foundation and has successfully executed a non-forced snapshot publication.

It is still **not** a fully hardened or complete system.

This document tracks:

- known limitations
- accepted approximations
- future work
- operational gaps
- remaining Layer-2 hardening items
- items that still block live execution readiness

---

## 2. What Is No Longer a Bootstrap Blocker

The following were previously contract-side blockers for Layer-3 bootstrap and are now implemented:

| Item | Current status | Notes |
|---|---|---|
| `guards` structured object in snapshot JSON | ✅ Implemented | Present in current snapshot outputs |
| `reason_code` enum in shared constants | ✅ Implemented | Shared constants now define enumerated reason codes |
| `layer1_events: []` stub | ✅ Implemented | Forward-compatible snapshot slot |
| `engine_version` in snapshot output | ✅ Implemented | Present in current published snapshot shape |
| `config_version` in snapshot output | ✅ Implemented | Present in current published snapshot shape |
| Operational Layer-2 snapshot publication path | ✅ Implemented | Successful non-forced publish observed |

These items should no longer be described as open Layer-3 bootstrap blockers in the current document set.

---

## 3. Current Real Limitations

These are still real open items.

### 3.1 Revision / vintage limitations

| Item | Why it matters | Current status |
|---|---|---|
| `revision_risk` tracking incomplete | Revised macro series are not yet explicitly marked in downstream interpretation | ⬜ Open |
| Revision writer not built | Historical corrections cannot yet be written as explicit higher revision rows through a dedicated revision path | ⬜ Open |

### 3.2 Operational limitations

| Item | Why it matters | Current status |
|---|---|---|
| No single orchestrator / end-to-end runner | Full daily workflow remains operator-driven | ⬜ Open |
| No scheduler | Daily refresh and publication are manual | ⬜ Open |
| No alerting / notification | Failures require active operator monitoring | ⬜ Open |
| No capped retry logic | Transient source failures remain manual recovery events | ⬜ Open |
| No kill switch | Required before any live execution path | ⬜ Open |

### 3.3 Layer boundary limitations

| Item | Why it matters | Current status |
|---|---|---|
| Layer-3 components not built | Feature / regime / supervisor / DecisionPacket stack does not yet exist | ⬜ Open |
| Live execution not wired | System ends at validated snapshot publication | ⬜ Open |

### 3.4 Repo / operator ergonomics

| Item | Why it matters | Current status |
|---|---|---|
| Runtime artifact hygiene still requires active discipline | `layer2_truth.db` and `latest_snapshot.json` should remain local runtime artifacts unless intentionally committed | ⬜ Active hygiene concern |
| Gold adapter local JSON path usability needs polish | Current workflow may still require explicit path handling depending on local file placement | ⬜ Non-blocking usability issue |

---

## 4. Accepted Approximations

These are deliberate approximations, not hidden defects.

| Item | Current interpretation |
|---|---|
| `gld_holdings_flow_confirm` | Treated as Tier-2 / flow confirmation signal rather than Tier-1 publication blocker |
| Monthly macro series staleness | Monthly series can appear old in calendar days without being operationally broken |
| `DTWEXBGS` structural lag sensitivity | This series may appear relatively old in calendar days due to source lag, but remains governed by its own threshold / policy treatment |
| Discontinued legacy USD / PPI series | Retained historically, but must not be over-interpreted as current real-time truth |

---

## 5. What the Current Successful Publish Does Not Prove

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

---

## 6. Summary

Current state:

- Layer-2 operational snapshot boundary: ✅
- Layer-3 bootstrap contract blockers: resolved
- Layer-3 implementation: not built
- live readiness: not ready
- remaining work: real but downstream of the now-working Layer-2 publish boundary
