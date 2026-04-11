# REPOSITORY CONSISTENCY AUDIT REPORT

**Date:** 2026-04-11
**Branch:** `docs-final`
**Auditor:** Claude Opus 4.6 (automated full-repository audit)
**Scope:** All canonical documentation, governance/orchestration layer, workflow YAML/DAG, hooks/stage gates, and Layer-2 code

---

## A. Executive Summary

### Overall Health Assessment

The Mr. Ripley repository is **partially aligned with several material drifts present**.

The core Layer-2 implementation is sound: database schema, alignment logic, quality gate, snapshot publisher, registry handling, and fail-closed behavior are well-implemented and internally consistent. The governance infrastructure (DAG runner, hooks, workflow packages) is structurally complete and tested.

However, **documentation has drifted from code in specific, verifiable ways**, the **governance "ready" verdict is structurally misleading**, and **CLAUDE.md contains a normative field-naming error** that contradicts actual implementation. Several workflow components are **declared but not operationally enforced** in the way their declarations imply.

### Highest Risk Inconsistencies

1. **README_LAYER2 claims CLI flags were renamed** (`--date`, `--db-path`) but **code still uses old names** (`--clock-date`, `--db`) — users following docs will get errors
2. **Snapshot `--list` output does NOT show `engine_version` / `config_version`** despite docs claiming it does
3. **CLAUDE.md §6.2 requires `as_of` as snapshot time anchor** — actual snapshots use `clock_ts`; no top-level `as_of` field exists
4. **Governance "ready" verdict** is produced by shell-mode execution that **does not run real skill logic** — misleading as a gate-passing signal
5. **Workflow package path references** use bare filenames without `Documentation/` prefix — no resolution mechanism exists

### Does the repo overclaim?

**Yes, in three specific areas:**
- README_LAYER2 overclaims a CLI rename that hasn't occurred in code
- README_LAYER2 overclaims snapshot listing fields not present in output
- Governance artifacts overclaim "ready" when execution was shell-mode only

---

## B. Verified Truths

### B.1 Layer-2 Database Schema

- **Claim:** Three tables: `observations`, `snapshots`, `snapshot_values` with immutable INSERT OR IGNORE semantics
- **Source docs:** SYSTEM_TECHNICAL_HANDBOOK_v1.md, README_LAYER2.md
- **Source code:** `layer2/db.py` — exact CREATE TABLE statements match documented schema
- **Verdict:** VERIFIED
- **Notes:** All three tables use `INSERT OR IGNORE`. No `INSERT OR REPLACE` anywhere in codebase.

### B.2 Registry as Single Source of Truth

- **Claim:** `series_registry.json` is authoritative; no hardcoded series logic in adapters
- **Source docs:** CLAUDE.md §8, README_LAYER2.md, SYSTEM_TECHNICAL_HANDBOOK_v1.md
- **Source code:** All four adapters (`fred_loader.py`, `gold_adapter.py`, `move_adapter.py`, `gld_holdings_adapter.py`) read metadata from `get_registry()`. Zero hardcoded series lists, tier assignments, or staleness thresholds in adapter code.
- **Verdict:** VERIFIED

### B.3 Fail-Closed Behavior

- **Claim:** System defaults to no output rather than incorrect output
- **Source docs:** CLAUDE.md §7, SYSTEM_TECHNICAL_HANDBOOK_v1.md
- **Source code:** `quality_gate.py` returns FAIL if any Tier-1 series is stale/missing. `snapshot_publisher.py` blocks publication on FAIL verdict (unless `--force`). DAG runner validator returns `blocked` on any validation error.
- **Verdict:** VERIFIED

### B.4 Snapshot Immutability and Version-Locking

- **Claim:** Snapshots are immutable, version-locked by (clock_ts, engine_version, config_version) triple
- **Source docs:** CLAUDE.md §12, SYSTEM_TECHNICAL_HANDBOOK_v1.md
- **Source code:** `snapshot_publisher.py` checks `_snapshot_exists(conn, clock_ts, engine_version, config_version)` before publishing. `snapshot_id` is SHA-256 of deterministic content string including both version fields.
- **Verdict:** VERIFIED

### B.5 Point-in-Time Alignment Discipline

- **Claim:** All reads enforce `obs_ts <= clock_date` AND `as_of_ts <= clock_ts` with deterministic tie-breaking
- **Source docs:** SYSTEM_TECHNICAL_HANDBOOK_v1.md, README_LAYER2.md
- **Source code:** `alignment.py` uses single SQL query with `obs_ts <= ?` and `as_of_ts <= ?` boundaries, `ORDER BY obs_ts DESC, as_of_ts DESC, revision_seq DESC`
- **Verdict:** VERIFIED

### B.6 Phase-Gate Model

- **Claim:** Phase A complete at contract boundary; Phase B allowed, not completed; Phase C future; Phase D blocked
- **Source docs:** CLAUDE.md §4, SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md
- **Source code:** No Layer-3 directory exists. No execution logic exists. Constants.py defines ReasonCode enum for future use but no Layer-3 consumer exists.
- **Verdict:** VERIFIED

### B.7 Execution Boundary (Analysis-Only)

- **Claim:** No automated trading, signal execution, decision triggering, or order generation
- **Source docs:** CLAUDE.md §9, all canonical docs
- **Source code:** Zero trading logic, zero execution logic, zero order generation anywhere in codebase
- **Verdict:** VERIFIED

### B.8 Snapshot Contract Fields

- **Claim:** Published snapshots contain snapshot_id, engine_version, config_version, clock_ts, clock_date, verdict, guards, tier1/tier2 series, values with as_of_ts and revision_seq
- **Source docs:** README_v1.md §7, SYSTEM_IMPLEMENTATION_RECORD_v1.md
- **Source code:** `snapshot_publisher.py` `_build_snapshot_payload()` constructs all these fields
- **Verdict:** VERIFIED

### B.9 Guards Object in Snapshot

- **Claim:** Snapshot JSON contains structured `guards` object with data_ok, idempotent_ok, cooldown_ok, risk_ok, supervisor_veto
- **Source docs:** README_v1.md, SYSTEM_IMPLEMENTATION_RECORD_v1.md
- **Source code:** `constants.py` `build_guards()` function creates the guards dict; `snapshot_publisher.py` includes it in payload
- **Verdict:** VERIFIED

### B.10 DAG Runner Structural Validity

- **Claim:** DAG runner loads, validates, plans, and executes 18 workflow steps with topological ordering
- **Source docs:** `governance/DAG_Runner_v1_Current_Implementation_State.md`
- **Source code:** All 14 modules in `governance/dag_runner/` are implemented with 13 test files. CLI produces `governance_run_state.json`.
- **Verdict:** VERIFIED

### B.11 Hook Enforcement (Python Hooks)

- **Claim:** Six Python hooks enforce snapshot boundary, adapter schema, live readiness claims, role-matched docs, doc-code sync, and pre-PR gate
- **Source docs:** `.claude/workflows/packages/hooks.yaml`
- **Source code:** All six `.claude/hooks/*.py` files contain complete, functional code (250–475 lines each). All are wired in `.claude/settings.json`.
- **Verdict:** VERIFIED

---

## C. Confirmed Drift / Contradictions

### C-1: README_LAYER2 CLI Flag Rename Claim vs Code

- **ID:** DRIFT-CLI-001
- **Severity:** HIGH
- **Category:** DOC-CODE
- **Problem:** README_LAYER2.md §7 explicitly states: _"CLI flag change (v2): `--clock-date` is now `--date`. `--db` is now `--db-path`."_ and uses `--date` in example commands. However, actual code in `snapshot_publisher.py` still uses `--clock-date` (line 561) and `--db` (line 582). The rename never happened.
- **Evidence in docs:** `Documentation/README_LAYER2.md` line 412: `python layer2\adapters\snapshot_publisher.py --date 2026-03-05`; line 421: `--clock-date is now --date. --db is now --db-path`; line 723: `CLI flags --clock-date / --db inconsistent with codebase | Renamed to --date / --db-path`
- **Evidence in code:** `layer2/adapters/snapshot_publisher.py` lines 561–582: argparse defines `--clock-date` and `--db`
- **Why it matters:** Any user following README_LAYER2 examples will get unrecognized argument errors. This is a functional break for collaborator onboarding.
- **Recommended fix direction:** Either rename the code flags to match docs, or revert docs to match code. Given that quality_gate.py also uses `--clock-date`, reverting docs is simpler and less risky.
- **Files impacted:** `Documentation/README_LAYER2.md`, potentially `layer2/adapters/snapshot_publisher.py`

### C-2: Snapshot `--list` Output Missing Version Fields

- **ID:** DRIFT-LIST-001
- **Severity:** MEDIUM
- **Category:** DOC-CODE
- **Problem:** README_LAYER2 claims `--list` now shows `engine_version` and `config_version`. Code's `_list_snapshots()` function queries only: `snapshot_id, clock_ts, verdict, tier1_pass, tier1_fail, series_count, dry_run, forced, created_at` — neither `engine_version` nor `config_version` is included.
- **Evidence in docs:** README_LAYER2.md §7 states the list command shows engine_version and config_version
- **Evidence in code:** `layer2/adapters/snapshot_publisher.py` line 223: SELECT statement does not include engine_version or config_version columns
- **Why it matters:** Operators expecting version fields in listing output won't see them, undermining version-locking visibility claims.
- **Recommended fix direction:** Fix code — add `engine_version, config_version` to the `_list_snapshots()` SELECT and print format. Both columns exist in the `snapshots` table.
- **Files impacted:** `layer2/adapters/snapshot_publisher.py`

### C-3: CLAUDE.md Snapshot `as_of` Field Naming Error

- **ID:** DRIFT-FIELD-001
- **Severity:** HIGH
- **Category:** TERMINOLOGY
- **Problem:** CLAUDE.md §6.2 states each snapshot MUST have a `time anchor (as_of)`. No top-level `as_of` field exists in snapshot payloads. The actual time anchor is `clock_ts`. The field `as_of_ts` exists only at the per-observation/per-value level, not as a snapshot-level identity field.
- **Evidence in docs:** CLAUDE.md line 215: `- time anchor (\`as_of\`)`
- **Evidence in code:** `snapshot_publisher.py` builds snapshot with `clock_ts` as time anchor. No `as_of` key in snapshot JSON payload.
- **Why it matters:** This is a **normative constitutional requirement** that does not match reality. Agents or contributors reading CLAUDE.md as authoritative will look for a field that doesn't exist. It conflates observation-level `as_of_ts` with snapshot-level `clock_ts`.
- **Recommended fix direction:** Doc fix only — change CLAUDE.md §6.2 to reference `clock_ts` as the time anchor, not `as_of`.
- **Files impacted:** `CLAUDE.md`

### C-4: Workflow Package Path References Missing `Documentation/` Prefix

- **ID:** DRIFT-PATH-001
- **Severity:** MEDIUM
- **Category:** PATH
- **Problem:** All workflow YAML packages reference canonical docs with bare filenames (e.g., `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`). Actual files live at `Documentation/README_v1.md`, etc. No path aliasing or resolution mechanism exists in the DAG runner code — `loader.py` resolves package paths relative to the workflow file, but doc path references in artifacts.yaml are declarative metadata with no filesystem resolution.
- **Evidence in docs/workflow:** `artifacts.yaml` lines 7–31: `path: README_v1.md`, `path: SYSTEM_TECHNICAL_HANDBOOK_v1.md`, etc.
- **Evidence in code:** `ls Documentation/` confirms all 7 canonical docs live under `Documentation/` prefix
- **Why it matters:** If any tool or automation attempts to resolve these paths to read canonical docs, they will fail. Currently these are consumed as LLM-readable metadata (not filesystem paths), which is why it hasn't caused runtime errors — but it's an inconsistency waiting to break if the system evolves toward tool-based doc reading.
- **Recommended fix direction:** Update `artifacts.yaml` paths to include `Documentation/` prefix, or document the convention that paths in YAML packages are logical identifiers, not filesystem paths.
- **Files impacted:** `.claude/workflows/packages/artifacts.yaml`, `.claude/workflows/packages/workflow-steps.yaml`, `.claude/workflows/packages/interpretation-policy.yaml`

### C-5: Governance "ready" Verdict Semantics Are Misleading

- **ID:** DRIFT-VERDICT-001
- **Severity:** HIGH
- **Category:** READINESS / GOVERNANCE
- **Problem:** `governance_run_state.json` reports `verdict_status: "ready"` and `pr_readiness: "ready"` with 18/18 steps PASS. However, the executor runs in **V1 shell mode** which does NOT execute real skill logic — it simply records each step as PASS and materializes artifact placeholders. "Ready" means "structural spec validation passed and shell execution completed without predicate errors," NOT "real governance checks were performed and passed."
- **Evidence in docs:** `governance_run_state.json` top-level `verdict_status: "ready"`, `pr_readiness: "ready"`
- **Evidence in code:** `executor.py` — V1 shell mode records `NodeResult(status="PASS")` for every step without running actual skill code. `verdict.py` — `compute_runtime_verdict()` returns "ready" when all structural checks pass and no blocking events exist.
- **Why it matters:** A reader of `governance_run_state.json` would reasonably conclude that all 18 governance steps were actually evaluated and passed. In reality, no claim classification, no terminology normalization, no doc-code sync check, and no verification matrix update actually occurred. The "ready" verdict is **structurally valid but semantically vacuous**.
- **Recommended fix direction:** Either (a) rename the verdict to something like `structural_ready` to distinguish from `governance_ready`, or (b) add an explicit `execution_mode: "shell_v1"` field to make the limitation visible, or (c) document this in `DAG_Runner_v1_Current_Implementation_State.md` with a clear caveat.
- **Files impacted:** `governance/dag_runner/verdict.py`, `governance/dag_runner/state_store.py`, `governance/DAG_Runner_v1_Current_Implementation_State.md`

### C-6: Artifact Verdict Timestamps Inconsistent with Run State

- **ID:** DRIFT-TIMESTAMP-001
- **Severity:** LOW
- **Category:** GOVERNANCE
- **Problem:** `governance_run_state.json` records execution at `2026-03-31T14:29:02Z`. The three verdict artifacts in `.claude/run/artifacts/` are timestamped `2026-04-06T19:01:32Z` — six days later. This indicates the artifacts were produced by a separate process (likely hook execution during an edit session), not by the DAG runner execution that produced the run state.
- **Evidence:** `governance_run_state.json` timestamp vs `adapter_schema_verdict.json`, `runtime_boundary_verdict.json`, `stage_gate_report.json` timestamps
- **Why it matters:** Consumers of governance state may assume artifacts and run state are from the same execution. They are not. This creates a temporal coherence gap.
- **Recommended fix direction:** Document that artifacts may be produced independently by hooks. Consider adding a `run_id` field to artifacts for cross-referencing.
- **Files impacted:** `.claude/hooks/lib/artifact_store.py`, governance documentation

---

## D. Declared But Not Proven

### D.1 Shell Script Hooks

- **Claim:** `auto-format.sh`, `run-tests.sh`, `security-scan.sh` exist as hook implementations
- **Where declared:** `.claude/hooks/` directory
- **Why proof is insufficient:** All three files are 0 bytes (completely empty). They exist as filesystem entries but contain no logic.
- **What must be checked next:** Determine if these are intentional placeholders for future work or abandoned stubs. If the former, they should be documented as such. If the latter, they should be removed.

### D.2 Skill Enforcement via Orchestration

- **Claim:** 12 skills form the executable governance workflow steps, each producing specific artifacts
- **Where declared:** `.claude/workflows/packages/skills.yaml`, `.claude/skills/*/SKILL.md`
- **Why proof is insufficient:** Skills are SKILL.md instruction files (LLM-readable prompts). They are NOT executable code. They are invoked when Claude reads and follows their instructions during a session — but this means enforcement depends entirely on the LLM correctly following instructions every time. There is no programmatic enforcement mechanism that guarantees skill logic runs. The DAG runner's shell-mode executor does not invoke skills at all — it just marks steps as PASS.
- **What must be checked next:** Clarify the enforcement model: skills are LLM-behavioral (Claude follows instructions) not code-executed. This distinction should be documented. The DAG runner should either be extended to invoke skills or documented as structural-only.

### D.3 Subagent Escalation Pathways

- **Claim:** 8 subagents handle deep-audit escalation (cross-doc-consistency-auditor, architecture-sequence-auditor, etc.)
- **Where declared:** `.claude/workflows/packages/subagents.yaml`
- **Why proof is insufficient:** Subagents are declared with trigger conditions and audit lanes but no executable mechanism invokes them. They would need to be wired into Claude Code's agent system or a separate orchestration layer.
- **What must be checked next:** Determine if subagent invocation is manual (operator triggers) or intended to be automated. Document the actual escalation pathway.

### D.4 Blocking Condition Runtime Enforcement

- **Claim:** 12 blocking conditions halt workflow on violation
- **Where declared:** `.claude/workflows/packages/blocking-conditions.yaml`
- **Why proof is insufficient:** In V1 shell mode, the executor does not evaluate blocking conditions at runtime. It only records them if predicate evaluation fails. The conditions are structurally registered and validated, but not actively enforced during execution. Enforcement happens only through the Python hooks (which check artifacts) and through LLM behavioral compliance with skill instructions.
- **What must be checked next:** Clarify the dual enforcement model: hooks enforce a subset of conditions programmatically; the rest depend on LLM compliance.

### D.5 DecisionPacket Schema Frozen vs Implemented

- **Claim:** DecisionPacket v0 schema is frozen (2026-03-22)
- **Where declared:** SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md §7
- **Why proof is insufficient:** The schema is thoroughly documented but exists only in documentation. No code file, JSON schema, or Python dataclass implements it. "Frozen" means design-locked, not code-implemented. This is correctly scoped in the canonical docs but CLAUDE.md §3.2 lists "DecisionPacket" ambiguously among "planned components" without distinguishing schema (frozen) from generator (not built).
- **What must be checked next:** No action needed for the canonical docs (they are precise). CLAUDE.md should clarify: "DecisionPacket schema = frozen; DecisionPacket generator = not built."

### D.6 Revision Writer

- **Claim:** `revision_seq` column exists, revision system is partial
- **Where declared:** SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md, README_LAYER2.md
- **Why proof is insufficient:** The `observations` table has `revision_seq` column (default 0). However, no revision writer exists — there is no code path to write `revision_seq > 0`. The system is correctly documented as partial, but the actual gap (no writer) should be tracked.
- **What must be checked next:** Confirm this is tracked as a known limitation. It is — SYSTEM_LIMITATIONS §3 lists it.

---

## E. Authority and Role-Matching Review

### E.1 Which Doc Governs Which Claim Type

The role-matching table in `.claude/workflows/packages/interpretation-policy.yaml` correctly maps:

| Claim Type | Canonical Source |
|---|---|
| Architecture claims | SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md |
| Implementation claims | SYSTEM_IMPLEMENTATION_RECORD_v1.md |
| Limitation claims | SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md |
| Collaborator workflow | README_LAYER2.md |
| Documentation consistency | DOCUMENTATION_VERIFICATION_MATRIX_v1.md |
| Technical constraints | SYSTEM_TECHNICAL_HANDBOOK_v1.md |
| Top-level orientation | README_v1.md |

**Verdict:** VERIFIED — role assignments are consistent with CLAUDE.md §2.2.

### E.2 Does README_LAYER2 Overreach?

README_LAYER2 is the most detailed document and contains claims spanning multiple roles:
- **CLI commands and arguments** → appropriate (collaborator workflow)
- **Snapshot field descriptions** → appropriate (operational reference)
- **CLI flag rename claim** → **OVERREACH** — claims code was changed when it wasn't. This is an implementation-state claim that should be verified against SYSTEM_IMPLEMENTATION_RECORD_v1.md before being stated as fact.
- **Handoff gate status** → borderline — README_LAYER2 §16 describes handoff readiness. This overlaps with SYSTEM_ARCHITECTURE's §8 scope. However, it's consistent and adds collaborator context, not contradiction.

**Verdict:** PARTIALLY VERIFIED — README_LAYER2 overreaches on one specific CLI claim. Otherwise role-appropriate.

### E.3 Does CLAUDE.md Contradict or Compress Canonical Truth?

Three compression issues identified:

1. **`as_of` field naming** (C-3 above): CLAUDE.md §6.2 uses `as_of` where code uses `clock_ts`. This is a factual error, not just compression.

2. **DecisionPacket ambiguity**: CLAUDE.md §3.2 lists "DecisionPacket" among "planned only" components without distinguishing schema (frozen) from generator (not built). Canonical docs (SYSTEM_ARCHITECTURE §7) make this distinction clearly.

3. **Three-input-layer architecture omission**: CLAUDE.md makes no mention of the three governed inputs (Snapshot Truth, Live Market State, Event Risk Stream) that are canonical in SYSTEM_ARCHITECTURE §7. This means rules about those inputs cannot be enforced through CLAUDE.md alone.

**Verdict:** CLAUDE.md is mostly accurate but has one factual error (as_of) and two meaningful compressions that could cause interpretation ambiguity.

### E.4 Does the Verification Matrix Reflect Real Authority Structure?

- **Source:** `Documentation/DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
- **Verdict:** NOT FULLY VERIFIED — would require reading the full matrix content. However, the role assignments in the workflow packages are consistent with CLAUDE.md §2.2 definitions, which is the primary authority.

---

## F. Workflow / DAG / Hooks Reality Check

### F.1 Structurally Valid Workflows

| Component | Structurally Valid | Operationally Enforced |
|---|---|---|
| system-orchestration.yaml | YES | YES (loaded by DAG runner) |
| 13 workflow packages | YES | YES (merged by assembler) |
| 18 workflow steps | YES (validated, no cycles) | PARTIAL (shell-mode only) |
| Topological ordering | YES | YES |
| Validation checks (10) | YES | YES (fail-closed) |

### F.2 Hooks: Declared vs Implemented

| Hook | Declared | Implemented | Wired | Actually Blocks |
|---|---|---|---|---|
| adapter_schema_guard.py | YES | YES (462 lines) | YES | YES (exit 2) |
| snapshot_boundary_guard.py | YES | YES (380 lines) | YES | YES (exit 2) |
| live_readiness_claim_blocker.py | YES | YES (456 lines) | YES | YES (exit 2) |
| role_matched_doc_guard.py | YES | YES (255 lines) | YES | YES (conditional) |
| doc_code_sync_guard.py | YES | YES (239 lines) | YES | NO (warn only) |
| pre_pr_governance_gate.py | YES | YES (475 lines) | YES | YES (exit 2) |
| auto-format.sh | IMPLIED | NO (0 bytes) | NO | NO |
| run-tests.sh | IMPLIED | NO (0 bytes) | NO | NO |
| security-scan.sh | IMPLIED | NO (0 bytes) | NO | NO |

### F.3 Stage Gates: Real vs Declared

| Stage Gate | Declared | Enforced By |
|---|---|---|
| phase_a_layer2_closure | YES | live_readiness_claim_blocker.py (blocks forbidden claims) |
| phase_b_layer3_bootstrap | YES | live_readiness_claim_blocker.py (blocks forbidden scope) |
| phase_c_layer3_structured_buildout | YES | live_readiness_claim_blocker.py (blocks Phase C claims) |
| phase_d_live_execution_gate | YES | live_readiness_claim_blocker.py + snapshot_boundary_guard.py |

Stage gates are enforced through **pattern-matching hooks**, not through the DAG runner itself. The hooks check for forbidden textual claims in edited/written files. This is real enforcement but limited to text patterns — it cannot detect semantic violations that don't match regex patterns.

### F.4 Blocking Conditions: Actually Enforced

Of 12 declared blocking conditions:
- **6 are enforced by Python hooks** (via artifact-based gating)
- **6 depend on LLM skill execution** (no programmatic enforcement)
- **0 are enforced by the DAG runner at runtime** (shell mode)

### F.5 Runtime Artifacts Relied Upon

| Artifact | Produced By | Consumed By | Real |
|---|---|---|---|
| adapter_schema_verdict.json | adapter_schema_guard.py hook | pre_pr_governance_gate.py | YES |
| runtime_boundary_verdict.json | snapshot_boundary_guard.py hook | pre_pr_governance_gate.py | YES |
| stage_gate_report.json | live_readiness_claim_blocker.py hook | pre_pr_governance_gate.py | YES |
| governance_run_state.json | DAG runner CLI | hook_bridge.py (read-only) | YES |
| Other 15 declared artifacts | Skills (LLM behavioral) | Pre-PR gate (if produced) | PARTIAL |

### F.6 Does DAG "Ready" Mean Anything Operationally Reliable?

**No.** The "ready" verdict means:
1. YAML spec loaded without errors
2. Structural validation passed (no cycles, no orphan references)
3. Shell-mode execution completed (no predicate evaluation errors)
4. All artifact placeholders were materialized

It does **not** mean:
- Real governance analysis was performed
- Claims were classified
- Doc-code sync was checked
- Terminology was normalized
- Any skill actually ran

**"Ready" is structurally reliable but semantically vacuous as a governance gate signal.**

---

## G. File-by-File Fix Plan

### G-1: CLAUDE.md

- **Issue:** `as_of` field reference in §6.2 is incorrect
- **Change needed:** Replace `time anchor (\`as_of\`)` with `time anchor (\`clock_ts\`)`
- **Why:** Constitutional document must match actual implementation field names
- **Dependency:** None — standalone fix

### G-2: CLAUDE.md (secondary)

- **Issue:** DecisionPacket listed ambiguously in §3.2 planned components
- **Change needed:** Split into "DecisionPacket schema (frozen)" and "DecisionPacket generator (not built)" or add a clarifying note
- **Why:** Prevents misinterpretation of schema-frozen vs implementation-absent distinction
- **Dependency:** None — standalone fix

### G-3: Documentation/README_LAYER2.md (CLI flags)

- **Issue:** Claims `--clock-date` renamed to `--date` and `--db` renamed to `--db-path` (lines 412, 421, 723)
- **Change needed:** Revert documentation to use actual flag names: `--clock-date` and `--db`
- **Why:** Code has not changed; docs must match code
- **Dependency:** None — standalone fix
- **Alternative:** If renaming is desired, change code instead (but this affects `quality_gate.py` too and requires testing)

### G-4: Documentation/README_LAYER2.md (snapshot listing)

- **Issue:** Claims `--list` shows `engine_version` and `config_version`
- **Change needed:** Either (a) remove the claim from docs, or (b) fix code to include these fields in `_list_snapshots()` SELECT query
- **Why:** Current `_list_snapshots()` at line 223 does not select these columns
- **Dependency:** If fixing code, requires testing snapshot listing output

### G-5: layer2/adapters/snapshot_publisher.py (if code-fix chosen for G-4)

- **Issue:** `_list_snapshots()` SELECT missing engine_version and config_version
- **Change needed:** Add `engine_version, config_version` to SELECT and print format
- **Why:** Both columns exist in `snapshots` table; trivial addition
- **Dependency:** Must update print format to display new columns

### G-6: .claude/workflows/packages/artifacts.yaml

- **Issue:** Canonical doc paths lack `Documentation/` prefix
- **Change needed:** Update all 7 canonical doc path references from `README_v1.md` to `Documentation/README_v1.md`, etc.
- **Why:** Filesystem accuracy; prevents resolution failures if automation evolves
- **Dependency:** Also update any matching references in `workflow-steps.yaml` and `interpretation-policy.yaml`

### G-7: .claude/workflows/packages/workflow-steps.yaml

- **Issue:** Same path prefix issue for doc references
- **Change needed:** Add `Documentation/` prefix to all canonical doc references
- **Dependency:** Coordinate with G-6

### G-8: .claude/workflows/packages/interpretation-policy.yaml

- **Issue:** Same path prefix issue for claim routing table
- **Change needed:** Add `Documentation/` prefix
- **Dependency:** Coordinate with G-6 and G-7

### G-9: governance/DAG_Runner_v1_Current_Implementation_State.md

- **Issue:** Does not document that "ready" verdict is shell-mode structural only
- **Change needed:** Add explicit caveat: "V1 shell mode records all steps as PASS without executing real skill logic. The 'ready' verdict means structural spec validation passed, not that governance analysis was performed."
- **Why:** Prevents misinterpretation of readiness claims
- **Dependency:** None — standalone fix

### G-10: governance/dag_runner/state_store.py (optional)

- **Issue:** `verdict_status` field name suggests gate-passing, but is structural only
- **Change needed:** Consider adding `execution_mode: "shell_v1"` field to StoredRunState
- **Why:** Makes the limitation machine-readable
- **Dependency:** Requires updating models.py and test files

### G-11: .claude/hooks/ (empty shell scripts)

- **Issue:** `auto-format.sh`, `run-tests.sh`, `security-scan.sh` are 0-byte stubs
- **Change needed:** Either implement them or remove them with a note in hook documentation
- **Why:** Empty files in a hooks directory imply functionality that doesn't exist
- **Dependency:** None — standalone cleanup

### G-12: CLAUDE.md (optional enhancement)

- **Issue:** No mention of three governed input layers (Snapshot Truth, Live Market State, Event Risk Stream)
- **Change needed:** Add a brief reference in §3.2 or §6 pointing to SYSTEM_ARCHITECTURE §7 for the three-input model
- **Why:** Constitutional completeness — rules about these inputs currently require cross-referencing
- **Dependency:** None — additive only

---

## H. Safe Edit Order

### Phase 1: Wording-Only Corrections (No functional change)

1. **G-1:** CLAUDE.md — fix `as_of` → `clock_ts` in §6.2
2. **G-2:** CLAUDE.md — clarify DecisionPacket schema vs generator distinction
3. **G-9:** DAG_Runner_v1_Current_Implementation_State.md — add shell-mode caveat
4. **G-12:** CLAUDE.md — optional: add three-input reference

### Phase 2: Path/Reference Corrections (No functional change)

5. **G-6:** artifacts.yaml — add `Documentation/` prefix
6. **G-7:** workflow-steps.yaml — add `Documentation/` prefix
7. **G-8:** interpretation-policy.yaml — add `Documentation/` prefix

### Phase 3: Documentation-Code Alignment (Requires decision)

8. **G-3:** README_LAYER2.md — revert CLI flag names to match code (`--clock-date`, `--db`)
9. **G-4:** README_LAYER2.md — correct snapshot listing field claims
10. **G-5:** (If code-fix chosen) snapshot_publisher.py — add version fields to `_list_snapshots()`

### Phase 4: Cleanup

11. **G-11:** Remove or implement empty shell script stubs

### Phase 5: Optional Structural Improvements

12. **G-10:** state_store.py — add `execution_mode` field

### Phase 6: Final Verification

13. Run `python -m governance.dag_runner.cli --write-state` to regenerate governance state
14. Run `python -m pytest tests/governance/` to verify no regressions
15. Manually verify `python layer2/adapters/snapshot_publisher.py --list` output format
16. Grep for any remaining `as_of` references in CLAUDE.md
17. Verify all path references in updated YAML resolve to real files

---

## I. Final Verdict

> **Partially aligned, several material drifts present.**

The core Layer-2 implementation is solid and internally consistent. The governance infrastructure is structurally sound. However:

- **2 HIGH-severity documentation-code drifts** exist (CLI flags, CLAUDE.md field naming)
- **1 HIGH-severity readiness semantics issue** (governance "ready" is misleading)
- **2 MEDIUM-severity issues** (snapshot listing fields, YAML path references)
- **1 LOW-severity temporal coherence gap** (artifact timestamps)

The repository should **not** be treated as fully self-consistent until at minimum the HIGH-severity items are resolved. None of these issues affect runtime correctness of the Layer-2 engine itself — they affect documentation accuracy, governance signal reliability, and collaborator onboarding.

**The code tells one truth. The documentation tells a slightly different truth. The governance layer tells a structurally valid but semantically incomplete truth. These three truths need to converge.**

---

*End of audit report.*
