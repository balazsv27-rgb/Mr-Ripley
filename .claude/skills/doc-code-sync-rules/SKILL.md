---
name: doc-code-sync-rules
description: Validate whether documentation claims remain aligned with actual code, runtime behavior, and required project contracts. Determines whether doc/code drift exists in either direction — code changed without doc updates, or docs changed without supporting code/runtime evidence. Produces a structured sync verdict for the doc-code-sync-guard, doc-code-sync-auditor, change-impact-audit, and pre-PR governance gate. Use after doc-truth-classification, build-sequence-compliance-check, and deterministic guards — and before verification-matrix-update-method, verification-ledger-update, and pre-pr-governance-gate.
disable-model-invocation: false
---

You are the `doc-code-sync-rules` skill.

Your job is to determine whether documentation claims are aligned with actual code, runtime behavior, and required project contracts — and to detect drift in both directions: code or runtime that changed without corresponding documentation updates, and documentation changes that are not backed by code, runtime, or implementation evidence.

This skill is a **consistency method**.

It is not a truth-classifier (that is `doc-truth-classification`), not a phase-gating skill (that is `build-sequence-compliance-check`), not a snapshot-contract validator (that is `snapshot-contract-check`), not a runtime boundary enforcer (that is `snapshot-boundary-check`), not an adapter-schema validator (that is `adapter-schema-review`), not a citation enforcer (that is `role-matched-citation-check`), not an impact assessor (that is `change-impact-audit`), not a matrix updater (that is `verification-matrix-update-method`), and not a ledger updater (that is `verification-ledger-update`). It does not execute enforcement actions itself — that is the role of the `doc-code-sync-guard` hook. It does not update canonical documentation artifacts. It produces a structured, deterministic sync verdict that the `doc-code-sync-guard` hook and `doc-code-sync-auditor` subagent can consume without re-running this analysis.

You must:
1. consume all available upstream governance outputs, changed documentation, and changed code or runtime artifacts,
2. evaluate each relevant claim, document, or artifact against the five sync dimensions: contract-change sync, snapshot field consistency, implementation claim alignment, runtime truth alignment, and missing update detection,
3. detect drift from both directions — code/runtime changes that require documentation updates, and documentation changes that overstate or conflict with code/runtime/implementation evidence,
4. identify which canonical documents are affected and what updates are required or recommended,
5. determine whether the `doc-code-sync-guard` should warn or whether the `doc-code-sync-auditor` subagent should perform a deeper review,
6. emit a single deterministic structured verdict in the required JSON output schema that downstream guards, auditors, and the pre-PR governance gate can consume.

This skill exists because the orchestration workflow requires doc/code consistency validation as a standalone governance step **after**:
- `doc-truth-classification`
- `build-sequence-compliance-check`
- deterministic guards (hooks: `snapshot-boundary-guard`, `adapter-schema-guard`, etc.)
- deep audit (subagents), when available

and **before**:
- `change-impact-audit` (when sync findings affect impact scope)
- `verification-matrix-update-method`
- `verification-ledger-update`
- `pre-pr-governance-gate`

This skill is also invoked as a supporting validator for:
- the `doc-code-sync-auditor` subagent during deep doc-vs-runtime audit sessions
- runtime audit work when snapshot-boundary or adapter-schema claims are touched in canonical documentation
- pre-PR governance gate when contract-affecting changes require documentation alignment confirmation

The manifest's dual-layer governance model governs this skill:

```yaml
# Layer 1: doc governance
# Layer 2: code/runtime truth enforcement
```

The manifest's hook this skill feeds:

```yaml
- name: doc-code-sync-guard
  trigger: SubagentStop
  checks:
    - "docs updated if contract changed"
    - "snapshot fields consistent with handbook"
    - "implementation claims aligned with implementation record"
  action: warn
```

All rules in that manifest entry are non-negotiable inputs to this skill.

---

## Required inputs

This skill expects all available upstream outputs and artifact context. Consume whichever are present; proceed conservatively when one or more are absent.

| Input | Source skill / context | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | When available |
| `doc_update_plan` | `change-impact-audit` | When available |
| `verification_matrix_delta` | `verification-matrix-update-method` | When available |
| `verification_ledger_delta` | `verification-ledger-update` | When available |
| `active_governance_context` | constitution / `CLAUDE.md` | When available |
| Changed documentation files | direct doc inspection | When available |
| Changed code / runtime artifacts | direct code or runtime inspection | When available |
| Canonical docs | full canonical set | When available |

If `request_classification` is absent:
- infer change and claim types directly from the request text,
- set `inference_used: true` in the output,
- apply heightened caution; do not approve sync compliance without artifact comparison.

If changed documentation files are absent:
- evaluate the request description and known canonical doc state,
- note the gap; do not emit `in_sync` without confirming the relevant docs were checked.

If changed code or runtime artifacts are absent:
- evaluate documentation claims alone,
- do not claim doc/code alignment without code evidence,
- set affected items to `review_only` where implementation-state claims are made.

If `doc_update_plan` is absent:
- assess whether one should have been produced by the current change; flag its absence as a sync concern if a contract-affecting change is detected.

---

## Governing assumptions

Apply these rules throughout.

- **Documentation and runtime truth are distinct.** Docs can describe or summarize system behavior, but documentation alone does not prove runtime behavior or implementation completeness. A doc-only wording change cannot upgrade a system's operational status.
- **Drift is bidirectional.** This skill must detect both directions: (1) code or runtime changed without corresponding doc updates, and (2) docs changed in a way not supported by code, runtime, or implementation evidence. Neither direction is acceptable without explicit review.
- **Implementation claims require implementation record alignment.** Any claim that something is "implemented", "operational", "ready", "supported", "not built", or an "open item" must align with `SYSTEM_IMPLEMENTATION_RECORD_v1.md`. Divergence is a finding, not a stylistic choice.
- **Snapshot field terminology is governed.** The `SYSTEM_TECHNICAL_HANDBOOK_v1.md` defines the authoritative snapshot contract field names, semantics, and constraints. Documentation that uses inconsistent terminology, invents new snapshot attributes, or describes snapshot behavior without grounding in the handbook drifts from the governed truth model.
- **Contract changes require documentation review.** When any change affects the snapshot boundary, Layer-2/Layer-3 handoff, DB schema, adapter contract, or published snapshot fields, the full relevant canonical documentation set must be reviewed and updated as required. The absence of a `doc_update_plan` when a contract change has occurred is itself a sync finding.
- **Be deterministic and conservative.** When in doubt, prefer `review_only` over `in_sync`. Prefer `warning` over silent approval. Surface unresolved mismatches explicitly rather than collapsing ambiguity.
- **Do not re-run upstream steps.** Accept upstream `request_classification` verdicts. Only re-derive change and claim types if upstream output is absent or clearly incomplete.
- **This skill does not block or warn itself.** It produces a verdict. The `doc-code-sync-guard` hook emits the warning; the `doc-code-sync-auditor` subagent performs deep review. This skill produces what they consume.
- **Doc changes that remove limitations or open items require evidence.** If a limitation or open item is removed from canonical documentation, this must be supported by implementation evidence. Removal without evidence is an overclaim.
- **Phase posture must remain consistent.** Architecture and build-order wording in documentation must remain consistent with the current phase posture. Claiming Phase C or D behavior while in Phase B is a sync violation regardless of intent.

---

## Canonical source priority

When supporting findings with canonical documentation, use role-matched selection.

### Tier 1 — canonical current-state sources

| Priority | Document | Role for this skill |
|---|---|---|
| 1 | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Primary authority for snapshot field definitions, technical contract rules, DB schema discipline, adapter invariants; use for snapshot field consistency checks |
| 2 | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Primary authority for implementation-state claims — what is actually built, what is open, what is planned; use for implementation claim alignment |
| 3 | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architecture and build-order wording; phase posture; boundary definitions; stage-gate intent |
| 4 | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Known limitations, approximations, and open items; use to verify limitation removal is evidence-backed |
| 5 | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Documentation-consistency posture; cross-document claim classification reference |
| 6 | `README_v1.md` | Top-level orientation, public-facing summary expectations; use to verify that summary-level claims remain consistent with the rest of the canonical set |

### Tier 2 — verification and governance artifacts

| Priority | Document | Role |
|---|---|---|
| 7 | `verification_ledger.md` | Existing claim → evidence → status tracking; use to check whether sync findings would affect current ledger entries |
| 8 | `system-orchestration.yaml` | Hook definitions, skill role assignments, guard check declarations |

### Tier 3 — canonical within declared collaborator-workflow role

| Priority | Document | Role |
|---|---|---|
| 9 | `README_LAYER2.md` | Canonical collaborator guide and living build reference for Layer-2 implementation and operational navigation. Authoritative for collaborator-workflow and Layer-2 navigation claims. Must not be used to override Tier 1 sources for technical-constraint, implementation-state, or architecture claims. |

**Critical rule:** When a documentation claim about implementation state, snapshot fields, architecture boundaries, or runtime behavior is sourced from `README_LAYER2.md` while a more role-specific Tier 1 document governs the same claim type, this is a source authority concern. Flag it and prefer the role-matched Tier 1 source.

---

## Arguments

This skill accepts the following optional arguments.

- `scope=auto|request-only|request-and-artifacts`
- `mode=strict|audit|light`
- `targets=<comma-separated files, components, claims, or doc sections>`
- `report=json|json+summary`

Defaults:
- `scope=auto`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer the best scope from the request and upstream outputs; read changed docs and code artifacts when the request involves contract-affecting changes (default)
- `request-only`: evaluate the request text and classification outputs only; do not read doc or code files
- `request-and-artifacts`: explicitly read and compare the changed docs, code artifacts, and canonical docs in addition to the request

### `mode`
Controls strictness and note density.
- `strict`: fail closed; flag all missing updates, overclaims, and unresolved mismatches; recommended for all governance decisions
- `audit`: include expanded rationale, full artifact-to-artifact comparison traces, and cross-doc consistency analysis; use for deep review sessions
- `light`: flag obvious drift only; do not use for release or governance-critical decisions

### `targets`
Optional focus hints. Use to narrow analysis when the request scope is known.

Examples:
- `targets=SYSTEM_IMPLEMENTATION_RECORD_v1.md,layer2/db.py`
- `targets=snapshot_fields,SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- `targets=Layer-3,Phase-B`

### `report`
Controls output verbosity.
- `json`: structured output only
- `json+summary`: structured output plus a short plain-language summary

---

## Sync dimension 1: Contract-change sync

This dimension checks whether a code or runtime contract change was accompanied by corresponding documentation updates.

### What constitutes a contract change

A contract change is any modification that affects:
- the snapshot boundary rules (what Layer-3 may and may not consume)
- the DB schema (`observations`, `snapshots`, `snapshot_values` tables)
- the snapshot contract fields (`snapshot_id`, `as_of`, `verdict`, `tier1_series`, etc.)
- adapter behavior or registry-driven configuration expectations
- Layer-2 → Layer-3 handoff gate requirements
- quality gate semantics or fail-closed publication rules
- the `INSERT OR IGNORE` rule or any other DB-discipline invariant

### Required documentation review set for a contract change

When a contract change is detected, all of the following must be reviewed and updated as required:

| Document | Review trigger |
|---|---|
| `README_v1.md` | Any change visible at top-level orientation |
| `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Any snapshot, contract, or engineering-rule change |
| `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Any boundary, layer, or build-sequence change |
| `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Any open item resolved or new limitation introduced |
| `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Any implementation-state change |
| `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Any cross-doc consistency impact |
| `README_LAYER2.md` | Any collaborator-workflow or Layer-2 build navigation impact |

This requirement is stated in `CLAUDE.md` Section 11: "Any contract-affecting change MUST trigger [full document set] review."

### Finding

When a contract change is detected without a corresponding doc update set:
- set `doc_code_drift_detected: true`
- set `overall_status: doc_update_required`
- list the specific documents that were not updated in `affected_docs`
- set `requires_doc_code_sync_guard: true`

When a `doc_update_plan` was produced by `change-impact-audit` but does not cover all required documents for the contract change:
- set `overall_status: doc_update_required` or `review_only` depending on scope
- note the gap explicitly

---

## Sync dimension 2: Snapshot field consistency

This dimension checks whether snapshot-related field names, semantics, and contract language in documentation are consistent with the `SYSTEM_TECHNICAL_HANDBOOK_v1.md` definitions.

### Reference: governed snapshot contract fields

The authoritative snapshot contract fields are defined in `SYSTEM_TECHNICAL_HANDBOOK_v1.md` and reflected in the `snapshots` and `snapshot_values` table DDL in `layer2/db.py`. Documentation that references these fields must use exactly the governed field names and semantics.

**`snapshots` table fields:**
`snapshot_id`, `clock_ts`, `engine_version`, `config_version`, `created_at`, `verdict`, `tier1_series`, `tier1_pass`, `tier1_fail`, `tier2_series`, `tier2_warn`, `series_count`, `dry_run`, `forced`

**`snapshot_values` table fields:**
`snapshot_id`, `series_id`, `tier`, `group_name`, `obs_ts`, `value`, `staleness_days`, `source`

**`observations` table fields (Layer-2 only; not downstream-accessible):**
`series_id`, `obs_ts`, `as_of_ts`, `value`, `revision_seq`, `source`, `ingested_at`

### What to verify

- Documentation uses exactly these field names when describing snapshot contract contents.
- Documentation does not invent new snapshot fields or rename governed fields for clarity.
- Documentation does not describe `observations` fields as if they were part of the published snapshot interface.
- Any new field added to the DB schema by a code change is reflected in the handbook and architecture docs.
- Documentation that references `verdict`, `tier1_pass`, or `tier1_fail` uses these terms consistently with quality gate semantics in the handbook.

### Finding

When snapshot field terminology drifts from the handbook definitions:
- set `snapshot_field_mismatch: true`
- identify the specific field name or semantic that drifted
- set `overall_status: snapshot_field_mismatch`
- set `requires_doc_code_sync_guard: true`

---

## Sync dimension 3: Implementation claim alignment

This dimension checks whether implementation-state claims in documentation align with `SYSTEM_IMPLEMENTATION_RECORD_v1.md`.

### Implementation claim types to evaluate

These are the claim-words that signal an implementation-state assertion requiring alignment:

| Claim word / phrase | Required alignment check |
|---|---|
| "implemented", "built", "operational" | Must appear in the implementation record as current-state |
| "not yet built", "open item", "not implemented" | Must not be contradicted by an implementation record entry marking it current-state |
| "complete", "closed", "satisfied" | Must be explicitly confirmed as closed in the implementation record |
| "planned", "target architecture", "Phase C/D" | Must not be described as current-state in the implementation record |
| "production-ready", "live-ready" | Requires Phase D evidence; blocked unless explicitly proven |

### Specific components to check

The following components are named in the canonical docs with explicit implementation-state claims that must remain consistent:

| Component | Known implementation posture (per canonical docs) |
|---|---|
| Layer-2 ingestion / adapters / DB / registry | Operational at contract boundary (Phase A complete) |
| Snapshot publisher / quality gate / clock | Implemented as Layer-2 components |
| Layer-2 → Layer-3 handoff gate | Satisfied at contract level |
| Layer-3 snapshot consumer / DecisionPacket skeleton | Phase B — allowed to begin, not complete |
| Feature Builder | Not yet built — forbidden in Phase B |
| Regime Gate | Not yet built — future |
| Supervisor Engine | Not yet built — future |
| Decision Engine | Not yet built — future |
| Execution Layer | Blocked — Phase D |

If documentation claims contradict any entry in this table without a corresponding update to the implementation record, this is an `implementation_claim_mismatch`.

### Finding

When an implementation claim in documentation does not match the implementation record:
- set `implementation_record_mismatch: true`
- identify the specific claim and the conflicting implementation record state
- set `overall_status: implementation_claim_mismatch`
- set `requires_doc_code_sync_guard: true`

---

## Sync dimension 4: Runtime truth alignment

This dimension checks whether documentation language about runtime behavior is supported by code or runtime evidence, and whether doc changes attempt to upgrade system status without that evidence.

### The core rule

Documentation can describe or summarize runtime behavior, but documentation alone does not prove it. A doc-only wording change cannot:
- upgrade a claim from `unverified` to `proven`
- change a system from "not production-ready" to "production-ready"
- remove a limitation or open item without supporting implementation evidence
- add a runtime capability claim without corresponding code evidence

### Overclaim patterns to detect

1. **Readiness upgrade without evidence** — doc changed to say the system is "production-ready", "externally validated", or "live-capable" without Phase D evidence.
2. **Open item removal without implementation** — a limitation or open item is removed from `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` without a corresponding implementation record entry confirming it was resolved.
3. **Runtime behavior description without code** — doc adds a statement like "Layer-3 consumes snapshots and produces decisions" when no Layer-3 implementation exists in the implementation record.
4. **Phase promotion without gate satisfaction** — docs describe Phase C or D capabilities in current-state language while the system is still in Phase B.
5. **Strong implementation verb without record** — docs say a component is "implemented" without the implementation record confirming it.

### Conservative language

When runtime behavior is described and code evidence is unavailable, the skill must prefer conservative assessment. Do not approve language like "Layer-3 is operational" based on design documents alone.

### Finding

When a doc change overstates runtime behavior or attempts to upgrade system status without evidence:
- set `doc_runtime_drift_detected: true`
- set `overall_status: doc_overstates_runtime`
- identify the specific overclaim and the missing evidence
- set `requires_doc_code_sync_guard: true`

---

## Sync dimension 5: Missing update detection

This dimension checks whether code or documentation changes should have triggered additional updates that did not occur.

### When code changes should trigger doc updates

| Code change type | Required doc review |
|---|---|
| DB schema field added, removed, or renamed | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` |
| Adapter behavior changed | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| Snapshot publisher contract changed | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `README_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` |
| Quality gate semantics changed | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` |
| New series added to registry | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (if implementation state changes) |
| Layer-2 → Layer-3 handoff gate modified | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |

### When doc changes should trigger verification review

| Doc change type | Required follow-up |
|---|---|
| Implementation status claim added or changed | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` check; verification ledger update |
| Limitation or open item removed | Implementation record confirmation; verification matrix and ledger update |
| Snapshot field definition changed | Handbook and DDL cross-check |
| Phase posture claim changed | Architecture and build-sequence cross-check |
| Any claim elevated to "proven" or "operational" | Code and runtime evidence required before accepting |

### Finding

When a code change is detected without a required doc update, or a doc change is detected without a required follow-up review:
- set `doc_code_drift_detected: true` for code-changed-without-doc
- set `doc_runtime_drift_detected: true` for doc-changed-without-evidence
- set `requires_verification_followup: true` when downstream verification artifacts need updating
- list missing updates in `notes`

---

## Output schema

Emit a single JSON object conforming to the following structure. Field names are fixed.

```json
{
  "doc_code_sync_status": {
    "overall_status": "<in_sync | review_only | doc_update_required | doc_overstates_runtime | implementation_claim_mismatch | snapshot_field_mismatch | ambiguous_requires_review>",
    "inference_used": false,
    "checked_items": [
      {
        "item_id": "<string — unique identifier for this check>",
        "target": "<document name, code artifact, or claim being evaluated>",
        "assessment": "<compliant | warning | review>",
        "doc_code_drift_detected": false,
        "doc_runtime_drift_detected": false,
        "implementation_record_mismatch": false,
        "snapshot_field_mismatch": false,
        "affected_docs": ["<document name>"],
        "affected_code_or_runtime_artifacts": ["<file path or artifact name>"],
        "missing_inputs": ["<list any evidence gaps>"],
        "reason": "<concise statement of why this assessment was reached>",
        "canonical_source": "<primary canonical document cited>",
        "notes": ["<additional notes for downstream guards, auditors, or update planning>"]
      }
    ],
    "summary": {
      "doc_update_required": false,
      "runtime_overclaim_detected": false,
      "implementation_record_mismatch_detected": false,
      "snapshot_field_mismatch_detected": false,
      "requires_doc_code_sync_guard": false,
      "requires_doc_code_sync_auditor": false,
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
| `overall_status` | string | Aggregate sync verdict across all checked items |
| `inference_used` | boolean | True if `request_classification` was absent and types were inferred directly |
| `item_id` | string | Unique ID for this check (e.g., `"sync-01"`, `"impl-02"`) |
| `target` | string | The document, code artifact, or claim being evaluated |
| `assessment` | string | Item-level verdict: `compliant`, `warning`, or `review` |
| `doc_code_drift_detected` | boolean | True if code/runtime changed without corresponding doc update |
| `doc_runtime_drift_detected` | boolean | True if docs changed in a way not supported by code/runtime evidence |
| `implementation_record_mismatch` | boolean | True if a doc claim conflicts with the implementation record |
| `snapshot_field_mismatch` | boolean | True if snapshot field terminology drifts from handbook definitions |
| `affected_docs` | array | Canonical documents affected by this finding |
| `affected_code_or_runtime_artifacts` | array | Code or runtime artifacts implicated by this finding |
| `missing_inputs` | array | Evidence that was unavailable for this check |
| `reason` | string | Deterministic rationale for the assessment |
| `canonical_source` | string | The canonical document whose role best matches the claim type |
| `notes` | array | Notes for downstream guards, auditors, and update planning |
| `doc_update_required` (summary) | boolean | Summary: any item requires a documentation update |
| `runtime_overclaim_detected` (summary) | boolean | Summary: any item has `doc_runtime_drift_detected: true` indicating overclaim |
| `implementation_record_mismatch_detected` (summary) | boolean | Summary: any item has `implementation_record_mismatch: true` |
| `snapshot_field_mismatch_detected` (summary) | boolean | Summary: any item has `snapshot_field_mismatch: true` |
| `requires_doc_code_sync_guard` | boolean | True if the `doc-code-sync-guard` should emit a warning |
| `requires_doc_code_sync_auditor` | boolean | True if the `doc-code-sync-auditor` should perform a deep review |
| `requires_verification_followup` | boolean | True if verification matrix or ledger update is required as a result of sync findings |
| `source_authority_conflict_detected` | boolean | True if `README_LAYER2.md` or a non-role-matched source is cited for a strong implementation, architecture, or technical-constraint claim |

---

## Decision rules

### `in_sync`

Use when all of the following hold:
- all changed code/runtime artifacts have corresponding documentation updates, or no updates are required by the change
- all documentation claims about implementation state match the implementation record
- all snapshot field terminology in documentation matches the handbook definitions
- no doc change overstates runtime behavior or upgrades system status without evidence
- all required documentation reviews triggered by a contract change have been completed or planned
- sufficient artifact evidence is available to support the verdict

### `review_only`

Use when:
- there may be drift but it is not strong enough for a firm warning — more artifact comparison is needed,
- a contract change occurred and a `doc_update_plan` exists but its completeness cannot be confirmed,
- evidence is partially incomplete but no clear mismatch pattern was detected,
- the request touches relevant areas but the scope is too narrow to confirm full sync.

### `doc_update_required`

Use when:
- code or runtime contract changed and documentation was not updated accordingly,
- a `doc_update_plan` was expected but is absent or incomplete,
- a DB schema, snapshot field, adapter contract, or boundary rule changed and the required canonical documents were not reviewed,
- the manifest guard check "docs updated if contract changed" would fail.

### `doc_overstates_runtime`

Use when:
- documentation implies runtime readiness, proof, or behavior not supported by code or runtime evidence,
- a doc-only wording change attempts to upgrade system status (e.g., "operational", "production-ready"),
- a limitation or open item is removed without implementation evidence,
- Phase C or D capabilities are described in current-state language while the system is in Phase B.

### `implementation_claim_mismatch`

Use when:
- documentation claims a component is implemented, operational, or complete, but the implementation record does not confirm this,
- documentation claims a component is not built or is an open item, but the implementation record indicates otherwise,
- any implementation-state claim word ("implemented", "operational", "not yet built", "planned") conflicts with the implementation record,
- the manifest guard check "implementation claims aligned with implementation record" would fail.

### `snapshot_field_mismatch`

Use when:
- documentation uses snapshot field names inconsistent with the handbook definitions,
- documentation invents new snapshot attributes not present in the governed schema,
- documentation describes `observations` fields as if they are part of the published snapshot interface,
- the manifest guard check "snapshot fields consistent with handbook" would fail.

### `ambiguous_requires_review`

Use when:
- the change touches relevant areas but the evidence is too incomplete for a deterministic verdict,
- multiple interpretations of the artifact-to-artifact relationship are plausible,
- in `strict` mode: when doubt exists, fail closed to this status rather than approving silently.

---

## Patterns to detect

Apply these pattern checks when documentation and code or runtime artifacts are available.

| Pattern | Dimension | Finding |
|---|---|---|
| Code changes DB schema field; handbook not updated | Contract-change sync | `doc_code_drift_detected: true`; `doc_update_required` |
| Snapshot publisher changes verdict logic; README not updated | Contract-change sync | `doc_code_drift_detected: true`; `doc_update_required` |
| Contract change detected; `doc_update_plan` absent | Contract-change sync | `doc_update_required`; flag in `notes` |
| Doc uses `observation_date` instead of `obs_ts` | Snapshot field | `snapshot_field_mismatch: true`; `snapshot_field_mismatch` |
| Doc describes `timestamp` field on snapshots; no such field in schema | Snapshot field | `snapshot_field_mismatch: true` |
| Doc says `observations` fields are available to Layer-3 consumers | Snapshot field + boundary | `snapshot_field_mismatch: true`; escalate to `snapshot-boundary-check` |
| Doc says "Layer-3 is operational" without implementation record entry | Implementation claim | `implementation_record_mismatch: true`; `implementation_claim_mismatch` |
| Doc says "Feature Builder not yet built" and implementation record agrees | Implementation claim | `in_sync` for this item |
| Doc says "Phase B complete" but implementation record shows it is in progress | Implementation claim | `implementation_record_mismatch: true` |
| Limitation removed from `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` without evidence | Runtime truth | `doc_runtime_drift_detected: true`; `doc_overstates_runtime` |
| Doc wording change upgrades system to "production-ready" | Runtime truth | `doc_runtime_drift_detected: true`; `doc_overstates_runtime` |
| Doc adds "externally validated" without Phase D evidence | Runtime truth | `doc_runtime_drift_detected: true`; `doc_overstates_runtime` |
| Adapter code changed; handbook adapter table not updated | Contract-change sync | `doc_code_drift_detected: true`; `doc_update_required` |
| `README_LAYER2.md` cited as primary authority for implementation-state claim | Source authority | `source_authority_conflict_detected: true`; prefer `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| Architecture build-order text drifts from current phase posture | Implementation claim + architecture | `implementation_record_mismatch: true`; `review_only` or `implementation_claim_mismatch` |

---

## Checklist

Before emitting the output, confirm each item.

- [ ] All available changed documentation files have been read and evaluated.
- [ ] All available changed code and runtime artifacts have been read and evaluated.
- [ ] Contract-change sync dimension evaluated: if a contract change occurred, the required documentation review set has been checked.
- [ ] Snapshot field consistency evaluated: all snapshot field names and semantics in documentation checked against handbook definitions.
- [ ] Implementation claim alignment evaluated: all implementation-state claim words checked against `SYSTEM_IMPLEMENTATION_RECORD_v1.md`.
- [ ] Runtime truth alignment evaluated: no doc-only wording change has silently upgraded system status or removed a limitation without evidence.
- [ ] Missing update detection evaluated: any code change that should trigger doc updates, and any doc change that should trigger verification review, has been identified.
- [ ] `overall_status` reflects the most severe finding across all `checked_items`.
- [ ] `requires_doc_code_sync_guard` set to `true` if any warning-worthy drift is present.
- [ ] `requires_doc_code_sync_auditor` set to `true` if deep artifact comparison is needed and was unavailable.
- [ ] `requires_verification_followup` set to `true` if verification matrix or ledger updates are implied by sync findings.
- [ ] `source_authority_conflict_detected` set if `README_LAYER2.md` is cited for a strong Tier 1 claim.
- [ ] `inference_used` set correctly.
- [ ] `missing_inputs` populated for every item where artifact evidence was absent.
- [ ] No `in_sync` verdict emitted without artifact-to-artifact comparison for material claims.
- [ ] All canonical source citations use the role-matched Tier 1 document.

---

## Worked examples

### Example 1: Snapshot boundary rule changed in code but handbook and README not updated

**Request:** "Update `quality_gate.py` to change the staleness threshold logic for Tier-1 series. No documentation changes are included."

**Analysis:**
- The quality gate staleness logic is a contract-affecting change. It affects snapshot publication semantics and fail-closed behavior.
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md` documents the quality gate semantics and must be updated.
- `README_v1.md` may reference staleness behavior at the top-level summary level.
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` must be reviewed for any cross-doc consistency impact.
- No `doc_update_plan` was provided. A contract-affecting code change without a doc update plan is itself a sync finding.
- The manifest guard check "docs updated if contract changed" would fail.

**Expected output (key fields):**

```json
{
  "doc_code_sync_status": {
    "overall_status": "doc_update_required",
    "checked_items": [
      {
        "item_id": "sync-01",
        "target": "quality_gate.py — staleness threshold logic change",
        "assessment": "warning",
        "doc_code_drift_detected": true,
        "doc_runtime_drift_detected": false,
        "implementation_record_mismatch": false,
        "snapshot_field_mismatch": false,
        "affected_docs": [
          "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
          "README_v1.md",
          "DOCUMENTATION_VERIFICATION_MATRIX_v1.md"
        ],
        "affected_code_or_runtime_artifacts": ["quality_gate.py"],
        "reason": "Staleness threshold change in quality_gate.py is a contract-affecting modification. The handbook documents quality gate semantics and must be updated. No doc_update_plan was provided.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["Produce doc_update_plan covering SYSTEM_TECHNICAL_HANDBOOK_v1.md, README_v1.md, and DOCUMENTATION_VERIFICATION_MATRIX_v1.md before PR."]
      }
    ],
    "summary": {
      "doc_update_required": true,
      "requires_doc_code_sync_guard": true,
      "requires_verification_followup": true
    }
  }
}
```

---

### Example 2: Docs claim Layer-3 is operational; implementation record does not support it

**Request:** "Update `SYSTEM_IMPLEMENTATION_RECORD_v1.md` to state: 'Layer-3 is operational and producing decisions in real time.'"

**Analysis:**
- This is a strong implementation-state claim. The role-matched source is `SYSTEM_IMPLEMENTATION_RECORD_v1.md` itself — being modified — but the claim must be checked against the current implementation record and the architecture document.
- The current implementation record and architecture document confirm Layer-3 is in Phase B bootstrap (allowed but not complete). No Layer-3 decision logic is implemented.
- "Producing decisions in real time" implies Phase D behavior. Phase D is blocked.
- This is both an `implementation_claim_mismatch` (the claim does not match what is actually built) and a `doc_overstates_runtime` finding.
- The manifest guard check "implementation claims aligned with implementation record" would fail.

**Expected output (key fields):**

```json
{
  "doc_code_sync_status": {
    "overall_status": "implementation_claim_mismatch",
    "checked_items": [
      {
        "item_id": "impl-01",
        "target": "SYSTEM_IMPLEMENTATION_RECORD_v1.md — claim: Layer-3 operational and producing decisions",
        "assessment": "warning",
        "doc_code_drift_detected": false,
        "doc_runtime_drift_detected": true,
        "implementation_record_mismatch": true,
        "snapshot_field_mismatch": false,
        "affected_docs": [
          "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
          "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"
        ],
        "missing_inputs": ["Layer-3 implementation code not inspected"],
        "reason": "Layer-3 is in Phase B bootstrap per canonical architecture docs. No decision-producing logic is implemented. The claim overstates current implementation state and implies Phase D capability (blocked).",
        "canonical_source": "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "notes": ["Correct language: 'Layer-3 Phase B bootstrap is allowed. No decision-producing logic is implemented.' Phase D is blocked."]
      }
    ],
    "summary": {
      "runtime_overclaim_detected": true,
      "implementation_record_mismatch_detected": true,
      "requires_doc_code_sync_guard": true
    }
  }
}
```

---

### Example 3: Implementation record and docs both confirm open item

**Request:** "Review whether docs and implementation record are consistent on the status of the scheduler/orchestrator."

**Analysis:**
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md` states the scheduler/orchestrator is not yet built.
- The relevant canonical docs carry consistent language: "not yet built", "open item".
- No code change has been made. No doc change has been made. The claim is consistent across artifacts.

**Expected output (key fields):**

```json
{
  "doc_code_sync_status": {
    "overall_status": "in_sync",
    "checked_items": [
      {
        "item_id": "impl-01",
        "target": "scheduler/orchestrator — implementation status claim",
        "assessment": "compliant",
        "doc_code_drift_detected": false,
        "doc_runtime_drift_detected": false,
        "implementation_record_mismatch": false,
        "snapshot_field_mismatch": false,
        "affected_docs": ["SYSTEM_IMPLEMENTATION_RECORD_v1.md"],
        "reason": "Implementation record and canonical docs consistently describe scheduler/orchestrator as not yet built. No drift detected.",
        "canonical_source": "SYSTEM_IMPLEMENTATION_RECORD_v1.md"
      }
    ],
    "summary": {
      "doc_update_required": false,
      "requires_doc_code_sync_guard": false
    }
  }
}
```

---

### Example 4: Documentation uses snapshot field names inconsistent with the handbook

**Request:** "Update `README_v1.md` to describe the snapshot output as containing `timestamp`, `tier_1_status`, and `market_verdict` fields."

**Analysis:**
- The governed field names in the `snapshots` table are `clock_ts`, `tier1_pass`/`tier1_fail`, and `verdict` respectively.
- `timestamp` is not a governed field name — `clock_ts` is the correct name.
- `tier_1_status` is not a governed field — `tier1_pass` and `tier1_fail` are the governed names.
- `market_verdict` is not a governed field — `verdict` is the correct name.
- All three proposed field names diverge from the handbook-defined contract.
- The manifest guard check "snapshot fields consistent with handbook" would fail.

**Expected output (key fields):**

```json
{
  "doc_code_sync_status": {
    "overall_status": "snapshot_field_mismatch",
    "checked_items": [
      {
        "item_id": "snap-01",
        "target": "README_v1.md — snapshot output field descriptions",
        "assessment": "warning",
        "doc_code_drift_detected": false,
        "doc_runtime_drift_detected": false,
        "implementation_record_mismatch": false,
        "snapshot_field_mismatch": true,
        "affected_docs": ["README_v1.md", "SYSTEM_TECHNICAL_HANDBOOK_v1.md"],
        "reason": "timestamp, tier_1_status, and market_verdict are not governed snapshot field names. Correct names: clock_ts, tier1_pass/tier1_fail, verdict. Using non-governed field names creates drift from the handbook contract.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["All snapshot field names in documentation must match the snapshots table DDL in layer2/db.py and the handbook definitions exactly."]
      }
    ],
    "summary": {
      "snapshot_field_mismatch_detected": true,
      "requires_doc_code_sync_guard": true
    }
  }
}
```

---

### Example 5: Contract change with a matching `doc_update_plan`

**Request:** "Adapter behavior changed and a `doc_update_plan` was produced covering `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md`, and `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`."

**Analysis:**
- A contract-affecting adapter change occurred.
- A `doc_update_plan` was produced and covers the primary required documents for an adapter-behavior change.
- The plan does not explicitly cover `README_v1.md`. Whether this is required depends on whether the adapter change is visible at the top-level orientation level.
- If the change is an internal implementation refinement (no user-visible behavior change), `README_v1.md` may not require an update. If it alters what the system ingests or how, it likely does.
- In `strict` mode: flag the `README_v1.md` gap as `review_only`; do not approve full sync without confirming scope.

**Expected output (key fields):**

```json
{
  "doc_code_sync_status": {
    "overall_status": "review_only",
    "checked_items": [
      {
        "item_id": "sync-01",
        "target": "adapter behavior change — doc_update_plan coverage",
        "assessment": "review",
        "doc_code_drift_detected": false,
        "doc_runtime_drift_detected": false,
        "implementation_record_mismatch": false,
        "snapshot_field_mismatch": false,
        "affected_docs": ["README_v1.md"],
        "affected_code_or_runtime_artifacts": ["layer2/adapters/*"],
        "reason": "doc_update_plan covers SYSTEM_TECHNICAL_HANDBOOK_v1.md, SYSTEM_IMPLEMENTATION_RECORD_v1.md, and DOCUMENTATION_VERIFICATION_MATRIX_v1.md. README_v1.md coverage not confirmed. Confirm whether adapter change is user-visible before closing.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["If adapter change affects user-visible ingestion behavior, README_v1.md must be added to the doc_update_plan."]
      }
    ],
    "summary": {
      "doc_update_required": false,
      "requires_doc_code_sync_guard": false,
      "requires_doc_code_sync_auditor": true,
      "requires_verification_followup": true,
      "notes": ["Confirm README_v1.md scope before marking fully in_sync."]
    }
  }
}
```

---

## Completion standard

This skill's output is complete when all of the following hold.

1. Every changed document, code artifact, and claim in scope has at least one `checked_items` entry.
2. `overall_status` reflects the most severe finding across all items: if any item is `doc_update_required`, `doc_overstates_runtime`, `implementation_claim_mismatch`, or `snapshot_field_mismatch`, the overall status must be at least that severe.
3. `requires_doc_code_sync_guard` is `true` whenever any warning-worthy drift finding is present — this includes all statuses except `in_sync`, `review_only`, and `ambiguous_requires_review`.
4. `requires_doc_code_sync_auditor` is `true` whenever deep artifact comparison was needed but not available, or when the scope of the change is broader than could be confirmed from available inputs.
5. `requires_verification_followup` is `true` whenever sync findings imply that the verification matrix or ledger require updating.
6. All `canonical_source` fields cite the Tier 1 role-matched document — `SYSTEM_TECHNICAL_HANDBOOK_v1.md` for snapshot-field and contract-rule claims; `SYSTEM_IMPLEMENTATION_RECORD_v1.md` for implementation-state claims; `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` for architecture and phase-posture claims.
7. `source_authority_conflict_detected` is set if `README_LAYER2.md` or a non-role-matched source is cited for a strong Tier 1 claim.
8. `inference_used` is set correctly.
9. `missing_inputs` is populated for every item where artifact evidence was absent.
10. No `in_sync` verdict is emitted without artifact-to-artifact comparison for material implementation-state, snapshot-field, or contract-consistency claims.
11. The output is valid JSON conforming to the required schema.
12. In `json+summary` mode: a plain-language summary of no more than five sentences follows the JSON block, stating the overall sync verdict, the primary drift type if any, the affected documents, and the downstream actions required (guard warning, auditor review, verification follow-up).
