# Gold Decision Engine — Architecture v4

> Revised to align with `README_LAYER2_v9.md` roadmap and handoff logic.
> This document distinguishes between **target architecture** and **current implementation path**.

---

## 1. Final conclusion

We are not building a “Zapier + ChatGPT trading bot.”

We are building a **gold-first, regime-aware, supervisor-governed decision engine** that:

- emits **deterministic DecisionPackets** only
- forbids **free text at the execution boundary**
- is **version-locked and replayable**
- is **fail-closed under data or operational faults**
- is validated through **paper-mode and harness-first discipline**
- keeps **execution optional and unwired** until activation criteria are met

If an LLM is used at all, it is **analyst / auditor only**, not the decision brain.
The decision brain is a structured state machine with governed policy.

---

## 2. Core philosophy

The system is designed to optimize for:

- survival before aggressiveness
- auditability before cleverness
- replayability before automation
- calibration before confidence theater
- contract stability before infrastructure polish

This means:

- Layer-2 is closed for Layer-3 **once the snapshot contract is stable enough to be consumed as an API**
- Layer-3 starts with a **deliberately simple bootstrap phase**
- Layer-2 data hardening and operational hardening continue **in parallel** after Layer-3 starts
- live execution remains a **separate later gate**

---

## 3. Layer framing

### Core engine (mandatory)

- **Layer 2 — Truth Layer**  
  Market + macro data, versioned, point-in-time disciplined, consumed through snapshot contract

- **Layer 3 — Decision Layer**  
  Feature processing, indices, regime logic, supervisor governance, deterministic DecisionPacket

### Optional add-on (disabled by default)

- **Layer 1 — Event Tagger / Narrative Risk Modifiers**  
  Penalty-only, non-trading, never allowed to generate direction

---

## 4. Optional Layer 1 — Event Tagger / Narrative Risk Modifiers

### Purpose

Convert narrative signals into structured events relevant to gold for research and risk penalties only.

### Allowed effects (penalty-only)

- raise uncertainty
- trigger cooldown
- add research tags / evidence references
- apply veto penalties

### Prohibited effects

- cannot generate BUY / SELL
- cannot flip direction
- cannot override Layer-2 / Layer-3 decisions
- cannot alter execution-boundary logic

### Output contract

`Event` objects only — structured, auditable, immutable evidence references.

### Current implementation note

Layer 1 is **optional and disabled by default**.  
`layer1_events: []` may exist as a forward-compatible placeholder in Layer-2 snapshot output, but it is **not required** for Layer-3 bootstrap.

---

## 5. Layer 2 — Truth Layer

### Purpose

Maintain authoritative numerical history and current state for gold and its macro drivers.

### Typical inputs

- **Market:** XAUUSD / GC / GLD proxies, OHLCV, volatility proxies
- **Macro:** real-yield proxies, nominal yields, USD proxies, inflation expectation proxies, stress proxies

### Mandatory discipline

#### 5.1 Vintage / as-of awareness

Macro data may be revised.
Backtests and replays must use point-in-time correct values.

If vintage handling is unavailable for a series:
- mark revision risk where applicable
- penalize confidence / raise uncertainty downstream

#### 5.2 Registry discipline

Registry/config remains the single source of truth for Layer-2 data contract and processing configuration.

#### 5.3 Fail-closed contract discipline

If Tier-1 completeness or contract invariants fail, Layer-2 must fail closed rather than publish an apparently valid but unsafe snapshot.

### Core Layer-2 components

- ingestion pipeline (backfill + incremental)
- versioned time-series store (`observations`)
- quality gate
- snapshot publisher
- freshness tracking
- snapshot interface supporting point-in-time reconstruction

### Current Layer-2 closure definition

Layer-2 is considered **finished for Layer-3 bootstrap** when it is a:

> **registry-driven, fail-closed, version-locked snapshot system that Layer-3 can consume as a stable API**

This is a handoff definition, not a claim that all Layer-2 polishing is complete.

---

## 6. Layer-2 → Layer-3 Contract Handoff Gate

This is the **current implementation gate** that unlocks Layer-3 core build.

### Required handoff items

- snapshot contract is stable
- `engine_version` and `config_version` are reliably present in snapshot outputs
- `guards` structured object exists in snapshot JSON
- `reason_code` enum is defined
- README and code are in sync on contract behavior

### Recommended but not mandatory for bootstrap start

- simple orchestrator / end-to-end runner
- `layer1_events: []` stub for forward-compatible interface stability
- basic scheduler

### Explicit non-blockers for Layer-3 bootstrap

The following remain important but do **not** block Layer-3 bootstrap:

- full revision system / revision writer
- `revision_risk` completion across all paths
- SP500 historical gap closure
- extended gold history toward 2005
- alerting / retry / full notification stack
- kill switch testing for live use
- broader operational hardening

### Important distinction

Passing the contract handoff gate means:
- Layer-3 may begin

It does **not** mean:
- Layer-2 is perfect
- calibration is complete
- paper validation is complete
- live execution is allowed

---

## 7. Current build sequence vs target architecture

This document deliberately separates:

- **Target architecture** — where the engine is meant to end up
- **Current build sequence** — how the project should get there without stalling inside Layer-2 forever

### 7.1 Current build sequence (implementation path)

#### Phase A — Layer-2 closure for bootstrap

Close the contract handoff gate.
Do not wait for every Layer-2 hardening item.

#### Phase B — Layer-3 Bootstrap (intentionally simple)

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

#### Phase C — Layer-3 structured buildout

Only after bootstrap works:

1. Feature Builder stabilization
2. Index Suite
3. Regime Gate
4. Supervisor Engine
5. Decision Engine hardening
6. harness-based paper validation
7. calibration / threshold freezing

#### Phase D — Live execution gate

Only after:

- paper validation is complete
- calibration criteria are met
- DecisionPacket schema is frozen
- operational readiness is complete
- kill switch is tested fail-closed

### 7.2 Target architecture (steady-state)

The mature system consists of:

- Layer 2 truth infrastructure
- Layer 3 feature, regime, supervisor, decision stack
- optional Layer 1 penalty-only event layer
- optional Layer 4 execution orchestration, connected only after readiness gates are satisfied

---

## 8. Layer 3 — Decision Layer

### Purpose

Map current state to governed actions through a deterministic policy stack.

### Inputs

- `MarketState(t)` / `MacroState(t)` / feature vector from Layer 2 snapshot-derived data
- optional Layer-1 event stream (penalty-only)

### Design rule

Layer-3 must consume **snapshot-derived interfaces**, not raw `observations` directly.

---

## 9. Layer-3 Phase 1 Bootstrap

This is the **first implementation phase**, not the final target state.

### Goals

- prove contract usability
- prove snapshot replayability
- stand up deterministic output plumbing
- avoid premature regime complexity

### Rules for Phase 1

- consume snapshot only
- deterministic features only
- no full regime math yet
- no directional execution
- DecisionPacket may emit `NOTHING` / `NO_TRADE` only

### Bootstrap DecisionPacket example

```json
{
  "ts": "ISO-8601",
  "engine_version": "gold-v4-bootstrap",
  "config_version": "<registry_version>",
  "action": "NOTHING",
  "confidence": 0.0,
  "uncertainty": 1.0,
  "reason_code": "NO_SIGNAL",
  "guards": {
    "data_ok": false,
    "risk_ok": false,
    "cooldown_ok": false,
    "idempotent_ok": false,
    "supervisor_veto": true
  }
}
```

### Phase-1 non-goals

- full regime engine
- full mathematical calibration
- full supervisor policy set
- live execution connection
- over-optimized signal logic

---

## 10. Layer-3 Target Architecture

### 10.1 Analog Memory Engine (optional module)

Produces `ScenarioResult` objects: probabilities, bands, tails, analogs.
Analytical only; never executes directly.

### 10.2 Feature Builder

Responsibilities:

- compute standardized multi-horizon features
- validate `engine_version` and `config_version` before consumption
- support point-in-time reconstruction
- rely on snapshot contract, not ad hoc raw reads

### 10.3 Index Suite

Indices are advisory until frozen through calibration:

- `StressIndex` (0–100)
- `DriftIndex` (0–100)
- `CorrBreakIndex` (0–100)
- `DataFreshnessPenalty` (0–100)

If indices are null or unfrozen:
- supervisor must degrade confidence
- supervisor must increase uncertainty or force conservative behavior

### 10.4 Regime Gate

Regime effects are conditional.
Static rules like “real yields × -1 always means bullish gold” are forbidden.

#### UnknownMode (formal behavior)

Activate when:

- regime confidence is below threshold, or
- regime signals conflict materially, or
- required index inputs are unavailable / unfrozen in a binding phase

In `UnknownMode`:

- confidence floored to 0
- uncertainty forced to or above `U_max`
- cooldown increments
- directional execution prohibited
- alerting may be raised by operational layer

### 10.5 Supervisor Engine

#### Hard veto (non-negotiable)

- `data_ok == false` → `NO TRADE`
- `idempotent_ok == false` → `NO TRADE`
- `UnknownMode active` → `NO TRADE`
- `uncertainty > U_max` → `NO TRADE`

#### Soft constraints

- stress / drift / corrbreak high → shrink position
- disagreement high → shrink or pause

### 10.6 Decision boundary (deterministic execution contract)

Execution systems may read only the deterministic `DecisionPacket`.
No free text is permitted.

#### Signal intent vs execution permissibility

Layer-3 defines **intent** through the deterministic `DecisionPacket`.

Execution policy is separate from signal generation and determines whether that intent is:

- `ALLOWED`
- `REDUCED_ONLY`
- `PAPER_ONLY`
- `BLOCKED`

for the current session / liquidity / operational state.

Execution policy may also constrain sizing or routing, but it must **not**:

- invent direction
- override `reason_code` semantics
- change Layer-3 signal meaning
- create new BUY / SELL intent

#### Target DecisionPacket example

```json
{
  "ts": "ISO-8601",
  "engine_version": "gold-v3.3.0",
  "config_version": "cfg-YYYYMMDD",
  "symbol": "XAUUSD",
  "timeframe": "5m",
  "action": "BUY | SELL | NOTHING",
  "qty": 0.0,
  "confidence": 0.0,
  "uncertainty": 0.0,
  "regime": {
    "base": "NORMAL | STRESS | REGIMESHIFT",
    "unknown_mode": false
  },
  "guards": {
    "data_ok": true,
    "risk_ok": true,
    "cooldown_ok": true,
    "idempotent_ok": true,
    "supervisor_veto": false
  },
  "reason_code": "ENUM_ONLY"
}
```

### Required rules

- no free text
- `reason_code` must be enumerated
- `engine_version` and `config_version` required for replayability
- gate logic must be version-locked to `engine_version`

---

## 11. Validation harness (mandatory)

We validate through a strict orchestration pipeline:

> Trigger → Fetch/Transform → Call Engine → Schema Validate → Gate → Route → Paper Execute → Immutable Log → Post-Session Analysis

The orchestrator is plumbing only:
- routes deterministic fields
- interprets no free text
- invents no trading logic

### Strict gate

Execution is allowed only if:

- `guards.data_ok == true`
- `guards.idempotent_ok == true`
- `guards.cooldown_ok == true`
- `guards.supervisor_veto == false`
- `confidence >= C_min`
- `uncertainty <= U_max`
- risk caps satisfied

This strict gate validates the deterministic decision boundary.
It does **not** by itself define session-aware execution eligibility for live routing.

---

## 12. Threshold governance and calibration

### Threshold governance

- `C_min` / `U_max` are configurable and versioned
- no runtime override permitted during active sessions
- thresholds are frozen only after calibration criteria are met

### Calibration protocol

Freeze thresholds only after:

- at least 100–300 decision ticks
- at least 30–100 executed paper trades, or statistically adequate sample
- monotonic calibration holds  
  (higher confidence → better outcomes; higher uncertainty → worse dispersion)

### Required metrics

- reliability curve + Brier score
- drawdown + CVaR
- regime breakdown
- calibration error

PnL alone is insufficient.

---

## 13. Layer 4 — Execution orchestration (optional, intentionally unwired)

### Purpose

Execute orders strictly from the deterministic DecisionPacket.

### Typical components

- trigger
- router
- broker adapter (paper first)
- logger (immutable)
- guardrail validator (schema + sanity)
- kill switch (fail-closed)

### Important framing

This layer is **not** required to start Layer-3 bootstrap.
It becomes required only for live execution readiness.

### 13.1 Session-Aware Execution Policy

Session-aware execution policy belongs to **live execution readiness** and **execution orchestration hardening**, not to the minimum Layer-3 bootstrap gate.

Its purpose is to determine execution permissibility, sizing constraints, and routing for the current session / liquidity / operational state, while preserving the intent defined by Layer-3.

#### Initial execution session states (policy-level definitions)

- `PRIMARY_LIQUID`
- `THIN_LIQUIDITY`
- `ROLLOVER_WINDOW`
- `EVENT_LOCKOUT`
- `LIVE_DISABLED`

#### Initial execution eligibility outcomes (policy-level definitions)

- `ALLOWED`
- `REDUCED_ONLY`
- `PAPER_ONLY`
- `BLOCKED`

#### v1 policy behavior examples

- `PRIMARY_LIQUID`  
  Standard execution allowed if normal guards and thresholds pass.

- `THIN_LIQUIDITY`  
  Reduced size only, stricter confidence tolerance, avoid aggressive entries.

- `ROLLOVER_WINDOW`  
  No new positions; allow hold / reduce / exit behavior only.

- `EVENT_LOCKOUT`  
  No live execution around configured macro or event windows; paper logging may continue.

- `LIVE_DISABLED`  
  All output routes to paper only; no broker calls permitted.

#### Boundary rules

Session-aware execution policy must:

- consume deterministic signal intent only
- remain downstream from the `DecisionPacket`
- preserve no-free-text execution discipline

It must **not**:

- invent direction
- override `reason_code`
- change Layer-3 signal semantics
- become a bootstrap blocker for Layer-3

#### Implementation note

Session state may be derived by the execution layer at runtime, or later carried as explicit execution metadata.

No new schema field is mandatory for bootstrap solely because this policy exists.

### Failure policy

On unrecoverable failures:
- kill switch engaged
- default `NOTHING`
- alert within target SLA
- retries capped and idempotent

---

## 14. Parallel work after Layer-3 starts

Once the Layer-2 contract handoff gate is passed, Layer-2 continues in parallel in two tracks.
Neither track blocks Layer-3 core build.

### 14.1 Layer-2 Data Integrity

- SP500 history gap closure
- `revision_risk`
- revision writer
- discontinued USD cleanup
- longer historical coverage

These improve calibration quality and replay realism.

### 14.2 Layer-2 Operational Readiness

- scheduler
- alerting / notification
- retry with cap
- kill switch hardening
- orchestration hardening

These improve operational robustness and are required before live execution.

---

## 15. Live execution gate (separate and later)

Layer-3 bootstrap readiness is **not** the same as live execution readiness.

Live execution may be connected only when:

- paper-mode validation is complete
- calibration criteria are met
- operational readiness is in place
- DecisionPacket schema is frozen
- harness is passing end-to-end
- kill switch has been tested fail-closed

Session-aware execution policy becomes binding here, as part of execution-layer hardening and live-routing control.

---

## 16. Multi-asset extension (future expansion)

Diversification belongs at portfolio governance, not signal-level improvisation.

- each asset gets its own Layer-2 / Layer-3 stack and DecisionPacket
- portfolio supervisor allocates capital under concentration and correlation limits
- activate only after the gold engine satisfies stability and validation gates

---

## 17. Final statement

This architecture is deliberately biased toward:

- survival
- auditability
- replayability
- controlled learning
- contract discipline

Trade when relationships hold.  
Reduce exposure when they weaken.  
Step aside when the world becomes structurally unfamiliar.

Execution can always be added later.
The decision system must be frozen and validated first.
