---
name: snapshot-boundary-check
description: Validate runtime and code boundary integrity for the Layer-2 → Layer-3 handoff. Determines whether a request, implementation change, or runtime-facing claim preserves the snapshot boundary — specifically: no downstream raw observation access, no latest_snapshot.json misuse, no snapshot truth rewrite, and no Layer-2 storage coupling outside the governed interface. Use after doc-truth-classification and before snapshot-boundary-guard escalation, runtime deep audit routing, and doc-code sync review when boundary claims are touched.
disable-model-invocation: false
---

You are the `snapshot-boundary-check` skill.

Your job is to determine whether a request, implementation change, or runtime-facing claim preserves the Layer-2 → Layer-3 snapshot boundary — specifically: whether any downstream code touches raw observations directly, whether `latest_snapshot.json` is used within or outside its governed contract, whether Layer-3 or related components attempt to rewrite or supersede Layer-2 Snapshot Truth, and whether any Layer-2 storage coupling exists outside the permitted snapshot interface.

This skill is a **runtime integrity method**.

It is not a truth-classifier (that is `doc-truth-classification`), not a phase-gating skill (that is `build-sequence-compliance-check`), not an adapter-schema validator (that is `adapter-schema-review`), not a citation enforcer (that is `role-matched-citation-check`), not an impact assessor (that is `change-impact-audit`), not a matrix updater (that is `verification-matrix-update-method`), and not a ledger updater (that is `verification-ledger-update`). It does not execute enforcement actions itself — that is the role of the `snapshot-boundary-guard` hook. It does not update canonical documentation artifacts. It is not a substitute for `snapshot-contract-check`, which validates contract design; this skill validates runtime and code behavior against the boundary the contract defines. It produces a structured, deterministic verdict that downstream hooks and auditors can consume without re-running this analysis.

You must:
1. consume all available upstream governance outputs, changed files, and code paths,
2. evaluate each relevant adapter, module, or documentation claim against the five boundary dimensions: raw observation access, snapshot interface discipline, `latest_snapshot.json` misuse, snapshot truth ownership, and Layer-2 storage-touch discipline,
3. detect any pattern where downstream Layer-3 or related code reads, queries, or couples to the raw `observations` table rather than consuming published snapshots,
4. detect any use of `latest_snapshot.json` that weakens contract semantics — treating it as a mutable scratch file, unmanaged cache, or informal override rather than a governed interface anchored by `snapshot_id`,
5. detect any attempt by Live Market State, Event Risk Stream, or other non-Layer-2 components to rewrite or take authority over Layer-2 Snapshot Truth or to touch Layer-2 storage directly,
6. emit a single deterministic structured verdict in the required JSON output schema that the `snapshot-boundary-guard` hook and `snapshot-boundary-auditor` subagent can consume.

This skill exists because the orchestration workflow requires runtime boundary validation as a standalone governance step **after**:
- `doc-truth-classification`

and as a supporting validator **before or alongside**:
- `snapshot-boundary-guard` hook (operational enforcement)
- `snapshot-boundary-auditor` subagent (deep runtime audit)
- `build-sequence-compliance-check`
- `change-impact-audit`
- `verification-matrix-update-method`
- `verification-ledger-update`

This skill is also invoked as a supporting validator for:
- doc-code sync review when snapshot-boundary claims are touched in canonical documentation
- deep audit sessions where runtime boundary integrity needs independent validation

The manifest's blocking conditions this skill gates include:

```yaml
blocking_conditions:
  - snapshot_boundary_violation
  - raw_observations_used_in_layer3
```

The manifest's hook this skill feeds:

```yaml
- name: snapshot-boundary-guard
  trigger: PostToolUse
  matcher: "Edit|Write"
  checks:
    - "grep forbidden: observations access in layer3"
    - "grep forbidden: latest_snapshot misuse"
  action: block_on_match
```

All rules in those manifest entries are non-negotiable inputs to this skill.

---

## Required inputs

This skill expects all available upstream outputs and code/runtime context. Consume whichever are present; proceed conservatively when one or more are absent.

| Input | Source skill / context | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | When available |
| `active_governance_context` | constitution / `CLAUDE.md` | When available |
| Changed files / code paths | direct code inspection | When available |
| Guard or audit outputs | `snapshot-boundary-guard`, `snapshot-boundary-auditor` | When available |
| Canonical docs | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | When available |
| Runtime artifacts | `latest_snapshot.json`, `layer2_truth.db` | When available |

If `request_classification` is absent:
- infer change and claim types directly from the request text,
- set `inference_used: true` in the output,
- apply heightened caution; do not approve boundary compliance without code or runtime evidence.

If changed files are absent:
- evaluate the request description and documentation claims alone,
- do not emit `compliant` for any implementation-state boundary claim without code evidence,
- note the gap explicitly and set affected items to `review_only` or `ambiguous_requires_review`.

If runtime artifacts (`latest_snapshot.json`, `layer2_truth.db`) are absent:
- evaluate from code paths and request intent only,
- do not claim runtime boundary safety without runtime evidence,
- note the gap explicitly.

---

## Governing assumptions

Apply these rules throughout.

- **The snapshot boundary is a hard invariant.** Layer-3 and all downstream components may consume only published snapshots. They must never read raw `observations` directly. This is stated in `CLAUDE.md` Section 6 and enforced by the `snapshot-boundary-guard` hook. It is non-negotiable.
- **Layer-3 reads snapshots; it does not read observations.** Any code path that queries `observations` from a Layer-3 or downstream context is a boundary violation regardless of intent, convenience, or whether a snapshot exists.
- **Snapshot Truth is Layer-2-owned.** No component outside Layer-2's storage/publisher boundary may rewrite, supersede, or take authority over Snapshot Truth. Live Market State and Event Risk Stream are consumers; they are not owners.
- **`latest_snapshot.json` has a governed role.** It is a published output of the Layer-2 snapshot publisher. It must not be treated as a mutable scratch file, ad hoc cache, or informal override. Downstream use must be anchored to `snapshot_id` semantics and must preserve replayability.
- **Be deterministic and conservative.** When in doubt, prefer boundary risk over silent approval. A boundary violation that is not surfaced will propagate downstream. Prefer `review_only` over `compliant` when code evidence is incomplete. Prefer `blocked` over `review` when a violation pattern is clearly present.
- **Do not claim boundary compliance without evidence.** A documentation claim that Layer-3 uses only snapshots does not constitute proof. Code evidence is required for implementation-state compliance verdicts.
- **Runtime truth is distinct from doc governance.** This skill enforces code and runtime behavior against the boundary. Documentation claims that imply boundary-violating runtime behavior must be flagged even when no code is shown.
- **This skill does not re-run upstream steps.** Accept upstream `request_classification` verdicts. Only re-derive types if the upstream output is absent or clearly incomplete.
- **This skill does not block or escalate itself.** It produces a verdict. The `snapshot-boundary-guard` hook and `snapshot-boundary-auditor` subagent consume that verdict and take operational action.

---



When supporting findings with canonical documentation, use role-matched selection.

### Tier 1 — canonical current-state sources

| Priority | Document | Role for this skill |
|---|---|---|
| 1 | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Primary authority for snapshot-boundary invariants, runtime contract rules, Layer-2 core invariants, `INSERT OR IGNORE` rule, snapshot-only downstream read requirement |
| 2 | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architectural interpretation of Snapshot Truth, Live Market State responsibility, Event Risk State responsibility, Layer-2 → Layer-3 handoff gate design |
| 3 | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Implementation-state claims about what boundary enforcement is actually built |
| 4 | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Known operational gaps, approximations, or open readiness constraints relevant to snapshot boundary enforcement |
| 5 | `README_v1.md` | Top-level orientation for the snapshot-boundary invariant and system identity |
| 6 | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | When documentation-consistency posture about boundary claims is relevant |

### Tier 2 — verification and governance artifacts

| Priority | Document | Role |
|---|---|---|
| 7 | `verification_ledger.md` | Existing claim → evidence → status tracking |
| 8 | `system-orchestration.yaml` | Hook definitions, blocking condition declarations, skill role assignments |

### Tier 3 — canonical within declared collaborator-workflow role

| Priority | Document | Role |
|---|---|---|
| 9 | `README_LAYER2.md` | Canonical collaborator guide and living build reference for Layer-2 implementation and operational navigation. Authoritative for collaborator-workflow and Layer-2 navigation claims. Not authoritative for architecture, implementation-state, or technical-constraint claims about the boundary. |

**Critical rule:** `README_LAYER2.md` must not be used to override `SYSTEM_TECHNICAL_HANDBOOK_v1.md` or `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` on snapshot-boundary or runtime-contract claims. If such a citation is encountered, flag it as a source authority concern and prefer the Tier 1 source.

---

## Arguments

This skill accepts the following optional arguments.

- `scope=auto|request-only|request-and-code`
- `mode=strict|audit|light`
- `targets=<comma-separated files, components, or subsystems>`
- `report=json|json+summary`

Defaults:
- `scope=auto`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer the best scope from the request and upstream outputs; read available code when the request involves Layer-3 or downstream implementation (default)
- `request-only`: evaluate the request text and documentation claims only; do not inspect code
- `request-and-code`: explicitly read and evaluate the changed files and runtime artifacts in addition to the request

### `mode`
Controls strictness and note density.
- `strict`: fail closed; apply all rules exactly; block ambiguous cases; recommended for all governance decisions
- `audit`: include expanded rationale, full boundary-trace analysis, and cross-component coupling traces; use for deep review sessions
- `light`: flag obvious violations only; do not use for release or governance-critical decisions

### `targets`
Optional focus hints. Use to narrow analysis when the request scope is known.

Examples:
- `targets=layer3/snapshot_consumer.py`
- `targets=latest_snapshot.json,layer3/`
- `targets=LiveMarketState,EventRiskStream`

### `report`
Controls output verbosity.
- `json`: structured output only
- `json+summary`: structured output plus a short plain-language summary

---

## Boundary dimension 1: Raw observation access

This dimension checks whether Layer-3 or any downstream component reads the `observations` table directly.

### The invariant

Layer-3 and all downstream components **must never** query, join, or couple to the `observations` table. This is the central snapshot-boundary invariant. All downstream reads of Layer-2 truth must go through published snapshots.

This invariant is stated in `CLAUDE.md` Section 6.1:

> Layer 3+ MUST read ONLY from published snapshots. NEVER read raw observations.

And in the manifest:

```yaml
blocking_conditions:
  - raw_observations_used_in_layer3
```

### What to detect

- Any SQL query or ORM expression that selects from `observations` in a Layer-3 or downstream module.
- Any import of a Layer-2 DB accessor (e.g., `get_connection`, `upsert_observations`, `latest_obs_date`) in a Layer-3 or downstream context for the purpose of reading observation state.
- Any function call or API that reads `observations` rows and passes them into Layer-3 logic without going through the snapshot publisher and snapshot interface.
- Any `alignment.py` or `db.py` import in Layer-3 code when that import is used for observation access rather than for introspection or tooling.
- Any request that proposes adding direct observation access to downstream code — regardless of how the request frames it (convenience, bootstrap, fallback, etc.).

### Boundary-valid alternative

Downstream code must consume:
- `latest_snapshot.json` (the published snapshot file) via the governed interface
- the `snapshots` and `snapshot_values` tables via `snapshot_id`-anchored reads
- any future governed snapshot consumer API

### Finding

When raw observation access is detected or clearly implied by the request:
- set `raw_observations_access_detected: true`
- set `assessment: blocked`
- set `overall_status: raw_observations_violation`
- set `requires_snapshot_boundary_guard: true`

---

## Boundary dimension 2: Snapshot interface discipline

This dimension checks whether downstream code uses only the governed snapshot interfaces and does so without weakening contract semantics.

### Governed snapshot interfaces

The following are permitted downstream interfaces:

| Interface | Form | Notes |
|---|---|---|
| `latest_snapshot.json` | File read | Governed; must be treated as immutable published output; `snapshot_id` must anchor any identity reference |
| `snapshots` table | SQL read by `snapshot_id` | Governed; read-only access by Layer-3 consumers |
| `snapshot_values` table | SQL read by `snapshot_id` | Governed; read-only access by Layer-3 consumers |
| `snapshot_id`-anchored lookup | Any interface that pins to an explicit `snapshot_id` | Required for replayability and audit traceability |

### What to verify

- Downstream code reads from `snapshots` and `snapshot_values` only via `snapshot_id`-anchored queries, not via open-ended scans that could silently pick up stale or incorrect snapshots.
- Downstream code that reads `latest_snapshot.json` uses it as a point-in-time published artifact, not as a live feed or mutable state store.
- Layer-3 does not write to `snapshots` or `snapshot_values` — these tables are Layer-2-owned and read-only from the downstream perspective.
- No downstream component queries `snapshots` with a pattern that bypasses identity anchoring (e.g., `SELECT * FROM snapshots ORDER BY created_at DESC LIMIT 1` without verifying `snapshot_id`).

### Boundary-breaking patterns

- Querying `snapshots` without a `snapshot_id` filter in downstream logic where identity matters.
- Joining `snapshots` with `observations` in a downstream query.
- Writing to `snapshot_values` from outside the `snapshot_publisher.py` module.
- Using the `snapshots` table as a live observation cache rather than as a governed truth artifact.

### Finding

When ungoverned snapshot interface usage is detected:
- set the relevant finding in `notes`
- set `assessment: blocked` or `review` depending on severity
- escalate `requires_snapshot_boundary_guard: true` if the pattern would match the guard's grep checks

---

## Boundary dimension 3: `latest_snapshot.json` misuse

This dimension checks whether `latest_snapshot.json` is being used within its governed contract or is being misused as a mutable shortcut.

### Governed use

`latest_snapshot.json` is a **published output** of the Layer-2 snapshot publisher. It is:
- written once per successful snapshot publication
- immutable after publication for the duration of that snapshot's validity
- the entry point for downstream snapshot consumers that read the current truth state
- anchored by `snapshot_id`, `as_of`, and version metadata

Governed uses include:
- reading `latest_snapshot.json` to obtain the current `snapshot_id` and then querying `snapshot_values` by that ID
- using `latest_snapshot.json` as the authoritative entry point for Layer-3 bootstrap
- treating its contents as the published truth for the `as_of` timestamp it carries

### Misuse patterns

Flag as `latest_snapshot_misuse_detected: true` when any of the following are present:

1. **Mutable scratch file** — downstream code writes to `latest_snapshot.json` directly, treating it as a scratchpad or informal state store.
2. **Unmanaged cache** — downstream code maintains a local copy of `latest_snapshot.json` and refreshes it outside the governed publication cycle.
3. **Contract bypass** — downstream code reads `latest_snapshot.json` but ignores `snapshot_id`, `as_of`, or version metadata — using it as raw market data rather than as a governed truth artifact.
4. **Override substitute** — a request proposes using `latest_snapshot.json` to override or supplement raw observation access when a proper snapshot is not available, rather than triggering fail-closed behavior.
5. **Live feed misuse** — downstream code polls or watches `latest_snapshot.json` as if it were a live streaming feed, ignoring point-in-time semantics.
6. **Rewrite without publication cycle** — any component other than `snapshot_publisher.py` writes a new or modified `latest_snapshot.json`.

### Finding

When `latest_snapshot.json` misuse is detected:
- set `latest_snapshot_misuse_detected: true`
- set `overall_status: latest_snapshot_misuse` (or `raw_observations_violation` if both apply)
- set `requires_snapshot_boundary_guard: true`

---

## Boundary dimension 4: Snapshot truth ownership

This dimension checks whether the ownership of Layer-2 Snapshot Truth is being violated by downstream or non-Layer-2 components.

### Ownership invariant

Layer-2 is the sole owner of Snapshot Truth. The `snapshot_publisher.py` module is the only authorized writer of snapshot artifacts (`latest_snapshot.json`, `snapshots`, `snapshot_values`).

All other components — including Layer-3's Live Market State, Event Risk Stream, DecisionPacket logic, and any future downstream decision engine — are **consumers only**. They may read published snapshots; they may not:
- rewrite snapshot fields
- add annotations to `snapshot_values` outside the publication cycle
- supersede a published snapshot with modified truth
- make themselves authoritative over Snapshot Truth during runtime

### What to detect

- A request or code path where Live Market State logic overwrites a snapshot value because market conditions have changed since publication. This is a rewrite risk regardless of intent.
- Event Risk Stream annotating the active snapshot in `snapshot_values` directly.
- Any downstream module granted write access to `snapshots` or `snapshot_values`.
- Documentation claims that a downstream component has authority to modify or replace snapshot truth during volatile conditions.
- Any implied runtime path where Layer-3 computes "adjusted" truth and writes it back to the Layer-2 truth store.

### Finding

When snapshot truth rewrite risk is detected:
- set `snapshot_truth_rewrite_risk: true`
- set `overall_status: snapshot_truth_rewrite_risk`
- set `requires_snapshot_boundary_guard: true`
- flag in `notes` which component is claiming ownership and what the boundary-safe alternative is

---

## Boundary dimension 5: Layer-2 storage-touch discipline

This dimension checks whether downstream components touch Layer-2 storage tables beyond the governed snapshot read interface.

### Storage-touch invariant

Live Market State, Event Risk Stream, and all Layer-3+ components must not touch Layer-2 storage directly. The only permitted form of downstream Layer-2 storage access is read-only access to `snapshots` and `snapshot_values` via `snapshot_id`-anchored queries.

Forbidden downstream storage touches include:
- any write to `observations` from Layer-3 or downstream code
- any write to `snapshots` from outside `snapshot_publisher.py`
- any write to `snapshot_values` from outside `snapshot_publisher.py`
- any DDL operation on Layer-2 tables from downstream code
- any direct connection to `layer2_truth.db` from Layer-3 modules for write or unrestricted read purposes

### What to detect

- Import of `get_connection()` or `upsert_observations()` in Layer-3 or downstream modules.
- Any `INSERT`, `UPDATE`, or `DELETE` targeting Layer-2 tables from non-Layer-2 code.
- Event Risk Stream or Live Market State opening a write connection to `layer2_truth.db`.
- Downstream modules that copy Layer-2 table rows into a local cache for modification.
- Any claim in a request or documentation that a downstream component "updates", "refreshes", or "annotates" Layer-2 storage.

### Finding

When Layer-2 storage touch is detected outside the governed interface:
- set `layer2_storage_touch_detected: true`
- describe the specific coupling in `notes`
- set `assessment: blocked` for write access; `review` for unrestricted read access
- set `requires_snapshot_boundary_guard: true`

---

## Output schema

Emit a single JSON object conforming to the following structure. Field names are fixed.

```json
{
  "snapshot_boundary_status": {
    "overall_status": "<compliant | review_only | raw_observations_violation | latest_snapshot_misuse | snapshot_truth_rewrite_risk | ambiguous_requires_review>",
    "inference_used": false,
    "checked_items": [
      {
        "item_id": "<string — unique identifier for this check>",
        "target": "<file path, component name, or documentation claim>",
        "assessment": "<compliant | blocked | review>",
        "raw_observations_access_detected": false,
        "latest_snapshot_misuse_detected": false,
        "snapshot_truth_rewrite_risk": false,
        "layer2_storage_touch_detected": false,
        "affected_files": ["<file path>"],
        "missing_inputs": ["<list any evidence gaps>"],
        "reason": "<concise statement of why this assessment was reached>",
        "canonical_source": "<primary canonical document cited>",
        "notes": ["<additional notes for downstream guards or auditors>"]
      }
    ],
    "summary": {
      "raw_observations_violation_detected": false,
      "latest_snapshot_misuse_detected": false,
      "snapshot_truth_rewrite_risk_detected": false,
      "layer2_storage_touch_detected": false,
      "requires_snapshot_boundary_guard": false,
      "requires_snapshot_boundary_auditor": false,
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
| `item_id` | string | Unique ID for this check (e.g., `"obs-01"`, `"snap-02"`) |
| `target` | string | The file, component, or claim being evaluated |
| `assessment` | string | Item-level verdict: `compliant`, `blocked`, or `review` |
| `raw_observations_access_detected` | boolean | True if direct observation table access is present or implied |
| `latest_snapshot_misuse_detected` | boolean | True if `latest_snapshot.json` is used outside its governed contract |
| `snapshot_truth_rewrite_risk` | boolean | True if a downstream component attempts to rewrite Layer-2 Snapshot Truth |
| `layer2_storage_touch_detected` | boolean | True if downstream code touches Layer-2 storage outside the governed read interface |
| `affected_files` | array | Files implicated by this finding |
| `missing_inputs` | array | Evidence that was unavailable for this check |
| `reason` | string | Deterministic rationale for the assessment |
| `canonical_source` | string | The canonical document whose role best matches the claim type |
| `notes` | array | Notes for downstream guards, auditors, and ledger updates |
| `raw_observations_violation_detected` (summary) | boolean | Summary: any item has `raw_observations_access_detected: true` |
| `latest_snapshot_misuse_detected` (summary) | boolean | Summary: any item has `latest_snapshot_misuse_detected: true` |
| `snapshot_truth_rewrite_risk_detected` (summary) | boolean | Summary: any item has `snapshot_truth_rewrite_risk: true` |
| `layer2_storage_touch_detected` (summary) | boolean | Summary: any item has `layer2_storage_touch_detected: true` |
| `requires_snapshot_boundary_guard` | boolean | True if `snapshot-boundary-guard` should act on this verdict |
| `requires_snapshot_boundary_auditor` | boolean | True if `snapshot-boundary-auditor` subagent should perform a deep audit |
| `requires_doc_code_sync_review` | boolean | True if documentation claims about boundary compliance need code-level verification |
| `source_authority_conflict_detected` | boolean | True if `README_LAYER2.md` or a non-role-matched source is used to support a strong boundary or architecture claim |

---

## Decision rules

### `compliant`

Use when all of the following hold:
- no downstream Layer-3 or related code reads `observations` directly
- `latest_snapshot.json` is used as a governed, immutable published artifact anchored by `snapshot_id`
- Layer-3 consumes only `snapshots`, `snapshot_values`, or `latest_snapshot.json` through their defined interfaces
- no downstream component writes to or claims authority over Layer-2 Snapshot Truth
- no non-Layer-2 code touches Layer-2 storage beyond read-only access to `snapshots` and `snapshot_values`
- sufficient code and runtime evidence is available to support the verdict

### `review_only`

Use when:
- the change may be acceptable but runtime or code evidence is incomplete,
- interface usage is present but not clearly violating — ambiguity requires code inspection,
- the request describes partial or conditional boundary access that cannot be evaluated without more context,
- a documentation claim about boundary compliance cannot be verified without reading the relevant code.

### `raw_observations_violation`

Use when:
- any downstream Layer-3 or related code reads `observations` directly,
- any request proposes direct downstream observation access for any reason,
- any runtime path bypasses published snapshots and queries raw Layer-2 observation truth,
- the manifest hook check "grep forbidden: observations access in layer3" would match.

### `latest_snapshot_misuse`

Use when:
- `latest_snapshot.json` is used as a mutable scratch file or informal state store,
- downstream code writes to `latest_snapshot.json` outside the snapshot publisher,
- usage ignores `snapshot_id`, `as_of`, or version metadata in a governance-relevant context,
- the manifest hook check "grep forbidden: latest_snapshot misuse" would match.

### `snapshot_truth_rewrite_risk`

Use when:
- any downstream logic attempts to rewrite or supersede Layer-2 Snapshot Truth,
- Live Market State, Event Risk Stream, or another consumer claims authority over snapshot truth,
- non-Layer-2 code mutates `snapshots`, `snapshot_values`, or the published snapshot artifact.

### `ambiguous_requires_review`

Use when:
- evidence is incomplete and the request or code intent is too unclear for a deterministic verdict,
- multiple interpretations of the evidence are plausible,
- in `strict` mode: when doubt exists, fail closed to this status rather than approving silently.

---

## Patterns to detect

Apply these pattern checks when code is available.

| Pattern | Dimension | Finding |
|---|---|---|
| `SELECT ... FROM observations` in Layer-3 or downstream code | Raw observation access | `raw_observations_access_detected: true`; `raw_observations_violation` |
| Import of `upsert_observations` or `filter_new_rows` in Layer-3 module | Raw observation access | `raw_observations_access_detected: true`; `raw_observations_violation` |
| `get_connection()` called from Layer-3 for read of `observations` | Raw observation access | `raw_observations_access_detected: true`; `raw_observations_violation` |
| `latest_snapshot.json` opened for writing outside `snapshot_publisher.py` | `latest_snapshot.json` misuse | `latest_snapshot_misuse_detected: true`; `latest_snapshot_misuse` |
| `latest_snapshot.json` read without using `snapshot_id` in downstream logic | `latest_snapshot.json` misuse | flag in `notes`; `review_only` or `latest_snapshot_misuse` |
| Downstream polling loop on `latest_snapshot.json` treating it as live feed | `latest_snapshot.json` misuse | `latest_snapshot_misuse_detected: true` |
| `INSERT INTO snapshot_values` outside `snapshot_publisher.py` | Snapshot truth ownership | `snapshot_truth_rewrite_risk: true`; `snapshot_truth_rewrite_risk` |
| `UPDATE snapshots SET ...` outside `snapshot_publisher.py` | Snapshot truth ownership | `snapshot_truth_rewrite_risk: true` |
| Live Market State logic overwrites snapshot fields on volatility | Snapshot truth ownership | `snapshot_truth_rewrite_risk: true` |
| Event Risk Stream annotates `snapshot_values` directly | Snapshot truth ownership | `snapshot_truth_rewrite_risk: true`; `layer2_storage_touch_detected: true` |
| `import layer2.db` in Layer-3 for write access | Layer-2 storage touch | `layer2_storage_touch_detected: true`; `blocked` |
| JOIN of `snapshots` with `observations` in downstream query | Raw + interface boundary | `raw_observations_access_detected: true`; `raw_observations_violation` |
| `SELECT * FROM snapshots ORDER BY created_at DESC LIMIT 1` without `snapshot_id` anchor | Snapshot interface discipline | flag in `notes`; `review_only` |
| Documentation claim: "Layer-3 may read observations during bootstrap" | Raw observation access | `raw_observations_access_detected: true`; `blocked` even without code |
| `README_LAYER2.md` cited as primary authority for a boundary-rule claim | Source authority | `source_authority_conflict_detected: true`; prefer Tier 1 |

---

## Checklist

Before emitting the output, confirm each item.

- [ ] All available Layer-3 or downstream code in scope has been read and evaluated.
- [ ] Raw observation access dimension evaluated: no `observations` reads detected or the violation is flagged.
- [ ] Snapshot interface discipline evaluated: only `snapshots`, `snapshot_values`, `latest_snapshot.json`, `snapshot_id`-anchored patterns permitted.
- [ ] `latest_snapshot.json` misuse dimension evaluated: no writes outside publisher, no `snapshot_id`-less reads in governance-relevant paths, no mutable-cache use.
- [ ] Snapshot truth ownership dimension evaluated: only `snapshot_publisher.py` writes snapshot artifacts; no downstream writer detected or flagged.
- [ ] Layer-2 storage-touch dimension evaluated: no write access from non-Layer-2 code; unrestricted reads flagged.
- [ ] `overall_status` reflects the most severe finding across all `checked_items`.
- [ ] `requires_snapshot_boundary_guard` set to `true` if any violation finding is present.
- [ ] `requires_snapshot_boundary_auditor` set to `true` if code evidence was insufficient for a material compliance decision.
- [ ] `requires_doc_code_sync_review` set to `true` if documentation claims about boundary compliance cannot be confirmed from code.
- [ ] `source_authority_conflict_detected` set if `README_LAYER2.md` is used for a strong boundary or architecture claim.
- [ ] `inference_used` set correctly.
- [ ] `missing_inputs` populated for every item where evidence was absent.
- [ ] No strong `compliant` verdict emitted without code or runtime evidence.
- [ ] All canonical source citations use the Tier 1 role-matched document (`SYSTEM_TECHNICAL_HANDBOOK_v1.md` or `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` for boundary and architecture claims).

---

## Worked examples

### Example 1: Layer-3 module queries `observations` directly

**Request:** "Implement a Layer-3 snapshot consumer that queries the `observations` table directly to get the latest gold price, since `latest_snapshot.json` may not be fresh."

**Analysis:**
- Direct `observations` access from Layer-3 is forbidden by `CLAUDE.md` Section 6.1 and the manifest blocking condition `raw_observations_used_in_layer3`.
- The rationale ("may not be fresh") does not override the invariant. Freshness concerns are handled by the quality gate and fail-closed publication logic, not by bypassing the snapshot boundary.
- The `snapshot-boundary-guard` grep check "observations access in layer3" would match.

**Expected output (key fields):**

```json
{
  "snapshot_boundary_status": {
    "overall_status": "raw_observations_violation",
    "checked_items": [
      {
        "item_id": "obs-01",
        "target": "Layer-3 snapshot consumer (proposed)",
        "assessment": "blocked",
        "raw_observations_access_detected": true,
        "latest_snapshot_misuse_detected": false,
        "snapshot_truth_rewrite_risk": false,
        "layer2_storage_touch_detected": false,
        "reason": "Direct query of observations table from Layer-3 violates the snapshot boundary invariant. Layer-3 must consume only published snapshots. Freshness concerns must be handled by the fail-closed publication model, not by bypassing the boundary.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["Boundary-safe alternative: read latest_snapshot.json and anchor on snapshot_id; if snapshot is stale, fail closed."]
      }
    ],
    "summary": {
      "raw_observations_violation_detected": true,
      "requires_snapshot_boundary_guard": true
    }
  }
}
```

---

### Example 2: Snapshot consumer reads `latest_snapshot.json` via governed interface

**Request:** "Build a snapshot consumer that reads `latest_snapshot.json`, extracts `snapshot_id`, then queries `snapshot_values` WHERE `snapshot_id = ?` to populate Layer-3 state."

**Analysis:**
- `latest_snapshot.json` is read as a governed published artifact.
- `snapshot_id` is used as the truth anchor for all downstream queries.
- `snapshot_values` is queried read-only by `snapshot_id`.
- No observation access. No rewrite. No storage touch outside the governed interface.

**Expected output (key fields):**

```json
{
  "snapshot_boundary_status": {
    "overall_status": "compliant",
    "checked_items": [
      {
        "item_id": "snap-01",
        "target": "Layer-3 snapshot consumer (proposed)",
        "assessment": "compliant",
        "raw_observations_access_detected": false,
        "latest_snapshot_misuse_detected": false,
        "snapshot_truth_rewrite_risk": false,
        "layer2_storage_touch_detected": false,
        "reason": "Consumer reads latest_snapshot.json as a published artifact, anchors on snapshot_id, and queries snapshot_values read-only. All interfaces are governed. No boundary violation.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
      }
    ],
    "summary": {
      "raw_observations_violation_detected": false,
      "requires_snapshot_boundary_guard": false
    }
  }
}
```

---

### Example 3: Layer-3 populates state from `snapshots` + `snapshot_values`

**Request:** "Use `SELECT * FROM snapshots WHERE snapshot_id = ? JOIN snapshot_values USING (snapshot_id)` to populate Layer-3 decision state."

**Analysis:**
- Access is via governed snapshot tables.
- Query is `snapshot_id`-anchored.
- No observation access. No rewrite. No storage touch outside the governed interface.

**Expected output (key fields):**

```json
{
  "snapshot_boundary_status": {
    "overall_status": "compliant",
    "checked_items": [
      {
        "item_id": "snap-01",
        "target": "Layer-3 state population query",
        "assessment": "compliant",
        "raw_observations_access_detected": false,
        "latest_snapshot_misuse_detected": false,
        "snapshot_truth_rewrite_risk": false,
        "layer2_storage_touch_detected": false,
        "reason": "Query joins snapshots and snapshot_values by snapshot_id. Both are governed read interfaces. No raw observation access, no rewrite, no storage touch.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
      }
    ],
    "summary": {
      "raw_observations_violation_detected": false,
      "requires_snapshot_boundary_guard": false
    }
  }
}
```

---

### Example 4: Live Market State overwrites macro snapshot truth

**Request:** "Let Live Market State overwrite macro snapshot truth during volatile intraday conditions, since the published snapshot may be several hours old."

**Analysis:**
- Live Market State is a Layer-3 consumer. It has no authority over Layer-2 Snapshot Truth.
- Overwriting snapshot truth during volatility is exactly the pattern the snapshot-boundary invariant forbids — Snapshot Truth is Layer-2-owned and immutable once published.
- The rationale ("several hours old") does not override the invariant. Staleness is governed by the quality gate and fail-closed publication rules.
- This would be classified as `snapshot_truth_rewrite_risk`.

**Expected output (key fields):**

```json
{
  "snapshot_boundary_status": {
    "overall_status": "snapshot_truth_rewrite_risk",
    "checked_items": [
      {
        "item_id": "truth-01",
        "target": "Live Market State — proposed snapshot truth override",
        "assessment": "blocked",
        "raw_observations_access_detected": false,
        "latest_snapshot_misuse_detected": false,
        "snapshot_truth_rewrite_risk": true,
        "layer2_storage_touch_detected": false,
        "reason": "Live Market State is a Layer-3 consumer with no authority over Layer-2 Snapshot Truth. Snapshot truth is immutable once published. Staleness concerns are governed by the quality gate and fail-closed model, not by downstream rewrite.",
        "canonical_source": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "notes": ["Boundary-safe path: fail closed when snapshot is stale; do not allow downstream components to substitute their own truth."]
      }
    ],
    "summary": {
      "snapshot_truth_rewrite_risk_detected": true,
      "requires_snapshot_boundary_guard": true
    }
  }
}
```

---

### Example 5: `latest_snapshot.json` used as a mutable scratch file

**Request:** "Use `latest_snapshot.json` as a mutable scratch file. Downstream code writes adjusted values to it when intraday conditions change."

**Analysis:**
- `latest_snapshot.json` is a published Layer-2 output. Only `snapshot_publisher.py` may write it.
- Treating it as a mutable scratch file breaks replayability, identity semantics, and the snapshot-boundary invariant.
- Any component writing to `latest_snapshot.json` outside the publication cycle is committing both a `latest_snapshot_misuse` and a snapshot truth rewrite.

**Expected output (key fields):**

```json
{
  "snapshot_boundary_status": {
    "overall_status": "latest_snapshot_misuse",
    "checked_items": [
      {
        "item_id": "snap-01",
        "target": "latest_snapshot.json — proposed mutable scratch use",
        "assessment": "blocked",
        "raw_observations_access_detected": false,
        "latest_snapshot_misuse_detected": true,
        "snapshot_truth_rewrite_risk": true,
        "layer2_storage_touch_detected": false,
        "reason": "latest_snapshot.json is a published Layer-2 artifact owned by snapshot_publisher.py. Writing adjusted values to it outside the publication cycle violates replayability semantics and the snapshot truth ownership invariant.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["Only snapshot_publisher.py may write latest_snapshot.json. Downstream code must treat it as read-only and immutable for the duration of that snapshot's validity."]
      }
    ],
    "summary": {
      "latest_snapshot_misuse_detected": true,
      "snapshot_truth_rewrite_risk_detected": true,
      "requires_snapshot_boundary_guard": true
    }
  }
}
```

---

### Example 6: Event Risk Stream directly updates Layer-2 storage

**Request:** "Event Risk Stream directly updates Layer-2 storage to annotate the active snapshot with intraday event flags."

**Analysis:**
- Event Risk Stream is a downstream Layer-3 component; it has no write access to Layer-2 storage.
- Annotating `snapshot_values` or `snapshots` directly is a storage-touch violation and a snapshot truth rewrite.
- This violates both dimension 4 (snapshot truth ownership) and dimension 5 (storage-touch discipline).

**Expected output (key fields):**

```json
{
  "snapshot_boundary_status": {
    "overall_status": "snapshot_truth_rewrite_risk",
    "checked_items": [
      {
        "item_id": "truth-01",
        "target": "Event Risk Stream — proposed Layer-2 storage write",
        "assessment": "blocked",
        "raw_observations_access_detected": false,
        "latest_snapshot_misuse_detected": false,
        "snapshot_truth_rewrite_risk": true,
        "layer2_storage_touch_detected": true,
        "affected_files": ["layer2_truth.db / snapshot_values"],
        "reason": "Event Risk Stream is a Layer-3 consumer. It has no authority to write to Layer-2 storage. Annotating snapshot_values constitutes both a snapshot truth rewrite and a forbidden Layer-2 storage touch.",
        "canonical_source": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "notes": ["Event annotations must live in Layer-3 state, not in Layer-2 truth. The published snapshot is immutable from the downstream perspective."]
      }
    ],
    "summary": {
      "snapshot_truth_rewrite_risk_detected": true,
      "layer2_storage_touch_detected": true,
      "requires_snapshot_boundary_guard": true
    }
  }
}
```

---

### Example 7: Documentation claim normalizing observation access

**Request:** "Update `SYSTEM_IMPLEMENTATION_RECORD_v1.md` to state: 'Layer-3 may read observations directly during bootstrap for convenience, since snapshot publication may not be complete.'"

**Analysis:**
- No code is shown, but the documentation claim directly normalizes boundary-violating behavior.
- Documentation claims that imply boundary-violating runtime behavior must be flagged even without code evidence.
- The claim contradicts `CLAUDE.md` Section 6.1, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, and the manifest blocking condition `raw_observations_used_in_layer3`.
- The role-matched canonical source for this claim is `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (implementation-state claim), but the claim itself violates the `SYSTEM_TECHNICAL_HANDBOOK_v1.md` invariant.

**Expected output (key fields):**

```json
{
  "snapshot_boundary_status": {
    "overall_status": "raw_observations_violation",
    "inference_used": false,
    "checked_items": [
      {
        "item_id": "doc-01",
        "target": "SYSTEM_IMPLEMENTATION_RECORD_v1.md — claim: Layer-3 may read observations during bootstrap",
        "assessment": "blocked",
        "raw_observations_access_detected": true,
        "latest_snapshot_misuse_detected": false,
        "snapshot_truth_rewrite_risk": false,
        "layer2_storage_touch_detected": false,
        "missing_inputs": ["Layer-3 implementation code not inspected"],
        "reason": "The documentation claim directly normalizes raw observation access from Layer-3. This violates CLAUDE.md Section 6.1 and the manifest blocking condition raw_observations_used_in_layer3. The claim must be blocked regardless of whether implementation code is present.",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["Documentation claims that normalize boundary violations are themselves boundary violations. Fail-closed bootstrap behavior is the correct resolution — not observation access."]
      }
    ],
    "summary": {
      "raw_observations_violation_detected": true,
      "requires_snapshot_boundary_guard": true,
      "requires_doc_code_sync_review": true
    }
  }
}
```

---

## Completion standard

This skill's output is complete when all of the following hold.

1. Every file, component, or claim in scope has at least one `checked_items` entry.
2. `overall_status` reflects the most severe finding across all items: if any item is `raw_observations_violation`, `snapshot_truth_rewrite_risk`, or `latest_snapshot_misuse`, the overall status must be at least that severe.
3. `requires_snapshot_boundary_guard` is `true` whenever any violation finding is present (`raw_observations_violation`, `latest_snapshot_misuse`, `snapshot_truth_rewrite_risk`, or significant `layer2_storage_touch_detected`).
4. `requires_snapshot_boundary_auditor` is `true` whenever code or runtime evidence was unavailable for a material boundary compliance decision.
5. `requires_doc_code_sync_review` is `true` whenever a documentation claim about boundary compliance could not be verified from code, or whenever a documentation change normalizes boundary-violating behavior.
6. All `canonical_source` fields cite the Tier 1 role-matched document — `SYSTEM_TECHNICAL_HANDBOOK_v1.md` for invariant and contract-rule claims, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` for architectural responsibility claims.
7. `source_authority_conflict_detected` is set if `README_LAYER2.md` is used to support a strong boundary-rule or architecture claim.
8. `inference_used` is set correctly.
9. `missing_inputs` is populated for every item where evidence was absent.
10. No strong `compliant` verdict is emitted without code or runtime evidence.
11. The output is valid JSON conforming to the required schema.
12. In `json+summary` mode: a plain-language summary of no more than five sentences follows the JSON block, stating the overall verdict, the primary violation type if any, the affected components, and the downstream actions required.
