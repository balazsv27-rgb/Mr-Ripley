# Gold Decision Engine — Architecture v4

> This document distinguishes between **target architecture** and **current implementation path**.
> `README_LAYER2.md` is historical context only and not the current canonical source.

---

## 1. Final conclusion

We are not building a “Zapier + ChatGPT trading bot.”

We are building a **gold-first, regime-aware, supervisor-governed decision engine** that:

- emits deterministic DecisionPackets only
- forbids free text at the execution boundary
- is version-locked and replayable
- is fail-closed under data or operational faults
- is validated through paper-mode and harness-first discipline
- keeps execution optional and unwired until activation criteria are met

If an LLM is used at all, it is analyst / auditor only, not the decision brain.

---

## 2. Core philosophy

The system optimizes for:

- survival before aggressiveness
- auditability before cleverness
- replayability before automation
- calibration before confidence theater
- contract stability before infrastructure polish

This means:

- Layer-2 closes first as a stable snapshot boundary
- Layer-3 starts as a deliberately simple bootstrap
- Layer-2 hardening continues in parallel after Layer-3 starts
- live execution remains a separate later gate

---

## 3. Layer framing

### Core engine

- **Layer 2 — Truth Layer**  
  Market + macro data, versioned, point-in-time disciplined, consumed through snapshot contract

- **Layer 3 — Decision Layer**  
  Feature processing, indices, regime logic, supervisor governance, deterministic DecisionPacket

### Optional add-on

- **Layer 1 — Event Tagger / Narrative Risk Modifiers**  
  Penalty-only, non-trading, never allowed to generate direction

---

## 4. Layer 2 — Truth Layer

### Purpose

Maintain authoritative numerical history and current state for gold and its macro drivers.

### Mandatory discipline

- vintage / as-of awareness
- registry discipline
- fail-closed publication
- version-locked snapshot boundary
- point-in-time replayability

### Current Layer-2 status

Current Layer-2 components are operational:

- ingestion adapters
- canonical clock
- alignment
- quality gate
- snapshot publisher

A successful **non-forced snapshot publication** has been executed with a valid `snapshot_id`, DB write, and `latest_snapshot.json` handoff file.

This means the contract-side Layer-2 boundary is now operational.

---

## 5. Layer-2 → Layer-3 Contract Handoff Gate

### Required handoff items

- snapshot contract stable
- `engine_version` and `config_version` reliably present in snapshot outputs
- `guards` structured object exists in snapshot JSON
- `reason_code` enum is defined
- current v1 docs reflect the current contract behavior

### Current handoff status

**Current status: satisfied at the contract boundary.**

Evidence reflected by the current v1 documents:

- successful non-forced snapshot publication observed
- `latest_snapshot.json` generated successfully
- snapshot written to DB
- quality gate passed at the observed publish boundary
- required contract fields present in the current published snapshot shape

### Important distinction

Passing the handoff gate means:

- Layer-3 bootstrap may begin

It does **not** mean:

- Layer-3 exists already
- Layer-2 is fully hardened
- revision handling is complete
- operational readiness is complete
- live execution is allowed

---

## 6. Current build sequence

### Phase A — Layer-2 closure for bootstrap

This phase is now complete **at the contract boundary level**.

Meaning:
- snapshot publisher operational
- quality gate operational
- stable contract fields present
- successful real publication observed

This does not imply all Layer-2 hardening work is finished.

### Phase B — Layer-3 bootstrap (intentionally simple)

Build in this order:

1. snapshot consumer
2. feature builder stub
3. 2–3 deterministic calculations
4. DecisionPacket skeleton
5. `NO_TRADE` / `NOTHING` default path only

Example early deterministic calculations:

- real-yield spread
- inflation-expectation spread
- stress placeholder

### Phase C — Layer-3 structured buildout

Only after bootstrap works:

1. Feature Builder stabilization
2. Index Suite
3. Regime Gate
4. Supervisor Engine
5. Decision Engine hardening
6. harness-based paper validation
7. calibration / threshold freezing

### Phase D — Live execution gate

Only after:

- paper validation is complete
- calibration criteria are met
- DecisionPacket schema is frozen
- operational readiness is complete
- kill switch is tested fail-closed

---

## 7. Layer 3 — Decision Layer

### Current status

Layer-3 is **not yet built**.

The following remain future work:

- Feature Builder
- Index Suite
- Regime Gate
- Supervisor Engine
- Decision Engine / DecisionPacket generator

### Bootstrap rule

Layer-3 must consume **published snapshot interfaces only**, never raw `observations`.

---

## 8. Live Execution Boundary

Live execution is a separate later gate.

Current Layer-2 success must not be misread as live readiness.

Live execution remains blocked until:

- Layer-3 exists
- paper validation is complete
- calibration is complete
- operational readiness exists
- kill switch testing exists

---

## 9. Interpretation Rule

This architecture document defines the sequencing boundary and target design.

For current Layer-2 status, interpret together with:

- `README_v1.md`
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
