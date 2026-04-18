# CONSOLIDATED AUDIT AND REFACTOR REPORT

**Compiled:** 2026-04-18
**Last updated:** 2026-04-18 (post-refactor reconciliation)
**Branch:** `docs-final`
**Source documents merged:**
- `REPOSITORY_CONSISTENCY_AUDIT_REPORT.md` (first-pass audit, 2026-04-11)
- `REPOSITORY_REFACTOR_PLAN.md` (refactor plan, 2026-04-11)
- Second-pass verification audit (2026-04-18, focused on unresolved uncertainty and false positives)
- Post-refactor reconciliation (2026-04-18, reflecting completed Layer-2 refactor)

**Merge authority:** Post-refactor state takes precedence over all prior findings. Second-pass findings take precedence over first-pass findings where they conflict. Refactor plan items are updated to reflect completed work and remaining open items.

---

## A. Executive Summary

### Overall Health Assessment

The Mr. Ripley repository is **aligned at the Layer-2 implementation and documentation level** following the 2026-04-18 refactor. The remaining gaps are governance runtime maturity limitations, not Layer-2 correctness issues.

The core Layer-2 implementation is sound: database schema, alignment logic, quality gate, snapshot publisher, and registry handling are well-implemented and internally consistent. All ingestion adapters now import from canonical `layer2.db` and `layer2.clock` modules. The `v0/` compatibility layer has been removed. The governance infrastructure (workflow YAML, hooks, stage gates) is structurally complete and partially enforced. Hook Python code is functional and wired correctly.

The canonical documentation set (7 documents) is synchronized with implementation reality. `index_suite.py` has been canonically classified as a Layer-2 internal pre-publication computation tool. The governance "ready" verdict caveat is documented in the DAG Runner implementation state document.

### Remaining Open Items

| Rank | ID | Description | Severity |
|---|---|---|---|
| 1 | DRIFT-VERDICT-001 | Governance "ready" verdict produced by shell-mode DAG execution that does NOT run real skill logic — caveat is documented, but semantic limitation persists | MEDIUM |
| 2 | NEW-ARTIFACT-001 | Only 3 of 19 pre-PR required artifacts exist; 16 cannot be auto-generated without real skill execution; this is a governance runtime maturity gap | MEDIUM |

### Resolved Issues (2026-04-18 refactor and prior fixes)

| ID | Description | Resolution |
|---|---|---|
| DRIFT-CLI-001 | README_LAYER2 CLI flag rename overclaim | Fixed prior to refactor — docs already use `--clock-date` and `--db`, explicitly state "not renamed" |
| DRIFT-FIELD-001 | CLAUDE.md `as_of` field naming error | Fixed prior to refactor — CLAUDE.md §6.2 already says `clock_ts` |
| DRIFT-LIST-001 | `--list` missing version fields | Fixed prior to refactor — code and docs both include `engine_version`/`config_version` |
| DRIFT-PATH-001 | YAML doc paths missing `Documentation/` prefix | Fixed prior to refactor — `artifacts.yaml` and `workflow-steps.yaml` already use correct paths |
| NEW-IMPORT-001 | Four adapters importing from v0/ | RESOLVED — all adapters migrated to canonical `layer2.db`/`layer2.clock`; `v0/` directory removed (2026-04-18) |
| NEW-BOUNDARY-001 | `index_suite.py` boundary position unclassified | RESOLVED — classified as Layer-2 internal pre-publication computation tool in SYSTEM_IMPLEMENTATION_RECORD, SYSTEM_ARCHITECTURE, and VERIFICATION_MATRIX (2026-04-18) |
| D.1 | 0-byte shell script stubs | RESOLVED — deleted (2026-04-18) |
| D.5 | DecisionPacket schema/generator ambiguity | Fixed prior to refactor — CLAUDE.md §3.2 already distinguishes "schema frozen; generator / runtime production path not built" |

### Does the Repo Overclaim?

**In one area only:**
- Governance artifacts report "ready" when execution was shell-mode only (documented caveat exists, but the semantic limitation persists as a governance maturity gap)

---

## B. Verified Truths

All findings below were verified in the second pass against active files. Status confirmed as of 2026-04-18.

### B.1 Layer-2 Database Schema
- **Claim:** Three tables — `observations`, `snapshots`, `snapshot_values` — with immutable INSERT OR IGNORE semantics
- **Evidence:** `layer2/db.py` — exact CREATE TABLE statements match documented schema. No `INSERT OR REPLACE` anywhere in codebase.
- **Verdict:** VERIFIED

### B.2 Registry as Single Source of Truth
- **Claim:** `series_registry.json` is authoritative; no hardcoded series logic in adapters
- **Evidence:** All four ingestion adapters read metadata from `get_registry()`. Zero hardcoded series lists, tier assignments, or staleness thresholds in adapter code.
- **Verdict:** VERIFIED
- **Note:** All adapters import from canonical modules (`layer2.db`, `layer2.clock`, `layer2.config.registry`). The `v0/` compatibility layer was removed in the 2026-04-18 refactor.

### B.3 Fail-Closed Behavior
- **Claim:** System defaults to no output rather than incorrect output
- **Evidence:** `quality_gate.py` returns FAIL on Tier-1 stale/missing series. `snapshot_publisher.py` blocks publication on FAIL verdict (unless `--force`). DAG runner validator returns `blocked` on validation error.
- **Verdict:** VERIFIED

### B.4 Snapshot Immutability and Version-Locking
- **Claim:** Snapshots are immutable, version-locked by (clock_ts, engine_version, config_version) triple
- **Evidence:** `snapshot_publisher.py` checks `_snapshot_exists(conn, clock_ts, engine_version, config_version)` before publishing. `snapshot_id` is SHA-256 of deterministic content string including both version fields.
- **Verdict:** VERIFIED

### B.5 Point-in-Time Alignment Discipline
- **Claim:** All reads enforce `obs_ts <= clock_date` AND `as_of_ts <= clock_ts` with deterministic tie-breaking
- **Evidence:** `alignment.py` uses single SQL with `obs_ts <= ?` and `as_of_ts <= ?` boundaries, `ORDER BY obs_ts DESC, as_of_ts DESC, revision_seq DESC`.
- **Verdict:** VERIFIED

### B.6 Phase-Gate Model
- **Claim:** Phase A complete at contract boundary; Phase B allowed, not completed; Phase C future; Phase D blocked
- **Evidence:** No Layer-3 directory exists. No execution logic exists. `constants.py` defines ReasonCode enum for future use only.
- **Verdict:** VERIFIED

### B.7 Execution Boundary (Analysis-Only)
- **Claim:** No automated trading, signal execution, decision triggering, or order generation
- **Evidence:** Zero trading logic, zero execution logic, zero order generation anywhere in codebase.
- **Verdict:** VERIFIED

### B.8 Snapshot Contract Fields
- **Claim:** Published snapshots contain snapshot_id, engine_version, config_version, clock_ts, clock_date, verdict, guards, tier1/tier2 series, values with as_of_ts and revision_seq
- **Evidence:** `snapshot_publisher.py` `_build_snapshot_payload()` constructs all these fields.
- **Verdict:** VERIFIED

### B.9 Guards Object in Snapshot
- **Claim:** Snapshot JSON contains structured `guards` object with data_ok, idempotent_ok, cooldown_ok, risk_ok, supervisor_veto
- **Evidence:** `constants.py` `build_guards()` creates the guards dict; `snapshot_publisher.py` includes it in payload.
- **Verdict:** VERIFIED

### B.10 DAG Runner Structural Validity
- **Claim:** DAG runner loads, validates, plans, and executes 18 workflow steps with topological ordering
- **Evidence:** All 14 modules in `governance/dag_runner/` are implemented with test files. CLI produces `governance_run_state.json`.
- **Verdict:** VERIFIED (with caveat — see C-5: "ready" is structurally valid, not semantically meaningful as a governance signal)

### B.11 Hook Enforcement (Python Hooks)
- **Claim:** Six Python hooks enforce snapshot boundary, adapter schema, live readiness claims, role-matched docs, doc-code sync, and pre-PR gate
- **Evidence:** All six `.claude/hooks/*.py` files contain complete, functional code. All are wired in `.claude/settings.json`. Artifact store library (`artifact_store.py`) is implemented and functional.
- **Verdict:** VERIFIED

### B.12 Orchestration Source (second-pass confirmation)
- **Claim:** `.claude/workflows/system-orchestration.yaml` is the sole active orchestration entrypoint
- **Evidence:** Only one YAML file exists at the workflow root level. No historical YAML files are present. All 14 declared packages resolve on disk.
- **Verdict:** VERIFIED — no historical YAML files are being mistakenly treated as current truth

### B.13 Active Package Count (second-pass correction)
- **Claim (corrected):** 14 packages in the orchestration graph
- **Evidence:** `system-orchestration.yaml` declares 14 packages; all 14 files exist in `.claude/workflows/packages/`. First-pass audit incorrectly stated 13 — the `execution-metadata.yaml` package was present but undercounted.
- **Verdict:** VERIFIED — correct count is 14

---

## C. Confirmed Drift / Contradictions

### C-1: README_LAYER2 CLI Flag Rename Claim vs Code
- **ID:** DRIFT-CLI-001
- **Severity:** ~~HIGH~~ → RESOLVED
- **Category:** DOC-CODE
- **Status:** RESOLVED (fixed prior to 2026-04-18 refactor). README_LAYER2 now uses correct flag names (`--clock-date`, `--db`) and explicitly states at line 445: "These flags have not been renamed — they remain as originally implemented."
- **Original problem:** README_LAYER2.md claimed CLI flags were renamed. This was corrected in a prior documentation update.
- **Verification:** `grep -n "clock-date\|--db\b" Documentation/README_LAYER2.md` — confirms correct flags throughout.

### C-2: Snapshot `--list` Output Missing Version Fields
- **ID:** DRIFT-LIST-001
- **Severity:** ~~MEDIUM~~ → RESOLVED
- **Category:** DOC-CODE
- **Status:** RESOLVED (fixed prior to 2026-04-18 refactor). `_list_snapshots()` SELECT now includes `engine_version` and `config_version` (line ~224). Print format displays `eng=<version> cfg=<version>` (line ~248). README_LAYER2 correctly documents this at line 436.
- **Verification:** `grep "engine_version\|config_version" layer2/adapters/snapshot_publisher.py` — confirms both fields in SELECT and print.

### C-3: CLAUDE.md Snapshot `as_of` Field Naming Error
- **ID:** DRIFT-FIELD-001
- **Severity:** ~~HIGH~~ → RESOLVED
- **Category:** TERMINOLOGY / CONSTITUTIONAL
- **Status:** RESOLVED (fixed prior to 2026-04-18 refactor). CLAUDE.md §6.2 now correctly reads `time anchor (clock_ts)` at line 215. `grep "as_of" CLAUDE.md` returns zero matches.
- **Original problem:** CLAUDE.md named `as_of` as the snapshot time anchor. The actual field is `clock_ts`.
- **Verification:** `grep "as_of" CLAUDE.md` — zero matches.

### C-4: Workflow Package Path References Missing `Documentation/` Prefix
- **ID:** DRIFT-PATH-001
- **Severity:** ~~MEDIUM~~ → RESOLVED
- **Category:** PATH
- **Status:** RESOLVED (fixed prior to 2026-04-18 refactor). `artifacts.yaml` lines 7–31 now use `Documentation/` prefixed paths (e.g., `path: Documentation/README_v1.md`). `workflow-steps.yaml` also uses correct paths. `interpretation-policy.yaml` uses semantic role references — correctly unchanged.
- **Verification:** `grep "path:" .claude/workflows/packages/artifacts.yaml` — all canonical doc paths prefixed with `Documentation/`.

### C-5: Governance "ready" Verdict Semantics Are Misleading
- **ID:** DRIFT-VERDICT-001
- **Severity:** ~~HIGH~~ → MEDIUM (caveat documented; semantic limitation persists)
- **Category:** READINESS / GOVERNANCE
- **Status:** PARTIALLY RESOLVED. `DAG_Runner_v1_Current_Implementation_State.md` lines 26–42 now contain an extensive shell-mode caveat clearly distinguishing structural readiness from semantic governance completion. The "ready" verdict remains structurally misleading to consumers who do not read the caveat, but the documentation is accurate.
- **Remaining gap:** Optional `execution_mode: "shell_v1"` field in `StoredRunState` not yet implemented (deferred — machine-readable improvement, not blocking).
- **Verification:** Read `governance/DAG_Runner_v1_Current_Implementation_State.md` lines 26–42 for caveat content.

### C-6: Artifact Verdict Timestamps Inconsistent with Run State
- **ID:** DRIFT-TIMESTAMP-001
- **Severity:** LOW
- **Category:** GOVERNANCE
- **Problem:** `governance_run_state.json` records execution at `2026-03-31T14:29:02Z`. The three verdict artifacts in `.claude/run/artifacts/` are timestamped `2026-04-06T19:01:32Z` — six days later. Artifacts and run state are from separate processes.
- **Second-pass clarification:** This is by design. The three existing artifacts (`adapter_schema_verdict.json`, `runtime_boundary_verdict.json`, `stage_gate_report.json`) were produced by manual skill execution in a later session. The artifact store library and hook infrastructure correctly handle independent production. The gap is informational, not a malfunction.
- **Fix:** No code change. Document the independent production model in governance docs.

### C-7 (NEW): Four Canonical Adapters Import from v0/ Instead of Canonical Layer-2
- **ID:** NEW-IMPORT-001
- **Severity:** ~~HIGH~~ → RESOLVED
- **Category:** DOC-CODE / MIGRATION DEBT
- **Status:** RESOLVED (2026-04-18 refactor). All four ingestion adapters (`gold_adapter.py`, `move_adapter.py`, `fred_loader.py`, `gld_holdings_adapter.py`) migrated to canonical `layer2.db` and `layer2.clock` imports. The `layer2/adapters/v0/` directory has been removed entirely. Import compatibility verified via smoke tests (all adapters load without errors). Adapter docstrings ("Schema, connection, and upsert all come from `layer2.db`") are now truthful.
- **Verification:** `grep -r "from layer2.adapters.v0" layer2/adapters/*.py` — zero matches.

### C-8 (NEW): `index_suite.py` Reads Raw Observations — Boundary Position Unclassified
- **ID:** NEW-BOUNDARY-001
- **Severity:** ~~HIGH~~ → RESOLVED
- **Category:** SNAPSHOT CONTRACT / ARCHITECTURE
- **Status:** RESOLVED (2026-04-18 refactor). `index_suite.py` is canonically classified as a **Layer-2 internal pre-publication computation tool**. It reads observations with point-in-time alignment (same data access pattern as snapshot publisher). It is NOT a Layer-3 component and does NOT violate the snapshot boundary contract.

  Classification is documented in:
  - `CLAUDE.md` §3.2 — distinguishes Layer-2 `index_suite.py` from planned Layer-3 Index Suite
  - `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` — listed under operational Layer-2 components
  - `SYSTEM_IMPLEMENTATION_RECORD_v1.md` — documented with classification rationale
  - `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` — separate entries for Layer-2 tool (verified) and Layer-3 Index Suite (planned)
  - `README_LAYER2.md` — scoped as Layer-2 internal with note distinguishing from planned Layer-3 component

- **Verification:** `grep "index_suite" Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md` — classification present.

### C-9 (NEW): Artifact Store Partially Populated — Pre-PR Gate Cannot Pass Automatically
- **ID:** NEW-ARTIFACT-001
- **Severity:** MEDIUM
- **Category:** GOVERNANCE / ENFORCEMENT GAP
- **Problem:** The pre-pr-governance-gate hook requires 19 artifacts. Currently only 3 exist in `.claude/run/artifacts/`:
  - `adapter_schema_verdict.json` (produced by prior manual skill run, timestamped 2026-04-06)
  - `runtime_boundary_verdict.json` (same)
  - `stage_gate_report.json` (same)

  The remaining 16 artifacts cannot be auto-generated because no DAG runner executes the workflow steps automatically. All artifact production is session-dependent and manual. Artifacts from Layers A, D, and E are entirely absent.

- **Impact:** The pre-PR gate will always fail by default unless a full manual governance run is performed before each commit. The Stop hooks for `role_citation_verdict` and `doc_code_sync_status` will always warn because those artifacts are absent.
- **Second-pass clarification on Stop-hook warnings:** These warnings are NOT evidence of a broken enforcement chain. The hooks correctly detect missing artifacts and degrade gracefully to a warn-only path (exit code 1). This is by design — the hooks are correctly wired; the gap is that no runner populates artifacts before the Stop event fires.
- **Fix:** Implement a bootstrap/pre-commit script that invokes the required skills in sequence and writes artifacts to `.claude/run/artifacts/`. This is the actionable path to making the pre-PR gate passable without a full DAG runner.

---

## D. Declared But Not Proven

### D.1 Shell Script Hooks
- **Status:** RESOLVED (2026-04-18 refactor). All three 0-byte stubs (`auto-format.sh`, `run-tests.sh`, `security-scan.sh`) have been deleted. None were wired in `.claude/settings.json`.

### D.2 Skill Enforcement via Orchestration
- **Status:** Skills are SKILL.md instruction files — LLM-behavioral, not code-executed. The DAG runner's shell-mode executor does not invoke them. Enforcement depends on the LLM following instructions per session.
- **Remaining gap:** No programmatic mechanism guarantees skill logic runs or produces canonical artifacts. The documentation should make this explicit.

### D.3 Subagent Escalation Pathways
- **Status:** Eight subagents are declared in `subagents.yaml` with trigger conditions. No executable mechanism invokes them automatically. Invocation is manual (operator triggers a Claude Code session).

### D.4 Blocking Condition Runtime Enforcement
- **Status:** Of 12 declared blocking conditions:
  - 6 are enforced by Python hooks (artifact-based gating — real enforcement)
  - 6 depend on LLM skill execution (no programmatic enforcement)
  - 0 are enforced by the DAG runner at runtime (shell mode only)

### D.5 DecisionPacket Schema Frozen vs Implemented
- **Status:** RESOLVED (fixed prior to 2026-04-18 refactor). CLAUDE.md §3.2 now reads: "DecisionPacket generator (schema frozen; generator / runtime production path not built)" — clearly distinguishing schema (frozen) from generator (not built).

### D.6 Revision Writer
- **Status:** `observations` table has `revision_seq` column (default 0). No revision writer exists — no code path writes `revision_seq > 0`. Correctly documented as a known limitation in SYSTEM_LIMITATIONS §3.

---

## E. Authority and Role-Matching Review

### E.1 Canonical Document Role Assignments

The role-matching table in `interpretation-policy.yaml` correctly maps:

| Claim Type | Canonical Source | Status |
|---|---|---|
| Architecture claims | SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | VERIFIED |
| Implementation claims | SYSTEM_IMPLEMENTATION_RECORD_v1.md | VERIFIED |
| Limitation claims | SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md | VERIFIED |
| Collaborator workflow | README_LAYER2.md | VERIFIED |
| Documentation consistency | DOCUMENTATION_VERIFICATION_MATRIX_v1.md | VERIFIED |
| Technical constraints | SYSTEM_TECHNICAL_HANDBOOK_v1.md | VERIFIED |
| Top-level orientation | README_v1.md | VERIFIED |

Role assignments are consistent with CLAUDE.md §2.2. Verdict: VERIFIED.

### E.2 README_LAYER2 Overreach Assessment

README_LAYER2 no longer overreaches. The CLI flag rename claim (DRIFT-CLI-001) was corrected prior to the 2026-04-18 refactor. All current claims are role-appropriate. Verdict: VERIFIED.

### E.3 CLAUDE.md Compression Issues

One remaining compression (low priority):
1. ~~**`as_of` field naming (C-3):**~~ RESOLVED — CLAUDE.md §6.2 now correctly says `clock_ts`.
2. ~~**DecisionPacket ambiguity (D.5):**~~ RESOLVED — CLAUDE.md §3.2 now distinguishes schema (frozen) from generator (not built).
3. **Three-input layer omission:** CLAUDE.md makes no mention of the three governed inputs (Snapshot Truth, Live Market State, Event Risk Stream) canonical in SYSTEM_ARCHITECTURE §7. Low priority — cross-reference would suffice.

Verdict: CLAUDE.md is accurate. One low-priority compression remains (three-input layer cross-reference).

---

## F. Workflow / DAG / Hooks Reality Check

### F.1 Structurally Valid Workflows

| Component | Structurally Valid | Operationally Enforced |
|---|---|---|
| system-orchestration.yaml | YES | YES (loaded by DAG runner) |
| 14 workflow packages (corrected from 13) | YES | YES (merged by assembler) |
| 18 workflow steps | YES (validated, no cycles) | PARTIAL (shell-mode only) |
| Topological ordering | YES | YES |
| Validation checks (13) | YES | YES (fail-closed) |

### F.2 Hooks: Declared vs Implemented

| Hook | Declared | Implemented | Wired | Actually Blocks |
|---|---|---|---|---|
| adapter_schema_guard.py | YES | YES (~462 lines) | YES | YES (exit 2) |
| snapshot_boundary_guard.py | YES | YES (~380 lines) | YES | YES (exit 2) |
| live_readiness_claim_blocker.py | YES | YES (~456 lines) | YES | YES (exit 2) |
| role_matched_doc_guard.py | YES | YES (~255 lines) | YES | WARN by default (exit 1); blocks on strong-claim violation (exit 2) |
| doc_code_sync_guard.py | YES | YES (~239 lines) | YES | NO — warn only (exit 1) |
| pre_pr_governance_gate.py | YES | YES (~475 lines) | YES | YES (exit 2) — but requires 19 artifacts, only 3 present |
| ~~auto-format.sh~~ | ~~IMPLIED~~ | ~~NO (0 bytes)~~ | ~~NO~~ | DELETED (2026-04-18) |
| ~~run-tests.sh~~ | ~~IMPLIED~~ | ~~NO (0 bytes)~~ | ~~NO~~ | DELETED (2026-04-18) |
| ~~security-scan.sh~~ | ~~IMPLIED~~ | ~~NO (0 bytes)~~ | ~~NO~~ | DELETED (2026-04-18) |

### F.3 Stop-Hook Warnings: Expected or Malfunction?

The Stop hooks (`role_matched_doc_guard.py`, `doc_code_sync_guard.py`) fire on every agent stop. Both read artifacts (`role_citation_verdict`, `doc_code_sync_status`) that are not currently in the artifact store. When artifacts are missing, both hooks raise `ArtifactNotFound` and return exit code 1 (warn, not block). This is by design — both hooks have graceful degradation paths with explicit stderr messages.

**Verdict:** The Stop-hook warnings are the expected structural symptom of operating without a DAG runner, not evidence of a broken enforcement chain. The hooks are correctly wired; the missing piece is a runner or bootstrap process to populate artifacts before Stop fires.

### F.4 Stage Gates: Real vs Declared

All four stage gates (A–D) are enforced through pattern-matching Python hooks (`live_readiness_claim_blocker.py`). This is real enforcement, but limited to text pattern detection in edited/written files — semantic violations that don't match regex patterns can pass through.

### F.5 Blocking Conditions: Actually Enforced

Of 12 declared blocking conditions:
- **6 enforced programmatically** (Python hooks via artifact gating)
- **6 depend on LLM skill execution** (no programmatic enforcement)
- **0 enforced by DAG runner at runtime** (shell mode)

### F.6 Artifact Store: Current State

| Artifact | Present | Producer | Timestamp |
|---|---|---|---|
| adapter_schema_verdict.json | YES | Manual skill run | 2026-04-06 |
| runtime_boundary_verdict.json | YES | Manual skill run | 2026-04-06 |
| stage_gate_report.json | YES | Manual skill run | 2026-04-06 |
| All other 16 declared artifacts | NO | Requires manual skill invocation | — |

Three artifacts cover Layer C (runtime/schema/boundary integrity). Layers A (semantic normalization), D (audit/impact), and E (verification/hygiene/release) have zero populated artifacts.

### F.7 Does DAG "Ready" Mean Anything Operationally?

**No — as a governance gate signal.** The "ready" verdict means:
1. YAML spec loaded without errors
2. Structural validation passed (no cycles, no orphan references)
3. Shell-mode execution completed without predicate errors
4. All artifact placeholders were materialized

It does NOT mean: claims were classified, doc-code sync was checked, terminology was normalized, or any skill actually ran.

"Ready" is structurally reliable as a spec-validation signal and semantically vacuous as a governance-completeness signal.

---

## G. Bottleneck Statement (Post-Refactor)

The binding bottleneck is the **absence of an automated governance artifact production mechanism**. This is a governance runtime maturity limitation, not an implementation integrity issue.

**1. Artifact production gap** — 16 of 19 pre-PR required artifacts cannot be produced without manual skill invocation. No automatic runner populates them. Governance is session-dependent and non-reproducible. Creating a bootstrap script is blocked by design — it requires real skill execution capability that does not exist in V1 shell mode. Producing empty/placeholder artifacts would violate fail-closed principles.

**2. No automated DAG execution** — The DAG runner operates in V1 shell mode only. All 18 workflow steps record PASS without executing real skill logic. Artifact materialization produces structural placeholders, not semantic governance verdicts.

**3. Non-reproducible governance** — Governance enforcement depends on LLM-behavioral skill execution within Claude Code sessions. There is no programmatic mechanism to guarantee skill logic runs, produces canonical artifacts, or validates claims consistently across sessions.

~~**Former bottleneck #2 (adapter migration debt):**~~ RESOLVED — all adapters migrated to canonical imports; `v0/` removed (2026-04-18).

~~**Former bottleneck #3 (index_suite.py boundary):**~~ RESOLVED — canonically classified as Layer-2 internal pre-publication computation tool (2026-04-18).

---

## H. Remediation Plan

### Strategy

1. Docs-only fix when code is already coherent.
2. Code fix only when trivially low-risk and materially improving truthfulness.
3. Never overstate governance enforcement.
4. Smallest correct edit wins.

### Issue-by-Issue Fix Decisions

| Issue ID | Fix Type | Decision | Status |
|---|---|---|---|
| DRIFT-CLI-001 | Docs-only | Revert README_LAYER2 to use `--clock-date` and `--db` | RESOLVED (prior fix) |
| DRIFT-LIST-001 | Code fix | Add `engine_version, config_version` to `_list_snapshots()` SELECT | RESOLVED (prior fix) |
| DRIFT-FIELD-001 | Docs-only | Change CLAUDE.md §6.2 `as_of` → `clock_ts` | RESOLVED (prior fix) |
| DRIFT-PATH-001 | Docs-only | Add `Documentation/` prefix in `artifacts.yaml` and `workflow-steps.yaml` | RESOLVED (prior fix) |
| DRIFT-VERDICT-001 | Docs + optional code | Document caveat in DAG Runner doc; optionally add `execution_mode` field | PARTIALLY RESOLVED (caveat documented; code field deferred) |
| DRIFT-TIMESTAMP-001 | No fix | By design; informational only | N/A |
| NEW-IMPORT-001 | Code fix | Migrate four adapters to `layer2.db` + `layer2.clock`; remove `v0/` | RESOLVED (2026-04-18) |
| NEW-BOUNDARY-001 | Docs fix | Add canonical boundary classification for `index_suite.py` | RESOLVED (2026-04-18) |
| NEW-ARTIFACT-001 | New tooling | Implement artifact bootstrap — blocked by design (requires real skill execution) | DEFERRED |
| D.1 (shell stubs) | Delete | Remove three 0-byte files | RESOLVED (2026-04-18) |
| D.5 (DecisionPacket) | Docs-only | Clarify schema-frozen vs generator-not-built in CLAUDE.md §3.2 | RESOLVED (prior fix) |

---

## I. File-by-File Execution Map

| File | Issues Addressed | Edit Type | Status |
|---|---|---|---|
| `CLAUDE.md` | DRIFT-FIELD-001, D.5, NEW-BOUNDARY-001 | Targeted wording edits | DONE (prior fix + 2026-04-18) |
| `Documentation/README_LAYER2.md` | DRIFT-CLI-001, DRIFT-LIST-001, NEW-BOUNDARY-001 | Text corrections + scope note | DONE (prior fix + 2026-04-18) |
| `layer2/adapters/snapshot_publisher.py` | DRIFT-LIST-001 (code side) | SELECT + format change | DONE (prior fix) |
| `layer2/adapters/gold_adapter.py` | NEW-IMPORT-001 | Import path migration | DONE (2026-04-18) |
| `layer2/adapters/fred_loader.py` | NEW-IMPORT-001 | Import path migration | DONE (2026-04-18) |
| `layer2/adapters/gld_holdings_adapter.py` | NEW-IMPORT-001 | Import path migration | DONE (2026-04-18) |
| `layer2/adapters/move_adapter.py` | NEW-IMPORT-001 | Import path migration | DONE (2026-04-18) |
| `layer2/adapters/v0/` | NEW-IMPORT-001 followup | Directory removal | DONE (2026-04-18) |
| `Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md` | NEW-BOUNDARY-001 | Add classification + migration note | DONE (2026-04-18) |
| `Documentation/SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | NEW-BOUNDARY-001 | Add Layer-2 tool classification | DONE (2026-04-18) |
| `Documentation/DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | NEW-BOUNDARY-001 | Add Layer-2 tool row | DONE (2026-04-18) |
| `.claude/workflows/packages/artifacts.yaml` | DRIFT-PATH-001 | Path prefix additions | DONE (prior fix) |
| `.claude/workflows/packages/workflow-steps.yaml` | DRIFT-PATH-001 | Path prefix additions | DONE (prior fix) |
| `governance/DAG_Runner_v1_Current_Implementation_State.md` | DRIFT-VERDICT-001 | Shell-mode caveat | DONE (prior fix) |
| `.claude/hooks/auto-format.sh` | D.1 | Delete | DONE (2026-04-18) |
| `.claude/hooks/run-tests.sh` | D.1 | Delete | DONE (2026-04-18) |
| `.claude/hooks/security-scan.sh` | D.1 | Delete | DONE (2026-04-18) |
| `.claude/run/bootstrap_artifacts.py` | NEW-ARTIFACT-001 | New file | DEFERRED (blocked by design) |

**Files NOT edited (correctly unchanged):**
- `.claude/workflows/packages/interpretation-policy.yaml` — uses semantic role references, not filesystem paths
- `governance/dag_runner/verdict.py` — no rename of `ready`; caveat handled in docs
- `governance/dag_runner/state_store.py` — `execution_mode` deferred (optional machine-readable improvement)

---

## J. Phased Refactor Order

### Phase 1: Constitutional Corrections — COMPLETE (prior fixes)

| Step | File | Change | Status |
|---|---|---|---|
| 1a | `CLAUDE.md` | `as_of` → `clock_ts` in §6.2 | DONE |
| 1b | `CLAUDE.md` | Clarify DecisionPacket schema (frozen) vs generator (not built) in §3.2 | DONE |

### Phase 2: Governance Documentation — COMPLETE (prior fixes)

| Step | File | Change | Status |
|---|---|---|---|
| 2a | `governance/DAG_Runner_v1_Current_Implementation_State.md` | Add explicit shell-mode verdict caveat | DONE |

### Phase 3: Path Corrections — COMPLETE (prior fixes)

| Step | File | Change | Status |
|---|---|---|---|
| 3a | `.claude/workflows/packages/artifacts.yaml` | Add `Documentation/` prefix to 7 canonical doc paths | DONE |
| 3b | `.claude/workflows/packages/workflow-steps.yaml` | Add `Documentation/` prefix to canonical doc references | DONE |

### Phase 4: README_LAYER2 Alignment — COMPLETE (prior fixes)

| Step | File | Change | Status |
|---|---|---|---|
| 4a | `Documentation/README_LAYER2.md` | Correct CLI flag names to `--clock-date` and `--db` | DONE |
| 4b | `Documentation/README_LAYER2.md` | Correct `--list` version field claims | DONE |

### Phase 5: Code Fixes — COMPLETE (prior fixes + 2026-04-18 refactor)

| Step | File | Change | Status |
|---|---|---|---|
| 5a | `layer2/adapters/snapshot_publisher.py` | Add `engine_version, config_version` to `_list_snapshots()` SELECT and print | DONE (prior fix) |
| 5b | `layer2/adapters/gold_adapter.py` | Migrate imports: `v0.db` → `layer2.db`, `v0.clock` → `layer2.clock` | DONE (2026-04-18) |
| 5c | `layer2/adapters/fred_loader.py` | Same migration | DONE (2026-04-18) |
| 5d | `layer2/adapters/gld_holdings_adapter.py` | Same migration | DONE (2026-04-18) |
| 5e | `layer2/adapters/move_adapter.py` | Same migration | DONE (2026-04-18) |
| 5f | `layer2/adapters/v0/` | Remove directory after migration | DONE (2026-04-18) |

### Phase 6: Boundary Classification — COMPLETE (2026-04-18 refactor)

| Step | File | Change | Status |
|---|---|---|---|
| 6a | `Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Add canonical boundary classification for `index_suite.py` | DONE |
| 6b | `Documentation/SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Add matching architectural statement | DONE |
| 6c | `Documentation/DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Add Layer-2 tool row; distinguish from Layer-3 planned component | DONE |
| 6d | `CLAUDE.md` | Clarify Index Suite naming distinction in §3.2 | DONE |

### Phase 7: Stub Cleanup — COMPLETE (2026-04-18 refactor)

| Step | File | Change | Status |
|---|---|---|---|
| 7a | `.claude/hooks/auto-format.sh` | Delete | DONE |
| 7b | `.claude/hooks/run-tests.sh` | Delete | DONE |
| 7c | `.claude/hooks/security-scan.sh` | Delete | DONE |

### Phase 8: Artifact Bootstrap Tooling — DEFERRED

| Step | File | Change | Status |
|---|---|---|---|
| 8a | `.claude/run/bootstrap_artifacts.py` | Implement pre-commit artifact population script | DEFERRED |

**Deferral rationale:** Creating `bootstrap_artifacts.py` is blocked by design. It requires real skill execution capability that does not exist in V1 shell mode. A bootstrap script producing empty/placeholder artifacts would violate fail-closed principles (artifacts would claim verdicts without evidence). The pre-PR gate's current behavior (blocking on missing artifacts) is the correct fail-closed response. Resolution requires implementing real skill execution in a future DAG runner version (Phase B/C work).

---

## K. Risk Register

| Risk ID | Description | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | README_LAYER2 CLI revert misses an occurrence | Medium | HIGH | Grep-based verification post-edit for `--date ` and `--db-path` |
| R-2 | `_list_snapshots()` format change breaks consuming scripts | Low | MEDIUM | Review print format; keep backward-compatible column ordering |
| R-3 | YAML path prefix breaks DAG runner loader | Very Low | MEDIUM | Loader resolves package paths, not doc metadata paths — declarative only |
| R-4 | Deleting shell stubs breaks a hook wiring | Very Low | LOW | Confirm `.claude/settings.json` has no `.sh` references before deleting |
| R-5 | CLAUDE.md `clock_ts` change triggers downstream interpretation drift | Very Low | MEDIUM | Corrects a factual error; cached wrong name is worse |
| R-6 | `_list_snapshots()` code change introduces regression in snapshot publishing | Low | HIGH | `_list_snapshots()` is read-only display; does not affect `_publish_snapshot()` |
| R-7 (NEW) | ~~Adapter import migration breaks ingestion pipeline~~ | ~~Low~~ | ~~HIGH~~ | RESOLVED — migration completed; all adapters verified via import smoke tests (2026-04-18) |
| R-8 (NEW) | ~~`index_suite.py` boundary classification triggers snapshot contract audit~~ | ~~Medium~~ | ~~MEDIUM~~ | RESOLVED — classified as Layer-2 internal; no snapshot contract concern (2026-04-18) |
| R-9 (NEW) | Bootstrap artifact script produces stale/incorrect artifacts | Medium | HIGH | DEFERRED — script not created; blocked by design (requires real skill execution) |

---

## L. Verification Plan

### Per-Phase Verification

| Phase | Verification Method | Pass Criteria | Status |
|---|---|---|---|
| 1 | `grep -n "as_of" CLAUDE.md` | No snapshot-level `as_of` references remain | PASSED |
| 1 | Read CLAUDE.md §3.2 | DecisionPacket schema/generator distinction is clear | PASSED |
| 2 | Read DAG Runner doc | Shell-mode caveat is prominent and unambiguous | PASSED |
| 3 | `grep "path:" .claude/workflows/packages/artifacts.yaml` | All paths have `Documentation/` prefix | PASSED |
| 4 | `grep -n "clock-date\|--db\b" Documentation/README_LAYER2.md` | Correct flags used throughout | PASSED |
| 5a | `grep "engine_version\|config_version" layer2/adapters/snapshot_publisher.py` | Version fields in SELECT and print | PASSED |
| 5b–5f | Import each adapter; v0/ removed | No import errors; v0/ directory absent | PASSED (2026-04-18) |
| 6 | `grep "index_suite" Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Clear boundary classification present | PASSED (2026-04-18) |
| 7 | `ls .claude/hooks/*.sh` | No results | PASSED (2026-04-18) |
| 8 | Run bootstrap script | 19 artifacts present | DEFERRED |

### Cross-Cutting Verification

| Check | Method | Pass Criteria | Status |
|---|---|---|---|
| No canonical adapter imports v0 | `grep -r "from layer2.adapters.v0" layer2/adapters/*.py` | Zero matches | PASSED |
| CLAUDE.md field names correct | `grep "as_of" CLAUDE.md` | Zero matches | PASSED |
| Index Suite distinction clear | `grep "Index Suite\|index_suite" CLAUDE.md` | Layer-2 vs Layer-3 distinguished | PASSED |
| Shell stubs removed | `ls .claude/hooks/*.sh` | No files | PASSED |
| Hook enforcement intact | Trigger a test Edit and confirm hooks fire | Python hooks produce verdicts | PASSED |
| Pre-PR gate passable | Run pre-commit hook against a test session | Gate passes with all 19 artifacts | BLOCKED (by design — 16 artifacts missing) |

---

## M. Prioritized Backlog (Post-Refactor)

### P0 — Must Fix Before Merge: ALL RESOLVED

All former P0 items have been resolved:
- ~~CLAUDE.md `as_of` → `clock_ts`~~ — RESOLVED (prior fix)
- ~~README_LAYER2 CLI flag revert~~ — RESOLVED (prior fix)
- ~~DAG Runner shell-mode caveat~~ — RESOLVED (prior fix)
- ~~`index_suite.py` boundary classification~~ — RESOLVED (2026-04-18)

### P1 — Should Fix Before Merge: ALL RESOLVED

All former P1 items have been resolved:
- ~~Four-adapter import migration~~ — RESOLVED (2026-04-18)
- ~~CLAUDE.md DecisionPacket clarification~~ — RESOLVED (prior fix)
- ~~YAML path prefix corrections~~ — RESOLVED (prior fix)
- ~~README_LAYER2 snapshot listing correction~~ — RESOLVED (prior fix)
- ~~`_list_snapshots()` code fix~~ — RESOLVED (prior fix)
- ~~Delete empty shell stubs~~ — RESOLVED (2026-04-18)
- ~~`v0/` directory removal~~ — RESOLVED (2026-04-18)

### P2 — Deferred (governance maturity, not Layer-2 correctness)

| Item | Issue ID | Reason |
|---|---|---|
| Artifact bootstrap script | NEW-ARTIFACT-001 | Blocked by design — requires real skill execution (V1 shell mode limitation) |
| `execution_mode` field in StoredRunState | DRIFT-VERDICT-001 (code part) | Machine-readable improvement; not blocking |
| CLAUDE.md three-input reference | G-12 | Compression, not drift; canonical docs cover it |
| Artifact timestamp documentation | DRIFT-TIMESTAMP-001 | Informational; no user impact |

---

## N. Final Verdict

> **Layer-2 implementation and documentation are aligned. Remaining gaps are governance runtime maturity limitations.**

### The three truths — converged

**The code** is internally consistent: Layer-2 engine is sound, fail-closed, and version-locked. All adapters import from canonical modules. `v0/` compatibility layer is removed. `index_suite.py` is classified and operates correctly within its Layer-2 boundary.

**The documentation** is synchronized with implementation reality: CLI flags, snapshot fields, listing output, boundary classifications, and architectural positions all match the code. No overclaims remain in the canonical documentation set.

**The governance layer** is structurally valid but semantically incomplete: hooks are wired and functional, but 16 of 19 required artifacts are absent (by design — real skill execution is not available in V1 shell mode). The DAG runner's "ready" verdict has a documented caveat clarifying it reflects spec validation, not governance completeness.

### Merge readiness

All former P0 and P1 items have been resolved. The repository is self-consistent at the Layer-2 implementation and documentation level.

Remaining limitations are governance runtime maturity issues:
- 16/19 governance artifacts missing (blocked by V1 shell-mode design)
- No automated DAG execution (shell-mode only)
- Governance enforcement depends on LLM-behavioral skill execution

These do not affect Layer-2 runtime correctness, documentation accuracy, or snapshot contract integrity.

---

## O. Post-Refactor Alignment Status (2026-04-18)

- Layer-2 implementation is internally consistent — all adapters use canonical imports, snapshot boundary is correctly enforced, registry-driven discipline is intact
- Canonical documentation set (7 documents) is synchronized with implementation reality
- Snapshot boundary contract is correctly enforced — no downstream raw observation access
- `index_suite.py` boundary classification is resolved — Layer-2 internal pre-publication computation tool, documented across 5 canonical sources
- Adapter migration is complete — `layer2/adapters/v0/` removed, all adapters import from `layer2.db` and `layer2.clock`
- Governance shell-mode caveat is documented — "ready" verdict semantics are explicit
- Remaining open items are governance execution-related (artifact production, automated DAG execution), not Layer-2 correctness issues

---

*End of consolidated report.*
*Sources: REPOSITORY_CONSISTENCY_AUDIT_REPORT.md (2026-04-11), REPOSITORY_REFACTOR_PLAN.md (2026-04-11), second-pass verification (2026-04-18), post-refactor reconciliation (2026-04-18).*
