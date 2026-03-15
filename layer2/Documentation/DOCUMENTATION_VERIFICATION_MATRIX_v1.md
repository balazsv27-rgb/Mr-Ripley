# Documentation Verification Matrix v1

## 1. Purpose

This document classifies what the current v1 documentation set supports as current truth, what remains future architecture, and what still cannot be treated as independently verified implementation fact.

It is a **classification layer**, not a substitute for code review.

Canonical document set:

- `README_v1.md`
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
- `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md`

`README_LAYER2.md` is historical only.

---

## 2. Classification Rules

| Classification | Meaning |
|---|---|
| **Verified in current documentation set** | Current v1 documents make a direct, stable claim and no material conflict remains within the current document set |
| **Documented current-state claim** | Current docs describe the item as current-state, but the claim still depends on project-owned evidence rather than independent certification |
| **Planned / target architecture** | Future or downstream design; not current Layer-2 implementation |
| **Cannot verify from current materials** | Current docs do not support a stronger statement without invention |

Important distinction:
- “Verified in current documentation set” is **not** the same as independent external certification.
- This matrix classifies the current docs; it does not replace direct code inspection.

---

## 3. Current Layer-2 Contract Items

| Item | Classification | Notes |
|---|---|---|
| Registry-driven ingestion | Verified in current documentation set | Described consistently across README, handbook, and architecture docs |
| Canonical clock module exists | Verified in current documentation set | `layer2/clock.py` is part of the documented current stack |
| Point-in-time alignment discipline | Documented current-state claim | Current docs describe governed `obs_ts <= clock_date` and `as_of_ts <= clock_ts` alignment |
| Quality gate blocks Tier-1 failures | Verified in current documentation set | Current docs consistently describe fail-closed publication |
| `engine_version` in snapshot output | Verified in current documentation set | Current docs now consistently treat this as implemented |
| `config_version` in snapshot output | Verified in current documentation set | Current docs now consistently treat this as implemented |
| `guards` object in snapshot JSON | Verified in current documentation set | Current docs now consistently treat this as implemented |
| `reason_code` enum in shared constants | Verified in current documentation set | Current docs now consistently treat this as implemented |
| `layer1_events: []` stub in snapshot JSON | Verified in current documentation set | Treated as implemented forward-compatible slot |
| Deterministic snapshot publication path | Documented current-state claim | Current docs describe this as operational, based on project-owned evidence |
| Successful non-forced snapshot publication | Verified in current documentation set | Current docs now consistently describe one successful non-forced publication event |
| `latest_snapshot.json` handoff file generated successfully | Verified in current documentation set | Current docs now consistently describe this as observed fact |
| Layer-2 → Layer-3 snapshot handoff gate satisfied | Verified in current documentation set | Current docs now consistently describe contract-side gate as satisfied |

---

## 4. Current Known Open Items

| Item | Classification | Notes |
|---|---|---|
| `revision_risk` tracking | Documented current-state claim | Current docs consistently say this remains incomplete |
| Revision writer | Documented current-state claim | Current docs consistently say it is not yet built |
| Scheduler / orchestrator | Documented current-state claim | Current docs consistently say it is not yet built |
| Alerting / retry / kill switch | Documented current-state claim | Current docs consistently say these are not yet built |
| Repo hygiene for runtime artifacts | Documented current-state claim | Current docs treat this as an open verification / hygiene concern |
| Adapter usability polish (e.g. gold JSON path handling) | Documented current-state claim | Current docs treat this as non-blocking operational polish |
| Layer-3 implementation | Verified in current documentation set | Current docs consistently say Layer-3 is not yet built |

---

## 5. Future / Target Architecture Items

| Item | Classification | Notes |
|---|---|---|
| Feature Builder | Planned / target architecture | Layer-3 component, not current Layer-2 implementation |
| Index Suite | Planned / target architecture | Layer-3 component |
| Regime Gate | Planned / target architecture | Layer-3 component |
| Supervisor Engine | Planned / target architecture | Layer-3 component |
| DecisionPacket generation | Planned / target architecture | Layer-3 component |
| Live execution wiring | Planned / target architecture | Later gate only |

---

## 6. Publication Event Classification

The current v1 documentation set supports the following statement:

> A successful non-forced Layer-2 snapshot publication has been executed, producing both a DB snapshot record and `latest_snapshot.json`, with Tier-1 passing 15/15 at the publish boundary.

This is now treated as **Verified in current documentation set** because the current v1 documents have been normalized to the same status statement.

This is still **not** independent external certification.

---

## 7. Interpretation Rule

If any older retained document contradicts the current v1 set, prefer the current v1 set.

`README_LAYER2.md` must not be used as a current-state source.
