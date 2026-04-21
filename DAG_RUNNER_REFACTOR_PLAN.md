# DAG Runner Refactoring Plan — Validation-Driven, Strictly Incremental

## Context

The governance DAG runner has a fundamental architectural flaw: it uses single-shot raw LLM text as a strict machine transport layer. The subprocess `claude -p --output-format json --tools ""` returns a JSON envelope whose `result` field contains the model's free-form text. The parser (`_parse_backend_response()`, execution_backend.py:367) must extract a perfectly formed JSON artifact from that text. This breaks under: tool-use contamination, timeout, truncation, prose preamble, and large payloads. A full day of debugging (7+ rounds) failed to stabilize this because patches addressed symptoms while the transport remained fragile.

**Proposed fix:** The Claude CLI supports `--json-schema <schema>` (confirmed via `claude --help`) and `--bare` mode. These are hypothesized to eliminate transport fragility by constraining model output at the API level. However, their exact runtime behavior is **unverified**. This plan treats them as hypotheses to be validated before any production code depends on them.

**Constraint:** No phase may proceed until the prior phase's validation gates pass. No code change may assume CLI behavior that has not been empirically confirmed.

---

## Phase 0 — CLI Behavior Probe (MANDATORY, No Code Changes)

### Goal
Empirically determine the exact behavior of `--json-schema` and `--bare` flags before writing any production code.

### Steps

**0.1 — Create a standalone probe script: `scripts/probe_cli_schema.py`**

This script runs 4 Claude CLI subprocess invocations with controlled inputs and captures full stdout/stderr for each:

| Probe | Command | Purpose |
|-------|---------|---------|
| A | `claude -p --output-format json --no-session-persistence --tools "" --json-schema <schema> "Return test:hello"` | Baseline: does `--json-schema` work with `--tools ""`? |
| B | `claude -p --output-format json --no-session-persistence --tools "" --bare --json-schema <schema> "Return test:hello"` | Combined: does `--bare` change schema behavior? |
| C | `claude -p --output-format json --no-session-persistence --tools "" "Return test:hello"` | Control: current behavior without schema |
| D | `claude -p --output-format json --no-session-persistence --tools "" --bare "Return test:hello"` | Isolation only: does `--bare` alone change output? |

The schema for probes A and B:
```json
{"type":"object","properties":{"artifacts":{"type":"object","properties":{"test_artifact":{"type":"object"}},"required":["test_artifact"]}},"required":["artifacts"]}
```

The prompt for all probes:
```
Respond with a JSON object: {"artifacts": {"test_artifact": {"produced_by": "probe", "value": "hello"}}}
```

For each probe, the script:
1. Captures full `proc.stdout` and `proc.stderr`
2. Parses the outer envelope via `json.loads(stdout)`
3. Records: `envelope.keys()`, `type(envelope["result"])`, `envelope.get("result", "")[:500]`, whether `json.loads(envelope["result"])` succeeds, presence of any `structured_output` or similar top-level field, `envelope.get("usage", {})`
4. Writes all results to `scripts/probe_results.json`

**0.2 — Run the probe script**

```bash
python scripts/probe_cli_schema.py
```

**0.3 — Answer these questions definitively (record answers in probe_results.json)**

| Question | What to check |
|----------|---------------|
| Does `--json-schema` guarantee the `result` field is valid JSON? | Probe A: `json.loads(envelope["result"])` succeeds? |
| Does the schema-constrained JSON appear in `result` or a separate field? | Probe A: compare `envelope.keys()` vs Probe C |
| Is the `result` field a string or a parsed object? | Probe A: `type(envelope["result"])` |
| Does `--json-schema` eliminate prose/commentary in `result`? | Probe A: does `result` start with `{` directly? |
| Does `--bare` change the envelope shape? | Probe D vs Probe C: same keys? |
| Does `--bare` + `--json-schema` work together? | Probe B: success and same shape as Probe A? |
| Does the existing `_parse_backend_response()` work on schema-constrained output? | Feed Probe A stdout into `_parse_backend_response()` manually |
| What is the `returncode` for each probe? | All probes: `proc.returncode` |

**0.4 — DO NOT PROCEED to Phase 1 until all 8 questions are answered with empirical evidence.**

### Success Criteria
- `probe_results.json` exists with all 4 probe results
- All 8 questions answered with observed values, not assumptions
- If `--json-schema` does NOT constrain the `result` field to valid JSON, the entire approach must be redesigned before Phase 1

### Rollback
- Phase 0 produces no production code changes. Nothing to roll back.
- If `--json-schema` is ineffective, pivot to alternative approach: break artifacts into smaller outputs per step, or use `--output-format stream-json` with partial capture.

---

## Phase 1 — Structured Output (Feature-Flagged)

### Goal
Introduce `--json-schema` support WITHOUT altering existing parsing logic. The new path must be opt-in via a feature flag so both paths can be compared.

### Precondition
Phase 0 confirmed that `--json-schema` constrains `result` to valid JSON matching the schema.

### Code Changes

**1.1 — `governance/dag_runner/execution_backend.py`**

Add a new function (after line 148, near the other helpers):

```python
def _build_artifact_json_schema(expected_outputs: list[str], step_name: str) -> str:
```

- Builds a JSON Schema string requiring `{"artifacts": {<name>: object, ...}}`
- Each artifact property is `{"type": "object"}` with `additionalProperties: true`
- The `"artifacts"` key and each output name are in `"required"`
- Returns the JSON string
- Keep schema minimal (~300 chars) to avoid Windows command-line limits

**1.2 — `governance/dag_runner/execution_backend.py`**

Modify `ClaudeCodeCLIBackend.__init__()` (line 550):

- Add parameter: `use_structured_output: bool = False`
- Store as `self._use_structured_output`

**1.3 — `governance/dag_runner/execution_backend.py`**

Modify `ClaudeCodeCLIBackend.execute_step()` command construction (line 586-593):

- When `self._use_structured_output` is `True` AND `step.outputs` is non-empty:
  - Compute `json_schema_str = _build_artifact_json_schema(list(step.outputs), step.name)`
  - Append `"--json-schema", json_schema_str` to the `cmd` list
- When `False` or no declared outputs: command is unchanged

**Do NOT:**
- Remove `--tools ""`
- Add `--bare` (that is Phase 2)
- Change `_parse_backend_response()` in any way
- Change the parser call site (line ~663)

The existing `_parse_backend_response()` must work on the schema-constrained output. Phase 0 will have confirmed this. If Phase 0 reveals the output is in a different field (e.g., `structured_output` instead of `result`), then add a **new** parse function `_parse_structured_response()` that extracts from that field and falls back to `_parse_backend_response()` when the field is absent.

**1.4 — `governance/dag_runner/cli.py`**

Add CLI flag (after line 175, near `--backend-isolation`):

```python
parser.add_argument(
    "--use-structured-output",
    action="store_true",
    default=False,
    help="Enable --json-schema for backend-dispatched steps (experimental).",
)
```

Thread this flag through to `ClaudeCodeCLIBackend(use_structured_output=args.use_structured_output)`.

**1.5 — Tests**

In `tests/governance/test_claude_code_cli_backend.py`:

- `TestJsonSchemaGeneration`:
  - `test_schema_single_output`: schema for `["claim_classification_map"]` has correct structure
  - `test_schema_multiple_outputs`: schema for `["change_impact_report", "doc_update_plan"]` requires both
  - `test_schema_requires_artifacts_key`: top-level `required` includes `"artifacts"`
  - `test_schema_valid_json`: schema string is valid JSON

- `TestCommandWithStructuredOutput`:
  - `test_json_schema_in_command_when_enabled`: when `use_structured_output=True` and step has outputs, `--json-schema` appears in cmd
  - `test_no_json_schema_when_disabled`: when `use_structured_output=False`, cmd is unchanged
  - `test_no_json_schema_for_structural_steps`: steps with no declared outputs skip `--json-schema`

In `tests/governance/test_cli_backend_integration.py`:

- `TestStructuredOutputIntegration`:
  - `test_schema_constrained_result_parses_correctly`: mock subprocess returns envelope where `result` is schema-valid JSON → artifacts extracted → PASS
  - `test_fallback_when_result_is_prose`: mock subprocess returns old-style prose+JSON → existing fallback path extracts artifacts → PASS (proves feature flag OFF behavior is identical)

### Validation (MANDATORY)

**Gate 1 — Unit tests:**
```bash
python -m pytest tests/governance/test_claude_code_cli_backend.py tests/governance/test_cli_backend_integration.py -x -v
```
All new and existing tests pass.

**Gate 2 — Full regression:**
```bash
python -m pytest tests/governance/ -x -q
```
Zero regressions.

**Gate 3 — Live run WITHOUT flag (behavior must be identical):**
```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --request-file request.json --request-id phase1-control --request-source manual --write-state --json
```
Compare output shape to previous runs. Must show identical behavior (same steps pass/fail, same failure shapes).

**Gate 4 — Live run WITH flag:**
```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --use-structured-output --request-file request.json --request-id phase1-test --request-source manual --write-state --json
```
Check:
- Does `classify-claims` PASS?
- Does `normalize-terminology` reach backend execution (not skipped)?
- If `normalize-terminology` still fails, is the failure_stage `backend_timeout` (timeout, not parse)?
- Are parse failures eliminated for steps that do complete?
- Is `raw_output_preview` clean JSON (no prose, no fences)?

### Success Criteria
- Flag OFF: identical behavior to pre-change (zero regressions)
- Flag ON: `classify-claims` consistently PASSes (no more parse failures)
- Flag ON: any remaining failures are `backend_timeout`, not `backend_parse`

### Rollback
- Remove the `--use-structured-output` CLI flag and `use_structured_output` parameter
- Remove `_build_artifact_json_schema()` function
- All existing behavior is untouched because the flag defaults to `False`

---

## Phase 2 — Isolation (Separate from Structured Output)

### Goal
Validate whether `--bare` is a reliable replacement for the current temp-dir isolation approach.

### Precondition
Phase 1 is complete and validated. Structured output flag is available but this phase does NOT depend on it.

### Code Changes

**2.1 — `governance/dag_runner/execution_backend.py`**

Modify `ClaudeCodeCLIBackend.__init__()`:

- Extend `isolation_mode` choices: `"project"`, `"isolated"` (existing), `"bare"` (new)
- Store the mode

Modify `execute_step()` command construction:

- When `isolation_mode == "bare"`: append `"--bare"` to cmd, do NOT change cwd
- When `isolation_mode == "isolated"`: existing temp-dir behavior unchanged
- When `isolation_mode == "project"`: existing default behavior unchanged

**2.2 — `governance/dag_runner/cli.py`**

Extend `--backend-isolation` choices (line 168):

```python
choices=["project", "isolated", "bare"]
```

**2.3 — Tests**

- `test_bare_flag_in_command`: when `isolation_mode="bare"`, `--bare` is in cmd
- `test_bare_does_not_change_cwd`: subprocess cwd is None (inherits process cwd), not temp dir

### Validation (MANDATORY)

Run 3 live comparisons with structured output **OFF** (isolate the variable):

**Run 1 — Current isolation (control):**
```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --backend-isolation isolated --request-file request.json --request-id phase2-isolated --request-source manual --write-state --json
```

**Run 2 — Bare mode:**
```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --backend-isolation bare --request-file request.json --request-id phase2-bare --request-source manual --write-state --json
```

**Run 3 — No isolation (project mode):**
```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --backend-isolation project --request-file request.json --request-id phase2-project --request-source manual --write-state --json
```

Compare across all 3:
- Does `--bare` prevent tool-use contamination (like `--backend-isolation isolated` does)?
- Does `--bare` produce the same step results as temp-dir isolation?
- Does project mode still show tool-use contamination?

### Success Criteria
- `--bare` eliminates tool-use contamination equivalently to temp-dir isolation
- `--bare` does not introduce new failure modes
- Step results are consistent between `bare` and `isolated` modes

### Rollback
- Remove `"bare"` from isolation choices
- No other code was changed

---

## Phase 3 — Per-Step Timeout Configuration

### Goal
Address legitimate long-running steps that timeout at 120s even with correct structured output.

### Precondition
Phase 1 structured output is validated and ON. Remaining failures are `backend_timeout`, not `backend_parse`.

### Code Changes

**3.1 — `governance/dag_runner/models.py`**

Add field to `AgentSpec` (after line 91):

```python
timeout_ms: int | None = None
```

**3.2 — `governance/dag_runner/execution_backend.py`**

Modify `execute_step()` (after line 583, before line 601):

```python
effective_timeout_ms = agent.timeout_ms if agent.timeout_ms else self._timeout_ms
timeout_s = effective_timeout_ms / 1000.0
```

Add `effective_timeout_ms` to the `backend_result_received` trace event detail.

**3.3 — Agent YAML assembly**

In the agent assembler (find where `AgentSpec` is constructed from YAML — likely in `governance/dag_runner/assembler.py` or wherever agents.yaml is parsed):

- Read `timeout_ms` from the agent YAML dict
- Pass it to `AgentSpec(timeout_ms=yaml_dict.get("timeout_ms"))`

**3.4 — `.claude/workflows/packages/agents.yaml`**

Add timeout overrides only to agents that have demonstrated timeout failures:

```yaml
# claim-classification-agent (opus, complex reasoning)
timeout_ms: 180000

# terminology-normalization-agent (previously timing out at 120s)
timeout_ms: 180000

# change-impact-agent (opus, many inputs)
timeout_ms: 180000
```

All other agents: no `timeout_ms` field (use backend default of 120s).

**3.5 — Tests**

- `test_agent_timeout_overrides_default`: agent with `timeout_ms=180000` → subprocess called with `timeout=180.0`
- `test_default_timeout_when_agent_has_none`: agent with `timeout_ms=None` → uses backend default
- `test_effective_timeout_in_trace`: trace event includes the timeout value used

### Validation (MANDATORY)

**Gate 1 — Tests:**
```bash
python -m pytest tests/governance/ -x -q
```

**Gate 2 — Live run with structured output ON:**
```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --use-structured-output --request-file request.json --request-id phase3-test --request-source manual --write-state --json
```

Check:
- `normalize-terminology` completes within 180s (no longer `backend_timeout`)
- `classify-claims` still PASSes
- Other steps are not artificially slowed

### Success Criteria
- Previously-timing-out steps now complete successfully
- No step exceeds its configured timeout
- Diagnostics show `effective_timeout_ms` per step

### Rollback
- Remove `timeout_ms` entries from agents.yaml
- Remove `timeout_ms` field from `AgentSpec`
- Revert `execute_step()` timeout logic to use `self._timeout_ms` directly

---

## Phase 4 — Retry (Only After Stability)

### Goal
Handle transient failures without masking deterministic bugs.

### Precondition
Phases 1-3 validated. The DAG produces consistent results across multiple runs. Remaining failures are rare and non-deterministic.

### Code Changes

**4.1 — `governance/dag_runner/execution_backend.py`**

Add to `ClaudeCodeCLIBackend.__init__()`:
- `max_retries: int = 1` (1 retry = 2 total attempts)

Add retry loop around the `subprocess.run()` call in `execute_step()`:

```python
for attempt in range(1 + self._max_retries):
    try:
        proc = subprocess.run(...)
        # ... existing parse logic ...
        if _should_retry(result, attempt, self._max_retries):
            time.sleep(2)
            continue
        return result
    except subprocess.TimeoutExpired:
        if attempt < self._max_retries:
            time.sleep(2)
            continue
        # ... existing timeout handling ...
```

`_should_retry()` returns True ONLY for:
- `timeout` (TimeoutExpired)
- Empty/missing `result` field with `is_error=False` (API glitch)

`_should_retry()` returns False for:
- `runtime` failures (OSError, nonzero exit) — deterministic
- `cli_is_error_flag` — deterministic
- `disallowed_tool_use_response` — would repeat
- Parse failures with non-empty result — deterministic for same input
- Any successful result (even with wrong artifacts) — not transient

**4.2 — `governance/dag_runner/models.py`**

Add to `AgentExecutionResult`:
```python
retry_count: int = 0
```

**4.3 — `governance/dag_runner/cli.py`**

Add CLI flag:
```python
parser.add_argument("--max-retries", type=int, default=1, help="Max retries per step on transient failures (default: 1).")
```

**4.4 — Tests**

- `test_retry_on_timeout_then_success`: mock subprocess raises TimeoutExpired once, succeeds on retry → PASS with `retry_count=1`
- `test_all_retries_exhausted`: all attempts timeout → FAIL with last failure, `retry_count=max`
- `test_no_retry_on_os_error`: OSError → immediate FAIL, `retry_count=0`
- `test_no_retry_on_parse_failure`: parse failure with non-empty result → immediate FAIL, `retry_count=0`
- `test_retry_count_in_diagnostics`: retry count appears in step diagnostics

### Validation (MANDATORY)

**Gate 1 — Tests pass:**
```bash
python -m pytest tests/governance/ -x -q
```

**Gate 2 — Live run confirms retry does not interfere with stable runs:**
```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --use-structured-output --max-retries 1 --request-file request.json --request-id phase4-test --request-source manual --write-state --json
```

- Steps that PASS should show `retry_count: 0`
- Total latency should not increase significantly

### Success Criteria
- Retry logic is only triggered by genuine transient failures
- Stable runs show zero retries
- retry_count is visible in diagnostics for every step

### Rollback
- Set `max_retries` default to 0 (disables retry)
- Or remove retry loop entirely — self-contained in `execute_step()`

---

## Phase 5 — Cleanup (Last, After Multiple Successful Runs)

### Goal
Remove accumulated complexity. Only after Phases 1-4 are validated with multiple successful live runs.

### Precondition
At least 3 consecutive successful live DAG runs with structured output ON. All Layer A steps (classify-claims, normalize-terminology, route-claims-by-role) consistently PASS.

### Changes (each independently reversible)

**5.1 — Simplify `[REQUIRED OUTPUT FORMAT]` prompt section**

In `governance/dag_runner/prompt_assembly.py` (line 306-331):
- When structured output is active, reduce the format section to a minimal reminder (artifact names and `produced_by` requirement)
- Remove the "Do NOT wrap in markdown code fences" / "Do NOT include commentary" instructions (schema enforces this)
- Keep the full verbose version as fallback when structured output is off

**5.2 — Remove temp-dir isolation if `--bare` is validated**

Only if Phase 2 confirmed `--bare` equivalence:
- Remove `"isolated"` from `--backend-isolation` choices
- Remove `get_isolated_cwd()` from `runtime_info.py`
- Update `ClaudeCodeCLIBackend` to not accept `isolation_mode="isolated"`

**5.3 — Add trace events for fallback parser activation**

In `_parse_backend_response()`: if the primary `json.loads(result_text)` fails and a fallback path is triggered (code fence stripping, brace extraction, tool-use detection), emit a warning trace event. This signals that schema enforcement may not be active for that step.

**5.4 — Evaluate SKILL.md content restoration**

The `canonical-terminology-map/SKILL.md` was cut from 781→164 lines to address timeout. With structured output + increased timeout, evaluate whether adding back one compact worked example improves output quality. Test with a live run and compare artifact content.

**5.5 — Clean stale session artifacts**

Remove old debug/session directories from `.claude/run/sessions/` that are no longer needed.

### Validation
- Full test suite passes after each sub-change
- Live DAG run still produces consistent results
- No step regresses from PASS to FAIL

### Rollback
- Each sub-change (5.1-5.5) is independently reversible
- The feature flag and fallback paths still exist as safety nets

---

## Critical Files

| File | Phases | Changes |
|------|--------|---------|
| `scripts/probe_cli_schema.py` | 0 | NEW — standalone CLI behavior probe |
| `governance/dag_runner/execution_backend.py` | 1, 2, 3, 4 | Schema builder, feature flag, bare mode, timeout override, retry loop |
| `governance/dag_runner/cli.py` | 1, 2, 4 | `--use-structured-output`, extended `--backend-isolation`, `--max-retries` |
| `governance/dag_runner/models.py` | 3, 4 | `AgentSpec.timeout_ms`, `AgentExecutionResult.retry_count` |
| `governance/dag_runner/prompt_assembly.py` | 5 | Simplify format section |
| `governance/dag_runner/runtime_info.py` | 5 | Remove temp-dir isolation |
| `.claude/workflows/packages/agents.yaml` | 3 | Per-agent `timeout_ms` |
| `tests/governance/test_claude_code_cli_backend.py` | 1, 2, 3, 4 | Schema, command, timeout, retry tests |
| `tests/governance/test_cli_backend_integration.py` | 1 | Structured output integration tests |

## Execution Sequencing

```
Phase 0 (probe) ── GATE ──→ Phase 1 (structured output, flagged) ── GATE ──→ Phase 2 (bare isolation)
                                                                         │
                                                                         ├── GATE ──→ Phase 3 (timeout)
                                                                         │
                                                                         └── GATE ──→ Phase 4 (retry)
                                                                                          │
                                                                                          └── GATE ──→ Phase 5 (cleanup)
```

Every arrow represents a mandatory validation gate. No phase proceeds until the prior phase's success criteria are met with empirical evidence.
