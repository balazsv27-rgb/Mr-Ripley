---
name: snapshot-contract-check
description: Validate whether a requested implementation, documentation change, architecture statement, or agent action preserves the Layer-2 → Layer-3 snapshot contract boundary. Determines whether downstream logic consumes only governed published snapshots, never raw Layer-2 observations. Use after doc-truth-classification and build-sequence-compliance-check, and before snapshot-boundary-guard, deep audit routing, and change-impact analysis.
disable-model-invocation: false
---

You are the `snapshot-contract-check` skill — a **contract-validation method**.

Determine whether a requested change, claim, or documentation update preserves the invariant that Layer-3+ logic consumes only governed published snapshots, never raw Layer-2 `observations`.

Not a phase-gating skill (`build-sequence-compliance-check`) or truth classifier (`doc-truth-classification`). Emits a structured contract-compliance verdict for downstream hooks/guards.

Procedure: (1) extract contract-relevant claims, (2) evaluate against invariants, (3) classify each as `compliant`/`blocked`/`ambiguous`, (4) emit structured result.

---

## Governing assumptions

- Snapshot-only downstream read rule is a **current-state invariant** — applies now.
- `observations` is Layer-2-internal. No downstream component may query it.
- Valid interfaces: **DB** (`snapshots` by `snapshot_id` + join `snapshot_values`), **File** (`latest_snapshot.json`).
- Forbidden interface: any direct `observations` query by Layer-3+.
- `snapshot_id` is the primary contract anchor; every DecisionPacket must carry `snapshot_id` and `snapshot_clock_ts`.
- Live Market State / Event Risk Stream are governed Layer-3 inputs but may not touch Layer-2 storage or rewrite Snapshot Truth.
- Handoff gate satisfied = Layer-3 bootstrap **may begin**. Does NOT relax any invariant or permit direct observation access.
- Applies equally to code, docs, and architectural claims. Docs implying forbidden access are blocked identically to code.

---

## Canonical source priority

**Tier 1** (primary): `SYSTEM_TECHNICAL_HANDBOOK_v1.md` (invariants 5-6, DecisionPacket anchors), `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` (bootstrap rule, governed inputs, storage isolation), `README_v1.md` (system identity).

**Tier 2** (supporting): `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md`.

**Tier 3** (collaborator role only): `README_LAYER2.md` — corroboration of Tier 1 only; never standalone contract authority.

**CLAUDE.md** Section 6 defines the snapshot contract as non-negotiable.

---

## Arguments

Defaults: `scope=request-and-contract`, `mode=strict`, `report=json`.

- `scope`: `auto` | `request-only` | `request-and-contract`
- `mode`: `strict` (fail closed on ambiguity) | `audit` (expanded notes) | `light` (triage only)
- `targets`: comma-separated focus hints (e.g. `Layer-3,observations`)
- `report`: `json` | `json+summary`

---

## Inputs

Expects: request text/claims, optionally `request_classification` from doc-truth-classification, `phase_alignment_status` from build-sequence-compliance-check. Infer conservatively if upstream outputs are absent.

---

## Invariants (non-negotiable)

| ID | Rule | Source |
|---|---|---|
| SCC-1 | Layer-3 consumes snapshots, never raw `observations` | Handbook Inv 5; Architecture s7 |
| SCC-2 | Every DecisionPacket carries `snapshot_id` + `snapshot_clock_ts` | Handbook Inv 6, s7 |
| SCC-3 | Live Market State / Event Risk Stream may not touch Layer-2 storage | Handbook s2; Architecture s7 |
| SCC-4 | Snapshot Truth is immutable — Layer-3 may not rewrite it | Architecture s7 |
| SCC-5 | Event Risk Stream may not generate direction by itself | Architecture s7 |
| SCC-6 | Handoff gate satisfaction does not relax any invariant | Handbook s5; Architecture s5 |

## Forbidden patterns

| ID | Pattern | Violates |
|---|---|---|
| FP-1 | `SELECT ... FROM observations` by Layer-3+ | SCC-1 |
| FP-2 | Bypassing `snapshot_id` to read latest observation row | SCC-1, SCC-2 |
| FP-3 | DecisionPacket without `snapshot_id` / `snapshot_clock_ts` | SCC-2 |
| FP-4 | Live/Event inputs writing to `observations`/`snapshots`/`snapshot_values` | SCC-3 |
| FP-5 | Layer-3 mutating snapshot records | SCC-4 |
| FP-6 | Event Risk Stream producing non-NO_TRADE action alone | SCC-5 |
| FP-7 | Docs implying forbidden access is permitted | SCC-1+ |

## Valid interfaces

1. **Snapshot DB**: `SELECT * FROM snapshots WHERE snapshot_id = ? JOIN snapshot_values` — for replay, truth base, anchoring.
2. **Latest snapshot file**: `latest_snapshot.json` (fields: snapshot_id, engine_version, config_version, clock_ts, verdict, tier1_series, tier2_series, missing_series) — for bootstrap, handoff reads.

---

## Decision procedure

1. **Extract claims** touching snapshot access, observation access, Layer-2 storage, DecisionPacket fields, Live/Event interactions, or docs about what Layer-3 may read. No contract claims found → emit `compliant`.
2. **Evaluate each** against SCC-1–6 and FP-1–7. Classify as `compliant`, `blocked`, or `ambiguous`.
3. **Mode behavior**: `strict` promotes `ambiguous` → `blocked` (`ambiguous_requires_block`); `audit` leaves `ambiguous` with notes; `light` flags only.
4. **valid_interface**: `snapshot_db` | `latest_snapshot_json` | `both` | `none`.
5. **snapshot_anchor_required**: `true` if request touches DecisionPacket generation.
6. **Risk flags**: `raw_observations_access_risk`, `snapshot_bypass_risk`, `layer2_storage_touch_risk`, `decisionpacket_anchor_risk`.
7. **Overall**: `compliant` (all pass) | `boundary_violation` (any blocked) | `ambiguous_requires_block`. `allowed: true` only when `compliant`.
8. **blocking_reason_if_any**: name specific SCC/FP violated. Every blocked/ambiguous claim needs `contract_reference`.

---

## Blocking rules

- **B1**: Layer-3 reads `observations` → block, cite SCC-1/FP-1, set `forbidden_access_detected: true`
- **B2**: Raw "latest" read without snapshot_id → block, cite SCC-1/SCC-2/FP-2
- **B3**: DecisionPacket without snapshot_id → block, cite SCC-2/FP-3
- **B4**: Live/Event writes to Layer-2 storage → block, cite SCC-3/FP-4
- **B5**: Layer-3 mutates snapshots → block, cite SCC-4/FP-5
- **B6**: Event Risk Stream as directional authority → block, cite SCC-5/FP-6
- **B7**: Doc implying forbidden access permitted → block, cite relevant SCC/FP-7
- **B8**: Ambiguous access in strict mode → block, `ambiguous_requires_block`, cite SCC-1
- **C1**: Reads via `snapshot_id` or `latest_snapshot.json` without mutation → compliant
- **C2**: Live/Event as read-only governed inputs not touching Layer-2 → compliant

---

## Output format

```json
{
  "snapshot_contract_status": {
    "allowed": true,
    "contract_status": "compliant | boundary_violation | ambiguous_requires_block",
    "valid_interface": "snapshot_db | latest_snapshot_json | both | none",
    "forbidden_access_detected": false,
    "snapshot_anchor_required": true,
    "blocking_reason_if_any": null,
    "checked_claims": [
      {
        "claim_id": "c1",
        "claim_text": "string",
        "assessment": "compliant | blocked | ambiguous",
        "violated_invariants": [],
        "triggered_forbidden_patterns": [],
        "valid_interface_if_compliant": "snapshot_db | latest_snapshot_json | both | none",
        "reason": "string",
        "contract_reference": ["SCC-1", "FP-1"]
      }
    ],
    "summary": {
      "raw_observations_access_risk": false,
      "snapshot_bypass_risk": false,
      "layer2_storage_touch_risk": false,
      "decisionpacket_anchor_risk": false,
      "followup_guard_recommended": true
    }
  }
}
```

**Key rules**: `allowed` is `true` only when `contract_status` is `compliant`. `blocking_reason_if_any` is non-null whenever `allowed` is `false`. `followup_guard_recommended` is `true` on `boundary_violation` or `ambiguous_requires_block`. `README_LAYER2.md` is corroboration only, never primary authority. The verdict must be deterministic.
