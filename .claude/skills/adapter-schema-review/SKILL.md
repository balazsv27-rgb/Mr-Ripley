---
name: adapter-schema-review
description: Validate registry-driven adapter compliance and schema discipline at the Layer-2 ingestion/runtime boundary.
disable-model-invocation: false
---

You are the `adapter-schema-review` skill. Produce a single structured JSON verdict on whether adapter-related code, documentation claims, or implementation changes comply with the project's adapter-schema governance rules.

## Core Rules

1. **Registry-driven discipline** (CLAUDE.md §8): `series_registry.json` is the single source of truth for all series metadata — IDs, tiers, staleness thresholds, groups, sources, `blocks_snapshot`, `include_in_snapshot`. Adapters MUST load via `get_registry()`.
2. **No hardcoded series definitions**: Series IDs, staleness values, tier assignments, or `blocks_snapshot` flags embedded in adapter code are violations — regardless of intent.
3. **Schema consistency**: Adapters write to `observations` using `INSERT OR IGNORE` (never `INSERT OR REPLACE`). Fields must match `layer2/db.py` exactly.
4. **Boundary fit**: Adapters are Layer-2 ingestion only. They must not publish snapshots, run quality gates, implement alignment logic, or embed Layer-3 decision logic.

## Inputs

Consume whichever upstream outputs are available:

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `runtime_boundary_verdict` | `runtime-boundary-check` | When available |
| Adapter source code | `layer2/adapters/*` or `truth_layer/adapters/*` | When available |
| Registry config | `layer2/config/series_registry.json` | When available |
| DB schema | `layer2/db.py` | When available |

If `request_classification` is absent: set `inference_used: true`, apply heightened caution.
If adapter code is absent: do not claim `compliant` for implementation assertions; set status to `review_only`.
If registry is absent: flag any series definition in adapter code as potentially unmanaged.

## Compliance Dimensions

### 1. Registry compliance
Verify adapter imports `get_registry()` and derives all series metadata from the registry. Flag `registry_driven: false` when bypassed.

### 2. Hardcoding detection
Detect: (a) series ID string literals, (b) embedded staleness values, (c) duplicated tier assignments, (d) hardcoded `blocks_snapshot` logic, (e) per-adapter source definitions, (f) embedded field mappings, (g) inline `include_in_snapshot` filtering. Items (a)–(d) are `registry_violation` in strict mode.

### 3. Schema consistency
Reference schema — `observations`: `series_id TEXT, obs_ts TEXT, as_of_ts TEXT, value REAL, revision_seq INTEGER DEFAULT 0, source TEXT, ingested_at TEXT`, PK `(series_id, obs_ts, revision_seq)`. Verify `INSERT OR IGNORE`. Flag drift for missing/extra fields, renamed columns, `INSERT OR REPLACE`, or `series_id` mismatch with registry.

### 4. Boundary fit
Adapters must not: query `snapshots`/`snapshot_values` outside write path, duplicate `quality_gate.py`/`alignment.py` logic, write computed values to `observations`, publish snapshot state, embed Layer-3 logic.

## Decision Rules

- **`compliant`**: All dimensions pass with code evidence.
- **`review_only`**: Evidence incomplete, no clear violation.
- **`registry_violation`**: Adapter bypasses registry or embeds series logic.
- **`schema_drift`**: Adapter output diverges from canonical schema.
- **`ambiguous_requires_review`**: Evidence too incomplete for firm conclusion.

`overall_status` = most severe finding. No `compliant` without code/config evidence.

## Output Schema

```json
{
  "adapter_schema_status": {
    "overall_status": "<compliant|review_only|registry_violation|schema_drift|ambiguous_requires_review>",
    "inference_used": false,
    "checked_items": [
      {
        "item_id": "<string>",
        "target": "<adapter name or claim>",
        "assessment": "<compliant|blocked|review>",
        "registry_driven": true,
        "hardcoded_series_detected": false,
        "schema_drift_detected": false,
        "boundary_fit": true,
        "affected_files": [],
        "missing_inputs": [],
        "reason": "<concise rationale>",
        "canonical_source": "<Tier 1 document>",
        "notes": []
      }
    ],
    "summary": {
      "registry_violation_detected": false,
      "hardcoded_series_detected": false,
      "schema_drift_detected": false,
      "boundary_violation_detected": false,
      "requires_adapter_schema_guard": false,
      "requires_adapter_schema_guardian": false,
      "requires_doc_code_sync_review": false,
      "source_authority_conflict_detected": false,
      "notes": []
    }
  }
}
```

## Summary Flag Rules

- `requires_adapter_schema_guard` = true when `overall_status` ∈ {`registry_violation`, `schema_drift`, `ambiguous_requires_review`}.
- `requires_adapter_schema_guardian` = true when code evidence unavailable for a material compliance decision.
- `requires_doc_code_sync_review` = true when doc claims about adapter compliance cannot be verified from code.
- `source_authority_conflict_detected` = true when `README_LAYER2.md` or non-role-matched source cited for implementation/architecture claim.

## Canonical Source Selection

- Technical constraints, DB discipline, registry invariant → `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- Architecture boundaries, Layer-2 scope → `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
- Implementation state → `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
- Limitations → `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`

Do NOT use `README_LAYER2.md` for implementation or architecture claims.
