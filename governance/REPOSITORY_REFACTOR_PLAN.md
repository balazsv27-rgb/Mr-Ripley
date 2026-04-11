# REPOSITORY REFACTOR PLAN

**Date:** 2026-04-11
**Source:** `REPOSITORY_CONSISTENCY_AUDIT_REPORT.md` (Sections C, G)
**Branch:** `docs-final`
**Scope:** Documentation-code alignment, governance semantics, path corrections, stub cleanup

---

## 1. Refactor Strategy

### Governing Principles

1. **Docs-only fix when code is already coherent and safe.** The Layer-2 engine is verified correct — do not touch runtime code unless it materially improves truthfulness.
2. **Never overstate governance enforcement.** Shell-mode DAG readiness is structural validation, not semantic governance.
3. **Never merge target-state claims into current-state claims.** DecisionPacket schema (frozen) ≠ DecisionPacket generator (exists).
4. **Smallest correct edit wins.** Each fix should be the minimum change that eliminates the drift.
5. **Code fix only for C-2 (snapshot listing).** Adding two columns to a SELECT is low-risk and materially improves version-locking visibility — the columns already exist in the table.

### Fix Type Summary

| Issue ID | Fix Type | Rationale |
|---|---|---|
| C-1 (CLI flags) | Docs-only | Code is coherent; rename never happened; revert docs |
| C-2 (snapshot listing) | Code fix | Trivial SELECT addition; columns exist; improves truthfulness |
| C-3 (as_of vs clock_ts) | Docs-only | Constitutional field name error; code is correct |
| C-4 (YAML paths) | Docs-only | Add `Documentation/` prefix to metadata paths |
| C-5 (ready semantics) | Docs + optional code | Document the caveat; optionally add `execution_mode` field |
| C-6 (timestamps) | No fix | Low severity; informational only; artifact timestamps are hook-produced by design |
| D.1 (empty shell stubs) | Delete | Remove misleading 0-byte files |
| D.5 (DecisionPacket) | Docs-only | Clarify schema vs generator distinction in CLAUDE.md |

---

## 2. Issue-by-Issue Remediation Plan

### ISSUE-1: README_LAYER2 CLI Flag Drift (C-1 / DRIFT-CLI-001)

**Severity:** HIGH
**Decision:** Revert docs to match code. Do NOT rename code flags.

**Rationale:** `--clock-date` and `--db` are used by both `snapshot_publisher.py` and `quality_gate.py`. Renaming code flags is a multi-file change with test implications. The docs claimed a rename that never occurred — revert the claim.

**Edits:**
- `Documentation/README_LAYER2.md`: Replace all `--date` references with `--clock-date`, all `--db-path` with `--db`
- Remove the "CLI flag change (v2)" changelog entry or rewrite it as "no rename occurred; flags remain `--clock-date` and `--db`"
- Fix example commands that use `--date`

**Verification:** Grep for `--date` and `--db-path` in README_LAYER2 after edit; should find zero matches (except where `--clock-date` contains `--date` as substring — grep for standalone `--date `).

---

### ISSUE-2: Snapshot `--list` Missing Version Fields (C-2 / DRIFT-LIST-001)

**Severity:** MEDIUM
**Decision:** Fix code — add `engine_version, config_version` to `_list_snapshots()` SELECT.

**Rationale:** Both columns exist in the `snapshots` table. This is a 2-line change to the SELECT and a formatting update. It makes version-locking visible in listings, which aligns with the system's version-lock contract.

**Edits:**
- `layer2/adapters/snapshot_publisher.py`: Add `engine_version, config_version` to the SELECT in `_list_snapshots()` (~line 224) and update the print formatting to display them.

**Verification:** Run `python layer2/adapters/snapshot_publisher.py --list --db <test-db>` and confirm `engine_version` and `config_version` appear in output.

---

### ISSUE-3: CLAUDE.md `as_of` vs `clock_ts` (C-3 / DRIFT-FIELD-001)

**Severity:** HIGH
**Decision:** Docs-only fix. Change `as_of` to `clock_ts` in CLAUDE.md §6.2.

**Rationale:** This is a normative constitutional requirement. The actual snapshot time anchor is `clock_ts`. The field `as_of_ts` exists only at per-observation/per-value level. CLAUDE.md must match implementation.

**Edits:**
- `CLAUDE.md` line 215: Change `- time anchor (\`as_of\`)` to `- time anchor (\`clock_ts\`)`

**Verification:** Grep CLAUDE.md for `as_of` — should appear zero times as a snapshot-level field name.

---

### ISSUE-4: Workflow Package Path Drift (C-4 / DRIFT-PATH-001)

**Severity:** MEDIUM
**Decision:** Add `Documentation/` prefix to canonical doc paths in `artifacts.yaml` and `workflow-steps.yaml`. Leave `interpretation-policy.yaml` unchanged — it uses semantic role references, not filesystem paths.

**Rationale:** `artifacts.yaml` declares `path:` fields that should be filesystem-resolvable. If any future tooling reads these paths, they will fail without the prefix. `interpretation-policy.yaml` uses `claim_routing:` keys that are semantic identifiers, not paths — no prefix needed there.

**Edits:**
- `.claude/workflows/packages/artifacts.yaml`: Prefix 7 canonical doc paths with `Documentation/`
- `.claude/workflows/packages/workflow-steps.yaml`: Prefix canonical doc references with `Documentation/` where they appear as file paths

**Verification:** For each updated path, verify `ls Documentation/<filename>` succeeds.

---

### ISSUE-5: Governance "ready" Verdict Semantics (C-5 / DRIFT-VERDICT-001)

**Severity:** HIGH
**Decision:** Two-part fix:
1. **(Required)** Document the caveat clearly in `DAG_Runner_v1_Current_Implementation_State.md`
2. **(Optional, recommended)** Add `execution_mode: "shell_v1"` to `StoredRunState` so the limitation is machine-readable

**Rationale:** The "ready" verdict is structurally valid but semantically vacuous as a governance signal. Renaming `verdict_status` to `structural_ready` would break existing consumers and tests. Adding an explicit `execution_mode` field is additive and non-breaking.

**Required edits:**
- `governance/DAG_Runner_v1_Current_Implementation_State.md`: Add a prominent caveat section explaining that V1 "ready" means structural spec validation passed, NOT that real governance analysis was performed. List what "ready" does and does not mean.

**Optional edits (deferred to P1):**
- `governance/dag_runner/state_store.py`: Add `execution_mode: str = "shell_v1"` to `StoredRunState`
- `governance/dag_runner/executor.py`: Set `execution_mode` during run
- Update tests to expect the new field

**Verification:** Read `governance_run_state.json` and confirm caveat is documented. If code change is applied, confirm `execution_mode` appears in JSON output.

---

### ISSUE-6: Empty Shell Script Hook Stubs (D.1)

**Severity:** LOW
**Decision:** Delete all three 0-byte files.

**Rationale:** Empty files in a hooks directory imply functionality that doesn't exist. They are not referenced in `.claude/settings.json` (only Python hooks are wired). The DAG Runner doc already lists them as "not implemented" — deleting the stubs makes filesystem state match documented state.

**Edits:**
- Delete `.claude/hooks/auto-format.sh`
- Delete `.claude/hooks/run-tests.sh`
- Delete `.claude/hooks/security-scan.sh`

**Verification:** `ls .claude/hooks/*.sh` returns no results. Confirm `.claude/settings.json` has no references to these files.

---

### ISSUE-7: DecisionPacket Schema/Generator Ambiguity in CLAUDE.md (D.5)

**Severity:** MEDIUM
**Decision:** Clarify in CLAUDE.md §3.2.

**Rationale:** CLAUDE.md lists "DecisionPacket" as a monolithic planned component. Canonical docs (SYSTEM_ARCHITECTURE §7) distinguish schema (frozen 2026-03-22) from generator (not built). CLAUDE.md should reflect this distinction without overcomplicating the list.

**Edits:**
- `CLAUDE.md` §3.2: Change `- DecisionPacket` to `- DecisionPacket generator (schema frozen; generator not built)`

**Verification:** Read CLAUDE.md §3.2 and confirm the distinction is clear.

---

### ISSUE-8: CLAUDE.md Three-Input Layer Omission (G-12, optional)

**Severity:** LOW
**Decision:** Defer. Not a drift — it's a compression. The three-input model (Snapshot Truth, Live Market State, Event Risk Stream) is fully documented in SYSTEM_ARCHITECTURE §7. Adding it to CLAUDE.md is additive but not required for consistency.

**Rationale:** Adding target-architecture details to the constitutional document risks blurring the current/target boundary. CLAUDE.md §3.2 already says "planned only" and points to canonical docs. A cross-reference is acceptable but not urgent.

**Disposition:** P2 backlog item.

---

## 3. File-by-File Execution Map

| File | Issues Addressed | Edit Type | Dependencies |
|---|---|---|---|
| `CLAUDE.md` | ISSUE-3, ISSUE-7 | 2 targeted edits | None |
| `Documentation/README_LAYER2.md` | ISSUE-1 | Multi-line text replacement | None |
| `layer2/adapters/snapshot_publisher.py` | ISSUE-2 | SELECT + format change | Test verification |
| `.claude/workflows/packages/artifacts.yaml` | ISSUE-4 | Path prefix additions | Coordinate with workflow-steps.yaml |
| `.claude/workflows/packages/workflow-steps.yaml` | ISSUE-4 | Path prefix additions | Coordinate with artifacts.yaml |
| `governance/DAG_Runner_v1_Current_Implementation_State.md` | ISSUE-5 | Add caveat section | None |
| `.claude/hooks/auto-format.sh` | ISSUE-6 | Delete | None |
| `.claude/hooks/run-tests.sh` | ISSUE-6 | Delete | None |
| `.claude/hooks/security-scan.sh` | ISSUE-6 | Delete | None |

**Files NOT edited:**
- `.claude/workflows/packages/interpretation-policy.yaml` — uses semantic references, not filesystem paths; no fix needed
- `governance/dag_runner/verdict.py` — no rename of `ready`; caveat handled in docs
- `governance/dag_runner/state_store.py` — `execution_mode` deferred to P1
- `governance/dag_runner/executor.py` — deferred with state_store.py

---

## 4. Phased Refactor Order

### Phase 1: Constitutional Corrections (zero functional risk)

**Goal:** Fix normative errors in the project constitution.

| Step | File | Change | Risk |
|---|---|---|---|
| 1a | `CLAUDE.md` | `as_of` → `clock_ts` in §6.2 | None — wording only |
| 1b | `CLAUDE.md` | Clarify DecisionPacket schema vs generator in §3.2 | None — wording only |

**Gate:** Grep CLAUDE.md for `as_of` snapshot references and `DecisionPacket` — confirm corrections.

### Phase 2: Governance Documentation (zero functional risk)

**Goal:** Eliminate misleading readiness semantics.

| Step | File | Change | Risk |
|---|---|---|---|
| 2a | `governance/DAG_Runner_v1_Current_Implementation_State.md` | Add shell-mode verdict caveat | None — additive doc |

**Gate:** Read the caveat section and confirm it clearly distinguishes structural-ready from governance-ready.

### Phase 3: Path Corrections (zero functional risk)

**Goal:** Make YAML metadata paths filesystem-accurate.

| Step | File | Change | Risk |
|---|---|---|---|
| 3a | `.claude/workflows/packages/artifacts.yaml` | Add `Documentation/` prefix to 7 doc paths | None — metadata only |
| 3b | `.claude/workflows/packages/workflow-steps.yaml` | Add `Documentation/` prefix to doc references | None — metadata only |

**Gate:** For each path, `ls` the full path to confirm it resolves.

### Phase 4: README_LAYER2 Alignment (doc risk — collaborator-facing)

**Goal:** Eliminate CLI and listing overclaims.

| Step | File | Change | Risk |
|---|---|---|---|
| 4a | `Documentation/README_LAYER2.md` | Revert `--date` → `--clock-date`, `--db-path` → `--db` | Low — reverting to true state |
| 4b | `Documentation/README_LAYER2.md` | Remove or correct `--list` version field claims | Low — aligning with code |

**Gate:** Grep README_LAYER2 for `--date ` (standalone), `--db-path` — zero matches expected.

### Phase 5: Code Fix (low functional risk)

**Goal:** Add version fields to snapshot listing.

| Step | File | Change | Risk |
|---|---|---|---|
| 5a | `layer2/adapters/snapshot_publisher.py` | Add `engine_version, config_version` to `_list_snapshots()` SELECT and print | Low — additive columns |

**Gate:** Run `python layer2/adapters/snapshot_publisher.py --list` against a test database.

### Phase 6: Stub Cleanup (zero functional risk)

**Goal:** Remove misleading empty files.

| Step | File | Change | Risk |
|---|---|---|---|
| 6a | `.claude/hooks/auto-format.sh` | Delete | None |
| 6b | `.claude/hooks/run-tests.sh` | Delete | None |
| 6c | `.claude/hooks/security-scan.sh` | Delete | None |

**Gate:** Confirm no references in `.claude/settings.json`.

---

## 5. Risk Register

| Risk ID | Description | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | README_LAYER2 CLI revert misses an occurrence | Medium | HIGH — users still get errors | Grep-based verification; search for `--date ` and `--db-path` post-edit |
| R-2 | `_list_snapshots()` format change breaks existing scripts consuming output | Low | MEDIUM — no known consumers beyond manual use | Review print format; keep backward-compatible column ordering |
| R-3 | YAML path prefix breaks DAG runner loader | Very Low | MEDIUM — DAG runner won't load | DAG runner loader resolves package paths, not doc metadata paths; these are declarative only |
| R-4 | Deleting shell stubs breaks a hook wiring | Very Low | LOW — stubs are 0 bytes and unwired | Confirm `.claude/settings.json` has no `.sh` references |
| R-5 | CLAUDE.md `clock_ts` change triggers downstream interpretation drift | Very Low | MEDIUM — agents may cache old field name | This corrects a factual error; caching the wrong name is worse |
| R-6 | Phase 5 code change introduces regression in snapshot publishing | Low | HIGH — affects core Layer-2 output | `_list_snapshots()` is read-only display; does not affect `_publish_snapshot()` |

---

## 6. Verification Plan

### Per-Phase Verification

| Phase | Verification Method | Pass Criteria |
|---|---|---|
| 1 | `grep -n "as_of" CLAUDE.md` | No snapshot-level `as_of` references remain |
| 1 | Read CLAUDE.md §3.2 | DecisionPacket schema/generator distinction is clear |
| 2 | Read DAG Runner doc | Shell-mode caveat is prominent and unambiguous |
| 3 | `ls Documentation/README_v1.md` (etc.) for each path | All 7 paths resolve |
| 4 | `grep -w "\-\-date" Documentation/README_LAYER2.md` | Zero standalone `--date` matches |
| 4 | `grep "\-\-db-path" Documentation/README_LAYER2.md` | Zero matches |
| 5 | `python layer2/adapters/snapshot_publisher.py --list --db <test-db>` | Output includes `engine_version` and `config_version` columns |
| 6 | `ls .claude/hooks/*.sh` | No results |
| 6 | `grep "\.sh" .claude/settings.json` | No shell script hook references |

### Cross-Cutting Verification

| Check | Method | Pass Criteria |
|---|---|---|
| No new drift introduced | Re-run audit Section C checks | All C-1 through C-5 resolved |
| DAG runner still works | `python -m governance.dag_runner.cli --write-state` | Exits 0; produces valid `governance_run_state.json` |
| Tests pass | `python -m pytest tests/governance/` | All green |
| Hook enforcement intact | Trigger a test edit and confirm hooks fire | Python hooks produce verdicts; no `.sh` errors |

---

## 7. Prioritized Backlog

### P0 — Must Fix Before Merge

| Item | Issue | Reason |
|---|---|---|
| CLAUDE.md `as_of` → `clock_ts` | ISSUE-3 | Constitutional field-naming error; highest interpretive authority is wrong |
| README_LAYER2 CLI flag revert | ISSUE-1 | Collaborators following docs get immediate errors |
| DAG Runner shell-mode caveat | ISSUE-5 (doc part) | "Ready" verdict is actively misleading without caveat |

### P1 — Should Fix Before Merge

| Item | Issue | Reason |
|---|---|---|
| CLAUDE.md DecisionPacket clarification | ISSUE-7 | Prevents schema/generator confusion |
| YAML path prefix corrections | ISSUE-4 | Future-proofing; prevents tooling breakage |
| README_LAYER2 snapshot listing correction | ISSUE-2 (doc side) | Doc overclaims fields not shown |
| `_list_snapshots()` code fix | ISSUE-2 (code side) | Makes version-lock visible in listings |
| Delete empty shell stubs | ISSUE-6 | Removes misleading filesystem state |

### P2 — Can Defer

| Item | Issue | Reason |
|---|---|---|
| `execution_mode` field in StoredRunState | ISSUE-5 (code part) | Machine-readable improvement; not blocking |
| CLAUDE.md three-input reference | ISSUE-8 | Compression, not drift; canonical docs cover it |
| Artifact timestamp documentation | C-6 | Informational; no user impact |

---

## 8. Final Recommendation

**Execute Phases 1-6 in order on the `docs-final` branch.**

All P0 and P1 items should be completed before merging to `main`. The total change set is:
- 2 edits to `CLAUDE.md` (wording only)
- 1 additive section in `DAG_Runner_v1_Current_Implementation_State.md`
- 2 YAML path corrections (metadata only)
- Multi-line text replacement in `README_LAYER2.md` (reverting false claims)
- 1 SELECT + format change in `snapshot_publisher.py` (additive, read-only path)
- 3 file deletions (empty stubs)

**Estimated blast radius:** Minimal. No runtime behavior changes except the additive `--list` output. All other changes are documentation and metadata corrections.

**Commit strategy:** One commit per phase (6 commits), each with a clear scope. This allows selective revert if any phase introduces unexpected issues.

Suggested commit messages:
1. `claude-md: fix as_of field name and DecisionPacket ambiguity`
2. `governance: add shell-mode verdict caveat to DAG runner docs`
3. `workflows: add Documentation/ prefix to canonical doc paths`
4. `readme-layer2: revert false CLI rename claims and listing overclaims`
5. `snapshot-publisher: add version fields to --list output`
6. `hooks: remove empty shell script stubs`

---

*End of refactor plan.*
