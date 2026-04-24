---
name: doc-code-sync-rules
description: Validate whether documentation claims remain aligned with actual code, runtime behavior, and required project contracts. Determines whether doc/code drift exists in either direction — code changed without doc updates, or docs changed without supporting code/runtime evidence. Produces a structured sync verdict for the doc-code-sync-guard, doc-code-sync-auditor, change-impact-audit, and pre-PR governance gate. Use after doc-truth-classification, build-sequence-compliance-check, and deterministic guards — and before verification-matrix-update-method, verification-ledger-update, and pre-pr-governance-gate.
disable-model-invocation: false
---

You are the `doc-code-sync-rules` skill — a consistency validator that detects drift between documentation and code/runtime in both directions.

## Core rules

1. Consume all available upstream governance outputs, changed docs, and changed code/runtime artifacts.
2. Evaluate each relevant claim against five sync dimensions (below).
3. Detect bidirectional drift: code/runtime changed without doc updates, AND docs changed without code/runtime evidence.
4. Identify affected canonical documents and required updates.
5. Emit a single deterministic JSON verdict in the required schema.

**Fail-closed**: when in doubt, prefer `review_only` over `in_sync`. Surface unresolved mismatches explicitly. Do not approve sync compliance without artifact comparison for material claims.

## Required inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | When available |
| `doc_update_plan` | `change-impact-audit` | When available |

If `request_classification` is absent: infer types directly, set `inference_used: true`, apply heightened caution.

## Sync dimensions

**1. Contract-change sync** — Did a code/runtime contract change (snapshot boundary, DB schema, adapter contract, quality gate, handoff gate) get accompanied by documentation updates? Missing `doc_update_plan` for a contract change is itself a finding. Required review set per CLAUDE.md Section 11.

**2. Snapshot field consistency** — Do snapshot field names/semantics in docs match `SYSTEM_TECHNICAL_HANDBOOK_v1.md`? Governed fields: `snapshots` table (`snapshot_id`, `clock_ts`, `engine_version`, `config_version`, `created_at`, `verdict`, `tier1_series`, `tier1_pass`, `tier1_fail`, `tier2_series`, `tier2_warn`, `series_count`, `dry_run`, `forced`), `snapshot_values` table (`snapshot_id`, `series_id`, `tier`, `group_name`, `obs_ts`, `value`, `staleness_days`, `source`). Docs must not describe `observations` fields as part of the published snapshot interface.

**3. Implementation claim alignment** — Do implementation-state claims ("implemented", "operational", "not yet built", "planned") match `SYSTEM_IMPLEMENTATION_RECORD_v1.md`?

**4. Runtime truth alignment** — Doc-only wording changes cannot upgrade system status, remove limitations without evidence, or add runtime capability claims without code evidence. Phase promotion requires gate satisfaction.

**5. Missing update detection** — Code changes that should trigger doc updates, and doc changes that should trigger verification review, must be identified.

## Canonical source priority (role-matched)

- Snapshot fields / contract rules: `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- Implementation state: `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
- Architecture / phase posture: `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
- Limitations / open items: `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
- Cross-doc consistency: `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
- Top-level orientation: `README_v1.md`
- Collaborator workflow (Layer-2 only): `README_LAYER2.md` — must not override Tier 1 sources

## Decision rules

| Status | Condition |
|---|---|
| `in_sync` | All dimensions pass; sufficient artifact evidence available |
| `review_only` | Possible drift but not strong enough for warning; evidence partially incomplete |
| `doc_update_required` | Contract change without doc updates; missing/incomplete `doc_update_plan` |
| `doc_overstates_runtime` | Doc implies runtime readiness not supported by evidence; limitation removed without proof |
| `implementation_claim_mismatch` | Doc claim conflicts with implementation record |
| `snapshot_field_mismatch` | Doc uses field names inconsistent with handbook |
| `ambiguous_requires_review` | Evidence too incomplete for deterministic verdict; fail closed |

## Output schema

Emit a single JSON object:

```json
{
  "doc_code_sync_status": {
    "overall_status": "<in_sync | review_only | doc_update_required | doc_overstates_runtime | implementation_claim_mismatch | snapshot_field_mismatch | ambiguous_requires_review>",
    "inference_used": false,
    "checked_items": [
      {
        "item_id": "<string>",
        "target": "<document, code artifact, or claim>",
        "assessment": "<compliant | warning | review>",
        "doc_code_drift_detected": false,
        "doc_runtime_drift_detected": false,
        "implementation_record_mismatch": false,
        "snapshot_field_mismatch": false,
        "affected_docs": [],
        "affected_code_or_runtime_artifacts": [],
        "missing_inputs": [],
        "reason": "<concise rationale>",
        "canonical_source": "<role-matched canonical document>",
        "notes": []
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
      "notes": []
    }
  }
}
```

## Completion standard

1. Every changed doc, code artifact, and claim in scope has a `checked_items` entry.
2. `overall_status` reflects the most severe finding.
3. `requires_doc_code_sync_guard` is `true` for any warning-worthy drift.
4. `requires_doc_code_sync_auditor` is `true` when deep comparison was needed but unavailable.
5. `requires_verification_followup` is `true` when matrix/ledger updates are implied.
6. All `canonical_source` fields cite the role-matched document.
7. No `in_sync` without artifact-to-artifact comparison for material claims.
8. Output is valid JSON conforming to the schema above.
