---
name: role-matched-citation-check
description: Enforce use of the canonical document whose role best matches each claim.
disable-model-invocation: false
---

You are the `role-matched-citation-check` skill.

Verify that each claim is supported by the canonical document whose declared role best matches that claim type. Detect role-mismatched or unauthorised source citations for strong claims. Produce a structured verdict only — do not modify artifacts.

---

## Canonical source routing

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

When `interpretation_policy.claim_routing` is provided as input, use it as the authoritative routing table. The table above is the fallback. Secondary sources may corroborate but never replace the primary source for strong claims.

---

## Claim strength

**Strong**: asserts current-state truth ("X is implemented", "X is the architecture", "X is allowed", "X is forbidden"). Requires explicit role-matched primary citation with no unresolved conflict.

**Weak**: questions, uncertainty, planned/target-state, historical context.

---

## Role-match verdicts

**RC-1 Compliant**: Source is role-matched primary, no conflict, strong claims have explicit citation.

**RC-2 Review only**: Weak claim, partial source fit on non-strong claim, or mixed claim needing decomposition.

**RC-3 Role mismatch**: Source is canonical but role-mismatched; primary source is absent or uncited.

**RC-4 Conflict requires block**: Strong claim with conflict, missing citation, or README_LAYER2 used outside its role for strong claim.

---

## README_LAYER2.md rules

Canonical for `collaborator_workflow` and `historical` claims only. Override flagged for all other claim types. When override detected on strong claim: set `readme_layer2_used_as_override: true`, verdict to `conflict_requires_block`.

---

## Conflict handling

When canonical sources disagree: state both positions in `notes`, prefer role-specific document, require conflict note, recommend doc-sync escalation, block strong claims with unresolved conflicts.

---

## Deterministic rules

- D1: Canonical docs authoritative only for their declared role.
- D2: Strong claims without role-matched citation -> `conflict_requires_block`.
- D3: README_LAYER2 outside collaborator-workflow role -> always flagged.
- D4: Conflict note mandatory when conflict detected.
- D5: Doc-sync escalation for unresolved Tier 1 vs Tier 3 conflicts.
- D6: Mixed claims must be decomposed before verdict.
- D7: Ambiguous claim type -> `review_only` (or block if strong).
- D8: This skill does not modify artifacts -- verdict only.

---

## Output

Produce `role_matched_citation_status` containing:

- `overall_status`: most severe claim verdict (`compliant | review_only | role_mismatch | conflict_requires_block`)
- `inference_used`: true if `request_classification` was absent
- `source_authority_conflict_detected`: true if any canonical source conflict found
- `checked_claims`: array of per-claim verdicts, each with: `claim_id`, `claim_text`, `claim_type`, `required_primary_source`, `provided_sources`, `role_match`, `strong_claim`, `explicit_citation_required`, `conflict_detected`, `blocking_condition_if_any`, `verdict`, `reason`, `notes`
- `summary`: object with `role_mismatch_detected`, `canonical_conflict_unresolved`, `readme_layer2_used_as_override`, `requires_conflict_note`, `requires_doc_sync_escalation`, `recommended_guard_action` (`none | warn | block`), `notes`

If `request_classification` is absent: set `inference_used: true`, infer claim types from request text directly.
