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
- `README_LAYER2.md`

These seven documents together form the canonical current-state set.

They are authoritative by role, not interchangeable by convenience.

---

## 2. Classification Rules

| Classification | Meaning |
|---|---|
| **Verified in current documentation set** | Current v1 documents make a direct, stable claim and no material conflict remains within the current document set |
| **Documented current-state claim** | Current docs describe the item as current-state, but the claim still depends on project-owned evidence rather than independent certification |
| **Planned / target architecture** | Future or downstream design; not current Layer-2 implementation |
| **Cannot verify from current materials** | Current docs do not support a stronger statement without invention |

Important distinction:
- "Verified in current documentation set" is **not** the same as independent external certification.
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
| Successful non-forced snapshot publication | Verified in current documentation set | Current docs consistently describe one successful non-forced publication event |
| `latest_snapshot.json` handoff file generated successfully | Verified in current documentation set | Current docs consistently describe this as observed fact |
| Layer-2 → Layer-3 snapshot handoff gate satisfied | Verified in current documentation set | Current docs consistently describe contract-side gate as satisfied |

---

## 4. Current Known Open Items

| Item | Classification | Notes |
|---|---|---|
| `revision_risk` flag in snapshot JSON | Verified in current documentation set | `revision_risk` bool added to registry, alignment payload, and snapshot JSON. Monthly macro series (CPILFESL, PCEPI, FEDFUNDS, PCU2122212122210) are `true`; daily market/yield series are `false`. Flag is interpretive metadata — does not block publication. Implemented 2026-05-01. |
| Revision writer | Documented current-state claim | Current docs consistently say it is not yet built (`revision_seq=1` write path absent) |
| Scheduler / orchestrator | Documented current-state claim | Current docs consistently say it is not yet built |
| Alerting / retry / kill switch | Documented current-state claim | Current docs consistently say these are not yet built |
| Repo hygiene for runtime artifacts | Documented current-state claim | Current docs treat this as an open verification / hygiene concern |
| Adapter usability polish (e.g. gold JSON path handling) | Documented current-state claim | Current docs treat this as non-blocking operational polish |
| Layer-3 implementation | Verified in current documentation set | Current docs consistently say Layer-3 is not yet built |
| SP500 history gap | Documented current-state claim | FRED SP500 from 2016 only — SPY migration planned, relevant for future Layer-3 live market inputs |
| Live Market State adapters | Verified in current documentation set | Not built — required for Layer-3 fast trigger detection |
| Event Risk Stream integration | Verified in current documentation set | Not built — required for Layer-3 uncertainty escalation and action restriction |

---

## 5. Future / Target Architecture Items

| Item | Classification | Notes |
|---|---|---|
| Layer-3 decision model | Planned / target architecture | State-driven / event-driven model. Three inputs: Snapshot Truth, Live Market State, Event Risk Stream. Frozen 2026-03-22. Full design in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7. |
| DecisionPacket v0 schema | Planned / target architecture | Governed action contract. Schema frozen 2026-03-22. Full field reference in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7. |
| Feature Builder | Planned / target architecture | Layer-3 component, not current Layer-2 implementation |
| `layer2/index_suite.py` (Layer-2 provisional tool) | Verified in canonical current-state documentation set | Layer-2 internal pre-publication computation tool. Reads observations with point-in-time alignment. Distinct from the planned Layer-3 Index Suite. |
| Index Suite (Layer-3) | Planned / target architecture | Layer-3 component — will consume published snapshots, not raw observations |
| Regime Gate | Planned / target architecture | Layer-3 component |
| Supervisor Engine | Planned / target architecture | Layer-3 component |
| DecisionPacket generation | Planned / target architecture | Layer-3 component — v0 schema defined, implementation not yet started |
| Live Market State adapters | Planned / target architecture | Layer-3 component — fast-changing input layer |
| Event Risk Stream | Planned / target architecture | Layer-3 component — penalty / override / uncertainty escalation only |
| Live execution wiring | Planned / target architecture | Later gate only |

---

## 6. Publication Event Classification

The current v1 documentation set supports the following statement:

> A successful non-forced Layer-2 snapshot publication has been executed, producing both a DB snapshot record and `latest_snapshot.json`, with Tier-1 passing 15/15 at the publish boundary.

This is now treated as **Verified in current documentation set** because the current v1 documents have been normalized to the same status statement.

This is still **not** independent external certification.

---

## 7. Layer-3 Philosophy and Schema Classification (added 2026-03-22)

The current v1 documentation set supports the following statements:

> The Layer-3 decision philosophy has been frozen: the engine is state-driven / event-driven, deciding because state changed — not because time passed.

> The Layer-3 DecisionPacket v0 schema has been defined: a governed action contract carrying snapshot_id, guard fields, reason codes, allowed actions, preferred action, confidence, uncertainty, cooldown, and invalidation semantics.

Both are classified as **Planned / target architecture** — the philosophy and schema are defined and frozen, but Layer-3 is not yet implemented.

The previous implicit timeframe-centered DecisionPacket framing (`action: "BUY | SELL | NOTHING"`, `timeframe: "5m"`) is superseded. Any document still containing the old framing should be treated as historical.

---

## 8. Document Role Classification

This table records the canonical role of each document to prevent role-mixing and documentation fog.

| Document | Role | Contains |
|---|---|---|
| `README_v1.md` | Entry point summary | Current status, component list, run sequence, short-form known risks |
| `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Current engineering reference (Layer-2) | Layer-2 stack, snapshot contract, quality gate semantics, handoff gate |
| `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Current Layer-2 gaps and open items | Known limitations, accepted approximations, Layer-2-owned open items only |
| `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Target architecture + build sequence + design risks | Layer framing, build phases, Layer-3 model, implementation risks |
| `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Canonical implementation record + realized-state reference | Build history, realized state, audit trail, schema diffs, philosophy change record |
| `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Classification layer | What is verified, what is claimed, what is planned, document role map |
| `README_LAYER2.md` | Collaborator guide + living build reference | Layer-2 build detail, adapter usage, DB state, run sequence, resolved/open items — updated alongside the v1 set |

---

## 9. Interpretation Rule

If any document contradicts the current canonical set, the conflict must be resolved — not silently preferred away. All seven documents must remain consistent with each other.

For Layer-3 design decisions and DecisionPacket field reference, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7 is the canonical source.
