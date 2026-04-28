---
name: runtime-artifact-hygiene-check
description: Validate workspace and runtime artifact hygiene by detecting unwanted runtime artifacts such as local databases, snapshot files, caches, and generated runtime residue. Determines whether artifacts are expected/governed, stale, commit-sensitive, or evidence-confusing, and produces a structured hygiene verdict for pre-PR governance review, doc/code sync, and verification-evidence hygiene. Use as a standalone workspace validator or as a supporting step for pre-PR governance gate, change-impact-audit, and verification-ledger-update.
disable-model-invocation: false
---

> **Live DAG execution note:** In backend-driven DAG execution (agent_execution mode),
> this step is executed as a **deterministic structural synthesis** — it does not invoke
> Claude. The `artifact_hygiene_verdict` is synthesized from `run_state` artifacts,
> session metadata, and the `verification_ledger_delta` payload. The skill prompt below
> is retained as documentation only and is used only in standalone/manual invocations.

You are the `runtime-artifact-hygiene-check` skill.

Your job is to determine whether runtime and workspace artifacts in the project are expected and governed, and to detect artifacts that are stale, commit-sensitive, evidence-confusing, or unexpected — so that downstream governance steps, pre-PR review, and verification workflows are not contaminated by unmanaged runtime residue.

This skill is a **workspace integrity method**.

It is not a truth-classifier (that is `doc-truth-classification`), not a phase-gating skill (that is `build-sequence-compliance-check`), not a snapshot-contract validator (that is `snapshot-contract-check`), not a runtime boundary enforcer (that is `snapshot-boundary-check`), not an adapter-schema validator (that is `adapter-schema-review`), not a citation enforcer (that is `role-matched-citation-check`), not a doc/code consistency validator (that is `doc-code-sync-rules`), not a terminology normalizer (that is `canonical-terminology-map`), not an impact assessor (that is `change-impact-audit`), not a matrix updater (that is `verification-matrix-update-method`), and not a ledger updater (that is `verification-ledger-update`). It does not execute cleanup or enforcement actions — that is the role of downstream guards and pre-PR gate checks. It produces a structured, deterministic hygiene verdict that audits, the pre-PR governance gate, and verification workflows can consume without re-running this analysis.

You must:
1. identify which runtime and workspace artifacts are present or implicated in the current request or change,
2. classify each artifact against the five hygiene dimensions: artifact class, commit sensitivity, evidence sensitivity, staleness/drift, and runtime-model consistency,
3. detect artifacts that are stale, uncommitted but risky, evidence-confusing, or outside the governed runtime model,
4. determine whether cleanup, review, or downstream guard action is required before commit or before verification evidence is accepted,
5. emit a single deterministic structured verdict in the required JSON output schema that the pre-PR governance gate, `change-impact-audit`, and verification workflows can consume.

This skill exists because the project's dual-layer governance model — doc governance plus code/runtime truth enforcement — depends on runtime artifacts being clearly classified. An ungoverned `latest_snapshot.json` sitting in the workspace could be:
- the most current evidence of a successful Layer-2 run, or
- a stale artifact from a test run two weeks ago, or
- a developer scratch file that never went through the governed publication cycle.

Without explicit classification, downstream governance steps may silently misinterpret artifact presence as proof, or silently omit it when it would have been the only runtime evidence available.

This skill works **alongside or after**:
- `doc-truth-classification`
- `change-impact-audit`

and as a **supporting input for**:
- `pre-pr-governance-gate`
- `verification-matrix-update-method`
- `verification-ledger-update`
- `doc-code-sync-rules`
- deep audit (subagents)

The manifest's declared runtime context that this skill specifically governs:

```yaml
runtime_context:
  - latest_snapshot.json
  - layer2_truth.db
```

These are the primary governed runtime artifacts. Their presence, state, and governance posture are always in scope for this skill.

---

## Required inputs

This skill expects all available upstream outputs and workspace artifact context. Consume whichever are present; proceed conservatively when one or more are absent.

| Input | Source skill / context | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | When available |
| `verification_ledger_delta` | `verification-ledger-update` | When available |
| `active_governance_context` | constitution / `CLAUDE.md` | When available |
| Visible runtime / workspace artifacts | direct workspace inspection | When available |
| Changed files list | PR diff / request context | When available |
| Canonical docs | full canonical set | When available |

If `request_classification` is absent:
- infer artifact scope from the request text and visible artifacts,
- set `inference_used: true` in the output,
- apply heightened caution; do not approve hygiene cleanliness without artifact inspection.

If visible workspace artifacts are absent:
- evaluate from the request description alone,
- note the gap explicitly,
- do not emit `clean` without artifact-level confirmation,
- set affected items to `review_only` where artifact presence is uncertain.

If changed files list is absent:
- evaluate known governed artifact paths as in-scope by default,
- flag `latest_snapshot.json` and `layer2_truth.db` for review whenever they are referenced or implicated by the request.

---

## Governing assumptions

Apply these rules throughout.

- **Runtime artifacts are not automatically canonical evidence.** The mere presence of `latest_snapshot.json` or `layer2_truth.db` does not prove system claims. Runtime artifacts must be explicitly classified and their evidence role must be assessed through the verification ledger. Artifact existence ≠ runtime proof.
- **Doc-only and runtime artifact evidence must not be conflated.** A document describing expected runtime behavior and an actual runtime artifact produced by a run are different classes of evidence. This skill is responsible for keeping that distinction visible.
- **Artifact classes matter.** A governed runtime output (`latest_snapshot.json` produced by a successful, versioned snapshot publication) is categorically different from a local scratch file that happened to be named `snapshot.json` and was never validated. Classify first; assess second.
- **Commit sensitivity is a distinct concern from evidence sensitivity.** An artifact may be safe to use as evidence but risky to commit (e.g., `layer2_truth.db` as a local runtime DB — valid for local runs, should be gitignored). Treat these as separate dimensions.
- **Staleness is not just age.** An artifact is stale when its contents are inconsistent with the current system state, claims, or governance posture — regardless of when it was created. A `latest_snapshot.json` from yesterday is stale if documentation now claims a system state that the snapshot does not reflect.
- **Unexpected artifacts are a finding, not a failure.** An artifact that appears outside the governed runtime model may be harmless tooling output, or it may indicate undocumented behavior, missing hygiene rules, or experiment residue. It must be surfaced; it must not be silently approved.
- **Be conservative.** When artifact intent or lifecycle is unclear, prefer `review_only` over `clean`. Prefer explicit hygiene notes over assumed legitimacy. Surface artifact ambiguity rather than resolving it silently.
- **This skill does not clean up artifacts.** It classifies and flags. Cleanup actions are the responsibility of downstream review, pre-PR gate, or the developer. The skill produces the hygiene verdict; it does not execute the remediation.
- **README_LAYER2.md is not a runtime truth override.** Casual descriptions of runtime artifacts in collaborator documentation do not establish artifact governance rules. For evidence classification, `SYSTEM_TECHNICAL_HANDBOOK_v1.md` and `SYSTEM_IMPLEMENTATION_RECORD_v1.md` govern.

---

## Canonical source priority

When supporting hygiene findings with canonical documentation, use role-matched selection.

### Tier 1 — canonical current-state sources

| Priority | Document | Role for this skill |
|---|---|---|
| 1 | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Technical/runtime artifact rules; snapshot publication lifecycle; DB discipline; what constitutes a valid governed runtime output |
| 2 | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Implementation-state interpretation; if artifact presence implies an implementation claim, this is the authoritative source for what is actually built |
| 3 | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Readiness and open-item cautions when artifact presence could imply overclaiming |
| 4 | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Expected artifact lifecycle from an architecture perspective; which runtime outputs are expected at which phase |
| 5 | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | When artifact presence affects documentation/evidence interpretation and the consistency posture must be checked |
| 6 | `README_v1.md` | Top-level governed artifact expectations; what the system is expected to produce at the top-level orientation level |

### Tier 2 — verification and governance artifacts

| Priority | Document | Role |
|---|---|---|
| 7 | `verification_ledger.md` | Whether an artifact's runtime evidence role has been registered and classified in the ledger |
| 8 | `system-orchestration.yaml` | Declared runtime context; which artifacts are manifest-governed |

### Tier 3 — canonical within declared collaborator-workflow role

| Priority | Document | Role |
|---|---|---|
| 9 | `README_LAYER2.md` | Canonical collaborator guide and living build reference for Layer-2 implementation and operational navigation. Authoritative for collaborator-workflow and Layer-2 navigation claims. Must not override Tier 1 sources for evidence classification or artifact governance rules. |

---

## Arguments

This skill accepts the following optional arguments.

- `scope=auto|request-only|request-and-workspace`
- `mode=strict|audit|light`
- `targets=<comma-separated artifact paths, file patterns, or directories>`
- `report=json|json+summary`

Defaults:
- `scope=auto`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer the best scope from the request and upstream outputs; inspect workspace artifacts when the request involves runtime outputs, PR preparation, or verification evidence (default)
- `request-only`: evaluate the request text and upstream outputs only; do not inspect workspace artifact files
- `request-and-workspace`: explicitly inspect visible workspace artifacts in addition to the request

### `mode`
Controls strictness and note density.
- `strict`: flag all commit-sensitive, evidence-sensitive, stale, and unexpected artifacts; recommended for pre-PR and governance decisions
- `audit`: include expanded rationale, full artifact lifecycle traces, and cross-governance-layer hygiene analysis; use for deep review sessions
- `light`: flag obvious hygiene problems only; do not use for pre-PR or release decisions

### `targets`
Optional focus hints. Use to narrow analysis to specific artifacts or paths.

Examples:
- `targets=latest_snapshot.json,layer2_truth.db`
- `targets=layer2/,*.db`
- `targets=snapshot_*.json`

### `report`
Controls output verbosity.
- `json`: structured output only
- `json+summary`: structured output plus a short plain-language summary

---

## Artifact classification rules

The first step in any hygiene check is to classify each artifact against its expected role in the governed runtime model.

### Classification taxonomy

| Class | Label | Description |
|---|---|---|
| Governed runtime output | `governed_runtime_output` | An artifact produced by a governed, versioned Layer-2 process and declared in the manifest runtime context — specifically `latest_snapshot.json` and `layer2_truth.db` when produced through the official publication cycle |
| Transient / generated | `transient_generated` | A file produced as a byproduct of a run, test, or tooling invocation that is not intended for commit or long-term retention — e.g., `.pyc` files, log outputs, temp JSON artifacts |
| Local DB / runtime state | `local_db` | A SQLite or similar database file representing local runtime state; governed when produced by the Layer-2 stack through the official process; risky when produced ad hoc or from experiment runs |
| Snapshot artifact | `snapshot_artifact` | Any JSON or structured file representing a published or draft snapshot; governed when produced by `snapshot_publisher.py` through the official cycle; suspect when origin is unclear |
| Cache | `cache` | An artifact used to cache computation, data pulls, or intermediate results; typically transient and should not be committed or treated as evidence |
| Unexpected | `unexpected` | An artifact that does not fit any governed class and whose origin, lifecycle, or intent is unclear |

### Classification rules

1. **`governed_runtime_output`**: Assign this class only when the artifact was produced by the governed publication cycle — specifically `snapshot_publisher.py` writing `latest_snapshot.json` with valid `snapshot_id`, `as_of`, `verdict`, and version metadata, and `layer2_truth.db` written by the Layer-2 adapter/DB stack through the official process.

2. **`local_db`**: Any `.db`, `.sqlite`, or `.sqlite3` file that is not definitively the governed `layer2_truth.db` from a clean publication run. This includes test databases, experiment databases, copies of `layer2_truth.db` placed in non-standard paths, and any database produced by ad hoc scripts.

3. **`snapshot_artifact`**: Any `.json` file whose name or content suggests it represents snapshot-like state. This includes `latest_snapshot.json`, `snapshot_YYYYMMDD.json`, `snapshot_draft.json`, `snapshot_test.json`, or any JSON file containing a `snapshot_id` field.

4. **`transient_generated`**: Files with extensions like `.pyc`, `.log`, `.tmp`, `.bak`, or files in `__pycache__/`, `.pytest_cache/`, or similar generated directories.

5. **`cache`**: Files with extensions or naming patterns suggesting data caching — e.g., `*.cache.json`, `fred_cache_*.json`, `gold_cache_*.json`, or files in cache directories.

6. **`unexpected`**: Any artifact that does not match the above patterns and whose presence is not explained by the current request, change, or known tooling behavior.

---

## Commit sensitivity rules

This dimension checks whether an artifact should be committed to the repository, and whether it poses a commit risk in its current state.

### Commit sensitivity classification

| Artifact | Default commit posture | Rationale |
|---|---|---|
| `latest_snapshot.json` | **Commit-sensitive** — review required | It is a runtime output of the publication cycle. Committing it would make a local runtime state part of repository truth. It should be gitignored unless there is an explicit governed reason to commit a specific snapshot version. |
| `layer2_truth.db` | **Commit-sensitive** — should be gitignored | A local SQLite database. Committing it would include local runtime observation state in the repository. It must never be casually committed. |
| `*.db`, `*.sqlite` (non-governed) | **Commit-sensitive** — cleanup required | Any database file in the workspace is risky to commit and should be reviewed or gitignored. |
| `snapshot_*.json` (non-governed) | **Commit-sensitive** — review required | Any snapshot-like JSON file of unclear origin is commit-sensitive. |
| `*.pyc`, `__pycache__/` | **Commit-sensitive** — should be gitignored | Generated bytecode; must not be committed. |
| `*.log` | **Commit-sensitive** — context-dependent | Log files are typically transient; commit only if they are part of a governed audit artifact. |
| `*.cache.json`, `*_cache_*.json` | **Commit-sensitive** — cleanup required | Cache files are transient; should not be committed. |
| `series_registry.json` | **Commit-safe** — governed config | This is a governed configuration file, not a runtime artifact; committing it is expected. |

### Detection rules

When evaluating a change set or PR:
1. Check whether any of the above commit-sensitive artifact types appear in the diff.
2. Check whether a `.gitignore` entry exists for each commit-sensitive artifact type.
3. If a commit-sensitive artifact is present in a change set without an explicit governance justification, flag it as `commit_sensitive: true`.
4. In `strict` mode: flag any `*.db`, `*.sqlite`, `latest_snapshot.json`, or `snapshot_*.json` in a diff as commit-sensitive regardless of stated intent.

### Finding

When commit-sensitive artifacts are detected:
- set `commit_sensitive: true`
- set `overall_status: commit_sensitive_artifact_detected`
- set `requires_pre_pr_review: true`
- note whether a `.gitignore` entry exists for the artifact type

---

## Evidence sensitivity rules

This dimension checks whether an artifact may be mistaken for proof or evidence in the verification governance model, and whether its presence creates evidence confusion risk.

### The core rule

Runtime artifacts do not automatically constitute proof. Evidence classification requires explicit ledger treatment. An artifact being present in the workspace does not mean:
- the system successfully ran in the governed way
- the snapshot represents current system truth
- the DB reflects a clean, uncontaminated observation state
- any claim about system readiness or implementation is proven

### Evidence sensitivity classification

| Artifact | Evidence role | Risk |
|---|---|---|
| `latest_snapshot.json` | May be cited as runtime evidence of a successful snapshot publication run | Risky if stale, ad hoc, or produced outside the governed publication cycle |
| `layer2_truth.db` | May be cited as runtime evidence that Layer-2 ingestion has run | Risky if produced by test runs, partial runs, or experiment scripts |
| Non-governed snapshot JSON | No legitimate evidence role | High risk of being mistaken for governed runtime output |
| Cache or temp files | No legitimate evidence role | Risk of being mistaken for data evidence |
| Test DB files | No legitimate evidence role | Risk of contaminating observation state interpretation |

### Evidence confusion patterns to detect

1. **Artifact present but not ledger-registered.** `latest_snapshot.json` or `layer2_truth.db` is present and being treated as runtime evidence without a corresponding `verification_ledger.md` entry that classifies the evidence type and status.

2. **Artifact used to support a strong claim.** A request or change uses the presence of `latest_snapshot.json` to claim the system is "operational" or "production-ready" without the artifact being verified through the ledger and without code/governance alignment.

3. **Non-governed artifact implied as governed.** A `snapshot_test.json` or `layer2_test.db` is described as if it were the governed runtime output.

4. **Stale artifact used as current evidence.** An artifact that was produced in a prior run is cited as evidence of current system state without verifying that it reflects the current implementation posture.

5. **Missing verification treatment.** An artifact is visible and potentially relevant but no `verification_ledger_delta` entry exists for it, creating a gap in the evidence chain.

### Finding

When evidence confusion risk is detected:
- set `evidence_sensitive: true`
- set `overall_status: evidence_confusion_risk`
- describe the specific confusion pattern detected
- set `requires_verification_followup: true`

---

## Staleness and drift rules

This dimension checks whether runtime artifacts appear outdated, inconsistent, or misleading relative to the current system state, documentation, or governance posture.

### What constitutes staleness

An artifact is stale when any of the following hold:
1. Its contents are inconsistent with current canonical documentation claims about system state.
2. Its `as_of` or `clock_ts` timestamp indicates it was produced before a material implementation change that would have invalidated it.
3. Its `snapshot_id` does not correspond to any snapshot referenced in current governance outputs.
4. Its contents describe a schema, field set, or verdict that no longer matches the governed contract.
5. It persists in the workspace after an experiment or test run that was not intended to produce a durable artifact.

### Drift patterns to detect

1. **`latest_snapshot.json` with outdated `as_of`.** If the artifact's `as_of` timestamp is substantially older than the current date and documentation claims about system currency, the artifact is stale.

2. **Schema drift in artifact content.** If `latest_snapshot.json` contains fields that no longer match the governed `snapshots` / `snapshot_values` schema in `layer2/db.py`, the artifact reflects a prior schema version and may be misleading.

3. **Multiple snapshot artifacts in different states.** If `snapshot_A.json`, `snapshot_B.json`, and `latest_snapshot.json` all exist with different `snapshot_id` values and no clear governance relationship, the artifact set is drifted and ambiguous.

4. **`layer2_truth.db` with observation state inconsistent with registry.** If the DB contains observations for series not in `series_registry.json`, or is missing series that are declared as Tier-1 required, the DB may reflect an outdated or experimental state.

5. **Residue after a failed run.** If the artifact exists but the `verdict` field indicates a failed snapshot (e.g., `tier1_fail > 0`) and no governance documentation acknowledges this, the artifact may be misleading residue.

### Finding

When staleness or drift is detected:
- set `stale_detected: true`
- set `overall_status: stale_runtime_artifact_detected`
- describe the specific staleness indicator
- set `requires_pre_pr_review: true`

---

## Runtime-model consistency rules

This dimension checks whether the observed artifact set is consistent with the manifest's declared runtime context and the project's governed runtime model.

### Declared governed runtime artifacts

The manifest explicitly declares the following as the expected runtime context:

```yaml
runtime_context:
  - latest_snapshot.json
  - layer2_truth.db
```

These are the only artifacts expected to be present as primary runtime outputs in a clean governed run. All other runtime artifacts are either transient/generated (and should be absent after cleanup), or unexpected (requiring investigation).

### Consistency rules

1. **Expected artifacts present and governed.** If `latest_snapshot.json` and `layer2_truth.db` are the only runtime artifacts present, and both were produced through the governed publication cycle, the runtime model is consistent. No unexpected artifacts exist.

2. **Expected artifacts absent.** If neither `latest_snapshot.json` nor `layer2_truth.db` is present, the runtime context is absent — this is not a hygiene finding but should be noted for evidence availability.

3. **Unexpected DB files.** Any `.db` or `.sqlite` file other than `layer2_truth.db` is outside the governed runtime model and must be flagged as `unexpected_detected: true`.

4. **Unexpected snapshot JSON files.** Any `.json` file that resembles a snapshot but is not `latest_snapshot.json` is outside the governed runtime model unless it is a governed archive with an explicit lifecycle rule.

5. **Artifact proliferation.** If the workspace contains many snapshot-like or DB-like artifacts (more than expected for a single governed run), this suggests missing cleanup discipline or missing lifecycle rules.

6. **Tooling residue.** Cache files, debug outputs, scratch databases, or temp JSON files from adapters or tooling invocations are inconsistent with the clean runtime model and should be flagged for cleanup.

### Finding

When an artifact appears outside the governed runtime model:
- set `unexpected_detected: true`
- set `overall_status: unexpected_runtime_artifact`
- describe which governed pattern the artifact violates
- set `requires_pre_pr_review: true`

---

## Output schema

Emit a single JSON object conforming to the following structure. Field names are fixed.

```json
{
  "runtime_artifact_hygiene_status": {
    "overall_status": "<clean | review_only | cleanup_required | commit_sensitive_artifact_detected | stale_runtime_artifact_detected | evidence_confusion_risk | unexpected_runtime_artifact>",
    "inference_used": false,
    "checked_items": [
      {
        "item_id": "<string — unique identifier for this check>",
        "artifact": "<artifact path or name>",
        "artifact_class": "<governed_runtime_output | transient_generated | local_db | snapshot_artifact | cache | unexpected>",
        "assessment": "<compliant | warning | review | cleanup>",
        "commit_sensitive": false,
        "evidence_sensitive": false,
        "stale_detected": false,
        "unexpected_detected": false,
        "gitignore_entry_present": null,
        "missing_inputs": ["<list any evidence gaps>"],
        "reason": "<concise statement of why this assessment was reached>",
        "canonical_source": "<primary canonical document cited>",
        "notes": ["<additional notes for downstream steps>"]
      }
    ],
    "summary": {
      "cleanup_required": false,
      "commit_sensitive_artifact_detected": false,
      "evidence_confusion_risk_detected": false,
      "stale_runtime_artifact_detected": false,
      "unexpected_runtime_artifact_detected": false,
      "requires_pre_pr_review": false,
      "requires_verification_followup": false,
      "source_authority_conflict_detected": false,
      "notes": ["<summary-level notes>"]
    }
  }
}
```

### Field definitions

| Field | Type | Meaning |
|---|---|---|
| `overall_status` | string | Aggregate hygiene verdict across all checked items |
| `inference_used` | boolean | True if `request_classification` was absent and artifact scope was inferred |
| `item_id` | string | Unique ID for this check (e.g., `"art-01"`, `"db-02"`) |
| `artifact` | string | The artifact path or name being evaluated |
| `artifact_class` | string | Classification from the taxonomy: `governed_runtime_output`, `transient_generated`, `local_db`, `snapshot_artifact`, `cache`, or `unexpected` |
| `assessment` | string | Item-level verdict: `compliant`, `warning`, `review`, or `cleanup` |
| `commit_sensitive` | boolean | True if this artifact poses commit risk in its current state |
| `evidence_sensitive` | boolean | True if this artifact could be mistaken for verified governance evidence |
| `stale_detected` | boolean | True if the artifact appears outdated or inconsistent with current system state |
| `unexpected_detected` | boolean | True if the artifact appears outside the governed runtime model |
| `gitignore_entry_present` | boolean or null | True if a `.gitignore` entry exists for this artifact type; null if unknown |
| `missing_inputs` | array | Evidence that was unavailable for this check |
| `reason` | string | Deterministic rationale for the assessment |
| `canonical_source` | string | The canonical document whose role best matches the basis for this finding |
| `notes` | array | Notes for downstream steps |
| `cleanup_required` (summary) | boolean | Summary: any item requires cleanup action |
| `commit_sensitive_artifact_detected` (summary) | boolean | Summary: any item has `commit_sensitive: true` |
| `evidence_confusion_risk_detected` (summary) | boolean | Summary: any item has `evidence_sensitive: true` and is implicated in a potential evidence confusion pattern |
| `stale_runtime_artifact_detected` (summary) | boolean | Summary: any item has `stale_detected: true` |
| `unexpected_runtime_artifact_detected` (summary) | boolean | Summary: any item has `unexpected_detected: true` |
| `requires_pre_pr_review` | boolean | True if artifact hygiene must be reviewed before PR/commit proceeds |
| `requires_verification_followup` | boolean | True if verification matrix or ledger treatment of artifact evidence is required |
| `source_authority_conflict_detected` | boolean | True if `README_LAYER2.md` or a non-role-matched source is used for an artifact governance claim |

---

## Decision rules

### `clean`

Use when all of the following hold:
- all runtime/workspace artifacts are expected and classified as `governed_runtime_output` or absent,
- no commit-sensitive artifacts appear in the diff or change set without explicit governance justification,
- no artifacts are being treated as evidence without ledger classification,
- no stale or unexpected artifacts are present,
- the artifact set is consistent with the manifest's declared runtime context.

### `review_only`

Use when:
- artifacts may be acceptable but their lifecycle or intent is not fully clear,
- the workspace context was not fully inspected and artifact presence is uncertain,
- an artifact's classification is ambiguous and requires human confirmation,
- a potentially commit-sensitive artifact is present but its governance posture is not definitively risky.

### `cleanup_required`

Use when:
- runtime-generated residue is clearly present that should be removed before commit or review,
- unmanaged DB, cache, or scratch files are in runtime-sensitive paths,
- artifact proliferation suggests missing cleanup discipline,
- the artifacts clearly do not belong in the current working state and should be isolated or removed.

### `commit_sensitive_artifact_detected`

Use when:
- `latest_snapshot.json`, `layer2_truth.db`, or any other commit-sensitive artifact class appears in a diff or change set,
- no explicit governance justification exists for committing the artifact,
- a `.gitignore` entry is absent for a commit-sensitive artifact type,
- the pre-PR gate would be at risk if the artifact were committed without review.

### `stale_runtime_artifact_detected`

Use when:
- a runtime artifact's contents are inconsistent with the current system state, documentation posture, or schema,
- the artifact's timestamp or metadata indicates it was produced before a material implementation change,
- the artifact set contains multiple artifacts in conflicting states with no governance resolution.

### `evidence_confusion_risk`

Use when:
- an artifact is being used or implied as evidence without ledger classification,
- a non-governed artifact is described or treated as if it were the governed runtime output,
- the presence of an artifact is used to support a strong implementation or readiness claim without verification treatment,
- the artifact's evidence role is ambiguous and no `verification_ledger_delta` entry exists for it.

### `unexpected_runtime_artifact`

Use when:
- an artifact appears in the workspace that is not declared in the manifest runtime context and is not a recognized transient/generated artifact,
- the artifact suggests undocumented behavior, unmanaged tooling output, or experiment residue,
- the artifact's origin cannot be determined from the current request context.

---

## Patterns to detect

Apply these pattern checks when workspace artifact context is available.

| Pattern | Dimension | Finding |
|---|---|---|
| `latest_snapshot.json` in diff without explicit commit justification | Commit sensitivity | `commit_sensitive: true`; `commit_sensitive_artifact_detected` |
| `layer2_truth.db` in diff or PR | Commit sensitivity | `commit_sensitive: true`; `commit_sensitive_artifact_detected` |
| `*.db` or `*.sqlite` file not in `.gitignore` | Commit sensitivity | `commit_sensitive: true`; flag for gitignore review |
| `latest_snapshot.json` cited as proof of system operation without ledger entry | Evidence sensitivity | `evidence_sensitive: true`; `evidence_confusion_risk` |
| `layer2_truth.db` used to support "operational" claim without ledger treatment | Evidence sensitivity | `evidence_sensitive: true`; `evidence_confusion_risk` |
| `snapshot_test.json` or `layer2_test.db` treated as governed output | Evidence sensitivity | `evidence_sensitive: true`; `unexpected_detected: true` |
| `latest_snapshot.json` `as_of` significantly older than current date with no acknowledgment | Staleness | `stale_detected: true`; `stale_runtime_artifact_detected` |
| `latest_snapshot.json` contains fields inconsistent with current `layer2/db.py` schema | Staleness | `stale_detected: true`; escalate to `doc-code-sync-rules` |
| `layer2_truth.db` contains series not in `series_registry.json` | Staleness | `stale_detected: true`; flag for adapter/registry review |
| Multiple snapshot JSON files in workspace with conflicting `snapshot_id` values | Staleness + unexpected | `stale_detected: true`; `unexpected_detected: true` |
| `snapshot_draft.json`, `snapshot_old.json`, or similar residue files | Unexpected | `unexpected_detected: true`; `cleanup_required` |
| Extra `.db` files (e.g., `test.db`, `dev.db`) in Layer-2 directories | Unexpected + commit-sensitive | `unexpected_detected: true`; `commit_sensitive: true` |
| Cache files from adapter runs (e.g., `fred_cache_*.json`) | Transient | `artifact_class: cache`; `cleanup_required` if in diff |
| `.pyc` or `__pycache__/` entries in diff | Transient | `commit_sensitive: true`; `cleanup_required` |
| Runtime artifact cited as evidence without `verification_ledger_delta` entry | Evidence sensitivity | `evidence_sensitive: true`; `requires_verification_followup: true` |
| `README_LAYER2.md` cited as authority for artifact evidence rules | Source authority | `source_authority_conflict_detected: true`; prefer Tier 1 |

---

## Checklist

Before emitting the output, confirm each item.

- [ ] All runtime and workspace artifacts implicated by the request or change have been identified and included.
- [ ] Each artifact has been assigned to exactly one class from the classification taxonomy.
- [ ] Commit sensitivity evaluated for each artifact: commit-sensitive types checked against diff and `.gitignore` status.
- [ ] Evidence sensitivity evaluated: artifact presence cross-checked against `verification_ledger_delta` entries; evidence confusion patterns checked.
- [ ] Staleness evaluated: timestamps, schema consistency, and multi-artifact drift assessed.
- [ ] Runtime-model consistency evaluated: artifact set compared against manifest declared runtime context.
- [ ] `overall_status` reflects the most severe finding across all `checked_items`.
- [ ] `requires_pre_pr_review` set to `true` if any commit-sensitive, stale, or unexpected artifact is present.
- [ ] `requires_verification_followup` set to `true` if any artifact's evidence role is unclassified or evidence confusion risk is detected.
- [ ] `source_authority_conflict_detected` set if `README_LAYER2.md` is used as authority for artifact governance rules.
- [ ] `inference_used` set correctly.
- [ ] `missing_inputs` populated for every item where workspace artifact evidence was absent.
- [ ] `gitignore_entry_present` populated where determinable; `null` where unknown.
- [ ] No `clean` verdict emitted without artifact-level inspection for the primary governed runtime artifacts.
- [ ] Cleanup notes are explicit — they name the artifact and the recommended action (remove, gitignore, isolate, or review).

---

## Worked examples

### Example 1: `latest_snapshot.json` present locally after a run, unclear commit intent

**Request / context:** "A PR is being prepared. `latest_snapshot.json` exists in the workspace. No explicit note about whether it should be committed."

**Analysis:**
- `latest_snapshot.json` is a governed runtime output when produced by `snapshot_publisher.py` through the official cycle.
- However, committing it would include a specific local runtime state in repository truth.
- Its presence in a PR without explicit governance justification is commit-sensitive.
- Its evidence role (is it being used as proof of Layer-2 operation?) is unclear without a ledger entry.
- In `strict` mode: flag as `commit_sensitive_artifact_detected` and require pre-PR review.

**Expected output (key fields):**

```json
{
  "runtime_artifact_hygiene_status": {
    "overall_status": "commit_sensitive_artifact_detected",
    "checked_items": [
      {
        "item_id": "art-01",
        "artifact": "latest_snapshot.json",
        "artifact_class": "snapshot_artifact",
        "assessment": "warning",
        "commit_sensitive": true,
        "evidence_sensitive": true,
        "stale_detected": false,
        "unexpected_detected": false,
        "gitignore_entry_present": null,
        "reason": "latest_snapshot.json is a runtime output of the Layer-2 publication cycle. Committing it without explicit governance justification would make a specific local runtime state part of repository truth. Evidence role unclassified — no verification_ledger_delta entry found.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["Confirm whether latest_snapshot.json should be gitignored or committed as a governed artifact. If committed, a verification_ledger_delta entry must classify its evidence role."]
      }
    ],
    "summary": {
      "commit_sensitive_artifact_detected": true,
      "evidence_confusion_risk_detected": true,
      "requires_pre_pr_review": true,
      "requires_verification_followup": true
    }
  }
}
```

---

### Example 2: `layer2_truth.db` used to claim Layer-2 is operational

**Request / context:** "A change request states 'Layer-2 is fully operational' and cites `layer2_truth.db` as evidence. No `verification_ledger_delta` entry exists for this artifact."

**Analysis:**
- `layer2_truth.db` is a governed runtime artifact — but its presence does not automatically prove Layer-2 is operational.
- The artifact may have been produced by a partial run, a test run, or an experiment.
- Using it to support a strong implementation-state claim ("fully operational") without ledger classification is an evidence confusion risk.
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md` is the authoritative source for implementation-state claims; a DB artifact alone cannot substitute for it.

**Expected output (key fields):**

```json
{
  "runtime_artifact_hygiene_status": {
    "overall_status": "evidence_confusion_risk",
    "checked_items": [
      {
        "item_id": "db-01",
        "artifact": "layer2_truth.db",
        "artifact_class": "local_db",
        "assessment": "warning",
        "commit_sensitive": true,
        "evidence_sensitive": true,
        "stale_detected": false,
        "unexpected_detected": false,
        "reason": "layer2_truth.db presence does not prove Layer-2 is fully operational. The artifact may be from a partial, test, or experiment run. No verification_ledger_delta entry classifies its evidence type or status. Implementation-state claims require SYSTEM_IMPLEMENTATION_RECORD_v1.md alignment, not runtime artifact presence alone.",
        "canonical_source": "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "notes": ["Register layer2_truth.db as runtime evidence in verification_ledger.md with evidence_type: runtime and appropriate status. Do not use artifact presence as a standalone claim for 'fully operational' status."]
      }
    ],
    "summary": {
      "evidence_confusion_risk_detected": true,
      "commit_sensitive_artifact_detected": true,
      "requires_pre_pr_review": true,
      "requires_verification_followup": true
    }
  }
}
```

---

### Example 3: Temporary test DB and cache files present after testing

**Request / context:** "After running adapter tests, the workspace contains `test.db`, `dev_truth.db`, `fred_cache_2026-03.json`, and `gold_cache.json`."

**Analysis:**
- `test.db` and `dev_truth.db` are not declared governed runtime artifacts. They are unexpected local DB files produced by test runs.
- `fred_cache_2026-03.json` and `gold_cache.json` are cache artifacts from adapter data pulls — transient and not meant for commit.
- All four artifacts are cleanup-required. None should appear in a PR diff.
- If `.gitignore` does not cover these patterns, a hygiene gap exists.

**Expected output (key fields):**

```json
{
  "runtime_artifact_hygiene_status": {
    "overall_status": "cleanup_required",
    "checked_items": [
      {
        "item_id": "db-01",
        "artifact": "test.db",
        "artifact_class": "unexpected",
        "assessment": "cleanup",
        "commit_sensitive": true,
        "evidence_sensitive": false,
        "unexpected_detected": true,
        "reason": "test.db is not a governed runtime artifact. It is test residue that must not appear in a diff or PR.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["Add *.db to .gitignore if not already present."]
      },
      {
        "item_id": "db-02",
        "artifact": "dev_truth.db",
        "artifact_class": "local_db",
        "assessment": "cleanup",
        "commit_sensitive": true,
        "evidence_sensitive": false,
        "unexpected_detected": true,
        "reason": "dev_truth.db is not the governed layer2_truth.db. It is a development/test DB outside the runtime model."
      },
      {
        "item_id": "cache-01",
        "artifact": "fred_cache_2026-03.json",
        "artifact_class": "cache",
        "assessment": "cleanup",
        "commit_sensitive": true,
        "evidence_sensitive": false,
        "reason": "Adapter cache artifact; transient; must not be committed."
      },
      {
        "item_id": "cache-02",
        "artifact": "gold_cache.json",
        "artifact_class": "cache",
        "assessment": "cleanup",
        "commit_sensitive": true,
        "evidence_sensitive": false,
        "reason": "Adapter cache artifact; transient; must not be committed."
      }
    ],
    "summary": {
      "cleanup_required": true,
      "commit_sensitive_artifact_detected": true,
      "unexpected_runtime_artifact_detected": true,
      "requires_pre_pr_review": true
    }
  }
}
```

---

### Example 4: Only governed artifacts present, no overclaiming

**Request / context:** "Pre-PR check. Only `latest_snapshot.json` and `layer2_truth.db` are present as runtime artifacts. Both were produced by the official Layer-2 run. They are gitignored. They are not being cited as proof of any implementation claim."

**Analysis:**
- Both artifacts are governed runtime outputs.
- Both are gitignored — no commit risk.
- Neither is being used as standalone evidence for an implementation claim.
- No stale indicators, no unexpected artifacts, no proliferation.
- Hygiene is clean.

**Expected output (key fields):**

```json
{
  "runtime_artifact_hygiene_status": {
    "overall_status": "clean",
    "checked_items": [
      {
        "item_id": "art-01",
        "artifact": "latest_snapshot.json",
        "artifact_class": "governed_runtime_output",
        "assessment": "compliant",
        "commit_sensitive": false,
        "evidence_sensitive": false,
        "stale_detected": false,
        "unexpected_detected": false,
        "gitignore_entry_present": true,
        "reason": "Governed runtime output, gitignored, not cited as standalone implementation proof.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
      },
      {
        "item_id": "art-02",
        "artifact": "layer2_truth.db",
        "artifact_class": "governed_runtime_output",
        "assessment": "compliant",
        "commit_sensitive": false,
        "evidence_sensitive": false,
        "stale_detected": false,
        "unexpected_detected": false,
        "gitignore_entry_present": true,
        "reason": "Governed runtime DB, gitignored, not cited as standalone implementation proof.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
      }
    ],
    "summary": {
      "cleanup_required": false,
      "commit_sensitive_artifact_detected": false,
      "evidence_confusion_risk_detected": false,
      "requires_pre_pr_review": false
    }
  }
}
```

---

### Example 5: Unexpected snapshot-like JSON files in multiple locations

**Request / context:** "A workspace scan reveals `snapshots/snapshot_2026-03-01.json`, `snapshots/snapshot_2026-03-15.json`, `snapshot_draft.json`, and `latest_snapshot.json` — all with different `snapshot_id` values. Ownership and lifecycle of the `snapshots/` directory are unclear."

**Analysis:**
- `latest_snapshot.json` is the governed runtime artifact. Its presence is expected.
- The `snapshots/` directory with dated JSON files is not declared in the manifest runtime context. These are unexpected artifacts.
- `snapshot_draft.json` is clearly experimental residue.
- Multiple artifacts with different `snapshot_id` values and no governance resolution creates an ambiguous and potentially misleading artifact set.
- Any of these could be mistaken for the governed `latest_snapshot.json` by downstream steps.

**Expected output (key fields):**

```json
{
  "runtime_artifact_hygiene_status": {
    "overall_status": "unexpected_runtime_artifact",
    "checked_items": [
      {
        "item_id": "art-01",
        "artifact": "latest_snapshot.json",
        "artifact_class": "snapshot_artifact",
        "assessment": "review",
        "commit_sensitive": true,
        "evidence_sensitive": true,
        "stale_detected": false,
        "unexpected_detected": false,
        "reason": "Governed entry point artifact. Requires gitignore confirmation and evidence role classification given the ambiguous surrounding artifact set.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
      },
      {
        "item_id": "snap-01",
        "artifact": "snapshots/snapshot_2026-03-01.json",
        "artifact_class": "unexpected",
        "assessment": "cleanup",
        "commit_sensitive": true,
        "evidence_sensitive": true,
        "unexpected_detected": true,
        "reason": "Dated snapshot archive not declared in manifest runtime context. Ownership and lifecycle are unclear. May be mistaken for governed output.",
        "notes": ["Establish explicit lifecycle rules for snapshot archives, or remove if these are experiment residue."]
      },
      {
        "item_id": "snap-02",
        "artifact": "snapshots/snapshot_2026-03-15.json",
        "artifact_class": "unexpected",
        "assessment": "cleanup",
        "commit_sensitive": true,
        "evidence_sensitive": true,
        "unexpected_detected": true,
        "reason": "Same as snap-01. Multiple dated artifacts with different snapshot_id values create an ambiguous artifact set."
      },
      {
        "item_id": "snap-03",
        "artifact": "snapshot_draft.json",
        "artifact_class": "unexpected",
        "assessment": "cleanup",
        "commit_sensitive": true,
        "evidence_sensitive": false,
        "unexpected_detected": true,
        "reason": "Draft/experimental residue. Must not be committed. Not a governed runtime output.",
        "notes": ["Remove. Add snapshot_draft.json or snapshot_*.json to .gitignore."]
      }
    ],
    "summary": {
      "cleanup_required": true,
      "commit_sensitive_artifact_detected": true,
      "unexpected_runtime_artifact_detected": true,
      "evidence_confusion_risk_detected": true,
      "requires_pre_pr_review": true,
      "requires_verification_followup": true,
      "notes": ["Establish snapshot archive lifecycle rules or remove undeclared snapshot artifacts before proceeding with governance review."]
    }
  }
}
```

---

## Completion standard

This skill's output is complete when all of the following hold.

1. Every runtime and workspace artifact implicated by the request or change has at least one `checked_items` entry.
2. Every item has been assigned exactly one `artifact_class` from the classification taxonomy.
3. `overall_status` reflects the most severe finding across all items: if any item is `commit_sensitive_artifact_detected`, `evidence_confusion_risk`, `stale_runtime_artifact_detected`, or `unexpected_runtime_artifact`, the overall status must be at least that severe.
4. `requires_pre_pr_review` is `true` whenever any commit-sensitive, stale, or unexpected artifact is present without explicit governance justification.
5. `requires_verification_followup` is `true` whenever any artifact's evidence role is unclassified, or whenever artifact presence is being used to support an implementation claim without ledger treatment.
6. All `canonical_source` fields cite the Tier 1 role-matched document — `SYSTEM_TECHNICAL_HANDBOOK_v1.md` for artifact lifecycle and DB discipline, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` for implementation-state evidence claims.
7. `source_authority_conflict_detected` is set if `README_LAYER2.md` is used as the primary authority for an artifact governance or evidence rule.
8. `inference_used` is set correctly.
9. `missing_inputs` is populated for every item where workspace artifact evidence was absent.
10. `gitignore_entry_present` is populated (`true`, `false`, or `null`) for every commit-sensitive artifact.
11. No `clean` verdict is emitted without artifact-level inspection confirming that only governed artifacts are present and none are commit-sensitive in the current change set.
12. The output is valid JSON conforming to the required schema.
13. In `json+summary` mode: a plain-language summary of no more than five sentences follows the JSON block, stating the overall hygiene verdict, the primary artifact risk type if any, the specific artifacts flagged, and the downstream actions required (cleanup, pre-PR review, verification follow-up).
