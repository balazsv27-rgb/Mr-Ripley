# Hook Implementation Plan

## Overview

This document describes the implementation plan for the six governance hooks defined in `hooks.yaml`. Hooks are the runtime enforcement mechanism for the constitutional rules declared in `CLAUDE.md` (Section 15). They are not advisory — they are the execution boundary between allowed and disallowed actions.

**Authority chain:**
- `CLAUDE.md` declares obligations
- `system-orchestration.yaml` specifies the workflow
- `hooks.yaml` defines hook logic
- Claude Code `settings.json` binds hooks to execution events

---

## Hook Trigger Mapping

Claude Code supports three hook event types that map to the triggers declared in `hooks.yaml`:

| `hooks.yaml` trigger | Claude Code event     | Fires when                                |
|----------------------|-----------------------|-------------------------------------------|
| `PreToolUse`         | `PreToolUse`          | Before a tool call executes               |
| `PostToolUse`        | `PostToolUse`         | After a tool call completes               |
| `SubagentStop`       | `Stop`                | When a subagent or the main agent stops   |

---

## Hook Definitions and Implementation

### 1. `role-matched-doc-guard`

**Trigger:** `SubagentStop`
**Layer:** A — Semantic Normalization
**Action:** `warn_or_block`

**Purpose:** Prevents role-mismatched document citations — e.g. using `README_LAYER2.md` to override implementation-state claims that belong to `SYSTEM_IMPLEMENTATION_RECORD_v1.md`.

**Artifact consumed:** `role_citation_verdict`

**Checks:**
- `role_citation_verdict.violations` must not contain `role_mismatch`
- `role_citation_verdict.violations` must not contain `readme_layer2_override`

**Implementation steps:**
1. After every subagent stop, run a validator script that reads the `role_citation_verdict` artifact from the session artifact store.
2. If either violation flag is present, emit a structured warning message and surface the specific citation that triggered the violation.
3. On `warn_or_block`: warn unless the violation is attached to a strong claim (Section 10 of CLAUDE.md), in which case block.

**Settings binding:**
```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "python .claude/hooks/role_matched_doc_guard.py" }]
      }
    ]
  }
}
```

---

### 2. `snapshot-boundary-guard`

**Trigger:** `PostToolUse`
**Matcher:** `Edit|Write`
**Layer:** C — Runtime Schema Integrity
**Action:** `block_on_match`

**Purpose:** Blocks any code change that introduces raw observation access, misuse of `latest` snapshot references, or Layer-2 storage coupling downstream.

**Artifact consumed:** `runtime_boundary_verdict`

**Checks (all must be `false`):**
- `raw_observation_access_detected`
- `latest_snapshot_misuse_detected`
- `layer2_storage_coupling_detected`

**Implementation steps:**
1. After every `Edit` or `Write` tool call, scan the written content and the affected file for forbidden patterns (direct DB observation reads, unversioned snapshot references, Layer-2 table coupling).
2. Populate `runtime_boundary_verdict` with results.
3. If any flag is `true`, raise `snapshot_boundary_violation` and halt further processing.

**Forbidden patterns to detect:**
- Direct reads from `observations` table without snapshot mediation
- References to `snapshot_id = 'latest'` or equivalent
- Imports or queries that bypass the snapshot boundary

**Settings binding:**
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{ "type": "command", "command": "python .claude/hooks/snapshot_boundary_guard.py" }]
      }
    ]
  }
}
```

---

### 3. `adapter-schema-guard`

**Trigger:** `PostToolUse`
**Matcher:** `Edit|Write`
**Layer:** C — Runtime Schema Integrity
**Action:** `warn_or_block`

**Purpose:** Enforces that all adapter logic is registry-driven. No hardcoded series logic or implicit interpretation is permitted.

**Artifact consumed:** `adapter_schema_verdict`

**Checks:**
- `registry_driven` must be `true`
- `hardcoded_series_detected` must be `false`
- `implicit_interpretation_detected` must be `false`

**Implementation steps:**
1. After every `Edit` or `Write` to adapter files, scan for hardcoded series identifiers, inline data mappings, or interpretation logic not delegated to `series_registry.json`.
2. Populate `adapter_schema_verdict`.
3. Warn on first detection; block if the violation affects a contract boundary.

**Scope:** Applies to all files under adapter-related paths. Scope predicate: `adapter_registry_scope`.

**Settings binding:**
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{ "type": "command", "command": "python .claude/hooks/adapter_schema_guard.py" }]
      }
    ]
  }
}
```

---

### 4. `live-readiness-claim-blocker`

**Trigger:** `PostToolUse`
**Matcher:** `Edit|Write`
**Layer:** B — Architecture Phase Contract
**Action:** `block_on_match`

**Purpose:** Blocks any document or code write that asserts production-readiness, execution capability, or live operation — all of which are forbidden until Phase D criteria are met (CLAUDE.md Section 10).

**Artifact consumed:** `stage_gate_report`

**Checks (all must be `false`):**
- `live_readiness_claim_detected`
- `execution_capability_claim_detected`
- `production_ready_claim_detected`

**Implementation steps:**
1. After every `Edit` or `Write`, scan written content for forbidden claim phrases (see CLAUDE.md Section 10 for the enumerated list).
2. Populate `stage_gate_report`.
3. On any `true` flag, raise `unsupported_current_state_claim` and block immediately.

**Forbidden phrase patterns to match:**
- "Layer 3 is implemented"
- "production-ready" / "production ready"
- "execution is available"
- "decisions are automated"
- "externally validated"
- Synonyms and near-matches should also be flagged

**Settings binding:** Combined with `snapshot-boundary-guard` under the same `PostToolUse` / `Edit|Write` hook group.

---

### 5. `doc-code-sync-guard`

**Trigger:** `SubagentStop`
**Layer:** D — Audit Impact
**Action:** `warn`

**Purpose:** Detects doc/code drift — cases where code changed without documentation alignment or vice versa. Triggers escalation to `doc-code-sync-auditor`.

**Artifact consumed:** `doc_code_sync_status`

**Checks:**
- `drift_detected` must be `false`

**Implementation steps:**
1. After subagent stop, check `doc_code_sync_status.drift_detected`.
2. If `true`, emit a warning and flag for `doc-code-sync-auditor` escalation.
3. Do not block — this is a warning gate. However, the condition must be resolved before `pre-pr-governance-gate` passes.

**Settings binding:** Combined with `role-matched-doc-guard` under the `Stop` hook group.

---

### 6. `pre-pr-governance-gate`

**Trigger:** `PreToolUse`
**Matcher:** `git push|commit`
**Layer:** E — Verification Hygiene / Release
**Action:** `block_on_fail`

**Purpose:** The final release gate. Blocks any commit or push unless all required governance artifacts are present and all PR readiness checks pass.

**Required artifacts (always):**
- `governance_context`
- `claim_classification_map`
- `normalized_terminology_map`
- `role_citation_verdict`
- `phase_alignment_status`
- `contract_compliance_verdict`
- `stage_gate_report`
- `guard_report`
- `audit_summary`
- `change_impact_report`
- `doc_code_sync_status`
- `verification_ledger_delta`
- `artifact_hygiene_verdict`
- `pr_readiness_verdict`

**Conditional artifacts:**
- `runtime_boundary_verdict` — required when `runtime_code_scope` predicate is true
- `adapter_schema_verdict` — required when `adapter_registry_scope` predicate is true
- `doc_update_plan` — required when `doc_update_required` predicate is true
- `invariance_verdict` — required when `rename_only_change` predicate is true
- `verification_matrix_delta` — required when `matrix_posture_affected` predicate is true

**PR readiness checks (`pr_readiness_verdict`):**
- `unsupported_strong_claims_remain` = `false`
- `blocking_conditions_unresolved` = `false`
- `required_canonical_docs_reviewed` = `true`
- `canonical_references_updated` = `true`
- `alias_map_present_for_renames` = `true` (when `rename_only_change` is true)

**On failure:** Reject commit/push. Surface `pr_readiness_verdict.failed_checks` to identify which artifacts are missing or which conditions are unresolved.

**Settings binding:**
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "python .claude/hooks/pre_pr_governance_gate.py" }]
      }
    ]
  }
}
```

> Note: The Claude Code `PreToolUse` hook fires before tool execution. For git operations invoked via `Bash`, match on `Bash` and inspect the command string for `git push` or `git commit` patterns inside the hook script.

---

## Artifact Store

Hooks read from a shared session artifact store. Each artifact is a JSON file written by a skill or subagent during workflow execution.

**Proposed path:** `.claude/run/artifacts/<artifact_name>.json`

Each artifact file follows this envelope:

```json
{
  "artifact": "<name>",
  "produced_by": "<skill or subagent id>",
  "session": "<session_id>",
  "timestamp": "<iso8601>",
  "data": { ... }
}
```

Hook scripts read `data.<field>` to evaluate checks.

---

## Implementation Order

Implement hooks in dependency order — later hooks depend on artifacts produced by earlier workflow steps:

| Priority | Hook                        | Reason                                           |
|----------|-----------------------------|--------------------------------------------------|
| 1        | `snapshot-boundary-guard`   | Core contract; no artifact dependencies          |
| 2        | `adapter-schema-guard`      | Core contract; no artifact dependencies          |
| 3        | `live-readiness-claim-blocker` | Core contract; no artifact dependencies       |
| 4        | `role-matched-doc-guard`    | Depends on `role_citation_verdict`               |
| 5        | `doc-code-sync-guard`       | Depends on `doc_code_sync_status`                |
| 6        | `pre-pr-governance-gate`    | Depends on all upstream artifacts                |

---

## Enforcement Gap

Until hooks are bound in `settings.json` and hook scripts are implemented, the constitutional rules in CLAUDE.md are declared but not enforced. All six hooks are in this state as of the current phase (Phase B bootstrap).

> This is a known gap. The system is **fail-closed by design** — no execution proceeds past Phase B until enforcement is realized.

---

## Files To Create

| File                                          | Purpose                                     |
|-----------------------------------------------|---------------------------------------------|
| `.claude/hooks/role_matched_doc_guard.py`     | Reads `role_citation_verdict`, warns/blocks |
| `.claude/hooks/snapshot_boundary_guard.py`    | Scans writes for boundary violations        |
| `.claude/hooks/adapter_schema_guard.py`       | Scans adapter writes for registry drift     |
| `.claude/hooks/live_readiness_claim_blocker.py` | Scans writes for forbidden claim phrases  |
| `.claude/hooks/doc_code_sync_guard.py`        | Reads `doc_code_sync_status`, warns         |
| `.claude/hooks/pre_pr_governance_gate.py`     | Validates all artifacts before commit/push  |
| `.claude/hooks/lib/artifact_store.py`         | Shared artifact read/write utility          |
| `.claude/hooks/lib/claim_scanner.py`          | Forbidden phrase pattern matching           |

---

## Settings.json Structure (Target)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "python .claude/hooks/pre_pr_governance_gate.py" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "python .claude/hooks/snapshot_boundary_guard.py" },
          { "type": "command", "command": "python .claude/hooks/adapter_schema_guard.py" },
          { "type": "command", "command": "python .claude/hooks/live_readiness_claim_blocker.py" }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "python .claude/hooks/role_matched_doc_guard.py" },
          { "type": "command", "command": "python .claude/hooks/doc_code_sync_guard.py" }
        ]
      }
    ]
  }
}
```

---

## Exit Codes

Hook scripts must communicate outcomes via exit codes per Claude Code convention:

| Exit code | Meaning                             |
|-----------|-------------------------------------|
| `0`       | Pass — allow tool use to proceed    |
| `1`       | Warn — surface message, do not block |
| `2`       | Block — halt tool use, surface error |

For `warn_or_block` hooks: use exit `1` for warnings, exit `2` when the violation is attached to a strong claim.
For `block_on_match` hooks: always exit `2` on match.
For `block_on_fail` hooks: exit `2` if any required artifact is missing or any check fails.
