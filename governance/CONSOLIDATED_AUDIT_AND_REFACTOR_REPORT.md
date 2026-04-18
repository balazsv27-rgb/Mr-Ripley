# CONSOLIDATED AUDIT AND REFACTOR REPORT

**Compiled:** 2026-04-18  
**Branch:** `docs-final`  
**Source documents merged:**
- `REPOSITORY_CONSISTENCY_AUDIT_REPORT.md` (first-pass audit, 2026-04-11)
- `REPOSITORY_REFACTOR_PLAN.md` (refactor plan, 2026-04-11)
- Second-pass verification audit (2026-04-18, focused on unresolved uncertainty and false positives)

**Merge authority:** Second-pass findings take precedence over first-pass findings where they conflict. Refactor plan items are updated to reflect second-pass corrections and new findings.

---

## A. Executive Summary

### Overall Health Assessment

The Mr. Ripley repository is **partially aligned with several material drifts present, and three newly confirmed structural gaps**.

The core Layer-2 implementation is sound: database schema, alignment logic, quality gate, snapshot publisher, and registry handling are well-implemented and internally consistent. The governance infrastructure (workflow YAML, hooks, stage gates) is structurally complete and partially enforced. Hook Python code is functional and wired correctly.

However, **documentation has drifted from code in verifiable ways**, the **governance "ready" verdict is structurally misleading**, **four canonical ingestion adapters are importing from `v0/` instead of canonical `layer2/` modules**, and **`index_suite.py` operates across the snapshot boundary without canonical documentation of its architectural position**.

### Highest-Risk Inconsistencies

| Rank | ID | Description | Severity |
|---|---|---|---|
| 1 | DRIFT-CLI-001 | README_LAYER2 claims CLI flags were renamed (`--date`, `--db-path`) but code still uses old names (`--clock-date`, `--db`) — collaborators following docs get errors | HIGH |
| 2 | DRIFT-FIELD-001 | CLAUDE.md §6.2 requires `as_of` as snapshot time anchor — actual snapshots use `clock_ts`; no `as_of` field exists at snapshot level | HIGH |
| 3 | DRIFT-VERDICT-001 | Governance "ready" verdict produced by shell-mode DAG execution that does NOT run real skill logic — misleading as a gate-passing signal | HIGH |
| 4 | NEW-IMPORT-001 | Four canonical adapters import from `layer2/adapters/v0/db` and `layer2/adapters/v0/clock` while their docstrings claim "Schema, connection, and upsert all come from `layer2.db`" | HIGH |
| 5 | NEW-BOUNDARY-001 | `layer2/index_suite.py` reads from `observations` table directly (bypassing snapshot boundary) with no canonical classification of its architectural position | HIGH |
| 6 | DRIFT-LIST-001 | Snapshot `--list` output does NOT show `engine_version` / `config_version` despite README_LAYER2 claiming it does | MEDIUM |
| 7 | DRIFT-PATH-001 | Workflow package path references use bare filenames without `Documentation/` prefix — no resolution mechanism | MEDIUM |
| 8 | NEW-ARTIFACT-001 | Only 3 of 19 pre-PR required artifacts exist; 16 cannot be auto-generated; Stop-hook warnings for `role_citation_verdict` and `doc_code_sync_status` are the structural symptom | MEDIUM |

### Does the Repo Overclaim?

**Yes, in four specific areas:**
- README_LAYER2 overclaims a CLI rename that never occurred in code
- README_LAYER2 overclaims snapshot listing fields not present in output
- Governance artifacts overclaim "ready" when execution was shell-mode only
- Four adapter docstrings claim canonical `layer2.db` imports while actual imports are from `v0/db`

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
- **Note:** The import path for `get_registry()` is correctly `layer2.config.registry` in all adapters — this is the one clean import even in the adapters that otherwise import from `v0/`.

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
- **Severity:** HIGH
- **Category:** DOC-CODE
- **Problem:** README_LAYER2.md §7 explicitly states: *"CLI flag change (v2): `--clock-date` is now `--date`. `--db` is now `--db-path`."* and uses `--date` in example commands. However, `snapshot_publisher.py` still defines `--clock-date` and `--db`. The rename never happened.
- **Evidence in docs:** README_LAYER2.md, example commands at lines ~412, 421, 723
- **Evidence in code:** `layer2/adapters/snapshot_publisher.py` argparse defines `--clock-date` and `--db`
- **Impact:** Any user following README_LAYER2 examples gets unrecognized argument errors. Functional break for collaborator onboarding.
- **Fix:** Revert docs to use actual flag names `--clock-date` and `--db`. Do NOT rename code flags (also used in `quality_gate.py`).

### C-2: Snapshot `--list` Output Missing Version Fields
- **ID:** DRIFT-LIST-001
- **Severity:** MEDIUM
- **Category:** DOC-CODE
- **Problem:** README_LAYER2 claims `--list` shows `engine_version` and `config_version`. Code's `_list_snapshots()` queries only: `snapshot_id, clock_ts, verdict, tier1_pass, tier1_fail, series_count, dry_run, forced, created_at`. Neither version field is selected.
- **Evidence in code:** `layer2/adapters/snapshot_publisher.py` line ~223: SELECT statement
- **Impact:** Operators expecting version fields won't see them, undermining version-locking visibility.
- **Fix:** Code fix — add `engine_version, config_version` to `_list_snapshots()` SELECT. Both columns exist in the `snapshots` table.

### C-3: CLAUDE.md Snapshot `as_of` Field Naming Error
- **ID:** DRIFT-FIELD-001
- **Severity:** HIGH
- **Category:** TERMINOLOGY / CONSTITUTIONAL
- **Problem:** CLAUDE.md §6.2 states each snapshot MUST have a `time anchor (as_of)`. No top-level `as_of` field exists in snapshot payloads. The actual time anchor is `clock_ts`. The field `as_of_ts` exists only at the per-observation/per-value level.
- **Evidence in docs:** CLAUDE.md line 215: `- time anchor (\`as_of\`)`
- **Evidence in code:** `snapshot_publisher.py` builds snapshot with `clock_ts` as time anchor
- **Impact:** Constitutional requirement does not match reality. Agents reading CLAUDE.md as authoritative will look for a field that doesn't exist.
- **Fix:** Docs-only — change CLAUDE.md §6.2 to reference `clock_ts`.

### C-4: Workflow Package Path References Missing `Documentation/` Prefix
- **ID:** DRIFT-PATH-001
- **Severity:** MEDIUM
- **Category:** PATH
- **Problem:** `artifacts.yaml` and `workflow-steps.yaml` reference canonical docs with bare filenames (e.g., `README_v1.md`). Actual files live at `Documentation/README_v1.md`. No path aliasing exists.
- **Evidence:** `artifacts.yaml` lines 7–31: `path: README_v1.md`, etc.
- **Impact:** If any tooling attempts to resolve these paths, they will fail.
- **Fix:** Add `Documentation/` prefix to paths in `artifacts.yaml` and `workflow-steps.yaml`. `interpretation-policy.yaml` uses semantic role references — no fix needed there.

### C-5: Governance "ready" Verdict Semantics Are Misleading
- **ID:** DRIFT-VERDICT-001
- **Severity:** HIGH
- **Category:** READINESS / GOVERNANCE
- **Problem:** `governance_run_state.json` reports `verdict_status: "ready"` with 18/18 steps PASS. However, the executor runs in **V1 shell mode** which does NOT execute real skill logic — it records each step as PASS and materializes placeholder artifacts. "Ready" means "structural spec validation passed," NOT "real governance checks were performed and passed."
- **Impact:** A reader would reasonably conclude all 18 governance steps were evaluated. In reality, no claim classification, terminology normalization, doc-code sync, or verification matrix update occurred.
- **Fix:** Required: add explicit shell-mode caveat to `DAG_Runner_v1_Current_Implementation_State.md`. Optional: add `execution_mode: "shell_v1"` field to `StoredRunState`.

### C-6: Artifact Verdict Timestamps Inconsistent with Run State
- **ID:** DRIFT-TIMESTAMP-001
- **Severity:** LOW
- **Category:** GOVERNANCE
- **Problem:** `governance_run_state.json` records execution at `2026-03-31T14:29:02Z`. The three verdict artifacts in `.claude/run/artifacts/` are timestamped `2026-04-06T19:01:32Z` — six days later. Artifacts and run state are from separate processes.
- **Second-pass clarification:** This is by design. The three existing artifacts (`adapter_schema_verdict.json`, `runtime_boundary_verdict.json`, `stage_gate_report.json`) were produced by manual skill execution in a later session. The artifact store library and hook infrastructure correctly handle independent production. The gap is informational, not a malfunction.
- **Fix:** No code change. Document the independent production model in governance docs.

### C-7 (NEW): Four Canonical Adapters Import from v0/ Instead of Canonical Layer-2
- **ID:** NEW-IMPORT-001
- **Severity:** HIGH
- **Category:** DOC-CODE / MIGRATION DEBT
- **Problem:** Four canonical ingestion adapters import from `layer2.adapters.v0.db` and `layer2.adapters.v0.clock`, while their module docstrings state "Schema, connection, and upsert all come from `layer2.db`." This is a partial migration: `snapshot_publisher.py` and `quality_gate.py` have been fully migrated to canonical imports; the four ingestion adapters have not.

  Specifically:
  - `layer2/adapters/gold_adapter.py` — imports `layer2.adapters.v0.db`, `layer2.adapters.v0.clock`
  - `layer2/adapters/fred_loader.py` — imports `layer2.adapters.v0.db`, `layer2.adapters.v0.clock`
  - `layer2/adapters/gld_holdings_adapter.py` — imports `layer2.adapters.v0.db`, `layer2.adapters.v0.clock`
  - `layer2/adapters/move_adapter.py` — imports `layer2.adapters.v0.db`, `layer2.adapters.v0.clock`
  
  Additionally, `layer2/adapters/v0/clock.py` is a **complete copy** of `layer2/clock.py` (not a thin shim), meaning two identical clock implementations coexist with divergence risk.

- **What the v0/ modules provide vs canonical:** The v0/ db module provides `get_connection`, `upsert_observations`, `filter_new_rows`, `latest_obs_date`, `count_rows`. The canonical `layer2.db` provides the same interface. The functional difference is zero today, but any change to `layer2.db` without updating `v0/db.py` will silently diverge.
- **Fix:** Migrate the four adapters to import from `layer2.db` and `layer2.clock` directly. After migration, assess `layer2/adapters/v0/` for removal.

### C-8 (NEW): `index_suite.py` Reads Raw Observations — Boundary Position Unclassified
- **ID:** NEW-BOUNDARY-001
- **Severity:** HIGH
- **Category:** SNAPSHOT CONTRACT / ARCHITECTURE
- **Problem:** `layer2/index_suite.py` is a fully implemented (~770 lines), operational runtime module that queries the `observations` table directly via `_get_pt_series()` using point-in-time SQL. It does NOT read from published snapshots.

  Under CLAUDE.md §6, Layer 3+ components MUST read only from published snapshots and MUST NOT read raw observations. If `index_suite.py` is a downstream/Layer-3 component, this is a snapshot contract violation.
  
  However, `index_suite.py` also imports from `layer2.alignment` and operates as a pre-publication computation tool (its CLI is `python -m layer2.index_suite`). This suggests it may be classified as a Layer-2 internal computation (pre-snapshot), which is acceptable. The self-description says "provisional M1 specs" referring to calibration, not implementation status — the file is fully implemented and runnable.

- **The critical gap:** No canonical document explicitly classifies `index_suite.py`'s position relative to the snapshot boundary. `SYSTEM_IMPLEMENTATION_RECORD_v1.md` and `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` must be consulted and, if silent, updated.
- **Fix:** Add a one-sentence canonical classification to `SYSTEM_IMPLEMENTATION_RECORD_v1.md` and `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` stating whether `index_suite.py` is a Layer-2 pre-snapshot computation or a post-snapshot downstream consumer.

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
- **Status:** All three (`auto-format.sh`, `run-tests.sh`, `security-scan.sh`) are 0-byte stubs. None are wired in `.claude/settings.json`. Should be deleted.

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
- **Status:** DecisionPacket v0 schema is documented and frozen (design-locked). No code file, JSON schema, or Python dataclass implements it. CLAUDE.md §3.2 lists "DecisionPacket" ambiguously — should distinguish schema (frozen) from generator (not built).

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

README_LAYER2 overreaches in one specific area (CLI flag rename claim — DRIFT-CLI-001). All other claims are role-appropriate. Verdict: PARTIALLY VERIFIED.

### E.3 CLAUDE.md Compression Issues

Three issues identified:
1. **`as_of` field naming (C-3):** Factual error — `as_of` does not exist as a snapshot-level field. Corrected form: `clock_ts`.
2. **DecisionPacket ambiguity (D.5):** Schema (frozen) vs generator (not built) not distinguished.
3. **Three-input layer omission:** CLAUDE.md makes no mention of the three governed inputs (Snapshot Truth, Live Market State, Event Risk Stream) canonical in SYSTEM_ARCHITECTURE §7. Low priority — cross-reference would suffice.

Verdict: CLAUDE.md is mostly accurate but has one factual error and two meaningful compressions.

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
| auto-format.sh | IMPLIED | NO (0 bytes) | NO | NO |
| run-tests.sh | IMPLIED | NO (0 bytes) | NO | NO |
| security-scan.sh | IMPLIED | NO (0 bytes) | NO | NO |

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

## G. Bottleneck Statement (Final Corrected)

The binding bottleneck is the **absence of an automated artifact population mechanism**, which creates a split-enforcement model with three distinct failure modes:

**1. Artifact gap** — 16 of 19 pre-PR required artifacts cannot be produced without manual skill invocation. No automatic runner populates them. Governance is session-dependent and non-reproducible.

**2. Partial migration debt** — Four canonical ingestion adapters import from `v0/db` and `v0/clock` despite docstrings claiming canonical imports. The v0 clock is a complete duplicate of the canonical clock. Any change to `layer2.db` or `layer2.clock` must be manually synchronized with `v0/` — a silent divergence risk.

**3. Unresolved architectural boundary** — `index_suite.py` is a fully implemented, runnable module that reads from `observations` directly. Without a canonical classification of its position relative to the snapshot boundary, any governance check touching this file will encounter an unverifiable claim. If it is a Layer-2 internal computation, it is acceptable. If it is post-snapshot, it violates CLAUDE.md §6. No canonical document resolves this.

---

## H. Remediation Plan

### Strategy

1. Docs-only fix when code is already coherent.
2. Code fix only when trivially low-risk and materially improving truthfulness.
3. Never overstate governance enforcement.
4. Smallest correct edit wins.

### Issue-by-Issue Fix Decisions

| Issue ID | Fix Type | Decision |
|---|---|---|
| DRIFT-CLI-001 | Docs-only | Revert README_LAYER2 to use `--clock-date` and `--db`; do NOT rename code flags |
| DRIFT-LIST-001 | Code fix | Add `engine_version, config_version` to `_list_snapshots()` SELECT — columns exist, trivial addition |
| DRIFT-FIELD-001 | Docs-only | Change CLAUDE.md §6.2 `as_of` → `clock_ts` |
| DRIFT-PATH-001 | Docs-only | Add `Documentation/` prefix in `artifacts.yaml` and `workflow-steps.yaml` |
| DRIFT-VERDICT-001 | Docs + optional code | Document caveat in DAG Runner doc; optionally add `execution_mode` field |
| DRIFT-TIMESTAMP-001 | No fix | By design; informational only |
| NEW-IMPORT-001 | Code fix | Migrate four adapters to `layer2.db` + `layer2.clock`; assess `v0/` for removal |
| NEW-BOUNDARY-001 | Docs fix | Add canonical boundary classification for `index_suite.py` to SYSTEM_IMPLEMENTATION_RECORD_v1.md and SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md |
| NEW-ARTIFACT-001 | New tooling | Implement `.claude/run/bootstrap_artifacts.py` to populate Layer A and E artifacts before pre-PR gate |
| D.1 (shell stubs) | Delete | Remove three 0-byte files |
| D.5 (DecisionPacket) | Docs-only | Clarify schema-frozen vs generator-not-built in CLAUDE.md §3.2 |

---

## I. File-by-File Execution Map

| File | Issues Addressed | Edit Type | Dependencies |
|---|---|---|---|
| `CLAUDE.md` | DRIFT-FIELD-001, D.5 | 2 targeted wording edits | None |
| `Documentation/README_LAYER2.md` | DRIFT-CLI-001, DRIFT-LIST-001 (doc side) | Multi-line text replacement | None |
| `layer2/adapters/snapshot_publisher.py` | DRIFT-LIST-001 (code side) | SELECT + format change | Test verification |
| `layer2/adapters/gold_adapter.py` | NEW-IMPORT-001 | Import path replacement | After v0/ audit |
| `layer2/adapters/fred_loader.py` | NEW-IMPORT-001 | Import path replacement | After v0/ audit |
| `layer2/adapters/gld_holdings_adapter.py` | NEW-IMPORT-001 | Import path replacement | After v0/ audit |
| `layer2/adapters/move_adapter.py` | NEW-IMPORT-001 | Import path replacement | After v0/ audit |
| `Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md` | NEW-BOUNDARY-001 | Add one-sentence classification | Requires decision on boundary position |
| `Documentation/SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | NEW-BOUNDARY-001 | Add one-sentence classification | Coordinate with IMPLEMENTATION_RECORD |
| `.claude/workflows/packages/artifacts.yaml` | DRIFT-PATH-001 | Path prefix additions | Coordinate with workflow-steps.yaml |
| `.claude/workflows/packages/workflow-steps.yaml` | DRIFT-PATH-001 | Path prefix additions | Coordinate with artifacts.yaml |
| `governance/DAG_Runner_v1_Current_Implementation_State.md` | DRIFT-VERDICT-001 | Add caveat section | None |
| `.claude/run/bootstrap_artifacts.py` | NEW-ARTIFACT-001 | New file | Requires skill invocation design |
| `.claude/hooks/auto-format.sh` | D.1 | Delete | Confirm not in settings.json |
| `.claude/hooks/run-tests.sh` | D.1 | Delete | Confirm not in settings.json |
| `.claude/hooks/security-scan.sh` | D.1 | Delete | Confirm not in settings.json |

**Files NOT edited:**
- `.claude/workflows/packages/interpretation-policy.yaml` — uses semantic role references, not filesystem paths
- `governance/dag_runner/verdict.py` — no rename of `ready`; caveat handled in docs
- `governance/dag_runner/state_store.py` — `execution_mode` deferred to P1

---

## J. Phased Refactor Order

### Phase 1: Constitutional Corrections (zero functional risk)

| Step | File | Change |
|---|---|---|
| 1a | `CLAUDE.md` | `as_of` → `clock_ts` in §6.2 |
| 1b | `CLAUDE.md` | Clarify DecisionPacket schema (frozen) vs generator (not built) in §3.2 |

Gate: Grep CLAUDE.md for `as_of` as snapshot-level field — zero matches expected.

### Phase 2: Governance Documentation (zero functional risk)

| Step | File | Change |
|---|---|---|
| 2a | `governance/DAG_Runner_v1_Current_Implementation_State.md` | Add explicit shell-mode verdict caveat |

Gate: Read the caveat section and confirm it distinguishes structural-ready from governance-ready.

### Phase 3: Path Corrections (zero functional risk)

| Step | File | Change |
|---|---|---|
| 3a | `.claude/workflows/packages/artifacts.yaml` | Add `Documentation/` prefix to 7 canonical doc paths |
| 3b | `.claude/workflows/packages/workflow-steps.yaml` | Add `Documentation/` prefix to canonical doc references |

Gate: For each updated path, `ls Documentation/<filename>` resolves.

### Phase 4: README_LAYER2 Alignment (doc risk — collaborator-facing)

| Step | File | Change |
|---|---|---|
| 4a | `Documentation/README_LAYER2.md` | Revert `--date` → `--clock-date`, `--db-path` → `--db` |
| 4b | `Documentation/README_LAYER2.md` | Remove or correct `--list` version field claims |

Gate: Grep README_LAYER2 for standalone `--date ` and `--db-path` — zero matches expected.

### Phase 5: Code Fixes (low functional risk)

| Step | File | Change |
|---|---|---|
| 5a | `layer2/adapters/snapshot_publisher.py` | Add `engine_version, config_version` to `_list_snapshots()` SELECT and print |
| 5b | `layer2/adapters/gold_adapter.py` | Migrate imports: `v0.db` → `layer2.db`, `v0.clock` → `layer2.clock` |
| 5c | `layer2/adapters/fred_loader.py` | Same migration |
| 5d | `layer2/adapters/gld_holdings_adapter.py` | Same migration |
| 5e | `layer2/adapters/move_adapter.py` | Same migration |

Gate for 5a: Run `python layer2/adapters/snapshot_publisher.py --list` — confirm version fields appear.
Gate for 5b–5e: Run each adapter's dry-run mode to confirm no import errors.

### Phase 6: Boundary Classification (requires decision, then docs-only)

| Step | File | Change |
|---|---|---|
| 6a | `Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Add canonical boundary classification for `index_suite.py` |
| 6b | `Documentation/SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Add matching architectural statement |

Gate: Both documents contain a sentence explicitly classifying `index_suite.py` as either Layer-2 pre-snapshot or post-snapshot.

### Phase 7: Stub Cleanup (zero functional risk)

| Step | File | Change |
|---|---|---|
| 7a | `.claude/hooks/auto-format.sh` | Delete |
| 7b | `.claude/hooks/run-tests.sh` | Delete |
| 7c | `.claude/hooks/security-scan.sh` | Delete |

Gate: `ls .claude/hooks/*.sh` returns no results.

### Phase 8: Artifact Bootstrap Tooling (new capability)

| Step | File | Change |
|---|---|---|
| 8a | `.claude/run/bootstrap_artifacts.py` | Implement pre-commit artifact population script |

Gate: Running the script produces all required Layers A and E artifacts in `.claude/run/artifacts/`. Pre-PR gate can pass without full manual session.

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
| R-7 (NEW) | Adapter import migration breaks ingestion pipeline | Low | HIGH | Test each adapter with `--dry-run` after migration; v0/ modules provide identical interface to canonical |
| R-8 (NEW) | `index_suite.py` boundary classification triggers snapshot contract audit | Medium | MEDIUM | Classification is a docs-only change; any audit finding is discovery, not regression |
| R-9 (NEW) | Bootstrap artifact script produces stale/incorrect artifacts | Medium | HIGH | Pin artifacts to session context; add `session_id` and `produced_by` fields |

---

## L. Verification Plan

### Per-Phase Verification

| Phase | Verification Method | Pass Criteria |
|---|---|---|
| 1 | `grep -n "as_of" CLAUDE.md` | No snapshot-level `as_of` references remain |
| 1 | Read CLAUDE.md §3.2 | DecisionPacket schema/generator distinction is clear |
| 2 | Read DAG Runner doc | Shell-mode caveat is prominent and unambiguous |
| 3 | `ls Documentation/README_v1.md` (etc.) for each path | All 7 paths resolve |
| 4 | `grep -w "\-\-date" Documentation/README_LAYER2.md` | Zero standalone `--date` matches |
| 4 | `grep "\-\-db-path" Documentation/README_LAYER2.md` | Zero matches |
| 5a | `python layer2/adapters/snapshot_publisher.py --list --db <test-db>` | Output includes `engine_version` and `config_version` |
| 5b–5e | Run each adapter `--dry-run` or `--staleness-check-only` | No import errors; behavior unchanged |
| 6 | Read both canonical docs for `index_suite.py` | Clear one-sentence boundary classification present |
| 7 | `ls .claude/hooks/*.sh` | No results |
| 7 | `grep "\.sh" .claude/settings.json` | No shell script hook references |
| 8 | Run bootstrap script; check `.claude/run/artifacts/` | 19 artifacts present with valid envelopes |

### Cross-Cutting Verification

| Check | Method | Pass Criteria |
|---|---|---|
| No new drift introduced | Re-run audit C-1 through C-9 checks | All resolved |
| DAG runner still works | `python -m governance.dag_runner.cli --write-state` | Exits 0; produces valid `governance_run_state.json` |
| Tests pass | `python -m pytest tests/governance/` | All green |
| Hook enforcement intact | Trigger a test Edit and confirm hooks fire | Python hooks produce verdicts; no `.sh` errors |
| Pre-PR gate passable | After Phase 8: run pre-commit hook against a test session | Gate passes with all 19 artifacts populated |

---

## M. Prioritized Backlog

### P0 — Must Fix Before Merge

| Item | Issue ID | Reason |
|---|---|---|
| CLAUDE.md `as_of` → `clock_ts` | DRIFT-FIELD-001 | Constitutional field-naming error; highest interpretive authority is wrong |
| README_LAYER2 CLI flag revert | DRIFT-CLI-001 | Collaborators following docs get immediate errors |
| DAG Runner shell-mode caveat | DRIFT-VERDICT-001 (doc part) | "Ready" verdict actively misleads without caveat |
| `index_suite.py` boundary classification | NEW-BOUNDARY-001 | Unresolved snapshot-contract risk; required before any further Layer-2.5/3 work |

### P1 — Should Fix Before Merge

| Item | Issue ID | Reason |
|---|---|---|
| Four-adapter import migration | NEW-IMPORT-001 | Eliminates docstring-vs-import inconsistency; removes silent divergence risk |
| CLAUDE.md DecisionPacket clarification | D.5 | Prevents schema/generator confusion |
| YAML path prefix corrections | DRIFT-PATH-001 | Future-proofs against tooling path resolution |
| README_LAYER2 snapshot listing correction | DRIFT-LIST-001 (doc side) | Doc overclaims fields not shown |
| `_list_snapshots()` code fix | DRIFT-LIST-001 (code side) | Makes version-lock visible in listings |
| Delete empty shell stubs | D.1 | Removes misleading filesystem state |

### P2 — Can Defer

| Item | Issue ID | Reason |
|---|---|---|
| Artifact bootstrap script | NEW-ARTIFACT-001 | Enables pre-PR gate; not blocking for doc-only merge |
| `execution_mode` field in StoredRunState | DRIFT-VERDICT-001 (code part) | Machine-readable improvement; not blocking |
| CLAUDE.md three-input reference | G-12 | Compression, not drift; canonical docs cover it |
| Artifact timestamp documentation | DRIFT-TIMESTAMP-001 | Informational; no user impact |
| `v0/` directory removal | NEW-IMPORT-001 followup | After adapter migration is complete and verified |

---

## N. Final Verdict

> **Partially aligned — multiple material drifts and three new structural gaps confirmed.**

### The three truths that need to converge

**The code** tells one truth: Layer-2 engine is sound, fail-closed, and version-locked. Four adapters import from v0/ (a functional duplicate of canonical modules). `index_suite.py` reads observations directly.

**The documentation** tells a slightly different truth: README_LAYER2 claims flags were renamed (they weren't) and lists fields that don't appear in `--list` output. CLAUDE.md names a snapshot field (`as_of`) that doesn't exist.

**The governance layer** tells a structurally valid but semantically incomplete truth: hooks are wired and functional, but 16 of 19 required artifacts are absent, and the DAG runner's "ready" verdict reflects spec validation, not governance completeness.

### Merge readiness

The repository should not be treated as fully self-consistent until at minimum the P0 items are resolved:
- CLAUDE.md constitutional field-naming error corrected
- README_LAYER2 CLI false-rename claims reverted
- DAG Runner "ready" caveat documented
- `index_suite.py` boundary position canonically classified

None of these affect runtime correctness of the Layer-2 engine itself. All affect documentation accuracy, governance signal reliability, and architectural interpretive authority.

**Commit strategy:** One commit per phase (Phases 1–8), each with a clear scope. Selective revert is possible per phase.

Suggested commit messages:
```
claude-md: fix as_of field name and DecisionPacket ambiguity
governance: add shell-mode verdict caveat to DAG runner docs
workflows: add Documentation/ prefix to canonical doc paths
readme-layer2: revert false CLI rename claims and listing overclaims
snapshot-publisher: add version fields to --list output
adapters: migrate gold/fred/gld/move imports to canonical layer2.db+clock
docs: classify index_suite.py boundary position in implementation record
hooks: remove empty shell script stubs
run: implement artifact bootstrap script for pre-PR gate
```

---

*End of consolidated report.*  
*Sources: REPOSITORY_CONSISTENCY_AUDIT_REPORT.md (2026-04-11), REPOSITORY_REFACTOR_PLAN.md (2026-04-11), second-pass verification (2026-04-18).*
