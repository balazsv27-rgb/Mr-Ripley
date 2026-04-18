# DAG Runner V2B Implementation Plan (Revised)

---

## 1. Planning Basis Correction

### V2A completion baseline

V2A is complete and accepted as mocked-testing ready (2026-04-18). Evidence:

| Dimension | Value |
|-----------|-------|
| Full test suite | 313 tests, ALL PASS |
| Must-fix items | 7 of 7 CLOSED |
| V2A acceptance criteria | 11 of 11 MET |
| Acceptance record | `DAG_RUNNER_V2A_ACCEPTANCE_RECORD.md` |

V2A provides:
- Complete executor pipeline with V1 shell mode, V2 dry-run, V2 mock agent_execution.
- MockExecutionBackend producing deterministic artifact envelopes.
- Halt-on-critical-failure, drift detection blocking, diagnostics, semantic exit codes, continuation support, required-input presence validation.
- `prompt_assembly.py`, `input_bounding.py` exist as standalone modules but are NOT wired into the executor pipeline.
- `ExecutionBackend.execute_step()` accepts `(step, agent, config, run_state, spec)` — no prompt context parameter.
- `skill_resolver.py` loads SKILL.md files from `.claude/skills/<name>/SKILL.md` as raw text content.
- `agent_resolver.py` resolves agent bindings and loads agent/skill instruction files from disk.

### Incorrect assumptions in the current plan (superseded)

The prior V2B plan contained three fundamental architectural misinterpretations:

**1. NativeClaudeBackend is invalid.**

The prior plan described `NativeClaudeBackend` as a "direct Anthropic API" backend (DF-B1), implying:
- An API client library (`anthropic` SDK)
- API key management and authentication
- Network-based request/response to Anthropic's API endpoints
- Per-request billing

This is **architecturally invalid** for this repository. The system MUST operate using **only local Claude Code capabilities** without any external API usage or billing. There is no Anthropic API key. There is no API client. There is no network call to `api.anthropic.com`. Any backend that assumes API-based execution is outside the project's execution model.

**2. CLI-only backend model is incomplete.**

The prior plan treated `ClaudeCLIBackend` (subprocess to `claude` CLI with plain prompt on stdin) as the only viable local backend and deferred tool-augmented execution entirely. This is incomplete because:

- Claude Code's local runtime supports two distinct execution modes: one-shot prompt (`claude -p`) and tool-augmented prompt mode (TAPM).
- TAPM is a local execution mode — NOT an API mode. It runs within the same `claude` process, using the same local authentication, with no additional billing.
- The prior plan's TAPM analysis (§3.4) correctly identified governance trade-offs but incorrectly framed the deferral as "plain prompt vs API tool calls." The real distinction is between two local execution envelopes with different determinism and governance profiles.

**3. SKILL.md was not correctly modeled as instruction payload.**

The prior plan's architecture implicitly treated skill invocation as an interactive slash-command mechanism (`/skill-name`). In reality:

- SKILL.md files are already registered internally by Claude Code's runtime.
- The DAG runner does NOT invoke skills via `/skill-name` — it reads SKILL.md content from disk via `skill_resolver.py` and injects it as instruction text into the assembled prompt.
- SKILL.md content is **executable instruction payload**: the full markdown text is concatenated into the prompt context so that the LLM follows the skill's rules during execution.
- No interactive UI mechanism is involved. No slash command is issued. The backend receives text containing SKILL.md instructions and produces a structured artifact response.

### Correct local-only execution model

The system operates using **local Claude Code execution only**:

- The `claude` CLI is installed locally and authenticated via local session.
- All execution happens on the local machine. No direct Anthropic API client integration. Execution depends on the locally installed and authenticated Claude Code runtime.
- No API key management. No per-request billing. No `anthropic` SDK dependency.
- Two local execution envelopes exist:
  1. **One-shot prompt mode** (`claude -p`): send assembled text, receive text response.
  2. **Tool-augmented prompt mode**: Claude Code uses its internal tool system (Read, Grep, Glob, etc.) during execution, under policy constraints.
- SKILL.md files are loaded from disk as instruction content, not invoked via slash commands.

### Explicit V2B prerequisites from V2A deferral list

| ID | Item | V2A Status |
|----|------|-----------|
| DF-1 | Prompt assembly executor integration | Deferred — module exists, not wired |
| DF-3 | `ExecutionBackend.execute_step()` signature reconciliation | Deferred — current sig works for Mock only |
| DF-5 | Input bounding executor integration | Deferred — used internally by prompt_assembly, not exposed to executor |
| DF-6 | Full artifact schema validation | Deferred — not needed for deterministic Mock payloads |
| DF-7 | Path-bounded file access enforcement | Deferred — no file access occurs in Mock |

### V2B scope boundary

V2B is strictly:

1. Real execution backend (`ClaudeCodeCLIBackend`)
2. Prompt assembly integration into executor (DF-1)
3. Input bounding integration (DF-5)
4. Path-bounded file access enforcement (DF-7)
5. `ExecutionBackend.execute_step()` signature reconciliation (DF-3)
6. Full artifact schema validation (DF-6)

V2B is NOT:

- API-based execution (NativeClaudeBackend or any Anthropic API client)
- Subagent orchestration or escalation dispatch
- Multi-backend runtime selection
- Semantic output validation beyond schema conformance
- Execution-layer features (trade signals, automated decisions)
- Phase-scoped execution (`--phase` remains non-functional)

V2B **defers** but **designs for**:

- `ClaudeCodeTAPMBackend` (tool-augmented prompt mode) — analysis in §5 concludes: defer to V2C. The `execute_step()` contract is designed to accommodate TAPM without signature changes.

---

## 2. Backend Architecture Redesign

### Backend taxonomy

Two backend types replace the prior plan's `ClaudeCLIBackend` / `NativeClaudeBackend` split:

#### `ClaudeCodeCLIBackend`

| Property | Value |
|----------|-------|
| **Execution model** | One-shot. Subprocess spawn of local `claude -p` with assembled prompt on stdin, structured response on stdout. Single request-response cycle. No tool loop. |
| **Determinism level** | High. Same prompt produces comparable output. Bounded by token budget. No runtime tool calls introduce variability. |
| **Failure surface** | Small. Process spawn + exit code + stdout parse. Three failure points: spawn failure, timeout, parse failure. |
| **Governance implications** | Natural fit for fail-closed governance. Single boundary: prompt in, artifact out. All file reads happen during assembly, before backend dispatch. Path bounding is a single pre-dispatch gate. Complete auditability: prompt + response = full execution record. |
| **When to use** | Default backend for V2B. All 12 governance skill steps. Sufficient for bounded analysis tasks where the context can be pre-assembled within token budget. |
| **API dependency** | None. Local `claude` CLI only. |
| **SKILL.md usage** | SKILL.md content is injected into `assembled_prompt` as instruction payload text. The backend sends this text to the local `claude` process. The process follows the instructions. No slash command is issued. |

#### `ClaudeCodeTAPMBackend` (deferred to V2C — see §5)

| Property | Value |
|----------|-------|
| **Execution model** | Multi-turn. Local Claude Code runtime with controlled tool access (Read, Grep, Glob, etc.). Claude may issue tool calls during execution, each intercepted by a policy enforcer. Bounded execution loop with max iterations. |
| **Determinism level** | Low. Tool call sequences are non-deterministic. Different runs may read different files, follow different reasoning paths. Output is structurally constrained but content-variable. |
| **Failure surface** | Large. Each tool call is a failure point. Tool errors, partial reads, policy violations, unbounded loops, intermediate state corruption. N tool calls = N additional failure points. |
| **Governance implications** | Requires runtime enforcement, not just assembly-time enforcement. Path bounding must intercept every tool call, not just pre-assembly reads. Execution loop must be bounded (max iterations, max tool calls, max wall time). Every tool call must be logged for auditability. Traceability is partial: must log the full tool-call conversation, not just prompt + response. |
| **When to use** | Steps that require dynamic context discovery — e.g., code inspection where the relevant files are not known at assembly time. NOT needed for the 12 governance skills in V2B, where inputs are well-defined by the DAG. |
| **API dependency** | None. Local Claude Code runtime only. |
| **SKILL.md usage** | SKILL.md content is injected as execution guidance in the initial prompt. The TAPM runtime follows these instructions while using tools. SKILL.md is NOT invoked via `/skill-name`. |

### Backend class hierarchy

```
ExecutionBackend (ABC)
├── MockExecutionBackend       ← V2A (unchanged)
├── ClaudeCodeCLIBackend       ← V2B (this plan)
└── ClaudeCodeTAPMBackend      ← V2C (deferred)
```

All backends implement the same `execute_step()` / `execute_structural_step()` contract. The executor does not know which backend is active — it passes `PromptContext` and receives `AgentExecutionResult`.

---

## 3. Execution Contract Revision

### Current contract (V2A)

```python
def execute_step(
    self,
    step: WorkflowStep,
    agent: AgentSpec,
    config: ExecutionConfig,
    run_state: GovernanceRunState,
    spec: AssembledWorkflowSpec,
) -> AgentExecutionResult:
```

### Target contract (V2B)

```python
def execute_step(
    self,
    step: WorkflowStep,
    agent: AgentSpec,
    config: ExecutionConfig,
    run_state: GovernanceRunState,
    spec: AssembledWorkflowSpec,
    prompt_context: PromptContext | None = None,
) -> AgentExecutionResult:
```

### `PromptContext` definition

```python
@dataclass(frozen=True)
class PromptContext:
    """Assembled and bounded prompt context for a single step."""
    assembled_prompt: str          # The full prompt text to send to the backend
    agent: AgentSpec | None = None # Resolved agent (for model selection, etc.)
    skill_content: str = ""        # SKILL.md content (instruction payload)
    agent_instructions: str = ""   # Agent .md content
    artifact_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_paths: list[str] = field(default_factory=list)
    token_budget: int = 100_000
    token_estimate: int = 0
    truncated: bool = False
    truncation_events: list[dict[str, str | int]] = field(default_factory=list)
```

### How `PromptContext` is used by each backend

| Backend | `PromptContext` usage |
|---------|----------------------|
| **MockExecutionBackend** | Ignores `prompt_context` entirely. Produces deterministic artifacts from step metadata. Backward compatible. |
| **ClaudeCodeCLIBackend** | Reads `prompt_context.assembled_prompt` as the single text blob to send on stdin. Reads `prompt_context.agent.model` to select `--model`. Does NOT decompose PromptContext further — the assembled prompt already contains all instruction content. |
| **ClaudeCodeTAPMBackend** (V2C) | Reads `prompt_context.assembled_prompt` as the initial system/user message. May also read `prompt_context.document_paths` to pre-authorize file access paths. Needs additional execution context (see below). |

### Why `prompt_context` is optional with default `None`

- `MockExecutionBackend` ignores it — backward compatible.
- V1 shell mode never calls `execute_step` — unaffected.
- Dry-run path assembles prompt for tracing but does not invoke backend.
- Only live backends consume `prompt_context`.
- Live backends fail closed when `prompt_context is None`.

### Forward compatibility for TAPM

The `execute_step()` contract does NOT need to change for TAPM. The `ClaudeCodeTAPMBackend` in V2C will:

1. Receive the same `PromptContext` (assembled prompt + metadata).
2. Internally construct a tool-augmented session from the assembled prompt.
3. Apply its own runtime policy enforcement (path bounding, loop limits, tool filtering).
4. Return the same `AgentExecutionResult`.

No additional parameters are needed on `execute_step()`. TAPM-specific configuration (max tool calls, tool policy, loop budget) belongs in the backend's constructor, not the executor contract.

### `execute_structural_step()` is unchanged

Structural steps never need prompt assembly or backend-specific behavior. They remain deterministic across all backend types.

---

## 4. SKILL.md Integration Model

### How SKILL.md is used WITHOUT slash commands

SKILL.md files are **instruction payload**, not UI commands. The integration path is:

```
Workflow step (YAML)
  → step.agent_binding → AgentSpec
    → agent.skill_bindings → ["doc-truth-classification"]
      → skill_resolver.load_skill("doc-truth-classification", repo_root)
        → reads .claude/skills/doc-truth-classification/SKILL.md
          → returns raw markdown text
```

This text is then injected into the assembled prompt as the highest-priority instruction block.

### Skill resolution chain

1. **Step declares agent binding**: `step.raw["agent_binding"] = "doc-truth-agent"`
2. **Agent resolver maps to AgentSpec**: `spec.agents["doc-truth-agent"]` → `AgentSpec(skill_bindings=["doc-truth-classification"], ...)`
3. **Skill resolver loads SKILL.md**: `skill_resolver.load_skill("doc-truth-classification", repo_root)` → reads `.claude/skills/doc-truth-classification/SKILL.md` as raw text
4. **Prompt assembly concatenates**: skill content is placed at priority 1 (highest) in the bounded input list, meaning it is **never truncated**
5. **Assembled prompt contains**: skill instructions + agent instructions + upstream artifacts + document content
6. **Backend receives**: the complete assembled prompt as a single text string

### What SKILL.md content IS

- The full markdown text of the SKILL.md file, including frontmatter
- Instruction content that tells the LLM: "You are the X skill. Your job is to Y. You must produce Z."
- Deterministic input to the LLM — same SKILL.md content produces comparable outputs across runs
- The highest-priority content in the prompt — never truncated by input bounding

### What SKILL.md content is NOT

- NOT a slash command (`/doc-truth-classification` is not issued to the backend)
- NOT an interactive UI invocation
- NOT a reference to Claude Code's internal skill registry for runtime dispatch
- NOT consumed via the `Skill` tool or any MCP mechanism during DAG execution

> **SKILL.md is treated as executable instruction payload, not a UI command.**

### Skill content in PromptContext

`PromptContext.skill_content` contains the concatenated SKILL.md text for all skill bindings of the resolved agent. This field exists for traceability and diagnostics. The actual content is already embedded in `PromptContext.assembled_prompt`.

---

## 5. TAPM Integration Design (Critical Section)

### Question: Does TAPM belong in V2B or V2C?

### Analysis

| Dimension | ClaudeCodeCLIBackend (CLI) | ClaudeCodeTAPMBackend (TAPM) |
|-----------|---------------------------|------------------------------|
| **Determinism** | High — same prompt produces comparable output. No runtime tool variability. | Low — tool call sequences are non-deterministic. File contents may change between runs. Different reasoning paths possible. |
| **Throughput** | Single request-response. Predictable latency (~5-30s per step). | Multi-turn tool loop. Latency scales with tool call count (10s-120s+ per step). |
| **Governance control** | Strong — single enforcement boundary at assembly time. All file reads validated before dispatch. Prompt + response = complete audit record. | Weak without additional infrastructure. Requires runtime interceptor for every tool call. Must bound loop count. Must audit tool history. |
| **Failure surface** | 3 points: spawn, timeout, parse. | N+3 points: spawn, timeout, parse, plus every tool call. Each tool call can fail, return partial data, or trigger policy violation. |
| **Path bounding model** | Assembly-time gate. All reads happen in `prompt_assembly.py` under `PathPolicy`. Backend receives only text — no file access. | Runtime interception. Claude decides at execution time which files to read. Every tool call must be intercepted by a path policy enforcer. Fundamentally different enforcement model. |
| **Auditability** | Complete. `assembled_prompt` + `raw_output` = full execution record. | Partial. Must log entire tool-call conversation. Intermediate states add audit complexity. |
| **Context pressure** | High — all context must fit in one prompt. Token budget is critical. Input bounding truncates low-priority content. | Lower — Claude can lazily load context via tools. But initial prompt still needed for instructions. Does not eliminate input bounding — just changes what gets pre-loaded vs. lazily loaded. |
| **Implementation cost** | Low — subprocess spawn, capture stdout, parse response. ~200 lines. | High — tool policy enforcer, loop limiter, tool call logger, runtime path validator, conversation state manager. ~500-800 lines plus new test infrastructure. |

### Assessment

For the 12 governance skills in the current workflow:

1. **All skills have well-defined inputs.** The DAG declares which artifacts, documents, and upstream outputs each step consumes. There is no need for dynamic context discovery.
2. **Token budgets are sufficient.** The largest skill (e.g., `change-impact-audit`) consumes ~6 upstream artifacts + canonical docs. At 100K token budget, this fits comfortably in a single prompt with input bounding.
3. **Determinism matters.** Governance verdicts should be reproducible. Two runs of the same step with the same inputs should produce comparable outputs. TAPM introduces non-deterministic tool call sequences that reduce reproducibility.
4. **Path bounding is security-critical.** The governance system must not allow arbitrary file reads. CLI mode enforces this at a single well-defined point (assembly time). TAPM requires a fundamentally different enforcement model (runtime interception).

### Decision: TAPM is deferred to V2C.

**Rationale**: CLI mode satisfies all V2B requirements with dramatically lower implementation cost, smaller failure surface, stronger governance guarantees, and higher determinism. The prompt-size pressure concern is addressed by input bounding (already implemented). TAPM requires new infrastructure (runtime policy enforcer, tool call interceptor, loop limiter, conversation logger) that does not exist and is not needed for the 12 governance skills.

**V2C prerequisites for TAPM** (documented here, built later):

1. `ToolPolicy` dataclass — declares which tools are allowed per step
2. `ToolCallInterceptor` — validates every tool call against `PathPolicy` + `ToolPolicy`
3. `LoopLimiter` — bounds max tool calls and max wall time per step
4. `ConversationLogger` — records full tool-call conversation for auditability
5. `ClaudeCodeTAPMBackend` class implementing `ExecutionBackend`

### Contract implication

The `execute_step()` contract designed in §3 already accommodates TAPM:
- TAPM backend receives the same `PromptContext`
- TAPM backend returns the same `AgentExecutionResult`
- TAPM-specific configuration lives in the backend constructor, not the contract
- No executor changes needed when TAPM is added in V2C

---

## 6. Security Model Revision

### Path-bounded file access: CLI mode

In CLI mode, path bounding is **assembly-time enforcement**:

```
prompt_assembly.py
  → resolve_skill_content() → validate_path(skill_path, policy)
  → load_agent_file()       → validate_path(agent_path, policy)
  → read document content   → validate_path(doc_path, policy)
  → [all reads complete]
  → build_prompt_text()     → pure string concatenation, no file access
  → PromptContext built
  → passed to backend
  → backend sends TEXT only — no file access capability
```

The backend process itself has **zero file access**. It receives a text string on stdin and returns a text string on stdout. The subprocess is not given tools, file handles, or path access. Path bounding is enforced at a single point: before backend dispatch.

### Path-bounded file access: TAPM mode (V2C design, not built)

In TAPM mode, path bounding requires **runtime enforcement**:

```
prompt_assembly.py
  → same assembly-time validation as CLI mode
  → PromptContext built
  → passed to TAPM backend
  → TAPM backend creates tool-augmented session
  → Claude issues tool calls during execution:
    → Read("/path/to/file")
      → ToolCallInterceptor.validate(path, policy)  ← RUNTIME CHECK
      → if allowed: execute tool, return content
      → if denied: return PolicyViolation, log, continue or abort
    → Grep(pattern, path)
      → ToolCallInterceptor.validate(path, policy)  ← RUNTIME CHECK
      → ...
  → loop continues until: response complete OR max_tool_calls reached OR timeout
```

> **TAPM requires runtime enforcement, not just assembly-time enforcement.**

This is the strongest architectural argument for deferring TAPM. The runtime enforcement layer (ToolCallInterceptor + PathPolicy integration) does not exist and requires careful design to avoid introducing governance gaps.

### PathPolicy (V2B — assembly-time only)

```python
@dataclass(frozen=True)
class PathPolicy:
    allowed_roots: list[Path]        # e.g., [repo_root]
    allowed_patterns: list[str]      # e.g., [".claude/agents/*.md", ".claude/skills/*/SKILL.md"]
    denied_patterns: list[str]       # e.g., [".env", "*.key", "*.pem", "**/.git/**"]
    max_file_size_bytes: int = 1_048_576  # 1 MB
```

**Allowed paths** (V2B governance policy):
- `.claude/agents/<name>.md` — agent instruction files
- `.claude/skills/<name>/SKILL.md` — skill instruction files
- `*.md` in repo root — canonical documents
- `Documentation/*.md` — documentation files referenced by `agent.consumes`

**Denied paths** (always blocked):
- `.env`, `*.key`, `*.pem`, `*.secret` — credentials
- `.git/**` — git internals
- `**/__pycache__/**` — cache
- `node_modules/**`, `venv/**`, `.venv/**` — dependency dirs
- Any file outside `allowed_roots`

**Enforcement mechanism**: Every `Path.read_text()` call in `prompt_assembly.py` must route through `validate_path()` before reading. If validation fails, raise `PathPolicyViolation` which propagates as a step FAIL (fail-closed).

---

## 7. Phase Restructuring

### Implementation sequence

```
B1: Contract Reconciliation (PromptContext, signature)
  ↓
B2: Prompt Assembly + Input Bounding Integration
  ↓
B3: Path-Bounded File Access Enforcement
  ↓
B4: ClaudeCodeCLIBackend Implementation
  ↓
B5: Artifact Schema Validation
  ↓
B6: Verification and Acceptance Review
```

All phases target the CLI backend only. TAPM is deferred to V2C.

---


---

### Phase B0: Claude CLI Contract Verification (Pre-B1, Mandatory)

**Objective**: Validate and freeze the actual local Claude CLI subprocess contract before implementation.

**Tasks**:
1. Verify exact command syntax:
   - `claude -p --model <model>`
   - Confirm availability and behavior of `--output-format json`
2. Validate stdin behavior:
   - Confirm prompt is correctly read from stdin
3. Validate stdout behavior:
   - Confirm response format (JSON vs text)
4. Validate timeout behavior:
   - Confirm subprocess termination on timeout
5. Capture canonical example:
   - One sample request
   - One sample response
6. Document the frozen contract in this file

**Success criteria**:
- Subprocess command syntax confirmed
- Response format confirmed and documented
- One canonical request/response pair recorded

---

### Claude CLI Subprocess Contract (Frozen after B0)

**Status**: VERIFIED 2026-04-18

**Command**:
```
claude -p --output-format json --model <model> --no-session-persistence --tools ""
```

**Flags**:
- `-p` / `--print`: One-shot print mode. Non-interactive. Reads prompt, responds, exits.
- `--output-format json`: Returns a single JSON envelope on stdout (not raw text).
- `--model <model>`: Accepts alias (`sonnet`, `opus`, `haiku`) or full model ID.
- `--no-session-persistence`: Prevents session disk writes (subprocess hygiene).
- `--tools ""`: Disables all built-in tools (enforces one-shot, no tool loop).

**Input (stdin)**:
- Full assembled prompt text (plain text, UTF-8).

**Output (stdout)**:
- Single JSON object with the following structure:

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "result": "<response text from LLM>",
  "duration_ms": 4248,
  "duration_api_ms": 3670,
  "num_turns": 1,
  "stop_reason": "end_turn",
  "session_id": "<uuid>",
  "total_cost_usd": 0.0246865,
  "usage": {
    "input_tokens": 9,
    "output_tokens": 41,
    ...
  }
}
```

**Key response fields for backend parsing**:
- `result`: The LLM's response text. This is where artifact JSON will appear.
- `is_error`: `true` if the CLI itself errored (auth failure, etc.).
- `usage.output_tokens`: Token count for the response.
- `duration_api_ms`: API latency in milliseconds.
- `stop_reason`: `"end_turn"` for normal completion.

**Exit codes**:
- 0: Success (check `is_error` for logical errors).
- 1: CLI-level failure (auth, config, etc.).

**Canonical example** (verified 2026-04-18):
```
Input:  echo "Reply with exactly: hello" | claude -p --output-format json --model haiku --no-session-persistence --tools ""
Output: {"type":"result","result":"hello","is_error":false,...}
```

---

### Backend Output / Artifact JSON Protocol (Frozen)

The backend instructs the LLM (via prompt) to return a strict JSON structure within its `result` text:

```
{
  "artifacts": {
    "<artifact_name>": {
      "produced_by": "<step-name>",
      "data": { ... }
    }
  }
}
```

**Rules**:
- Exactly one top-level JSON object in the `result` text
- `artifacts` key is REQUIRED
- Each artifact MUST:
  - match a declared output
  - include `produced_by`
  - contain a `data` object
- No additional top-level keys unless explicitly allowed
- Any extra text outside JSON in `result` → PARSE FAILURE
- Missing expected artifacts → VALIDATION FAILURE

**Parsing strategy**:
1. Parse CLI JSON envelope from stdout → extract `result` field.
2. Parse `result` text as JSON → extract `artifacts` dict.
3. If step 1 fails → subprocess parse failure.
4. If `is_error` is true → runtime failure.
5. If step 2 fails → artifact parse failure (fail-closed).

---


### Phase B1: Contract Reconciliation

**Objective**: Add `PromptContext` type. Reconcile `ExecutionBackend.execute_step()` to accept prompt context. Preserve backward compatibility.

**Files affected**: `models.py`, `execution_backend.py`, `executor.py`

#### B1-A: Add `PromptContext` to `models.py`

Add a frozen dataclass:

```python
@dataclass(frozen=True)
class PromptContext:
    assembled_prompt: str
    agent: AgentSpec | None = None
    skill_content: str = ""
    agent_instructions: str = ""
    artifact_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_paths: list[str] = field(default_factory=list)
    token_budget: int = 100_000
    token_estimate: int = 0
    truncated: bool = False
    truncation_events: list[dict[str, str | int]] = field(default_factory=list)
```

#### B1-B: Update `ExecutionBackend.execute_step()` signature

In `execution_backend.py`:

1. Add `prompt_context: PromptContext | None = None` as the last parameter of `ExecutionBackend.execute_step()`.
2. Update `MockExecutionBackend.execute_step()` to accept the parameter and ignore it.
3. Update module docstring: replace "V2B adds ClaudeCLIBackend and NativeClaudeBackend" with "V2B adds ClaudeCodeCLIBackend."
4. `execute_structural_step()` is unchanged.

#### B1-C: Update executor call site

In `executor.py` `_execute_v2_step()`, update the call to `backend.execute_step()` to pass `prompt_context=None` explicitly (no behavioral change yet — prompt assembly integration happens in B2).

**Dependencies**: None. This is the first phase.

**Required behavior after remediation**:
- All existing tests pass unchanged.
- `MockExecutionBackend.execute_step()` accepts the new parameter and ignores it.
- No behavioral change to any execution mode.

**Required tests**:
- Test: `MockExecutionBackend.execute_step()` works with and without `prompt_context`.
- Test: `PromptContext` round-trips correctly (frozen dataclass, all fields).

**Success criteria**:
- All 313 V2A tests pass.
- New `PromptContext` type importable and usable.
- Contract updated without behavioral regression.

---

### Phase B2: Prompt Assembly + Input Bounding Integration

**Objective**: Wire `prompt_assembly.py` into the executor pipeline for V2 backend-dispatched steps. Build a `PromptContext` and pass it to `execute_step()`.

**Files affected**: `executor.py`, `prompt_assembly.py`

#### B2-A: Integrate prompt assembly into `_execute_v2_step()`

In `executor.py`, for non-dry-run, non-structural steps:

1. After agent resolution (line 346) and before `backend.execute_step()` (line 355), call `assemble_step_prompt()`.
2. Convert the returned dict to a `PromptContext`.
3. Build the `assembled_prompt` string by concatenating: skill_content + agent_instructions + serialized artifact inputs + document content. (This is the single text blob sent to the backend.)
4. Pass the `PromptContext` to `backend.execute_step()`.

For dry-run mode:
1. Still assemble the prompt (for diagnostics/trace).
2. Emit `prompt_assembled` trace event with token estimate and truncation info.
3. Do NOT invoke backend (existing behavior).

For structural steps: no prompt assembly (existing behavior).

For MockExecutionBackend: prompt_context is passed but ignored (existing behavior preserved).

#### B2-B: Build assembled prompt text

Add a function to `prompt_assembly.py`:

```python
def build_prompt_text(context: dict) -> str:
```

This function concatenates the assembled sections in priority order:
1. Skill instructions
2. Agent instructions
3. Upstream artifact payloads (serialized JSON)
4. Document content

Each section is separated by a clear delimiter for parseability.

#### B2-C: Emit prompt_assembled trace event

In `executor.py`, after prompt assembly completes, emit:

```python
_append_trace(run_state, node_name=step.name, event_type="prompt_assembled",
    detail={"token_estimate": ctx.token_estimate, "truncated": ctx.truncated})
```

#### B2-D: Emit input_bounded trace event

After bounding is applied (already happens inside `assemble_step_prompt` via `bound_inputs`), emit:

```python
_append_trace(run_state, node_name=step.name, event_type="input_bounded",
    detail={"budget": ctx.token_budget, "actual": ctx.token_estimate, "truncated": ctx.truncated,
            "truncation_events": ctx.truncation_events})
```

**Dependencies**: B1 (PromptContext type and signature exist).

**Required behavior after remediation**:
- V2 non-dry-run steps receive a `PromptContext` when dispatched to backend.
- Dry-run steps assemble prompt but do not invoke backend.
- V1 shell mode is unaffected.
- MockExecutionBackend still ignores prompt_context.
- `prompt_assembled` and `input_bounded` trace events appear in execution trace.

**Required tests**:
- Test: V2 execution with MockExecutionBackend produces `prompt_assembled` trace event.
- Test: V2 dry-run produces `prompt_assembled` trace event without backend invocation.
- Test: Assembled `PromptContext` contains skill_content, agent_instructions, artifact_inputs.
- Test: Truncation: assemble with a small token_budget, verify `truncated=True`.
- Test: V1 shell mode still produces no prompt_assembled events.
- Test: Structural steps produce no prompt_assembled events.

**Success criteria**:
- All V2A tests pass.
- Prompt assembly is part of the V2 execution pipeline.
- Trace events prove prompt assembly and bounding occur.

---

### Phase B3: Path-Bounded File Access Enforcement

**Objective**: Enforce that prompt assembly reads ONLY files within an explicitly allowed set of paths. Violations fail closed.

**Files affected**: `prompt_assembly.py`, new module `path_policy.py`

#### B3-A: Define path policy

Create `governance/dag_runner/path_policy.py`:

```python
@dataclass(frozen=True)
class PathPolicy:
    allowed_roots: list[Path]
    allowed_patterns: list[str]
    denied_patterns: list[str]
    max_file_size_bytes: int = 1_048_576  # 1 MB

class PathPolicyViolation(RuntimeError): ...

def validate_path(path: Path, policy: PathPolicy) -> None:
    """Raise PathPolicyViolation if path is not allowed."""

def default_governance_policy(repo_root: Path) -> PathPolicy:
    """Return the standard V2B path policy."""
```

#### B3-B: Integrate path policy into prompt assembly

In `prompt_assembly.py`:

1. Accept an optional `path_policy: PathPolicy | None` parameter in `assemble_step_prompt()`.
2. Before every file read (`load_agent_file`, `resolve_skill_content`, document reads), call `validate_path(path, policy)`.
3. If `path_policy is None` (V2A backward compat, mock usage), skip validation.
4. If `path_policy` is provided (V2B live backend), enforce strictly.

The executor passes `path_policy=default_governance_policy(repo_root)` when `backend` is a live backend, and `path_policy=None` for MockExecutionBackend and V1.

#### B3-C: Fail-closed violation handling

In `executor.py`, catch `PathPolicyViolation` during prompt assembly:

```python
except PathPolicyViolation as exc:
    # Record FAIL, emit trace event, apply halt-on-critical if applicable
```

Map to exit code 4 (artifact/security failure) via existing exit code infrastructure.

**Dependencies**: B2 (prompt assembly is wired into executor).

**Required behavior after remediation**:
- Prompt assembly for live backends validates every file read against path policy.
- Reads outside allowed paths raise `PathPolicyViolation` → step FAIL.
- Credential files (`.env`, `*.key`) are always blocked.
- Reads outside repo root are always blocked.
- MockExecutionBackend and V1 are unaffected (no path policy applied).
- Dry-run mode with live backend config applies path policy (validates even without executing).

**Required tests**:
- Test: allowed path (`.claude/agents/foo.md`) → passes validation.
- Test: denied path (`.env`) → `PathPolicyViolation`.
- Test: path outside repo root → `PathPolicyViolation`.
- Test: file exceeding max_file_size → `PathPolicyViolation`.
- Test: `path_policy=None` (mock/V1) → no validation.
- Test: path policy violation in executor → step FAIL, trace event.
- Test: default governance policy allows known agent and skill paths.

**Success criteria**:
- All V2A tests pass (path policy is None for mock).
- Live backend path would enforce policy.
- No file read in prompt assembly bypasses policy when policy is active.

---

### Phase B4: ClaudeCodeCLIBackend Implementation

**Objective**: Implement `ClaudeCodeCLIBackend` that sends assembled prompts to the local `claude` CLI subprocess and parses the response into `AgentExecutionResult`.

**Files affected**: `execution_backend.py`, `cli.py`

#### B4-A: Implement `ClaudeCodeCLIBackend`

Add to `execution_backend.py`:

```python
class ClaudeCodeCLIBackend(ExecutionBackend):
    """V2B live backend — dispatches to local claude CLI subprocess.

    Uses ``claude -p`` (one-shot print mode) with assembled prompt on stdin.
    No direct API calls, no external billing, and no repository-managed API dependency (uses local Claude Code runtime).
    """

    def __init__(
        self,
        model: str = "sonnet",
        timeout_ms: int = 120_000,
        claude_command: str = "claude",
    ) -> None: ...

    def execute_step(
        self,
        step: WorkflowStep,
        agent: AgentSpec,
        config: ExecutionConfig,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
        prompt_context: PromptContext | None = None,
    ) -> AgentExecutionResult: ...

    def execute_structural_step(self, ...) -> AgentExecutionResult: ...
```

**Execution flow**:

1. If `prompt_context is None`, fail closed (`AgentExecutionResult(success=False, failure=...)`).
2. Select model from `agent.model` (e.g., `"opus"`, `"sonnet"`).
3. Build subprocess command: `[claude_command, "-p", "--model", model, "--output-format", "json"]`.
4. Send `prompt_context.assembled_prompt` on stdin.
5. Set `timeout_ms` as subprocess timeout.
6. Parse stdout JSON for the response text.
7. Extract artifact payloads from the response using a deterministic extraction protocol (section delimiter parsing or structured JSON output).
8. On subprocess failure (nonzero exit, timeout, parse error): return `AgentExecutionResult(success=False, ...)`.
9. Measure `latency_ms` from wall clock. Extract `token_count` from response metadata if available.

**Key difference from prior plan**: The command uses `claude -p` (print/prompt mode), NOT `claude --print -` (the prior plan's syntax). The `-p` flag is Claude Code's one-shot prompt mode designed for non-interactive use.

**Structural steps**: `execute_structural_step()` delegates to the base `MockExecutionBackend` behavior (structural steps are deterministic, no LLM needed even in live mode).

#### B4-B: Response parsing

Add a response parser that extracts artifact payloads from Claude's text response:

```python
def _parse_backend_response(
    raw_output: str,
    expected_artifacts: list[str],
) -> dict[str, dict[str, Any]]:
```

The parser must:
- Look for artifact JSON blocks in the response (delimited by a known marker or extracted from structured output format).
- Return a dict mapping artifact names to their payload dicts.
- If expected artifacts are missing from the response, return them as absent (let artifact validation catch it).
- On parse failure, return empty dict (fail-closed: step will fail artifact validation).

#### B4-C: Wire ClaudeCodeCLIBackend into CLI

In `cli.py`, add a `--backend` flag:

```python
if exec_config.mode == "agent_execution":
    if args.backend == "claude_code_cli":
        from governance.dag_runner.execution_backend import ClaudeCodeCLIBackend
        backend = ClaudeCodeCLIBackend(timeout_ms=exec_config.timeout_per_step_ms)
    else:
        backend = MockExecutionBackend()
```

Default remains MockExecutionBackend. `--backend claude_code_cli` opts into live execution.

**Dependencies**: B1 (contract), B2 (prompt assembly wired), B3 (path policy enforced).

**Required behavior after remediation**:
- `--mode agent_execution --backend claude_code_cli` invokes local Claude CLI per step.
- Missing prompt_context → fail closed.
- Subprocess timeout → step FAIL with `FailureClassification(origin="timeout")`.
- Subprocess error → step FAIL with `FailureClassification(origin="runtime")`.
- `--mode agent_execution` (no `--backend`) → MockExecutionBackend (unchanged).
- V1, dry-run, graph modes unaffected.

**Required tests** (using mock subprocess, NOT real Claude):
- Test: ClaudeCodeCLIBackend with mocked subprocess returning valid JSON → `AgentExecutionResult(success=True)`.
- Test: ClaudeCodeCLIBackend with mocked subprocess timeout → `AgentExecutionResult(success=False, failure.origin="timeout")`.
- Test: ClaudeCodeCLIBackend with mocked subprocess error → `AgentExecutionResult(success=False, failure.origin="runtime")`.
- Test: ClaudeCodeCLIBackend with `prompt_context=None` → fail closed.
- Test: Response parsing extracts artifact payloads from known format.
- Test: Response parsing with malformed output → empty artifacts.
- Test: `execute_structural_step()` produces deterministic result (no subprocess).
- Test: CLI `--backend claude_code_cli` selects ClaudeCodeCLIBackend.

**Success criteria**:
- All V2A tests pass.
- ClaudeCodeCLIBackend passes all mocked-subprocess tests.
- Backend does NOT call real Claude in any automated test.

---

### Phase B5: Artifact Schema Validation

**Objective**: Validate backend-produced artifact payloads against declared artifact schemas before recording in run_state.

**Files affected**: `executor.py`, new module `artifact_schema.py`

#### B5-A: Define artifact schema validation

Create `governance/dag_runner/artifact_schema.py`:

```python
class ArtifactSchemaError(RuntimeError): ...

@dataclass(frozen=True)
class ArtifactSchemaViolation:
    artifact_name: str
    violation: str
    detail: dict[str, Any] = field(default_factory=dict)

def validate_artifact_output(
    artifact_name: str,
    payload: dict[str, Any],
    spec: AssembledWorkflowSpec,
) -> list[ArtifactSchemaViolation]:
```

**What is validated** (V2B scope):

1. **Required keys present**: Every backend-produced artifact must have a `produced_by` key matching the step that produced it.
2. **Type constraint**: Payload must be a non-empty dict.
3. **No forbidden keys**: Artifacts must not contain keys that conflict with the envelope schema (`artifact`, `session`, `timestamp` — these are envelope-level, not payload-level).
4. **Declared artifact match**: Artifact name must be in the step's declared `outputs`.

**What is NOT validated** (deferred):

- Field-level semantic validation
- Cross-artifact consistency
- Content correctness (LLM output quality)

#### B5-B: Integrate validation into executor

In `executor.py`, after `backend.execute_step()` returns and before recording artifacts in run_state:

1. For each artifact in `result.artifacts_produced`, call `validate_artifact_output()`.
2. If violations exist and backend is a live backend (not Mock): mark step as FAIL, emit `artifact_validated` trace event with violations.
3. If violations exist and backend is MockExecutionBackend: log warning but do not FAIL (mock produces controlled payloads).
4. Emit `artifact_validated` trace event (pass or fail).

**When validation applies**:

| Backend | Mode | Validation |
|---------|------|-----------|
| MockExecutionBackend | agent_execution | Warn only (mock output is trusted) |
| MockExecutionBackend | dry_run | Skip (no artifacts produced) |
| ClaudeCodeCLIBackend | agent_execution | Strict — FAIL on violation |
| V1 shell | any | Skip (no backend) |

#### B5-C: Map validation failures to exit codes

Artifact schema violations map to existing exit code 4 (`EXIT_ARTIFACT_FAILURE`). No new exit codes needed.

**Dependencies**: B4 (live backend exists and produces non-deterministic output).

**Required behavior after remediation**:
- Live backend artifacts are validated before recording.
- Schema violations → step FAIL (fail-closed).
- Mock backend artifacts are warn-only validated.
- `artifact_validated` trace event emitted.
- V1 and dry-run unaffected.

**Required tests**:
- Test: valid artifact payload → passes validation.
- Test: empty payload → violation.
- Test: payload with forbidden envelope keys → violation.
- Test: artifact name not in step outputs → violation.
- Test: validation failure with live backend → step FAIL.
- Test: validation failure with MockExecutionBackend → warn, step still PASS.
- Test: `artifact_validated` trace event emitted after validation.

**Success criteria**:
- All V2A tests pass.
- Live backend output is schema-validated before recording.
- Non-deterministic backend output that violates schema causes fail-closed step failure.

---

### Phase B6: Verification and Acceptance Review

**Objective**: Execute the full V2B verification protocol and produce an acceptance record.

**Files affected**: None (verification only).

#### B6-A: Full test suite execution

Run the complete test suite and verify:
- All V2A tests pass (313+ tests).
- All new V2B tests pass.
- No regressions.

#### B6-B: Manual verification commands

```bash
# V1 shell mode (unchanged — backwards compat)
python -m governance.dag_runner.cli --show-steps --write-state

# Dry-run mode (now includes prompt_assembled trace events)
python -m governance.dag_runner.cli --dry-run --json

# V2A mocked agent execution (unchanged)
python -m governance.dag_runner.cli --mode agent_execution --write-state --json

# V2B live backend with mocked subprocess (integration test)
python -m pytest tests/governance/test_claude_code_cli_backend.py -v

# Full test suite
python -m pytest tests/governance -q
```

#### B6-C: V2B acceptance criteria checklist

| # | Criterion | Evidence required |
|---|-----------|-------------------|
| 1 | All V2A tests pass (313+) | Test suite output |
| 2 | V1 shell mode unchanged | Text output comparison |
| 3 | Dry-run includes prompt_assembled trace events | JSON output inspection |
| 4 | MockExecutionBackend backward compatible | Existing mock tests pass |
| 5 | ClaudeCodeCLIBackend passes mocked-subprocess tests | Backend test suite |
| 6 | Prompt assembly wired into V2 execution pipeline | Trace event presence |
| 7 | Input bounding applied to assembled prompts | Token budget test |
| 8 | Path policy enforced for live backend | Policy violation tests |
| 9 | Artifact schema validation applied to live backend output | Schema violation tests |
| 10 | `ExecutionBackend.execute_step()` contract reconciled | Type checking, signature tests |
| 11 | Exit codes still correct | Exit code tests pass |

---

## 8. Test Strategy Update

### CLI backend tests (mocked subprocess)

| Test | Phase | File | Priority |
|------|-------|------|----------|
| Mocked subprocess returns valid JSON | B4 | `test_claude_code_cli_backend.py` (new) | P0 |
| Mocked subprocess timeout | B4 | `test_claude_code_cli_backend.py` | P0 |
| Mocked subprocess error (nonzero exit) | B4 | `test_claude_code_cli_backend.py` | P0 |
| prompt_context=None → fail closed | B4 | `test_claude_code_cli_backend.py` | P0 |
| Response parsing valid format | B4 | `test_claude_code_cli_backend.py` | P1 |
| Response parsing malformed → empty artifacts | B4 | `test_claude_code_cli_backend.py` | P1 |
| Subprocess command uses `claude -p` not API | B4 | `test_claude_code_cli_backend.py` | P0 |
| Model selection from agent.model | B4 | `test_claude_code_cli_backend.py` | P1 |

### Security enforcement tests

| Test | Phase | File | Priority |
|------|-------|------|----------|
| `.env` read blocked by path policy | B3 | `test_path_policy.py` | P0 |
| `*.key` / `*.pem` blocked | B3 | `test_path_policy.py` | P0 |
| Path outside repo root blocked | B3 | `test_path_policy.py` | P0 |
| File exceeding max_file_size blocked | B3 | `test_path_policy.py` | P1 |
| `.git/**` paths blocked | B3 | `test_path_policy.py` | P0 |
| Allowed skill path passes | B3 | `test_path_policy.py` | P0 |
| Allowed agent path passes | B3 | `test_path_policy.py` | P0 |
| Live backend without prompt → fail closed | B4 | `test_claude_code_cli_backend.py` | P0 |
| Artifact with forbidden envelope keys → fail closed | B5 | `test_artifact_schema.py` | P0 |

### Fail-closed behavior tests

| Test | Phase | File | Priority |
|------|-------|------|----------|
| Path policy violation → step FAIL | B3 | `test_executor_path_policy.py` (new) | P0 |
| Schema validation failure → step FAIL (live backend) | B5 | `test_executor_artifacts.py` (extend) | P0 |
| Schema validation warning (mock) → step PASS | B5 | `test_executor_artifacts.py` (extend) | P1 |
| Subprocess timeout → step FAIL | B4 | `test_claude_code_cli_backend.py` | P0 |
| Missing prompt_context → step FAIL | B4 | `test_claude_code_cli_backend.py` | P0 |

### Unit tests

| Test | Phase | File | Priority |
|------|-------|------|----------|
| `PromptContext` construction | B1 | `test_models.py` (extend) | P0 |
| `MockExecutionBackend.execute_step()` with prompt_context | B1 | `test_execution_backend.py` (extend) | P0 |
| `assemble_step_prompt()` returns all expected fields | B2 | `test_prompt_assembly.py` (extend) | P0 |
| `build_prompt_text()` concatenation order | B2 | `test_prompt_assembly.py` (extend) | P1 |
| `validate_path()` allowed path | B3 | `test_path_policy.py` (new) | P0 |
| `validate_path()` denied path | B3 | `test_path_policy.py` | P0 |
| `validate_artifact_output()` valid payload | B5 | `test_artifact_schema.py` (new) | P0 |
| `validate_artifact_output()` empty payload | B5 | `test_artifact_schema.py` | P0 |

### Integration tests

| Test | Phase | File | Priority |
|------|-------|------|----------|
| V2 execution emits prompt_assembled trace | B2 | `test_trace_events.py` (extend) | P0 |
| V2 dry-run emits prompt_assembled without backend | B2 | `test_trace_events.py` (extend) | P1 |
| Path policy violation → step FAIL in pipeline | B3 | `test_executor_path_policy.py` (new) | P0 |
| Schema validation failure → step FAIL in pipeline | B5 | `test_executor_artifacts.py` (extend) | P0 |

### CLI tests

| Test | Phase | File | Priority |
|------|-------|------|----------|
| `--backend claude_code_cli` selects ClaudeCodeCLIBackend | B4 | `test_cli_backend_selection.py` (new) | P0 |
| Default backend remains MockExecutionBackend | B4 | `test_cli_backend_selection.py` | P0 |

### Backward compatibility tests

| Expectation | Evidence |
|-------------|----------|
| V1 shell mode unchanged | All 204+ V1 tests pass |
| V2A dry-run unchanged | Existing dry-run tests pass |
| V2A mock agent_execution unchanged | Existing mock tests pass |
| MockExecutionBackend backward compatible | All existing backend tests pass |
| Exit codes unchanged | All exit code tests pass |
| Continuation unchanged | All continuation tests pass |

---

## 9. Live-Testing Gate Revision

### CLI backend readiness criteria

All of the following must be true before claiming V2B is integration-complete:

1. All V2A tests pass (313+).
2. All V2B tests pass.
3. ClaudeCodeCLIBackend passes all mocked-subprocess tests.
4. Prompt assembly is wired into executor with trace evidence.
5. Path policy enforcement tested and passing.
6. Artifact schema validation tested and passing.
7. V1 shell mode produces identical output.

### Controlled live-testing preconditions (CLI backend)

Controlled live testing (with real local Claude) MUST NOT proceed until ALL of the following are true:

1. **V2B integration-complete**: All mocked tests pass.
2. **Path policy active**: `default_governance_policy()` enforced for ClaudeCodeCLIBackend.
3. **Artifact validation active**: Schema validation enforced for ClaudeCodeCLIBackend.
4. **Claude CLI available**: `claude` command is installed locally and authenticated.
5. **Manual supervision**: First live runs must be manually supervised, not automated.
6. **Timeout enforced**: Per-step timeout configured (default 120s).
7. **Single-step testing first**: Test one step in isolation before full DAG execution.

### TAPM backend readiness criteria (V2C — not part of V2B)

The following are documented as V2C gate criteria, not V2B:

1. All V2B criteria remain satisfied.
2. `ToolPolicy` implemented and tested.
3. `ToolCallInterceptor` validates every tool call against PathPolicy + ToolPolicy.
4. `LoopLimiter` bounds max tool calls and max wall time per step.
5. `ConversationLogger` records full tool-call conversation.
6. All TAPM-specific tests pass.
7. Single-step TAPM testing completed under manual supervision.

### What "live-testing ready" means

- The runner can invoke real local Claude per step via `claude -p`.
- Each invocation has bounded prompt context and timeout.
- File reads are path-bounded at assembly time.
- Backend output is schema-validated.
- Failures are fail-closed.
- No API calls, no external billing, no direct Anthropic API client integration or repository-managed API billing path

### What "live-testing ready" does NOT mean

- NOT production-ready.
- NOT approved for unsupervised automated execution.
- NOT TAPM-enabled (deferred to V2C).
- NOT performance-benchmarked.
- NOT cost-optimized (no response caching).

---

## 10. Final Recommendation

### Which backend to implement FIRST

**ClaudeCodeCLIBackend** must be implemented first (and is the only backend in V2B).

**Rationale**:
- CLI mode is the minimum viable live backend with the smallest failure surface.
- It enforces path bounding at a single well-defined point (assembly time).
- It preserves auditability (one prompt, one response = complete record).
- It satisfies all 12 governance skill execution requirements.
- It requires no new runtime enforcement infrastructure.

### Whether TAPM is required now or deferred

**TAPM is deferred to V2C.**

**Rationale**:
- All governance skills have well-defined inputs discoverable at assembly time.
- Token budgets are sufficient for pre-assembled context.
- TAPM requires runtime enforcement infrastructure that does not exist (ToolCallInterceptor, LoopLimiter, ConversationLogger).
- TAPM reduces determinism and increases failure surface without providing governance value for the current 12-skill workflow.
- The `execute_step()` contract is designed to accommodate TAPM without changes — adding it later is safe.

### Implementation order

```
B1: Contract Reconciliation (PromptContext, signature)         ~30 lines, 2-3 tests
  ↓
B2: Prompt Assembly + Input Bounding Integration               ~80 lines, 6-8 tests
  ↓
B3: Path-Bounded File Access Enforcement                      ~120 lines, 8-10 tests
  ↓
B4: ClaudeCodeCLIBackend Implementation                       ~200 lines, 8-10 tests
  ↓
B5: Artifact Schema Validation                                 ~80 lines, 7-8 tests
  ↓
B6: Verification and Acceptance Review                           0 lines, 0 new tests
```

**Total**: ~510 new/changed lines, ~31-39 new tests.

---

## Decision Summary

1. **Corrected backend model**: `NativeClaudeBackend` (API-based) is removed entirely. The backend taxonomy is `ClaudeCodeCLIBackend` (V2B, one-shot local CLI) and `ClaudeCodeTAPMBackend` (V2C, tool-augmented local runtime). Both are local-only, zero API dependency.

2. **CLI backend role**: `ClaudeCodeCLIBackend` is the sole V2B live backend. It spawns `claude -p` as a subprocess with the fully assembled prompt on stdin and parses the JSON response from stdout. Single request-response cycle, deterministic, fail-closed, fully auditable.

3. **TAPM backend role**: `ClaudeCodeTAPMBackend` is deferred to V2C. It would allow controlled tool usage during execution for steps requiring dynamic context discovery. Not needed for the 12 governance skills, which have well-defined inputs. The `execute_step()` contract is forward-compatible — no signature changes needed when TAPM is added.

4. **SKILL.md usage model**: SKILL.md files are loaded from disk as raw markdown text by `skill_resolver.py` and injected into the assembled prompt as the highest-priority instruction block (never truncated). They are **instruction payload**, not slash commands. No `/skill-name` invocation occurs. No interactive UI mechanism is used. The LLM receives the full SKILL.md text as part of its prompt and follows the instructions.

5. **Security enforcement strategy**: Path bounding is enforced at assembly time via `PathPolicy` + `validate_path()` in `prompt_assembly.py`. The CLI backend has zero file access — it receives text and returns text. TAPM (V2C) will require runtime enforcement via `ToolCallInterceptor`, which is a fundamentally different enforcement model and the primary reason for deferral.

6. **Recommended implementation order**: B1 (contract) → B2 (prompt assembly) → B3 (path policy) → B4 (CLI backend) → B5 (artifact validation) → B6 (verification). B1 first because all phases depend on `PromptContext`. B3 before B4 because path bounding is a security prerequisite for live backends. Total scope: ~510 lines, ~35 tests.

---

## V2B Acceptance Contract

### Must-fix items (blocking V2B completion claim)

| ID | Item | Rationale |
|----|------|-----------|
| MF-B1 | `ExecutionBackend.execute_step()` accepts assembled prompt context | Required for any real backend to receive meaningful input. |
| MF-B2 | `prompt_assembly.py` wired into executor for V2 backend-dispatched steps | No prompt assembly = backend receives no context. |
| MF-B3 | Input bounding applied before prompt delivery to backend | Unbounded prompts risk context overflow and non-deterministic truncation. |
| MF-B4 | Path-bounded file access enforcement for prompt assembly reads | Security: live backends must not read arbitrary files during prompt assembly. |
| MF-B5 | `ClaudeCodeCLIBackend` implemented and tested with mock Claude subprocess | Must exist for controlled live testing to proceed. |
| MF-B6 | Artifact schema validation applied to backend-produced outputs | Non-deterministic backend output must be validated before recording. |
| MF-B7 | All V2A tests still pass (313 tests, zero regressions) | V2B must not break V2A. |

### Allowable deferrals beyond V2B

| ID | Item | Rationale |
|----|------|-----------|
| DF-B1 | `ClaudeCodeTAPMBackend` (tool-augmented prompt mode) | Requires runtime enforcement infrastructure. CLI backend is sufficient for all 12 governance skills. §5 analysis concludes: deferred. |
| DF-B2 | Subagent orchestration / escalation dispatch | Out of V2B scope. No subagent runtime exists. |
| DF-B3 | Semantic output validation (beyond schema) | V2B validates artifact schema. Semantic correctness is future work. |
| DF-B4 | Multi-backend runtime selection | One backend per run. CLI flag to select backend is deferred. |
| DF-B5 | `--phase` scoped execution | Deferred since V2A. Not a V2B concern. |
| DF-B6 | Remaining trace event types | V2B adds 3 events. Full coverage remains deferred. |
| DF-B7 | Parallel step execution | DAG supports it but executor is serial. |
| DF-B8 | Retry / recovery for failed live steps | Steps fail closed. No retry in V2B. |
| DF-B9 | Response caching | No caching. Each invocation is fresh. |

### Non-negotiable compatibility constraints

1. **V1 shell mode preservation**: All V1 tests must pass unchanged. `backend=None` path produces identical output.
2. **V2A dry-run preservation**: `--dry-run` must continue to work with MockExecutionBackend.
3. **No YAML modification**: Workflow packages remain the spec.
4. **Fail-closed principle**: Every new integration point must default to blocking/erroring, never silently continuing.
5. **Hook envelope compatibility**: Artifact envelopes must match `artifact_store.py` format exactly.
6. **MockExecutionBackend backward compatibility**: Existing mock tests must continue to work. Mock backend ignores prompt context.
7. **Zero API dependency**: No `anthropic` SDK, no API key, no network calls to Anthropic endpoints.

---

## Critical File Remediation Matrix

| File | V2B Concern | Remediation Action | Phase | Required Tests |
|------|-------------|-------------------|-------|----------------|
| `models.py` | No `PromptContext` type | Add `PromptContext` frozen dataclass | B1-A | Type construction test |
| `execution_backend.py` | `execute_step()` lacks prompt_context; docstring references invalid NativeClaudeBackend | Add `prompt_context: PromptContext \| None = None` param. Fix docstring. Implement `ClaudeCodeCLIBackend`. | B1-B, B4-A | Signature compat test, mocked-subprocess tests |
| `executor.py` | No prompt assembly in pipeline, no artifact schema validation | Wire `assemble_step_prompt()` before backend dispatch. Validate backend output. | B2-A, B5-B | prompt_assembled trace, schema validation fail test |
| `prompt_assembly.py` | No path policy enforcement, returns dict not `PromptContext` | Accept `path_policy` param. Validate reads. Add `build_prompt_text()`. | B2-B, B3-B | Path violation test, prompt text assembly test |
| `path_policy.py` (new) | Does not exist | Create: PathPolicy, validate_path, default_governance_policy | B3-A | Allowed/denied path tests |
| `artifact_schema.py` (new) | Does not exist | Create: validate_artifact_output, ArtifactSchemaViolation | B5-A | Valid/invalid payload tests |
| `cli.py` | No `--backend` flag, no live backend wiring | Add `--backend` arg, wire ClaudeCodeCLIBackend | B4-C | CLI arg parsing, backend selection test |
