architecture3.md

Here’s a tightened, updated version of that whole “final conclusion + v3 architecture summary” text, modified to match what we’ve now agreed is final:

Layer 1 is explicitly optional and disabled by default

Zapier-style harness is mandatory

Deterministic replay + version-locking + fail-closed policy are explicit

Confidence/uncertainty thresholds are configurable + calibration-governed (not arbitrary)

DecisionPacket includes engine_version + config_version

Gate logic is version-locked to engine_version

UnknownMode is defined

Final conclusion (what we’re actually building)

We are not building a “Zapier + ChatGPT trading bot.”

We are building a Gold-first, regime-adaptive decision engine with:

Deterministic outputs (DecisionPacket only; no free-text at execution boundary)

Supervisor governance (hard veto + soft shrink constitution)

Uncertainty / stress / drift / correlation-break controls

Vintage / as-of macro discipline (point-in-time correct features; revision-risk tracked)

Friction-aware validation (paper + simulated costs; not “PnL-only”)

Execution is optional and contract-based, and remains intentionally unwired until:

the decision math is frozen,

deterministic replay passes,

calibration is proven,

and the Zapier-style harness exit criteria are met.

This aligns with the M1 principle: structured evidence → scenarios → uncertainty, validated by stability, calibration, and survival metrics, not by PnL alone.

Gold Decision Engine — Architecture v3.3 (Final)

This document defines the governed architecture for a Gold-first decision engine designed to be:

Regime-aware

Drift-aware

Correlation-break-aware

Supervisor-governed

Deterministic and replayable at the execution boundary

Fail-closed under operational faults

Validation-first via a Zapier-style harness

Execution integration is architecturally defined but prohibited until numerical definitions, calibrations, and validation metrics are frozen and verified.

Core philosophy

We are not building “an AI trading bot.”

We are designing:

A regime-adaptive gold decision system with supervisory governance
that produces deterministic execution contracts for controlled validation.

If an LLM is used at all, it is analyst/auditor only, not the brain.

The brain is a structured state machine + governed policy.

Layer framing (updated and explicit)
Core Engine (Mandatory)

Layer 2: Truth Layer (Market + Macro Data, Versioned & Point-in-Time Correct)

Layer 3: Decision Layer (Regime + Supervisor + Deterministic DecisionPacket)

Optional Add-On (Disabled by Default)

Layer 1: Event Tagger / Narrative Risk Modifiers (Penalty-only, Non-trading)

Optional Layer 1 — Event Tagger / Narrative Risk Modifiers (Disabled by default)

Purpose: Convert narrative signals into structured events relevant to gold for research and risk penalties only.

Allowed effects (penalty-only):

Raise uncertainty

Trigger cooldown

Add research tags / evidence references

Apply veto penalties

Prohibited effects:

Cannot generate BUY/SELL

Cannot flip direction

Cannot override Layer 2–3 decisions

Cannot alter execution boundary logic

Output contract: Event (structured, auditable, immutable evidence refs)

Layer 2 — Market & Macro APIs (Truth Layer)

Purpose: Maintain authoritative numerical history + current state for gold and macro drivers.

Inputs

Market: gold proxy price (XAUUSD / GC / GLD), OHLCV, volatility proxies

Macro: real yield proxies, USD proxies, optional policy/inflation proxies

Mandatory discipline: Vintage / As-of awareness

Macro data may be revised.

Backtests and replays must use point-in-time correct values.

If vintage is unavailable: mark revision_risk=true and penalize confidence/raise uncertainty accordingly.

Core components

Ingestion scheduler (backfill + incremental)

Versioned time-series store (observations)

Feature builder (standardized, multi-horizon)

Freshness tracker (staleness penalties)

Feature store interface supporting point-in-time reconstruction

Layer 3 — Memory + Regime + Decision System (Decision Layer)

Purpose: Map current state to regimes and governed decisions with supervisor control.

Inputs

MarketState(t), MacroState(t), FeatureVector x_t from Layer 2

Optional Event stream from Layer 1 (penalty-only influence)

3.1 Analog Memory Engine (optional module)

Produces ScenarioResult (probabilities, bands, tails, analogs).
Analytical only; does not directly execute.

3.2 Regime Gate (conditional world model)

Regime effects are conditional; static “real yields * -1” rules are forbidden.

UnknownMode (formal behavior)
Activated when:

regime confidence < configurable threshold (placeholder default: 60%) OR

regime signals conflict materially

In UnknownMode:

confidence floored to 0

uncertainty forced ≥ U_max

cooldown increments

alert generated

directional execution prohibited

3.3 Index Suite (not frozen until calibrated)

StressIndex (0–100)

DriftIndex (0–100)

CorrBreakIndex (0–100)

DataFreshnessPenalty (0–100)

If indices are not frozen or null → supervisor must degrade confidence / increase uncertainty.

3.4 Supervisor Engine (governance constitution)

Hard veto (non-negotiable):

data_ok == false → NO TRADE

idempotent_ok == false → NO TRADE

UnknownMode active → NO TRADE

uncertainty > U_max → NO TRADE

Soft constraints:

stress/drift/corrbreak high → shrink position

disagreement high → shrink or pause

Decision boundary (deterministic execution contract)

Execution systems may read only the deterministic DecisionPacket.
No free-text is permitted.

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

Rules

No free text.

reason_code must be enumerated.

engine_version and config_version required for replayability.

Gate logic must be version-locked to engine_version.

Mandatory validation: Zapier-style test harness (non-negotiable)

We validate through a strict orchestration pipeline:

Trigger → Fetch/Transform → Call Engine → Schema Validate → Gate → Route → Paper Execute → Immutable Log → Post-Session Analysis

Orchestrator is plumbing only: routes deterministic fields, interprets no text, invents no trading logic.

Strict gate (confidence / uncertainty made real)

Execution is allowed only if:

guards.data_ok == true

guards.idempotent_ok == true

guards.cooldown_ok == true

guards.supervisor_veto == false

confidence >= C_min

uncertainty <= U_max

risk caps satisfied

Threshold governance

C_min / U_max are configurable and versioned

No runtime override permitted during active sessions

Thresholds frozen only after calibration criteria are met

Calibration protocol (thresholds aren’t theater)

Freeze thresholds only after:

≥ 100–300 decision ticks

≥ 30–100 executed paper trades (or statistically adequate sample)

monotonic calibration holds (higher confidence → better outcomes; higher uncertainty → worse dispersion)

Metrics required:

reliability curve + Brier score

drawdown + CVaR

regime breakdown

calibration error

PnL alone is insufficient.

Layer 4 — Execution orchestration (optional, intentionally unwired)

Purpose: Execute orders strictly based on DecisionPacket.

Components:

Trigger

Router

Broker adapter (paper first)

Logger (immutable)

Guardrail validator (schema + sanity)

Kill switch (fail-closed)

Failure policy:

On unrecoverable failures → kill switch engaged, default NOTHING, alert within 60s, retries capped and idempotent.

Multi-Asset Extension — Diversification (future expansion)

Diversification is implemented at portfolio governance, not signal level.

Each asset has its own Layer 2/3 and DecisionPacket

Portfolio Supervisor allocates capital under correlation and concentration limits

Activation only after Gold engine stability gates are satisfied (M1/M2 + harness success)

Final statement

This architecture is deliberately biased toward survival, auditability, and controlled learning:

Trade when relationships hold

Reduce exposure when they weaken

Step aside when the world becomes structurally unfamiliar

Execution can always be added later.
The decision system must be frozen and validated first.