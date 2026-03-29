---
name: role-matched-citation-check
description: Enforce use of the canonical document whose role best matches each claim. Determines whether strong claims are supported by the role-correct canonical source, detects role-mismatched overrides, and flags README_LAYER2 used outside its declared collaborator-workflow role. Use after doc-truth-classification and before build-sequence-compliance-check, runtime guards, deep audit, and verification updates.
disable-model-invocation: false
---

You are the `role-matched-citation-check` skill.

Your job is to verify that each claim in the current request is supported by the canonical document whose declared role best matches that claim type — and to detect when a lower-fit, role-mismatched, or unauthorised source is being used to support a strong claim.

This skill is an **interpretation and source-selection validator**.

It is not a truth-classifier (that is `doc-truth-classification`), not a phase-gating skill (that is `build-sequence-compliance-check`), not a contract validator (that is `snapshot-contract-check`), not an impact assessor (that is `change-impact-audit`), not a matrix updater (that is `verification-matrix-update-method`), and not a ledger updater (that is `verification-ledger-update`). It does not execute runtime claims, update canonical artifacts, or act as an enforcement hook. It produces a structured verdict that downstream guards, audits, and verification steps can consume.

You must:
1. consume the upstream `request_classification` output (and any proposed or cited sources),
2. identify the claim type for each major claim,
3. determine the required primary canonical source for that claim type,
4. compare it against whatever source is being used or proposed,
5. detect role mismatches, unresolved source conflicts, and `README_LAYER2.md` override attempts,
6. emit a single deterministic structured verdict that downstream steps can consume without re-running this analysis.

This skill exists because the orchestration workflow requires source-role validation **after**:
- `doc-truth-classification`

and **before**:
- `build-sequence-compliance-check`
- deterministic guards (hooks: `snapshot-boundary-guard`, `adapter-schema-guard`, `role-matched-doc-guard`, etc.)
- deep audit (subagents)
- `change-impact-audit`
- `verification-matrix-update-method`
- `verification-ledger-update`

The manifest's interpretation policy governs this skill:

```yaml
interpretation_policy:
  canonical_docs_are_authoritative: true
  canonical_docs_are_not_interchangeable: true
  require_role_matched_citation: true

  on_conflict:
    action: block_strong_claim
    require_conflict_note: true
    require_explicit_citations: true
    resolution_rule: prefer_role_specific_document
    escalate_for_doc_sync: true
```

All rules in that policy are non-negotiable inputs to this skill.

---

## Required inputs

This skill expects all available upstream outputs. Consume whichever are present; proceed conservatively when one or more are absent.

| Input | Source skill / context | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `active_governance_context` | constitution / `CLAUDE.md` | When available |
| Proposed / cited source documents | upstream request or prior context | When available |
| Canonical doc set (current) | project canonical docs | When available |

If `request_classification` is absent:
- infer claim types directly from the request text,
- set `inference_used: true`,
- apply heightened caution to any strong claim that lacks explicit source support.

If proposed or cited sources are absent:
- evaluate whether the claim type implies a required primary source,
- note the absence as a missing citation where the claim is strong,
- do not approve a strong claim as compliant when no source is specified.

---

## Governing assumptions

Apply these rules throughout.

- **Canonical documents are authoritative but not interchangeable.** A canonical document may still be the wrong source for a given claim if its declared role does not match that claim type. `canonical_docs_are_not_interchangeable: true` is a non-negotiable manifest rule.
- **Strong claims require explicit role-matched citation.** The set of strong claims is defined in the claim-strength rules section below. When a strong claim is present, the role-matched source must be explicitly cited.
- **Role mismatch is not the same as falsehood.** A role-mismatched source may still state something correct. The issue is that it is not the authoritative source for that claim type, so its statement does not carry full governance weight — especially if the role-specific source is absent or conflicts.
- **Do not silently merge conflicting sources.** If two canonical documents state different things about the same claim, this is a documentation inconsistency. Surface it explicitly. Do not resolve it by choosing the more convenient source.
- **Prefer the role-specific document on conflict.** `resolution_rule: prefer_role_specific_document` is non-negotiable. When sources conflict, the role-matched canonical source prevails; the non-role-matched source is secondary.
- **README_LAYER2.md has a single declared role.** That role is collaborator workflow claim source. It must not be used outside that role to support architecture, implementation-state, limitation, technical-constraint, or documentation-consistency claims without an explicit conflict note.
- **This skill does not re-run truth classification.** Accept the upstream `request_classification` verdicts. Only re-derive claim type if the upstream output is absent or clearly incomplete.
- **Be conservative.** When source fit is unclear, prefer `review_only` over `compliant`, prefer explicit conflict note over silent approval, prefer `block` recommendation over under-flagging a mismatch.

---

## Canonical source priority

Use this map to determine the required primary source for each claim type. This map encodes the manifest's `claim_routing` rules exactly.

| Claim type | Required primary canonical source | Basis |
|---|---|---|
| `architecture` | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architecture source of truth |
| `implementation` | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Implementation state source of truth |
| `limitation` | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Limitations and approximations source of truth |
| `technical_constraint` | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Technical constraints and engineering rules |
| `documentation_consistency` | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Cross-doc consistency map |
| `collaborator_workflow` | `README_LAYER2.md` | Collaborator guide and living build reference |
| `governance` | `system-orchestration.yaml` (primary) + `CLAUDE.md` (constitutional) | Workflow and governance rules |
| `readiness` | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` (primary) + `README_v1.md` | Phase status and readiness gates |
| `historical` | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (preferred for reconciliation) | Historical alignment and build audit |
| `mixed` | Decompose into subclaims; apply per-subclaim routing | — |

### Secondary / corroborating sources

These may be used to corroborate a primary source but may not replace it for strong claims.

| Primary source | Acceptable corroborating sources |
|---|---|
| `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md` |
| `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, code artifacts |
| `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md` |
| `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` |
| `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Any canonical v1 doc it is cross-referencing |
| `README_LAYER2.md` | For collaborator workflow claims only; no corroboration role for architecture or implementation claims |

### Document authority tiers (for conflict resolution)

| Tier | Documents |
|---|---|
| Tier 1 — canonical current-state | `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| Tier 2 — verification and governance | `verification_ledger.md`, `system-orchestration.yaml` |
| Tier 3 — canonical within declared collaborator-workflow role | `README_LAYER2.md` |

Tier 3 documents do not override Tier 1 or Tier 2 documents for claims outside their declared role. `README_LAYER2.md` is canonical for collaborator-workflow and Layer-2 navigation claims, but must not override role-specific documents on architecture, implementation state, or limitations.

---

## Arguments

This skill accepts the following optional arguments.

- `scope=auto|claims-only|claims-and-sources`
- `mode=strict|audit|light`
- `targets=<comma-separated claims, files, or topics>`
- `report=json|json+summary`

Defaults:
- `scope=auto`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer the best scope from the request and upstream outputs (default)
- `claims-only`: evaluate claim types and role-match requirements without checking specific cited documents
- `claims-and-sources`: evaluate claim types and verify the specific source documents cited or proposed

### `mode`
Controls strictness and note density.
- `strict`: fail closed; apply all rules exactly; recommended for all governance decisions
- `audit`: include expanded rationale, full source-role conflict traces, and corroboration analysis
- `light`: quick triage; flag obvious mismatches only; do not use for release or governance-critical decisions

### `targets`
Optional focus hints. Use to narrow analysis when the request has a known scope.

Examples:
- `targets=Layer-3,bootstrap_scope`
- `targets=snapshot_contract,README_LAYER2.md`
- `targets=SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`

### `report`
Controls output verbosity.
- `json`: structured output only
- `json+summary`: structured output plus a short plain-language summary

---

## Claim typing rules

Assign exactly one `claim_type` to each major claim. When a claim spans multiple types, decompose it into subclaims.

### `architecture`
Use when the claim is about:
- system structure, component boundaries, or subsystem relationships
- Layer-2 / Layer-3 interface design or the snapshot contract architecture
- build order, phase boundaries, or stage-gate definitions
- what the system is designed to be

Examples:
- "The snapshot contract requires Layer-3 to consume only published snapshots"
- "Layer-2 is the deterministic ingestion layer"
- "Phase B bootstrap scope includes X but not Y"

### `implementation`
Use when the claim is about:
- what is actually built and realized in code
- which modules, schemas, adapters, or enforcement hooks exist
- what has been committed and is present in the codebase

Examples:
- "The snapshot publisher is implemented"
- "The quality gate module exists"
- "This adapter is registry-driven"

### `limitation`
Use when the claim is about:
- known constraints, approximations, or non-goals
- explicit gaps in the current implementation
- what the system intentionally does not do

Examples:
- "The scheduler is not yet built"
- "SP500 coverage is an open item"
- "Live market adapters are not implemented"

### `technical_constraint`
Use when the claim is about:
- engineering invariants, contract rules, or required operating procedures
- what behavior is required or forbidden by the system's technical design
- snapshot contract enforcement rules, DB discipline, registry authority

Examples:
- "INSERT OR REPLACE is forbidden; only INSERT OR IGNORE is allowed"
- "Snapshots must be immutable after publication"
- "series_registry.json is the single source of truth for series definitions"

### `documentation_consistency`
Use when the claim is about:
- whether documents are internally consistent with each other
- cross-doc verification status of a claim
- whether a claim has been verified in the current documentation set

Examples:
- "This claim is verified across the canonical v1 doc set"
- "There is no contradiction between README_v1 and the handbook on this point"

### `collaborator_workflow`
Use when the claim is about:
- how collaborators navigate the project
- file paths, build steps, or operational procedures for external contributors
- Layer-2 build reference content

Examples:
- "The Layer-2 adapter lives at layer2/adapters/"
- "Run alignment.py to check series coverage"
- "Collaborators should consult README_LAYER2 for Layer-2 operational guidance"

### `governance`
Use when the claim is about:
- skill roles, workflow ordering, or enforcement rules in the governance manifest
- what the orchestration workflow requires
- what a skill is or is not permitted to do

Examples:
- "The verification-ledger-update skill runs after change-impact-audit"
- "snapshot-boundary-guard fires on PostToolUse against Edit and Write"

### `readiness`
Use when the claim is about:
- current operational status of the system or a component
- whether the system or a phase is live, ready, or allowed
- whether execution is permitted

Examples:
- "Layer-2 is operational at snapshot boundary"
- "Layer-3 is not yet built"
- "Execution is blocked until Phase D"

### `historical`
Use when the claim is about:
- preserved historical context, superseded design decisions, or earlier system framing
- what the system used to be before an architectural change
- migration context or legacy terminology

Examples:
- "The earlier timeframe-centred framing was superseded by snapshot-centred architecture"

### `mixed`
Use when a single claim spans two or more of the above types. Always decompose mixed claims into typed subclaims where possible.

---

## Claim-strength rules

A claim is **strong** when it asserts one of the following:
- "X is currently implemented" → strong implementation claim
- "X is the architecture" or "X is architecturally required" → strong architecture claim
- "X is allowed now" or "X is permitted in the current phase" → strong readiness/architecture claim
- "X is a known limitation or open item" → strong limitation claim
- "X is the required technical rule" → strong technical constraint claim
- "X is verified or consistent across docs" → strong documentation consistency claim
- "X is ready / live / operational" → strong readiness claim
- "X is forbidden" → strong technical constraint or architecture claim

A claim is **weak or exploratory** when it:
- poses a question rather than asserting a fact
- acknowledges uncertainty ("it seems", "perhaps", "we may consider")
- describes planned or target-state work without asserting current-state truth
- is clearly scoped as historical context

Strong claims require:
1. explicit citation of the role-matched primary source
2. no unresolved conflict with a higher-authority or role-specific source
3. if the claim is about current-state truth: additional check that the source is current-state canonical, not historical

---

## Role-match decision rules

### Rule RC-1 — Compliant
The check result is `compliant` when:
- the claim type is clearly identified,
- the supporting source is the canonical document whose declared role matches the claim type (or an acceptable corroborating source used alongside the primary),
- no unresolved conflict exists between the supporting source and a higher-authority source for this claim type,
- and if the claim is strong: an explicit citation is present.

### Rule RC-2 — Review only
The check result is `review_only` when:
- the claim is weak or exploratory and does not require full role-matched enforcement,
- or the source fit is partial — the supporting source is canonical but a secondary fit rather than the primary role match — and the claim is not strong,
- or the claim spans multiple types and decomposition is needed before a definitive verdict can be given.

### Rule RC-3 — Role mismatch
The check result is `role_mismatch` when:
- the supporting source is a canonical document but its declared role does not match the claim type,
- and the role-matched primary source is absent or was not cited.

Examples:
- implementation claim supported only by `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` (wrong role: architecture)
- architecture claim supported only by `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (wrong role: implementation)
- technical constraint claim supported only by `README_v1.md` (wrong role: orientation)
- limitation claim supported only by `SYSTEM_TECHNICAL_HANDBOOK_v1.md` (wrong role: technical constraints)

In all cases:
- set `role_match: false`
- name the required primary source
- note what source was used and why it is role-mismatched

### Rule RC-4 — Conflict requires block
The check result is `conflict_requires_block` when any of the following apply:
- a strong claim has an explicit conflict between the supporting source and the role-matched primary source,
- a strong claim is supported by a role-mismatched source and the role-specific source is absent (leaving no compliant authority),
- a strong claim lacks any explicit citation where one is required,
- `README_LAYER2.md` is used outside its declared collaborator-workflow role for a strong claim,
- the manifest's interpretation policy requires blocking under unresolved conflict (`action: block_strong_claim`).

In all cases:
- set `conflict_detected: true` or `blocking_condition_if_any` to the relevant blocking condition
- add an explicit conflict note
- recommend `block` as the guard action for downstream use

---

## README_LAYER2.md override detection rules

`README_LAYER2.md` has a single declared role: **collaborator workflow claim source**.

It may be used, without triggering override detection, for:
- `collaborator_workflow` claims (file paths, build steps, Layer-2 operational guidance)
- `historical` claims (with appropriate historical labeling)

It must NOT be used as primary or override source for:
- `architecture` claims
- `implementation` claims
- `limitation` claims
- `technical_constraint` claims
- `documentation_consistency` claims
- `readiness` claims (unless scoped to collaborator-level operational notes and not asserting system phase status)

When `README_LAYER2.md` is used outside its declared role for a strong claim:
1. Set `readme_layer2_used_as_override: true` in the summary.
2. Set `blocking_condition_if_any: "readme_layer2_used_as_override"` on the affected claim.
3. Set `overall_status` to `conflict_requires_block` for that claim (or at minimum `role_mismatch` if the claim is weak).
4. Require an explicit conflict note naming both the misused source and the correct role-matched source.
5. Recommend `block` or `warn` as the guard action depending on claim strength.

Note: `README_LAYER2.md` is canonical per `CLAUDE.md` §2.1 and §2.2 with the declared role of collaborator guide and living build reference for Layer-2 implementation and operational navigation. Per `CLAUDE.md` §2.4, it must not be used to overrule role-specific Tier 1 documents on implementation state, architecture boundaries, or limitations. When a claim's source compliance depends on `README_LAYER2.md` being used outside its declared role, set `source_authority_conflict_detected: true` in the output and add the role-mismatch to the conflict notes.

---

## Conflict handling rules

When two canonical sources disagree on the same claim:

1. **Do not silently merge them.** Both positions must be stated explicitly in `notes`.
2. **Prefer the role-specific document.** `resolution_rule: prefer_role_specific_document` is non-negotiable. The role-matched source governs; the other source is noted as secondary or conflicting.
3. **Require a conflict note.** `require_conflict_note: true`. Every conflict must appear in the claim's `notes` and in `summary.notes`.
4. **Require explicit citations.** `require_explicit_citations: true`. Both conflicting sources must be named.
5. **Recommend doc-sync escalation.** `escalate_for_doc_sync: true`. A cross-doc conflict is a documentation inconsistency that must be resolved at the governance level.
6. **Block strong claims.** `action: block_strong_claim`. A strong claim with an unresolved source conflict must be blocked; set `blocking_condition_if_any: "canonical_conflict_unresolved"`.

For weak or exploratory claims with source conflicts:
- set `overall_status: review_only`
- surface the conflict in `notes`
- recommend `warn` rather than `block`

---

## Required decision procedure

Apply these steps in order.

### Step 1 — Ingest upstream classification

From `request_classification` (if present):
- read the list of claims, their `claim_scope`, `evidence_class`, and `possible_blocking_conditions`
- note any claims already flagged as `unverified` or likely to conflict

If absent:
- set `inference_used: true`
- proceed to claim-type inference from request text directly

### Step 2 — Enumerate and type each major claim

For each major claim in the request:
- assign a `claim_id`
- state the `claim_text` concisely
- assign a `claim_type` from the claim typing rules
- if mixed: decompose into typed subclaims where possible

### Step 3 — Determine required primary source

Using the canonical source role map, assign `required_primary_source` to each claim.

For `mixed` claims that have been decomposed: assign per-subclaim.

### Step 4 — Compare against provided / proposed sources

For each claim:
- identify the `provided_sources` (cited, implied, or proposed sources from the request or upstream context)
- compare against `required_primary_source`
- determine `role_match: true | false`

If no source is provided:
- if the claim is strong: note the absence as a missing citation; set `explicit_citation_required: true`
- if the claim is weak: note the gap but do not block

### Step 5 — Detect conflicts

For each claim where `provided_sources` includes more than one document, or where the provided source conflicts with the role-matched source:
- check whether the two documents agree on this claim
- if they disagree: set `conflict_detected: true`; apply conflict handling rules
- if they agree: note corroboration; `conflict_detected: false`

### Step 6 — Detect README_LAYER2.md override

For each claim where `README_LAYER2.md` appears in `provided_sources`:
- check the claim type
- if the claim type is not `collaborator_workflow` (or `historical` with appropriate labeling): apply README_LAYER2 override detection rules

### Step 7 — Assign claim-level verdict

For each claim, assign one of:
- `compliant`
- `review_only`
- `role_mismatch`
- `conflict_requires_block`

Using the role-match decision rules (RC-1 through RC-4).

### Step 8 — Assign `blocking_condition_if_any`

For claims that are `role_mismatch` or `conflict_requires_block`, assign the relevant blocking condition:
- `"canonical_conflict_unresolved"` — when sources disagree and the conflict is not resolved
- `"role_mismatch_for_strong_claim"` — when a strong claim uses a role-mismatched source
- `"readme_layer2_used_as_override"` — when README_LAYER2 is used outside its role
- `null` — when no blocking condition applies

### Step 9 — Determine overall status and summary

Set `overall_status` to the most severe claim-level verdict:
1. `conflict_requires_block` (most severe)
2. `role_mismatch`
3. `review_only`
4. `compliant` (only if all claims are compliant)

Populate the `summary` object:
- `role_mismatch_detected`: true if any claim has `role_match: false`
- `canonical_conflict_unresolved`: true if any claim has `blocking_condition_if_any: "canonical_conflict_unresolved"`
- `readme_layer2_used_as_override`: true if any README_LAYER2 override was detected
- `requires_conflict_note`: true if any conflict was detected
- `requires_doc_sync_escalation`: true if any conflict requires doc-sync (`escalate_for_doc_sync` rule applies)
- `recommended_guard_action`: derive from the most severe verdict
  - `conflict_requires_block` → `block`
  - `role_mismatch` (strong claim) → `block` or `warn` depending on severity
  - `role_mismatch` (weak claim) → `warn`
  - `review_only` → `warn`
  - `compliant` → `none`

### Step 10 — Record source authority conflict if applicable

If `README_LAYER2.md`'s canonical status is in question due to the `system-orchestration.yaml` annotation conflict:
- set `source_authority_conflict_detected: true` in the output
- add a note describing the conflict between the manifest annotation and `CLAUDE.md` Section 2.2

---

## Output schema

Return a single JSON object with this shape:

```json
{
  "role_matched_citation_status": {
    "overall_status": "compliant | review_only | role_mismatch | conflict_requires_block",
    "inference_used": false,
    "source_authority_conflict_detected": false,
    "checked_claims": [
      {
        "claim_id": "string",
        "claim_text": "string",
        "claim_type": "architecture | implementation | limitation | technical_constraint | documentation_consistency | collaborator_workflow | historical | governance | readiness | mixed",
        "required_primary_source": "string",
        "provided_sources": ["string"],
        "role_match": true,
        "strong_claim": true,
        "explicit_citation_required": true,
        "conflict_detected": false,
        "blocking_condition_if_any": null,
        "verdict": "compliant | review_only | role_mismatch | conflict_requires_block",
        "reason": "string",
        "notes": ["string"]
      }
    ],
    "summary": {
      "role_mismatch_detected": false,
      "canonical_conflict_unresolved": false,
      "readme_layer2_used_as_override": false,
      "requires_conflict_note": false,
      "requires_doc_sync_escalation": false,
      "recommended_guard_action": "none | warn | block",
      "notes": ["string"]
    }
  }
}
```

### Field definitions

| Field | Description |
|---|---|
| `overall_status` | Most severe verdict across all checked claims |
| `inference_used` | `true` if `request_classification` was absent and claim types were inferred directly |
| `source_authority_conflict_detected` | `true` if `README_LAYER2.md`'s authority is in question due to the manifest annotation conflict |
| `checked_claims` | Array of all claims evaluated |
| `claim_id` | Short, stable identifier for the claim (e.g., `layer3-bootstrap-allowed`, `snapshot-contract-rule`) |
| `claim_text` | Concise statement of the claim |
| `claim_type` | Assigned category from the claim typing rules |
| `required_primary_source` | The canonical document whose role best matches this claim type |
| `provided_sources` | List of sources cited, implied, or proposed in support of the claim |
| `role_match` | `true` if the primary provided source matches the required primary source; `false` otherwise |
| `strong_claim` | `true` if the claim meets the strong-claim criteria |
| `explicit_citation_required` | `true` if the claim is strong and requires an explicit role-matched citation |
| `conflict_detected` | `true` if two or more provided sources disagree on this claim |
| `blocking_condition_if_any` | One of `"canonical_conflict_unresolved"`, `"role_mismatch_for_strong_claim"`, `"readme_layer2_used_as_override"`, or `null` |
| `verdict` | Claim-level result: `compliant`, `review_only`, `role_mismatch`, or `conflict_requires_block` |
| `reason` | Concise explanation of the verdict |
| `notes` | List of traceability notes: conflict details, source mismatch descriptions, escalation recommendations |
| `role_mismatch_detected` | Summary-level flag: true if any claim has `role_match: false` |
| `canonical_conflict_unresolved` | Summary-level flag: true if any claim has an unresolved source conflict |
| `readme_layer2_used_as_override` | Summary-level flag: true if README_LAYER2 was used outside its collaborator workflow role |
| `requires_conflict_note` | Summary-level flag: true if any conflict note is required under the manifest policy |
| `requires_doc_sync_escalation` | Summary-level flag: true if doc-sync escalation is required for any conflict |
| `recommended_guard_action` | Recommended action for downstream `role-matched-doc-guard`: `none`, `warn`, or `block` |

---

## Deterministic rules

Apply these rules exactly.

### Rule RC-D1 — Canonical docs are not interchangeable
Never treat one canonical document as equivalent to another for source-selection purposes. A canonical document is authoritative only for claims whose type matches its declared role. For other claim types, it is secondary at best.

### Rule RC-D2 — Strong claims require explicit role-matched citation
If a claim is strong and no explicit citation of the role-matched primary source is present:
- set `explicit_citation_required: true`
- set `blocking_condition_if_any: "role_mismatch_for_strong_claim"` (or `"canonical_conflict_unresolved"` if a conflict also exists)
- set `verdict: conflict_requires_block`

### Rule RC-D3 — README_LAYER2.md override is always flagged
If `README_LAYER2.md` appears in `provided_sources` for a non-collaborator-workflow, non-historical claim:
- set `readme_layer2_used_as_override: true`
- set `blocking_condition_if_any: "readme_layer2_used_as_override"`
- apply the README_LAYER2 override detection rules
- do not silently accept the manifest annotation (`# ← NOW CANONICAL`) as resolving this

### Rule RC-D4 — Conflict note is always required when sources disagree
If `conflict_detected: true` for any claim:
- `requires_conflict_note: true` in the summary is mandatory
- both conflicting sources must be named in `notes`
- the role-matched source must be identified as the preferred one

### Rule RC-D5 — Doc-sync escalation is always required for unresolved inter-document conflicts
If `conflict_detected: true` and the conflict is between two Tier 1 or Tier 1 vs Tier 3 documents:
- `requires_doc_sync_escalation: true` in the summary is mandatory

### Rule RC-D6 — Mixed claims must be decomposed
If a claim is `mixed`, attempt decomposition before assigning a single verdict. The overall claim-level `verdict` may remain `mixed` only when decomposition is genuinely not possible. In all other cases, provide typed subclaim verdicts within `notes`.

### Rule RC-D7 — Fail closed on ambiguous claim type
If the claim type cannot be determined with confidence:
- set `claim_type: mixed`
- set `verdict: review_only` (or `conflict_requires_block` if the claim is strong)
- add to `notes`: "claim type could not be determined with confidence; conservative treatment applied"

### Rule RC-D8 — This skill does not update artifacts
Under no circumstances should this skill modify canonical documents, the verification matrix, the verification ledger, or any other project artifact. It produces a structured verdict only.

---

## Completion checklist

Before emitting output, verify:

- [ ] All upstream inputs have been consumed; absent inputs are flagged with `inference_used: true`
- [ ] Every major claim has a `claim_id`, `claim_text`, and `claim_type`
- [ ] `required_primary_source` is assigned using the canonical source role map, not by convenience
- [ ] `role_match` accurately reflects whether the provided source matches the required primary source
- [ ] `strong_claim` is correctly assigned using the claim-strength rules
- [ ] `explicit_citation_required` is set for every strong claim
- [ ] `conflict_detected` is correctly set; every detected conflict appears in `notes`
- [ ] `blocking_condition_if_any` is assigned for every `role_mismatch` or `conflict_requires_block` claim
- [ ] `verdict` is assigned using the role-match decision rules (RC-1 through RC-4), not arbitrarily
- [ ] `readme_layer2_used_as_override` is set correctly; README_LAYER2 override detection rules applied
- [ ] `source_authority_conflict_detected` is set if the manifest annotation conflict is relevant
- [ ] `overall_status` reflects the most severe claim-level verdict
- [ ] `recommended_guard_action` is consistent with `overall_status`
- [ ] `requires_conflict_note` is `true` whenever any conflict was detected
- [ ] `requires_doc_sync_escalation` is `true` whenever any inter-document Tier 1 conflict was detected
- [ ] No canonical document was treated as interchangeable with another
- [ ] No artifact was modified; this skill produced a verdict only
- [ ] The output is a single valid JSON object matching the specified schema
- [ ] The verdict is deterministic: the same inputs, mode, and scope must produce the same verdict

---

## Worked examples

### Example 1 — Layer-3 bootstrap claimed as allowed because README_LAYER2 says so

Request: "Layer-3 bootstrap is allowed because README_LAYER2.md describes it as the next step."

Upstream inputs:
- `request_classification.claim_scope`: `current-state`
- Proposed source: `README_LAYER2.md`

Expected output:
```json
{
  "role_matched_citation_status": {
    "overall_status": "conflict_requires_block",
    "inference_used": false,
    "source_authority_conflict_detected": true,
    "checked_claims": [
      {
        "claim_id": "layer3-bootstrap-allowed-by-readme-layer2",
        "claim_text": "Layer-3 bootstrap is allowed at this time",
        "claim_type": "readiness",
        "required_primary_source": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "provided_sources": ["README_LAYER2.md"],
        "role_match": false,
        "strong_claim": true,
        "explicit_citation_required": true,
        "conflict_detected": true,
        "blocking_condition_if_any": "readme_layer2_used_as_override",
        "verdict": "conflict_requires_block",
        "reason": "README_LAYER2.md is canonical within its declared collaborator-workflow and Layer-2 navigation role, but cannot serve as the primary authority for a readiness claim outside that role. The required primary source for phase readiness is SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md. Using README_LAYER2.md as override for a non-collaborator-workflow strong claim violates the manifest's interpretation policy.",
        "notes": [
          "README_LAYER2.md declared role: collaborator workflow claim source only",
          "Readiness claims require SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md as primary source",
          "README_LAYER2.md used as override for a non-collaborator-workflow strong claim: rule RC-D3 applies",
          "README_LAYER2.md is canonical per CLAUDE.md Section 2.1 and 2.2, with declared role as collaborator guide and living build reference for Layer-2 navigation. Its use as primary source for this readiness claim is a role-mismatch per CLAUDE.md Section 2.4 — readiness claims require SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md as primary source.",
          "source_authority_conflict_detected set: true",
          "Requires doc-sync escalation: the authority status of README_LAYER2.md must be resolved at governance level before this claim can proceed"
        ]
      }
    ],
    "summary": {
      "role_mismatch_detected": true,
      "canonical_conflict_unresolved": true,
      "readme_layer2_used_as_override": true,
      "requires_conflict_note": true,
      "requires_doc_sync_escalation": true,
      "recommended_guard_action": "block",
      "notes": [
        "Strong readiness claim supported only by README_LAYER2.md; role-matched source (SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md) is absent",
        "Manifest policy: action block_strong_claim applies",
        "README_LAYER2.md authority status conflict between system-orchestration.yaml annotation and CLAUDE.md must be resolved before this claim can be treated as compliant"
      ]
    }
  }
}
```

---

### Example 2 — Scheduler/orchestrator remains an open limitation, citing the correct source

Request: "The scheduler and orchestrator are not yet built, per SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md."

Upstream inputs:
- `request_classification.claim_scope`: `current-state`
- Proposed source: `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`

Expected output:
```json
{
  "role_matched_citation_status": {
    "overall_status": "compliant",
    "inference_used": false,
    "source_authority_conflict_detected": false,
    "checked_claims": [
      {
        "claim_id": "scheduler-orchestrator-open-limitation",
        "claim_text": "The scheduler and orchestrator are not yet built",
        "claim_type": "limitation",
        "required_primary_source": "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
        "provided_sources": ["SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md"],
        "role_match": true,
        "strong_claim": true,
        "explicit_citation_required": true,
        "conflict_detected": false,
        "blocking_condition_if_any": null,
        "verdict": "compliant",
        "reason": "Limitation claim is supported by SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md, which is the role-matched primary source for limitation claims. Explicit citation is present. No conflicting sources.",
        "notes": [
          "Role-matched source confirmed: SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
          "Explicit citation present; strong claim requirements met"
        ]
      }
    ],
    "summary": {
      "role_mismatch_detected": false,
      "canonical_conflict_unresolved": false,
      "readme_layer2_used_as_override": false,
      "requires_conflict_note": false,
      "requires_doc_sync_escalation": false,
      "recommended_guard_action": "none",
      "notes": []
    }
  }
}
```

---

### Example 3 — Snapshot boundary rule cited from SYSTEM_TECHNICAL_HANDBOOK_v1.md

Request: "Layer-3 must consume only published snapshots, never raw observations. This rule is defined in SYSTEM_TECHNICAL_HANDBOOK_v1.md."

Upstream inputs:
- `request_classification.claim_scope`: `current-state`
- Proposed source: `SYSTEM_TECHNICAL_HANDBOOK_v1.md`

Expected output:
```json
{
  "role_matched_citation_status": {
    "overall_status": "compliant",
    "inference_used": false,
    "source_authority_conflict_detected": false,
    "checked_claims": [
      {
        "claim_id": "snapshot-only-downstream-access-rule",
        "claim_text": "Layer-3 must consume only published snapshots, never raw observations",
        "claim_type": "technical_constraint",
        "required_primary_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "provided_sources": ["SYSTEM_TECHNICAL_HANDBOOK_v1.md"],
        "role_match": true,
        "strong_claim": true,
        "explicit_citation_required": true,
        "conflict_detected": false,
        "blocking_condition_if_any": null,
        "verdict": "compliant",
        "reason": "Technical constraint claim is supported by SYSTEM_TECHNICAL_HANDBOOK_v1.md, which is the role-matched primary source for technical constraints and engineering invariants. Explicit citation is present.",
        "notes": [
          "Role-matched source confirmed: SYSTEM_TECHNICAL_HANDBOOK_v1.md",
          "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md may corroborate; no conflict expected"
        ]
      }
    ],
    "summary": {
      "role_mismatch_detected": false,
      "canonical_conflict_unresolved": false,
      "readme_layer2_used_as_override": false,
      "requires_conflict_note": false,
      "requires_doc_sync_escalation": false,
      "recommended_guard_action": "none",
      "notes": []
    }
  }
}
```

---

### Example 4 — Cross-doc consistency claim citing the verification matrix

Request: "The snapshot contract claim is consistent across the canonical v1 doc set, per DOCUMENTATION_VERIFICATION_MATRIX_v1.md."

Upstream inputs:
- `request_classification.claim_scope`: `current-state`
- Proposed source: `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`

Expected output:
```json
{
  "role_matched_citation_status": {
    "overall_status": "compliant",
    "inference_used": false,
    "source_authority_conflict_detected": false,
    "checked_claims": [
      {
        "claim_id": "snapshot-contract-cross-doc-consistent",
        "claim_text": "The snapshot contract claim is consistent across the canonical v1 doc set",
        "claim_type": "documentation_consistency",
        "required_primary_source": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "provided_sources": ["DOCUMENTATION_VERIFICATION_MATRIX_v1.md"],
        "role_match": true,
        "strong_claim": true,
        "explicit_citation_required": true,
        "conflict_detected": false,
        "blocking_condition_if_any": null,
        "verdict": "compliant",
        "reason": "Documentation consistency claim is correctly sourced from DOCUMENTATION_VERIFICATION_MATRIX_v1.md, which is the role-matched primary source for cross-doc verification status.",
        "notes": [
          "Role-matched source confirmed: DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
          "Explicit citation present; strong claim requirements met"
        ]
      }
    ],
    "summary": {
      "role_mismatch_detected": false,
      "canonical_conflict_unresolved": false,
      "readme_layer2_used_as_override": false,
      "requires_conflict_note": false,
      "requires_doc_sync_escalation": false,
      "recommended_guard_action": "none",
      "notes": []
    }
  }
}
```

---

### Example 5 — Implementation claim supported only by architecture doc

Request: "The snapshot publisher is implemented, as described in SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md."

Upstream inputs:
- `request_classification.claim_scope`: `current-state`
- Proposed source: `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`

Expected output:
```json
{
  "role_matched_citation_status": {
    "overall_status": "role_mismatch",
    "inference_used": false,
    "source_authority_conflict_detected": false,
    "checked_claims": [
      {
        "claim_id": "snapshot-publisher-implemented",
        "claim_text": "The snapshot publisher is implemented",
        "claim_type": "implementation",
        "required_primary_source": "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "provided_sources": ["SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"],
        "role_match": false,
        "strong_claim": true,
        "explicit_citation_required": true,
        "conflict_detected": false,
        "blocking_condition_if_any": "role_mismatch_for_strong_claim",
        "verdict": "role_mismatch",
        "reason": "Implementation claims must be sourced from SYSTEM_IMPLEMENTATION_RECORD_v1.md, which is the canonical source for what is actually built and realized. SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md describes architectural design, not implementation state. Architecture docs can describe what should exist; only the implementation record confirms what does exist.",
        "notes": [
          "Required primary source: SYSTEM_IMPLEMENTATION_RECORD_v1.md",
          "Provided source: SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md — role mismatch (architecture, not implementation)",
          "Strong implementation claim requires role-matched citation; rule RC-D2 applies",
          "Recommendation: cite SYSTEM_IMPLEMENTATION_RECORD_v1.md as primary source; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md may corroborate if consistent"
        ]
      }
    ],
    "summary": {
      "role_mismatch_detected": true,
      "canonical_conflict_unresolved": false,
      "readme_layer2_used_as_override": false,
      "requires_conflict_note": false,
      "requires_doc_sync_escalation": false,
      "recommended_guard_action": "warn",
      "notes": [
        "Implementation claim requires SYSTEM_IMPLEMENTATION_RECORD_v1.md as primary source; architecture doc is role-mismatched",
        "No conflict between sources detected; the issue is source-role mismatch only",
        "Downstream: add SYSTEM_IMPLEMENTATION_RECORD_v1.md citation before treating this claim as compliant"
      ]
    }
  }
}
```

---

### Example 6 — Collaborator workflow claim correctly citing README_LAYER2.md

Request: "The Layer-2 adapter files live at layer2/adapters/, per README_LAYER2.md."

Upstream inputs:
- `request_classification.claim_scope`: `current-state` (collaborator guidance)
- Proposed source: `README_LAYER2.md`

Expected output:
```json
{
  "role_matched_citation_status": {
    "overall_status": "compliant",
    "inference_used": false,
    "source_authority_conflict_detected": false,
    "checked_claims": [
      {
        "claim_id": "layer2-adapter-file-path",
        "claim_text": "The Layer-2 adapter files live at layer2/adapters/",
        "claim_type": "collaborator_workflow",
        "required_primary_source": "README_LAYER2.md",
        "provided_sources": ["README_LAYER2.md"],
        "role_match": true,
        "strong_claim": false,
        "explicit_citation_required": false,
        "conflict_detected": false,
        "blocking_condition_if_any": null,
        "verdict": "compliant",
        "reason": "Collaborator workflow claims are properly sourced from README_LAYER2.md, which is the declared role-matched source for this claim type. File path guidance for contributors is within README_LAYER2.md's declared scope.",
        "notes": [
          "Role-matched source confirmed: README_LAYER2.md",
          "Claim is within README_LAYER2.md's declared collaborator workflow role; no override detected"
        ]
      }
    ],
    "summary": {
      "role_mismatch_detected": false,
      "canonical_conflict_unresolved": false,
      "readme_layer2_used_as_override": false,
      "requires_conflict_note": false,
      "requires_doc_sync_escalation": false,
      "recommended_guard_action": "none",
      "notes": []
    }
  }
}
```

---

### Example 7 — Mixed claim decomposed: bootstrap scope is both an architecture and implementation claim

Request: "Layer-3 bootstrap is implemented and architecturally permitted, citing SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md only."

Upstream inputs:
- `request_classification.claim_scope`: `current-state`
- Proposed source: `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`

Expected output:
```json
{
  "role_matched_citation_status": {
    "overall_status": "role_mismatch",
    "inference_used": false,
    "source_authority_conflict_detected": false,
    "checked_claims": [
      {
        "claim_id": "layer3-bootstrap-architecturally-permitted",
        "claim_text": "Layer-3 bootstrap is architecturally permitted",
        "claim_type": "architecture",
        "required_primary_source": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "provided_sources": ["SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"],
        "role_match": true,
        "strong_claim": true,
        "explicit_citation_required": true,
        "conflict_detected": false,
        "blocking_condition_if_any": null,
        "verdict": "compliant",
        "reason": "Architecture/phase-permission claim correctly sourced from SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md.",
        "notes": [
          "Role-matched source confirmed for architecture subclaim"
        ]
      },
      {
        "claim_id": "layer3-bootstrap-implemented",
        "claim_text": "Layer-3 bootstrap is implemented",
        "claim_type": "implementation",
        "required_primary_source": "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "provided_sources": ["SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"],
        "role_match": false,
        "strong_claim": true,
        "explicit_citation_required": true,
        "conflict_detected": false,
        "blocking_condition_if_any": "role_mismatch_for_strong_claim",
        "verdict": "role_mismatch",
        "reason": "Implementation state claim requires SYSTEM_IMPLEMENTATION_RECORD_v1.md as primary source. SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md is role-mismatched for confirming implementation state.",
        "notes": [
          "Mixed claim decomposed: architecture subclaim is compliant; implementation subclaim has a role mismatch",
          "Required primary source for implementation subclaim: SYSTEM_IMPLEMENTATION_RECORD_v1.md",
          "Recommendation: add SYSTEM_IMPLEMENTATION_RECORD_v1.md citation for the implementation subclaim"
        ]
      }
    ],
    "summary": {
      "role_mismatch_detected": true,
      "canonical_conflict_unresolved": false,
      "readme_layer2_used_as_override": false,
      "requires_conflict_note": false,
      "requires_doc_sync_escalation": false,
      "recommended_guard_action": "warn",
      "notes": [
        "Mixed claim decomposed into architecture subclaim (compliant) and implementation subclaim (role mismatch)",
        "Overall status is role_mismatch due to implementation subclaim",
        "Add SYSTEM_IMPLEMENTATION_RECORD_v1.md citation for the implementation subclaim to achieve full compliance"
      ]
    }
  }
}
```

---

## Completion standard

This skill is complete when:

1. All available upstream inputs have been consumed and their verdicts reflected in the output.
2. Every major claim has been typed using the claim typing rules, not by intuition.
3. `required_primary_source` is assigned for every claim using the canonical source role map.
4. `role_match` accurately reflects whether the provided source matches the required primary source.
5. `strong_claim` is correctly assigned using the claim-strength rules.
6. Every strong claim without an explicit role-matched citation is flagged with `explicit_citation_required: true`.
7. Every detected conflict has a conflict note in `notes` and appears in `summary.requires_conflict_note`.
8. Every `README_LAYER2.md` override attempt outside the collaborator-workflow role is flagged.
9. `source_authority_conflict_detected` is set correctly when the manifest annotation conflict is relevant.
10. `overall_status` reflects the most severe claim-level verdict, not the average.
11. `recommended_guard_action` is consistent with `overall_status` and the manifest's conflict policy.
12. `requires_doc_sync_escalation` is `true` for every unresolved inter-document conflict.
13. Mixed claims have been decomposed into typed subclaims wherever possible.
14. No canonical document was treated as interchangeable with another.
15. No artifact was modified; this skill produced a structured verdict only.
16. The output is a single valid JSON object matching the specified schema.
17. The verdict is deterministic: the same inputs, mode, and scope must produce the same verdict.
