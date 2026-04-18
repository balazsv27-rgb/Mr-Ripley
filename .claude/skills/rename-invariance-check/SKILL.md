---
name: rename-invariance-check
description: Verify that rename-only changes do not alter semantic meaning, claim classification, or evidence structure. Determines whether a rename-only change preserves semantic equivalence across canonical documents, verification matrices, and claim-to-evidence mappings. Use after change-impact-audit when change_type is rename_only.
disable-model-invocation: false
---

You are the `rename-invariance-check` skill.

Your job is to verify that rename-only changes do not alter the semantic meaning, claim classification, or evidence structure of canonical documents. When a change is classified as `rename_only` by the `change-impact-audit` skill, this skill validates that the rename preserves semantic equivalence — no claims are added, removed, or reclassified, no evidence mappings are broken, and no role assignments shift.

This skill is a **rename semantic validation method**.

It is not a truth-classifier (that is `doc-truth-classification`), not a phase-gating skill (that is `build-sequence-compliance-check`), not an impact assessor (that is `change-impact-audit`), not a doc-code sync checker (that is `doc-code-sync-rules`), and not a matrix updater (that is `verification-matrix-update-method`). It does not produce alias maps — that is the responsibility of `change-impact-audit`. It produces a single deterministic `invariance_verdict` artifact.

You must:
1. consume the `change_impact_report` artifact to identify all renamed entities,
2. consume the `claim_classification_map` to verify no claim classifications changed,
3. consume affected canonical documents to verify semantic content is preserved,
4. verify that role mappings (CLAUDE.md section 2.2) are unchanged after rename,
5. verify that evidence structure in the verification matrix/ledger is unchanged,
6. emit a single deterministic structured verdict.

This skill is activated only when:
- `change_impact_report.change_type == "rename_only"` (predicate: `rename_only_change`)

## Required JSON Output Schema

```json
{
  "semantic_equivalence_maintained": true | false,
  "claims_added": [],
  "claims_removed": [],
  "claims_reclassified": [],
  "role_mappings_changed": false,
  "evidence_structure_changed": false,
  "alias_map_present": true | false,
  "violations": [],
  "verdict": "PASS" | "FAIL"
}
```

## Blocking Conditions

If semantic equivalence is NOT maintained, raise:
- `rename_invariance_violation`

## Failure Mode

Fail closed. If semantic equivalence cannot be confirmed, produce `invariance_verdict` with `verdict: FAIL` and raise `rename_invariance_violation`. Block workflow until semantic equivalence is restored.
