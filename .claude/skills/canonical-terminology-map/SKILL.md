---
name: canonical-terminology-map
description: Enforce consistent canonical terminology across documentation, governance outputs, and implementation-facing descriptions. Produces a compact normalized_terminology_map artifact for downstream consumption.
disable-model-invocation: false
---

You are the `canonical-terminology-map` skill.

Your job is to check whether the request and upstream artifacts use the project's canonical terminology consistently, and produce a compact normalization map. You detect variant drift, synonym substitution, and governance-sensitive term conflicts.

This skill is a **normalization method only**. It does not perform downstream audit, filename migration planning, doc-code sync, verification updates, or governance reconciliation. Those are handled by later steps.

## Core rules

- **One canonical term per governed concept.** Where the project has an established canonical term, that term must be preferred. Variants are acceptable only when explicitly listed as allowed.
- **Do not invent new canonical terms.** Flag unrecognized terms as such rather than silently adopting them.
- **Ambiguity is a finding.** When one term is used for two governed concepts, or two terms for one concept, flag it.
- **Governance-sensitive drift is severe.** Terminology drift that changes how claims are classified (snapshot boundary, evidence status, phase meaning, decision vocabulary) must be flagged as governance-sensitive.
- **Be conservative.** Prefer `review_only` over approving a potentially drifted term.

## Inputs

Consume whichever upstream artifacts are available:
- `claim_classification_map` — classified claims from prior step
- `governance_context` — constitutional rules and run metadata

If `claim_classification_map` is absent or empty, evaluate terminology directly from any request text in `governance_context` and set `inference_used: true`.

## Canonical term table

Each entry: concept ID, canonical term, allowed variants, discouraged variants.

### System identity and architecture

| ID | Canonical | Allowed | Discouraged |
|---|---|---|---|
| `SYSTEM_IDENTITY` | `gold-first, fail-closed, snapshot-based decision support system` | `gold-first engine`, `Mr. Ripley system` | `live system`, `trading system`, `automated execution system` |
| `LAYER_2` | `Layer-2` | `Layer 2` (prose) | `truth layer`, `data layer`, `L2` |
| `LAYER_3` | `Layer-3` | `Layer 3` (prose) | `decision engine`, `signal layer`, `L3` |
| `SNAPSHOT_TRUTH` | `Snapshot Truth` | — | `snapshot state`, `current truth`, `live truth` |
| `LIVE_MARKET_STATE` | `Live Market State` | — | `live state`, `market state`, `real-time state` |
| `EVENT_RISK_STREAM` | `Event Risk Stream` | — | `event stream`, `risk events` |

### Snapshot boundary

| ID | Canonical | Allowed | Discouraged |
|---|---|---|---|
| `SNAPSHOT` | `snapshot` | `published snapshot` | `data pull`, `observation snapshot`, `latest data` |
| `SNAPSHOT_ID` | `snapshot_id` | — | `snap_id`, `snapshot key` |
| `LATEST_SNAPSHOT` | `latest_snapshot.json` | — | `latest snapshot`, `snapshot file`, `current snapshot` |
| `SNAPSHOT_VALUES` | `snapshot_values` | — | `snapshot data`, `snap values` |
| `SNAPSHOTS_TABLE` | `snapshots` | — | `snapshot metadata`, `snapshot table` |
| `OBSERVATIONS` | `observations` | — | `raw data`, `obs`, `Layer-2 data` |
| `SNAPSHOT_CONTRACT` | `snapshot contract` | `handoff contract` | `snapshot spec`, `snapshot interface` |

### Decision layer

| ID | Canonical | Allowed | Discouraged |
|---|---|---|---|
| `NO_TRADE` | `NO_TRADE` | — | `no-trade`, `no trade`, `hold-fire`, `HOLD`, `neutral` |
| `DECISION_PACKET` | `DecisionPacket` | — | `decision payload`, `decision output`, `decision struct` |
| `GUARD_TAXONOMY` | `guard taxonomy` | — | `guard list`, `guard rules` |
| `STATE_TAXONOMY` | `state taxonomy` | — | `state types`, `state list` |
| `TRIGGER_TAXONOMY` | `trigger taxonomy` | — | `trigger list`, `trigger types` |

### Phase and build-sequence

| ID | Canonical | Allowed | Discouraged |
|---|---|---|---|
| `PHASE_A` | `Phase A` | — | `phase 1`, `ingestion phase` |
| `PHASE_B` | `Phase B` | — | `phase 2`, `bootstrap phase` |
| `PHASE_C` | `Phase C` | — | `phase 3`, `buildout phase` |
| `PHASE_D` | `Phase D` | — | `phase 4`, `execution phase`, `live phase` |
| `HANDOFF_GATE` | `Layer-2 → Layer-3 handoff gate` | `handoff gate` | `Layer-2 done`, `Layer-3 ready to start` |

### Layer-2 technical vocabulary

| ID | Canonical | Allowed | Discouraged |
|---|---|---|---|
| `SERIES_REGISTRY` | `series_registry.json` | `registry`, `series registry` | `series config`, `series list` |
| `FAIL_CLOSED` | `fail-closed` | — | `fail safe`, `fail-safe` |
| `GOLD_FIRST` | `gold-first` | — | `gold focused`, `XAU first` |
| `INSERT_OR_IGNORE` | `INSERT OR IGNORE` | — | `upsert`, `INSERT OR REPLACE` |
| `CLOCK_TS` | `clock_ts` | — | `timestamp`, `snap_ts` |
| `AS_OF` | `as_of` | `as_of_ts` | `publish time`, `truth time` |
| `VERDICT` | `verdict` | — | `status`, `result`, `outcome` |
| `TIER1_PASS` | `tier1_pass` | — | `t1_pass`, `tier 1 pass count` |
| `TIER1_FAIL` | `tier1_fail` | — | `t1_fail`, `tier 1 fail count` |

### Evidence and verification

| ID | Canonical | Allowed | Discouraged |
|---|---|---|---|
| `EVIDENCE_PROVEN` | `proven` | — | `confirmed`, `verified`, `validated` |
| `EVIDENCE_SUPPORTED` | `supported` | — | `backed`, `evidenced` |
| `EVIDENCE_UNVERIFIED` | `unverified` | — | `pending`, `not verified` |
| `EVIDENCE_CONTRADICTED` | `contradicted` | — | `disproven`, `rejected`, `wrong` |

### Implementation-state vocabulary

| ID | Canonical | Allowed | Discouraged |
|---|---|---|---|
| `IMPL_OPERATIONAL` | `operational` | `implemented`, `built` | `live`, `production`, `running in production` |
| `IMPL_NOT_BUILT` | `not yet built` | `not built`, `open item` | `pending`, `TBD`, `in progress` |
| `IMPL_PLANNED` | `planned` | `target architecture` | `designed`, `specified` |
| `IMPL_BLOCKED` | `blocked` | — | `disabled`, `gated`, `not enabled` |

## Governance-sensitive categories

Flag as `governance_sensitive: true` when drift falls in these categories:

- **A: Snapshot boundary** — conflating `snapshot` with `observations`, weakening `Snapshot Truth` semantics
- **B: Phase/readiness** — using `live` where `operational` is correct, weakening `blocked` to `not enabled`
- **C: Evidence status** — conflating `proven` and `supported`, using `verified` as a status term
- **D: Decision vocabulary** — any variant of `NO_TRADE`, non-PascalCase `DecisionPacket`

## Output schema

Produce a single JSON object as the `normalized_terminology_map` artifact. Keep it compact and deterministic.

```json
{
  "produced_by": "normalize-terminology",
  "overall_status": "<compliant | review_only | normalization_required | ambiguity_detected | governance_sensitive_term_conflict>",
  "inference_used": false,
  "canonical_term_mappings": [
    {
      "from": "<observed non-canonical form>",
      "to": "<canonical form>",
      "concept_id": "<ID from canonical term table>",
      "reason": "<brief reason>"
    }
  ],
  "scope_constraints": ["<what was in scope for this check>"],
  "excluded_reference_types": ["<what was excluded or unavailable>"],
  "filename_rename_candidates": ["<files where terminology changes would apply>"],
  "ambiguity_flags": [
    {
      "term": "<ambiguous term>",
      "concepts": ["<concept IDs it maps to>"],
      "governance_sensitive": false,
      "note": "<brief description>"
    }
  ]
}
```

### Field rules

- `overall_status` reflects the most severe finding: `governance_sensitive_term_conflict` > `ambiguity_detected` > `normalization_required` > `review_only` > `compliant`.
- `canonical_term_mappings` contains every detected non-canonical variant with its canonical resolution. Empty array if all terms are compliant.
- `scope_constraints` lists what was evaluated (e.g., "request text", "claim_classification_map claims").
- `excluded_reference_types` lists what was not available (e.g., "canonical documents not read directly").
- `filename_rename_candidates` lists filenames or artifact names that contain non-canonical terms. Empty if none.
- `ambiguity_flags` lists cases where one term maps to multiple concepts or multiple terms map to one concept. Empty if none.
- `inference_used` is `true` only when `claim_classification_map` was absent/empty and scope was inferred.

### Decision rules

- **`compliant`**: All terms canonical or acceptable variants. No ambiguity. No governance-sensitive drift.
- **`review_only`**: Mostly acceptable but context incomplete, or casual variants in non-governance contexts.
- **`normalization_required`**: Clear non-canonical variants where canonical form should apply.
- **`ambiguity_detected`**: One term for multiple concepts, or multiple terms for one concept.
- **`governance_sensitive_term_conflict`**: Drift that would change how claims are classified, routed, or enforced by downstream governance steps.
