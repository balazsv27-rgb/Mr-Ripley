# DAG Runner V2A Remediation Plan

## 1. Planning Basis

### Review baseline used

`DAG_RUNNER_REFACTOR_IMPLEMENTATION_REVIEW.md` — static analysis review covering all 22 modules in `governance/dag_runner/`, 20 test files (~400+ test methods), and the authoritative `dag_refactor_plan.md` baseline.

### Current status summary

| Dimension | Value |
|-----------|-------|
| Overall status | **V2A COMPLETE (mocked-testing ready)** |
| Module delivery | 100% (V2A scope) |
| Integration wiring | 100% (V2A scope; prompt_assembly, input_bounding deferred to V2B) |
| Full test suite | 313 tests, ALL PASS |
| Contract-breaking defects | 0 (F1, F2 both FIXED) |
| Unwired modules | 1 deferred (prompt_assembly — V2B prerequisite); artifact_writer, drift_detector, diagnostics all wired |
| Live testing readiness | Mocked testing: ALL MODES READY. Live testing: blocked on V2B prerequisites. |
| Acceptance record | `DAG_RUNNER_V2A_ACCEPTANCE_RECORD.md` — all 11 criteria MET |

### Remediation goal

Bring V2A to internal acceptance by:
1. Fixing the two contract-breaking defects (F1 halt-on-critical, F2 continuation crash)
2. Wiring the four unwired modules into the executor/CLI production path
3. Restoring plan conformance for exit codes, state persistence, and phase scoping
4. Establishing the minimum test set that proves integration correctness
5. Defining an explicit gate for when mocked and live testing can proceed

This plan does NOT expand scope into V2B (live Claude backends, escalation, subagent dispatch). It does NOT redesign any module. It treats unwired modules as integration work items.

---

## 2. Revised V2A Acceptance Contract

### Must-fix items (blocking V2A completion claim)

**Status: ALL 7 ITEMS CLOSED** (verified 2026-04-18)

| ID | Finding | File(s) | Status | Fixed In |
|----|---------|---------|--------|----------|
| MF-1 | F1: halt-on-critical-failure does not halt DAG traversal | `executor.py` | **CLOSED** | R1-A (6 tests in `test_executor_halt.py`) |
| MF-2 | F2: `load_run_state_from_path` does not exist — continuation crashes | `cli.py`, `state_store.py` | **CLOSED** | R1-B (5 tests in `test_state_store.py`) |
| MF-3 | F3: artifact_writer not integrated into executor | `executor.py` | **CLOSED** | R2-A (15 tests in `test_executor_artifacts.py`) |
| MF-4 | F5: drift detection not integrated into CLI | `cli.py` | **CLOSED** | R2-B (5 tests in `test_cli_drift.py`) |
| MF-5 | F6: diagnostics not integrated into CLI | `cli.py` | **CLOSED** | R2-C (4 tests in `test_cli_diagnostics.py`) |
| MF-6 | F7: exit code mapping missing | `cli.py` | **CLOSED** | R3-A (8 tests in `test_cli_exit_codes.py`) |
| MF-7 | F9: state_store missing V2 metadata persistence | `state_store.py` | **CLOSED** | R3-C (2 tests in `test_state_store_v2_metadata.py`) |

### Allowable deferrals (documented, non-blocking for V2A)

| ID | Item | Rationale for deferral |
|----|------|----------------------|
| DF-1 | F4/F11: prompt_assembly executor integration + PromptAssemblyContext inconsistency | MockExecutionBackend ignores prompt input entirely. Integration is architecturally correct to defer until V2B when a real backend consumes the prompt. Must be documented as V2B prerequisite. |
| DF-2 | F12: 2 of 7 drift checks missing (duplicate invariant logic, doc path consistency) | Both are informational-severity. No execution-blocking impact. |
| DF-3 | F14: `ExecutionBackend.execute_step()` signature divergence from plan | Benign for V2A (MockExecutionBackend). Must reconcile for V2B. |
| DF-4 | F10: 12 of 13 trace event types not emitted (partial remediation in R2; full coverage deferred) | Minimum viable trace events emitted during R2 integration. Full 13-type coverage deferred to plan-conformance phase. |
| DF-5 | Input bounding executor integration | Same rationale as DF-1; no real backend to consume bounded input. |
| DF-6 | Full artifact schema validation (4.3, 4.4 from plan) | Schema definitions and pre-step input validation are V2B concerns — MockExecutionBackend produces deterministic payloads. |
| DF-7 | Path-bounded file access enforcement (3.3 from plan) | Acceptable risk when only MockExecutionBackend is used. Must be enforced before V2B live backends. |

### Non-negotiable compatibility constraints

1. **V1 shell mode preservation**: All 204 V1 tests must pass unchanged. The `backend=None` path must produce identical output.
2. **No YAML modification**: Workflow packages are the spec. No `.claude/workflows/` files are modified.
3. **Fail-closed principle**: All new integration points must default to blocking/erroring rather than silently continuing.
4. **Hook envelope compatibility**: Artifact envelopes written to disk must match `.claude/hooks/lib/artifact_store.py` format exactly.

---

## 3. Remediation Strategy

### Ordered phases

```
R1: Contract-Breaking Defect Repair (F1, F2)          ✓ COMPLETE
  ↓
R2: V2A Integration Wiring (F3, F5, F6)               ✓ COMPLETE
  ↓
R3: Plan-Conformance Restoration (F7, F8, F9, F10)    ✓ COMPLETE
  ↓
R4: Verification and Acceptance Review                 ✓ COMPLETE
```

### Rationale for sequencing

**R1 before R2**: The two contract-breaking defects (halt-on-critical, continuation crash) are preconditions for all other integration work. The halt-on-critical fix changes control flow in `executor.py`, which is the same file that receives artifact_writer integration in R2. Fixing F2 is required before any continuation-dependent integration testing can occur.

**R2 before R3**: V2A acceptance criteria explicitly require artifact_writer integration, drift detection blocking, and diagnostics output. These are the four unwired modules that represent the 55%→~90% integration jump. Plan-conformance items (exit codes, state metadata, phase scoping) are important but do not block the core V2A integration claim.

**R3 before R4**: Exit codes, state persistence extensions, and minimum trace event coverage are plan-conformance items. They must be in place before the acceptance review, but they depend on R2 being complete (e.g., exit codes map to drift failures and artifact failures introduced in R2).

**R4 is the gate**: No live testing or V2A completion claim until R4 passes.

### Dependency notes

- R1/F1 (executor.py halt fix) and R1/F2 (state_store.py + cli.py continuation fix) are independent of each other within R1 — can be implemented in parallel.
- R2/F3 (artifact_writer in executor) depends on R1/F1 being complete, because artifact_writer integration adds code in the same executor V2 path that halt-on-critical modifies.
- R2/F5 (drift in CLI) and R2/F6 (diagnostics in CLI) are independent of each other but both modify `cli.py`.
- R3/F7 (exit codes) depends on R2 being complete, because new exit codes map to drift failures (R2/F5) and artifact failures (R2/F3).
- R3/F9 (state_store V2 metadata) is independent of other R3 items.
- R3/F8 (planner layer_groups) is independent of other R3 items.

---

## 4. Phase-by-Phase Work Plan

### Phase R1: Contract-Breaking Defect Repair — COMPLETE

**Objective**: Fix the two defects that make V2A contract-non-compliant: halt-on-critical control flow (F1) and continuation crash (F2).

**Status**: COMPLETE. Implemented in commit `c56aee8`. 11 new tests added.

**Files affected**: `executor.py`, `state_store.py`, `cli.py`

#### R1-A: Fix halt-on-critical-failure (F1)

**File**: `governance/dag_runner/executor.py`, lines 544-571

**Current defect**: The `break` at line 569 exits the inner `for blocker_id in step.raises:` loop. The `continue` at line 571 then advances to the next node in the outer `for node in plan.ordered_steps:` loop. No flag is set to stop the outer loop.

**Required implementation**:
1. Add a `halted = False` flag before the outer loop (before line 418).
2. Inside the halt branch (line 549-567), after appending the `BlockingEvent` and recording the trace event, set `halted = True`.
3. After the `break` exits the inner blocker loop, check `if halted: break` to exit the outer loop.
4. After the outer loop, if `halted`, mark all remaining unexecuted steps as SKIP with reason `"halted by critical blocker at {step_name}"`.

**Required behavior after remediation**:
- When a step FAILs and raises a blocker with `halts_workflow=True`, ALL subsequent steps must be skipped.
- Skipped steps must be recorded as `NodeResult(status="SKIP", summary="halted by critical blocker at ...")`.
- The halt must be visible in the execution trace.
- V1 shell path (`backend=None`) must be unaffected.

**Dependencies**: None. This is the first fix.

**Required tests**:
- Test: construct a spec with a step that has `halts_workflow=True` blocker, force the step to FAIL via MockExecutionBackend, assert all subsequent steps have status SKIP.
- Test: same scenario but `halts_workflow=False` — assert subsequent steps continue executing.
- Test: verify the `halt_on_critical_failure` trace event is recorded.
- Test: verify V1 path is unaffected (existing 204 tests suffice).

#### R1-B: Fix continuation crash (F2)

**File**: `governance/dag_runner/state_store.py` (add function), `governance/dag_runner/cli.py` line 210 (fix import)

**Current defect**: `cli.py:210` imports `load_run_state_from_path` from `state_store`, which does not exist. Only `load_run_state()` exists, and it returns `dict`, not `GovernanceRunState`.

**Required implementation**:
1. Add `load_run_state_from_path(path: Path) -> GovernanceRunState` to `state_store.py`.
2. This function must:
   - Read JSON from the given path (reuse existing `load_run_state()` for raw dict loading).
   - Reconstruct a `GovernanceRunState` from the stored JSON dict.
   - Reconstruct `NodeResult` objects from stored node results.
   - Reconstruct `ArtifactRecord` objects from stored artifact records.
   - Reconstruct `BlockingEvent` objects from stored blocking conditions.
   - Reconstruct `ExecutionTraceEvent` objects from stored trace events.
   - Parse ISO timestamps back to `datetime` objects.
   - Fail closed (raise `StateStoreError`) on any structural mismatch.
3. The existing `cli.py:210` import already references this name — no CLI change needed once the function exists.

**Required behavior after remediation**:
- `--continue-from <step>` loads prior state, passes continuation validation, and resumes execution.
- Round-trip: write state → load state → continuation validation passes → execution resumes from the correct step.

**Dependencies**: None. Independent from R1-A.

**Required tests**:
- Test: round-trip `write_run_state` → `load_run_state_from_path` → verify `GovernanceRunState` fields match.
- Test: `load_run_state_from_path` with corrupt JSON → `StateStoreError`.
- Test: `load_run_state_from_path` with missing file → `StateStoreError`.
- Test: CLI-level continuation: write state from a partial run, invoke CLI with `--continue-from`, verify execution resumes.

**Success criteria for R1**:
- F1 halt test passes: FAIL + halts_workflow → all subsequent steps SKIP. **MET**
- F2 round-trip test passes: write → load → validate → resume works. **MET**
- All 204 V1 tests still pass. **MET**
- All existing 56 V2 tests still pass. **MET**

---

### Phase R2: V2A Integration Wiring — COMPLETE

**Objective**: Wire the three remaining critical unwired modules into the production path: artifact_writer into executor, drift_detector into CLI, diagnostics into CLI.

**Status**: COMPLETE. Implemented in commit `143a59d`. 24 new tests added.

**Files affected**: `executor.py`, `cli.py`

#### R2-A: Integrate artifact_writer into executor (F3)

**File**: `governance/dag_runner/executor.py`

**Current defect**: `_execute_v2_step()` records artifacts as in-memory `ArtifactRecord` objects (lines 331-338) but never writes to disk. `artifact_writer.py` is never imported.

**Required implementation**:
1. Import `write_artifact_envelope` and `ArtifactWriterError` from `artifact_writer`.
2. After the in-memory artifact recording loop (after line 338), add a disk-write loop:
   - For each artifact in `result.artifacts_produced`, call `write_artifact_envelope()`.
   - Use `run_state.run_id` as `session`.
   - Use `Path(".claude/run/artifacts/")` as the default artifact directory.
   - Wrap in try/except for `ArtifactWriterError`; on failure, classify as artifact failure and set node result to FAIL.
3. Emit `artifact_produced` trace event for each successful write.
4. The artifact directory path should be derivable from a reasonable default (`.claude/run/artifacts/` relative to cwd), consistent with existing hook conventions.

**Required behavior after remediation**:
- `--mode agent_execution` produces JSON envelope files in `.claude/run/artifacts/`.
- Each file matches the hook `artifact_store.py` envelope schema.
- Artifact write failure causes the step to FAIL (fail-closed).
- Dry-run mode does NOT write artifacts to disk.

**Dependencies**: R1-A (halt-on-critical) must be merged first because both modify executor.py's V2 execution path.

**Required tests**:
- Test: execute with MockExecutionBackend, verify `.claude/run/artifacts/<name>.json` files exist.
- Test: verify written envelopes have required keys: `artifact`, `produced_by`, `session`, `timestamp`, `data`.
- Test: verify dry-run mode does NOT produce disk artifacts.
- Test: verify artifact write failure causes step FAIL.

### R2-A.1: Minimum Artifact Flow Validation (required-input presence check)

**Objective**: Restore basic DAG dependency correctness by ensuring a step cannot execute when its declared required input artifacts are missing.

Files affected: executor.py

Why this is required in V2A:
This is not full artifact schema validation and not V2B-style semantic output validation. It is a minimum execution-integrity guard required for any DAG runtime: a step must not execute if the artifacts it depends on are absent. Without this check, the runner can still produce false-positive PASS states for steps whose upstream dependencies were never materialized.

Scope boundary:

Included in V2A: presence validation for declared required input artifacts
Still deferred to V2B:
field-level artifact schema validation
semantic validation of artifact payload contents
path-bounded file access enforcement
output-validator-style downstream contract checking

Required implementation:

Before executing any V2 step in executor.py, determine the step’s declared required input artifacts.
For each required input artifact:
check whether it exists in run_state.artifacts
check whether its status is present
If any required artifact is missing:
do not execute the step
record a FAIL NodeResult
append a BlockingEvent or artifact-failure record consistent with existing executor failure handling
emit a trace event indicating artifact dependency failure
If the missing artifact should have been produced by a prior step that was intentionally skipped due to condition / skip_if, classify the current step conservatively:
either FAIL fail-closed
or SKIP only if the workflow explicitly supports dependency-skipping semantics for that path
Default policy for V2A: fail closed unless skip propagation is already explicitly modeled
Preserve V1 shell-mode behavior when backend=None unless the same dependency contract is already expected there.

Resolution source for required inputs:
Use the workflow/spec-declared artifact dependencies already available to the executor. Do not introduce new YAML schema or redesign package ownership. This is a runtime enforcement layer over the existing spec, not a spec rewrite.

Required behavior after remediation:

A step with missing required input artifacts must never execute normally.
The failure must be visible in:
node results
execution trace
final verdict / exit semantics
MockExecutionBackend runs must reflect real dependency absence instead of silently succeeding.
Dry-run mode may evaluate and report the missing dependency without materializing artifacts.

Dependencies:

Should be implemented alongside or immediately after R2-A because both modify the V2 executor path and both concern artifact integrity.
Exit-code mapping for artifact failures remains part of R3-A.

Required tests:

Test: a step with a missing required upstream artifact fails before backend execution.
Test: a step with all required input artifacts present executes normally.
Test: dry-run reports missing required artifacts without writing outputs.
Test: artifact dependency failure is reflected in execution trace.
Test: artifact dependency failure contributes to blocked / non-ready final state.
Test: V1 shell path remains backward compatible unless explicitly brought under the same dependency enforcement rule.

Success criteria:

No step can PASS in V2 mode when one of its declared required input artifacts is absent.
Artifact dependency failures are observable and fail closed.
This check closes the remaining DAG-correctness gap without pulling full schema validation into V2A.

#### R2-B: Integrate drift_detector into CLI pipeline (F5)

**File**: `governance/dag_runner/cli.py`

**Current defect**: `cli.py` never imports or calls `detect_drift()`. Critical drifts do not block execution.

**Required implementation**:
1. Import `detect_drift` and `DriftResult` from `drift_detector`.
2. Insert drift detection call between `validate_or_raise(spec)` (line 172) and `plan = build_execution_plan(spec)` (line 174).
3. Determine `repo_root` as the parent of the workflow file's directory (or use `Path.cwd()` / a reasonable project-root heuristic).
4. On critical drifts: print drift issues to stderr, return exit code 1 (R3 will refine this to a dedicated code).
5. On informational-only drifts: print warnings to stderr, continue execution.
6. In `--json` mode, include drift results in the output structure.

**Required behavior after remediation**:
- Critical drifts (missing agent files, missing skill files, binding mismatches, artifact producer inconsistencies) block execution before the plan is built.
- Informational drifts produce warnings but do not block.
- The drift check runs for ALL modes (shell_v1, agent_execution, dry-run) — it validates spec consistency, not execution readiness.

**Dependencies**: None within R2. Can be implemented in parallel with R2-A.

**Required tests**:
- Test: CLI with a spec that has a critical drift → exit code nonzero, execution does not proceed.
- Test: CLI with a spec that has only informational drift → execution proceeds, warnings emitted.
- Test: CLI with clean drift result → execution proceeds normally.

#### R2-C: Integrate diagnostics into CLI (F6)

**File**: `governance/dag_runner/cli.py`

**Current defect**: `cli.py` never imports or calls `diagnostics.py`. No diagnostic output is produced.

**Required implementation**:
1. Import `build_diagnostic_report` and `diagnostic_report_to_dict` from `diagnostics`.
2. After `execute_plan()` returns (after line 234), build a diagnostic report from `spec`, `plan`, and `execution_result.run_state`.
3. In `--json` mode: include `"diagnostics": diagnostic_report_to_dict(report)` in the output.
4. In text mode: append a brief diagnostics summary (total latency, bottleneck, failed count) to the printed output.
5. The diagnostics module already handles the case where `latency_ms` and `token_count` are 0.0/0 (V1 shell mode), so no special handling is needed for V1 compatibility.

**Required behavior after remediation**:
- `--json` output includes a `diagnostics` key with per-step timing, critical path, and bottleneck data.
- Text output includes a diagnostics summary line.
- V1 shell mode includes diagnostics (all latencies will be 0.0, which is correct).

**Dependencies**: None within R2. Can be implemented in parallel with R2-A and R2-B.

**Required tests**:
- Test: CLI `--json` output includes `diagnostics` key with expected structure.
- Test: CLI text output includes diagnostics summary.
- Test: diagnostics work correctly with V1 shell mode (all zeros).

**Success criteria for R2**:
- Artifact envelopes written to disk during `--mode agent_execution`. **MET**
- Critical drifts block execution. **MET**
- Diagnostics present in `--json` output. **MET**
- All V1 tests still pass. **MET**
- All V2 tests still pass. **MET**

---

### Phase R3: Plan-Conformance Restoration — COMPLETE

**Objective**: Close the remaining plan-conformance gaps: exit codes, phase scoping, state persistence, and minimum trace event coverage.

**Status**: COMPLETE. Implemented in commit `3f36a34`. 18 new tests added. Option B chosen for `--phase` (warning emitted, documented as deferred).

**Files affected**: `cli.py`, `planner.py`, `state_store.py`, `executor.py`

#### R3-A: Implement exit code mapping (F7)

**File**: `governance/dag_runner/cli.py`

**Current defect**: CLI returns only 0 or 1. Plan specifies semantic exit codes.

**Required implementation**:
1. Define an exit code mapping (can be a module-level dict or constants):
   - 0 = clean run, verdict=ready
   - 1 = structural failure (loader, assembler, validator, drift)
   - 2 = contract failure (blocking condition with `halts_workflow`)
   - 3 = runtime failure (backend invocation error, timeout)
   - 4 = artifact failure (validation, missing required)
   - 5 = timeout exceeded
   - 10 = verdict=review_only
   - 11 = verdict=blocked (governance, not structural)
2. After execution, map the result to the appropriate exit code.
3. Catch `ArtifactWriterError` (from R2-A integration) and map to exit code 4.
4. Map drift detection failures (from R2-B) to exit code 1.
5. Map halt-on-critical (from R1-A) to exit code 2.
6. Map verdict `review_only` to exit code 10, `blocked` to exit code 11, `ready` to exit code 0.

**Dependencies**: R2 must be complete (drift failures map to code 1, artifact failures map to code 4).

**Required tests**:
- Test: clean run → exit code 0.
- Test: structural failure (validation) → exit code 1.
- Test: drift failure → exit code 1.
- Test: halt-on-critical → exit code 2.
- Test: verdict=review_only → exit code 10.
- Test: verdict=blocked → exit code 11.

#### R3-B: Planner `layer_groups()` or `--phase` documentation (F8)

**File**: `governance/dag_runner/planner.py`

**Current defect**: `--phase` flag accepted but `phase_scope` value is never used. Phase-scoped execution is non-functional.

**Required implementation — option A (implement)**:
1. Add `layer_groups(spec: AssembledWorkflowSpec) -> dict[str, list[str]]` to `planner.py`.
2. This function groups step IDs by their `layer` field (from `step.raw.get("layer")`).
3. In `build_execution_plan()`, accept an optional `phase_scope: str | None` parameter.
4. When `phase_scope` is provided, filter ordered steps to only those in the matching layer group.
5. Wire `phase_scope` from `ExecutionConfig` through CLI → planner.

**Required implementation — option B (document as deferred)**:
1. If implementing `layer_groups()` is not cost-effective for V2A, explicitly document `--phase` as non-functional in V2A.
2. Add a CLI warning when `--phase` is used: "Phase scoping is not yet implemented. Flag ignored."
3. Document this as a known deferral in the acceptance record.

**Recommendation**: Option B is acceptable for V2A. The `--phase` flag is a convenience feature, not a contract obligation. Document as deferred. If Option A is chosen, the implementation is straightforward (~30 lines) but requires additional test coverage.

**Dependencies**: None.

**Required tests** (if Option A):
- Test: `--phase A` returns only Layer A steps.
- Test: `--phase` with invalid layer returns error.
- Test: `--phase` omitted returns all steps (existing behavior).

**Required tests** (if Option B):
- Test: `--phase` emits warning and continues with all steps.

#### R3-C: Extend `StoredNodeResult` with V2 metadata (F9)

**File**: `governance/dag_runner/state_store.py`

**Current defect**: `StoredNodeResult` lacks `latency_ms` and `token_count`. V2 execution metadata is lost on persistence.

**Required implementation**:
1. Add `latency_ms: float = 0.0` and `token_count: int = 0` fields to `StoredNodeResult`.
2. In `build_stored_run_state()`, populate these fields from `NodeResult` values (lines 187-199).
3. These fields have defaults, so all existing serialized state files remain loadable (backwards compatible).

**Dependencies**: None.

**Required tests**:
- Test: V2 execution → write state → verify `latency_ms` and `token_count` present in persisted JSON.
- Test: Loading a V1-era state file (without these fields) still works.

#### R3-D: Minimum trace event coverage (F10 partial)

**File**: `governance/dag_runner/executor.py`

**Current defect**: Only `agent_resolved` emitted. 12 of 13 planned trace event types missing.

**Required implementation for V2A minimum**:
Emit the following trace events during V2 execution (minimum set required for observability):
1. `backend_invocation_started` — before `backend.execute_step()` / `backend.execute_structural_step()`.
2. `backend_invocation_completed` — after successful backend return.
3. `backend_invocation_failed` — after backend failure.
4. `artifact_produced` — after each `write_artifact_envelope()` (added in R2-A).
5. `blocking_event_raised` — when a blocking event is appended to run_state.

The remaining 7 event types (`skill_resolved`, `prompt_assembled`, `input_bounded`, `artifact_validated`, `drift_check_completed`, `continuation_validated`) are deferred to full plan-conformance or V2B, because they correspond to integrations that are either deferred (prompt_assembly, input_bounding, artifact_validation) or are already adequately covered by the drift/continuation implementations.

**Dependencies**: R2-A (artifact_produced events depend on artifact_writer integration).

**Required tests**:
- Test: V2 execution trace contains `backend_invocation_started` and `backend_invocation_completed` events.
- Test: V2 execution with artifact production contains `artifact_produced` events.

**Success criteria for R3**:
- Exit codes map to failure categories per the plan table. **MET**
- `StoredNodeResult` persists V2 metadata. **MET**
- `--phase` is either functional or documented as deferred with a warning. **MET** (Option B: warning emitted)
- Minimum trace events emitted for backend invocation and artifact production. **MET**
- All V1 and V2 tests still pass. **MET**

---

### Phase R4: Verification and Acceptance Review — COMPLETE

**Objective**: Execute the full V2A verification protocol and produce an acceptance record.

**Status**: COMPLETE. Verified 2026-04-18. Acceptance record: `DAG_RUNNER_V2A_ACCEPTANCE_RECORD.md`.

**Files affected**: None (verification only).

#### R4-A: Full test suite execution

Run the complete test suite and verify:
- All 204 V1 tests pass.
- All existing V2 tests pass.
- All new tests from R1-R3 pass.
- No regressions.

#### R4-B: Manual verification commands

Execute the V2A verification commands from the plan:

```bash
# V1 shell mode (unchanged — backwards compat)
python -m governance.dag_runner.cli --show-steps --write-state

# Dry-run mode
python -m governance.dag_runner.cli --dry-run --json

# Graph-only mode
python -m governance.dag_runner.cli --graph --json

# V2A mocked agent execution
python -m governance.dag_runner.cli --mode agent_execution --write-state --json

# Continuation from prior run
python -m governance.dag_runner.cli --mode agent_execution --continue-from <step> --state-path governance_run_state.json

# Full test suite
python -m pytest tests/governance -q
```

#### R4-C: V2A acceptance criteria checklist

Verify each criterion from the plan:

| # | Criterion | Evidence required |
|---|-----------|-------------------|
| 1 | All 204 existing tests pass | Test suite output |
| 2 | V1 shell mode produces identical output | Compare text output before/after |
| 3 | `--dry-run` produces trace events without artifacts | JSON output inspection |
| 4 | `--graph` emits valid DAG JSON with component_kind fields | JSON output inspection |
| 5 | `--mode agent_execution` with MockExecutionBackend produces artifact envelopes | File existence check in `.claude/run/artifacts/` |
| 6 | All artifacts written match hook envelope format | Envelope schema validation |
| 7 | Halt-on-critical-failure stops DAG traversal | Dedicated test |
| 8 | Drift detection blocks on critical drift | Dedicated test |
| 9 | Continuation fails closed when guardrails violated | Dedicated test |
| 10 | Exit codes align with failure categories | Exit code tests |
| 11 | Component-kind dispatch routes correctly for all steps | Existing V2 tests |

#### R4-D: Produce acceptance record

Document:
- All criteria met / not met
- All deferrals with rationale
- Remaining open items classified as V2B or future
- Updated V2A status assessment

**Success criteria for R4**:
- All 11 V2A acceptance criteria verified with evidence. **MET**
- Acceptance record produced with clear status. **MET** → `DAG_RUNNER_V2A_ACCEPTANCE_RECORD.md`

---

## 5. Critical File Remediation Matrix

| File | Defect | Remediation Action | Phase | Status | Tests |
|------|--------|-------------------|-------|--------|-------|
| `executor.py` | F1: halt-on-critical `break` exits wrong loop scope | Added `halted` flag, outer loop break, remaining steps SKIP | R1-A | **FIXED** | 6 in `test_executor_halt.py` |
| `executor.py` | F3: artifact_writer not imported or called | Imported `write_artifact_envelope`, disk-write loop, `artifact_produced` trace | R2-A | **FIXED** | 15 in `test_executor_artifacts.py` |
| `executor.py` | F10: trace events missing (partial) | Emitting `backend_invocation_started/completed/failed`, `artifact_produced`, `blocking_event_raised` | R3-D | **FIXED** | 6 in `test_trace_events.py` |
| `cli.py` | F2: imports non-existent `load_run_state_from_path` | Function added to `state_store.py`; import resolved | R1-B | **FIXED** | 5 in `test_state_store.py` |
| `cli.py` | F5: drift detection not integrated | Imported `detect_drift`, call between validate and plan, blocks on critical | R2-B | **FIXED** | 5 in `test_cli_drift.py` |
| `cli.py` | F6: diagnostics not integrated | Imported `build_diagnostic_report`, included in JSON and text output | R2-C | **FIXED** | 4 in `test_cli_diagnostics.py` |
| `cli.py` | F7: exit codes only 0/1 | Exit code mapping implemented per plan table (0/1/2/3/4/5/10/11) | R3-A | **FIXED** | 8 in `test_cli_exit_codes.py` |
| `state_store.py` | F2: `load_run_state_from_path` does not exist | Added function: load JSON → reconstruct GovernanceRunState | R1-B | **FIXED** | 5 in `test_state_store.py` |
| `state_store.py` | F9: `StoredNodeResult` missing `latency_ms`, `token_count` | Added fields with defaults, populated in `build_stored_run_state()` | R3-C | **FIXED** | 2 in `test_state_store_v2_metadata.py` |
| `planner.py` | F8: `layer_groups()` missing, `--phase` non-functional | Option B: `--phase` emits warning, documented as deferred | R3-B | **FIXED** | 2 in `test_cli_phase_warning.py` |

---

## 6. Test Recovery Plan

### Tests added during remediation

**All tests implemented and passing.** Total new tests: 53.

| Test | Phase | File | Priority | Status |
|------|-------|------|----------|--------|
| T1: halt-on-critical-failure | R1-A | `test_executor_halt.py` | **P0** | PASS |
| T2: halt-on-critical-failure (non-halting) | R1-A | `test_executor_halt.py` | **P0** | PASS |
| T3: continuation round-trip | R1-B | `test_state_store.py` | **P0** | PASS |
| T4: continuation corrupt JSON | R1-B | `test_state_store.py` | **P0** | PASS |
| T5: CLI continuation | R1-B | `test_state_store.py` | **P0** | PASS |
| T6: artifact envelope disk write | R2-A | `test_executor_artifacts.py` | **P1** | PASS |
| T7: artifact write dry-run bypass | R2-A | `test_executor_artifacts.py` | **P1** | PASS |
| T8: artifact write failure → step FAIL | R2-A | `test_executor_artifacts.py` | **P1** | PASS |
| T9: drift detection CLI blocking | R2-B | `test_cli_drift.py` | **P1** | PASS |
| T10: drift detection CLI pass-through | R2-B | `test_cli_drift.py` | **P1** | PASS |
| T11: diagnostics in JSON output | R2-C | `test_cli_diagnostics.py` | **P1** | PASS |
| T12: exit code 0 (ready) | R3-A | `test_cli_exit_codes.py` | **P2** | PASS |
| T13: exit code 1 (structural/drift) | R3-A | `test_cli_exit_codes.py` | **P2** | PASS |
| T14: exit code 2 (halt-on-critical) | R3-A | `test_cli_exit_codes.py` | **P2** | PASS |
| T15: exit code 10 (review_only) | R3-A | `test_cli_exit_codes.py` | **P2** | PASS |
| T16: exit code 11 (blocked) | R3-A | `test_cli_exit_codes.py` | **P2** | PASS |
| T17: StoredNodeResult V2 metadata | R3-C | `test_state_store_v2_metadata.py` | **P2** | PASS |
| T18: phase scope warning | R3-B | `test_cli_phase_warning.py` | **P2** | PASS |
| T19: trace event coverage | R3-D | `test_trace_events.py` | **P2** | PASS |

### Integration paths covered

| Integration Path | Tests | Coverage |
|-----------------|-------|----------|
| executor → artifact_writer → disk | T6, T7, T8 | **COVERED** (15 tests) |
| cli → drift_detector → block/pass | T9, T10 | **COVERED** (5 tests) |
| cli → diagnostics → JSON output | T11 | **COVERED** (4 tests) |
| cli → state_store → GovernanceRunState reconstruction | T3, T4, T5 | **COVERED** (5 tests) |
| executor → halt-on-critical → skip remaining | T1, T2 | **COVERED** (6 tests) |
| cli → exit code mapping | T12-T16 | **COVERED** (8 tests) |
| state_store → V2 metadata persistence | T17 | **COVERED** (2 tests) |

### Acceptance evidence — VERIFIED

- Full `pytest tests/governance -q` passes: **313 passed, 0 failed** (2026-04-18)
- Tests T1-T5 (P0): **ALL PASS** — contract-breaking defects fixed
- Tests T6-T11 (P1): **ALL PASS** — V2A integration wiring functional
- Manual verification commands (R4-B): **ALL PRODUCE EXPECTED OUTPUT**

---

## 7. Scope Decisions and Deferrals

| Item | Decision | Rationale | Doc Update Required? |
|------|----------|-----------|---------------------|
| **Prompt assembly executor integration** (F4/F11) | **Defer to V2B** | MockExecutionBackend ignores prompt input. Integration is meaningless until a real backend consumes it. The `PromptAssemblyContext` vs dict inconsistency (F11) should be resolved as part of V2B when prompt assembly is actually consumed. | Yes — document as V2B prerequisite in acceptance record. |
| **Input bounding executor integration** | **Defer to V2B** | Same rationale as prompt assembly — no consumer in V2A. | Yes — document alongside prompt assembly deferral. |
| **Missing informational drift checks** (F12: duplicate invariant logic, doc path consistency) | **Defer — V2A acceptable without** | Both are informational-severity. They produce warnings, not blocks. No V2A acceptance criterion requires them. | No — already classified as informational in review. |
| **Expanded trace event coverage** (F10 beyond minimum) | **Partial: emit 5 minimum in V2A, defer remaining 7 to V2B/post-V2A** | Full 13-type coverage requires prompt_assembly and input_bounding integration (deferred) and artifact_validated (requires output_validator, which is V2B). The 5 minimum events (`backend_invocation_started/completed/failed`, `artifact_produced`, `blocking_event_raised`) cover the observable V2A execution surface. | No — minimum coverage is sufficient for V2A observability. |
| **Full artifact schema validation** (plan 4.3, 4.4) | **Defer to V2B** | Schema definitions and pre-step input validation are meaningful only when real backends produce non-deterministic output. MockExecutionBackend payloads are controlled test data. | Yes — document as V2B prerequisite. |
| **Path-bounded file access enforcement** (plan 3.3) | **Defer to V2B** | No file access occurs in V2A execution (MockExecutionBackend). Path bounding is a security constraint for live backends that read repo files during prompt assembly. | Yes — document as V2B security prerequisite. |
| **`ExecutionBackend.execute_step()` signature reconciliation** (F14) | **Defer to V2B** | Current signature works for MockExecutionBackend. Real backends will need the plan's `PromptAssemblyContext` parameter, which requires prompt assembly integration (also V2B). | No — already flagged as benign for V2A. |
| **`--phase` flag** (F8) | **Acceptable to defer with warning** | Phase-scoped execution is a convenience feature. No V2A acceptance criterion mandates it. If deferred, emit a CLI warning when `--phase` is used. | Yes — document as known non-functional flag if deferred. |

---

## 8. Live-Testing Gate

### Mocked-testing gate — ALL MODES READY

All mocked-testing modes are now operational:

| Mode | Command | Status |
|------|---------|--------|
| V1 shell | `python -m governance.dag_runner.cli` | READY |
| Graph-only | `python -m governance.dag_runner.cli --graph --json` | READY |
| Dry-run | `python -m governance.dag_runner.cli --dry-run` | READY |
| Mock agent_execution | `python -m governance.dag_runner.cli --mode agent_execution` | READY (full: in-memory + disk artifacts) |
| Mock agent_execution with disk artifacts | `python -m governance.dag_runner.cli --mode agent_execution --write-state` | READY |
| Continuation | `python -m governance.dag_runner.cli --continue-from <step> --state-path <path>` | READY |
| Test suite | `python -m pytest tests/governance -q` | READY (313 tests) |

### Previously blocked modes — ALL UNBLOCKED

| Mode | Was Blocked By | Gate Condition | Status |
|------|---------------|----------------|--------|
| `--continue-from` | F2 (ImportError) | R1-B complete | **UNBLOCKED** |
| Mock agent_execution with disk artifacts | F3 (artifact_writer unwired) | R2-A complete | **UNBLOCKED** |
| Halt-on-critical | F1 (broken control flow) | R1-A complete | **UNBLOCKED** |
| Drift blocking | F5 (drift unwired) | R2-B complete | **UNBLOCKED** |
| Semantic exit codes | F7 (only 0/1) | R3-A complete | **UNBLOCKED** |

### Controlled live-testing preconditions

Controlled live testing (with real Claude backends, V2B) MUST NOT proceed until ALL of the following are true:

1. **R1-R3 complete**: All remediation phases finished and verified. **SATISFIED**
2. **R4 acceptance review passed**: All 11 V2A acceptance criteria verified with evidence. **SATISFIED**
3. **All P0 tests pass** (T1-T5): Contract-breaking defects proven fixed. **SATISFIED**
4. **All P1 tests pass** (T6-T11): V2A integration wiring proven functional. **SATISFIED**
5. **Full test suite green**: `pytest tests/governance -q` — all V1 + V2 + new tests. **SATISFIED** (313 passed)
6. **V2B implementation started**: `ClaudeCLIBackend` or `NativeClaudeBackend` exists (at minimum as a scaffold). **NOT YET**
7. **Prompt assembly integrated into executor**: Currently deferred (DF-1). Must be resolved before live backends can receive meaningful prompt context. **NOT YET**
8. **Path bounding enforced**: Currently deferred (DF-7). Must be resolved before live backends read repo files. **NOT YET**

V2A preconditions (1-5): ALL SATISFIED.
V2B preconditions (6-8): REMAINING — these gate live testing.

### Explicit blockers — ALL CLOSED

| Blocker | Finding | Phase | Status |
|---------|---------|-------|--------|
| Halt-on-critical does not halt | F1 | R1-A | **CLOSED** |
| Continuation crashes with ImportError | F2 | R1-B | **CLOSED** |
| Artifacts not written to disk | F3 | R2-A | **CLOSED** |
| Drift detection does not block | F5 | R2-B | **CLOSED** |
| Diagnostics not in output | F6 | R2-C | **CLOSED** |
| Exit codes wrong | F7 | R3-A | **CLOSED** |
| V2 metadata not persisted | F9 | R3-C | **CLOSED** |

All 7 blockers CLOSED. V2A accepted 2026-04-18.

---

## 9. Final Status

### Assessment: V2A COMPLETE (mocked-testing ready)

V2A remediation is complete. All four phases (R1-R4) executed successfully:

- All 7 must-fix items closed with test evidence.
- All 11 V2A acceptance criteria met.
- 313 tests pass with zero regressions.
- All manual verification commands produce expected output.
- Acceptance record produced: `DAG_RUNNER_V2A_ACCEPTANCE_RECORD.md`.

### Remediation scope (actual)

| Phase | Commit | Files touched | New tests |
|-------|--------|---------------|-----------|
| R1 | `c56aee8` | executor.py, state_store.py | 11 |
| R2 | `143a59d` | executor.py, cli.py | 24 |
| R3 | `3f36a34` | cli.py, state_store.py, planner.py, executor.py | 18 |
| R4 | (verification only) | — | 0 |
| **Total** | | | **53 new tests** |

### Next milestone: V2B

V2B (live Claude backends) requires:
1. Real execution backend (`ClaudeCLIBackend` or `NativeClaudeBackend`)
2. Prompt assembly integration into executor (DF-1)
3. Input bounding integration (DF-5)
4. Path-bounded file access enforcement (DF-7)
5. `ExecutionBackend.execute_step()` signature reconciliation (DF-3)
6. Full artifact schema validation (DF-6)

Controlled live testing MUST NOT proceed until all V2B prerequisites are met.
