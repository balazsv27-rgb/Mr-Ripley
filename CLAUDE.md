# CLAUDE.md — Project Constitution

This document defines the **constitutional rules** of the Mr. Ripley gold first engine.
This document defines obligations.
It does not execute or enforce them.
Execution is delegated to orchestration systems.
Enforcement is delegated to runtime mechanisms.

It governs:
- how the system is interpreted
- what counts as truth and proof
- how components relate to each other
- what is allowed vs forbidden to claim
- how changes must be validated

This file is **not a workflow** and **not an implementation guide**.  
It is the **highest-priority interpretative authority** for Claude.

---

# 1. SYSTEM IDENTITY

The Mr. Ripley gold first engine is a:

> **Gold-first, fail-closed, snapshot-based decision support system**

Core properties:

- deterministic data ingestion (Layer 2)
- immutable snapshot boundary
- no direct raw-data consumption downstream
- LLM = **analysis + audit only**, never execution
- execution remains **blocked by design**

---

# 2. DOCUMENT AUTHORITY (TRUTH HIERARCHY)

## 2.1 Canonical Current-State Sources

The following define **current system truth**:

1. `README_v1.md`
2. `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
3. `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
4. `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
5. `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
6. `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
7. `README_LAYER2.md`

These together form the **canonical current-state documentation set**.

## 2.2 Canonical Role Definitions

Canonical documents are **authoritative by role**, not interchangeable by convenience.

- `README_v1.md`  
  Top-level project orientation and entry point.

- `SYSTEM_TECHNICAL_HANDBOOK_v1.md`  
  Technical implementation constraints, engineering discipline, contract behavior, and expected operating rules.

- `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`  
  Known limitations, approximations, explicit non-goals, and constraint boundaries.

- `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`  
  Primary architectural source of truth for structure, boundaries, sequencing, and stage intent.

- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`  
  Cross-document consistency map and verification reference.

- `SYSTEM_IMPLEMENTATION_RECORD_v1.md`  
  Canonical record of what is actually implemented and realized.

- `README_LAYER2.md`  
  Canonical collaborator guide and living build reference for Layer-2 implementation and operational navigation.

## 2.3 Historical Sources

Historical or superseded materials MAY exist outside the canonical set.

Rule:

> Historical documents that are outside the canonical set MUST NOT be used as current truth sources.

## 2.4 Conflict Resolution

If any document conflicts:

> **Role-matched canonical interpretation overrides convenience-based interpretation.**

Resolution order:

1. identify the claim type,
2. choose the canonical document whose declared role most directly matches that claim,
3. cite the conflict explicitly,
4. treat unresolved contradiction as documentation inconsistency,
5. do not invent reconciliation.

Examples:
- architecture / boundary questions → prefer `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
- implementation-state claims → prefer `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
- limitations / approximations → prefer `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
- collaborator workflow / Layer-2 navigation → prefer `README_LAYER2.md`

Critical rule:

> `README_LAYER2.md` is canonical, but it MUST NOT be used to overrule more role-specific canonical documents on implementation state, architecture boundaries, or limitations.

---

# 3. CURRENT vs TARGET ARCHITECTURE

The system is explicitly **multi-stage**.

## 3.1 Current State

- Layer 2 = **operational at snapshot boundary**
- Snapshots = published, immutable, contract-compliant
- No downstream computation layer exists yet

## 3.2 Target Architecture (NOT YET BUILT)

The following are **planned only**:

- Feature Builder
- Index Suite
- Regime Gate
- Supervisor Engine
- Decision Engine
- DecisionPacket
- Execution Layer

Rule:

> Planned components MUST NOT be described as existing implementation.

---

# 4. STAGE-GATE MODEL

The system evolves through strict phases:

## Phase A — Layer 2 Closure
- Status: **complete at contract boundary**

## Phase B — Layer 3 Bootstrap
- Status: **allowed, not completed**

## Phase C — Layer 3 Structured Buildout
- Status: **future**

## Phase D — Live Execution Gate
- Status: **blocked**

---

## Critical Rule

> “Handoff gate satisfied” ≠ Layer 3 exists  
> “Layer 3 exists” ≠ Live execution allowed  

---

# 5. EVIDENCE AND PROOF MODEL

All claims must be classified.

## 5.1 Allowed Evidence Classes

- **Verified in canonical current-state documentation set**
- **Documented current-state claim**
- **Planned / target architecture**
- **Not verifiable from current materials**

## 5.2 What Counts as Proof

Valid proof must be:

- traceable to canonical documents OR
- supported by concrete code-level implementation

## 5.3 What Does NOT Count as Proof

- inferred behavior
- implied architecture
- planned components
- partial documentation
- non-canonical historical statements
- LLM reasoning alone

---

## Critical Rule

> Documentation validation ≠ external certification  
> Documentation validation ≠ production readiness  

---

# 6. SNAPSHOT CONTRACT (NON-NEGOTIABLE)

## 6.1 Downstream Rule

Layer 3+ MUST:

- read ONLY from published snapshots
- NEVER read raw observations

## 6.2 Snapshot Requirements

Each snapshot MUST have:

- identity (`snapshot_id`)
- time anchor (`as_of`)
- revision metadata
- deterministic contents

## 6.3 Forbidden Patterns

- reading `latest`
- reading raw observations downstream
- bypassing snapshot boundary

---

# 7. FAIL-CLOSED PRINCIPLE

The system MUST default to:

> **NO OUTPUT rather than incorrect output**

Applied to:

- missing data
- invalid states
- broken invariants
- unverified assumptions

---

# 8. REGISTRY AS SINGLE SOURCE OF TRUTH

All series definitions MUST come from:

- `series_registry.json`

Rules:

- no hardcoded series logic
- no implicit data interpretation
- no hidden mappings

---

# 9. EXECUTION BOUNDARY

The system is:

> **analysis-only**

NOT allowed:

- automated trading
- signal execution
- decision triggering
- order generation

---

## Critical Rule

> No component may simulate or imply execution capability.

---

# 10. STRONG CLAIM DISCIPLINE

The following claims are **FORBIDDEN unless explicitly proven**:

- “Layer 3 is implemented”
- “System is production-ready”
- “Execution is available”
- “Decisions are automated”
- “System is externally validated”

---

## Allowed Language

- “planned”
- “target architecture”
- “not yet implemented”
- “requires Phase C/D”

---

# 11. DOCUMENT UPDATE OBLIGATIONS

Any **contract-affecting change** MUST trigger:

- `README_v1.md` review
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md` review
- `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` update
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` update
- `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` review
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md` review when implementation state changes
- `README_LAYER2.md` review when collaborator workflow or Layer-2 build navigation changes

---

## Critical Rule

> Code changes without documentation alignment are invalid.

---

# 12. VERSION LOCK AND IMMUTABILITY

- snapshots are immutable
- contracts are versioned
- behavior must be reproducible

---

# 13. LLM ROLE CONSTRAINT

Claude is:
- analyst
- validator
- auditor

Claude is NOT:
- decision engine
- execution engine
- source of truth

---

# 14. INTERPRETATION PRIORITIES

When answering or reasoning:
1. use canonical documents
2. classify the claim by role and evidence type
3. prefer the role-matched canonical source
4. respect phase-gates
5. enforce snapshot contract
6. avoid implicit assumptions
7. block strong claims when evidence is incomplete or contradictory

---

# 15. WORKFLOW GOVERNANCE CONSTRAINT

All governed actions (interpretation, modification, validation, audit, documentation updates) MUST be subject to orchestration-based workflow enforcement.

The workflow definition in `.claude/workflows/system-orchestration.yaml` is the authoritative execution specification.

However:
- this document does NOT execute workflows
- enforcement MUST be implemented via orchestration mechanisms (hooks, runners, validators)

Any action that bypasses enforced workflow execution is considered invalid and non-compliant.

---

# 16. FINAL CONSTITUTIONAL RULE

> If a statement cannot be traced to a canonical source  
> AND cannot be proven from implementation  
> THEN it MUST be treated as unverified and non-binding.

---

# SUMMARY

This system is:
- **deterministic**
- **fail-closed**
- **snapshot-driven**
- **phase-gated**
- **documentation-governed**

And most importantly:

> **Truth is constrained. Claims are earned. Execution is forbidden until proven safe.**
