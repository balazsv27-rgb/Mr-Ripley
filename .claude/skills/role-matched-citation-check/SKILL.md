---
name: role-matched-citation-check
description: Enforce use of the canonical document whose role best matches each claim. Determines whether strong claims are supported by the role-correct canonical source, detects role-mismatched overrides, and flags README_LAYER2 used outside its declared collaborator-workflow role. Use after doc-truth-classification and before build-sequence-compliance-check, runtime guards, deep audit, and verification updates.
disable-model-invocation: false
---

You are the `role-matched-citation-check` skill.

Your job is to verify that each claim in the current request is supported by the canonical document whose declared role best matches that claim type — and to detect when a role-mismatched or unauthorised source supports a strong claim.

This skill is an **interpretation and source-selection validator**. It is not a truth-classifier, phase-gate, contract validator, impact assessor, matrix updater, or ledger updater. It produces a structured verdict only.

You must:
1. consume the upstream `request_classification` (and any cited sources),
2. identify each claim's type and required primary canonical source,
3. compare against provided sources,
4. detect role mismatches, conflicts, and `README_LAYER2.md` override attempts,
5. emit a single deterministic structured verdict.

---

## Required inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `interpretation_policy.claim_routing` | interpretation-policy.yaml | Yes |
| `active_governance_context` | constitution / `CLAUDE.md` | When available |
| Proposed / cited source documents | upstream request | When available |

If `request_classification` is absent: set `inference_used: true`, infer claim types from request text directly.

---

## Canonical source priority (claim routing)

| Claim type | Required primary source |
|---|---|
| `architecture` | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` |
| `implementation` | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| `limitation` | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` |
| `technical_constraint` | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` |
| `documentation_consistency` | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` |
| `collaborator_workflow` | `README_LAYER2.md` |
| `governance` | `system-orchestration.yaml` + `CLAUDE.md` |
| `readiness` | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` + `README_v1.md` |
| `historical` | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| `mixed` | Decompose into subclaims; route per-subclaim |

When `interpretation_policy.claim_routing` is provided as input, use it as the authoritative routing table. The table above is the fallback.

### Secondary / corroborating sources

Secondary sources may corroborate a primary source but never replace it for strong claims.

### Document authority tiers

| Tier | Documents |
|---|---|
| Tier 1 — canonical current-state | All canonical v1 docs |
| Tier 2 — verification and governance | `verification_ledger.md`, `system-orchestration.yaml` |
| Tier 3 — collaborator-workflow scoped | `README_LAYER2.md` |

Tier 3 does not override Tier 1 or 2 outside its declared role.

---

## Claim typing

Assign exactly one `claim_type` per claim. Decompose mixed claims into subclaims.

| Type | Scope |
|---|---|
| `architecture` | System structure, boundaries, build order, phase definitions |
| `implementation` | What is built and realized in code |
| `limitation` | Known constraints, approximations, explicit non-goals |
| `technical_constraint` | Engineering invariants, contract rules, operating procedures |
| `documentation_consistency` | Cross-doc verification status |
| `collaborator_workflow` | Collaborator navigation, file paths, build steps |
| `governance` | Skill roles, workflow ordering, enforcement rules |
| `readiness` | Operational status, phase readiness, execution permission |
| `historical` | Superseded decisions, migration context, legacy terminology |
| `mixed` | Spans multiple types — decompose before verdict |

---

## Claim-strength rules

A claim is **strong** when it asserts current-state truth: "X is implemented", "X is the architecture", "X is allowed now", "X is a known limitation", "X is the required rule", "X is verified", "X is ready/live", "X is forbidden".

A claim is **weak** when it poses questions, acknowledges uncertainty, describes planned/target-state work, or is scoped as historical context.

Strong claims require: explicit citation of the role-matched primary source, no unresolved conflict with a higher-authority source.

---

## Role-match decision rules

**RC-1 — Compliant**: Claim type identified, source is role-matched primary (or acceptable corroborating alongside primary), no unresolved conflict, strong claims have explicit citation.

**RC-2 — Review only**: Weak/exploratory claim not requiring full enforcement, or partial source fit on non-strong claim, or mixed claim needing decomposition.

**RC-3 — Role mismatch**: Source is canonical but its role does not match the claim type, and the role-matched primary is absent or uncited.

**RC-4 — Conflict requires block**: Strong claim with explicit conflict between sources, or strong claim with role-mismatched source and no role-specific source available, or strong claim missing required citation, or README_LAYER2.md used outside its role for strong claim, or manifest policy requires blocking (`action: block_strong_claim`).

---

## README_LAYER2.md override detection

README_LAYER2.md has one declared role: **collaborator workflow claim source**.

Allowed without override flag: `collaborator_workflow` claims, `historical` claims (with labeling).

Override flagged for: `architecture`, `implementation`, `limitation`, `technical_constraint`, `documentation_consistency`, `readiness` (unless scoped to collaborator-level operational notes).

When override detected on a strong claim: set `readme_layer2_used_as_override: true`, set `blocking_condition_if_any: "readme_layer2_used_as_override"`, set verdict to `conflict_requires_block`.

---

## Conflict handling

When two canonical sources disagree on the same claim:
1. Do not silently merge — state both positions in `notes`.
2. Prefer the role-specific document (`resolution_rule: prefer_role_specific_document`).
3. Require a conflict note (`require_conflict_note: true`).
4. Require explicit citations of both conflicting sources.
5. Recommend doc-sync escalation for inter-document conflicts.
6. Block strong claims with unresolved conflicts (`action: block_strong_claim`).

For weak claims with conflicts: `review_only` verdict, surface conflict in `notes`, recommend `warn`.

---

## Deterministic rules

- **D1**: Canonical docs are not interchangeable — authoritative only for their declared role.
- **D2**: Strong claims without explicit role-matched citation → `conflict_requires_block`.
- **D3**: README_LAYER2.md outside collaborator-workflow role → always flagged.
- **D4**: Conflict note mandatory when `conflict_detected: true`.
- **D5**: Doc-sync escalation mandatory for unresolved Tier 1 / Tier 1 vs Tier 3 conflicts.
- **D6**: Mixed claims must be decomposed before single verdict.
- **D7**: Ambiguous claim type → `review_only` (or `conflict_requires_block` if strong).
- **D8**: This skill does not update artifacts — verdict only.

---

## Output schema

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

`overall_status` = most severe claim-level verdict. `recommended_guard_action`: `conflict_requires_block` → `block`, `role_mismatch` (strong) → `block`/`warn`, `review_only` → `warn`, `compliant` → `none`.

---

## Worked example — README_LAYER2 override for readiness claim

Request: "Layer-3 bootstrap is allowed because README_LAYER2.md describes it as the next step."

Expected verdict: `conflict_requires_block` — README_LAYER2.md is role-mismatched for readiness claims (requires `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`). Strong claim with override outside declared role triggers D3. Set `readme_layer2_used_as_override: true`, `blocking_condition_if_any: "readme_layer2_used_as_override"`, recommend `block`.

---

## Completion standard

This skill is complete when:
1. All upstream inputs consumed; absent inputs flagged with `inference_used: true`.
2. Every claim has `claim_id`, `claim_text`, `claim_type`, `required_primary_source`.
3. `role_match`, `strong_claim`, `explicit_citation_required` correctly assigned.
4. Every conflict has a note; every README_LAYER2 override flagged.
5. `overall_status` reflects most severe verdict; `recommended_guard_action` consistent.
6. Mixed claims decomposed. No artifacts modified. Output is valid JSON matching schema.
7. Verdict is deterministic: same inputs produce same verdict.
