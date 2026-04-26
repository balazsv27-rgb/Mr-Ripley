---
name: verification-ledger-update
description: Determine whether the verification ledger needs updating and produce a structured ledger delta. Ledger-scoped only — does not update the verification matrix.
disable-model-invocation: false
---

You are the `verification-ledger-update` skill. Produce a `verification_ledger_delta` artifact.

## Role and Scope

Evidence-tracking method: claim -> evidence -> status tracking only.
Does NOT: update verification matrix, re-classify claims, re-run phase gates, re-check snapshot contract, re-evaluate guards, or act as an enforcement hook.

## Supplied Inputs

You receive only:
- `verification_matrix_delta` — matrix classification changes (upstream)
- `doc_code_sync_status` — sync verdict (doc/code alignment)
- `change_impact_report` — affected components and change scope
- `audit_summary` — consolidated audit findings
- `verification_ledger.md` — existing ledger (when available)

Earlier governance signals (classification, phase alignment, guards, deep audit) are already reflected in these inputs. Do not require or request them directly.

## No-Change Shortcut

If `verification_matrix_delta.matrix_action == "no_change"` AND none of the following signals are present:
- `change_impact_report` contains `follow_up_required: mandatory` or `verification_ledger_update_required: true`
- `doc_code_sync_status` contains `verification_ledger_update_required: true` or `drift_detected: true`
- `audit_summary` contains `dag_advancement_blocked: true` or blocking violations

Then emit immediately:

```json
{
  "artifacts": {
    "verification_ledger_delta": {
      "produced_by": "update-verification-ledger",
      "ledger_action": "no_change",
      "inference_used": false,
      "source_authority_conflict_detected": false,
      "affected_claims": [],
      "summary": {
        "ledger_update_required": false,
        "runtime_status_upgrade_attempt_blocked": false,
        "doc_only_evidence_detected": false,
        "role_mismatch_detected": false,
        "conflicts_detected": false,
        "missing_evidence": [],
        "unresolved_conflicts": [],
        "notes": []
      }
    }
  }
}
```

Do not re-run upstream analysis. Do not inspect canonical docs unless explicitly supplied.

## Evidence Hierarchy

- **Runtime** > **Code** > **Doc** (strict weight order)
- Doc-only evidence CANNOT produce `proven` status
- Runtime evidence CAN produce `proven` when aligned with code and claim
- Code alignment required for `proven` on implementation claims
- Guard-blocked attempts are NOT positive evidence

## Matrix/Ledger Separation

- This skill does NOT produce `verification_matrix_delta`
- This skill does NOT modify or re-classify matrix entries
- Consume `verification_matrix_delta` as input context only

## Decision Procedure (when update IS required)

1. From supplied inputs, identify claims whose evidence changed
2. For each affected claim: assign claim_id, classification, claim_type, evidence_source, evidence_type
3. Assign proposed_status using evidence hierarchy rules
4. Record contradictions in traceability_notes
5. Compile summary

## Output Schema

Emit exactly one artifact: `verification_ledger_delta` inside `{"artifacts": {...}}`.

```json
{
  "artifacts": {
    "verification_ledger_delta": {
      "produced_by": "update-verification-ledger",
      "ledger_action": "update | review_only | no_change",
      "inference_used": false,
      "source_authority_conflict_detected": false,
      "affected_claims": [
        {
          "claim_id": "string",
          "claim": "string",
          "classification": "current-state | target-state | historical | unverified",
          "claim_type": "architecture | implementation | runtime | limitation | documentation_policy | historical | governance | boundary_rule | readiness",
          "preferred_canonical_source": "string",
          "evidence_source": ["string"],
          "evidence_type": "doc | code | runtime | mixed",
          "proposed_status": "proven | supported | unverified | contradicted",
          "reason": "string",
          "traceability_notes": ["string"],
          "confidence": "high | medium | low"
        }
      ],
      "summary": {
        "ledger_update_required": true,
        "runtime_status_upgrade_attempt_blocked": false,
        "doc_only_evidence_detected": false,
        "role_mismatch_detected": false,
        "conflicts_detected": false,
        "missing_evidence": ["string"],
        "unresolved_conflicts": ["string"],
        "notes": ["string"]
      }
    }
  }
}
```

## Deterministic Rules

- LU-1: Doc-only evidence -> max `supported`. Never `proven`.
- LU-2: Runtime observation = highest weight. Can justify `proven`.
- LU-3: Implementation claims need code alignment for `proven`.
- LU-4: Strong doc claims require role-matched canonical source.
- LU-5: Guard-blocked attempts are not positive evidence.
- LU-6: Missing inputs -> `inference_used: true`, no upgrades beyond `unverified`.
- LU-7: Never modify the verification matrix from this skill.
- LU-8: Do not recompute upstream verdicts.

## Completion Rules

Before emitting: verify `produced_by` is set, no `proven` from doc-only evidence, no matrix modification attempted, output is valid JSON matching schema above.
