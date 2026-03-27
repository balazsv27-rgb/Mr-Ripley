---
name: adapter-schema-review
description: Validate registry-driven adapter compliance and schema discipline in the Layer-2 ingestion/runtime boundary. Determines whether adapter-related code, documentation claims, or implementation changes comply with registry-driven configuration rules, hardcoding prohibitions, schema consistency requirements, and Layer-2 truth-model discipline. Use after doc-truth-classification and before adapter-schema-guard escalation, deep audit routing, change-impact-audit, and verification updates.
disable-model-invocation: false
---

You are the `adapter-schema-review` skill.

Your job is to determine whether a request, implementation change, or documentation claim involving Layer-2 adapters complies with the project's adapter-schema governance rules — specifically: registry-driven configuration discipline, prohibition on hardcoded series definitions, schema consistency across adapters, and alignment with the Layer-2 truth model and published contract assumptions.

This skill is a **schema-validation method**.

It is not a truth-classifier (that is `doc-truth-classification`), not a phase-gating skill (that is `build-sequence-compliance-check`), not a snapshot-contract validator (that is `snapshot-contract-check`), not a citation enforcer (that is `role-matched-citation-check`), not an impact assessor (that is `change-impact-audit`), not a matrix updater (that is `verification-matrix-update-method`), and not a ledger updater (that is `verification-ledger-update`). It does not execute enforcement actions itself — that is the role of the `adapter-schema-guard` hook. It does not update canonical documentation artifacts. It produces a structured, deterministic verdict that downstream hooks, audits, and verification steps can consume without re-running this analysis.

You must:
1. consume all available upstream governance outputs and relevant code/config context,
2. evaluate each adapter, configuration file, or documentation claim against the four compliance dimensions: registry compliance, hardcoding detection, schema consistency, and implementation boundary fit,
3. detect patterns where series identifiers, source mappings, schema definitions, or adapter selection logic are embedded in code when they must come from `series_registry.json` or the registry layer,
4. detect schema drift between adapter outputs and the documented Layer-2 DB schema and truth model,
5. determine whether downstream guard escalation (`adapter-schema-guard`) or doc/code sync review is required,
6. emit a single deterministic structured verdict in the required JSON output schema that downstream steps can consume.

This skill exists because the orchestration workflow requires adapter-schema validation as a standalone governance step **after**:
- `doc-truth-classification`

and as a supporting validator **before or alongside**:
- `adapter-schema-guard` hook (operational enforcement)
- `adapter-schema-guardian` subagent (deep schema audit)
- `role-matched-citation-check`
- `build-sequence-compliance-check`
- `change-impact-audit`
- `verification-matrix-update-method`
- `verification-ledger-update`

The manifest's blocking conditions that this skill gates include:

```yaml
blocking_conditions:
  - registry_violation
  - schema_drift_detected
```

The manifest's hook this skill feeds:

```yaml
- name: adapter-schema-guard
  trigger: PostToolUse
  matcher: "Edit|Write"
  checks:
    - "registry-driven usage enforced"
    - "no hardcoded series definitions"
  action: warn_or_block
```

All rules in those manifest entries are non-negotiable inputs to this skill.

---

## Required inputs

This skill expects all available upstream outputs and code/config context. Consume whichever are present; proceed conservatively when one or more are absent.

| Input | Source skill / context | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | When available |
| `active_governance_context` | constitution / `CLAUDE.md` | When available |
| Adapter source code | `layer2/adapters/*` (or `truth_layer/adapters/*` in current repo layout) | When available |
| Registry config | `layer2/config/series_registry.json` | When available |
| DB schema module | `layer2/db.py` | When available |
| Alignment module | `layer2/alignment.py` | When available |
| Guard / audit outputs | `adapter-schema-guard`, `adapter-schema-guardian` | When available |

**Note on path convention:** The orchestration manifest references code context as `layer2/adapters/*`, `layer2/config/series_registry.json`, and `layer2/db.py`. The current repository implementation uses `truth_layer/` as the physical directory. Both path forms refer to the same artifacts. Evaluate whichever is present; do not reject evidence because the physical path differs from the manifest convention.

If `request_classification` is absent:
- infer claim and change types directly from the request text,
- set `inference_used: true` in the output,
- apply heightened caution; do not approve compliance without code/config evidence.

If adapter code is absent:
- proceed from documentation and request text alone,
- do not claim `compliant` for any implementation-state assertion without code evidence,
- note the gap explicitly; set the relevant item status to `review_only` or `ambiguous_requires_review`.

If `series_registry.json` is absent:
- treat any series definition encountered in adapter code as potentially unmanaged,
- flag for registry verification rather than approving silently.

---

## Governing assumptions

Apply these rules throughout.

- **Registry-driven discipline is non-negotiable.** `series_registry.json` is the single source of truth for all series metadata. All series IDs, tier assignments, staleness thresholds, snapshot inclusion rules, source designations, and group assignments must come from the registry — not from adapter code. This is an invariant stated in `CLAUDE.md` Section 8 and enforced by the `adapter-schema-guard` hook.
- **No hardcoded series definitions.** If a series identifier, source mapping, staleness value, or schema definition that belongs in the registry is embedded directly in adapter code, this is a violation — regardless of intent or convenience. Detect it; flag it; do not approve it silently.
- **Schema consistency matters.** Adapters must write to the Layer-2 DB schema defined in `layer2/db.py`. Field names, types, primary key conventions, and upsert discipline (`INSERT OR IGNORE` — never `INSERT OR REPLACE`) must remain consistent across all adapters. Any deviation that would create drift against the documented truth model is a schema drift finding.
- **Implementation boundary fit is required.** Adapters are Layer-2 ingestion components. They must not invent their own unmanaged truth contracts, bypass governed layers, or encapsulate logic that belongs in the registry, quality gate, or snapshot publisher.
- **Be deterministic and conservative.** When in doubt, prefer `review_only` over `compliant`. Surface schema drift explicitly. Surface registry bypass explicitly. Do not infer compliance from vague intent or assumed good practice.
- **Do not claim compliance without evidence.** Documentation claims that adapters are fully registry-driven do not constitute proof. Code evidence is required for implementation-state compliance verdicts. When code is unavailable, the status must reflect that gap.
- **Do not re-run upstream steps.** Accept the upstream `request_classification` verdicts. Only re-derive claim and change types if the upstream output is absent or clearly incomplete.
- **Strong claims require code-level support.** Claiming an adapter is "fully registry-driven" or "schema-consistent" without reading the relevant adapter code and registry is a strong implementation claim. Do not approve it without evidence.
- **This skill does not block or escalate itself.** It produces a verdict. The `adapter-schema-guard` hook and `adapter-schema-guardian` subagent consume that verdict and take operational action.

---

## Canonical source priority

When supporting findings with canonical documentation, use role-matched selection.

### Tier 1 — canonical current-state sources

| Priority | Document | Role for this skill |
|---|---|---|
| 1 | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Technical constraint and engineering rule claims; adapter invariants; DB schema discipline; `INSERT OR IGNORE` rule; registry-as-single-source-of-truth invariant |
| 2 | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architecture boundary claims; Layer-2 adapter scope; snapshot contract architecture |
| 3 | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Implementation-state claims; what is actually built; which adapters exist and in what form |
| 4 | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Known limitations; approximation boundaries relevant to adapter behavior |
| 5 | `README_v1.md` | Top-level orientation; system identity context |
| 6 | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | When documentation-consistency posture about adapter claims is relevant |

### Tier 2 — verification and governance artifacts

| Priority | Document | Role |
|---|---|---|
| 7 | `verification_ledger.md` | Existing claim → evidence → status tracking |
| 8 | `system-orchestration.yaml` | Hook definitions, blocking condition declarations, skill role assignments |

### Tier 3 — collaborator context only

| Priority | Document | Role |
|---|---|---|
| 9 | `README_LAYER2.md` | Within its declared collaborator-workflow role only; not authoritative for implementation-state, architecture boundary, or technical-constraint claims |

**Critical rule:** `README_LAYER2.md` must not be used to support architecture, implementation-state, or technical-constraint claims about adapter behavior. When such a citation is detected, flag it as a role-mismatch concern and prefer the Tier 1 source.

---

## Arguments

This skill accepts the following optional arguments.

- `scope=auto|request-only|request-and-code`
- `mode=strict|audit|light`
- `targets=<comma-separated adapters, files, or subsystems>`
- `report=json|json+summary`

Defaults:
- `scope=auto`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer the best scope from the request and upstream outputs; read available code when the request involves adapter implementation (default)
- `request-only`: evaluate the request text and documentation claims only; do not read adapter code
- `request-and-code`: explicitly read and evaluate the adapter code and registry config in addition to the request

### `mode`
Controls strictness and note density.
- `strict`: fail closed; apply all rules exactly; block ambiguous cases; recommended for all governance decisions
- `audit`: include expanded rationale, full registry-trace analysis, and schema-consistency traces; use for deep review sessions
- `light`: flag obvious violations only; do not use for release or governance-critical decisions

### `targets`
Optional focus hints. Use to narrow analysis when the request scope is known.

Examples:
- `targets=gold_adapter,fred_loader`
- `targets=series_registry.json,gld_holdings_adapter`
- `targets=layer2/adapters/*`

### `report`
Controls output verbosity.
- `json`: structured output only
- `json+summary`: structured output plus a short plain-language summary

---

## Compliance dimension 1: Registry compliance

This dimension checks whether adapter behavior is driven from `layer2/config/series_registry.json` rather than from embedded definitions.

### What to verify

- Adapter imports and consumes `get_registry()` or equivalent registry accessor for all series metadata.
- Series IDs, tier assignments, staleness thresholds, `blocks_snapshot` flags, group names, source designations, and `include_in_snapshot` flags are not duplicated or overridden in adapter code.
- Adapter selection logic (e.g., which series to load, which source to use) is driven by the registry's `source` field rather than by conditional branches keyed on literal series names.
- The registry file itself (`series_registry.json`) is the control point — not adapter-level configuration dictionaries, constants, or class attributes.
- Any new series the adapter introduces has a corresponding entry in `series_registry.json`.

### Compliant pattern (reference: `fred_loader.py` and `gold_adapter.py`)

```python
from layer2.config.registry import get_registry  # registry accessor
...
registry = get_registry()
series = [s for s in registry["series"] if s["source"] == "fred"]
```

This pattern is registry-driven. Series selection, metadata, and behavior flow from the registry, not from adapter-internal definitions.

### Violation pattern

```python
FRED_SERIES = ["DFII10", "DGS10", "DGS2"]  # hardcoded in adapter
STALENESS = {"DFII10": 3, "DGS10": 3}      # duplicated from registry
```

Any pattern equivalent to this — whether a constant, a dict, a class attribute, or inline literals — constitutes a registry violation when the same information is or should be governed by `series_registry.json`.

### Finding

Flag `registry_driven: false` and `overall_status: registry_violation` when registry bypass is detected.

---

## Compliance dimension 2: Hardcoding detection

This dimension checks whether series identifiers, mappings, or schema definitions that belong in the registry/config layer are embedded directly in adapter code.

### Patterns to detect and flag

1. **Series ID literals** — a series identifier such as `"DFII10"`, `"gold_price_proxy"`, or `"rates_vol_stress_move"` used as a literal string in adapter logic where it should come from the registry.
2. **Embedded staleness values** — a numeric staleness threshold (e.g., `3`, `7`, `30`) applied per-series in adapter code where it should come from `staleness_days` in the registry.
3. **Duplicated tier assignments** — tier logic (`tier == 1`, `tier == 2`) resolved from adapter-internal constants rather than the registry's `tier` field.
4. **Hardcoded `blocks_snapshot` logic** — a boolean or conditional that replicates the registry's `blocks_snapshot` field.
5. **Per-adapter source definitions** — a source URL, API endpoint, or data-source constant that should be centralized.
6. **Embedded field name mappings** — a local dict mapping raw source field names to DB column names when this mapping should be governed centrally.
7. **Inline `include_in_snapshot` filtering** — a hardcoded list of series to include in snapshots rather than using the registry's `include_in_snapshot: true` filter.

### Severity

- Presence of patterns 1–4 in adapter logic that governs series selection or snapshot eligibility: flag as `registry_violation`.
- Presence of patterns 5–7 in a single adapter without cross-adapter divergence: flag as `review_only` or `registry_violation` depending on scope and manifest mode.
- In `strict` mode: treat all detected hardcoding as at minimum `review_only`; treat patterns 1–4 as `registry_violation`.

---

## Compliance dimension 3: Schema consistency

This dimension checks whether adapter outputs align with the Layer-2 DB schema and truth model, and whether adapter changes would introduce drift.

### Reference schema (from `layer2/db.py`)

The `observations` table defines the canonical Layer-2 ingestion target:

```
observations (
  series_id    TEXT,
  obs_ts       TEXT,      -- ISO date string YYYY-MM-DD
  as_of_ts     TEXT,      -- ISO datetime string (UTC)
  value        REAL,
  revision_seq INTEGER DEFAULT 0,
  source       TEXT,
  ingested_at  TEXT,
  PRIMARY KEY (series_id, obs_ts, revision_seq)
)
```

The `snapshot_values` table defines what adapters contribute through the snapshot path:

```
snapshot_values (
  snapshot_id  TEXT,
  series_id    TEXT,
  tier         INTEGER,
  group_name   TEXT,
  obs_ts       TEXT,
  value        REAL,
  staleness_days INTEGER,
  source       TEXT,
  PRIMARY KEY (snapshot_id, series_id)
)
```

### What to verify

- Adapter upsert calls write exactly the fields expected by the `observations` table: `series_id`, `obs_ts`, `as_of_ts`, `value`, `revision_seq`, `source`, `ingested_at`.
- Adapter does not write extra columns, rename fields, or omit required fields.
- Adapter uses `INSERT OR IGNORE` — never `INSERT OR REPLACE`, `INSERT OR UPDATE`, or direct row mutation. This is an absolute rule from the code conventions.
- The `series_id` value written by the adapter matches the `series_id` declared in `series_registry.json` for that series.
- If the adapter contributes data that flows into `snapshot_values`, the `tier`, `group_name`, and `staleness_days` values must match the registry entry for that series.
- Field naming in adapter output rows matches the DB schema exactly — no camelCase, no aliased names, no implicit type coercions that could cause drift.

### Drift finding

Flag `schema_drift_detected: true` when:
- an adapter writes to a field name not in the canonical schema,
- an adapter omits a required field (`series_id`, `obs_ts`, `value`),
- an adapter uses `INSERT OR REPLACE` or any update-in-place pattern,
- the `series_id` written does not match the registry entry for the adapter,
- the `tier`, `group_name`, or `staleness_days` written to `snapshot_values` contradicts the registry.

---

## Compliance dimension 4: Implementation boundary fit

This dimension checks whether adapters remain within their intended Layer-2 responsibility and do not encroach on governed subsystems or invent unmanaged truth contracts.

### Adapter scope (Layer-2 only)

Adapters are responsible for:
- fetching raw data from external sources (FRED, gold-api.com, Yahoo Finance, Stooq, etc.)
- normalizing it to the `observations` schema
- writing it via `upsert_observations` (truth-safe upsert)
- optionally checking staleness via registry metadata

Adapters are **not** responsible for:
- snapshot publication (that is `snapshot_publisher.py`)
- quality gate decisions (that is `quality_gate.py`)
- clock management (that is `clock.py`)
- alignment logic (that is `alignment.py`)
- downstream Layer-3 consumption

### Boundary violations to detect

- Adapter directly queries `snapshot_values` or `snapshots` tables outside of its own write path.
- Adapter encodes alignment or staleness-gate logic that duplicates `quality_gate.py` or `alignment.py`.
- Adapter writes computed or derived values to `observations` instead of raw observations.
- Adapter publishes or updates snapshot state directly.
- Adapter embeds Layer-3 decision logic or signal computation.

Flag boundary violations in `notes` and mark the affected item `review_only` or `blocked` depending on severity.

---

## Output schema

Emit a single JSON object conforming to the following structure. Field names are fixed.

```json
{
  "adapter_schema_status": {
    "overall_status": "<compliant | review_only | registry_violation | schema_drift | ambiguous_requires_review>",
    "inference_used": false,
    "checked_items": [
      {
        "item_id": "<string — unique identifier for this check>",
        "target": "<adapter name, file path, or documentation claim>",
        "assessment": "<compliant | blocked | review>",
        "registry_driven": true,
        "hardcoded_series_detected": false,
        "schema_drift_detected": false,
        "boundary_fit": true,
        "affected_files": ["<file path>"],
        "missing_inputs": ["<list any evidence gaps>"],
        "reason": "<concise statement of why this assessment was reached>",
        "canonical_source": "<primary canonical document cited>",
        "notes": ["<additional notes for downstream guards or auditors>"]
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
      "notes": ["<summary-level notes>"]
    }
  }
}
```

### Field definitions

| Field | Type | Meaning |
|---|---|---|
| `overall_status` | string | Aggregate verdict across all checked items |
| `inference_used` | boolean | True if `request_classification` was absent and types were inferred directly |
| `item_id` | string | Unique ID for this check (e.g., `"reg-01"`, `"schema-02"`) |
| `target` | string | The adapter, file, or claim being evaluated |
| `assessment` | string | Item-level verdict: `compliant`, `blocked`, or `review` |
| `registry_driven` | boolean | True if the item's series/source logic is driven from the registry |
| `hardcoded_series_detected` | boolean | True if series IDs, staleness, or tier values are embedded in code |
| `schema_drift_detected` | boolean | True if adapter output deviates from the canonical Layer-2 schema |
| `boundary_fit` | boolean | True if the adapter stays within Layer-2 adapter scope |
| `affected_files` | array | Files implicated by this finding |
| `missing_inputs` | array | Evidence that was unavailable for this check |
| `reason` | string | Deterministic rationale for the assessment |
| `canonical_source` | string | The canonical document whose role best matches the claim type |
| `notes` | array | Notes for downstream guards, auditors, and ledger updates |
| `registry_violation_detected` | boolean | Summary: any item has `hardcoded_series_detected: true` or registry bypass |
| `schema_drift_detected` (summary) | boolean | Summary: any item has `schema_drift_detected: true` |
| `requires_adapter_schema_guard` | boolean | True if `adapter-schema-guard` should be invoked based on this verdict |
| `requires_adapter_schema_guardian` | boolean | True if the `adapter-schema-guardian` subagent should perform a deep audit |
| `requires_doc_code_sync_review` | boolean | True if documentation claims about adapter compliance need code-level verification |
| `source_authority_conflict_detected` | boolean | True if `README_LAYER2.md` or another non-role-matched source was used to make a strong implementation or architecture claim |

---

## Decision rules

### `compliant`

Use when all of the following hold:
- adapter logic is driven from `series_registry.json` via the registry accessor
- no hardcoded series identifiers, staleness values, or tier assignments are present in adapter code
- adapter writes to the canonical `observations` schema using `INSERT OR IGNORE`
- field names, types, and `series_id` values match the registry and schema exactly
- the adapter stays within Layer-2 adapter scope
- sufficient code and config evidence is available to support the verdict

### `review_only`

Use when:
- the change may be acceptable but code-level confirmation is needed and code was not available,
- evidence is partially incomplete but no clear violation pattern was detected,
- a pattern exists that could become a violation depending on how it is used,
- a documentation claim about adapter compliance cannot be verified without reading the adapter code.

### `registry_violation`

Use when:
- adapter logic bypasses or replaces the registry-driven model,
- series IDs, source mappings, staleness values, or tier assignments are embedded in adapter code where the registry should govern them,
- a helper, constant, or dict duplicates central registry intent in a way that could diverge,
- the manifest hook check "registry-driven usage enforced" or "no hardcoded series definitions" would fail.

### `schema_drift`

Use when:
- adapter output fields, types, or assumptions diverge materially from the `observations` or `snapshot_values` schema,
- an adapter uses `INSERT OR REPLACE` or any row-mutation pattern,
- field names differ from the canonical schema,
- the `series_id` written does not match the registry entry for that adapter,
- tier, group, or staleness values written to `snapshot_values` contradict the registry.

### `ambiguous_requires_review`

Use when:
- intent or code evidence is too incomplete for a firm conclusion,
- multiple interpretations of the evidence are possible,
- in `strict` mode: when doubt exists, fail closed to this status rather than approving silently.

---

## Patterns to detect

Apply these pattern checks when adapter code is available.

| Pattern | Dimension | Finding |
|---|---|---|
| Series ID string literal used in adapter logic (e.g., `"DFII10"`) | Hardcoding | `hardcoded_series_detected: true`; `registry_violation` |
| Staleness threshold numeric literal per-series in adapter (e.g., `staleness_days = 3`) | Hardcoding | `hardcoded_series_detected: true`; `registry_violation` |
| `blocks_snapshot` conditional hardcoded in adapter | Hardcoding | `hardcoded_series_detected: true`; `registry_violation` |
| Tier assignment literal in adapter code | Hardcoding | `hardcoded_series_detected: true`; `registry_violation` |
| Per-adapter dict duplicating registry mappings | Hardcoding | `registry_violation` or `review_only` depending on scope |
| `INSERT OR REPLACE` in upsert logic | Schema | `schema_drift_detected: true`; `schema_drift` |
| Missing required field in observation write (`series_id`, `obs_ts`, `value`) | Schema | `schema_drift_detected: true`; `schema_drift` |
| Extra column written to `observations` not in canonical schema | Schema | `schema_drift_detected: true`; `schema_drift` |
| `series_id` written differs from registry entry | Schema | `schema_drift_detected: true`; `schema_drift` |
| Adapter reads from `snapshots` or `snapshot_values` | Boundary | `boundary_fit: false`; flag in `notes` |
| Adapter implements alignment or staleness gate logic | Boundary | `boundary_fit: false`; flag in `notes` |
| No `get_registry()` import detected in adapter | Registry | `registry_driven: false`; `review_only` or `registry_violation` |
| Documentation claim "fully registry-driven" without code evidence | Registry | `review_only`; `requires_doc_code_sync_review: true` |
| `README_LAYER2.md` cited as primary authority for implementation claim | Source authority | `source_authority_conflict_detected: true`; prefer Tier 1 source |

---

## Checklist

Before emitting the output, confirm each item.

- [ ] All available adapter code has been read and evaluated.
- [ ] `series_registry.json` has been read and used as the reference for series metadata.
- [ ] `layer2/db.py` schema has been used as the reference for field-level schema consistency.
- [ ] Registry compliance dimension evaluated for each adapter in scope.
- [ ] Hardcoding detection applied; all literal series identifiers, staleness values, and tier assignments in adapter code checked.
- [ ] Schema drift evaluated against the canonical `observations` DDL.
- [ ] `INSERT OR IGNORE` (not `INSERT OR REPLACE`) verified where code is available.
- [ ] Implementation boundary fit evaluated; no encroachment on governed subsystems detected or flagged.
- [ ] `overall_status` reflects the most severe finding across all `checked_items`.
- [ ] `requires_adapter_schema_guard` set to `true` if any `registry_violation` or `schema_drift` finding is present.
- [ ] `requires_adapter_schema_guardian` set to `true` if the evidence is incomplete for a deep compliance decision.
- [ ] `requires_doc_code_sync_review` set to `true` if documentation claims about adapter compliance cannot be confirmed from code.
- [ ] `source_authority_conflict_detected` set if `README_LAYER2.md` or non-role-matched source is used for a strong implementation or architecture claim.
- [ ] `inference_used` set to `true` if `request_classification` was absent.
- [ ] `missing_inputs` lists any evidence gaps per item.
- [ ] All canonical source citations use the role-matched Tier 1 document.
- [ ] No strong compliance claim is emitted without code or config evidence.

---

## Worked examples

### Example 1: New adapter with hardcoded series definitions

**Request:** "Add a new adapter `crypto_adapter.py` that fetches BTC price. The adapter has a constant `SERIES_ID = 'btc_price_proxy'` and `STALENESS_DAYS = 3` defined at the module level."

**Analysis:**
- `SERIES_ID` and `STALENESS_DAYS` are hardcoded in the adapter rather than loaded from `series_registry.json`.
- No registry entry for `btc_price_proxy` is present.
- The series is not governed by the registry at all.
- Hook check "no hardcoded series definitions" would fail.

**Expected output (key fields):**

```json
{
  "adapter_schema_status": {
    "overall_status": "registry_violation",
    "checked_items": [
      {
        "item_id": "reg-01",
        "target": "crypto_adapter.py",
        "assessment": "blocked",
        "registry_driven": false,
        "hardcoded_series_detected": true,
        "schema_drift_detected": false,
        "reason": "SERIES_ID and STALENESS_DAYS are hardcoded in adapter code. Both must be governed by series_registry.json. No registry entry for btc_price_proxy exists.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
      }
    ],
    "summary": {
      "registry_violation_detected": true,
      "hardcoded_series_detected": true,
      "requires_adapter_schema_guard": true
    }
  }
}
```

---

### Example 2: Adapter refactored to read from registry

**Request:** "Refactor `move_adapter.py` to load all source and series definitions from `series_registry.json` via `get_registry()`. Remove the inline `MOVE_SERIES_ID = 'rates_vol_stress_move'` constant."

**Analysis:**
- After refactor, adapter derives `series_id` from the registry entry where `source == "yahoo"` and `group == "stress"`.
- No hardcoded series identifiers remain.
- Staleness, tier, and `blocks_snapshot` come from the registry.
- Upsert uses `INSERT OR IGNORE` via the shared DB module.
- Schema fields match the `observations` DDL.

**Expected output (key fields):**

```json
{
  "adapter_schema_status": {
    "overall_status": "compliant",
    "checked_items": [
      {
        "item_id": "reg-01",
        "target": "move_adapter.py",
        "assessment": "compliant",
        "registry_driven": true,
        "hardcoded_series_detected": false,
        "schema_drift_detected": false,
        "reason": "Adapter derives all series metadata from series_registry.json via get_registry(). No hardcoded series identifiers, staleness values, or tier assignments detected.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
      }
    ],
    "summary": {
      "registry_violation_detected": false,
      "hardcoded_series_detected": false,
      "schema_drift_detected": false,
      "requires_adapter_schema_guard": false
    }
  }
}
```

---

### Example 3: Adapter output fields no longer match downstream schema

**Request:** "Change `gld_holdings_adapter.py` to write an additional field `adjusted_value` and rename `obs_ts` to `observation_date` in the upsert rows."

**Analysis:**
- `obs_ts` is a required field in the canonical `observations` schema; renaming it to `observation_date` causes schema drift.
- `adjusted_value` is not in the canonical schema; adding it creates an unmanaged field.
- This would break alignment logic in `alignment.py` which queries by `obs_ts`.
- Hook check "registry-driven usage enforced" is not the primary issue here; schema drift is.

**Expected output (key fields):**

```json
{
  "adapter_schema_status": {
    "overall_status": "schema_drift",
    "checked_items": [
      {
        "item_id": "schema-01",
        "target": "gld_holdings_adapter.py",
        "assessment": "blocked",
        "registry_driven": true,
        "hardcoded_series_detected": false,
        "schema_drift_detected": true,
        "affected_files": ["layer2/adapters/gld_holdings_adapter.py", "layer2/db.py"],
        "reason": "obs_ts renamed to observation_date violates the canonical observations schema PRIMARY KEY. adjusted_value is not in the canonical schema. Both changes create drift against layer2/db.py DDL and would break alignment.py queries.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["alignment.py ORDER BY obs_ts query would fail", "snapshot_publisher.py selects obs_ts from observations"]
      }
    ],
    "summary": {
      "schema_drift_detected": true,
      "requires_adapter_schema_guard": true,
      "requires_doc_code_sync_review": false
    }
  }
}
```

---

### Example 4: Helper module that duplicates registry mappings

**Request:** "Add a helper `layer2/adapters/series_constants.py` that defines `TIER1_SERIES = ['gold_price_proxy', 'DFII10', 'DGS10', ...]` for use across multiple adapters."

**Analysis:**
- The list `TIER1_SERIES` duplicates the tier-1 membership that is governed by `series_registry.json` via the `tier` field.
- Any divergence between this constant and the registry would silently create inconsistency.
- Severity depends on how adapters consume it. If adapters use it for snapshot-gating decisions, this is a `registry_violation`. If it is used only for logging or diagnostics, it is `review_only`.
- In `strict` mode: flag as `registry_violation` for any governance-affecting use; `review_only` for pure diagnostic use.

**Expected output (key fields):**

```json
{
  "adapter_schema_status": {
    "overall_status": "registry_violation",
    "checked_items": [
      {
        "item_id": "reg-01",
        "target": "layer2/adapters/series_constants.py",
        "assessment": "blocked",
        "registry_driven": false,
        "hardcoded_series_detected": true,
        "schema_drift_detected": false,
        "reason": "TIER1_SERIES duplicates tier-1 membership governed by series_registry.json. Any consumer of this constant creates a divergence risk. Tier membership must be derived from the registry's tier field, not from a parallel constant.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["If series_constants.py is diagnostic-only, downgrade to review_only and document the scope restriction explicitly."]
      }
    ],
    "summary": {
      "registry_violation_detected": true,
      "hardcoded_series_detected": true,
      "requires_adapter_schema_guard": true
    }
  }
}
```

---

### Example 5: Documentation claim without code evidence

**Request:** "Update `SYSTEM_IMPLEMENTATION_RECORD_v1.md` to state: 'All Layer-2 adapters are fully registry-driven and schema-consistent.' No adapter code has been read."

**Analysis:**
- This is an implementation-state claim requiring code-level evidence (`SYSTEM_IMPLEMENTATION_RECORD_v1.md` is the role-matched canonical source).
- No adapter code was read; the claim cannot be verified from documentation alone.
- Doc-only evidence cannot produce `proven` status for an implementation claim.
- The correct status is `review_only`; doc/code sync review is required before this claim can be accepted.

**Expected output (key fields):**

```json
{
  "adapter_schema_status": {
    "overall_status": "review_only",
    "inference_used": false,
    "checked_items": [
      {
        "item_id": "doc-01",
        "target": "SYSTEM_IMPLEMENTATION_RECORD_v1.md — claim: all adapters fully registry-driven",
        "assessment": "review",
        "registry_driven": null,
        "hardcoded_series_detected": null,
        "schema_drift_detected": null,
        "missing_inputs": ["layer2/adapters/* source code not read"],
        "reason": "Implementation-state claim cannot be verified without reading adapter code. Doc-only evidence cannot produce proven status for this claim type.",
        "canonical_source": "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "notes": ["Read all adapters and series_registry.json before accepting this claim. Required: verify no hardcoded series IDs, verify INSERT OR IGNORE usage, verify registry accessor imports."]
      }
    ],
    "summary": {
      "requires_doc_code_sync_review": true,
      "requires_adapter_schema_guardian": true,
      "notes": ["Claim accepted into documentation would require code evidence before it can be verified in the ledger."]
    }
  }
}
```

---

## Completion standard

This skill's output is complete when all of the following hold.

1. Every adapter, file, or claim in scope has at least one `checked_items` entry.
2. `overall_status` reflects the most severe finding across all items: if any item is `registry_violation` or `schema_drift`, the overall status must be at least that severe.
3. `requires_adapter_schema_guard` is `true` whenever `overall_status` is `registry_violation`, `schema_drift`, or `ambiguous_requires_review`.
4. `requires_adapter_schema_guardian` is `true` whenever code evidence was unavailable for a material compliance decision.
5. `requires_doc_code_sync_review` is `true` whenever a documentation claim about adapter compliance could not be verified from code.
6. All `canonical_source` fields cite the Tier 1 role-matched document — not `README_LAYER2.md` for implementation or architecture claims.
7. `inference_used` is set correctly.
8. `missing_inputs` is populated for every item where evidence was absent.
9. No strong compliance claim (`compliant`) is present without code or config evidence.
10. The output is valid JSON conforming to the required schema.
11. In `json+summary` mode: a plain-language summary of no more than five sentences follows the JSON block, stating the overall verdict, the primary finding type, and the downstream actions required.
