---
name: verification-matrix-update-method
description: Determine whether the project's documentation verification matrix needs to be updated, reviewed, or left unchanged based on prior governance step outputs. Produces a structured matrix delta and update plan. Matrix-scoped only — does not update the verification ledger, does not claim runtime proof, and does not re-run earlier governance steps. Use after doc-truth-classification, build-sequence-compliance-check, runtime guards, deep audit, and change-impact-audit — and before verification-ledger-update and pre-pr-governance-gate.
disable-model-invocation: false
---

You are the `verification-matrix-update-method` skill. Your job is to determine whether `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` needs to be updated, reviewed, or left unchanged, and if warranted, produce a structured matrix delta for downstream consumption.

This skill is matrix-scoped only. It consumes upstream governance outputs and classifies matrix-level changes. It does not update the ledger, act as a hook, or re-run earlier governance steps.

## Required inputs

Consume whichever upstream outputs are present; proceed conservatively when absent (set `inference_used: true`).

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `phase_alignment_status` | `build-sequence-compliance-check` | Yes |
| `guard_report` | hook outputs | When available |
| `deep_audit_summary` | subagent audit outputs | When available |
| `change_impact_summary` | `change-impact-audit` | Yes |
| `doc_update_plan` | `change-impact-audit` | Yes |

## Canonical source priority

- **Tier 1** (current-state): README_v1.md, SYSTEM_TECHNICAL_HANDBOOK_v1.md, SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md, SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md, DOCUMENTATION_VERIFICATION_MATRIX_v1.md, SYSTEM_IMPLEMENTATION_RECORD_v1.md
- **Tier 2** (governance addenda): system-orchestration.yaml
- **Tier 3** (collaborator-workflow role): README_LAYER2.md

README_LAYER2.md must not be used to overrule Tier 1 documents on implementation state, architecture, or limitations (CLAUDE.md §2.4). When cited outside its declared role, set `source_authority_conflict_detected: true`.

## Matrix classification vocabulary

| Classification | Meaning |
|---|---|
| `Verified in current documentation set` | Tier 1 docs make a direct, stable, cross-doc-consistent claim |
| `Documented current-state claim` | Current docs describe as current-state; depends on project-owned evidence |
| `Planned / target architecture` | Future/downstream design; not current implementation |
| `Cannot verify from current materials` | Docs do not support a stronger statement |

## Matrix sections

| Section | Content |
|---|---|
| 3 | Current Layer-2 Contract Items |
| 4 | Current Known Open Items |
| 5 | Future / Target Architecture Items |
| 6 | Publication Event Classification |
| 7 | Layer-3 Philosophy and Schema Classification |
| 8 | Document Role Classification |

## Matrix update rules

- **MU-1 Classification update**: Claim moves between classification levels. Requires cross-doc Tier 1 consistency for upgrades; doc-only changes cannot upgrade runtime status.
- **MU-2 Source priority update**: Governing source precedence changed or needs clarification.
- **MU-3 Contradiction note**: Two+ governing docs disagree; record the unresolved state.
- **MU-4 Status review**: Evidence posture changed enough for manual review but not automatic reclassification.
- **MU-5 Add new entry**: New governance-critical topic the matrix does not track.
- **MU-6 Remove stale entry**: Entry explicitly superseded by traceable governance source.
- **MU-7 No change after review**: Change touched related areas but existing classification remains valid.

## Deterministic rules

- **DR-1**: Doc-only changes must not upgrade runtime status. Set `runtime_status_upgrade_blocked: true` if blocked.
- **DR-2**: Blocked guard attempts flow into contradiction check only, not classification updates.
- **DR-3**: Upgrading to `Verified in current documentation set` requires all Tier 1 docs consistent; no single doc suffices.
- **DR-4**: Target-state demotion only with explicit governance evidence.
- **DR-5**: Source authority conflict prevents settled updates; use `review_only` or `contradiction_note`.
- **DR-6**: README_LAYER2 authority conflict is always reported when it is cited as canonical.
- **DR-7**: New governance artifacts require Section 8 entry assessment.
- **DR-8**: Fail closed on ambiguous direction — default to `status_review`.

## Decision procedure

1. **Extract signals** from upstream inputs (claim scopes, blocking conditions, guard results, contradiction flags, impact type, doc update plan).
2. **Determine if matrix is affected**: classification change → MU-1; new claim → MU-5; source authority change → MU-2; contradiction → MU-3; ambiguous evidence → MU-4; no implications → MU-7.
3. **Identify affected entries** by section and entry name.
4. **Classify each entry's change type** using MU-1 through MU-7.
5. **Assess runtime upgrade risk**: block doc-only upgrades, set `runtime_status_upgrade_blocked: true`.
6. **Detect source-authority conflicts**: apply README_LAYER2 role constraint; surface contradictions.
7. **Set matrix_action**: `update` (edits required), `review_only` (manual review needed), or `no_change` (confirmed accurate).
8. **Populate summary flags** and `unresolved_conflicts`.

## Output schema

Return a single JSON object:

```json
{
  "verification_matrix_delta": {
    "matrix_action": "update | review_only | no_change",
    "inference_used": false,
    "affected_entries": [
      {
        "entry_id": "string (section + short topic key, e.g. s3-snapshot-handoff-gate)",
        "section": "string (e.g. Section 3 — Current Layer-2 Contract Items)",
        "claim_or_topic": "string",
        "change_type": "classification_update | source_priority_update | contradiction_note | status_review | add_new_entry | remove_stale_entry | no_change_after_review",
        "reason": "string (specific, traceable)",
        "source_documents": ["string"],
        "proposed_old_state": "string (exact vocabulary; null for add_new_entry)",
        "proposed_new_state": "string (exact vocabulary; null for remove_stale_entry or status_review)",
        "confidence": "high | medium | low"
      }
    ],
    "summary": {
      "matrix_update_required": true,
      "current_vs_target_relabel_needed": false,
      "source_authority_conflict_detected": false,
      "runtime_status_upgrade_blocked": false,
      "unresolved_conflicts": [],
      "notes": []
    }
  }
}
```

## Completion standard

The output must satisfy: all upstream inputs consumed (absent ones flagged), `matrix_action` traceable to signals, every affected entry has section/change_type/reason/source_documents/confidence, classification vocabulary used exactly, no doc-only upgrades without cross-doc consistency, README_LAYER2 conflicts reported, contradictions surfaced not resolved, skill has not updated ledger or acted as hook, output is valid JSON, verdict is deterministic.
