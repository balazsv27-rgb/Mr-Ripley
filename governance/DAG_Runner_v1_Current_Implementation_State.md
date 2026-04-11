# DAG Runner v1 — Current Implementation State

## Executive Summary

`governance/dag_runner/` is a working V1 governance runtime shell for Mr. Ripley.

It can:

* load the root orchestration workflow,
* resolve and load the workflow package set,
* assemble a typed workflow specification,
* validate the structure fail-closed (including `validates` tokens and predicate references),
* compute a topological execution plan,
* analyze blocker coverage and references (structural and runtime),
* compute a structural governance verdict,
* execute the workflow in V1 shell mode with condition/`skip_if` evaluation and SKIP semantics,
* populate runtime `BlockingEvent` records from step execution,
* compute a runtime-aware governance verdict,
* query artifact policy (required artifacts, presence, summaries),
* evaluate structured predicate conditions against run state,
* persist the run state into JSON including compact top-level readiness fields,
* and expose a read-only bridge API for hook consumption.

This implementation is not a trading engine, not an MCP orchestration layer, and not a true skill-execution runtime. It is the executable governance layer that turns the package-based specification into a testable runtime surface.

### V1 Shell-Mode Execution Caveat

The DAG runner currently executes in **V1 shell mode**. This is structural execution, not true skill execution.

A `ready` verdict in V1 shell mode means:

- structural validation of the workflow specification passed
- shell-mode execution completed without fatal blockers
- artifact placeholder records were materialized by the executor

It does **not** mean:

- governance analysis skills (claim classification, terminology normalization, doc-code sync, etc.) actually ran
- skills were truly executed with real inputs and outputs
- the semantic governance pipeline produced verified results

Steps may be recorded as `PASS` without real skill execution having occurred. The `ready` verdict is a **structural readiness signal**, not a semantic governance completion signal.

---

## 1. Repository Structure

```text
governance/
└── dag_runner/
    ├── __init__.py
    ├── models.py
    ├── loader.py
    ├── assembler.py
    ├── validator.py
    ├── planner.py
    ├── blockers.py
    ├── verdict.py
    ├── executor.py
    ├── artifacts.py
    ├── predicates.py
    ├── hook_bridge.py
    ├── state_store.py
    ├── cli.py
    └── dag_runner_v_1_blueprint.md

tests/
└── governance/
    ├── test_loader.py
    ├── test_assembler.py
    ├── test_validator.py
    ├── test_validator_failures.py
    ├── test_planner.py
    ├── test_blockers.py
    ├── test_verdict.py
    ├── test_executor.py
    ├── test_state_store.py
    ├── test_cli_integration.py
    ├── test_artifacts.py
    ├── test_predicates.py
    └── test_hook_bridge.py
```

---

## 2. Code File Inventory

### `governance/dag_runner/__init__.py`

**Purpose:** package entry point.
**Status:** technical support file.

**How to test**

```bash
python -c "import governance.dag_runner; print('package ok')"
```

---

### `governance/dag_runner/models.py`

**Purpose:** Defines the typed data model used across the DAG runner.
             This is the canonical type system of the DAG runtime.
             These are not "static properties" — they are the contract boundary between every module.
**Key models**

* `ManifestSpec`
* `WorkflowPackageSpec`
* `PredicateSpec`
* `SkillSpec`
* `SubagentSpec`
* `ArtifactSpec`
* `BlockingCondition`
* `StageGateSpec`
* `WorkflowStep`
* `AssembledWorkflowSpec`
* `ArtifactRecord`
* `BlockingEvent`
* `ExecutionTraceEvent`
* `NodeResult`
* `GovernanceRunState`

**How to test**

```bash
python -c "from governance.dag_runner.models import GovernanceRunState, WorkflowStep; print('models ok')"
```

**Expected result**

```text
models ok
```

---

### `governance/dag_runner/loader.py`

**Purpose:** Loads the root workflow YAML and all referenced workflow package YAML files.
             Transforms external YAML into raw in-memory structures.
**What it does**

* reads `.claude/workflows/system-orchestration.yaml`
* resolves `assembly.packages`
* loads the 13 package YAML files
* fails closed on missing or invalid YAML

**How to test**

```bash
python -c "from governance.dag_runner.loader import load_workflow_packages; r=load_workflow_packages(); print(r.manifest.workflow_name, len(r.packages))"
```

**Current result**

* workflow name: `mr-ripley-governance-orchestration`
* loaded packages: `13`

---

### `governance/dag_runner/assembler.py`

**Purpose:** Assembles loaded workflow packages into a typed compiled workflow specification.
             This is the compiler's "linker" phase, where the declarative system becomes a structured program.
**What it does**

* extracts package `data` sections
* assembles:

  * predicates
  * skills
  * subagents
  * artifacts
  * blockers
  * stage gates
  * workflow steps
* supports the current mixed YAML section layouts

**How to test**

```bash
python -c "from governance.dag_runner.loader import load_workflow_packages; from governance.dag_runner.assembler import assemble_workflow_spec; loaded=load_workflow_packages(); spec=assemble_workflow_spec(loaded); print(spec.manifest.workflow_name, len(spec.workflow_steps), len(spec.skills), len(spec.artifacts), len(spec.blocking_conditions), len(spec.stage_gates), len(spec.subagents), len(spec.predicates))"
```

**Current result**

* workflow steps: `18`
* skills: `13`
* artifacts: `19`
* blocking conditions: `12`
* stage gates: `4`
* subagents: `8`
* predicates: `6`

---

### `governance/dag_runner/validator.py`

**Purpose:** Validates the assembled workflow specification.
             This is a fail-closed static verifier (like a type checker + linter).
             This is pre-execution enforcement — nothing dynamic here.

**What it does**

* validates required sections
* validates `depends_on`
* validates output artifact references
* validates blocker references
* validates component references
* validates supported condition / `skip_if` structures
* detects dependency cycles
* validates `validates` tokens against declared blocking conditions and known governance property constants
* validates named predicate references (`type: "predicate_ref"`) against declared predicates in `spec.predicates`
* fails closed when the spec is invalid

**Allowed condition types (V1)**

| Type | Category |
|---|---|
| `artifact_field_equals` | inline structured condition |
| `artifact_field_not_equals` | inline structured condition |
| `artifact_exists` | inline structured condition |
| `artifact_missing` | inline structured condition |
| `predicate_ref` | named predicate reference — requires `name` key resolving to `spec.predicates` |

**`validates` token source of truth (V1)**

Union of:
1. All declared blocking condition IDs from `spec.blocking_conditions`
2. `_KNOWN_VALIDATES_TOKENS` — a hardcoded frozenset of 15 governance property constants in `validator.py` (invariants validated by workflow steps that are not tied to a `BlockingCondition`)

**How to test**

```bash
python -c "from governance.dag_runner.loader import load_workflow_packages; from governance.dag_runner.assembler import assemble_workflow_spec; from governance.dag_runner.validator import validate_workflow_spec; loaded=load_workflow_packages(); spec=assemble_workflow_spec(loaded); result=validate_workflow_spec(spec); print(result.is_valid, len(result.issues))"
```

**Current result**

```text
True 0
```

---

### `governance/dag_runner/planner.py`

**Purpose:** Computes the topological execution order from the validated workflow spec.
             Transforms a validated spec into an executable DAG plan.
**What it does**

* builds a dependency graph
* performs topological sorting
* materializes execution order
* emits an `ExecutionPlan`

**How to test**

```bash
python -c "from governance.dag_runner.loader import load_workflow_packages; from governance.dag_runner.assembler import assemble_workflow_spec; from governance.dag_runner.validator import validate_or_raise; from governance.dag_runner.planner import build_execution_plan; loaded=load_workflow_packages(); spec=assemble_workflow_spec(loaded); validate_or_raise(spec); plan=build_execution_plan(spec); print(plan.workflow_name, len(plan.ordered_steps), plan.ordered_step_ids[:5])"
```

**Current first five steps**

1. `load-context`
2. `classify-claims`
3. `normalize-terminology`
4. `route-claims-by-role`
5. `phase-check`

---

### `governance/dag_runner/blockers.py`

**Purpose:** Analyzes the relationship between the blocker registry and workflow step `raises` references
             (structural analysis), and analyzes runtime blocking events recorded during execution
             (runtime analysis).

**What it does — structural analysis**

* collects declared blockers
* collects referenced blockers from planned steps
* detects orphan blockers
* detects unknown blocker references
* reports structural consistency

**What it does — runtime analysis**

* `analyze_runtime_blockers(run_state, spec) -> RuntimeBlockerSummary`
  * validates all recorded `BlockingEvent` IDs against the declared registry (fails closed on unknown IDs)
  * returns `raised_blockers`, `unresolved_blockers`, `fatal_unresolved_blockers`
  * returns counts and boolean flags (`has_unresolved`, `has_fatal_unresolved`)
  * returns `raised_by_step` map
* `has_unresolved_fatal_blocks(run_state, spec) -> bool`
  * convenience wrapper — True when any unresolved blocking event has `halts_workflow=True`

**How to test**

```bash
python -c "from governance.dag_runner.loader import load_workflow_packages; from governance.dag_runner.assembler import assemble_workflow_spec; from governance.dag_runner.validator import validate_or_raise; from governance.dag_runner.planner import build_execution_plan; from governance.dag_runner.blockers import analyze_blockers; loaded=load_workflow_packages(); spec=assemble_workflow_spec(loaded); validate_or_raise(spec); plan=build_execution_plan(spec); summary=analyze_blockers(spec, plan); print(len(summary.declared_blockers), len(summary.referenced_blockers), len(summary.orphan_blockers), len(summary.unknown_references), summary.is_structurally_consistent)"
```

**Current structural result**

* declared blockers: `12`
* referenced blockers: `17`
* orphan blockers: `0`
* unknown references: `0`
* structurally consistent: `True`

**Current runtime result (clean shell run)**

* raised blockers: `0`
* unresolved blockers: `0`
* fatal unresolved: `0`

---

### `governance/dag_runner/verdict.py`

**Purpose:** Computes the governance verdict from validation and blocker analysis.
             Provides both a structural verdict (pre-execution) and a runtime-aware verdict
             (post-execution, consults run state and artifact presence).

**Structural verdict logic (`compute_structural_verdict` / `compute_verdict`)**

* validation failure → `blocked`
* unknown blocker references → `blocked`
* orphan blockers → `review_only`
* otherwise → `ready`

**Runtime-aware verdict logic (`compute_runtime_verdict`)**

Evaluation order:
1. structural invalidity → `blocked`
2. unknown structural blocker refs → `blocked`
3. fatal unresolved runtime blockers → `blocked`
4. non-fatal unresolved runtime blockers → `review_only`
5. required outputs not present → `review_only`
6. workflow not complete (no `run_completed` trace event) → `review_only`
7. structural orphan blockers → `review_only`
8. all clean → `ready`

**Additional exports**

* `is_workflow_complete(run_state) -> bool` — True when `run_completed` trace event is present

**How to test**

```bash
python -c "from governance.dag_runner.loader import load_workflow_packages; from governance.dag_runner.assembler import assemble_workflow_spec; from governance.dag_runner.validator import validate_workflow_spec; from governance.dag_runner.planner import build_execution_plan; from governance.dag_runner.blockers import analyze_blockers; from governance.dag_runner.verdict import compute_verdict; loaded=load_workflow_packages(); spec=assemble_workflow_spec(loaded); validation=validate_workflow_spec(spec); plan=build_execution_plan(spec); blockers=analyze_blockers(spec, plan); verdict=compute_verdict(validation, blockers); print(verdict.status, verdict.reasons)"
```

**Current result**

```text
ready ['Validation passed and blocker structure is consistent.']
```

---

### `governance/dag_runner/executor.py`

**Purpose:** Builds the runtime state and executes the planned workflow in V1 shell mode.

**Important note**
This is not true skill execution. It is a trace-producing shell runtime with real condition evaluation and SKIP semantics.

**What it does**

* walks the planned nodes in order
* builds a `GovernanceRunState`
* evaluates `condition` before executing each node — if unmatched, emits `SKIP`
* evaluates `skip_if` after `condition` — if matched, emits `SKIP`
* records `condition_evaluated` and `skip_if_evaluated` trace events during evaluation
* records `step_skipped` trace event when a node is skipped
* records `NodeResult` entries (status: `PASS` or `SKIP`)
* records `ExecutionTraceEvent` entries
* materializes artifact records (skipped steps produce no artifacts)
* stores the final verdict into the run state
* populates `run_state.blocking_conditions` with runtime `BlockingEvent` objects (via `_raise_blocking_event`)

**How to test**

```bash
python -c "from governance.dag_runner.loader import load_workflow_packages; from governance.dag_runner.assembler import assemble_workflow_spec; from governance.dag_runner.validator import validate_workflow_spec; from governance.dag_runner.planner import build_execution_plan; from governance.dag_runner.blockers import analyze_blockers; from governance.dag_runner.verdict import compute_verdict; from governance.dag_runner.executor import execute_plan; loaded=load_workflow_packages(); spec=assemble_workflow_spec(loaded); validation=validate_workflow_spec(spec); plan=build_execution_plan(spec); blockers=analyze_blockers(spec, plan); verdict=compute_verdict(validation, blockers); result=execute_plan(spec, plan, verdict_status=verdict.status); print(result.run_state.final_verdict, len(result.run_state.node_results), len(result.run_state.execution_trace), len(result.run_state.artifacts))"
```

**Current result**

* final verdict: `ready`
* node results: `18` (17 PASS + 1 SKIP — `rename-invariance-check` is skipped when condition is not met)
* execution trace events: `39`
* artifacts recorded: `18` (skipped step produces no artifact)
* runtime blocking conditions: `0` (clean run)

---

### `governance/dag_runner/artifacts.py`

**Purpose:** Artifact policy and query module. The single place for answering artifact questions:
             which artifacts are declared, which are required, which are present, which are missing,
             and what compact summary should verdict and hooks consume.

**Design rules**

* read-only and policy-only — no disk I/O, no run-state mutation
* fail closed — malformed inputs raise explicit exceptions
* supports both typed `GovernanceRunState` and persisted dict payloads
* deterministic — list-returning functions return sorted output

**Public API**

| Function | Description |
|---|---|
| `artifact_exists(run_state, name)` | True when artifact is present and usable |
| `get_artifact_record(run_state, name)` | Returns the artifact record dict or None |
| `get_required_artifacts(spec)` | Sorted list of unconditionally required artifact names |
| `get_missing_required_artifacts(spec, run_state)` | Sorted list of required artifacts absent from run state |
| `build_artifact_summary(spec, run_state)` | Compact machine-readable artifact summary dict |

**Required-artifact policy (V1)**

An artifact is unconditionally required when `ArtifactSpec.required = True`. The assembler derives this from `conditional` in `artifacts.yaml`:

```
required = not conditional
```

Conditional artifacts (`doc_update_plan`, `invariance_verdict`, `verification_matrix_delta`) are excluded from the required list — they are only required when specific runtime predicates are active.

**Exceptions**

* `ArtifactPolicyError` — base exception
* `ArtifactStructureError` — malformed or structurally insufficient run-state input

**How to test**

```bash
python -c "from governance.dag_runner.artifacts import get_required_artifacts, build_artifact_summary; from governance.dag_runner.loader import load_workflow_packages; from governance.dag_runner.assembler import assemble_workflow_spec; from governance.dag_runner.executor import execute_plan; from governance.dag_runner.planner import build_execution_plan; from governance.dag_runner.validator import validate_workflow_spec; from governance.dag_runner.blockers import analyze_blockers; from governance.dag_runner.verdict import compute_verdict; loaded=load_workflow_packages(); spec=assemble_workflow_spec(loaded); validation=validate_workflow_spec(spec); plan=build_execution_plan(spec); blockers=analyze_blockers(spec, plan); verdict=compute_verdict(validation, blockers); result=execute_plan(spec, plan, verdict_status=verdict.status); req=get_required_artifacts(spec); print(len(req), 'required artifacts')"
```

**Current result**

* required artifacts: `16` (19 total − 3 conditional)

---

### `governance/dag_runner/predicates.py`

**Purpose:** V1 predicate evaluator. The single place for answering predicate questions at runtime.
             Evaluates structured predicate conditions against a governance run state.

**Design rules**

* fail closed — unsupported or malformed predicates raise explicit exceptions
* read-only — does not mutate run state
* delegates artifact-record lookup to `artifacts.get_artifact_record()` (public API, not the internal helper)
* deterministic — summary output is sorted

**Supported V1 predicate types**

| Type | Matched when |
|---|---|
| `artifact_exists` | named artifact is present in run state |
| `artifact_missing` | named artifact is absent from run state |
| `artifact_field_equals` | artifact exists and a field equals a value |
| `artifact_field_not_equals` | artifact exists and a field does not equal a value |

All other predicate types raise `UnsupportedPredicateError`.

**Field resolution order** (for field-based predicates)

1. `record["payload"][field]` — payload dict takes precedence
2. `record["data"][field]` — supports hook `artifact_store` envelope format
3. `record[field]` — top-level key fallback

**Public API**

| Function | Description |
|---|---|
| `evaluate_condition(condition, run_state)` | Evaluate one predicate, return `ConditionEvaluationResult` |
| `predicate_matches(condition, run_state)` | Thin wrapper, returns `bool` |
| `build_predicate_summary(evaluations)` | Compact machine-readable summary of a list of evaluations |

**Exceptions**

* `PredicateEvaluationError` — base exception
* `PredicateStructureError` — malformed predicate or missing required keys
* `UnsupportedPredicateError` — predicate type not in V1 supported set

---

### `governance/dag_runner/hook_bridge.py`

**Purpose:** Read-only bridge from `.claude/hooks/` runtime enforcement hooks to the persisted
             `governance_run_state.json` produced by the DAG runner.

**Design rules**

* read-only — no writes to disk, no mutation of loaded state
* fail closed — missing or malformed state files raise explicit exceptions
* no live runner dependency — consumes only persisted JSON
* no YAML loading, no subprocess calls, no artifact-store writes

**Public API**

| Function | Description |
|---|---|
| `load_run_state(path=None)` | Load and minimally validate the persisted run-state JSON |
| `get_final_verdict(path=None)` | Return final verdict string (or None) |
| `has_unresolved_blocks(path=None)` | True when unknown blocker references exist or verdict is blocked |
| `get_required_artifact(name, path=None)` | Return named artifact record dict from persisted state, or None |
| `get_recorded_trace_events(path=None)` | Return the persisted execution trace event list |
| `get_pr_readiness(path=None)` | Return PR readiness dict or None |

**`get_final_verdict` resolution order**

1. top-level `final_verdict` (executor-recorded, post-run)
2. top-level `verdict_status` (computation-time, pre-execution)
3. `None` — does not invent a verdict

**`get_pr_readiness` resolution order**

1. top-level `pr_readiness` string (Phase 3 compact contract) — returned as `{"status": value}`
2. top-level `pr_readiness` dict (legacy dict form)
3. artifact named `pr_readiness_verdict` in `artifact_records`
4. `None`

**Exceptions**

* `HookBridgeError` — base exception
* `RunStateNotFoundError` — file does not exist or cannot be read
* `RunStateDecodeError` — file contains invalid JSON
* `RunStateStructureError` — JSON is valid but fails minimal structure check

**How to test**

```bash
python -c "from governance.dag_runner.hook_bridge import get_final_verdict; print(get_final_verdict())"
```

(Requires a `governance_run_state.json` generated by `--write-state`.)

---

### `governance/dag_runner/state_store.py`

**Purpose:** Persists the current run into machine-readable JSON.
             This is the serialization boundary of the runtime.
             As of Phase 3, also exposes a compact top-level readiness contract for hooks and CI consumers.

**What it does**

* stores workflow summary
* stores validation results
* stores blocker summary
* stores verdict
* stores execution order
* stores run metadata
* stores node results
* stores artifact records
* stores execution trace
* derives and stores compact top-level readiness fields from existing runtime analysis modules

**Compact top-level readiness fields (Phase 3 hook-facing contract)**

| Field | Type | Derivation |
|---|---|---|
| `workflow_completed` | `bool` | `is_workflow_complete(run_state)` — checks for `run_completed` trace event |
| `required_outputs_present` | `bool` | `artifacts.build_artifact_summary(...)["required_outputs_present"]` |
| `unresolved_blocking_conditions` | `list[dict]` | Unresolved `BlockingEvent` objects serialized to `{blocking_id, raised_by, severity, resolved, message}` |
| `fatal_unresolved_block_count` | `int` | `blockers.analyze_runtime_blockers(...).total_fatal_unresolved` |
| `pr_readiness` | `str` | Mapped from `compute_runtime_verdict(...)` status: `"ready"`, `"review_only"`, or `"blocked"` |

**Primary output**

* `governance_run_state.json`

**How to test**

```bash
python -c "from governance.dag_runner.state_store import generate_and_write_run_state; print(generate_and_write_run_state('.claude/workflows/system-orchestration.yaml'))"
```

---

### `governance/dag_runner/cli.py`

**Purpose:** CLI entry point for the full V1 governance runtime shell.
             Coordinates the full pipeline end-to-end.
**What it does**

* load
* assemble
* validate
* plan
* analyze blockers
* compute verdict
* execute in shell mode
* optionally write run state JSON

**Usage**

```bash
# basic run
python -m governance.dag_runner.cli

# show execution order
python -m governance.dag_runner.cli --show-steps

# write run-state JSON
python -m governance.dag_runner.cli --write-state

# write run-state JSON to a specific path
python -m governance.dag_runner.cli --write-state --state-path path/to/output.json

# full run
python -m governance.dag_runner.cli --show-steps --write-state
```

**Current typical output**

* Validation: `PASS`
* Planned steps: `18`
* Executed steps: `18`
* Recorded trace events: `39`
* Verdict: `READY`

---

### `governance/dag_runner/dag_runner_v_1_blueprint.md`

**Purpose:** implementation blueprint for the DAG runner.

**What it does**

* documents scope
* explains architecture
* records module responsibilities
* defines why DAG Runner v1 is the right next step
* identifies remaining components and future phases

**How to use**

* architectural reference
* implementation checkpoint
* handoff document for future work

---

## 3. Hook Implementation

The following runtime enforcement hooks are implemented in `.claude/hooks/`.
They form the active governance enforcement surface that fires during Claude Code tool use and agent stop events.
All hooks share a common artifact contract via `.claude/hooks/lib/artifact_store.py`.

### Shared library: `.claude/hooks/lib/artifact_store.py`

**Purpose:** Shared read/write contract for governance artifacts.
**Artifact location:** `.claude/run/artifacts/<name>.json`
**Provides:** `read_artifact(name)`, `write_artifact(name, data, produced_by)`, `artifact_exists(name)`
**Envelope schema:** `artifact`, `produced_by`, `session`, `timestamp`, `data`

---

### `snapshot_boundary_guard.py`

**Hook event:** PostToolUse (Edit | Write)
**Layer:** C — Runtime Schema Integrity
**Action:** block on violation
**Blocking conditions raised:** `snapshot_boundary_violation`, `raw_observations_used_in_layer3`
**Artifact written:** `runtime_boundary_verdict`

**What it enforces**

* `raw_observation_access_detected` — non-Layer-2 code reading the `observations` table directly
* `latest_snapshot_misuse_detected` — use of `snapshot_id='latest'` (forbidden by CLAUDE.md §6.3)
* `layer2_storage_coupling_detected` — non-Layer-2 code importing `layer2.db` or referencing `layer2_truth.db`

Layer-2 files are exempt from raw observation access and storage coupling checks.
`latest` snapshot misuse is forbidden everywhere.

---

### `adapter_schema_guard.py`

**Hook event:** PostToolUse (Edit | Write)
**Layer:** C — Runtime Schema Integrity
**Action:** warn (exit 1) or block (exit 2)
**Scope predicate:** `adapter_registry_scope` (`layer2/adapters/**`, `layer2/config/**`)
**Blocking conditions raised:** `registry_violation`, `schema_drift_detected`
**Artifact written:** `adapter_schema_verdict`

**What it enforces**

* `registry_driven` (positive check) — adapter must import from `layer2.config.registry` or reference the registry
* `hardcoded_series_detected` — inline series ID lists, dicts, or per-series conditionals
* `implicit_interpretation_detected` — inline tier, staleness_days, blocks_snapshot, frequency, or include_in_snapshot assignments

Blocks (exit 2) when no registry usage is found at all.
Warns (exit 1) when violations appear alongside registry usage.

---

### `live_readiness_claim_blocker.py`

**Hook event:** PostToolUse (Edit | Write)
**Layer:** B — Architecture Phase Contract
**Action:** block on match
**Blocking conditions raised:** `unsupported_current_state_claim`
**Artifact written:** `stage_gate_report`

**What it enforces**

* `live_readiness_claim_detected` — claims asserting Layer-3 existence, system live status, or live operation availability (forbidden until Phase D)
* `execution_capability_claim_detected` — claims asserting execution readiness, automated decision-making, or trading/order/signal execution capability (forbidden until Phase D)
* `production_ready_claim_detected` — assertions of production-readiness or external validation

Applies a negation filter — lines with clear negation words in the ~50-character prefix before the match are excluded.
Scans all non-governance-tooling files (code and documentation alike).

---

### `role_matched_doc_guard.py`

**Hook event:** Stop (SubagentStop)
**Layer:** A — Semantic Normalization
**Action:** warn (exit 1) or block (exit 2)
**Blocking conditions raised:** `role_mismatch_for_strong_claim`, `readme_layer2_used_as_override`, `canonical_conflict_unresolved`
**Artifact consumed:** `role_citation_verdict`

**What it enforces**

* `role_mismatch` — a canonical document was cited for a claim whose role belongs to a different canonical document (CLAUDE.md §2.2, §2.4)
* `readme_layer2_override` — README_LAYER2.md was used to override a more role-specific canonical document on implementation state, architecture boundaries, or limitations

Blocks (exit 2) when a violation is attached to a strong claim (CLAUDE.md §10).
Warns (exit 1) otherwise.

---

### `doc_code_sync_guard.py`

**Hook event:** Stop (SubagentStop)
**Layer:** D — Audit Impact
**Action:** warn only (exit 1)
**Escalation target:** doc-code-sync-auditor subagent
**Blocking conditions flagged:** `doc_code_drift_unresolved` (for pre-pr-governance-gate, not here)
**Artifact consumed:** `doc_code_sync_status`

**What it enforces**

* `drift_detected` must be false
* Drift types: `code_without_doc`, `doc_without_code`, or `both`

Warning-only gate: does not block agent stop.
Unresolved drift WILL block at `pre_pr_governance_gate` before commit or push.

---

### `pre_pr_governance_gate.py`

**Hook event:** PreToolUse (Bash)
**Layer:** E — Verification Hygiene / Release
**Action:** block on fail
**Self-filter:** only activates when command contains `git commit` or `git push`
**Blocking conditions raised:** `governance_artifacts_incomplete`, `pr_readiness_checks_failed`

**What it enforces**

* All 14 always-required governance artifacts are present in `.claude/run/artifacts/`
* Conditional artifacts are present based on active scope predicates inferred from staged files:

  | Predicate | Trigger | Required artifact |
  |-----------|---------|------------------|
  | `runtime_code_scope` | any `layer2/` file staged | `runtime_boundary_verdict` |
  | `adapter_registry_scope` | `layer2/adapters/` or `layer2/config/` staged | `adapter_schema_verdict` |
  | `doc_update_required` | canonical document staged | `doc_update_plan` |
  | `rename_only_change` | staged set is exclusively renames | `invariance_verdict` |
  | `matrix_posture_affected` | verification matrix staged | `verification_matrix_delta` |

* PR readiness checks from `pr_readiness_verdict`:
  * `unsupported_strong_claims_remain` must be `false`
  * `blocking_conditions_unresolved` must be `false`
  * `required_canonical_docs_reviewed` must be `true`
  * `canonical_references_updated` must be `true`
  * `alias_map_present_for_renames` must be `true` (only when `rename_only_change` active)

---

### Shell stubs

Three shell hook stubs are present but not yet implemented:

* `auto-format.sh`
* `run-tests.sh`
* `security-scan.sh`

These are placeholder files and currently contain no logic.

---

## 4. Current Recognized Workflow Shape

| Slice | Value |
|-|-:|
| Workflow name | `mr-ripley-governance-orchestration` |
| Loaded packages | 13 |
| Workflow steps | 18 |
| Skills | 13 |
| Artifacts | 19 |
| Blocking conditions | 12 |
| Stage gates | 4 |
| Subagents | 8 |
| Predicates | 6 |

### First five execution steps

1. `load-context`
2. `classify-claims`
3. `normalize-terminology`
4. `route-claims-by-role`
5. `phase-check`

### Current runtime execution summary

| Metric | Value |
|-|-:|
| PASS nodes | 17 |
| SKIP nodes | 1 (`rename-invariance-check` — condition not met) |
| Trace events | 39 |
| Artifacts recorded | 18 (skipped step produces no artifact) |
| Runtime blocking conditions | 0 (clean run) |
| Workflow completed | `True` |
| Required outputs present | `True` |
| PR readiness | `ready` |

---

## 5. Tests and Results

### Test file structure

```text
tests/governance/
├── test_loader.py              (  1 test)
├── test_assembler.py           (  1 test)
├── test_validator.py           (  1 test)
├── test_validator_failures.py  ( 24 tests)
├── test_planner.py             (  1 test)
├── test_blockers.py            ( 15 tests)
├── test_verdict.py             ( 16 tests)
├── test_executor.py            ( 21 tests)
├── test_state_store.py         ( 13 tests)
├── test_cli_integration.py     ( 13 tests)
├── test_artifacts.py           ( 33 tests)
├── test_predicates.py          ( 34 tests)
└── test_hook_bridge.py         ( 31 tests)
```

### What each test covers

#### `test_loader.py`

Checks that the root workflow loads, the 13 packages load, and the workflow name is correct.

#### `test_assembler.py`

Checks that the typed spec assembles successfully and the current counts match expected values.

#### `test_validator.py`

Checks that the current assembled workflow validates cleanly with zero issues.

#### `test_validator_failures.py`

Focused negative fixture suite — all tests use inline-constructed `AssembledWorkflowSpec` fixtures (no disk I/O, no YAML loading):

* **missing dependency** — step referencing a nonexistent `depends_on` target fires `missing_dependency`
* **missing skill reference** — `component: skill:unknown` fires `unknown_skill_component`; declared skill passes
* **missing blocker reference** — `raises` referencing undeclared blocker fires `unknown_blocking_condition`; declared blocker passes
* **unsupported condition structure** — unrecognized `type`, non-dict condition, unsupported `skip_if` type each fire the appropriate issue; valid inline conditions are not flagged
* **dependency cycle** — direct two-step A→B, B→A cycle fires `dependency_cycle`; self-referential step fires invalid
* **invalid `validates` token** — unknown governance token fires `unknown_validates_token` with token detail; blocking condition IDs and empty lists pass cleanly
* **invalid predicate reference** — undeclared `predicate_ref` name fires `unknown_predicate_reference`; missing `name` key fires `invalid_predicate_reference`; declared predicate passes in both `condition` and `skip_if`
* **multiple issues accumulated** — step with three simultaneous problems yields ≥3 issues; issues from multiple steps are all reported
* **real workflow sanity check** — current real workflow still validates cleanly after all expansions

#### `test_planner.py`

Checks that the execution plan builds successfully and the topological order starts with the expected five steps.

#### `test_blockers.py`

Covers:

* structural analysis against current real workflow (12 declared, 17 referenced, 0 orphans, 0 unknown, consistent)
* `analyze_runtime_blockers` with empty state returns zero counts
* resolved blockers are not counted as unresolved
* unresolved non-fatal blockers appear in `unresolved_blockers` but not `fatal_unresolved_blockers`
* unresolved fatal blockers appear in both lists
* `fatal` vs `non-fatal` classification is driven by `BlockingCondition.halts_workflow`
* `raised_by_step` map is populated correctly
* per-step deduplication of blocker IDs
* unknown blocker ID raises `BlockerError` (fail-closed)
* `has_unresolved_fatal_blocks` convenience wrapper — False for empty / non-fatal / resolved, True for fatal unresolved
* integration: shell run produces zero runtime blockers

#### `test_verdict.py`

Covers:

* `compute_structural_verdict` — ready, blocked on validation failure, blocked on unknown refs, review_only on orphans
* `compute_verdict` backward-compat wrapper matches structural verdict
* `compute_runtime_verdict` — blocked on validation failure, blocked on unknown blocker refs, blocked on fatal unresolved blocker, not blocked when fatal blocker resolved, review_only on non-fatal unresolved, review_only on missing required artifacts, review_only when workflow not complete, review_only on structural orphan blockers, ready when all clean
* integration: runtime verdict is `ready` for full shell run

#### `test_executor.py`

Covers:

* V1 shell run produces expected node results, trace events, and artifacts
* `condition_evaluated` trace event is emitted for the real workflow's conditional step
* `step_skipped` trace event is present in real workflow (rename-invariance-check)
* `blocking_conditions` is empty for the clean real workflow
* step without predicates executes as PASS
* matched `condition` → PASS; unmatched `condition` → SKIP with correct trace events
* unmatched `condition` SKIP result has empty `produced_artifacts`
* unmatched `skip_if` → PASS; matched `skip_if` → SKIP with correct trace events
* `condition` evaluated before `skip_if`; both evaluated when `condition` passes but `skip_if` fails
* malformed `condition` raises `ExecutorError` (fail-closed)
* malformed `skip_if` raises `ExecutorError` (fail-closed)
* unsupported `condition` type raises `ExecutorError`
* unsupported `skip_if` type raises `ExecutorError`
* `BlockingEvent` objects are populated via the blocking helper
* condition-triggered SKIP and skip_if-triggered SKIP produce no blocking conditions

#### `test_state_store.py`

Verifies the persisted JSON contract:

* file is written as valid JSON
* verdict fields (`verdict_status`, `verdict_reasons`, `final_verdict`) are present and correct
* execution trace is present with correct shape and event types (`run_started`, `run_completed`)
* node results are present with correct shape and valid statuses
* artifact records are present with correct shape
* run and workflow metadata fields are present and match expected values
* blocker summary fields are present and correct
* count fields are internally consistent (each count matches the length of its corresponding list)
* compact readiness fields are present (`workflow_completed`, `required_outputs_present`, `unresolved_blocking_conditions`, `fatal_unresolved_block_count`, `pr_readiness`)
* compact readiness field types are correct
* clean workflow persists a clean ready state: `workflow_completed=True`, `required_outputs_present=True`, `fatal_unresolved_block_count=0`, `pr_readiness="ready"`, `unresolved_blocking_conditions=[]`
* compact readiness fields are internally consistent with detailed runtime content
* all pre-Phase-3 detailed fields remain present (backward compatibility)

#### `test_cli_integration.py`

End-to-end CLI integration via `main()` with monkeypatched `sys.argv`:

* basic run exits with code 0 and reports Verdict, Planned steps, Executed steps
* `--show-steps` includes execution order and all 18 steps
* `--write-state` creates a file, writes valid JSON, and reports the written path
* `--write-state --state-path <path>` writes to the specified path
* full combined run (`--show-steps --write-state`) succeeds, produces both console output and a valid state file
* console step counts are consistent with the written state file

#### `test_artifacts.py`

Covers:

* `artifact_exists` for typed `GovernanceRunState` (present, absent, non-present statuses)
* `artifact_exists` for persisted dict payloads (present, absent, non-present)
* `get_artifact_record` for typed state (returns record, returns None, raises on malformed dict)
* `get_artifact_record` for persisted dict payload (returns record)
* `get_required_artifacts` (sorted list, count, includes known required, excludes conditional)
* `get_missing_required_artifacts` (detects missing, detects non-present status, empty after full shell run)
* `build_artifact_summary` (required keys, counts, `required_outputs_present`, declared-vs-recorded)
* malformed input raises `ArtifactStructureError`
* integration against full pipeline fixture

#### `test_predicates.py`

Covers all four predicate types, field resolution order (payload → data → top-level), malformed predicate errors, `UnsupportedPredicateError`, `predicate_matches`, `build_predicate_summary`, and a light integration test against a real shell run state.

#### `test_hook_bridge.py`

Covers:

* `load_run_state` — success, missing file, invalid JSON, malformed payload (all structural variants)
* `get_final_verdict` — priority order, blocked, `None` when both null
* `get_required_artifact` — returns record, returns None for absent
* `get_recorded_trace_events` — list contents, empty list, copy isolation
* `get_pr_readiness` — resolves from artifact, prefers top-level dict, returns None when absent
* `get_pr_readiness` — Phase 3 compact string field wrapped as `{"status": value}`; string takes priority over artifact fallback; dict form remains backward compatible
* `has_unresolved_blocks` — True on unknown references, True on blocked verdict, False when clean, False on `review_only`
* `_extract_blocking_conditions` — fails closed when no blocker structure and no verdict
* exception hierarchy (`RunStateNotFoundError`, `RunStateDecodeError`, `RunStateStructureError` are all `HookBridgeError`)
* path handling — accepts both `str` and `Path`

### Current test result

```text
204 passed in ~3s
```

### Full test command

```bash
python -m pytest tests/governance -q
```

---

## 6. Current Run-State JSON Contents

`governance_run_state.json` currently contains:

**Workflow and structural metadata**
* workflow metadata (name, file, loaded packages)
* workflow shape counts (steps, skills, artifacts, blockers, stage gates, subagents)
* validation status and issue list
* blocker summary counts (declared, referenced, orphan, unknown, structurally consistent)
* structural verdict status and reasons
* execution order

**Runtime execution metadata**
* final verdict
* run id
* started_at timestamp
* recorded node result count
* recorded artifact count
* recorded trace event count
* node result list (with status, summary, evidence, produced_artifacts, triggered_blocks, inference_used)
* artifact record list (with name, producer_step, status, payload)
* execution trace list (with timestamp, node_name, event_type, detail)

**Compact top-level readiness fields (Phase 3 — hook-facing contract)**
* `workflow_completed` — bool
* `required_outputs_present` — bool
* `unresolved_blocking_conditions` — list of serialized runtime blocking events
* `fatal_unresolved_block_count` — int
* `pr_readiness` — string: `"ready"`, `"review_only"`, or `"blocked"`

---

## 7. What Is Still Missing

| Component | Status | Meaning |
|-|-|-|
| Real skill execution | not implemented | executor is shell mode only; all steps record PASS/SKIP via structural simulation |
| Shell hook stubs | not implemented | `auto-format.sh`, `run-tests.sh`, `security-scan.sh` are present but empty |
| Runtime artifact hygiene expansion | not implemented | `runtime-artifact-hygiene-check` skill and broader workspace hygiene enforcement beyond the current hook |
| Negative integration suite | not implemented | no end-to-end negative test covering full pipeline under failure conditions (invalid spec, blocked verdict, skipped artifacts) |

---

## 8. Completed Phases

### Phase 1 — Executor runtime semantics ✓

Implemented `condition` and `skip_if` evaluation before executing each node.
Emits `SKIP` when the skip condition is satisfied or the run condition is not met.
Records `condition_evaluated`, `skip_if_evaluated`, and `step_skipped` trace events.
Populates `run_state.blocking_conditions` via `_raise_blocking_event`.
Malformed or unsupported conditions raise `ExecutorError` (fail-closed).

### Phase 2 — Runtime blocker analysis and runtime-aware verdict ✓

Added `analyze_runtime_blockers(run_state, spec) -> RuntimeBlockerSummary` to `blockers.py`.
Added `has_unresolved_fatal_blocks(run_state, spec) -> bool`.
Added `compute_runtime_verdict(...)` to `verdict.py` — evaluates execution state, artifact presence, and blocker resolution.
Exposed `is_workflow_complete(run_state) -> bool`.

### Phase 3 — Richer hook contract in `state_store.py` ✓

Added compact top-level readiness fields to the persisted JSON:
`workflow_completed`, `required_outputs_present`, `unresolved_blocking_conditions`, `fatal_unresolved_block_count`, `pr_readiness`.
Fields are derived from `artifacts.build_artifact_summary`, `blockers.analyze_runtime_blockers`, and `verdict.compute_runtime_verdict`.
Updated `hook_bridge._extract_pr_readiness` to handle Phase 3 compact string field.
All pre-Phase-3 fields remain present (backward compatible).

### Phase 4 — Validator expansion ✓

Added `_validate_step_validates(spec)` — rejects unknown `validates` tokens (code: `unknown_validates_token`).
Added `_validate_predicate_references(spec)` — rejects undeclared `predicate_ref` names (codes: `unknown_predicate_reference`, `invalid_predicate_reference`).
Added `predicate_ref` to supported condition types in `_is_supported_condition`.
Added `_KNOWN_VALIDATES_TOKENS` frozenset (15 governance property constants) as the V1 static token registry.
Source of truth for allowed validates tokens: `spec.blocking_conditions.keys()` ∪ `_KNOWN_VALIDATES_TOKENS`.

### Phase 5 — Negative fixture test suite ✓

Created `tests/governance/test_validator_failures.py` (24 tests).
Covers all required failure cases: missing dependency, missing skill reference, missing blocker reference, unsupported condition structure, dependency cycle, invalid `validates` token, invalid predicate reference.
All tests use inline-constructed `AssembledWorkflowSpec` fixtures — no disk I/O, no YAML loading, no CLI required.
Includes positive counterparts (declared references pass), multi-issue accumulation, and a real workflow sanity check.

---

## 9. Recommended Next Steps

### Next — Negative integration suite

Add `tests/governance/test_pipeline_failures.py` (or similar) with end-to-end pipeline tests covering:
* invalid workflow spec fed through the full load→assemble→validate→plan pipeline
* blocked verdict propagated through executor and state store
* runtime blocking event triggering `review_only` or `blocked` verdict
* missing required artifact producing non-ready `pr_readiness`

These would complement the unit-level negative fixtures in `test_validator_failures.py` with integration-level negative evidence.

### Later — Shell hook stub completion

Implement `auto-format.sh`, `run-tests.sh`, `security-scan.sh` with real logic.

### Later — Runtime artifact hygiene expansion

Expand workspace hygiene enforcement beyond the current `runtime-artifact-hygiene-check` skill stub.

---

## 10. Final Summary

DAG Runner v1 is currently:

* operational,
* tested (204 tests across 13 test files),
* CLI-runnable (with `--show-steps`, `--write-state`, `--state-path`),
* verdict-aware (both structural and runtime-aware),
* execution-capable in shell mode with real condition/`skip_if` evaluation and SKIP semantics,
* runtime-blocker-aware (BlockingEvent population, fatal/non-fatal classification),
* backed by a public artifact policy module (`artifacts.py`),
* backed by a runtime predicate evaluator (`predicates.py`),
* backed by a read-only hook bridge (`hook_bridge.py`),
* backed by a compact top-level readiness contract in `governance_run_state.json`,
* backed by a hardened static validator (validates tokens, predicate references, dependency cycles, component refs),
* backed by a negative fixture suite proving validator fail-closed behavior,
* and backed by six active runtime enforcement hooks covering the full governance enforcement surface.

The most important single-sentence summary:

> **The governance specification has been translated into a runnable, validatable, plannable, blocker-aware (structural and runtime), verdict-producing (structural and runtime-aware), artifact-queryable, predicate-evaluating, hook-readable, compact-readiness-persisted, statically-hardened V1 runtime shell.**
