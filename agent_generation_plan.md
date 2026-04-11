# Agent Generation Plan — Mr. Ripley Gold First Engine

> **Status:** Architecture + implementation plan — partially implemented. agents.yaml created, workflow wired. Implementation procedure defined.
> **Scope:** Defines how agents and subagents integrate into the DAG-governed orchestration system.
> **Authority:** Derived from CLAUDE.md constitutional rules and system-orchestration.yaml execution model.
> **Authoritative definitions:** `.claude/workflows/packages/agents.yaml` (agents), `.claude/workflows/packages/subagents.yaml` (subagents)

---

## 1. Purpose and Scope

### Why agents are needed in THIS system

The Mr. Ripley governance orchestration has four component types, now with clear separation:

- **Skills** — LLM behavioral instructions bound to workflow steps. They shape Claude's reasoning but have no guaranteed execution fidelity. They are semantic, not structural.
- **Hooks** — Programmatic enforcement points (shell scripts, PreToolUse/PostToolUse triggers). They are the only hard enforcement layer. They block or allow actions deterministically.
- **Subagents** — Escalation-only audit specialists dispatched by specific violation conditions. Defined in `subagents.yaml`. They do NOT execute primary workflow steps.
- **Agents** — Primary workflow step executors. Defined in `agents.yaml`. They provide scoped context isolation, constrained tool access, and structured artifact production. Each agent is bound 1:1 to a workflow step via `agent_binding`.

**The gap agents fill:**

Skills instruct but don't isolate. Hooks enforce but don't reason. Subagents investigate violations but don't execute primary steps. Agents provide the missing *execution body* for workflow steps — scoped, isolated, multi-step reasoning with constrained tools and deterministic artifact output.

> An agent is a **governed workflow component that is the primary executor of a workflow step** — scoped context, constrained tools, structured artifact output, and deterministic invocation via the DAG runner.

Agents do NOT replace the DAG. They execute *within* it as the implementation body of skill-bound steps.

### What agents are NOT in this system

- Free autonomous Claude subagents that decide their own scope
- Runtime-created execution units
- Decision engines or execution triggers
- Replacements for hooks or DAG orchestration
- Escalation targets (that role belongs to subagents)

---

## 2. Reverse-Engineered Model (from source plan)

### Source material

The primary reverse-engineering source is `.claude/bootstrap/candidate-agents.md` (now marked SUPERSEDED), which defined three Layer-2 operational agents:

| Agent | Model | Role |
|-------|-------|------|
| `planner` | opus | Analyze scope, map dependencies, propose minimal safe plan |
| `implementer` | sonnet | Execute patches per approved plan |
| `reviewer` | sonnet | Verify contract safety, conventions, verification |

These were placeholder `.md` files in `.claude/agents/` — they were **not wired into the governance workflow** and have been **removed**. The authoritative agent definitions now live in `agents.yaml`.

### Original plan structure

The candidate-agents model followed a **plan - implement - review** lifecycle:

1. **Planner** — Read-only analysis producing a structured scope analysis and minimal plan
2. **Implementer** — Executes approved plan with code conventions enforcement
3. **Reviewer** — Post-implementation verification with structured pass/fail output

Key properties:
- Each agent had explicit tool constraints (planner = read-only; implementer = read+write; reviewer = read+bash)
- Agents were invoked by the user, not by an orchestrator
- Output was structured markdown with checklists
- Activation triggers were user-facing ("use when...")

### Execution model assumptions

The original plan assumed:
- **Human-in-the-loop invocation** — user decides when to spawn an agent
- **Agent-to-agent handoff** — planner output feeds implementer; implementer output feeds reviewer
- **No DAG integration** — agents operated outside the governance workflow
- **Layer-2 operational scope only** — no governance workflow agents

### What was preserved

| Element | Rationale |
|---------|-----------|
| Scoped tool access per agent | Principle of least privilege; read-only agents cannot edit |
| Structured output format | Enables artifact production and downstream consumption |
| Read-before-write discipline | Aligns with CLAUDE.md's fail-closed principle |
| Model selection per agent | Allows matching reasoning capacity to task complexity |
| Explicit activation context | Prevents spurious invocation |

### What was rejected

| Element | Rationale |
|---------|-----------|
| Human-only invocation model | Agents must be invocable as DAG nodes, not just by user request |
| Standalone `.md` file definitions | Agents are defined in `agents.yaml` as workflow package members, not as freestanding files |
| No DAG integration | Agents must participate in the governance workflow DAG |
| Agent-to-agent direct handoff | Handoff must be mediated by the DAG runner via artifact dependencies |
| Layer-2 operational scope limitation | Governance workflow agents are the primary use case |
| Absence of artifact contracts | Every agent must declare what it produces and what it consumes |
| Grouped multi-step agents | 1:1 agent-to-step binding provides clearer failure isolation |

### What was adapted

| Element | Original Form | Adapted Form |
|---------|--------------|--------------|
| Activation triggers | "Use when..." user guidance | DAG node invocation via `agent_binding` field |
| Output format | Freeform markdown with checklists | Structured artifact conforming to `artifacts.yaml` contract |
| Agent lifecycle | Spawn - execute - return | DAG-scheduled - execute - produce artifact - DAG advances |
| Scope definition | Implicit (via description) | Explicit (inputs, outputs, dependencies, authority sources) |
| Agent definition location | `.claude/agents/<name>.md` | `.claude/workflows/packages/agents.yaml` (single authoritative file) |
| Subagent relationship | Not addressed | Subagents are a strictly separate concept in `subagents.yaml` |
| Agent-to-step ratio | Implicit (3 agents for all work) | Explicit 1:1 binding (14 agents for 14 skill-bound steps) |

---

## 3. System Alignment Layer

### How agents map to existing components

| Component | Role | Execution Type | Enforcement | Invocation |
|-----------|------|---------------|-------------|------------|
| **DAG Runner** | Orchestrator — controls step ordering, dependency resolution, fail-closed halting | Structural (shell-mode) | Deterministic — halts on validation failure | Entry point; not invoked by others |
| **Workflow Step** | Atomic unit in the DAG — declares inputs, outputs, dependencies | Declarative node | Via `depends_on`, `validates`, `raises` | By DAG runner when dependencies satisfied |
| **Skill** | Behavioral instruction — shapes Claude's reasoning within a step | Semantic (LLM prompt) | None — advisory only | Bound to step via `component: skill:<name>` |
| **Hook** | Hard enforcement — blocks/allows actions programmatically | Programmatic (shell) | Deterministic — block or pass | Trigger-based (PreToolUse, PostToolUse, SubagentStop) |
| **Agent** | Primary step executor — scoped multi-step reasoning with constrained tools and structured artifact output | Hybrid (DAG-scheduled + LLM-executed) | Tool constraints + artifact contracts + hook reinforcement | Bound to step via `agent_binding` field |
| **Subagent** | Escalation-only audit specialist — deep investigation of specific governance violations | Conditional dispatch | Via trigger conditions on artifact fields | By `escalates_to` / `audit_dispatch` conditions only |

### Agent position in the architecture

```
DAG Runner
  |
  +-- Workflow Step (node)
        |-- component: skill:<name>         (behavioral instruction)
        |-- agent_binding: <agent_name>     (primary executor)
        |-- reinforced_by_hook: <hook>      (hard enforcement)
        +-- escalates_to: [subagents]       (escalation dispatch)
```

An agent is the *execution body* of a workflow step. The skill tells it how to reason. The hook enforces its outputs. The subagent handles its escalation path. The DAG controls when it runs.

### Authoritative definition files

| What | Where | Contains |
|------|-------|----------|
| Agent definitions | `agents.yaml` | 14 primary step executors with model, tools, artifacts, failure modes |
| Subagent definitions | `subagents.yaml` | 8 escalation-only audit specialists with trigger conditions |
| Step bindings | `workflow-steps.yaml` | `agent_binding` field on each skill-bound step |
| Behavioral instructions | `skills.yaml` | 13 skills consumed by agents |
| Enforcement rules | `hooks.yaml` | 6 hooks reinforcing agent outputs |

---

## 4. Agent Definition Standard

### Authoritative location

All agent definitions live in a single file:

```
.claude/workflows/packages/agents.yaml
```

There are no standalone agent `.md` files. The YAML package model is authoritative.

### Required schema per agent

Each agent entry in `agents.yaml` MUST contain:

```yaml
- name: <agent_name>              # unique ID, referenced by agent_binding
  role: <functional_role>          # what this agent does in the workflow
  layer: <governance_layer>        # A through E
  purpose: <description>           # what this agent accomplishes
  model: <opus | sonnet>           # LLM model selection
  tools: [<tool_list>]             # allowed tools (least privilege)
  workflow_steps:                   # 1:1 binding to workflow step
    - <step_id>
  skill_bindings:                   # skills providing behavioral instructions
    - <skill_name>
  produces:                         # required output artifacts
    - <artifact_id>
  consumes:                         # input artifacts and documents
    - <artifact_or_doc>
  hook_reinforcement: <hook | null> # hook that enforces this agent's output
  escalation_targets:               # subagents dispatched on violations
    - subagent: <subagent_name>
      condition: <trigger_condition>
  failure_mode: <description>       # behavior on failure (default: fail closed)
```

### Optional fields

```yaml
  activation_predicate: <predicate>  # scope predicate required for execution
```

---

## 5. Agent Invocation Model

### A. DAG-Controlled Invocation (PRIMARY AND REQUIRED)

This is the only valid invocation mode for governance workflow agents.

**How it works:**

1. DAG runner reaches a workflow step with an `agent_binding` field
2. Runner resolves all `depends_on` artifacts — confirms availability
3. Runner loads the agent definition from `agents.yaml` by name
4. Runner spawns the agent with:
   - Scoped tool access (per agent definition)
   - Input artifacts (per step declaration)
   - Behavioral instruction (from skill bound via `component: skill:<name>`)
5. Agent executes within its declared scope
6. Agent produces output artifact(s)
7. DAG runner validates artifact presence and format
8. If artifact missing or invalid: fail-closed halt
9. DAG advances to next step

**Properties:**
- Deterministic ordering (DAG edges)
- Auditable (artifact trail)
- Reproducible (same inputs produce same invocation)
- Fail-closed (missing artifact halts the DAG)

**How agents appear in workflow-steps.yaml:**

```yaml
- id: classify-claims
  layer: A_semantic_normalization
  component: skill:doc-truth-classification      # behavioral instruction
  agent_binding: claim-classification-agent       # primary executor
  purpose: >
    Classify every major claim as current-state, target-state,
    historical, or unverified.
  inputs:
    - governance_context
    - canonical_docs
  outputs:
    - claim_classification_map
  depends_on:
    - load-context
  reinforced_by_hook: role-matched-doc-guard
```

The `agent_binding` field signals the DAG runner to:
1. Load the agent definition from `agents.yaml` by matching `name`
2. Spawn it with the declared tool constraints and model
3. Pass the resolved input artifacts
4. Apply the skill instructions from the `component: skill:<name>` binding
5. Collect the output artifacts

### B. User-Triggered Invocation (NOT APPLICABLE)

With the removal of the placeholder `.claude/agents/*.md` files, there are currently no user-triggered agents in this system. All 14 agents are governance workflow agents invoked exclusively by the DAG runner.

**If user-triggered agents are needed in the future:**
- They must be defined in a separate mechanism (not `agents.yaml`)
- They must NOT produce governance artifacts
- They must NOT claim governance authority
- Hook reinforcement would not be active outside DAG context

---

## 6. Agent vs Skill vs Hook vs Subagent

| Dimension | Agent | Skill | Hook | Subagent |
|-----------|-------|-------|------|----------|
| **Nature** | Primary step executor with scoped context and tools | Behavioral instruction (LLM prompt) | Programmatic enforcement (shell script) | Escalation-only audit specialist |
| **Execution** | Multi-step LLM reasoning within constrained scope | Single-step reasoning guidance | Deterministic pass/block evaluation | Conditional dispatch on artifact field values |
| **Enforcement** | Tool constraints + artifact contracts + hook reinforcement | None — advisory only | Hard block or warn | Via escalation conditions |
| **Isolation** | Full context isolation (own agent instance) | Shared context (main conversation) | No LLM context (shell execution) | Partial isolation (subagent scope) |
| **Output** | Required workflow artifacts with declared schema | Shapes parent step's reasoning | Block signal or pass-through | Audit findings merged into `audit_summary` |
| **Invocation** | DAG runner via `agent_binding` (always) | Bound to step via `component: skill:<name>` | Trigger-based (Pre/PostToolUse, SubagentStop) | Conditional dispatch via `escalates_to` |
| **Lifecycle** | Defined in `agents.yaml` | Defined in `skills.yaml` + `.claude/skills/<name>.md` | Defined in `hooks.yaml` + `settings.json` | Defined in `subagents.yaml` |
| **Count** | 14 (one per skill-bound step) | 13 (one per governance concern) | 6 (enforcement points) | 8 (escalation targets) |
| **When to use** | Every skill-bound workflow step | When behavioral guidance is the concern | When a rule must be enforced deterministically | When a governance violation needs deep investigation |

### Decision tree: When to create what

```
Is this a primary workflow step executor?
  YES -> Agent (agents.yaml)
  NO  ->
    Is this a deterministic enforcement rule?
      YES -> Hook (hooks.yaml)
      NO  ->
        Is this behavioral reasoning guidance?
          YES -> Skill (skills.yaml)
          NO  ->
            Is this an escalation path for a specific violation?
              YES -> Subagent (subagents.yaml)
              NO  -> Not a governed component
```

---

## 7. Agent Integration into DAG Runner

### How agents bind to workflow steps

Agents are referenced via the `agent_binding` field in `workflow-steps.yaml`. This field is additive — it does not replace the existing `component` field:

```yaml
- id: <step_id>
  component: skill:<skill_name>           # WHAT behavioral instruction to follow
  agent_binding: <agent_name>             # WHO executes this step
  # ... remaining step fields unchanged
```

- The **`component`** field indicates the skill (behavioral instruction) or structural executor
- The **`agent_binding`** field indicates which agent implements the step

Steps WITHOUT `agent_binding` are structural steps executed by the DAG runner directly:
- `load-context` (component: constitution)
- `stage-gate-enforcement` (component: stage_gates)
- `runtime-guards-summary` (component: hooks)
- `pre-pr-governance-readiness` (component: hooks)

### Relationship between agents and skills

Agents consume skills. They do NOT replace them:

```
Workflow Step
  |-- component: skill:<name>     -> HOW to reason (behavioral instruction)
  +-- agent_binding: <name>       -> WHO executes (scoped unit)
```

- The **agent** provides: tool isolation, artifact production, failure handling, model selection
- The **skill** provides: domain-specific reasoning instructions
- The **hook** provides: post-execution structural enforcement

A skill without an agent binding executes in the main conversation context (legacy behavior).
An agent without a skill binding is a dispatcher (e.g., `audit-coordinator-agent`).

### How outputs become artifacts

1. Agent produces structured output conforming to its declared `produces` list
2. DAG runner captures output and registers it as the declared artifact ID
3. Downstream steps consume this artifact via their `inputs` list
4. Pre-PR gate checks artifact presence per `artifacts.yaml` contract
5. Artifacts are ephemeral per-run (not persisted to disk unless explicitly required)

---

## 8. Artifact Production Model

### Complete agent-to-artifact mapping

Each agent produces exactly the artifacts declared in both `agents.yaml` and `artifacts.yaml`:

| Agent | Layer | Produces | Consumed By |
|-------|-------|----------|-------------|
| `claim-classification-agent` | A | `claim_classification_map` | normalize-terminology, route-claims-by-role, phase-check, deep-audit, change-impact-audit |
| `terminology-normalization-agent` | A | `normalized_terminology_map` | route-claims-by-role |
| `role-citation-agent` | A | `role_citation_verdict` | phase-check, snapshot-contract-check, deep-audit, change-impact-audit |
| `build-sequence-agent` | B | `phase_alignment_status` | snapshot-contract-check, stage-gate-enforcement, deep-audit, change-impact-audit |
| `snapshot-contract-agent` | B | `contract_compliance_verdict` | stage-gate-enforcement, runtime-boundary-check, deep-audit |
| `runtime-boundary-agent` | C | `runtime_boundary_verdict` | adapter-schema-check, runtime-guards-summary, deep-audit |
| `adapter-schema-agent` | C | `adapter_schema_verdict` | runtime-guards-summary, deep-audit |
| `audit-coordinator-agent` | D | `audit_summary` | change-impact-audit, update-verification-matrix, update-verification-ledger |
| `change-impact-agent` | D | `change_impact_report`, `doc_update_plan` | rename-invariance-check, doc-code-sync-check, update-verification-matrix, update-verification-ledger |
| `rename-invariance-agent` | D | `invariance_verdict` | pre-pr-governance-readiness (conditional) |
| `doc-code-sync-agent` | D | `doc_code_sync_status` | update-verification-matrix, update-verification-ledger, pre-pr-governance-readiness |
| `verification-matrix-agent` | E | `verification_matrix_delta` | update-verification-ledger, pre-pr-governance-readiness |
| `verification-ledger-agent` | E | `verification_ledger_delta` | runtime-artifact-hygiene-check, pre-pr-governance-readiness |
| `artifact-hygiene-agent` | E | `artifact_hygiene_verdict` | pre-pr-governance-readiness |

### Artifact schema requirements

Each artifact MUST contain:

```json
{
  "artifact_id": "<declared_id>",
  "produced_by": "<agent_name>",
  "produced_at": "<ISO_8601_timestamp>",
  "workflow_run_id": "<run_id>",
  "status": "pass | fail | warn | inconclusive",
  "findings": [],
  "blocking_conditions_raised": []
}
```

### Integration with existing artifact contract

Agents produce the SAME artifacts already declared in `artifacts.yaml`. They do not introduce new artifact types. The three-way contract is:

- `artifacts.yaml` declares what must exist and which step produces it
- `agents.yaml` declares which agent executes that step and what it outputs
- `hooks.yaml` declares how the output is structurally enforced

---

## 9. Governance Constraints

### Agents MUST NOT:

| Prohibition | Rationale | Enforced By |
|------------|-----------|-------------|
| Assert planned components as implemented | CLAUDE.md Section 3.2 — planned components MUST NOT be described as existing (Layer-3 is not yet built) | `live-readiness-claim-blocker` hook |
| Bypass snapshot boundary | CLAUDE.md Section 6 — downstream MUST read ONLY from published snapshots | `snapshot-boundary-guard` hook |
| Bypass hooks | CLAUDE.md Section 15 — actions bypassing workflow enforcement are invalid | DAG runner enforcement |
| Generate execution logic | CLAUDE.md Section 9 — system is analysis-only | `live-readiness-claim-blocker` hook |
| Self-invoke other agents | Agents are DAG-controlled; no agent-to-agent direct calls | Agent invocation model |
| Run outside DAG for governance work | Non-DAG invocation produces non-binding output | `agent_binding` is DAG-only |
| Produce artifacts outside declared schema | Artifact contract is fixed per `agents.yaml` + `artifacts.yaml` | DAG runner artifact validation |
| Modify canonical documents without doc_update_plan | CLAUDE.md Section 11 — document update obligations | `pre-pr-governance-gate` hook |
| Use `INSERT OR REPLACE` | Code conventions — immutable observation rows | `adapter-schema-guard` hook |

### Agents MUST:

- Fail closed on missing input or invalid state
- Produce declared artifacts or halt
- Respect tool constraints in their definition
- Cite only role-matched canonical documents
- Classify all claims per the evidence model (CLAUDE.md Section 5)
- Use allowed language for planned components ("planned", "target architecture", "not yet implemented")

---

## 10. Complete Agent and Subagent Roster

### 10.1 Agents (14) — Primary Workflow Step Executors

Defined in `.claude/workflows/packages/agents.yaml`.

#### Layer A — Semantic Normalization (3 agents)

| # | Agent | Step | Skill | Model | Tools | Produces | Escalation Target |
|---|-------|------|-------|-------|-------|----------|-------------------|
| 1 | `claim-classification-agent` | classify-claims | doc-truth-classification | opus | Read, Grep, Glob | `claim_classification_map` | implementation-history-reconciler |
| 2 | `terminology-normalization-agent` | normalize-terminology | canonical-terminology-map | sonnet | Read, Grep, Glob | `normalized_terminology_map` | (none) |
| 3 | `role-citation-agent` | route-claims-by-role | role-matched-citation-check | sonnet | Read, Grep, Glob | `role_citation_verdict` | canonical-role-auditor |

#### Layer B — Architecture + Phase + Contract Gating (2 agents)

| # | Agent | Step | Skill | Model | Tools | Produces | Escalation Target |
|---|-------|------|-------|-------|-------|----------|-------------------|
| 4 | `build-sequence-agent` | phase-check | build-sequence-compliance-check | sonnet | Read, Grep, Glob | `phase_alignment_status` | architecture-sequence-auditor |
| 5 | `snapshot-contract-agent` | snapshot-contract-check | snapshot-contract-check | sonnet | Read, Grep, Glob | `contract_compliance_verdict` | snapshot-boundary-auditor |

#### Layer C — Runtime / Schema / Boundary Integrity (2 agents)

| # | Agent | Step | Skill | Model | Tools | Produces | Escalation Target |
|---|-------|------|-------|-------|-------|----------|-------------------|
| 6 | `runtime-boundary-agent` | runtime-boundary-check | snapshot-boundary-check | sonnet | Read, Grep, Glob, Bash | `runtime_boundary_verdict` | snapshot-boundary-auditor |
| 7 | `adapter-schema-agent` | adapter-schema-check | adapter-schema-review | sonnet | Read, Grep, Glob | `adapter_schema_verdict` | adapter-schema-guardian |

#### Layer D — Audit + Impact (4 agents)

| # | Agent | Step | Skill | Model | Tools | Produces | Escalation Target |
|---|-------|------|-------|-------|-------|----------|-------------------|
| 8 | `audit-coordinator-agent` | deep-audit | (none — dispatches subagents) | sonnet | Read, Grep, Glob | `audit_summary` | (dispatches 5 subagents) |
| 9 | `change-impact-agent` | change-impact-audit | change-impact-audit | opus | Read, Grep, Glob | `change_impact_report`, `doc_update_plan` | (none) |
| 10 | `rename-invariance-agent` | rename-invariance-check | rename-invariance-check | sonnet | Read, Grep, Glob | `invariance_verdict` | (none) |
| 11 | `doc-code-sync-agent` | doc-code-sync-check | doc-code-sync-rules | sonnet | Read, Grep, Glob, Bash | `doc_code_sync_status` | doc-code-sync-auditor, cross-doc-consistency-auditor |

#### Layer E — Verification + Hygiene + Release (3 agents)

| # | Agent | Step | Skill | Model | Tools | Produces | Escalation Target |
|---|-------|------|-------|-------|-------|----------|-------------------|
| 12 | `verification-matrix-agent` | update-verification-matrix | verification-matrix-update-method | sonnet | Read, Grep, Glob | `verification_matrix_delta` | verification-matrix-auditor |
| 13 | `verification-ledger-agent` | update-verification-ledger | verification-ledger-update | sonnet | Read, Grep, Glob | `verification_ledger_delta` | (none) |
| 14 | `artifact-hygiene-agent` | runtime-artifact-hygiene-check | runtime-artifact-hygiene-check | sonnet | Read, Grep, Glob, Bash | `artifact_hygiene_verdict` | (none) |

### 10.2 Subagents (8) — Escalation-Only Audit Specialists

Defined in `.claude/workflows/packages/subagents.yaml`. Unchanged.

| # | Subagent | Audit Lane | Triggered By Step | Trigger Condition |
|---|----------|------------|-------------------|-------------------|
| 1 | `cross-doc-consistency-auditor` | documentary_consistency | doc-code-sync-check | `doc_doc_conflict_detected` |
| 2 | `architecture-sequence-auditor` | phase_and_build_order | phase-check | `build_order_ambiguity_detected` |
| 3 | `verification-matrix-auditor` | verification_classification | update-verification-matrix | `classification_dispute_detected` |
| 4 | `implementation-history-reconciler` | historical_source_conflicts | classify-claims | `non_canonical_source_as_current_truth` |
| 5 | `doc-code-sync-auditor` | doc_runtime_alignment | doc-code-sync-check | `drift_detected` |
| 6 | `snapshot-boundary-auditor` | snapshot_boundary_integrity | snapshot-contract-check, runtime-boundary-check | `boundary_violation_suspected` |
| 7 | `adapter-schema-guardian` | adapter_schema_governance | adapter-schema-check | `registry_violation` or `schema_drift_detected` |
| 8 | `canonical-role-auditor` | canonical_role_enforcement | route-claims-by-role | `role_mismatch_for_strong_claim` or `readme_layer2_used_as_override` |

### 10.3 Steps Without Agent Binding (4 structural steps)

These steps are executed directly by the DAG runner or hook consolidation logic. They do not need agents:

| Step | Component | Reason No Agent Needed |
|------|-----------|----------------------|
| `load-context` | constitution | Structural load — reads CLAUDE.md and canonical docs |
| `stage-gate-enforcement` | stage_gates | Structural gate evaluation — checks phase status |
| `runtime-guards-summary` | hooks | Hook signal consolidation — no LLM reasoning needed |
| `pre-pr-governance-readiness` | hooks | Final gate check — synthesizes all layer outputs |

### 10.4 Exhaustive Coverage Verification

**Workflow steps: 18 total**
- 14 with `agent_binding` (all skill-bound steps)
- 4 structural steps (no agent needed)
- Coverage: **100%**

**Subagent escalation paths: 8 total**
- All 8 reachable via `escalates_to` conditions in workflow steps
- All 8 also reachable via `audit_dispatch` in the deep-audit step
- Coverage: **100%**

**Artifact production: 19 declared outputs**
- 17 produced by agents (via their bound steps)
- 2 produced by structural steps (`governance_context` by load-context, `pr_readiness_verdict` by pre-pr-governance-readiness)
- Coverage: **100%**

---

## 11. Open Decisions

### 11.1 Resolved: agent_binding vs component: agent:<name>

**Decision:** Use `agent_binding` as an additive field alongside the existing `component` field.

**Rationale:** This preserves existing `component: skill:<name>` semantics while cleanly adding agent execution. No changes to the existing component type system. The DAG compiler resolves both the skill (behavioral instruction) and the agent (executor) from the same step.

### 11.2 Resolved: One agent per step vs grouped agents

**Decision:** 1:1 agent-to-step binding. Each skill-bound step gets exactly one agent.

**Rationale:** Grouped agents (one agent covering multiple steps) create ambiguous failure boundaries. If the agent fails, which step failed? With 1:1 binding, failure is isolated to a single step. The DAG can report exactly which agent failed and which artifact is missing.

### 11.3 Resolved: Agent definition location

**Decision:** All agent definitions live in `agents.yaml` as a workflow package. No standalone `.md` files.

**Rationale:** The package model requires single-file section ownership. `agents.yaml` owns the `agents` section. Standalone files would create a parallel definition system that conflicts with the package assembly model.

### 11.4 Open: Should agents wrap skills or replace them?

**Current position:** Agents consume skills as behavioral instructions. Skills continue to exist as standalone components in `skills.yaml`.

**Risk of replacing:** Skills are lightweight and reusable. Merging them into agents reduces composability and forces behavioral changes to touch the agent definition.

**Risk of wrapping:** Two layers of indirection (step + agent + skill) may create confusion about where reasoning instructions live.

**Recommendation:** Maintain separation. Agent definitions specify scope, tools, and artifact contracts. Behavioral instructions live in skill definitions only.

### 11.5 Open: Should subagents ever converge into agents.yaml?

**Current position:** Subagents remain in `subagents.yaml` as a distinct concept.

**Possible future:** Subagents could be modeled as agents with `invocation_mode: escalation_only` in a unified `agents.yaml`.

**Risk of merging:** Different lifecycle (conditional dispatch vs. primary execution). Merging may conflate two distinct invocation semantics.

**Recommendation:** Keep separate for now. The distinction is load-bearing: agents always run for their bound step, subagents run only on violation. Revisit if the distinction becomes a source of confusion.

### 11.6 Open: Should agent execution become programmatic later?

**Current position:** Agents are LLM-executed (Claude subagent tool). DAG orchestration is structural (shell-mode YAML interpretation).

**Future possibility:** Agent execution could become programmatic if agent logic is simple enough to codify.

**Recommendation:** Defer. Current system complexity does not warrant programmatic agents. Revisit when governance workflow stabilizes.

### 11.7 Open: User-triggered operational agents

**Context:** The previous planner/implementer/reviewer agents in `.claude/agents/` have been removed. There are currently no user-triggered agents.

**Question:** Should user-triggered agents for Layer-2 operational work be reintroduced?

**If yes:** They must be defined in a separate mechanism (not `agents.yaml`), must not produce governance artifacts, and must not claim governance authority.

**Recommendation:** Defer until there is a demonstrated need. The existing skill-based workflow handles most operational tasks.

---

## 12. Implementation Plan

### Completed

1. **Created `agents.yaml`** — 14 agents defined with full schema
2. **Updated `system-orchestration.yaml`** — agents package added between subagents and artifacts; 3 new validation expectations added
3. **Updated `PACKAGE_MODEL.md`** — agents added to structure, loading order (position 8 of 14), section ownership, and DAG compiler notes
4. **Updated `execution-metadata.yaml`** — `agent_contract_version: "1.0"` added; note updated to describe agent/subagent distinction
5. **Updated `workflow-steps.yaml`** — `agent_binding` added to all 14 skill-bound steps; header comment updated; missing `escalates_to` added to snapshot-contract-check
6. **Removed placeholder files** — `.claude/agents/planner.md`, `implementer.md`, `reviewer.md` deleted
7. **Updated `candidate-agents.md`** — marked SUPERSEDED with pointer to `agents.yaml` and `subagents.yaml`

### Remaining

8. **Dry-run DAG validation**
   - Verify all `agent_binding` references resolve to `agents.yaml` entries
   - Verify all artifact producer/consumer relationships are consistent
   - Verify no cycles introduced by new `escalates_to` on snapshot-contract-check

9. **Verify hook reinforcement**
   - Confirm hooks read agent-produced artifacts correctly
   - Confirm `pre-pr-governance-gate` checks all 17 agent-produced artifacts in its `required_artifacts` list

10. **Governance workflow test**
    - Run the governance workflow on a no-op change
    - Confirm each agent produces its declared artifacts
    - Confirm hooks still enforce correctly
    - Confirm subagent escalation paths function

---

## 13. Risks

### 13.1 Agent drift from DAG control

**Risk:** Agents begin to be invoked outside DAG context for governance tasks, producing non-binding artifacts that are treated as authoritative.

**Mitigation:** All 14 agents are defined in `agents.yaml` and invoked only via `agent_binding` in workflow steps. There is no mechanism to invoke them outside the DAG. The `pre-pr-governance-gate` hook validates artifact presence.

### 13.2 Hidden Claude autonomy

**Risk:** An agent's LLM execution deviates from its skill binding, producing outputs that bypass governance constraints.

**Mitigation:** Hooks provide structural post-check. Agent output is validated against artifact schema. Tool constraints prevent agents from taking actions outside their declared scope. The agent is advisory; the hook is authoritative.

### 13.3 Duplication with skills

**Risk:** Agent definitions duplicate skill instructions, creating two sources of behavioral specification that may drift apart.

**Mitigation:** Agent definitions MUST NOT duplicate skill content. They specify scope, tools, and artifact contracts. Behavioral instructions live in skill definitions only. Agent entries reference skills via `skill_bindings`.

### 13.4 Artifact inconsistency

**Risk:** Agent-produced artifacts drift from the schema declared in `artifacts.yaml`, causing downstream consumption failures.

**Mitigation:** DAG runner validates artifact presence and format after each agent execution. Missing or malformed artifacts trigger fail-closed halt. Three new validation expectations enforce consistency.

### 13.5 Agent-subagent confusion

**Risk:** The distinction between agents (14 primary executors) and subagents (8 escalation specialists) may blur over time.

**Mitigation:** Separate YAML files (`agents.yaml` vs `subagents.yaml`). Clear decision tree in Section 6. Agents always run; subagents run only on violation conditions. The distinction is structural, not semantic.

### 13.6 Governance theatre

**Risk:** Agents produce passing verdicts without meaningful analysis, creating a false sense of compliance.

**Mitigation:** Verification ledger tracks claim to evidence to status. `doc-only updates do not prove runtime` rule (from `verification-ledger.yaml`) prevents documentation-only validation from being treated as proof. Deep audit subagents provide secondary validation.

### 13.7 Package loading order sensitivity

**Risk:** Agents load at position 8 (after skills and subagents, before artifacts). If the DAG compiler resolves references during load rather than after full assembly, agents may not see all required references.

**Mitigation:** Per PACKAGE_MODEL.md, reference resolution happens during validation (step 4 of assembly), not during loading (step 2-3). The loading order ensures reproducibility but does not affect reference resolution.

---

## 14. Mandatory Source Reading Order

Before implementing any agent file in `.claude/agents/`, the implementer MUST read the following sources in the order specified. No agent implementation may proceed from memory or cached understanding alone.

### 14.1 Constitutional Authority (read first)

| Priority | File | Why Mandatory |
|----------|------|---------------|
| 1 | `CLAUDE.md` | Defines all interpretive rules, evidence model, phase gates, snapshot contract, execution boundary, and claim discipline. Every agent constraint traces here. |
| 2 | `.claude/rules/code-conventions.md` | Database discipline, snapshot determinism, registry authority. Applies to any agent touching code context. |
| 3 | `.claude/rules/git-workflow.md` | Branching and commit scope rules. Applies to any agent-produced doc_update_plan or code changes. |

### 14.2 Execution Model Authority (read second)

| Priority | File | Why Mandatory |
|----------|------|---------------|
| 4 | `.claude/workflows/system-orchestration.yaml` | Authoritative execution entrypoint. Defines assembly model, package order, validation expectations. Every agent must operate within this compiled spec. |
| 5 | `.claude/workflows/PACKAGE_MODEL.md` | Package loading order, section ownership, DAG compiler notes. Defines how agents.yaml integrates. |
| 6 | `.claude/workflows/packages/workflow-steps.yaml` | All 18 DAG steps with `agent_binding`, `component`, `depends_on`, `escalates_to`. The primary binding target for agents. |

### 14.3 Artifact Authority (read third)

| Priority | File | Why Mandatory |
|----------|------|---------------|
| 7 | `.claude/workflows/packages/artifacts.yaml` | Declares all required inputs, expected outputs, and producer ownership. Agent `produces` lists must be subsets. |
| 8 | `.claude/workflows/packages/hooks.yaml` | Hook enforcement points. Agents must know which hooks reinforce their outputs. |
| 9 | `.claude/workflows/packages/blocking-conditions.yaml` | Blocking conditions agents may raise. No agent may raise an undeclared condition. |

### 14.4 Workflow Binding Authority (read fourth)

| Priority | File | Why Mandatory |
|----------|------|---------------|
| 10 | `.claude/workflows/packages/agents.yaml` | Authoritative agent definitions. Every `.claude/agents/<name>.md` file must faithfully implement the contract declared here. |
| 11 | `.claude/workflows/packages/subagents.yaml` | Escalation targets. Agents must know their escalation paths but must NOT duplicate subagent behavior. |
| 12 | `.claude/workflows/packages/stage-gates.yaml` | Phase gate definitions. Agents must respect phase boundaries. |
| 13 | `.claude/workflows/packages/predicates.yaml` | Scope predicates. Agents with `activation_predicate` must understand the predicate contract. |

### 14.5 Skill Authority (read fifth)

| Priority | File | Why Mandatory |
|----------|------|---------------|
| 14 | `.claude/workflows/packages/skills.yaml` | Skill inventory with step/artifact bindings. Agents consume skills — they must not duplicate or contradict skill instructions. |
| 15 | `.claude/skills/<skill_name>.md` (each bound skill) | Actual behavioral instruction content. Agent files must reference, not replicate, this content. |

### 14.6 Canonical Documentation (consult as needed)

| File | When to Consult |
|------|-----------------|
| `Documentation/SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | When agent scope touches architecture boundaries, phase gates, or layer contracts |
| `Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md` | When agent scope touches implementation state claims |
| `Documentation/SYSTEM_TECHNICAL_HANDBOOK_v1.md` | When agent scope touches engineering invariants or adapter discipline |
| `Documentation/SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | When agent scope touches known limitations |
| `Documentation/README_LAYER2.md` | When agent scope touches collaborator workflow or Layer-2 navigation |
| `Documentation/DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | When agent scope touches verification classification |

---

## 15. Mandatory Re-Validation Rule

The source reading order in Section 14 is not a one-time activity. Sources MUST be re-consulted whenever implementation decisions are made about:

| Decision Type | Must Re-Read |
|--------------|-------------|
| Agent scope definition | CLAUDE.md (Section 13 — LLM role constraint), agents.yaml entry, bound workflow step |
| Allowed inputs | workflow-steps.yaml `inputs` for the bound step, artifacts.yaml `required_inputs` |
| Artifact outputs | artifacts.yaml `expected_outputs`, agents.yaml `produces`, hooks.yaml (reinforcing hook) |
| Step binding | workflow-steps.yaml `agent_binding` field, PACKAGE_MODEL.md (DAG compiler notes) |
| Escalation behavior | subagents.yaml, workflow-steps.yaml `escalates_to`, agents.yaml `escalation_targets` |
| Hook reinforcement | hooks.yaml entry for `reinforced_by_hook`, blocking-conditions.yaml |
| Canonical authority references | CLAUDE.md Section 2 (document authority), interpretation-policy.yaml |
| Failure mode definition | CLAUDE.md Section 7 (fail-closed principle), agents.yaml `failure_mode` |
| Tool constraint decisions | agents.yaml `tools`, CLAUDE.md Section 9 (execution boundary) |

**Rule:** If an implementation decision is made without re-consulting the relevant source, the decision is non-binding and must be re-verified before the agent file is considered complete.

---

## 16. Objectives and Outputs of the Agent Implementation Process

### 16.1 Goal

"Agent implementation" in this repository means: creating `.claude/agents/<agent_name>.md` files that serve as the concrete realization of the agent contracts declared in `agents.yaml`. Each file provides the full behavioral specification that the DAG runner (or, in shell-mode, the skill-based workflow) uses to instantiate a governed execution unit for a specific workflow step.

Agent implementation does NOT mean:
- building a DAG runner
- creating runtime agent infrastructure
- modifying the workflow YAML packages
- changing hook enforcement logic

### 16.2 Expected Outputs

The agent implementation process must produce exactly the following:

| Output | Location | Description |
|--------|----------|-------------|
| Agent files | `.claude/agents/<agent_name>.md` | One file per declared agent in `agents.yaml`. 14 files total. |
| Binding confirmation | Appendix to this plan or standalone checklist | Confirmation that every `agent_binding` in workflow-steps.yaml resolves to a created agent file |
| Artifact ownership confirmation | Appendix to this plan or standalone checklist | Confirmation that every agent's `produces` list matches artifacts.yaml declarations |
| Validation checklist (completed) | Section 20 of this plan | All checklist items passed |

The implementation process must NOT produce:
- New YAML package files
- New skill definitions
- New hook definitions
- New artifact types not declared in artifacts.yaml
- Modifications to system-orchestration.yaml
- Subagent `.md` files (subagents are defined solely in subagents.yaml)

### 16.3 Agent File Purpose

Each `.claude/agents/<name>.md` file serves as:
- The behavioral contract for the Agent tool invocation
- The scoped instruction set loaded when the DAG runner spawns this agent
- The explicit authority, constraint, and artifact production specification

It does NOT serve as:
- A replacement for the skill instruction (skills provide reasoning guidance; the agent file provides scope and contract)
- A replacement for the YAML definition (agents.yaml remains authoritative for schema fields)
- A standalone executable (agents are always invoked within DAG or workflow context)

---

## 17. Non-Goals and Forbidden Moves

The following are explicitly forbidden during agent file implementation. Violations of any item below render the implementation invalid.

### 17.1 Structural Prohibitions

| # | Forbidden Action | Rationale |
|---|-----------------|-----------|
| 1 | Autonomous orchestration outside DAG | Agents are DAG-controlled. No agent may self-schedule, self-invoke, or bypass `depends_on` ordering. |
| 2 | Bypassing hooks | CLAUDE.md Section 15. Hook enforcement is non-negotiable. No agent may instruct or imply that hook checks can be skipped. |
| 3 | Weakening constitutional rules | CLAUDE.md is the highest-priority interpretive authority. No agent file may soften, reinterpret, or override constitutional constraints. |
| 4 | Creating fake canonical authority | No agent may claim a non-canonical document as current-state truth. CLAUDE.md Section 2.3. |
| 5 | Implying Layer-3 implementation | Layer-3 is planned, not built. CLAUDE.md Sections 3.2 and 10. No agent may describe Layer-3 components as existing. |
| 6 | Modifying scheduler/DAG contracts | system-orchestration.yaml and workflow-steps.yaml define the execution contract. Agent files must conform, not modify. |
| 7 | Inventing artifact paths not in artifacts.yaml | Every artifact an agent references must exist in artifacts.yaml. No invented or ad-hoc artifacts. |
| 8 | Collapsing agents and subagents | Agents are primary executors; subagents are escalation-only. An agent file must not incorporate subagent audit behavior as primary execution. |

### 17.2 Content Prohibitions

| # | Forbidden Content | Rationale |
|---|------------------|-----------|
| 9 | Duplicated skill instructions | Agent files reference skills; they do not copy or paraphrase skill content. Risk 13.3 (duplication drift). |
| 10 | Hardcoded series logic | CLAUDE.md Section 8. series_registry.json is authoritative. |
| 11 | `INSERT OR REPLACE` patterns | Code conventions. Immutable observation rows. |
| 12 | Execution or trading language | CLAUDE.md Section 9. System is analysis-only. |
| 13 | Strong claims without evidence | CLAUDE.md Section 10. Forbidden unless explicitly proven. |
| 14 | User-invocation instructions | Section 5.B of this plan. All 14 agents are DAG-invoked only. No user-trigger metadata. |

### 17.3 Process Prohibitions

| # | Forbidden Process | Rationale |
|---|------------------|-----------|
| 15 | Creating agent files without reading agents.yaml | Section 14 mandatory source reading order. |
| 16 | Creating undeclared agent files | Only agents declared in agents.yaml get `.md` files. No extras. |
| 17 | Skipping binding validation | Every `agent_binding` must resolve. Section 19 Step 6. |
| 18 | Bulk generation without per-agent review | Each agent file must be individually validated against its YAML contract. |

---

## 18. Implementation Sequence

This section defines the concrete step-by-step procedure for creating `.claude/agents/<name>.md` files. Steps must be executed in order. No step may be skipped.

### Step 1 — Initialize Implementation Context

**Purpose:** Confirm all prerequisite sources exist and are internally consistent.

**Actions:**
1. Confirm all files listed in Section 14 exist and are readable
2. Confirm `agents.yaml` declares exactly 14 agents
3. Confirm `subagents.yaml` declares exactly 8 subagents
4. Confirm `workflow-steps.yaml` contains `agent_binding` on exactly 14 steps
5. Confirm `artifacts.yaml` lists exactly 19 expected outputs
6. Confirm `system-orchestration.yaml` contains the three agent-related validation expectations
7. Confirm `.claude/agents/` directory exists (create if not)

**Gate:** Proceed only if all 7 confirmations pass. Any failure halts implementation.

### Step 2 — Build Implementation Mapping

**Purpose:** Create a complete cross-reference table before writing any agent file.

**Actions:**
For every agent declared in `agents.yaml`, resolve and record:

| Field | Source |
|-------|--------|
| Agent name | agents.yaml `name` |
| Bound workflow step | agents.yaml `workflow_steps` → verify against workflow-steps.yaml `agent_binding` |
| Bound skill | agents.yaml `skill_bindings` → verify against skills.yaml `name` |
| Produced artifacts | agents.yaml `produces` → verify against artifacts.yaml `expected_outputs` |
| Consumed artifacts | agents.yaml `consumes` → verify against workflow-steps.yaml `inputs` |
| Hook reinforcement | agents.yaml `hook_reinforcement` → verify against hooks.yaml `name` |
| Escalation targets | agents.yaml `escalation_targets` → verify against subagents.yaml `name` |
| Canonical authority sources | Derived from workflow step `inputs` that reference `Documentation/*` |
| Failure mode | agents.yaml `failure_mode` |
| Model | agents.yaml `model` |
| Tools | agents.yaml `tools` |
| Activation predicate | agents.yaml `activation_predicate` (if present) → verify against predicates.yaml |

**Gate:** The mapping must cover all 14 agents with zero unresolved references. Any unresolved reference halts implementation for that agent.

### Step 3 — Define Agent File Schema

**Purpose:** Establish the exact structure each `.claude/agents/<name>.md` file must follow.

**Required frontmatter:**

```yaml
---
name: <agent_name>                    # must match agents.yaml name
description: <one-line purpose>       # derived from agents.yaml purpose
model: <opus | sonnet>                # must match agents.yaml model
tools: <tool_list>                    # must match agents.yaml tools
---
```

**Required body sections:**

```markdown
# <Agent Display Name>

## Role
<functional role — derived from agents.yaml role>

## Bound Workflow Step
<step ID from agents.yaml workflow_steps>

## Skill Binding
<skill name(s) from agents.yaml skill_bindings — reference only, do not duplicate content>

## Authority Sources
<canonical documents this agent must consult, derived from workflow step inputs>

## Inputs
<artifacts and documents consumed — must match workflow-steps.yaml inputs for bound step>

## Required Outputs
<artifacts produced — must match agents.yaml produces and artifacts.yaml>

## Constraints
<governance constraints from CLAUDE.md, specific to this agent's scope>

## Failure Mode
<from agents.yaml failure_mode>

## Escalation
<escalation targets and conditions from agents.yaml escalation_targets, or "None">

## Hook Reinforcement
<hook name from agents.yaml hook_reinforcement, or "None">
```

**What does NOT belong in the agent file:**
- Skill reasoning instructions (live in `.claude/skills/<name>.md`)
- YAML schema fields already in agents.yaml (the file implements, not re-declares)
- General CLAUDE.md content not specific to this agent
- Implementation code or scripts

### Step 4 — Scaffold Agent Files

**Purpose:** Create all 14 agent files with correct names and empty structure.

**Actions:**
1. For each agent in agents.yaml, create `.claude/agents/<agent_name>.md`
2. File naming: use the exact `name` field from agents.yaml (e.g., `claim-classification-agent.md`)
3. Populate frontmatter from the Step 2 mapping
4. Insert section headers from the Step 3 schema with placeholder markers

**Rules:**
- No agent file may be created for a name not in agents.yaml
- No agent declared in agents.yaml may be missing a file
- No subagent gets a file (subagents are defined only in subagents.yaml)

**Expected file list (14 files):**

```
.claude/agents/
  claim-classification-agent.md
  terminology-normalization-agent.md
  role-citation-agent.md
  build-sequence-agent.md
  snapshot-contract-agent.md
  runtime-boundary-agent.md
  adapter-schema-agent.md
  audit-coordinator-agent.md
  change-impact-agent.md
  rename-invariance-agent.md
  doc-code-sync-agent.md
  verification-matrix-agent.md
  verification-ledger-agent.md
  artifact-hygiene-agent.md
```

### Step 5 — Fill Agent Contracts

**Purpose:** Complete each agent file with its full behavioral contract.

**Per-agent procedure:**
1. Re-read the agents.yaml entry for this agent (Section 15 re-validation rule)
2. Re-read the bound workflow step in workflow-steps.yaml
3. Re-read the bound skill in skills.yaml (if any)
4. Fill each section from the Step 3 schema using the Step 2 mapping
5. For the Constraints section: derive agent-specific constraints from CLAUDE.md rules that apply to this agent's scope (e.g., snapshot agents must cite Section 6; claim agents must cite Section 5)
6. For the Authority Sources section: list only canonical documents referenced in the workflow step's `inputs` field
7. Verify the completed file against agents.yaml — no contradictions allowed

**Layer-by-layer execution order:**

| Order | Layer | Agents |
|-------|-------|--------|
| 1 | A (Semantic Normalization) | claim-classification-agent, terminology-normalization-agent, role-citation-agent |
| 2 | B (Architecture + Phase + Contract) | build-sequence-agent, snapshot-contract-agent |
| 3 | C (Runtime + Schema Integrity) | runtime-boundary-agent, adapter-schema-agent |
| 4 | D (Audit + Impact) | audit-coordinator-agent, change-impact-agent, rename-invariance-agent, doc-code-sync-agent |
| 5 | E (Verification + Hygiene) | verification-matrix-agent, verification-ledger-agent, artifact-hygiene-agent |

**Rationale for layer order:** Earlier-layer agents have simpler dependency chains. Completing them first builds familiarity with the pattern before tackling the more complex D/E layer agents.

### Step 6 — Validate Binding Resolution

**Purpose:** Confirm every agent_binding in the workflow resolves and no orphan files exist.

**Checks:**
1. For each `agent_binding: <name>` in workflow-steps.yaml:
   - Confirm `<name>` matches an entry in agents.yaml
   - Confirm `.claude/agents/<name>.md` exists
   - Confirm the agent file's frontmatter `name` matches
2. For each `.claude/agents/*.md` file:
   - Confirm its `name` appears in agents.yaml
   - Confirm it is referenced by exactly one `agent_binding` in workflow-steps.yaml
3. No duplicate agent identities across files
4. No orphan agent files (files without a corresponding agents.yaml entry)

**Gate:** All bindings resolve. Zero orphans. Zero duplicates.

### Step 7 — Validate Artifact Ownership

**Purpose:** Confirm agent-produced artifacts align with declared contracts.

**Checks:**
1. For each agent file's Required Outputs section:
   - Every listed artifact appears in artifacts.yaml `expected_outputs`
   - The `produced_by` step in artifacts.yaml matches the agent's bound workflow step
   - The artifact appears in agents.yaml `produces` for this agent
2. No agent file claims to produce an artifact not in artifacts.yaml
3. No artifact in artifacts.yaml produced by an agent-bound step is missing from the corresponding agent file
4. Cross-check: agents.yaml `produces` == agent file `Required Outputs` == artifacts.yaml `produced_by` for the bound step

**Gate:** Three-way artifact contract consistency confirmed for all 14 agents.

### Step 8 — Validate Subagent References

**Purpose:** Confirm escalation paths are correctly represented without role confusion.

**Checks:**
1. For each agent file with an Escalation section:
   - Every named subagent exists in subagents.yaml
   - The escalation condition matches agents.yaml `escalation_targets` and workflow-steps.yaml `escalates_to`
   - The agent file does not describe performing the subagent's audit work
2. Agents with no escalation targets correctly state "None"
3. No agent file lists a subagent not declared in subagents.yaml
4. No subagent is treated as a primary step executor in any agent file

**Gate:** All escalation references valid. No agent-subagent role confusion.

### Step 9 — Run Structural Verification

**Purpose:** Confirm the assembled workflow remains valid after agent file creation.

**Checks:**
1. Re-run the validation expectations from system-orchestration.yaml conceptually:
   - `every_agent_binding_resolves_to_declared_agent` — still passes
   - `every_agent_produces_declared_artifacts_only` — still passes
   - `every_agent_skill_binding_resolves_to_declared_skill` — still passes
2. Verify no new files introduced cycles or package inconsistencies
3. Verify `.claude/agents/` contains exactly 14 files (no more, no less)
4. Verify no YAML package was modified during agent file creation

**Gate:** Structural verification passes. No regressions.

### Step 10 — Governance No-Op Verification

**Purpose:** Perform a dry-run governance pass to confirm agents are structurally accounted for.

**Actions:**
1. Walk the workflow DAG from `load-context` through `pre-pr-governance-readiness`
2. At each agent-bound step, confirm:
   - The agent file exists
   - The agent file's inputs match the step's inputs
   - The agent file's outputs match the step's outputs
   - The agent file's hook reinforcement matches the step's `reinforced_by_hook`
3. Confirm hooks can still read agent-produced artifacts (hooks.yaml `reads_artifacts` matches agent `produces`)
4. Confirm the pre-PR gate's `required_artifacts` list is fully covered by agent-produced artifacts plus structural step outputs

**Gate:** Full DAG walk completes. All 18 steps accounted for. All 19 artifacts traceable.

---

## 19. Completion Criteria

Agent implementation is considered **complete** when ALL of the following conditions are met:

### 19.1 File Completeness

- [ ] Every agent declared in agents.yaml has a corresponding `.claude/agents/<name>.md` file
- [ ] Every `.claude/agents/<name>.md` file has a corresponding entry in agents.yaml
- [ ] No undeclared agent files exist in `.claude/agents/`
- [ ] Exactly 14 agent files exist

### 19.2 Binding Resolution

- [ ] Every `agent_binding` in workflow-steps.yaml resolves to an existing agent file
- [ ] Every agent file's `name` frontmatter matches its agents.yaml entry
- [ ] No duplicate agent identities

### 19.3 Artifact Contract Alignment

- [ ] Every agent file's Required Outputs section matches agents.yaml `produces`
- [ ] Every agent's `produces` list is a subset of artifacts.yaml `expected_outputs`
- [ ] Three-way consistency: agent file ↔ agents.yaml ↔ artifacts.yaml

### 19.4 Escalation Integrity

- [ ] All escalation targets in agent files exist in subagents.yaml
- [ ] No agent performs subagent audit work
- [ ] Agents without escalation targets correctly declare "None"

### 19.5 Hook Compatibility

- [ ] Hook reinforcement fields in agent files match agents.yaml and hooks.yaml
- [ ] Hooks can read artifacts produced by their reinforced agents
- [ ] pre-pr-governance-gate artifact list remains fully covered

### 19.6 Constitutional Compliance

- [ ] No agent file weakens CLAUDE.md constraints
- [ ] No agent file implies Layer-3 is implemented
- [ ] No agent file contains execution or trading language
- [ ] No agent file makes strong claims without evidence
- [ ] All agent files respect the fail-closed principle

### 19.7 No False Claims Introduced

- [ ] No agent file describes a capability the system does not have
- [ ] No agent file references a component that does not exist
- [ ] No agent file claims production readiness or external validation

---

## 20. Validation Checklist

This checklist is designed for use during and after agent implementation. Each item must be explicitly confirmed.

### Source Verification

- [ ] All files in Section 14 source reading order were read before implementation began
- [ ] agents.yaml was re-consulted for every agent file written (Section 15)
- [ ] workflow-steps.yaml was re-consulted for every step binding
- [ ] No agent file was written from memory alone

### Binding Verification

- [ ] 14 agent files exist in `.claude/agents/`
- [ ] 14 `agent_binding` fields in workflow-steps.yaml resolve
- [ ] 0 orphan files in `.claude/agents/`
- [ ] 0 missing files for declared agents

### Artifact Verification

- [ ] Every agent `produces` list matches artifacts.yaml `expected_outputs`
- [ ] No agent produces an artifact not declared in artifacts.yaml
- [ ] No artifact declared as agent-produced is missing from an agent file

### Escalation Verification

- [ ] Every subagent reference resolves to subagents.yaml
- [ ] No agent incorporates subagent audit behavior
- [ ] audit-coordinator-agent correctly references 5 dispatch targets

### Authority Verification

- [ ] Every agent file cites only role-matched canonical documents
- [ ] No agent file uses README_LAYER2 to override role-specific sources
- [ ] No agent file creates new canonical authority claims

### Hook Compatibility Verification

- [ ] 5 hook-reinforced agents correctly declare their hook
- [ ] 9 non-hook-reinforced agents correctly declare "None"
- [ ] Hook `reads_artifacts` are producible by agent `produces`

### No-Overclaim Verification

- [ ] No "Layer 3 is implemented" language
- [ ] No "system is production-ready" language
- [ ] No "execution is available" language
- [ ] No "decisions are automated" language
- [ ] No "system is externally validated" language
- [ ] All planned components use "planned", "target architecture", or "not yet implemented" language

### Structural Verification

- [ ] No YAML packages were modified during implementation
- [ ] No new artifact types were introduced
- [ ] No new skill definitions were created
- [ ] No new hook definitions were added
- [ ] DAG walk completes from load-context through pre-pr-governance-readiness

---

## Appendix A: Component Binding Summary

```
workflow-steps.yaml step
  |
  |-- component: skill:<name>
  |     +-- resolves to: skills.yaml entry + .claude/skills/<name>.md
  |           +-- provides: behavioral reasoning instructions
  |
  |-- agent_binding: <agent_name>
  |     +-- resolves to: agents.yaml entry
  |           |-- tools: [constrained tool list]
  |           |-- model: [opus | sonnet]
  |           +-- produces: [artifact declarations]
  |
  |-- reinforced_by_hook: <hook_name>
  |     +-- resolves to: hooks.yaml entry
  |           +-- enforces: structural post-check on agent output
  |
  +-- escalates_to: [subagent conditions]
        +-- resolves to: subagents.yaml entries
              +-- dispatches: deep audit on governance violation
```

## Appendix B: Artifact Flow Diagram

```
Layer A (Semantic Normalization)
  claim-classification-agent
    -> claim_classification_map
  terminology-normalization-agent
    -> normalized_terminology_map
  role-citation-agent
    -> role_citation_verdict

Layer B (Architecture + Phase Gating)
  build-sequence-agent
    -> phase_alignment_status
  snapshot-contract-agent
    -> contract_compliance_verdict
  [structural] stage-gate-enforcement
    -> stage_gate_report

Layer C (Runtime + Schema Integrity)
  runtime-boundary-agent
    -> runtime_boundary_verdict
  adapter-schema-agent
    -> adapter_schema_verdict
  [structural] runtime-guards-summary
    -> guard_report

Layer D (Audit + Impact)
  audit-coordinator-agent (dispatches subagents)
    -> audit_summary
  change-impact-agent
    -> change_impact_report, doc_update_plan
  rename-invariance-agent (conditional: rename_only_change)
    -> invariance_verdict
  doc-code-sync-agent
    -> doc_code_sync_status

Layer E (Verification + Release)
  verification-matrix-agent
    -> verification_matrix_delta
  verification-ledger-agent
    -> verification_ledger_delta
  artifact-hygiene-agent
    -> artifact_hygiene_verdict
  [structural] pre-pr-governance-readiness
    -> pr_readiness_verdict
```

## Appendix C: Validation Expectations (New)

Three new validation expectations were added to `system-orchestration.yaml`:

1. `every_agent_binding_resolves_to_declared_agent` — Every `agent_binding` field in workflow-steps.yaml must match a `name` in agents.yaml
2. `every_agent_produces_declared_artifacts_only` — Agent `produces` lists must be a subset of `artifacts.yaml` expected outputs
3. `every_agent_skill_binding_resolves_to_declared_skill` — Agent `skill_bindings` must match entries in skills.yaml

---

> **This plan is structurally aligned with the Mr. Ripley repository.**
> **It is reproducible, auditable, and keeps the DAG as the control plane.**
> **Agents and subagents are now clearly separated with distinct definitions and invocation models.**
