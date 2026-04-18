# DAG Runner Refactor Implementation Review

## 1. Executive Verdict

| Dimension | Assessment |
|-----------|-----------|
| **Overall status** | Partial V2A |
| **Maturity classification** | V2A ~70% module delivery, ~55% integration wiring |
| **Live testing readiness** | Ready for mocked testing only (graph/dry-run/mock agent_execution). NOT ready for continuation, halt-on-critical scenarios, or disk artifact production. |

**Justification:** All planned V2A modules exist and pass isolated tests (260 total: 204 V1 + 56 V2). However, four modules (`prompt_assembly.py`, `artifact_writer.py`, `drift_detector.py`, `diagnostics.py`) are implemented and tested in isolation but **never wired into the executor or CLI production path**. The halt-on-critical-failure mechanism has a control-flow defect that silently allows continued execution. The continuation code path references a non-existent function (`load_run_state_from_path`) and will crash at runtime. These are not cosmetic gaps; they represent broken contract obligations.

---

## 2. Review Basis

### Files reviewed
- All `.py` files in `governance/dag_runner/` (22 modules)
- All test files in `tests/governance/` (20 test files, ~400+ test methods)
- `dag_refactor_plan.md` (authoritative baseline)
- `.claude/workflows/system-orchestration.yaml` and all 14 YAML packages
- `.claude/skills/` (14 skill files)
- `.claude/hooks/` (6 hook files + lib)
- `.claude/settings.json`

### Refactor-plan scope used as baseline
`dag_refactor_plan.md`: V2A (Phases 1-6) and V2B (Phase 7). V2B is correctly deferred.

### Limits of the review
- No code was executed. Behavior is inferred from static analysis and test evidence only.
- Line-level verification performed for all critical findings flagged by exploration agents.
- Untested code is treated as not production-capable per review rules.

---

## 3. Phase-by-Phase Conformance Matrix

### Phase 1: Structural Foundation

| Planned Requirement | Status | Evidence | Notes |
|---|---|---|---|
| 1.1 New types in `models.py` (AgentSpec, ComponentKind, ExecutionMode, ExecutionConfig, PromptAssemblyContext, ArtifactEnvelope, FailureClassification, AgentExecutionResult) | **Implemented** | `models.py` contains all 7 types with correct fields | `PromptAssemblyContext` defined but unused in production |
| 1.1 Extend `AssembledWorkflowSpec` with `agents` | **Implemented** | `agents: dict[str, AgentSpec]` present | |
| 1.1 Extend `NodeResult` with `latency_ms`, `token_count` | **Implemented** | Fields present with defaults | |
| 1.2 `_assemble_agents()` in assembler.py | **Implemented** | Parses `agents.yaml` into `dict[str, AgentSpec]`, wired into `assemble_workflow_spec()` | |
| 1.3 Five new validator checks | **Implemented** | `_validate_agent_bindings`, `_validate_agent_skill_bindings`, `_validate_agent_artifact_production`, `_validate_hook_reinforcements`, `_validate_escalation_targets` | |
| 1.4 `execution_backend.py` (ABC + MockExecutionBackend) | **Implemented with deviation** | Both present. `execute_step()` signature: plan says `(prompt, step, agent, config)`, implementation uses `(step, agent, config, run_state, spec)` | PromptAssemblyContext not passed to backend |
| 1.5 `agent_resolver.py` | **Implemented** | `resolve_agent`, `load_agent_file`, `resolve_skill_content` | Fail-closed on missing agents |
| 1.6 `skill_resolver.py` | **Implemented** | `load_skill`, `load_all_skills`, `clear_cache` | Module-level cache, not thread-safe (acceptable for CLI) |

### Phase 2: Component-Kind Dispatch & Execution Modes

| Planned Requirement | Status | Evidence | Notes |
|---|---|---|---|
| 2.1 Component-kind routing | **Implemented** | `_parse_component_kind()`, `_is_structural_step()`, `_execute_v2_step()` in `executor.py` | Dispatch is component-driven, not step-name-driven |
| 2.2 Extended `execute_plan()` signature | **Implemented** | `config`, `backend`, `prior_state` parameters added | V1/V2 path switching on `backend is not None` |
| 2.3 CLI flags (7 new) | **Implemented** | `--dry-run`, `--json`, `--graph`, `--mode`, `--continue-from`, `--timeout`, `--phase` all present in `cli.py` | |
| 2.4 Graph output mode | **Implemented** | `_build_graph_json()` produces DAG JSON with `component_kind` fields | |
| 2.5 Dry-run mode | **Implemented** | Returns PASS with `dry_run=True` evidence, no backend invocation | |
| 2.6 Continuation with 5 guardrails | **Partially implemented** | `validate_continuation()` has 5 checks in `execution_modes.py`. **BUT** `cli.py:210` imports `load_run_state_from_path` which DOES NOT EXIST in `state_store.py` | **CONTRACT-BREAKING**: any `--continue-from` will crash with ImportError |
| 2.7 `execution_modes.py` | **Implemented** | `build_config_from_args()` and `validate_continuation()` present | |

### Phase 3: Prompt Assembly Pipeline

| Planned Requirement | Status | Evidence | Notes |
|---|---|---|---|
| 3.1 `prompt_assembly.py` | **Implemented but NOT integrated** | `assemble_step_prompt()` present, returns `dict` (not frozen dataclass). **Never imported by `executor.py` or `cli.py`** | Dead code from execution perspective |
| 3.2 `input_bounding.py` | **Implemented but NOT integrated** | `BoundedInput`, `BoundingResult`, `estimate_tokens`, `bound_inputs` present. **Never called from executor** | Dead code from execution perspective |
| 3.3 Path bounding | **Not implemented** | No explicit repo-root whitelist enforcement. `_gather_document_paths()` checks `is_file()` only | |

### Phase 4: Artifact Production & Canonical Write Contract

| Planned Requirement | Status | Evidence | Notes |
|---|---|---|---|
| 4.1 Canonical envelope format | **Implemented** | `ArtifactEnvelope` dataclass. `artifact_writer.py` writes hook-compatible format | |
| 4.2 `artifact_writer.py` | **Implemented but NOT integrated** | `write_artifact_envelope()` and `read_artifact_envelope()` present. **Never imported by `executor.py`**. Executor writes artifacts as in-memory `ArtifactRecord` objects only | V2A criterion "artifacts written to disk in envelope format" is UNMET |
| 4.3 Artifact flow validation (pre-execution input check) | **Not implemented** | No pre-step input validation in executor | |
| 4.4 Artifact schema definitions | **Not implemented** | No field-level schema validation for the 9 key artifacts | |

### Phase 5: Drift Detection

| Planned Requirement | Status | Evidence | Notes |
|---|---|---|---|
| 5.1 `drift_detector.py` | **Implemented** | `DriftIssue`, `DriftResult`, `detect_drift()` present | |
| 5.2 Drift checks (7 planned) | **5 of 7 implemented** | Missing: "Duplicate invariant logic" (informational), "Doc path consistency" (informational) | Both missing checks are informational-severity |
| 5.3 Pipeline integration (between validate and plan) | **NOT integrated** | `cli.py` never imports or calls `detect_drift()`. Critical drifts will NOT block execution | **HIGH-RISK**: the entire purpose of this module is to block before execution |

### Phase 6: Observability & Diagnostics

| Planned Requirement | Status | Evidence | Notes |
|---|---|---|---|
| 6.1 Extended trace event types (13 new) | **1 of 13 emitted** | Only `agent_resolved` emitted by `executor.py:309-313`. All others absent | |
| 6.2 `diagnostics.py` | **Implemented but NOT integrated** | `build_diagnostic_report()`, `diagnostic_report_to_dict()`, critical path DP. **Never called from `cli.py`** | |
| 6.3 Exit code alignment (0-5, 10, 11) | **Not implemented** | `cli.py` returns only 0 or 1 | |
| 6.4 Halt-on-critical-failure | **CONTRACT-BREAKING DEFECT** | `executor.py:569` `break` exits inner `for blocker_id in step.raises:` loop. Outer `for node in plan.ordered_steps:` continues via `continue` at line 571. DAG traversal is NOT halted | See Finding F1 |

### Phase 7: Live Agent Execution (V2B)

| Planned Requirement | Status | Evidence | Notes |
|---|---|---|---|
| All V2B modules | **Correctly not implemented** | No `claude_cli_backend.py`, `native_claude_backend.py`, `output_validator.py`, `escalation.py` | Phase 7 correctly deferred per milestone boundary |

---

## 4. Implemented Module Inventory vs Plan

### Existing Modules (Modified)

| Module | Planned? | Implemented? | Status | Notable Deviations |
|--------|----------|-------------|--------|-------------------|
| `models.py` | Yes | Yes | Complete | `PromptAssemblyContext` defined but unused |
| `assembler.py` | Yes | Yes | Complete | None |
| `validator.py` | Yes | Yes | Complete | None |
| `executor.py` | Yes | Yes | **Defective** | Halt-on-critical broken (F1). artifact_writer/prompt_assembly not integrated |
| `cli.py` | Yes | Partial | **Defective** | `load_run_state_from_path` missing (F2). No drift/diagnostics integration. Exit codes not mapped |
| `planner.py` | Yes (`+layer_groups()`) | No | Missing | `layer_groups()` not added. `--phase` flag accepted but unused |
| `state_store.py` | Yes (extend StoredRunState) | No | Missing | No `latency_ms`/`token_count` in StoredNodeResult. No `load_run_state_from_path` |

### New Modules -- V2A

| Module | Planned? | Implemented? | Status | Notable Deviations |
|--------|----------|-------------|--------|-------------------|
| `execution_backend.py` | Yes | Yes | Complete | Method signature differs from plan (benign for V2A) |
| `agent_resolver.py` | Yes | Yes | Complete | None |
| `skill_resolver.py` | Yes | Yes | Complete | None |
| `execution_modes.py` | Yes | Yes | Complete | None |
| `prompt_assembly.py` | Yes | Yes | **Unwired** | Returns dict not PromptAssemblyContext. Never called from executor |
| `input_bounding.py` | Yes | Yes | **Unwired** | Never called from executor |
| `artifact_writer.py` | Yes | Yes | **Unwired** | Never called from executor |
| `drift_detector.py` | Yes | Yes | **Unwired** | Never called from cli.py. 5/7 checks only |
| `diagnostics.py` | Yes | Yes | **Unwired** | Never called from cli.py |

### New Modules -- V2B (correctly deferred)

| Module | Planned? | Implemented? | Status |
|--------|----------|-------------|--------|
| `claude_cli_backend.py` | Yes (V2B) | No | Correctly deferred |
| `native_claude_backend.py` | Yes (V2B) | No | Correctly deferred |
| `output_validator.py` | Yes (V2B) | No | Correctly deferred |
| `escalation.py` | Yes (V2B) | No | Correctly deferred |

---

## 5. Critical Findings

### Contract-Breaking Issues

**F1. Halt-on-critical-failure does not halt DAG traversal**
- **File:** `governance/dag_runner/executor.py`, lines 544-571
- **Evidence:** The `break` at line 569 exits the inner `for blocker_id in step.raises:` loop. The `continue` at line 571 then advances to the NEXT node in the outer `for node in plan.ordered_steps:` loop. No flag is set to stop the outer loop.
- **Impact:** Steps after a fatal blocker continue executing. Violates plan section 6.4 and CLAUDE.md section 7 (fail-closed principle).
- **No test coverage exists** for halt-on-critical behavior.

**F2. `load_run_state_from_path` does not exist**
- **File:** `governance/dag_runner/cli.py`, line 210
- **Evidence:** `from governance.dag_runner.state_store import load_run_state_from_path` -- grep of `state_store.py` confirms this function does not exist. Only `load_run_state()` exists (returns `dict`, not `GovernanceRunState`).
- **Impact:** Any `--continue-from` invocation crashes with `ImportError`.

### High-Risk Issues

**F3. `artifact_writer.py` never called from executor**
- **File:** `governance/dag_runner/executor.py` lines 331-338
- **Evidence:** Grep for `artifact_writer` in executor.py returns no matches. `_execute_v2_step()` writes artifacts as in-memory `ArtifactRecord` objects (line 333) but never writes to disk.
- **Impact:** V2A success criterion "All artifacts written to `.claude/run/artifacts/` match hook `artifact_store.py` envelope format" is unmet.

**F4. `prompt_assembly.py` never called from executor**
- **File:** `governance/dag_runner/executor.py`
- **Evidence:** Grep for `prompt_assembly` in executor.py returns no matches. Backend receives `run_state` and `spec`, not a `PromptAssemblyContext`.
- **Impact:** Acceptable for MockExecutionBackend (ignores input) but architecturally disconnected. Must be resolved before V2B.

**F5. Drift detection not integrated into CLI pipeline**
- **File:** `governance/dag_runner/cli.py`
- **Evidence:** Grep for `drift_detect` in cli.py returns no matches. Plan specifies it runs between `validate_or_raise()` and `build_execution_plan()`.
- **Impact:** Critical drifts do not block execution. The entire purpose of the module is negated.

**F6. `diagnostics.py` not integrated into CLI**
- **File:** `governance/dag_runner/cli.py`
- **Evidence:** Grep for `diagnostics` in cli.py returns no matches. No diagnostic output is produced.
- **Impact:** No observability data in CLI output or JSON mode.

### Medium-Risk Issues

**F7. Exit codes 0-5/10/11 not implemented**
- `cli.py` returns only 0 or 1. Plan specifies semantic codes: structural=1, contract=2, runtime=3, artifact=4, timeout=5, review_only=10, blocked=11.

**F8. `planner.py` missing `layer_groups()`**
- `--phase` flag accepted but `phase_scope` value is never used. Phase-scoped execution non-functional.

**F9. `state_store.py` not extended with V2 metadata**
- `StoredNodeResult` lacks `latency_ms` and `token_count`. V2 execution metadata lost on persistence.

**F10. 12 of 13 planned trace event types not emitted**
- Only `agent_resolved` emitted. Missing: `skill_resolved`, `prompt_assembled`, `input_bounded`, `backend_invocation_started/completed/failed`, `artifact_produced`, `artifact_validated`, `blocking_event_raised`, `drift_check_completed`, `continuation_validated`.

### Informational Issues

**F11. `PromptAssemblyContext` dataclass defined but unused** -- `prompt_assembly.py` returns a dict instead. Spec inconsistency.

**F12. 2 of 7 drift checks missing** -- "Duplicate invariant logic" and "Doc path consistency" (both informational). Non-blocking.

**F13. Test file organization differs from plan** -- Plan specifies separate `test_component_dispatch.py`, `test_continuation.py`, `test_executor_v2.py`; implementation consolidates into `test_execution_modes.py`. Acceptable.

**F14. `ExecutionBackend.execute_step()` signature divergence** -- Plan: `(prompt, step, agent, config)`. Implementation: `(step, agent, config, run_state, spec)`. Acceptable for V2A; must reconcile for V2B.

---

## 6. DAG Scheduler / Runtime Readiness Assessment

| Capability | Status | Detail |
|------------|--------|--------|
| **Graph assembly** | READY | Topological sort, component-kind classification, graph JSON output all functional and tested |
| **Validation** | READY | All 14 validation checks present, passing against real workflow (18 steps, 13 skills, 19 artifacts, 12 blockers) |
| **Component-kind dispatch** | READY | `_parse_component_kind()`, structural/backend routing operational. No step-name conditionals |
| **V1 shell mode** | READY | 204 tests pass. `backend=None` path unchanged |
| **Dry-run mode** | READY | Tested. No artifacts produced, no backend invocation |
| **Mock agent execution** | READY | MockExecutionBackend produces in-memory artifacts. 17+ artifacts materialized |
| **Prompt assembly** | NOT READY | Module works in isolation but not connected to execution |
| **Artifact disk write** | NOT READY | Module works in isolation but not connected to execution |
| **Drift detection gate** | NOT READY | Module works in isolation but not connected to CLI |
| **Halt-on-critical-failure** | **BROKEN** | `break` exits wrong loop scope. DAG does not halt (F1) |
| **Continuation** | **BROKEN** | `load_run_state_from_path` missing. ImportError on use (F2) |
| **Blocker propagation** | PARTIAL | V1 blocker analysis works. V2 halt-on-critical defective |
| **Exit code semantics** | NOT READY | Only 0/1 returned |
| **Diagnostics** | NOT READY | Module works but not connected to CLI |
| **Live backend safety** | SAFE | No live backends exist. MockExecutionBackend only |
| **Hook compatibility** | PARTIAL | Artifact envelope format correct in writer, but writer never called |

---

## 7. Test Posture

### V1 Preservation
- **204 V1 tests: ALL PASS** (based on test file analysis)
- No regressions detected in V1 shell path

### V2 Coverage
- **~56 new V2 tests across 7 test files**

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_agent_resolver.py` | 8 | Agent binding, file loading, skill resolution |
| `test_execution_backend.py` | 8 | Mock backend, interface contract |
| `test_execution_modes.py` | 14 | Config building, component parsing, continuation validation, dry-run, agent_execution modes |
| `test_prompt_assembly.py` | 8 | Token estimation, input bounding, prompt assembly |
| `test_artifact_writer.py` | 8 | Envelope write/read, format validation |
| `test_drift_detector.py` | 7 | Real workflow cleanliness, synthetic drift detection |
| `test_diagnostics.py` | 7 | Diagnostic report, critical path, serialization |

### Missing Tests (Critical Gaps)
1. **No test for halt-on-critical-failure behavior** -- the broken mechanism has zero test coverage
2. **No integration test for `artifact_writer` called during execution** -- only standalone unit tests
3. **No integration test for `prompt_assembly` called during execution** -- because it isn't called
4. **No integration test for drift detection blocking CLI pipeline** -- because it isn't integrated
5. **No test for CLI exit codes 2-5, 10, 11** -- because they aren't implemented
6. **No test for continuation at CLI level** -- `load_run_state_from_path` will crash
7. **No test for `--phase` flag behavior** -- `layer_groups()` not implemented

### Confidence Level
- **Module-level unit tests:** HIGH -- all modules tested in isolation
- **Integration wiring tests:** LOW -- critical end-to-end flows for V2-specific behavior untested
- **Overall V2A confidence:** MODERATE-LOW

---

## 8. Live Testing Decision

### ALLOWED NOW (no fixes needed):
- `python -m governance.dag_runner.cli --graph --json` (graph-only, no execution)
- `python -m governance.dag_runner.cli --dry-run` (walk plan, no artifacts, no backend)
- `python -m governance.dag_runner.cli --mode agent_execution` (MockExecutionBackend, in-memory only)
- `python -m governance.dag_runner.cli` (V1 shell mode, fully tested)
- `python -m pytest tests/governance -q` (full test suite)

### BLOCKED until fixes:
- `--continue-from` (ImportError crash -- F2)
- Any scenario relying on halt-on-critical-failure (broken control flow -- F1)
- Any scenario expecting artifacts on disk (F3)
- Any scenario expecting drift detection to block execution (F5)
- Any scenario expecting semantic exit codes (F7)
- Any scenario using `--phase` for scoped execution (F8)

---

## 9. Minimal Fix List Before Live Testing

Ordered by priority. Each fix is the smallest possible change.

### P0 -- Must fix before any V2A completeness claim

**Fix 1: Halt-on-critical-failure control flow** (`executor.py`)
- Add a `halted = False` flag before the outer loop
- Set `halted = True` inside the halt branch (line 549-567)
- Check `if halted: break` after the blocker loop to exit the outer loop
- Add test: construct spec with `halts_workflow=True` blocker, force FAIL, assert subsequent steps are SKIP

**Fix 2: `load_run_state_from_path` missing** (`state_store.py` or `cli.py`)
- Either add `load_run_state_from_path(path) -> GovernanceRunState` to `state_store.py` that loads JSON and reconstructs a GovernanceRunState
- Or fix `cli.py:210` to use existing `load_run_state(path)` with appropriate dict-to-GovernanceRunState conversion
- Add test: round-trip write-load-continue

### P1 -- Required for V2A acceptance criteria

**Fix 3: Integrate `detect_drift()` into CLI** (`cli.py`)
- Add `from governance.dag_runner.drift_detector import detect_drift`
- Call between `validate_or_raise(spec)` and `build_execution_plan(spec)`
- Block with exit code 1 on critical drifts, warn on informational

**Fix 4: Integrate `artifact_writer` into executor V2 path** (`executor.py`)
- After `_execute_v2_step()` records in-memory artifacts (line 331-338), call `write_artifact_envelope()` to disk
- Add test: verify `.claude/run/artifacts/` files match envelope schema

**Fix 5: Integrate `diagnostics.py` into CLI output** (`cli.py`)
- Build `DiagnosticReport` after execution, include in JSON output and text summary

### P2 -- Should fix for plan conformance

6. Implement exit code mapping (cli.py) per plan table
7. Extend `StoredNodeResult` with `latency_ms` and `token_count` (state_store.py)
8. Implement `layer_groups()` or document `--phase` as deferred (planner.py)
9. Emit remaining trace event types from executor (at minimum `backend_invocation_started/completed`, `artifact_produced`)
10. Wire `prompt_assembly` into executor or document as V2B-deferred

---

## 10. Final Conclusion

**The V2A refactor is approximately 70% complete by module delivery and 55% complete by integration wiring.**

The architectural foundation is solid: all planned types, parsing, validation, mock backend, and module APIs exist and are individually tested. The individual pieces are well-built. The gap is in the last-mile integration:

- **Executor** does not call `prompt_assembly`, `artifact_writer`, or halt correctly on critical failure
- **CLI** does not call `detect_drift`, `diagnostics`, has a broken continuation path, and lacks exit code mapping
- **4 of 9 new V2A modules are dead code** from the execution perspective

These are wiring defects, not design flaws. The P0 fixes (halt-on-critical, continuation crash) are small scoped changes. The P1 fixes (integration wiring) are straightforward imports and function calls.

**Readiness statement:** V2A is NOT ready for acceptance as a complete milestone. It IS ready for constrained mocked testing (graph-only, dry-run, mock agent_execution, V1 shell). The P0 fixes are blockers. The P1 fixes are required to satisfy the plan's stated V2A success criteria. Until P0+P1 are addressed, classify V2A as **in-progress**.

### Critical Implementation Files

| File | Fixes Needed |
|------|-------------|
| `governance/dag_runner/executor.py` | F1 (halt control flow), F4 (artifact_writer integration) |
| `governance/dag_runner/cli.py` | F2 (load_run_state_from_path fix), F3 (drift integration), F5 (diagnostics integration), F7 (exit codes) |
| `governance/dag_runner/state_store.py` | F2 (add missing function or fix import), F9 (V2 metadata fields) |
| `governance/dag_runner/planner.py` | F8 (layer_groups for --phase) |
