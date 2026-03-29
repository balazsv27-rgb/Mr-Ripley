# Layer-2 Technical Handbook
## Mr. Ripley — Gold-First Decision Engine

> **Entry-point summary:** `README_v1.md`
> **Architecture reference:** `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
> **Limitations / approximations:** `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
> **Implementation record:** `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
> **Last updated:** 2026-03-22

---

## 1. Purpose and System Role

Layer-2 is the truth and observation layer of the Mr. Ripley gold-first decision engine.

Its responsibilities are:

- ingest market and macro time-series data from external sources
- validate freshness against governed staleness rules
- store observations in an immutable, point-in-time correct store
- publish versioned, deterministic snapshots as the stable API consumed by Layer-3

Layer-2 responsibility ends at snapshot publication.

It does **not** compute:

- features
- indices
- regimes
- supervisor decisions
- execution actions

Any downstream computation is Layer-3 work.

---

## 2. Current Architecture Position

```
Layer-1  →  Event Tagger / Narrative Risk Modifiers   (optional, disabled by default)
Layer-2  →  Ingestion + validation + snapshot store    ← THIS DOCUMENT
Layer-3  →  State-driven decision engine               (not yet built — philosophy frozen)
Layer-4  →  Execution orchestration                    (not yet built / intentionally unwired)
```

Layer-3 must consume only published snapshots. It must never query `observations` directly.

Layer-3 note: as of 2026-03-22, the Layer-3 decision philosophy is frozen as of 2026-03-22. The engine will be state-driven / event-driven, consuming Snapshot Truth from Layer-2 alongside Live Market State and Event Risk Stream as additional governed inputs. Neither of those additional inputs may touch Layer-2 storage.

---

## 3. Core Invariants

| # | Invariant | Implication |
|---|---|---|
| 1 | Registry is the single source of truth | Series metadata, thresholds, and tiering come from `series_registry.json` |
| 2 | Fail-closed publication | Tier-1 blocking failures prevent snapshot publication |
| 3 | Version-locked snapshots | `engine_version`, `config_version`, and `snapshot_id` are part of the boundary |
| 4 | Point-in-time discipline | Alignment respects governed `clock_date` / `clock_ts` boundaries |
| 5 | Snapshot-only downstream reads | Layer-3 consumes snapshots, never raw `observations` |
| 6 | snapshot_id as DecisionPacket anchor | Every Layer-3 DecisionPacket must carry the `snapshot_id` of its governing snapshot |

---

## 4. Current Layer-2 Stack

Current documented Layer-2 stack:

- `layer2/config/series_registry.json`
- `layer2/config/registry.py`
- `layer2/clock.py`
- `layer2/alignment.py`
- `layer2/adapters/quality_gate.py`
- `layer2/adapters/snapshot_publisher.py`
- `layer2/db.py`

Current adapter set in documented use:

- `gold_adapter.py`
- `move_adapter.py`
- `gld_holdings_adapter.py`
- `fred_loader.py`

---

## 5. Layer-2 → Layer-3 Handoff Gate

### Required handoff items

| Item | Status |
|---|---|
| Snapshot contract stable | ✅ Done |
| `engine_version` + `config_version` reliable in snapshot outputs | ✅ Done |
| `guards` structured object in snapshot JSON | ✅ Done |
| `reason_code` enum defined in shared constants | ✅ Done |
| Current v1 docs aligned to current contract behavior | ✅ Done |
| Layer-3 decision philosophy frozen | ✅ Done |
| Layer-3 DecisionPacket schema v0 defined | ✅ Done |

### Current gate result

The contract-side Layer-2 → Layer-3 handoff gate is now satisfied.

This means Layer-3 bootstrap may begin.

---

## 6. Snapshot Publication Boundary

### Publication preconditions

A normal non-forced publication requires:

1. governed clock resolved
2. Tier-1 freshness / completeness pass
3. no blocking fail-closed condition
4. aligned point-in-time payload available
5. no duplicate snapshot for the same `clock_ts` + `engine_version` + `config_version`

### Publication outputs

A successful publication writes:

- one row to `snapshots`
- one row per included series to `snapshot_values`
- `latest_snapshot.json`

### Observed successful publication example

- `snapshot_id`: `a562bef5b93fa07794e9b73c17a24ddad0ce271678fd52cc939ac1d4cae32526`
- `engine_version`: `gold-v3.3.0`
- `config_version`: `1.0.0`
- `clock_ts`: `2026-03-15T22:00:00+00:00`
- Tier-1 gate result: `15 / 15 PASS`

---

## 7. Current Snapshot Contract

Current published snapshot fields include:

- `snapshot_id`
- `engine_version`
- `config_version`
- `clock_ts`
- `clock_date`
- `verdict`
- `forced`
- `dry_run`
- `guards`
- `tier1_series`
- `tier2_series`
- `missing_series`
- `layer1_events`

Current informational fields also included:

- `run_ts`
- `published_at`
- `series_count`
- `quality_summary`
- `values_by_group`
- `values`

Current published grouped / flat value views include `as_of_ts` and `revision_seq`.

### snapshot_id as Layer-3 anchor

The `snapshot_id` is the primary contract anchor between Layer-2 and Layer-3.

Every DecisionPacket emitted by Layer-3 must carry:
- `snapshot_id` — the governing snapshot used as truth base
- `snapshot_clock_ts` — the clock timestamp of that snapshot

This ensures every decision is replayable against a specific, immutable Layer-2 publication.
Every DecisionPacket must carry `decision_id`, `asset_id`, `engine_version`, `config_version`, `decision_ts`, and `snapshot_id` as identity fields. State timestamps must include `snapshot_clock_ts`, `live_state_ts`, and `event_state_ts`. See the Layer-3 section of `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` for the full field reference.

---

## 8. Quality Gate Semantics

The quality gate is a Layer-2 truth-discipline gate.

It exists to answer:

- Is Tier-1 complete?
- Is Tier-1 fresh enough under governed thresholds?
- Is publication allowed under normal fail-closed rules?

### Current observed publication boundary result

- Tier-1 total: 15
- Tier-1 pass: 15
- Tier-1 fail: 0
- Tier-2 total: 5
- Tier-2 warnings: 2

Tier-2 warnings do not block publication.

### Relationship to Layer-3 guard fields

The Layer-2 quality gate result maps directly to Layer-3 DecisionPacket guard fields:

| Layer-2 gate result | Layer-3 guard field | Implication |
|---|---|---|
| Tier-1 all pass | `data_ok = true`, `freshness_ok = true` | Packet may be actionable if other guards pass |
| Any Tier-1 fail | `data_ok = false` or `freshness_ok = false` | Packet must not recommend aggressive new entry |
| VERDICT: FAIL (no snapshot published) | No valid snapshot → Layer-3 cannot form a packet | `NO_TRADE` is the only valid output |

---

## 9. What Is Still Not Built

The following are still not built:

- revision writer
- complete `revision_risk` tracking
- scheduler / orchestrator
- alerting / retry / kill switch
- Layer-3 Feature Builder
- Layer-3 Index Suite
- Layer-3 Regime Gate
- Layer-3 Supervisor
- Layer-3 DecisionPacket generation
- Layer-3 Live Market State adapters
- Layer-3 Event Risk Stream integration
- live execution wiring

---

## 10. Verification Status

### Current verification framing

The current v1 document set now consistently reflects:

- contract-side handoff gate satisfied
- successful non-forced Layer-2 snapshot publication observed
- Layer-3 decision philosophy frozen
- Layer-3 not yet built
- live execution not ready

### Open verification / hygiene items that still matter

| Area | Current result |
|---|---|
| Repo hygiene for runtime artifacts | Still should be treated as an active check |
| Independent line-by-line code certification | Not available from documentation alone |
| Full revision-aware backtest hardening | Not yet complete |

---

## 11. Interpretation Rule

Use this handbook as the structured engineering reference for the current system state.

For:
- status classification → use `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
- remaining risks / approximations → use `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
- Layer-3 decision model → see `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7
- Layer-3 output contract → see `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` section 7 (DecisionPacket field reference)
- long-form history → use `SYSTEM_IMPLEMENTATION_RECORD_v1.md`

`README_LAYER2.md` is part of the canonical current-state set — collaborator guide and living build reference.
Canonical documents are authoritative by role; use the role-matched source for strong claims.


Yes. Your current structure is now rich enough to support a real DAG runner. The key point is this:

**the runner must treat `system-orchestration.yaml` as an executable step graph, not as documentation metadata.**

That is already strongly implied by:

* the constitutional workflow-governance constraint in `CLAUDE.md`
* the YAML’s `execution_policy` flags (`workflow_mandatory`, `enforce_order`, `enforce_stage_gates`, `enforce_blocking_conditions`, `reject_partial_execution`) 
* the workflow step model with `inputs`, `outputs`, `depends_on`, `validates`, and `on_block`
* the final pre-PR gate requiring specific artifacts to exist before `commit` or `push` 

## What the DAG runner should do

It should implement five hard responsibilities.

### 1. Compile YAML workflow steps into a typed execution graph

Each `workflow` entry becomes a node with:

* `id`
* `component`
* `layer`
* `inputs`
* `outputs`
* `depends_on`
* `validates`
* `on_block`
* optional execution condition

This is already present in your YAML, especially in the layered workflow section.

### 2. Resolve execution order from dependencies, not from list position alone

The YAML is written in order, but the runner should still compute the DAG from `depends_on`.
That gives you:

* validation of missing dependencies
* cycle detection
* future extensibility
* partial re-run safety

### 3. Materialize outputs as first-class governance artifacts

The runner must not treat outputs as informal notes. It should persist them in a run state store, because your hooks and final governance gate explicitly require artifacts such as:

* `governance_context`
* `claim_classification_map`
* `phase_alignment_status`
* `guard_report`
* `doc_update_plan`
* `verification_ledger_delta`
* `pr_readiness_verdict`

### 4. Halt on blocking conditions

Your YAML already defines named blocking conditions and ties them to workflow stages and hooks. The runner should therefore maintain a blocking-condition registry and stop forward progress immediately when one is raised. 

### 5. Gate tool actions through runner state

The `pre-pr-governance-gate` is only truly meaningful if `git commit` / `git push` checks the DAG-run state rather than ad hoc local heuristics. The hook should read the runner’s artifact ledger and blocking-condition ledger. 

---

## Best-fit architecture in your structure

Given your existing orchestrator work, the cleanest design is:

### A. YAML compiler layer

Reads `system-orchestration.yaml` and builds an in-memory `GovernanceDAG`.

### B. Node executor layer

Maps each node’s `component` to a concrete executor:

* `constitution` → loader
* `skill:...` → skill runner
* `hooks` → hook synthesizer / state check
* `subagents` → escalated audit dispatcher
* `stage_gates` → gate evaluator

### C. Run state store

Persists:

* produced artifacts
* node status
* blocking conditions
* audit escalations
* execution trace
* final verdict

### D. Hook bridge

Your Claude Code hooks should not independently “decide truth.”
They should query the DAG runner state:

* “Has the required graph completed?”
* “Are any blocking conditions unresolved?”
* “Does the required artifact set exist?”

### E. Policy adapters

A small layer that interprets YAML semantics like:

* `when runtime/code scope is touched`
* `when change scope requires it`
* `Execute only if change_type == rename_only`

That part cannot remain plain English forever. It must become executable predicates.

---

## The internal data model you need

A minimal but correct model would look like this:

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal

NodeStatus = Literal["pending", "running", "passed", "failed", "blocked", "skipped"]

@dataclass
class WorkflowNode:
    id: str
    layer: str
    component: str
    purpose: str
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    validates: List[str] = field(default_factory=list)
    on_block: Optional[str] = None
    condition: Optional[str] = None
    reinforced_by_hook: Optional[str] = None

@dataclass
class BlockingConditionEvent:
    condition_id: str
    raised_at: str
    detail: str
    resolved: bool = False

@dataclass
class ArtifactRecord:
    name: str
    producer_node: str
    value: Any
    exists: bool = True

@dataclass
class NodeResult:
    node_id: str
    status: NodeStatus
    produced_artifacts: List[str] = field(default_factory=list)
    raised_conditions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

@dataclass
class GovernanceRunState:
    request_id: str
    workflow_name: str
    node_results: Dict[str, NodeResult] = field(default_factory=dict)
    artifacts: Dict[str, ArtifactRecord] = field(default_factory=dict)
    blocking_conditions: List[BlockingConditionEvent] = field(default_factory=list)
```

This is the minimum structure required to make the YAML operational rather than descriptive.

---

## Execution algorithm

The runner flow should be:

### Step 1: Load constitution + YAML

Load `CLAUDE.md` and `system-orchestration.yaml`.
Validate that the constitution requires orchestration-based enforcement and that the YAML declares mandatory workflow execution.

### Step 2: Compile the graph

* parse all workflow steps
* validate unique IDs
* validate that every `depends_on` target exists
* validate that each output has at most one producer
* validate no cycles

### Step 3: Bind step executors

Map:

* `skill:doc-truth-classification` → skill implementation
* `skill:change-impact-audit` → skill implementation
* `subagents` → audit dispatcher
* `hooks` → summarizer or readiness evaluator
* `stage_gates` → gate engine

### Step 4: Run nodes topologically

For each node:

* verify dependencies passed
* evaluate condition, if any
* resolve required input artifacts
* execute the node
* record outputs
* record raised blocking conditions
* halt if any unresolved blocking condition is fatal

### Step 5: Persist run artifacts

Write a governed run directory, for example:

```text
.ai-orchestrator/governance_runs/<request_id>/
  run_state.json
  artifacts/
    governance_context.json
    claim_classification_map.json
    ...
    pr_readiness_verdict.json
```

### Step 6: Hook integration

Before `git commit` or `git push`, the hook reads the latest active run state and checks:

* required artifact set exists
* no unresolved blocking conditions
* final gate passed

That exactly matches your current YAML gate intent. 

---

## The most important implementation decision

You need to distinguish between two kinds of nodes:

### Pure evaluation nodes

They inspect inputs and emit verdicts.
Examples:

* `phase-check`
* `snapshot-contract-check`
* `runtime-boundary-check`
* `update-verification-ledger`

### Dispatch nodes

They select specialized behavior.
Examples:

* `deep-audit`
* `runtime-guards-summary`
* `pre-pr-governance-readiness`

That means your executor interface should support both direct skill execution and orchestration/meta execution.

A clean interface is:

```python
class GovernanceNodeExecutor:
    def execute(self, node: WorkflowNode, state: GovernanceRunState, context: dict) -> NodeResult:
        ...
```

Then implement:

* `SkillExecutor`
* `StageGateExecutor`
* `HookSummaryExecutor`
* `SubagentDispatcherExecutor`
* `ConstitutionLoaderExecutor`

---

## Where it fits in your existing orchestrator

Based on your broader orchestrator patterns, the clean insertion point is:

### New package

```text
graph/
  governance_types.py
  governance_compiler.py
  governance_runner.py
  governance_registry.py
  governance_state.py
  governance_hooks.py
```

### Responsibilities

* `governance_compiler.py`
  Parses YAML → `WorkflowNode[]`
* `governance_registry.py`
  Maps `component` strings to executable handlers
* `governance_runner.py`
  Runs DAG, halts on block, persists state
* `governance_state.py`
  Reads/writes artifact + blocking-condition state
* `governance_hooks.py`
  Exposes simple functions for `commit/push` hooks

---

## What must be added to the YAML before this is fully executable

Your YAML is close, but not yet fully machine-ready.

### 1. Predicate fields must become formal

Right now you have human-language conditions like:

* `when runtime/code scope is touched`
* `when adapter/registry scope is touched`
* `when change scope requires it` 

These need formal predicates, for example:

```yaml
requires_if:
  changed_paths_any:
    - "layer2/**"
    - "layer3/**"
```

or

```yaml
condition:
  expr: change_impact_report.change_type == "rename_only"
```

You already started this for `rename-invariance-check`; that is the right direction. 

### 2. Undefined skill reference must be fixed

Your workflow contains:

```yaml
component: skill:rename-invariance-check
```

but that skill is not declared in the `skills:` section shown earlier. That will break registry binding unless you add it explicitly.

### 3. Duplicate hook block should be cleaned

`pre-pr-governance-gate` contains duplicated `action` / `on_fail` entries. That should be normalized before a compiler relies on it. 

### 4. Constitution role label is semantically off

In YAML, under `constitution`, you currently use:

```yaml
role: authoritative_execution_specification
```

But the same file still says the constitution does not execute workflows; enforcement belongs to hooks, runners, validators. 

So for machine clarity, the role should be closer to:

* `authoritative_governance_constraints`
  or
* `authoritative_normative_source`

The YAML itself should remain the execution specification.

---

## Recommended runtime contract

The runner should produce one final machine-verdict object:

```json
{
  "request_id": "govrun-2026-03-29-001",
  "workflow_completed": true,
  "partial_execution_rejected": false,
  "unresolved_blocking_conditions": [],
  "required_outputs_present": true,
  "pr_readiness": "pass"
}
```

Then the `pre-pr-governance-gate` hook only needs to ask:

```python
if not run_state.workflow_completed:
    block()
if run_state.unresolved_blocking_conditions:
    block()
if run_state.pr_readiness != "pass":
    block()
```

This is much safer than re-deriving all logic inside the hook.

---

## Best rollout strategy

I would implement it in three passes.

### Phase 1 — Graph execution only

* compile workflow
* execute nodes in order
* persist artifacts
* halt on blocks

No hook integration yet.

### Phase 2 — Hook-backed enforcement

* `commit` / `push` checks runner state
* no bypass if workflow incomplete
* no bypass if blocks unresolved

### Phase 3 — Predicate formalization + selective reruns

* path-based conditions
* rename-only conditional execution
* targeted reruns of affected subgraph only

That sequence fits your fail-closed model much better than trying to make everything dynamic at once. The constitution explicitly requires fail-closed behavior and blocks unsupported claims, which strongly favors progressive hardening over loose early automation.

## Bottom line

Yes, DAG runner enforcement is the right fit for your structure.

The correct implementation model is:

**constitution defines obligation → YAML defines executable graph → runner executes graph → hooks verify runner state**

Your current files already contain almost all the semantics needed for that model. The remaining work is mainly:

* compile YAML into machine-typed nodes
* persist artifact/state outputs
* formalize predicates
* bind hooks to DAG-run state
* fix a few manifest inconsistencies before execution

The two highest-priority fixes before coding are:

1. add the missing `rename-invariance-check` skill declaration, since the workflow already references it
2. make conditional clauses machine-readable instead of English-only, especially around scope-sensitive outputs and rename-only execution

I can turn this into a concrete implementation spec for your orchestrator next.
