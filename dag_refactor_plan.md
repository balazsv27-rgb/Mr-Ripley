# DAG Runner V2 Refactor Plan

## Context

The governance DAG runner (`governance/dag_runner/`, 14 modules, ~3,732 lines, 204 tests) currently executes in **V1 shell mode** — it loads, validates, plans, and walks the 18-step DAG, but does not invoke real agents/skills. All artifacts are placeholders. Only 3 of 19 artifacts exist on disk (written by hooks, not the runner). The "ready" verdict is structurally valid but semantically misleading.

This plan specifies the refactor to V2 in two milestones:
- **V2A** — deterministic governance runtime (no real Claude invocation; mocked execution backend)
- **V2B** — live agent execution (pluggable Claude backends, subagent dispatch, timeout/retry)

**Constraint:** YAML packages are the spec — they are NOT modified. All changes are in `governance/dag_runner/` Python code.

---

## Milestone Structure

### V2A — Deterministic Governance Runtime
Phases 1-6 below. Delivers:
- Agents parsed, structured, and validated
- Execution backend interface with `MockExecutionBackend`
- Component-kind-driven dispatch (not step-name-driven)
- Dry-run / graph / JSON / continuation modes
- Strict continuation guardrails
- Prompt assembly pipeline
- Real artifact envelopes (hook-compatible canonical format)
- Drift detection as a pre-execution validation gate
- Diagnostics and observability
- All execution via `MockExecutionBackend` — no real Claude invocation

### V2B — Live Agent Execution
Phase 7 below. Delivers:
- `ClaudeCLIBackend` and `NativeClaudeBackend` implementations
- Timeout, retry, error classification
- Schema-aware output validation
- Subagent dispatch and escalation
- Two-tier gate architecture (hard + soft)

---

## Phase 1: Structural Foundation

**Goal:** Add new types, agent parsing, execution backend interface, and validation — without changing any existing behavior. All 204 tests must pass after every step.

### 1.1 Extend `models.py` with new types

Add the following dataclasses (all with defaults for backwards compat):

```python
@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str | None = None
    layer: str | None = None
    model: str = "sonnet"
    tools: list[str] = field(default_factory=list)
    workflow_steps: list[str] = field(default_factory=list)
    skill_bindings: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    hook_reinforcement: str | None = None
    escalation_targets: list[dict[str, Any]] = field(default_factory=list)
    failure_mode: str | None = None
    activation_predicate: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

# Component kinds — the execution dispatch discriminator
ComponentKind = Literal[
    "constitution", "stage_gates", "hooks", "subagents",
    "skill", "stage_gate", "hook", "subagent",
    "final_gate", "blocking_evaluator", "verification_update",
    "artifact_gate", "predicate_gate", "workflow_step",
]

ExecutionMode = Literal["shell_v1", "dry_run", "agent_execution", "graph_only"]

@dataclass(frozen=True)
class ExecutionConfig:
    mode: ExecutionMode = "shell_v1"
    json_output: bool = False
    timeout_per_step_ms: int = 120_000
    timeout_total_ms: int = 1_800_000
    continue_from: str | None = None
    phase_scope: str | None = None
    state_bootstrap_path: str | None = None

@dataclass(frozen=True)
class PromptAssemblyContext:
    agent_spec: AgentSpec
    skill_content: str
    artifact_inputs: dict[str, dict[str, Any]]
    document_paths: list[str]
    token_budget: int = 100_000
    truncated: bool = False

@dataclass(frozen=True)
class ArtifactEnvelope:
    """Canonical artifact envelope — the ONE write format for V2.
    Must match .claude/hooks/lib/artifact_store.py exactly."""
    artifact: str
    produced_by: str
    session: str
    timestamp: str
    data: dict[str, Any]

@dataclass(frozen=True)
class FailureClassification:
    origin: Literal["structural", "contract", "runtime", "artifact", "timeout"]
    step_id: str
    detail: str
    recoverable: bool = False

@dataclass(frozen=True)
class AgentExecutionResult:
    success: bool
    artifacts_produced: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw_output: str = ""
    failure: FailureClassification | None = None
    latency_ms: float = 0.0
    token_count: int = 0
```

Extend `AssembledWorkflowSpec` — add `agents: dict[str, AgentSpec] = field(default_factory=dict)`.

Extend `NodeResult` — add optional `latency_ms: float = 0.0`, `token_count: int = 0`.

### 1.2 Extend `assembler.py` — parse agents

Add `_assemble_agents()` that reads agents.yaml `data` section (list of agent dicts) into `dict[str, AgentSpec]`. The agents.yaml package is already loaded into `raw_sections` but currently unstructured.

Wire into `assemble_workflow_spec()` → populate `spec.agents`.

### 1.3 Extend `validator.py` — 5 new checks

These match the `validation_expectations` declared in `system-orchestration.yaml`:

| Check | Code | Description |
|-------|------|-------------|
| `_validate_agent_bindings()` | `unknown_agent_binding` | Every step with `agent_binding` in `step.raw` resolves to `spec.agents` |
| `_validate_agent_skill_bindings()` | `unknown_agent_skill_binding` | Every agent `skill_bindings` entry resolves to `spec.skills` |
| `_validate_agent_artifact_production()` | `agent_produces_undeclared_artifact` | Every agent `produces` entry exists in `spec.artifacts` |
| `_validate_hook_reinforcements()` | `unknown_hook_reinforcement` | Every step `reinforced_by_hook` in `step.raw` resolves to `spec.hooks` |
| `_validate_escalation_targets()` | `unknown_escalation_target` | Every `escalates_to[].subagent` in step/agent resolves to `spec.subagents` |

### 1.4 Execution backend interface — `execution_backend.py`

Define the pluggable execution adapter that the executor depends on:

```python
from abc import ABC, abstractmethod

class ExecutionBackend(ABC):
    """Interface for step execution. Executor depends on this, not on Claude."""

    @abstractmethod
    def execute_step(
        self,
        prompt: PromptAssemblyContext,
        step: WorkflowStep,
        agent: AgentSpec,
        config: ExecutionConfig,
    ) -> AgentExecutionResult:
        ...

    @abstractmethod
    def execute_structural_step(
        self,
        step: WorkflowStep,
        component_kind: ComponentKind,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
    ) -> AgentExecutionResult:
        ...


class MockExecutionBackend(ExecutionBackend):
    """V2A default — produces deterministic artifact payloads without Claude invocation."""

    def __init__(self, artifact_payloads: dict[str, dict[str, Any]] | None = None):
        self._payloads = artifact_payloads or {}

    def execute_step(self, prompt, step, agent, config) -> AgentExecutionResult:
        artifacts = {}
        for output_name in step.outputs:
            artifacts[output_name] = self._payloads.get(output_name, {"produced_by": step.name})
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)

    def execute_structural_step(self, step, component_kind, run_state, spec) -> AgentExecutionResult:
        # Deterministic structural logic — no LLM
        artifacts = {}
        for output_name in step.outputs:
            artifacts[output_name] = self._build_structural_output(step, component_kind, run_state, spec, output_name)
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)
```

### 1.5 New module: `agent_resolver.py` (~150 lines)

```python
def resolve_agent(step: WorkflowStep, spec: AssembledWorkflowSpec) -> AgentSpec | None
def resolve_skill_content(agent: AgentSpec, repo_root: Path) -> str
def load_agent_file(agent_name: str, repo_root: Path) -> str
```

Fails closed if agent or skill is declared but not found on disk.

### 1.6 New module: `skill_resolver.py` (~100 lines)

Loads skill SKILL.md files by name from `.claude/skills/<name>/SKILL.md`. Caches loaded content.

```python
def load_skill(name: str, repo_root: Path) -> str
def load_all_skills(spec: AssembledWorkflowSpec, repo_root: Path) -> dict[str, str]
```

### Critical files:
- `governance/dag_runner/models.py` — extend with new types
- `governance/dag_runner/assembler.py` — add `_assemble_agents()`
- `governance/dag_runner/validator.py` — add 5 new validation checks
- `governance/dag_runner/execution_backend.py` — new (interface + MockExecutionBackend)
- `governance/dag_runner/agent_resolver.py` — new
- `governance/dag_runner/skill_resolver.py` — new

---

## Phase 2: Component-Kind Dispatch & Execution Modes

**Goal:** Refactor executor dispatch to use parsed component kinds. Add dry-run, JSON, graph-only, and continuation modes. All dispatch is component-driven, never step-name-driven.

### 2.1 Component-kind routing in `executor.py`

The executor MUST route by parsed component kind, not by hardcoded step names. Use the existing `_parse_component()` from `validator.py`:

```python
def _classify_step(step: WorkflowStep) -> tuple[ComponentKind, str | None]:
    """Parse step.component into (kind, name_or_none).
    Returns the dispatch discriminator for execution strategy."""
    kind, name = _parse_component(step.component)
    return kind, name
```

Execution strategy table (component-kind-driven):

| Component Kind | Execution Strategy |
|----------------|-------------------|
| `constitution` | Structural: load CLAUDE.md + canonical doc paths (no LLM) |
| `stage_gates` | Structural: evaluate gate conditions deterministically (no LLM) |
| `hooks` | Structural: synthesize hook verdicts (no LLM) |
| `skill:<name>` with `agent_binding` | Backend dispatch: `backend.execute_step()` |
| `subagents` with `agent_binding` | Backend dispatch: `backend.execute_step()` (coordinator) |
| All other bare kinds | Structural: deterministic evaluation |

The executor receives an `ExecutionBackend` instance. In V2A, this is always `MockExecutionBackend`. In V2B, this becomes `ClaudeCLIBackend` or `NativeClaudeBackend`.

### 2.2 Extend `executor.py` — `execute_plan()` signature

```python
def execute_plan(
    spec: AssembledWorkflowSpec,
    plan: ExecutionPlan,
    *,
    verdict_status: str | None = None,
    config: ExecutionConfig | None = None,       # new, defaults to shell_v1
    backend: ExecutionBackend | None = None,      # new, defaults to None (V1 shell path)
    prior_state: GovernanceRunState | None = None, # new, for continuation
) -> ExecutionResult:
```

When `backend is None`: existing V1 shell path (unchanged, all 204 tests pass).
When `backend is not None`: new V2 component-kind dispatch path.

### 2.3 Extend `cli.py` — new flags

| Flag | Mode | Behavior |
|------|------|----------|
| `--dry-run` | `dry_run` | Walk plan, evaluate predicates, no artifacts, no backend invocation |
| `--json` | any + json | JSON output to stdout instead of text summary |
| `--graph` | `graph_only` | Emit DAG structure as JSON, no execution |
| `--mode agent_execution` | `agent_execution` | Backend-driven execution (MockExecutionBackend in V2A) |
| `--continue-from <step>` | continuation | Resume from step, loading prior state |
| `--timeout <ms>` | any | Total run timeout budget |
| `--phase <A-E>` | phase scope | Execute only steps in the given layer |

Default behavior (no new flags) remains V1 shell mode.

### 2.4 Graph output mode

Produce machine-readable DAG JSON:
```json
{
  "steps": [{"id": "...", "component": "...", "component_kind": "...", "depends_on": [...], "agent_binding": "...", "outputs": [...]}],
  "edges": [{"from": "...", "to": "..."}],
  "agents": {"name": {"model": "...", "skill_bindings": [...], "produces": [...]}},
  "skills": {"name": {"produces": [...]}},
  "artifacts": {"name": {"producer_step": "...", "required": true}},
  "blocking_conditions": {"id": {"severity": "...", "halts_workflow": true}}
}
```

### 2.5 Dry-run mode

Walk the plan, evaluate predicates, resolve agents/skills, classify component kinds, but produce no artifacts and invoke no backend. Emit trace events with `dry_run: true`.

### 2.6 Continuation mode with guardrails

Accept prior `GovernanceRunState` via `--continue-from` + `--state-path`. **Strict compatibility checks (fail-closed):**

| Check | Fails When |
|-------|-----------|
| Workflow name match | `prior_state.current_phase != plan.workflow_name` |
| Orchestration version match | `prior_state.orchestration_version != spec.manifest.workflow_version` |
| Structural validity | Prior state has unresolvable structure (missing fields, corrupt JSON) |
| No fatal unresolved blockers before continuation point | Any `BlockingEvent` with `halts_workflow=True` and `resolved=False` exists for steps before the continuation step |
| Prerequisite artifacts exist and validate | For each step from continuation point forward, all declared `inputs` that should have been produced by prior steps must be present in `prior_state.artifacts` with `status="present"` |

Continuation fails closed unless ALL checks pass. No partial or best-effort continuation.

```python
def validate_continuation(
    prior_state: GovernanceRunState,
    spec: AssembledWorkflowSpec,
    plan: ExecutionPlan,
    continue_from: str,
) -> list[str]:  # returns list of failure reasons; empty = valid
```

### 2.7 New module: `execution_modes.py` (~80 lines)

CLI flag → `ExecutionConfig` mapping. Continuation validation logic.

### Critical files:
- `governance/dag_runner/executor.py` — component-kind dispatch, backend integration, continuation
- `governance/dag_runner/cli.py` — extend with new flags
- `governance/dag_runner/execution_modes.py` — new

---

## Phase 3: Prompt Assembly Pipeline

**Goal:** Build infrastructure that constructs bounded prompt context for each step.

### 3.1 New module: `prompt_assembly.py` (~250 lines)

```python
def assemble_step_prompt(
    step: WorkflowStep,
    spec: AssembledWorkflowSpec,
    run_state: GovernanceRunState,
    repo_root: Path,
    token_budget: int = 100_000,
) -> PromptAssemblyContext
```

Assembly order (deterministic, priority-ordered):
1. Skill SKILL.md content (never truncated)
2. Agent .md file content
3. Upstream artifact payloads (ordered by production step in DAG order)
4. Canonical document paths and content (from agent.consumes)

### 3.2 New module: `input_bounding.py` (~100 lines)

Deterministic input slicing to enforce prompt token budget:
- Priority: skill > agent instructions > artifacts > documents
- Truncation from lowest priority first
- Record truncation events in trace

### 3.3 Path bounding

All file access validated against repo root. Only paths declared in `artifacts.yaml` required_inputs or agent.consumes are loadable.

### Critical files:
- `governance/dag_runner/prompt_assembly.py` — new
- `governance/dag_runner/input_bounding.py` — new

---

## Phase 4: Artifact Production & Canonical Write Contract

**Goal:** Make all 19 artifacts real (via MockExecutionBackend). Lock one canonical artifact write format.

### 4.1 Canonical artifact write contract

**V2 writes ONLY hook-compatible artifact envelopes.** One format, no alternatives:

```json
{
  "artifact": "<name>",
  "produced_by": "<step_id>",
  "session": "<run_id>",
  "timestamp": "<iso8601>Z",
  "data": { ... }
}
```

This matches `.claude/hooks/lib/artifact_store.py` exactly. The read path remains broad (supports `payload`, `data`, and top-level key fallback as in `predicates.py`). The write path is locked.

### 4.2 New module: `artifact_writer.py` (~80 lines)

```python
def write_artifact_envelope(
    name: str,
    data: dict[str, Any],
    produced_by: str,
    session: str,
    artifact_dir: Path,
) -> Path:
    """Write one canonical artifact envelope. No other write format exists in V2."""
```

Creates directory if needed. Returns path written. Uses `datetime.now(timezone.utc)` (not `utcnow()`).

### 4.3 Artifact flow validation

Before executing a step, verify all declared inputs exist in `run_state.artifacts`. If a required input is missing and was NOT produced by a skipped step, raise an artifact failure.

### 4.4 Artifact schema definitions

Key fields needed by downstream steps and hooks:

| Artifact | Required Fields | Consumed By |
|----------|----------------|-------------|
| `claim_classification_map` | `non_canonical_source_as_current_truth` | escalation condition |
| `role_citation_verdict` | `violations[]` | hook + escalation |
| `phase_alignment_status` | `phase_a_satisfied`, `build_order_ambiguity_detected` | stage-gate + escalation |
| `runtime_boundary_verdict` | `raw_observation_access_detected`, `latest_snapshot_misuse_detected`, `boundary_violation_suspected` | hook |
| `adapter_schema_verdict` | `registry_driven`, `hardcoded_series_detected`, `violations[]` | hook |
| `stage_gate_report` | `live_readiness_claim_detected`, `execution_capability_claim_detected` | hook |
| `change_impact_report` | `change_type`, `contract_affecting`, `doc_update_required`, `matrix_posture_affected` | predicates |
| `doc_code_sync_status` | `drift_detected`, `doc_doc_conflict_detected` | hook + escalation |
| `verification_matrix_delta` | `classification_dispute_detected` | escalation |

### Critical files:
- `governance/dag_runner/artifact_writer.py` — new
- `governance/dag_runner/executor.py` — integrate artifact writing after backend execution

---

## Phase 5: Drift Detection as Pre-Execution Validation

**Goal:** Detect cross-file inconsistencies BEFORE execution. Critical drift blocks the run.

### 5.1 New module: `drift_detector.py` (~200 lines)

Runs as a validation phase **after assembly, before execution**. Integrated into the pipeline between `validate_or_raise()` and `build_execution_plan()`.

```python
@dataclass(frozen=True)
class DriftResult:
    is_clean: bool
    critical_drifts: list[DriftIssue]    # block execution
    informational_drifts: list[DriftIssue]  # warn only

def detect_drift(
    spec: AssembledWorkflowSpec,
    repo_root: Path,
) -> DriftResult
```

### 5.2 Drift checks

| Check | Severity | Description |
|-------|----------|-------------|
| Agent file existence | **critical** | Every `spec.agents` entry has a `.claude/agents/<name>.md` file |
| Skill file existence | **critical** | Every `spec.skills` entry has a `.claude/skills/<name>/SKILL.md` file |
| Agent-step binding mismatch | **critical** | Agent `workflow_steps` matches step `agent_binding` (bidirectional) |
| Artifact producer consistency | **critical** | Agent `produces` matches step `outputs` for bound steps |
| Hook reinforcement consistency | informational | Step `reinforced_by_hook` references a hook that reads the step's output artifacts |
| Duplicate invariant logic | informational | Skills and hooks that validate the same blocking conditions |
| Doc path consistency | informational | Agent `consumes` references only paths in `artifacts.yaml` required_inputs |

### 5.3 Integration into pipeline

```python
# In cli.py main():
loaded = load_workflow_packages(workflow_path)
spec = assemble_workflow_spec(loaded)
validate_or_raise(spec)

# NEW — drift detection blocks before execution
drift_result = detect_drift(spec, repo_root)
if not drift_result.is_clean:
    # critical drifts → fail closed, exit 1
    # informational only → warn, continue

plan = build_execution_plan(spec)
# ... rest of pipeline
```

### Critical files:
- `governance/dag_runner/drift_detector.py` — new
- `governance/dag_runner/cli.py` — integrate drift check before planning

---

## Phase 6: Observability & Diagnostics

**Goal:** Rich structured event stream and diagnostic outputs.

### 6.1 Extended trace event types

Add to `ExecutionTraceEvent` event_type vocabulary:

| Event Type | When |
|------------|------|
| `agent_resolved` | agent_binding resolved to AgentSpec |
| `skill_resolved` | skill loaded from SKILL.md |
| `prompt_assembled` | PromptAssemblyContext constructed |
| `input_bounded` | Token budget truncation applied |
| `backend_invocation_started` | Backend execution initiated |
| `backend_invocation_completed` | Backend returned result |
| `backend_invocation_failed` | Backend execution error |
| `artifact_produced` | Real artifact written |
| `artifact_validated` | Schema validation result |
| `blocking_event_raised` | Runtime blocking event |
| `halt_on_critical_failure` | DAG halted |
| `drift_check_completed` | Drift detection result |
| `continuation_validated` | Continuation guardrail result |

### 6.2 New module: `diagnostics.py` (~120 lines)

Produce diagnostic report at run end:
- Per-step latency (wall time ms)
- Per-step token consumption (when backend reports it)
- Prompt budget utilization
- Critical path analysis (longest dependency chain)
- Bottleneck identification
- Total run duration

### 6.3 Exit code alignment

| Code | Meaning |
|------|---------|
| 0 | Clean run, verdict=ready |
| 1 | Structural failure (loader, assembler, validator, drift) |
| 2 | Contract failure (blocking condition with halts_workflow) |
| 3 | Runtime failure (backend invocation error, timeout) |
| 4 | Artifact failure (validation, missing required) |
| 5 | Timeout exceeded |
| 10 | verdict=review_only |
| 11 | verdict=blocked (governance, not structural) |

### 6.4 Halt-on-critical-failure

When a step raises a blocking condition with `halts_workflow: true`:
1. Record `BlockingEvent`
2. Record `halt_on_critical_failure` trace event
3. Skip all subsequent steps (reason: "halted by critical blocker at {step_id}")
4. Compute final verdict (will be `blocked`)
5. Exit code 2

### Critical files:
- `governance/dag_runner/diagnostics.py` — new
- `governance/dag_runner/executor.py` — emit new trace events, halt-on-critical
- `governance/dag_runner/cli.py` — map exit codes

---

## Phase 7: Live Agent Execution (V2B Milestone)

**Goal:** Plug in real Claude backends, output validation, subagent dispatch.

### 7.1 `ClaudeCLIBackend` — `claude_cli_backend.py` (~150 lines)

```python
class ClaudeCLIBackend(ExecutionBackend):
    """Invokes claude -p with assembled prompt. For CI/CD and non-interactive use."""

    def execute_step(self, prompt, step, agent, config) -> AgentExecutionResult:
        # subprocess: claude -p "<prompt>" --model <model>
        # Parse JSON artifact from output
        # Handle timeout, parse failure, agent error
        # Classify failures
        ...
```

### 7.2 `NativeClaudeBackend` — `native_claude_backend.py` (~150 lines)

```python
class NativeClaudeBackend(ExecutionBackend):
    """Claude Code SDK invocation. For interactive sessions."""
    ...
```

### 7.3 Timeout, retry, error classification

- Per-step timeout from `ExecutionConfig.timeout_per_step_ms`
- Total run timeout from `ExecutionConfig.timeout_total_ms`
- Retry: 1 retry with exponential backoff on transient failures only
- Failure classification: structural, contract, runtime, artifact, timeout
- Fail closed on all non-transient failures

### 7.4 Schema-aware output validation — `output_validator.py` (~100 lines)

```python
def validate_artifact_output(
    artifact_name: str,
    data: dict,
    step: WorkflowStep,
    spec: AssembledWorkflowSpec,
) -> list[str]  # validation issues
```

Validate produced artifact contains fields needed by downstream consumers. Fail closed on schema violations.

### 7.5 Subagent dispatch — `escalation.py` (~150 lines)

```python
def evaluate_escalation_conditions(
    step: WorkflowStep,
    agent: AgentSpec,
    produced_artifacts: dict[str, dict],
    spec: AssembledWorkflowSpec,
) -> list[EscalationTrigger]

def dispatch_subagent(
    trigger: EscalationTrigger,
    context: PromptAssemblyContext,
    backend: ExecutionBackend,
    config: ExecutionConfig,
) -> dict[str, Any]  # merged into audit_summary
```

Escalation conditions from agents.yaml:

| Agent | Condition | Subagent |
|-------|-----------|----------|
| claim-classification-agent | `non_canonical_source_as_current_truth` | implementation-history-reconciler |
| role-citation-agent | `role_mismatch_for_strong_claim` or `readme_layer2_override` | canonical-role-auditor |
| build-sequence-agent | `build_order_ambiguity_detected` | architecture-sequence-auditor |
| snapshot-contract-agent | `snapshot_boundary_violation` | snapshot-boundary-auditor |
| runtime-boundary-agent | `boundary_violation_suspected` | snapshot-boundary-auditor |
| adapter-schema-agent | `registry_violation` or `schema_drift_detected` | adapter-schema-guardian |
| doc-code-sync-agent | `drift_detected` → doc-code-sync-auditor, `doc_doc_conflict` → cross-doc-consistency-auditor |
| verification-matrix-agent | `classification_dispute_detected` | verification-matrix-auditor |

### 7.6 Two-tier gate architecture

| Tier | Type | Examples | Behavior |
|------|------|----------|----------|
| Hard | Deterministic | Predicate checks, artifact presence, schema validation, drift | Fail immediately |
| Soft | Semantic | Agent-produced verdicts, escalation conditions | Accumulate toward review_only |

### 7.7 Skill applicability guards

Before invoking a skill-bound agent via a live backend, verify the current phase allows the skill by checking stage-gates.yaml scope. Block if skill scope is forbidden in current phase.

### Critical files:
- `governance/dag_runner/claude_cli_backend.py` — new (V2B)
- `governance/dag_runner/native_claude_backend.py` — new (V2B)
- `governance/dag_runner/output_validator.py` — new (V2B)
- `governance/dag_runner/escalation.py` — new (V2B)

---

## Testing Strategy

### Existing tests (204 tests) — must pass unchanged

All V1 tests validate the default path (`backend=None`). The refactor adds new execution paths without modifying the default path.

### New test files — V2A

| File | Phase | Coverage |
|------|-------|----------|
| `test_agent_resolver.py` | 1 | Agent/skill resolution, missing agent error |
| `test_execution_backend.py` | 1 | MockExecutionBackend, interface contract |
| `test_component_dispatch.py` | 2 | Component-kind routing for all kinds |
| `test_execution_modes.py` | 2 | Dry-run, graph, JSON modes |
| `test_continuation.py` | 2 | Continuation guardrails (all 5 checks) |
| `test_prompt_assembly.py` | 3 | Prompt construction, budget, truncation |
| `test_artifact_writer.py` | 4 | Envelope writing, hook format compatibility |
| `test_drift_detector.py` | 5 | All 7 drift checks, critical vs informational |
| `test_diagnostics.py` | 6 | Timing, bottleneck analysis |
| `test_executor_v2.py` | 2-4 | Full pipeline with MockExecutionBackend |

### New test files — V2B

| File | Phase | Coverage |
|------|-------|----------|
| `test_claude_cli_backend.py` | 7 | Mock subprocess, timeout, retry, parse |
| `test_output_validator.py` | 7 | Artifact schema validation |
| `test_escalation.py` | 7 | Escalation conditions, subagent dispatch |

### Test infrastructure

- `MockExecutionBackend` with configurable artifact payloads (built in Phase 1)
- Fixture providing complete `AssembledWorkflowSpec` from real YAML packages
- Fixture providing predetermined artifact payloads for all 19 artifacts

---

## Module Inventory (Final State)

### Existing modules (modified)

| Module | Changes |
|--------|---------|
| `models.py` | +AgentSpec, +ComponentKind, +ExecutionConfig, +PromptAssemblyContext, +ArtifactEnvelope, +FailureClassification, +AgentExecutionResult; extend AssembledWorkflowSpec, NodeResult |
| `assembler.py` | +_assemble_agents() |
| `validator.py` | +5 new validation checks |
| `executor.py` | +component-kind dispatch, +backend integration, +dry_run, +continuation with guardrails, +halt-on-critical |
| `cli.py` | +7 new CLI flags, +drift check integration, +exit code mapping |
| `planner.py` | +layer_groups() for phase-scoped execution |
| `state_store.py` | Extend StoredRunState with agent execution metadata |

### New modules — V2A

| Module | Lines (est.) | Purpose |
|--------|-------------|---------|
| `execution_backend.py` | ~120 | ExecutionBackend interface + MockExecutionBackend |
| `agent_resolver.py` | ~150 | Resolve agent_binding → AgentSpec → skill content |
| `skill_resolver.py` | ~100 | Load SKILL.md files by name |
| `execution_modes.py` | ~80 | ExecutionConfig mapping + continuation validation |
| `prompt_assembly.py` | ~250 | Assemble bounded prompt context per step |
| `input_bounding.py` | ~100 | Deterministic token budget truncation |
| `artifact_writer.py` | ~80 | Canonical artifact envelope writer |
| `drift_detector.py` | ~200 | Pre-execution cross-file consistency validation |
| `diagnostics.py` | ~120 | Per-step timing, bottleneck analysis |
| **V2A total** | **~1,200** | |

### New modules — V2B

| Module | Lines (est.) | Purpose |
|--------|-------------|---------|
| `claude_cli_backend.py` | ~150 | ClaudeCLIBackend (claude -p) |
| `native_claude_backend.py` | ~150 | NativeClaudeBackend (SDK) |
| `output_validator.py` | ~100 | Schema-aware artifact validation |
| `escalation.py` | ~150 | Subagent dispatch on violations |
| **V2B total** | **~550** | |

**Combined:** existing ~3,732 + V2A ~1,200 + V2B ~550 = **~5,482 lines total**

---

## Verification

### V2A end-to-end

```bash
# V1 shell mode (unchanged — backwards compat)
python -m governance.dag_runner.cli --show-steps --write-state

# Dry-run mode
python -m governance.dag_runner.cli --dry-run --json

# Graph-only mode
python -m governance.dag_runner.cli --graph --json

# V2A mocked agent execution
python -m governance.dag_runner.cli --mode agent_execution --write-state

# Continuation from prior run
python -m governance.dag_runner.cli --mode agent_execution --continue-from deep-audit --state-path governance_run_state.json

# Full test suite
python -m pytest tests/governance -q
```

### V2A success criteria
- All 204 existing tests pass
- V1 shell mode produces identical output to current
- `--dry-run` produces trace events without artifacts
- `--graph` emits valid DAG JSON with component_kind fields
- `--mode agent_execution` with MockExecutionBackend produces all 19 artifact envelopes
- All artifacts written to `.claude/run/artifacts/` match hook `artifact_store.py` envelope format exactly
- Halt-on-critical-failure stops DAG traversal on `halts_workflow: true` blockers
- Drift detection blocks on critical drift before execution starts
- Continuation fails closed when guardrails are violated
- Exit codes align with failure categories
- Component-kind dispatch routes correctly for all 18 steps (no step-name conditionals)

### V2B success criteria (deferred)
- `ClaudeCLIBackend` invokes `claude -p` and parses real output
- `NativeClaudeBackend` invokes Claude Code SDK
- Timeout and retry work correctly
- Output validator rejects malformed artifacts
- Escalation dispatches subagents on violation conditions
- Skill applicability guards block forbidden-phase skills

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Breaking existing tests | `backend=None` preserves V1 shell path; new model fields have defaults |
| Agent invocation reliability | Deferred to V2B behind ExecutionBackend interface; V2A uses mock |
| Prompt exceeding context window | Deterministic input bounding; skill content never truncated |
| Artifact format drift | Locked canonical write contract; ONE envelope format for all V2 writes |
| Continuation corruption | 5 strict guardrails; fail closed on any mismatch |
| Cross-file inconsistency | Drift detection runs before execution; critical drift blocks |
| Token cost | V2A is zero-cost (mocked); V2B uses sonnet for 12/14 agents |
| Windows path handling | `pathlib.Path` throughout; normalize in prompt assembly |
| Hook compatibility | Write format matches `artifact_store.py` exactly |
| Blast radius | V2A delivers full infrastructure without any Claude invocation |

---

## Implementation Order

V2A: Phases 1 → 2 → 3 → 4 → 5 → 6 (sequential, each builds on prior).
V2B: Phase 7 (after V2A complete).

```
V2A Milestone:
  Phase 1 (foundation + backend interface)
    → Phase 2 (component dispatch + modes + continuation)
      → Phase 3 (prompt assembly)
        → Phase 4 (artifact envelopes)
          → Phase 5 (drift detection as validation)
            → Phase 6 (diagnostics + observability)

V2B Milestone (after V2A):
  Phase 7 (live backends + output validation + escalation)
```
