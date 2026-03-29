# Gold Decision Engine — Architecture v4.1

> **Change from v4:** Layer-3 decision philosophy updated to state-driven / event-driven model.
> Layer-2 truth-layer contract and live-execution gate status are unchanged.
>
> `README_LAYER2.md` is part of the canonical set — collaborator guide and living build reference.
> Canonical documents are authoritative by role, not interchangeable by convenience.

---

## 1. Final conclusion

We are not building a "Zapier + ChatGPT trading bot."

We are building a **gold-first, regime-aware, supervisor-governed decision engine** that:

- emits deterministic DecisionPackets only
- forbids free text at the execution boundary
- is version-locked and replayable
- is fail-closed under data or operational faults
- is validated through paper-mode and harness-first discipline
- keeps execution optional and unwired until activation criteria are met
- **decides because state changed, not because time passed** ← updated

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
- **Layer-3 is state-driven / event-driven, not timeframe-driven** ← updated

---

## 3. Layer framing

### Core engine

- **Layer 2 — Truth Layer**
  Market + macro data, versioned, point-in-time disciplined, consumed through snapshot contract

- **Layer 3 — Decision Layer**
  Feature processing, indices, regime logic, supervisor governance, deterministic DecisionPacket.
  Consumes three governed inputs: Snapshot Truth, Live Market State, Event Risk Stream.

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

### Phase B — Layer-3 bootstrap (intentionally simple)

Layer-3 is **state-driven / event-driven**. Build in this order:

1. snapshot consumer (reads `latest_snapshot.json` or `snapshot_values` by `snapshot_id`)
2. DecisionPacket skeleton — minimal bootstrap fields: `decision_id`, `asset_id`, `engine_version`, `config_version`, `decision_ts`, `snapshot_id`, `regime_class`, `uncertainty_class`, `allowed_actions`, `preferred_action`, `confidence`, `uncertainty`, `data_ok`, `supervisor_ok`, `reason_code`, `no_trade_reason`
3. default `NO_TRADE` path — this is the correct first behavior
4. state taxonomy stub (regime_class, volatility_class, uncertainty_class)
5. guard taxonomy stub (data_ok, freshness_ok, supervisor_ok, cooldown_ok, duplicate_ok)
6. 2–3 deterministic calculations as proof-of-concept

Example early deterministic calculations:

- real-yield spread (DFII10 context)
- inflation-expectation spread (T10YIE vs T5YIFR)
- stress placeholder (MOVE level classification)

### Phase C — Layer-3 structured buildout

Only after bootstrap works:

1. Feature Builder stabilization
2. Index Suite (StressIndex, DriftIndex, CorrBreakIndex, DataFreshnessPenalty)
3. Regime Gate
4. Supervisor Engine (hard veto, soft shrink, UnknownMode)
5. Decision Engine hardening — full DecisionPacket emission
6. Live Market State adapters
7. Event Risk Stream integration
8. harness-based paper validation
9. calibration / threshold freezing

### Phase D — Live execution gate

Only after:

- paper validation is complete
- calibration criteria are met
- DecisionPacket schema is frozen
- operational readiness is complete
- kill switch is tested fail-closed

---

## 7. Layer 3 — Decision Layer

### Design model (updated 2026-03-22)

Layer-3 is a **state-driven / event-driven decision system**.

The canonical principle: **the system decides because state changed enough to justify governed action — not because a fixed amount of time elapsed.**

### Three governed inputs

#### A. Snapshot Truth (from Layer-2)
- authoritative, versioned, point-in-time, replayable base state
- slow-changing relative to intraday conditions
- Layer-2-owned — Layer-3 may not rewrite it
- governs: macro regime base, rates/inflation/USD context, structural trend context

#### B. Live Market State
- fast-changing, ephemeral, trigger-capable
- governs: intraday price state, volatility expansion, gap state, invalidation detection, execution urgency
- may trigger recompute or decision — may not rewrite Snapshot Truth

#### C. Event Risk State
- penalty / override / uncertainty escalation input only
- governs: geopolitical shocks, earnings proximity, macro release risk, exchange halts
- may restrict action space, increase uncertainty, trigger cooldown
- **may not generate direction by itself**

### State taxonomy

The engine must maintain at least three speed classes of governed state:

**Slow state** (refreshes on Layer-2 snapshot publication boundary):
- macro regime state
- structural trend state
- inflation / real-yield context
- correlation stability state
- broad uncertainty state

**Medium state** (refreshes on meaningful intraday change):
- local trend / momentum state
- volatility regime state
- liquidity / stress state
- cross-asset confirmation state
- asset-specific strength / weakness state

**Fast state** (refreshes on valid live market input):
- breakout state
- invalidation / stop state
- gap state
- event proximity state
- execution urgency state

A new decision is justified only if the combination of slow, medium, and fast state changes materially.

### Trigger taxonomy

Three trigger types must remain separate in code, logs, and schema:

- **Recompute trigger** — state refresh allowed, no action required. Examples: valid live market update, new snapshot publication, state score drift.
- **Decision trigger** — DecisionPacket candidate may be generated. Examples: regime change, volatility spike, breakout confirmation, supervisor flag changed, confidence crossed threshold.
- **Execution trigger** — routing allowed only if all guards pass. Requires: preferred action non-null and allowed, no veto, no cooldown, duplicate protection passed, execution urgency sufficient.

### Guard taxonomy

A decision must not be actionable if any of the following is true:

- snapshot truth unavailable
- required data freshness failed (`data_ok = false`, `freshness_ok = false`)
- uncertainty above allowed limit
- supervisor veto active (`supervisor_ok = false`)
- cooldown active (`cooldown_ok = false`)
- duplicate action candidate detected (`duplicate_ok = false`)
- system in degraded operational mode (`operational_ok = false`)

### NO_TRADE semantics

`NO_TRADE` is a valid, expected, first-class output — not an error condition.
Bootstrap default behavior should be dominated by `NO_TRADE` until thresholds and supervisor behavior are validated.

`NO_TRADE` must be used when: state change is insufficient, uncertainty too high, event risk too elevated, supervisor blocks action, required data missing or stale, cooldown or duplicate controls active.

When `preferred_action = NO_TRADE`: `no_trade_reason` must be populated, all guard fields must still be present.

### DecisionPacket — governed action contract

Every Layer-3 output must be a deterministic, machine-readable DecisionPacket. No free text at the execution boundary.

**Identity fields** (required):
- `decision_id` — unique identifier for the packet
- `asset_id` — canonical asset identifier
- `engine_version`, `config_version` — for audit and replay
- `decision_ts` — timestamp of emission
- `snapshot_id` — governing Layer-2 snapshot (truth anchor)

**State timestamp fields** (required):
- `snapshot_clock_ts` — clock timestamp of the governing snapshot
- `live_state_ts` — timestamp of latest accepted live market state
- `event_state_ts` — timestamp of latest accepted event risk state (may be null)

**State summary fields** (required):
- `regime_class` — `bull` / `bear` / `range` / `transition` / `unknown`
- `trend_state`
- `volatility_class` — `low` / `normal` / `elevated` / `spike` / `unknown`
- `liquidity_stress_class`
- `uncertainty_class` — `low` / `moderate` / `high` / `extreme` / `unknown`
- `correlation_state`
- `event_risk_class` — `none` / `watch` / `elevated` / `shock` / `unknown`

**Action fields** (required):
- `allowed_actions` — explicit list. Vocabulary: `enter_long`, `enter_short`, `hold`, `reduce`, `exit`, `no_trade`
- `preferred_action` — must be a member of `allowed_actions`
- `action_status` — `actionable` / `non_actionable` / `blocked` / `degraded`

**Confidence and risk fields** (required):
- `confidence` — numeric 0.0–1.0
- `uncertainty` — numeric 0.0–1.0
- `risk_class` — `low` / `moderate` / `high` / `extreme` / `blocked`
- `execution_urgency` — `none` / `low` / `medium` / `high` / `immediate`

**Guard fields** (required):
- `data_ok`, `freshness_ok`, `supervisor_ok`, `cooldown_ok`, `duplicate_ok`, `operational_ok`
- `guard_summary` — machine-readable structured object
- `supervisor_flags` — list of active supervisor conditions (e.g. `hard_veto`, `soft_shrink`, `unknown_mode`, `event_override`, `degraded_mode`)

**Invalidation and timing fields** (required):
- `invalidation_condition` — structured representation of what makes the preferred action invalid
- `cooldown_until` — timestamp until which identical follow-up action is blocked
- `duplicate_protection_key` — stable key to prevent re-emitting without material state change
- `max_valid_until` — latest timestamp after which the packet must be re-evaluated

**Reason fields** (required):
- `reason_code` — primary stable decision reason, enum-driven only
- `reason_detail_codes` — optional list of supporting sub-reasons
- `no_trade_reason` — mandatory when `preferred_action = no_trade`

**Non-negotiable packet rules:**
- `preferred_action` must be inside `allowed_actions`
- if `supervisor_ok = false` → packet must not be actionable
- if `data_ok = false` or `freshness_ok = false` → packet must not recommend aggressive new entry
- `no_trade_reason` must be present when `preferred_action = no_trade`
- `duplicate_protection_key` must be present for actionable outputs
- packet must support replay against the referenced `snapshot_id`

### Current status

Layer-3 is **not yet built**.

The following remain future work:

- Feature Builder
- Index Suite
- Regime Gate
- Supervisor Engine
- Decision Engine / DecisionPacket generator
- Live Market State adapters
- Event Risk Stream integration

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

## 8. Layer-3 Implementation Risks

The state-driven / event-driven model introduces implementation risks that must be tracked here, not in the limitations document. These are design-level risks, not Layer-2 data gaps.

| Risk | Description | Mitigation |
|---|---|---|
| Live state leaking into truth history | Live Market State adapters must not write to `observations` or influence `as_of_ts` alignment | Strict separation: live state lives entirely outside `layer2_truth.db` |
| Event trigger noise | Event Risk Stream inputs may over-trigger recompute if not properly classified | All event inputs are penalty / override / uncertainty only — never directional by themselves |
| Recompute / decision / execution conflation | These three trigger types must remain separate in code, logs, and schema | Explicit trigger taxonomy: recompute / decision / execution must remain separate in code, logs, and schema — enforce from bootstrap |
| Premature calibration confidence | DecisionPackets may appear correct before thresholds are validated | Bootstrap must default to `NO_TRADE` until calibration criteria are met |
| Scheduler complexity | Three input speeds (snapshot / live / event) require three independent refresh disciplines | Each speed must be independently scheduled and monitored — operational gaps here remain open |

---

## 9. What Has Not Changed

The following remain unchanged by the Layer-3 philosophy update:

| Element | Status |
|---|---|
| Layer-2 truth-layer contract | Unchanged — operational |
| Snapshot-only reads for Layer-3 | Unchanged — mandatory |
| Fail-closed gate (Tier-1 blocking) | Unchanged — core constitution |
| Version-locking (engine + config + snapshot_id) | Unchanged — required for replay |
| Supervisor governance (hard veto, soft shrink, UnknownMode) | Unchanged — central risk control |
| Event inputs non-directional | Unchanged — penalty / override only |
| Live execution gate | Unchanged — later-gated |
| Paper-mode first discipline | Unchanged |

---

## 10. Interpretation Rule

This architecture document defines the sequencing boundary and target design.

For current Layer-2 status, interpret together with:

- `README_v1.md`
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`