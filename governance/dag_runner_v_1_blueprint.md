# DAG Runner v1 — Mr. Ripley

## Purpose
Build a fail-closed governance DAG runner for Mr. Ripley from the `.claude/workflows/system-orchestration.yaml` root manifest and its package files.

The runner is intended to become the first real executable governance layer for the project. It should not be a generic workflow engine and it should not attempt to implement Layer-3 trading execution. Its job is to:

- assemble workflow packages,
- validate the assembled governance specification,
- build a typed execution graph,
- plan and execute in topological order,
- evaluate blocking conditions,
- materialize artifacts,
- persist run state,
- and expose a read-only hook bridge for later hook enforcement.

---

## Where the project stands now

The project has moved past the purely documentary stage.

What is already in place:
- the canonical 7-document documentation set,
- an updated `CLAUDE_updated.md`,
- a split package-based orchestration model,
- a full `.claude/workflows/packages/` governance package set,
- a working skills library,
- planner / implementer / reviewer agents,
- settings and local settings,
- bootstrap design notes,
- rules for code conventions and git workflow,
- and a partially uploaded Layer-2 runtime surface.

This means the governance specification side is mature enough to support a DAG runner implementation.

What is **not** in place yet:
- implemented runtime hooks,
- uploaded command files,
- uploaded plans,
- full Layer-2 runtime coverage (`db.py`, `constants.py` still missing),
- and any Layer-3 execution runtime.

This is acceptable for DAG Runner v1.

---

## What the runner is and is not

### The runner **is**
- a governance-spec assembler,
- a validation boundary,
- a typed graph planner,
- a fail-closed execution coordinator,
- an artifact and blocker recorder,
- a state persistence layer,
- and a hook-read bridge.

### The runner is **not**
- a general-purpose orchestration engine,
- a substitute for skills as human-readable governance instructions,
- a hook runtime,
- an MCP tool manager,
- a Layer-3 decision engine,
- or a trading executor.

---

## Why this runner is the right next step

The project already has:
- a compiled root manifest,
- section-owned workflow packages,
- stage gates,
- blocking conditions,
- predicates,
- artifact definitions,
- workflow steps,
- subagent declarations,
- interpretation policy,
- verification ledger logic,
- and a canonical documentation authority model.

Without a DAG runner, these remain a static governance design.

With a DAG runner, they become:
- loadable,
- validated,
- executable,
- traceable,
- and inspectable.

The DAG runner is therefore the bridge between “well-structured governance documentation” and “actual governance runtime”.

---

## Current confirmed input inventory

### Constitution / orchestration inputs
- `CLAUDE_updated.md`
- `.claude/workflows/system-orchestration.yaml`
- `.claude/workflows/PACKAGE_MODEL.md`
- `.claude/workflows/packages/constitution.yaml`
- `.claude/workflows/packages/manifest.yaml`
- `.claude/workflows/packages/predicates.yaml`
- `.claude/workflows/packages/skills.yaml`
- `.claude/workflows/packages/hooks.yaml`
- `.claude/workflows/packages/subagents.yaml`
- `.claude/workflows/packages/artifacts.yaml`
- `.claude/workflows/packages/interpretation-policy.yaml`
- `.claude/workflows/packages/stage-gates.yaml`
- `.claude/workflows/packages/blocking-conditions.yaml`
- `.claude/workflows/packages/verification-ledger.yaml`
- `.claude/workflows/packages/workflow-steps.yaml`
- `.claude/workflows/packages/execution-metadata.yaml`

### Canonical documentation inputs
- `README_v1.md`
- `README_LAYER2.md`
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
- `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
- `roadmap.md`

### `.claude` support inputs
- `.claude/agents/planner.md`
- `.claude/agents/implementer.md`
- `.claude/agents/reviewer.md`
- `.claude/settings.json`
- `.claude/settings.local.json`
- `.claude/rules/code-conventions.md`
- `.claude/rules/git-workflow.md`

### Skill inventory currently available
- `adapter-schema-review`
- `build-sequence-compliance-check`
- `canonical-terminology-map`
- `change-impact-audit`
- `doc-code-sync-rules`
- `doc-truth-classification`
- `role-matched-citation-check`
- `runtime-artifact-hygiene-check`
- `snapshot-boundary-check`
- `snapshot-contract-check`
- `verification-ledger-update`
- `verification-matrix-update-method`
- `skills.md`

### Bootstrap references currently available
- `bootstrap-brief.md`
- `candidate-agents.md`
- `candidate-commands.md`
- `candidate-hooks.md`
- `candidate-skills.md`
- `extracted-patterns.md`
- `mcp-bootstrap-notes.md`

### Partial Layer-2 runtime currently available
- `layer2/clock.py`
- `layer2/alignment.py`
- `layer2/config/registry.py`
- `layer2/config/series_registry.json`
- `layer2/adapters/gold_adapter.py`
- `layer2/adapters/move_adapter.py`
- `layer2/adapters/gld_holdings_adapter.py`
- `layer2/adapters/fred_loader.py`
- `layer2/adapters/quality_gate.py`
- `layer2/adapters/snapshot_publisher.py`

### Still not uploaded
- `.claude/commands/*`
- `.claude/hooks/*`
- `.claude/plans/*`
- `layer2/db.py`
- `layer2/constants.py`
- original `CLAUDE.md`
- `.mcp.json`
- `requirements.txt`

---

## Key architectural conclusions from the current state

### 1. Governance spec is sufficient for DAG v1
The workflow package set is complete enough to support:
- assembly,
- validation,
- graph planning,
- blocking evaluation,
- artifact registry binding,
- and persisted run state.

### 2. Hooks are not required to begin
Runtime hooks are not yet implemented, but the hook specification already exists in the workflow package model and bootstrap materials. That is enough to design the hook bridge contract now.

### 3. Skills are registry-backed references, not executable programs
The `SKILL.md` files are governance instructions. DAG v1 should reference and validate them, not attempt to execute them as machine code.

### 4. Layer-2 runtime is becoming visible but is not a hard prerequisite
Enough Layer-2 code is available to understand the project’s fail-closed truth-layer discipline, but the DAG runner does not need full Layer-2 runtime parsing in v1.

### 5. There is already one important runtime/doc sync warning
The GLD holdings adapter now uses a Yahoo-based proxy source, while `series_registry.json` still describes the source as `spdr_gld_archive`. This is a runtime/documentation sync issue to track, though it does not block DAG Runner v1.

---

## V1 scope

### Included
- YAML/package loader
- assembled spec model
- validation pass
- node taxonomy
- dependency resolver
- execution planner
- `GovernanceRunState`
- `NodeResult`
- `ArtifactRecord`
- blocker engine
- final verdict
- hook bridge read API
- persisted run-state output
- supported structured condition evaluation for v1

### Not included yet
- actual hook runtime implementation
- MCP orchestration
- full subagent runtime execution
- Layer-3 execution
- live execution or trading logic
- machine execution of SKILL markdown files
- code-aware validator behavior against full Layer-2 runtime

---

## Suggested repo structure

```text
governance/
  dag_runner/
    __init__.py
    models.py
    loader.py
    assembler.py
    validator.py
    planner.py
    executor.py
    blockers.py
    artifacts.py
    verdict.py
    hook_bridge.py
    predicates.py
    skills_registry.py
    state_store.py
    cli.py

tests/
  governance/
    fixtures/
    test_loader.py
    test_assembler.py
    test_validator.py
    test_planner.py
    test_blockers.py
    test_hook_bridge.py
    test_state_store.py
```

---

## Typed model layer

### Core models
- `WorkflowPackageSpec`
- `AssembledWorkflowSpec`
- `WorkflowStep`
- `BlockingCondition`
- `ArtifactSpec`
- `PredicateSpec`
- `SkillSpec`
- `SubagentSpec`
- `StageGateSpec`
- `InterpretationPolicy`
- `VerificationLedgerSpec`
- `ManifestSpec`
- `ExecutionMetadataSpec`

### Runtime models
- `GovernanceRunState`
- `NodeResult`
- `ArtifactRecord`
- `BlockingEvent`
- `ExecutionTraceEvent`
- `FinalVerdict`
- `ConditionEvaluationResult`

---

## Node taxonomy

In DAG v1, use these node types:
- `workflow_step`
- `skill`
- `artifact_gate`
- `predicate_gate`
- `blocking_evaluator`
- `stage_gate`
- `subagent_dispatch`
- `verification_update`
- `final_gate`

---

## Suggested GovernanceRunState fields

```python
run_id: str
started_at: datetime
constitution_version: str | None
orchestration_version: str | None
current_phase: str | None
active_claims: list[dict]
node_results: dict[str, NodeResult]
artifacts: dict[str, ArtifactRecord]
blocking_conditions: list[BlockingEvent]
warnings: list[str]
execution_trace: list[ExecutionTraceEvent]
final_verdict: FinalVerdict | None
```

---

## Suggested NodeResult fields

```python
node_name: str
node_type: str
status: Literal["PASS", "WARN", "FAIL", "SKIP"]
summary: str
evidence: list[str]
produced_artifacts: list[str]
triggered_blocks: list[str]
inference_used: bool
```

---

## Suggested ArtifactRecord fields

```python
name: str
producer_step: str
status: Literal["present", "missing", "blocked", "stale"]
payload: dict
```

---

## Main pipeline

### 1. Loader
- read the root manifest from `system-orchestration.yaml`
- resolve the package list
- load `packages/*.yaml`

### 2. Assembler
- merge sections according to section ownership
- build the assembled workflow spec
- compare it against manifest expectations

### 3. Validator
- validate required sections
- validate step dependencies
- validate predicate references
- validate blocking-condition references
- validate stage-gate references
- validate skill references against the declared skill registry
- validate component references against skills / subagents / hooks registries
- validate step outputs against the artifact registry
- validate `raises` and `validates` references against known registries
- validate whether `condition` / `skip_if` structures use supported v1 condition forms
- detect cycles
- fail closed if the spec is invalid

### 4. Planner
- build a graph from the workflow steps
- compute topological order
- identify the active execution path

### 5. Executor
- run nodes in order
- update runner state after each node
- materialize artifacts
- call the blocker engine
- evaluate only supported v1 conditional forms
- fail closed on unsupported structured conditions instead of silently ignoring them

### 6. Blocker engine
- evaluate rules from `blocking-conditions.yaml`
- collect blocking events raised by workflow execution
- return a fail-closed verdict when unresolved blocks exist

### 7. Verdict
- aggregate the run result
- emit a final verdict such as `ready`, `review_only`, or `blocked`

### 8. Hook bridge
- expose a stable read API for hooks:
  - `has_unresolved_blocks()`
  - `get_required_artifact(name)`
  - `get_final_verdict()`
  - `get_guard_report()`
  - `get_phase_alignment_status()`
- remain strictly read-only
- consume persisted run state rather than mutating runtime state

---

## Persisted run-state requirement

V1 should persist the latest completed run state into a stable machine-readable format.

Suggested output:
- `governance_run_state.json`

Minimum contents:
- run metadata
- execution trace summary
- artifacts produced
- blocker list
- unresolved blocker list
- final verdict
- warnings

This file becomes the safest initial contract between:
- the DAG runner,
- future hook scripts,
- and future governance reporting tools.

---

## Condition handling policy for v1

Conditions are not fully general expressions yet.

Therefore v1 should:
- support explicitly structured condition forms already used by the workflow spec,
- reject unsupported condition structures fail-closed,
- never silently ignore unknown condition types,
- and record condition evaluation in the execution trace.

This is stricter and safer than pretending all conditions are false or all are ignorable.

---

## Validator responsibilities in detail

The validator should explicitly check:
- required package sections are present,
- step `depends_on` links resolve,
- no cycle exists in workflow dependencies,
- predicate references exist,
- blocking-condition references exist,
- stage-gate references exist,
- skill references exist in the declared registry,
- component references resolve against the correct registry type,
- step `outputs` resolve against the artifact registry,
- `raises` resolve against blocking conditions,
- `validates` resolve against the known validation token set,
- `condition` and `skip_if` structures are supported,
- and package assembly produces a coherent compiled spec.

This is what turns the runner into a governance compiler rather than a thin YAML loader.

---

## Design review

### What is already strong

#### 1. Clean separation of responsibilities
The blueprint clearly separates:
- YAML/package loading and assembly,
- validation,
- graph construction and planning,
- execution and blocker evaluation,
- and the hook-bridge read API.

This matches the package-compiled orchestration model and keeps the runner from collapsing into a single opaque executor.

#### 2. Fail-closed behavior starts at validation
Validation is not cosmetic. It is a first-class safety boundary.
The validator is expected to stop execution when the spec is inconsistent, incomplete, cyclic, or references undeclared workflow elements.

#### 3. Strong typed runtime model
The proposed models cover the key workflow sections and provide enough runtime state to support:
- execution tracing,
- artifact collection,
- blocker evaluation,
- and later hook consumption.

#### 4. Realistic implementation phasing
The sprint split is sensible:
- Sprint 1 gives a testable assembly/validation core,
- Sprint 2 adds actual planning and blocker logic,
- Sprint 3 adds execution, hook bridge, and CLI behavior.

#### 5. CLI is useful already in v1
Even before hook runtime exists, a CLI-driven runner provides manual validation, execution-plan inspection, and blocker visibility.

### Important design clarifications

#### 1. Skills are registry-backed references in v1
Skill nodes should not be interpreted as executable code modules in v1.
`SKILL.md` files are human-readable governance instructions, not machine-executable programs.

In v1, the runner should:
- validate that every referenced `skill:<name>` exists in the declared skill registry,
- preserve the skill reference in the execution graph,
- and treat skill execution as a resolved workflow node type, not as parsed code execution.

#### 2. Predicate handling should be selective, not ignored
Predicates and step conditions are not fully general executable expressions yet.
However, some condition structures already appear in a structured form.

Therefore v1 should:
- evaluate only explicitly supported structured condition forms,
- reject unsupported condition structures fail-closed,
- never silently skip or ignore conditions that it cannot interpret.

#### 3. Hook bridge must remain read-only
The hook bridge should expose post-run state only.
Hooks must not mutate runner state.
A persisted runner-state artifact is sufficient for v1, and is the safest contract between the DAG runner and future hook implementations.

#### 4. Blocking evaluation can be partial in v1
The runner does not need to execute hook logic itself.
It only needs to:
- collect blocking events raised by steps,
- reconcile them against the blocking-condition registry,
- and compute whether unresolved blocks remain.

That is enough for a safe first blocker engine.

#### 5. `rename-invariance-check` is declared, not missing
The workflow references `rename-invariance-check`, and the declared skill registry also includes it.
So this is not a missing workflow declaration problem.
The validator should still verify that the referenced skill exists in the registry and, where applicable, that the corresponding skill artifact is physically present.

#### 6. Layer-2 runtime code is not required for DAG v1
The governance DAG runner can be built from workflow packages, canonical documents, skills, agents, and settings without loading `layer2/` Python code.
That code surface becomes relevant later for code-aware skill execution and deeper runtime validation.

#### 7. `CLAUDE.md` content is not a hard runtime dependency for v1
The package constitution and manifest metadata are sufficient for building the initial governance runtime.
`CLAUDE.md` remains important as project constitution, but the runner does not need full direct parsing of the markdown file in v1.

### Additional validator requirements
The validator should explicitly check:
- step `outputs` against the artifact registry,
- step `component` references against skills / subagents / hooks registries,
- `raises` against the blocking-condition registry,
- `validates` against the known validation token set,
- `condition` and `skip_if` structure support,
- and registry-backed skill existence.

### Testing guidance
After Sprint 1, add fixture-based tests for at least:
- valid package assembly,
- missing skill reference,
- missing predicate reference,
- missing blocking-condition reference,
- cyclic workflow dependency,
- unsupported condition structure.

These cases will harden the runner before execution logic becomes more complex.

---

## Sprint plan

### Sprint 1 — Assembly and validation core
Deliverables:
- `models.py`
- `loader.py`
- `assembler.py`
- `validator.py`

Expected outcome:
- the runner can load the root manifest,
- assemble packages into one compiled spec,
- validate references and structure,
- and fail closed on invalid workflow definitions.

### Sprint 2 — Planning and verdict core
Deliverables:
- `planner.py`
- `artifacts.py`
- `blockers.py`
- `verdict.py`

Expected outcome:
- the runner can build a typed graph,
- compute a topological execution order,
- maintain artifact state,
- and compute a blocker-aware verdict.

### Sprint 3 — Execution and integration shell
Deliverables:
- `executor.py`
- `hook_bridge.py`
- `state_store.py`
- `cli.py`
- tests

Expected outcome:
- the runner can execute nodes in order,
- persist run state,
- and expose stable post-run state for hooks and external inspection.

---

## Immediate implementation target

Start with:
- `models.py`
- `loader.py`
- `assembler.py`
- `validator.py`

This is the minimum viable governance runtime core.

---

## Confirmed repo file map (from available inventory)

```text
Mr-Ripley/
│
├── .claude/                                                 [UPLOADED: structure known]
│   │
│   ├── agents/                                              [UPLOADED: 3 files]
│   │   ├── planner.md                                       ✅ ACCEPTED
│   │   ├── implementer.md                                   ✅ ACCEPTED
│   │   └── reviewer.md                                      ✅ ACCEPTED
│   │
│   ├── bootstrap/                                           [UPLOADED: 7 files]
│   │   ├── bootstrap-brief.md                               ✅ ACCEPTED
│   │   ├── candidate-agents.md                              ✅ ACCEPTED
│   │   ├── candidate-commands.md                            ✅ ACCEPTED
│   │   ├── candidate-hooks.md                               ✅ ACCEPTED
│   │   ├── candidate-skills.md                              ✅ ACCEPTED
│   │   ├── extracted-patterns.md                            ✅ ACCEPTED
│   │   └── mcp-bootstrap-notes.md                           ✅ ACCEPTED
│   │
│   ├── commands/                                            🔒 (not uploaded; design known)
│   │
│   ├── hooks/                                               🔒 (not uploaded; candidate design known)
│   │
│   ├── plans/                                               🔒 (not uploaded)
│   │
│   ├── rules/                                               [UPLOADED: 2 files]
│   │   ├── code-conventions.md                              ✅ ACCEPTED
│   │   └── git-workflow.md                                  ✅ ACCEPTED
│   │
│   ├── skills/                                              [UPLOADED: 12 skills + skills.md]
│   │   ├── adapter-schema-review/                           ✅
│   │   ├── build-sequence-compliance-check/                 ✅
│   │   ├── canonical-terminology-map/                       ✅
│   │   ├── change-impact-audit/                             ✅
│   │   ├── doc-code-sync-rules/                             ✅
│   │   ├── doc-truth-classification/                        ✅
│   │   ├── role-matched-citation-check/                     ✅
│   │   ├── runtime-artifact-hygiene-check/                  ✅
│   │   ├── snapshot-boundary-check/                         ✅
│   │   ├── snapshot-contract-check/                         ✅
│   │   ├── verification-ledger-update/                      ✅
│   │   ├── verification-matrix-update-method/               ✅
│   │   └── skills.md                                        ✅ ACCEPTED
│   │
│   ├── workflows/                                           [UPLOADED: full packages directory]
│   │   ├── PACKAGE_MODEL.md                                 ✅ ACCEPTED
│   │   ├── system-orchestration.yaml                        ✅ ACCEPTED
│   │   └── packages/                                        [13 files, all accepted]
│   │
│   ├── settings.json                                        ✅ ACCEPTED
│   └── settings.local.json                                  ✅ ACCEPTED
│
├── Documentation/                                           [LOGICAL GROUPING: 9 uploaded files]
│
├── layer2/                                                  [PARTIALLY UPLOADED]
│   ├── adapters/
│   │   ├── gold_adapter.py                                  ✅ ACCEPTED
│   │   ├── move_adapter.py                                  ✅ ACCEPTED
│   │   ├── gld_holdings_adapter.py                          ✅ ACCEPTED
│   │   ├── fred_loader.py                                   ✅ ACCEPTED
│   │   ├── quality_gate.py                                  ✅ ACCEPTED
│   │   └── snapshot_publisher.py                            ✅ ACCEPTED
│   ├── config/
│   │   ├── series_registry.json                             ✅ ACCEPTED
│   │   └── registry.py                                      ✅ ACCEPTED
│   ├── clock.py                                             ✅ ACCEPTED
│   ├── alignment.py                                         ✅ ACCEPTED
│   ├── db.py                                                🔒
│   └── constants.py                                         🔒
│
├── FRED/                                                    🔒
├── .secrets/                                                🔒
├── CLAUDE.md                                                🔒
├── .mcp.json                                                🔒
└── requirements.txt                                         🔒
```

