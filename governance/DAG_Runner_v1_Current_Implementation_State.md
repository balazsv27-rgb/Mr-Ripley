# DAG Runner v1 — Current Implementation State

## Executive Summary

`governance/dag\_runner/` is now a working V1 governance runtime shell for Mr. Ripley.

It can:

* load the root orchestration workflow,
* resolve and load the workflow package set,
* assemble a typed workflow specification,
* validate the structure fail-closed,
* compute a topological execution plan,
* analyze blocker coverage and references,
* compute a governance verdict,
* execute the workflow in V1 shell mode,
* and persist the run state into JSON.

This implementation is not a trading engine, not an MCP orchestration layer, and not a true skill-execution runtime. It is the executable governance layer that turns the package-based specification into a testable runtime surface.

\---

## 1\. Repository Structure

```text
governance/
└── dag\_runner/
    ├── \_\_init\_\_.py
    ├── models.py
    ├── loader.py
    ├── assembler.py
    ├── validator.py
    ├── planner.py
    ├── blockers.py
    ├── verdict.py
    ├── executor.py
    ├── state\_store.py
    ├── cli.py
    └── dag\_runner\_v\_1\_blueprint.md

tests/
└── governance/
    ├── test\_loader.py
    ├── test\_assembler.py
    ├── test\_validator.py
    ├── test\_planner.py
    ├── test\_blockers.py
    ├── test\_verdict.py
    └── test\_executor.py
```

\---

## 2\. Code File Inventory

### `governance/dag\_runner/\_\_init\_\_.py`

**Purpose:** package entry point.  
**Status:** technical support file.

**How to test**

```bash
python -c "import governance.dag\_runner; print('package ok')"
```

\---

### `governance/dag\_runner/models.py`

**Purpose:** Defines the typed data model used across the DAG runner.
             This is the canonical type system of the DAG runtime.
             These are not “static properties” — they are the contract boundary between every module.
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
python -c "from governance.dag\_runner.models import GovernanceRunState, WorkflowStep; print('models ok')"
```

**Expected result**

```text
models ok
```

\---

### `governance/dag\_runner/loader.py`

**Purpose:** Loads the root workflow YAML and all referenced workflow package YAML files.
             Transforms external YAML into raw in-memory structures.   
**What it does**

* reads `.claude/workflows/system-orchestration.yaml`
* resolves `assembly.packages`
* loads the 13 package YAML files
* fails closed on missing or invalid YAML

**How to test**

```bash
python -c "from governance.dag\_runner.loader import load\_workflow\_packages; r=load\_workflow\_packages(); print(r.manifest.workflow\_name, len(r.packages))"
```

**Current result**

* workflow name: `mr-ripley-governance-orchestration`
* loaded packages: `13`

\---

### `governance/dag\_runner/assembler.py`

**Purpose:** Assembles loaded workflow packages into a typed compiled workflow specification.
             This is the compiler’s “linker” phase, where the declarative system becomes a structured program.   
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
python -c "from governance.dag\_runner.loader import load\_workflow\_packages; from governance.dag\_runner.assembler import assemble\_workflow\_spec; loaded=load\_workflow\_packages(); spec=assemble\_workflow\_spec(loaded); print(spec.manifest.workflow\_name, len(spec.workflow\_steps), len(spec.skills), len(spec.artifacts), len(spec.blocking\_conditions), len(spec.stage\_gates), len(spec.subagents))"
```

**Current result**

* workflow steps: `18`
* skills: `13`
* artifacts: `19`
* blocking conditions: `12`
* stage gates: `4`
* subagents: `8`

\---

### `governance/dag\_runner/validator.py`

**Purpose:** Validates the assembled workflow specification.
             This is a fail-closed static verifier (like a type checker + linter).
             This is pre-execution enforcement — nothing dynamic here.

**What it does**

* validates required sections
* validates `depends\_on`
* validates output artifact references
* validates blocker references
* validates component references
* validates supported condition / `skip\_if` structures
* detects dependency cycles
* fails closed when the spec is invalid

**How to test**

```bash
python -c "from governance.dag\_runner.loader import load\_workflow\_packages; from governance.dag\_runner.assembler import assemble\_workflow\_spec; from governance.dag\_runner.validator import validate\_workflow\_spec; loaded=load\_workflow\_packages(); spec=assemble\_workflow\_spec(loaded); result=validate\_workflow\_spec(spec); print(result.is\_valid, len(result.issues))"
```

**Current result**

```text
True 0
```

\---

### `governance/dag\_runner/planner.py`

**Purpose:** Computes the topological execution order from the validated workflow spec.
             Transforms a validated spec into an executable DAG plan.
**What it does**

* builds a dependency graph
* performs topological sorting
* materializes execution order
* emits an `ExecutionPlan`

**How to test**

```bash
python -c "from governance.dag\_runner.loader import load\_workflow\_packages; from governance.dag\_runner.assembler import assemble\_workflow\_spec; from governance.dag\_runner.validator import validate\_or\_raise; from governance.dag\_runner.planner import build\_execution\_plan; loaded=load\_workflow\_packages(); spec=assemble\_workflow\_spec(loaded); validate\_or\_raise(spec); plan=build\_execution\_plan(spec); print(plan.workflow\_name, len(plan.ordered\_steps), plan.ordered\_step\_ids\[:5])"
```

**Current first five steps**

1. `load-context`
2. `classify-claims`
3. `normalize-terminology`
4. `route-claims-by-role`
5. `phase-check`

\---

### `governance/dag\_runner/blockers.py`

**Purpose:** Analyzes the relationship between the blocker registry and workflow step `raises` references.
             Currently: structural analysis only (not enforcement), a registry integrity checker, not a runtime gatekeeper.

**What it does**

* collects declared blockers
* collects referenced blockers from planned steps
* detects orphan blockers
* detects unknown blocker references
* reports structural consistency

**How to test**

```bash
python -c "from governance.dag\_runner.loader import load\_workflow\_packages; from governance.dag\_runner.assembler import assemble\_workflow\_spec; from governance.dag\_runner.validator import validate\_or\_raise; from governance.dag\_runner.planner import build\_execution\_plan; from governance.dag\_runner.blockers import analyze\_blockers; loaded=load\_workflow\_packages(); spec=assemble\_workflow\_spec(loaded); validate\_or\_raise(spec); plan=build\_execution\_plan(spec); summary=analyze\_blockers(spec, plan); print(len(summary.declared\_blockers), len(summary.referenced\_blockers), len(summary.orphan\_blockers), len(summary.unknown\_references), summary.is\_structurally\_consistent)"
```

**Current result**

* declared blockers: `12`
* referenced blockers: `17`
* orphan blockers: `0`
* unknown references: `0`
* structurally consistent: `True`

\---

### `governance/dag\_runner/verdict.py`

**Purpose:** Computes the governance verdict from validation and blocker analysis.
             Converts validation + blocker analysis into a governance verdict.
             The first “decision layer” in the system.

**Current V1 logic**

* validation failure → `blocked`
* unknown blocker references → `blocked`
* structural warning conditions → `review\_only`
* otherwise → `ready`

**How to test**

```bash
python -c "from governance.dag\_runner.loader import load\_workflow\_packages; from governance.dag\_runner.assembler import assemble\_workflow\_spec; from governance.dag\_runner.validator import validate\_workflow\_spec; from governance.dag\_runner.planner import build\_execution\_plan; from governance.dag\_runner.blockers import analyze\_blockers; from governance.dag\_runner.verdict import compute\_verdict; loaded=load\_workflow\_packages(); spec=assemble\_workflow\_spec(loaded); validation=validate\_workflow\_spec(spec); plan=build\_execution\_plan(spec); blockers=analyze\_blockers(spec, plan); verdict=compute\_verdict(validation, blockers); print(verdict.status, verdict.reasons)"
```

**Current result**

```text
ready \['Validation passed and blocker structure is consistent.']
```

\---

### `governance/dag\_runner/executor.py`

**Purpose:** builds the runtime state and executes the planned workflow in V1 shell mode.
                
**Important note**  
This is not true skill execution. It is a trace-producing shell runtime.

**What it does**

* walks the planned nodes in order
* builds a `GovernanceRunState`
* records `NodeResult` entries
* records `ExecutionTraceEvent` entries
* materializes artifact records
* stores the final verdict into the run state

**How to test**

```bash
python -c "from governance.dag\_runner.loader import load\_workflow\_packages; from governance.dag\_runner.assembler import assemble\_workflow\_spec; from governance.dag\_runner.validator import validate\_workflow\_spec; from governance.dag\_runner.planner import build\_execution\_plan; from governance.dag\_runner.blockers import analyze\_blockers; from governance.dag\_runner.verdict import compute\_verdict; from governance.dag\_runner.executor import execute\_plan; loaded=load\_workflow\_packages(); spec=assemble\_workflow\_spec(loaded); validation=validate\_workflow\_spec(spec); plan=build\_execution\_plan(spec); blockers=analyze\_blockers(spec, plan); verdict=compute\_verdict(validation, blockers); result=execute\_plan(spec, plan, verdict\_status=verdict.status); print(result.run\_state.final\_verdict, len(result.run\_state.node\_results), len(result.run\_state.execution\_trace), len(result.run\_state.artifacts))"
```

**Current result**

* final verdict: `ready`
* node results: `18`
* execution trace events: `38`
* artifacts: `19`

\---

### `governance/dag\_runner/state\_store.py`

**Purpose:** Persists the current run into machine-readable JSON.
             This is the serialization boundary of the runtime.
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

**Primary output**

* `governance\_run\_state.json`

**How to test**

```bash
python -c "from governance.dag\_runner.state\_store import generate\_and\_write\_run\_state; print(generate\_and\_write\_run\_state('.claude/workflows/system-orchestration.yaml'))"
```

\---

### `governance/dag\_runner/cli.py`

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
python -m governance.dag\_runner.cli

# show execution order
python -m governance.dag\_runner.cli --show-steps

# write run-state JSON
python -m governance.dag\_runner.cli --write-state

# full run
python -m governance.dag\_runner.cli --show-steps --write-state
```

**Current typical output**

* Validation: `PASS`
* Planned steps: `18`
* Executed steps: `18`
* Recorded trace events: `38`
* Verdict: `READY`

\---

### `governance/dag\_runner/dag\_runner\_v\_1\_blueprint.md`

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

\---

## 3\. Hook Implementation

The following runtime enforcement hooks are now implemented in `.claude/hooks/`.
They form the active governance enforcement surface that fires during Claude Code tool use and agent stop events.
All hooks share a common artifact contract via `.claude/hooks/lib/artifact_store.py`.

### Shared library: `.claude/hooks/lib/artifact\_store.py`

**Purpose:** Shared read/write contract for governance artifacts.
**Artifact location:** `.claude/run/artifacts/<name>.json`
**Provides:** `read_artifact(name)`, `write_artifact(name, data, produced_by)`, `artifact_exists(name)`
**Envelope schema:** `artifact`, `produced_by`, `session`, `timestamp`, `data`

\---

### `snapshot\_boundary\_guard.py`

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

\---

### `adapter\_schema\_guard.py`

**Hook event:** PostToolUse (Edit | Write)
**Layer:** C — Runtime Schema Integrity
**Action:** warn (exit 1) or block (exit 2)
**Scope predicate:** `adapter_registry_scope` (`layer2/adapters/**`, `layer2/config/**`)
**Blocking conditions raised:** `registry_violation`, `schema_drift_detected`
**Artifact written:** `adapter_schema_verdict`

**What it enforces**

* `registry_driven` (positive check) — adapter must import from `layer2.config.registry` or reference the registry
* `hardcoded_series_detected` — inline series ID lists, dicts, or per-series conditionals
* `implicit_interpretation_detected` — inline tier, staleness\_days, blocks\_snapshot, frequency, or include\_in\_snapshot assignments

Blocks (exit 2) when no registry usage is found at all.
Warns (exit 1) when violations appear alongside registry usage.

\---

### `live\_readiness\_claim\_blocker.py`

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

\---

### `role\_matched\_doc\_guard.py`

**Hook event:** Stop (SubagentStop)
**Layer:** A — Semantic Normalization
**Action:** warn (exit 1) or block (exit 2)
**Blocking conditions raised:** `role_mismatch_for_strong_claim`, `readme_layer2_used_as_override`, `canonical_conflict_unresolved`
**Artifact consumed:** `role_citation_verdict`

**What it enforces**

* `role_mismatch` — a canonical document was cited for a claim whose role belongs to a different canonical document (CLAUDE.md §2.2, §2.4)
* `readme_layer2_override` — README\_LAYER2.md was used to override a more role-specific canonical document on implementation state, architecture boundaries, or limitations

Blocks (exit 2) when a violation is attached to a strong claim (CLAUDE.md §10).
Warns (exit 1) otherwise.

\---

### `doc\_code\_sync\_guard.py`

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

\---

### `pre\_pr\_governance\_gate.py`

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

\---

### Shell stubs

Three shell hook stubs are present but not yet implemented:

* `auto-format.sh`
* `run-tests.sh`
* `security-scan.sh`

These are placeholder files and currently contain no logic.

\---

## 4\. Current Recognized Workflow Shape

|Slice|Value|
|-|-:|
|Workflow name|`mr-ripley-governance-orchestration`|
|Loaded packages|13|
|Workflow steps|18|
|Skills|13|
|Artifacts|19|
|Blocking conditions|12|
|Stage gates|4|
|Subagents|8|

### First five execution steps

1. `load-context`
2. `classify-claims`
3. `normalize-terminology`
4. `route-claims-by-role`
5. `phase-check`

\---

## 4\. Tests and Results

### Test file structure

```text
tests/governance/
├── test\_loader.py
├── test\_assembler.py
├── test\_validator.py
├── test\_planner.py
├── test\_blockers.py
├── test\_verdict.py
└── test\_executor.py
```

### What each test covers

#### `test\_loader.py`

Checks that:

* the root workflow loads
* the 13 packages load
* the workflow name is correct

#### `test\_assembler.py`

Checks that:

* the typed spec is assembled successfully
* the current counts match expected values

#### `test\_validator.py`

Checks that:

* the current assembled workflow validates cleanly
* issue count is zero

#### `test\_planner.py`

Checks that:

* the execution plan builds successfully
* the topological order starts with the expected five steps

#### `test\_blockers.py`

Checks that:

* there are 12 declared blockers
* there are 17 blocker references
* there are 0 orphan blockers
* there are 0 unknown references
* the blocker structure is consistent

#### `test\_verdict.py`

Checks that:

* the current workflow verdict is `ready`

#### `test\_executor.py`

Checks that:

* the V1 shell executor records a full run state
* there are 18 node results
* there are 38 trace events
* there are 19 artifact records

### Current test result

```text
7 passed in 0.53s
```

### Full test command

```bash
python -m pytest tests/governance -q
```

\---

## 5\. Current Run-State JSON Contents

`governance\_run\_state.json` currently contains:

* workflow metadata
* package / step / skill / artifact / blocker / stage gate / subagent counts
* validation status and issue list
* blocker summary counts
* verdict status and reasons
* execution order
* run id
* started\_at timestamp
* final verdict
* recorded node result count
* recorded artifact count
* recorded trace event count
* node result list
* artifact record list
* execution trace list

\---

## 6\. What Is Still Missing

|Component|Status|Meaning|
|-|-|-|
|`.claude/hooks/*.py`|**implemented**|six runtime enforcement hooks are in place and active|
|`.claude/hooks/lib/artifact\_store.py`|**implemented**|shared artifact read/write contract used by all hooks|
|`hook\_bridge.py`|not implemented|read-only API over persisted run state for hook consumption|
|predicate runtime evaluation|partial|validation exists, true runtime condition evaluation does not|
|artifact lifecycle handling|basic|no deeper missing / stale / blocked lifecycle|
|blocker runtime events|partial|structural blocker analysis exists, runtime blocker event handling does not|
|real skill execution|not implemented|executor is shell mode only|
|integration tests|partial|unit-style coverage exists, end-to-end CLI integration is still missing|
|shell hook stubs|not implemented|`auto-format.sh`, `run-tests.sh`, `security-scan.sh` are present but empty|

\---

## 7\. Recommended Next Steps

### Step 1 — Save this as a stable milestone

Commit this state as a dedicated milestone. Do not mix it with the next refactor wave.

### Step 2 — Add `test\_state\_store.py`

Validate that the persisted JSON really contains:

* verdict fields
* execution trace
* node results
* artifact records

### Step 3 — Add a CLI integration test

At minimum:

* CLI runs successfully
* exit code is 0
* verdict appears in output
* run-state file is created

### Step 4 — Implement `hook\_bridge.py`

The six runtime enforcement hooks in `.claude/hooks/` are now implemented and active.
`hook\_bridge.py` is the missing link: it will allow those hooks to query the DAG runner's persisted run state through a stable read-only API rather than parsing the raw JSON themselves.

First V1 version should expose read-only helpers over persisted run state:

* `get\_final\_verdict()`
* `has\_unresolved\_blocks()`
* `get\_required\_artifact(name)`
* `get\_recorded\_trace\_events()`
* `get\_pr\_readiness()`

### Step 5 — Implement `artifacts.py`

Move artifact-oriented logic into its own module:

* artifact state queries
* required artifact checks
* conditional artifact handling
* artifact summaries

### Step 6 — Deepen predicate runtime support

Only support explicit structured condition forms.
Do not introduce free-form expression behavior.

### Step 7 — Tighten blocker runtime and verdict logic

Do this only after:

* artifact state support
* predicate runtime evaluation
* hook bridge

### Step 8 — Deepen executor behavior

The current executor is a good shell runtime. Do not overcomplicate it too early.

\---

## 8\. Final Summary

DAG Runner v1 is currently:

* operational,
* tested,
* CLI-runnable,
* verdict-aware,
* execution-capable in shell mode,
* able to persist a machine-readable governance run state,
* and backed by six active runtime enforcement hooks covering the full governance enforcement surface.

The most important sentence in one line:

**the governance specification has already been translated into a runnable, validatable, plannable, blocker-aware, verdict-producing, persisted V1 runtime shell.





TO discuss:

Here is the remediation checklist, turned into concrete, file-by-file next work.**



**EXECUTION PRIORITY**

**Make runtime semantics real.**

**Add hook-facing read API.**

**Separate artifact policy from executor.**

**Expand failure-mode and integration tests.**

**Tighten types and small performance issues.**

**FILE-BY-FILE REMEDIATION CHECKLIST**

**governance/dag\_runner/validator.py**



**Why**

**The blueprint says validator should also check predicate references and validates tokens, not just dependencies, outputs, raises, components, conditions, and cycles. The current validator does not yet do that.**



**Change**



**Add \_validate\_step\_validates()**

**Add \_validate\_predicate\_references()**

**Add optional duplicate-output-producer validation**

**Add explicit hook/component registry validation if hooks registry becomes formal**



**Suggested additions**



**\_validate\_step\_validates(spec) -> list\[ValidationIssue]**

**\_validate\_predicate\_references(spec) -> list\[ValidationIssue]**



**Acceptance criteria**



**Unknown validates token fails validation**

**Unknown predicate reference fails validation**

**New fixture tests cover both**

**governance/dag\_runner/executor.py**



**Why**

**Right now executor records a shell pass for every step, never evaluates condition / skip\_if, never emits real BlockingEvents, and never changes node status based on runtime semantics. That is the biggest roadmap gap.**



**Change**



**Evaluate supported condition forms before executing a node**

**Respect skip\_if**

**Emit SKIP when skip condition is satisfied**

**Emit FAIL or halt when unsupported runtime condition is encountered**

**Append real BlockingEvent objects into run\_state.blocking\_conditions**

**Record condition evaluation in execution trace**



**Suggested helper functions**



**\_evaluate\_condition(condition, run\_state) -> tuple\[bool, dict]**

**\_evaluate\_skip\_if(skip\_if, run\_state) -> tuple\[bool, dict]**

**\_raise\_blocking\_events(step, run\_state) -> None**



**Acceptance criteria**



**A satisfied skip\_if produces NodeResult.status == "SKIP"**

**Unsupported runtime condition fails closed**

**run\_state.blocking\_conditions is populated from actual runtime events**

**Trace contains condition evaluation events**

**governance/dag\_runner/blockers.py**



**Why**

**Current blocker logic is structurally correct, but still registry-analysis only. The roadmap wants unresolved-block failure semantics, not just reference hygiene.**



**Change**



**Keep current structural summary**

**Add runtime-oriented summary helper over GovernanceRunState**

**Distinguish:**

**declared blockers**

**referenced blockers**

**raised blockers**

**unresolved blockers**

**fatal unresolved blockers**



**Suggested additions**



**analyze\_runtime\_blockers(run\_state, spec) -> RuntimeBlockerSummary**

**has\_unresolved\_fatal\_blocks(...) -> bool**



**Acceptance criteria**



**Runtime blocker summary can answer:**

**are there unresolved blocks?**

**are any fatal?**

**which steps raised them?**

**governance/dag\_runner/verdict.py**



**Why**

**Current verdict logic only looks at validation result plus structural blocker summary. It does not yet incorporate runtime block state, required artifact presence, or workflow completion.**



**Change**



**Split verdict into:**

**structural verdict**

**runtime verdict**

**Add optional execution-aware verdict computation**



**Suggested additions**



**compute\_structural\_verdict(validation\_result, blocker\_summary)**

**compute\_runtime\_verdict(validation\_result, blocker\_summary, run\_state, artifact\_summary)**



**Recommended runtime inputs**



**unresolved runtime blockers**

**required outputs present**

**workflow completed**

**final gate result**



**Acceptance criteria**



**Runtime unresolved fatal block -> blocked**

**Missing required artifact -> blocked or review\_only, based on policy**

**Full clean run -> ready**

**governance/dag\_runner/state\_store.py**



**Why**

**This is already useful, but it needs to become the stable hook contract. The roadmap explicitly wants hooks to read runner state and gate commit/push.**



**Change**



**Add compact hook-facing fields in persisted JSON**

**Preserve current rich details, but add a concise top-level machine contract**



**Recommended new top-level fields**



**workflow\_completed: bool**

**required\_outputs\_present: bool**

**unresolved\_blocking\_conditions: list\[...]**

**fatal\_unresolved\_block\_count: int**

**pr\_readiness: str**

**hook\_readiness: dict**



**Acceptance criteria**



**Hook code can determine readiness from a few top-level fields**

**No need for hooks to re-derive logic from raw trace**

**governance/dag\_runner/cli.py**



**Why**

**CLI is good, but it should eventually expose the stronger runtime semantics and integration health more clearly.**



**Change**



**Add --json-summary option**

**Add --fail-on-review-only option for stricter CI usage**

**Print unresolved runtime block counts when runtime blocker engine exists**

**Print required artifact status when artifact policy exists**



**Acceptance criteria**



**CLI can be used both by humans and CI**

**Summary output includes readiness-critical signals**

**governance/dag\_runner/planner.py**



**Why**

**Functionally correct, but mildly inefficient and a bit too forgiving. It currently ignores ordered nodes not present in workflow\_steps, even though validator should have guaranteed consistency.**



**Change**



**Replace pop(0) with a queue/heap approach**

**Fail instead of silently ignoring missing ordered nodes**

**Optionally preserve deterministic sort with heapq**



**Acceptance criteria**



**No silent skip in \_build\_planned\_nodes()**

**Same deterministic order as today**

**Cleaner asymptotic behavior**

**governance/dag\_runner/assembler.py**



**Why**

**Overall good, but still tightly coupled to current YAML shapes. That is acceptable for V1, though a few hardening checks would help.**



**Change**



**Validate uniqueness of artifact producers if roadmap requires it**

**Normalize more package metadata into raw\_sections**

**Add explicit manifest expectation checks if package model requires them**



**Acceptance criteria**



**Duplicate artifact producers fail closed**

**Assembly errors become more specific when package shape drifts**

**governance/dag\_runner/models.py**



**Why**

**The model layer is strong, but one roadmap expectation is still underused: BlockingEvent exists, yet runtime code barely uses it. Also some types could become more explicit in downstream modules.**



**Change**



**Keep models mostly stable**

**Add any missing runtime summary types only if needed**

**Ensure downstream modules type their inputs explicitly against these models**



**Acceptance criteria**



**No spec/plan/verdict loose typing in public functions where model types are known**

**NEW FILES TO ADD**

**governance/dag\_runner/hook\_bridge.py**



**Priority: very high**



**Why**

**This is the clearest missing roadmap piece. Both roadmap and blueprint expect hooks to read runner state.**



**First version should provide**



**get\_final\_verdict(state\_path=...)**

**has\_unresolved\_blocks(state\_path=...)**

**get\_required\_artifact(name, state\_path=...)**

**get\_recorded\_trace\_events(state\_path=...)**

**get\_pr\_readiness(state\_path=...)**



**Implementation base**



**Use load\_run\_state() from state\_store.py**



**Acceptance criteria**



**Hook scripts do not parse JSON themselves**

**API is read-only**

**Missing state file fails closed**

**governance/dag\_runner/artifacts.py**



**Priority: high**



**Why**

**Blueprint includes it, roadmap implies it, current implementation smears artifact logic across executor and state store.**



**First version should provide**



**build\_artifact\_summary(spec, run\_state)**

**get\_required\_artifacts(spec)**

**get\_missing\_required\_artifacts(spec, run\_state)**

**artifact\_exists(run\_state, name)**



**Acceptance criteria**



**Required artifact checking is no longer hand-coded in later modules**

**Verdict and hook bridge can depend on artifact summary cleanly**

**governance/dag\_runner/predicates.py**



**Priority: medium-high**



**Why**

**Validator already knows supported condition types; runtime executor needs a real evaluator.**



**First version should support only**



**artifact\_exists**

**artifact\_missing**

**artifact\_field\_equals**

**artifact\_field\_not\_equals**



**Recommended interface**



**evaluate\_condition(condition: dict\[str, Any], run\_state: GovernanceRunState) -> ConditionResult**



**Acceptance criteria**



**Unsupported type raises fail-closed runtime error**

**Executor uses this rather than its own local ad hoc logic**

**TESTS TO ADD NEXT**

**tests/governance/test\_state\_store.py**



**Priority: very high**

**Check that persisted JSON contains:**



**verdict\_status**

**verdict\_reasons**

**recorded\_trace\_events**

**node\_results**

**artifact\_records**

**future workflow\_completed / required\_outputs\_present fields**

**tests/governance/test\_cli\_integration.py**



**Priority: very high**

**Run CLI end-to-end and assert:**



**exit code 0**

**output contains Verdict:**

**output contains Executed steps:**

**state file exists**

**tests/governance/test\_validator\_failures.py**



**Priority: high**

**Add fixture-based failures for:**



**missing dependency**

**missing skill reference**

**missing blocker reference**

**unsupported condition structure**

**dependency cycle**

**invalid validates token**

**invalid predicate reference**



**This is explicitly in the spirit of the blueprint hardening guidance.**



**tests/governance/test\_hook\_bridge.py**



**Priority: high**

**Once hook\_bridge.py exists:**



**read final verdict**

**detect unresolved blocks**

**fetch required artifact**

**fail closed on missing state file**

**SUGGESTED IMPLEMENTATION ORDER**

**Phase 1**

**hook\_bridge.py**

**test\_state\_store.py**

**test\_cli\_integration.py**

**Phase 2**

**artifacts.py**

**predicates.py**

**executor integration with runtime condition evaluation**

**Phase 3**

**runtime blocker events in executor**

**runtime-aware verdict.py**

**richer persisted hook contract in state\_store.py**

**Phase 4**

**validator expansion for predicates + validates**

**negative fixture suite**

**planner cleanup and minor performance polish**

**MINIMAL “DONE” DEFINITION FOR NEXT SPRINT**



**I would call the next sprint successful if all of this is true:**



**hooks can read persisted runner state through hook\_bridge.py**

**executor evaluates supported conditions**

**executor records runtime BlockingEvents**

**artifact requiredness is checked through artifacts.py**

**verdict can block on unresolved runtime blockers**

**state JSON exposes a compact hook-facing readiness contract**

**new negative and integration tests are green**



**That gets you from “good shell” to “actual governance enforcement surface,” which is what the roadmap has been hinting at all along, with admirable persistence and only moderate cruelty.**

