# Governance DAG Runner

Orchestration engine for the Mr. Ripley governance workflow.
Executes a 5-layer governance DAG using pluggable backends (mock or live Claude CLI).

---

## Quick Start

```bash
# Ensure you are at the repo root (C:\Code\Mr-Ripley)
cd C:\Code\Mr-Ripley

# 1. Inspect the DAG structure (no execution)
python -m governance.dag_runner.cli --graph --json

# 2. Dry run — walk all steps, evaluate predicates, assemble prompts, produce no artifacts
python -m governance.dag_runner.cli --dry-run --json

# 3. Mock execution — deterministic placeholder artifacts, full pipeline
python -m governance.dag_runner.cli --mode agent_execution --write-state --json

# 4. Live execution — real Claude CLI invocations per step (requires local `claude` auth)
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --write-state --json
```

---

## CLI Reference

```
python -m governance.dag_runner.cli [OPTIONS]
```

### Core Flags

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--mode` | `shell_v1`, `agent_execution` | `shell_v1` | Execution mode |
| `--backend` | `mock`, `claude_code_cli` | `mock` | Execution backend (only applies to `agent_execution`) |
| `--dry-run` | — | off | Walk plan, assemble prompts, skip backend invocation |
| `--graph` | — | off | Emit DAG structure as JSON, then exit |
| `--json` | — | off | Machine-readable JSON output |
| `--show-steps` | — | off | Print ordered step list (text mode) |
| `--write-state` | — | off | Persist `governance_run_state.json` after execution |

### Continuation & Timeout

| Flag | Description |
|------|-------------|
| `--continue-from <step-id>` | Resume from a specific step (requires prior `--write-state`) |
| `--timeout <ms>` | Total run timeout in milliseconds |
| `--state-path <path>` | Custom path for persisted run state (default: `governance_run_state.json`) |
| `--phase <A-E>` | Execute only steps in a given layer (accepted but not yet functional) |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All steps passed, verdict = ready |
| 1 | Structural failure (loader, assembler, validator, drift) |
| 2 | Contract failure (halt-on-critical blocking condition) |
| 3 | Runtime failure (backend invocation error) |
| 4 | Artifact failure (write or schema validation) |
| 5 | Timeout exceeded |
| 10 | Verdict = review_only |
| 11 | Verdict = blocked |

---

## Execution Modes

### V1 Shell Mode (`--mode shell_v1`, default)

Walks the execution plan, evaluates predicates, materializes placeholder artifacts.
No agent or skill invocation. No backend needed.
Useful for verifying DAG structure and predicate logic.

```bash
python -m governance.dag_runner.cli --show-steps --write-state
```

### Mock Execution (`--mode agent_execution`)

Uses `MockExecutionBackend` to produce deterministic artifact payloads.
Every step gets a `{"produced_by": "<step-name>"}` artifact.
Full pipeline runs: predicates, prompt assembly, artifact writing, trace events.

```bash
python -m governance.dag_runner.cli --mode agent_execution --write-state --json
```

### Live Execution (`--mode agent_execution --backend claude_code_cli`)

Spawns a real `claude -p` subprocess per step with the assembled prompt on stdin.
Each step's SKILL.md instructions, agent context, upstream artifacts, and document
content are assembled into a single prompt and sent to the local Claude CLI.

```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --write-state --json
```

**Live execution requirements:**
- `claude` CLI installed and authenticated locally (`claude --version` to verify)
- Per-step timeout: 120s default (configurable via `--timeout`)
- Path-bounded file access enforced at prompt assembly time
- Artifact schema validation enforced on backend output
- All failures are fail-closed (no silent continuation)

**What happens per step:**
1. Predicates evaluated (condition/skip_if)
2. Agent resolved from workflow step binding
3. SKILL.md loaded from `.claude/skills/<name>/SKILL.md`
4. Upstream artifact payloads gathered from run state
5. Prompt assembled and token-bounded (100K budget)
6. Path policy validated (no credentials, no .git, repo-root only)
7. `claude -p --output-format json --model <model> --no-session-persistence --tools ""` invoked
8. Response parsed: CLI envelope -> result text -> artifact JSON
9. Artifact schema validated (produced_by, no envelope keys, declared outputs)
10. Artifacts written to `.claude/run/artifacts/<name>.json`

---

## Architecture

### Five-Layer Governance DAG

```
LAYER A: Semantic Normalization
  load-context ─────> classify-claims ──> normalize-terminology ──> route-claims-by-role
  (constitution)      (claim-classification)  (terminology-map)       (role-citation)

LAYER B: Architecture + Phase + Contract Gating
  phase-check ──────> snapshot-contract-check ──> stage-gate-enforcement
  (build-sequence)    (snapshot-contract)          (stage_gates)

LAYER C: Runtime / Schema / Boundary Integrity
  runtime-boundary-check ──> adapter-schema-check ──> runtime-guards-summary
  (snapshot-boundary)        (adapter-schema)          (hooks synthesis)

LAYER D: Audit + Impact
  deep-audit ──> change-impact-audit ──> rename-invariance-check ──> doc-code-sync-check
  (subagents)    (change-impact)          (conditional)                (doc-code-sync)

LAYER E: Verification + Hygiene + Release
  update-verification-matrix ──> update-verification-ledger ──> artifact-hygiene ──> pre-pr-gate
  (matrix-update)                (ledger-update)                 (hygiene-check)      (hooks gate)
```

### Agents, Skills, and Steps

Each workflow step binds to one **agent** (execution context) which binds to one **skill**
(behavioral instruction set). The relationship is 1:1:1.

| Workflow Step | Agent | Skill | Artifact(s) Produced |
|---------------|-------|-------|---------------------|
| classify-claims | claim-classification-agent | doc-truth-classification | claim_classification_map |
| normalize-terminology | terminology-normalization-agent | canonical-terminology-map | normalized_terminology_map |
| route-claims-by-role | role-citation-agent | role-matched-citation-check | role_citation_verdict |
| phase-check | build-sequence-agent | build-sequence-compliance-check | phase_alignment_status |
| snapshot-contract-check | snapshot-contract-agent | snapshot-contract-check | contract_compliance_verdict |
| runtime-boundary-check | runtime-boundary-agent | snapshot-boundary-check | runtime_boundary_verdict |
| adapter-schema-check | adapter-schema-agent | adapter-schema-review | adapter_schema_verdict |
| deep-audit | audit-coordinator-agent | *(dispatcher)* | audit_summary |
| change-impact-audit | change-impact-agent | change-impact-audit | change_impact_report, doc_update_plan |
| rename-invariance-check | rename-invariance-agent | rename-invariance-check | invariance_verdict |
| doc-code-sync-check | doc-code-sync-agent | doc-code-sync-rules | doc_code_sync_status |
| update-verification-matrix | verification-matrix-agent | verification-matrix-update-method | verification_matrix_delta |
| update-verification-ledger | verification-ledger-agent | verification-ledger-update | verification_ledger_delta |
| runtime-artifact-hygiene-check | artifact-hygiene-agent | runtime-artifact-hygiene-check | artifact_hygiene_verdict |
| pre-pr-governance-readiness | *(hook gate)* | *(hook synthesis)* | pr_readiness_verdict |

### Where Things Live

```
.claude/
  workflows/
    system-orchestration.yaml          # Root workflow manifest (v4.1.0)
    packages/                          # 14 YAML packages merged into spec
      workflow-steps.yaml              #   20 step definitions (the DAG)
      agents.yaml                      #   14 agent definitions
      skills.yaml                      #   13 skill declarations
      hooks.yaml                       #   6 runtime guard definitions
      subagents.yaml                   #   7 escalation-only audit specialists
      artifacts.yaml                   #   22 artifact definitions
      blocking-conditions.yaml         #   13 blocking condition definitions
      stage-gates.yaml                 #   4 phase gate definitions
      predicates.yaml                  #   6 scope predicates
      constitution.yaml                #   Reference to CLAUDE.md
      interpretation-policy.yaml       #   Claim routing table
      verification-ledger.yaml         #   Ledger update rules
      execution-metadata.yaml          #   Exit codes, backend models
      manifest.yaml                    #   Workflow identity
  agents/                              # Agent instruction .md files
    claim-classification-agent.md
    terminology-normalization-agent.md
    ...
  skills/                              # Skill instruction SKILL.md files
    doc-truth-classification/SKILL.md
    canonical-terminology-map/SKILL.md
    ...
  hooks/                               # Hook enforcement scripts
    pre_pr_governance_gate.py          #   PreToolUse: blocks git commit/push
    snapshot_boundary_guard.py         #   PostToolUse: blocks boundary violations
    adapter_schema_guard.py            #   PostToolUse: blocks registry violations
    live_readiness_claim_blocker.py    #   PostToolUse: blocks live-readiness claims
    role_matched_doc_guard.py          #   Stop: warns on role-mismatched citations
    doc_code_sync_guard.py             #   Stop: warns on doc/code drift
    lib/artifact_store.py              #   Shared artifact read/write utilities
  settings.json                        # Hook wiring (PreToolUse, PostToolUse, Stop)
  run/artifacts/                       # Produced governance artifacts (JSON envelopes)

governance/dag_runner/                 # DAG runner engine (this directory)
  cli.py                               # CLI entry point
  executor.py                          # DAG execution engine
  execution_backend.py                 # Backend interface + implementations
  prompt_assembly.py                   # Prompt assembly + input bounding
  path_policy.py                       # Path-bounded file access enforcement
  artifact_schema.py                   # Artifact schema validation
  models.py                            # All data models (PromptContext, etc.)
  assembler.py                         # Workflow spec assembly
  planner.py                           # Topological sort / execution plan
  validator.py                         # Workflow spec validation
  loader.py                            # YAML package loader
  predicates.py                        # Predicate evaluation engine
  agent_resolver.py                    # Agent binding resolution
  skill_resolver.py                    # SKILL.md file loader
  input_bounding.py                    # Token budget enforcement
  drift_detector.py                    # Canonical document drift detection
  blockers.py                          # Blocking condition analysis
  verdict.py                           # Final verdict computation
  diagnostics.py                       # Latency/bottleneck diagnostics
  state_store.py                       # Run state persistence
  artifact_writer.py                   # Artifact envelope writer
  artifacts.py                         # Artifact existence queries
  hook_bridge.py                       # Hook signal integration
  execution_modes.py                   # Execution config builder
```

---

## Hooks

Hooks are wired in `.claude/settings.json` and fire automatically during Claude Code sessions.
They read governance artifacts from `.claude/run/artifacts/` and enforce constraints.

| Hook | Trigger | What It Does |
|------|---------|-------------|
| `pre_pr_governance_gate.py` | PreToolUse (Bash) | Blocks `git commit`/`git push` unless all governance artifacts are present and `pr_readiness_verdict` passes |
| `snapshot_boundary_guard.py` | PostToolUse (Edit/Write) | Blocks edits that violate snapshot boundary (raw observation access, Layer-2 coupling) |
| `adapter_schema_guard.py` | PostToolUse (Edit/Write) | Blocks edits that violate registry-driven adapter discipline |
| `live_readiness_claim_blocker.py` | PostToolUse (Edit/Write) | Blocks edits that claim live-readiness or execution capability before Phase D |
| `role_matched_doc_guard.py` | Stop | Warns when citations use wrong canonical document for claim type |
| `doc_code_sync_guard.py` | Stop | Warns when doc/code drift is detected |

**Hook execution flow:**
1. Claude Code fires the hook event (PreToolUse/PostToolUse/Stop)
2. Hook script reads the relevant governance artifact from `.claude/run/artifacts/`
3. Hook checks specific fields in the artifact data
4. If check fails: exit 2 (block) or print warning (warn)
5. If check passes: exit 0 (allow)

**Important:** Hooks depend on governance artifacts being present. Run the DAG first
to produce artifacts, then hooks enforce them during subsequent editing.

---

## Artifacts

All governance artifacts are written to `.claude/run/artifacts/` as JSON envelopes:

```json
{
  "artifact": "<artifact_name>",
  "produced_by": "<step_name>",
  "session": "<run_id>",
  "timestamp": "<ISO-8601>",
  "data": { ... }
}
```

### Always-Required Artifacts (14)

These must be present for the pre-PR governance gate to pass:

- `governance_context` — Constitutional context from CLAUDE.md
- `claim_classification_map` — Claim type classification
- `normalized_terminology_map` — Terminology normalization verdicts
- `role_citation_verdict` — Role-matched citation check
- `phase_alignment_status` — Build sequence compliance
- `contract_compliance_verdict` — Snapshot contract validation
- `stage_gate_report` — Phase gate enforcement results
- `guard_report` — Consolidated runtime guard summary
- `audit_summary` — Deep audit findings
- `change_impact_report` — Change impact assessment
- `doc_code_sync_status` — Doc/code alignment check
- `verification_ledger_delta` — Ledger tracking updates
- `artifact_hygiene_verdict` — Workspace hygiene check
- `pr_readiness_verdict` — Final release gate verdict

### Conditional Artifacts

| Artifact | Required When |
|----------|-------------|
| `runtime_boundary_verdict` | Files under `layer2/` are staged |
| `adapter_schema_verdict` | Files under `layer2/adapters/` or `layer2/config/` are staged |
| `doc_update_plan` | Canonical documents are staged |
| `invariance_verdict` | All staged changes are renames only |
| `verification_matrix_delta` | `DOCUMENTATION_VERIFICATION_MATRIX` file is staged |

---

## Use Case: Terminology Rename

Renaming terms across canonical documentation (e.g., "Layer 2" -> "truth_store",
"Layer 3" -> "decision_layer") is a **contract-affecting change** that triggers
several governance steps.

### Relevant Steps for a Terminology Rename

| Step | Why It Matters |
|------|---------------|
| **normalize-terminology** | Detects that "Layer 2" and "Layer 3" are project-governed terms. Flags the rename as a governance-sensitive terminology change. Produces a normalization map showing old -> new term mappings. |
| **classify-claims** | Classifies every claim in the affected documents. Verifies that renaming doesn't accidentally reclassify a current-state claim as target-state or vice versa. |
| **route-claims-by-role** | Checks that citations still point to the role-correct canonical document after the rename. `README_LAYER2.md` is itself a rename candidate (the filename contains "LAYER2"). |
| **phase-check** | Validates the rename doesn't introduce forbidden scope for the current phase. |
| **change-impact-audit** | Produces the `change_impact_report` with `change_type` (likely `rename_only` or `terminology_update`). Identifies all canonical documents requiring review per CLAUDE.md section 11. Produces `doc_update_plan`. |
| **rename-invariance-check** | If `change_type == "rename_only"`: verifies semantic equivalence is preserved. No claims added, removed, or reclassified. No evidence mappings broken. |
| **doc-code-sync-check** | Verifies that code references to "layer2" (Python module names, import paths, database names) are still aligned with documentation after the terminology change. |
| **update-verification-matrix** | Updates the verification matrix classifications if the rename affects verification posture. |
| **pre-pr-governance-readiness** | Final gate: all artifacts present, no blocking conditions unresolved, alias map present for renames. |

### Recommended Execution Sequence

**Step 1: Inspect the DAG (no execution)**

```bash
python -m governance.dag_runner.cli --graph --json > dag_structure.json
```

Review the step dependencies and confirm which steps will execute.

**Step 2: Dry run to verify prompt assembly**

```bash
python -m governance.dag_runner.cli --dry-run --json
```

Confirms all 18 steps can be walked, predicates evaluated, and prompts assembled
without errors. Check trace events for `prompt_assembled` entries.

**Step 3: Mock execution to verify artifact flow**

```bash
python -m governance.dag_runner.cli --mode agent_execution --write-state --json
```

Produces deterministic placeholder artifacts. Verifies the full pipeline including
artifact writing, predicate evaluation, and halt-on-critical logic.

**Step 4: Live execution with Claude CLI**

```bash
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --write-state --json
```

Each step invokes real Claude with assembled SKILL.md instructions + context.
Claude produces structured artifact JSON per step.

**Step 5: Review artifacts**

```bash
# Check all produced artifacts
ls .claude/run/artifacts/*.json

# Inspect a specific artifact (e.g., terminology normalization)
python -c "import json; print(json.dumps(json.load(open('.claude/run/artifacts/normalized_terminology_map.json')), indent=2))"

# Inspect change impact report
python -c "import json; print(json.dumps(json.load(open('.claude/run/artifacts/change_impact_report.json')), indent=2))"
```

**Step 6: Make the terminology changes in documentation**

After reviewing the governance artifacts, apply the rename across files.
The hooks in `.claude/settings.json` will enforce governance constraints
during editing (snapshot boundary, adapter schema, doc/code sync).

**Step 7: Re-run governance and commit**

```bash
# Re-run governance after edits
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --write-state --json

# Commit (pre-pr-governance-gate hook will validate all artifacts)
git add Documentation/ CLAUDE.md
git commit -m "docs: rename Layer 2 -> truth_store, Layer 3 -> decision_layer"
```

The `pre-pr-governance-gate` hook fires on `git commit` and validates:
- All 14 always-required artifacts are present
- `doc_update_plan` artifact is present (canonical docs are staged)
- `pr_readiness_verdict` passes all field checks
- No unresolved blocking conditions remain

### Scope of the Rename (312 occurrences + 13 in CLAUDE.md)

| File | Occurrences |
|------|------------|
| `Documentation/README_LAYER2.md` | 106 |
| `Documentation/README_v1.md` | 48 |
| `Documentation/SYSTEM_TECHNICAL_HANDBOOK_v1.md` | 47 |
| `Documentation/SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | 37 |
| `Documentation/SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | 29 |
| `Documentation/DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | 27 |
| `Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md` | 18 |
| `CLAUDE.md` | 13 |

**Governance considerations for this rename:**
- "Layer 2" and "Layer 3" are **canonical project-defined terms** tracked by the
  `canonical-terminology-map` skill. Renaming them triggers terminology normalization.
- `README_LAYER2.md` contains "LAYER2" in its filename. The rename may require a
  file rename, which triggers the `rename-invariance-check` step.
- CLAUDE.md section 2 defines the document authority hierarchy referencing "Layer-2"
  and "Layer-3". Updating CLAUDE.md is a constitutional change requiring all downstream
  documents to remain consistent.
- Code modules (`layer2/`) use `layer2` in import paths. The doc rename must not
  break doc/code alignment — the `doc-code-sync-check` step validates this.
- The `change-impact-audit` step (using opus model) will determine whether the rename
  is `contract_affecting` and produce the `doc_update_plan` listing all files that
  must be updated per CLAUDE.md section 11.

---

## Continuation

If execution fails mid-run, resume from the failed step:

```bash
# First run writes state
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --write-state --json

# Resume from a specific step
python -m governance.dag_runner.cli --mode agent_execution --backend claude_code_cli --write-state --json \
  --continue-from change-impact-audit
```

Continuation carries forward all prior artifacts and node results.

---

## Diagnostics

The `--json` output includes a `diagnostics` section:

```json
{
  "diagnostics": {
    "total_latency_ms": 45000,
    "total_tokens": 12500,
    "bottleneck_step": "change-impact-audit",
    "bottleneck_latency_ms": 15000,
    "critical_path": ["load-context", "classify-claims", "..."],
    "failed_steps": 0
  }
}
```

---

## Testing

```bash
# Full test suite (404 tests)
python -m pytest tests/governance -q

# Backend-specific tests
python -m pytest tests/governance/test_claude_code_cli_backend.py -v

# Run a specific test class
python -m pytest tests/governance/test_claude_code_cli_backend.py::TestSubprocessCommand -v
```
