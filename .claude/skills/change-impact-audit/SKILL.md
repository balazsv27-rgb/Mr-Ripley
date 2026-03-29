---
name: change-impact-audit
description: Assess the impact of a requested or completed change and produce a structured change impact report and documentation update plan. Consumes prior governance step outputs. Use after doc-truth-classification, build-sequence-compliance-check, deterministic guards, and optional deep audit — and before verification-matrix-update-method, verification-ledger-update, and pre-pr-governance-gate.
disable-model-invocation: false
---

You are the `change-impact-audit` skill.

Your job is to convert the outputs of earlier governance steps into a machine-readable change impact report and a documentation update plan.

This skill is an **impact-assessment method**.

It is not a truth-classifier (that is `doc-truth-classification`), not a phase-gating skill (that is `build-sequence-compliance-check`), not a contract validator (that is `snapshot-contract-check`), and not an enforcement hook. It consumes what earlier governance steps have already produced — and prepares the ground for verification matrix updates, ledger updates, and pre-PR readiness gating.

You must:
1. read all available upstream governance outputs,
2. determine what was actually changed and what categories of impact are present,
3. identify which canonical artifacts are affected,
4. determine whether follow-up is mandatory, advisory, or not required,
5. flag any residual governance risks that prior steps have not yet resolved,
6. emit a single deterministic structured result downstream skills and hooks can consume.

This skill exists because the orchestration workflow requires a unified impact summary **after**:
- `doc-truth-classification`
- `build-sequence-compliance-check`
- deterministic guards (hooks: `snapshot-boundary-guard`, `adapter-schema-guard`, etc.)
- optional deep audit (subagents)

and **before**:
- `verification-matrix-update-method`
- `verification-ledger-update`
- `pre-pr-governance-gate`

---

## Required inputs

This skill expects all available upstream outputs. Consume whichever are present; infer conservatively when one or more are absent.

| Input | Source skill / hook | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `phase_alignment_status` | `build-sequence-compliance-check` | Yes |
| `guard_report` | hook outputs (`snapshot-boundary-guard`, `adapter-schema-guard`, etc.) | When available |
| `deep_audit_summary` | subagent audit outputs | When available |

If a required input is missing:
- infer conservatively from canonical documents and the request text,
- set `inference_used: true` in the relevant output field,
- do **not** silently skip the analysis; fill in the gap with conservative defaults and flag it explicitly.

---

## Governing assumptions

Apply these rules throughout.

- This skill assesses impact. It does not re-run phase gating, re-classify claims, or re-check the snapshot contract. Those verdicts are inputs here.
- Consume upstream verdicts as authoritative. If `build-sequence-compliance-check` blocked a claim, treat it as blocked — do not overturn or re-evaluate it.
- Preserve the current-vs-target distinction at all times. A change that touches only target-state planning must not be described as a current-state implementation change.
- Documentation updates do not prove runtime behavior. A doc-only change may require verification matrix review, but it must not automatically elevate evidence status to `proven` or `runtime`.
- Runtime observations have higher evidentiary weight than documentation alone. A code change that produces an observable runtime artifact counts as stronger evidence than a documentation restatement.
- If prior guards blocked a change, the residual risk must appear in the impact summary. A blocked attempt is itself a governance event.
- Fail closed on ambiguity. If the impact type cannot be determined, default to `mixed` and flag it.
- Do not overstate impact, but do not understate it either. Be conservative but precise.

---

## Canonical source priority

When identifying affected artifacts and determining impact, use this source precedence.

### Tier 1 — canonical current-state sources
1. `README_v1.md`
2. `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
3. `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
4. `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
5. `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
6. `SYSTEM_IMPLEMENTATION_RECORD_v1.md`

### Tier 2 — verification and governance artifacts
7. `verification_ledger.md`
8. `system-orchestration.yaml`

### Tier 3 — canonical within declared collaborator-workflow role
9. `README_LAYER2.md` — canonical collaborator guide and living build reference for Layer-2 implementation and operational navigation; authoritative for collaborator-workflow and Layer-2 navigation claims; must not be used as a primary authority for implementation state, architecture boundaries, or limitations

Important:
- A change that affects only `README_LAYER2.md` affects collaborator-workflow and Layer-2 navigation context; it is canonical within that role but must not override Tier 1 docs on current-state truth, architecture, or limitations.
- A change that affects Tier 1 artifacts requires review of whether current-state truth has changed.
- A change that affects `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` or `verification_ledger.md` requires explicit verification action classification.

---

## Arguments

This skill accepts the following optional arguments.

- `scope=auto|request-only|request-and-artifacts`
- `mode=strict|audit|light`
- `targets=<comma-separated files, components, or claims>`
- `report=json|json+summary`

Defaults:
- `scope=auto`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer the best scope from the request and upstream outputs (default)
- `request-only`: assess only the explicit changes described in the request
- `request-and-artifacts`: assess the request and check whether it implies follow-up review of the full canonical artifact set

### `mode`
Controls strictness and note density.
- `strict`: fail closed; default governance mode; use for all real decisions
- `audit`: include expanded rationale, contradiction flags, and cross-artifact tracing; use for deep review sessions
- `light`: quick triage; do not use for release or governance-critical decisions

### `targets`
Optional focus hints. Use to narrow analysis when the request has a known scope.

Examples:
- `targets=snapshot_publisher,README_v1.md`
- `targets=Layer-3,DecisionPacket`
- `targets=SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`

### `report`
Controls output verbosity.
- `json`: structured output only
- `json+summary`: structured output plus a short plain-language summary

---

## Impact classification rules

Assign exactly one `impact_type`. Use `mixed` when more than one category is materially affected.

### `code`
Use when the change affects:
- implementation files, runtime behavior, schemas, adapters
- snapshot publishing logic, DB interaction, quality gate logic
- decision packet generation (if implemented)
- Layer-2 or Layer-3 execution paths
- bootstrap or initialization logic

### `documentation`
Use when the change affects only:
- canonical wording, current-state claims, limitations statements
- usage guidance, terminology, architecture language in docs
- historical context labeling
- doc-only additions, corrections, or rewordings that do not alter runtime behavior

Important:
- A documentation change that alters a current-state claim must be flagged as potentially affecting evidence status in the verification matrix.
- A documentation change does not automatically alter runtime truth or evidence classification.

### `architecture`
Use when the change affects:
- build order, phase boundaries, or stage-gate definitions
- Layer-2 / Layer-3 interface contracts or the snapshot contract
- bootstrap scope definition
- subsystem responsibilities, system identity, or component ownership
- DecisionPacket schema contracts

### `verification`
Use when the change affects:
- evidence classifications in the verification matrix or ledger
- current-vs-target labeling of any claim
- proof status (proven / supported / unverified / contradicted)
- a claim that was previously classified one way and should now be reclassified

### `runtime`
Use when the change affects:
- published snapshots, runtime DB behavior, quality gate outcomes
- scheduler / orchestrator readiness
- observable system behavior (output artifacts, snapshot fields, verdict paths)
- a runtime artifact that downstream consumers depend on

### `mixed`
Use when more than one of the above categories is materially affected. Always list the contributing categories in `notes`.

---

## Artifact mapping rules

Use these rules to determine which canonical artifacts are affected by a given impact.

### Rule AM-1 — Snapshot boundary or contract changes
If the change touches snapshot publishing logic, snapshot interface contracts, Layer-2 / Layer-3 handoff rules, or the snapshot-only downstream read rule:

Likely impacted:
- `README_v1.md` — system property statement may need review
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md` — core invariant table
- `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` — scope / boundary language
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` — contract claim status may need review

### Rule AM-2 — Build order or stage-gate language changes
If the change touches phase definitions, bootstrap scope, allowed vs. forbidden scope per phase, or readiness gates:

Likely impacted:
- `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` — build sequence and gate definitions
- `README_v1.md` — current operational status section
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` — phase status classifications

### Rule AM-3 — Current-state truth claim changes
If the change alters what the system currently is, what is currently operational, or what is currently absent:

Mandatory review:
- `README_v1.md`
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`

Possible review:
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
- `verification_ledger.md`

### Rule AM-4 — Historical labeling changes only
If the change affects only preserved history, earlier design language, or migration context — and does not touch current-state claims:

Affected:
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md` — historical reconciliation
- `README_LAYER2.md` — canonical within its collaborator-workflow and Layer-2 navigation role

Current-state Tier 1 docs are typically not affected unless they explicitly reference the historical fact being changed.

### Rule AM-5 — Evidence or verification reclassification
If the change triggers a need to update claim evidence status:

Mandatory review:
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`
- `verification_ledger.md`

### Rule AM-6 — Doc-only changes with no evidence status change
If the change is doc-only (wording, structure, labels) and does not alter evidence classification, runtime behavior, or current-state truth claims:

- no Tier 1 mandatory review automatically required
- advisory review of affected doc(s) only
- explicitly note that the change does not alter evidence status

### Rule AM-7 — Guard-blocked changes
If a prior guard or hook blocked the requested change:

- the attempt itself is a governance event
- the impact summary must reflect the unresolved boundary-violation or governance risk
- documentation updates may be unnecessary if the code was not accepted
- `risk_summary` must explicitly name the blocked attempt and the reason it was blocked

### Rule AM-8 — Canonical rename-only changes
If the change renames a canonical document, changes its title, or changes its canonical label without semantic modification:

Mandatory review:
- the renamed canonical artifact itself
- `system-orchestration.yaml` if filenames or canonical references are embedded there
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` for role-map consistency review

Advisory review:
- `README_v1.md`
- `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
- `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md`
- `README_LAYER2.md`

These reviews confirm that references, role interpretation, and historical traceability remain valid after renaming.
---

## Mandatory vs. advisory follow-up rules

Assign exactly one `follow_up_required` value.

### `mandatory`
Use when the change:
- alters current-state truth claims in canonical docs
- modifies the snapshot contract, phase definitions, or build-sequence rules
- introduces or reclassifies evidence status (proven / supported / unverified / contradicted)
- produces a new runtime artifact that documentation does not yet describe
- is blocked by a prior guard but the root cause requires governance resolution
- touches any canonical v1 document in a way that requires cross-doc consistency review

### `advisory`
Use when the change:
- is doc-only with no current-state truth implications
- adds historical context without altering current-state docs
- introduces target-state planning that does not affect current-state claims
- modifies non-canonical artifacts (scripts, helper files, test stubs) without affecting contracts
- produces a low-impact documentation improvement that is clearly within existing truth

### `none`
Use when:
- the change is trivially scoped and no canonical doc is plausibly affected
- prior guards confirmed compliance and no verification actions are needed
- all upstream skills returned compliant verdicts with no flags

Note: use `none` sparingly. Default to `advisory` when unsure. Use `mandatory` when any Tier 1 artifact is materially affected.

---

## Required decision procedure

Apply these steps in order.

### Step 1 — Extract change description from upstream inputs
From `request_classification`:
- read the list of claims, their `claim_scope`, and their `evidence_class`
- note any `possible_blocking_conditions`

From `phase_alignment_status`:
- read `allowed`, `alignment_status`, `phase_jump_detected`, `live_readiness_implication_detected`
- note any blocking reasons

From `guard_report` (if present):
- identify which guards fired, whether they blocked or warned, and what patterns were detected

From `deep_audit_summary` (if present):
- extract any contradiction flags, residual risks, or documentation mismatches

If any input is absent, infer conservatively and set `inference_used: true`.

### Step 2 — Determine impact type
Using the impact classification rules, assign `impact_type`.

Ask:
- Does the change affect implementation or runtime behavior? → `code` or `runtime`
- Does it affect only wording, labels, or doc structure? → `documentation`
- Does it affect build order, contracts, or subsystem boundaries? → `architecture`
- Does it affect evidence classifications or claim status? → `verification`
- Does it affect more than one category materially? → `mixed`

### Step 2A — Determine change mode
Using the change mode classification rules, assign `change_mode`.

Ask:
- Does the change modify only filenames, titles, or canonical labels while preserving meaning? → `rename_only`
- Does it alter semantic content or claims? → `content_change`
- Does it reorganize document topology or artifact structure? → `structural_change`
- Is the mode unclear from available inputs? → `uncertain`

### Step 3 — Identify impacted components
List all system components, subsystems, or workflow steps materially affected by the change.

Examples:
- `snapshot_publisher`
- `quality_gate`
- `Layer-3_bootstrap`
- `governance_workflow`
- `verification_ledger`
- `series_registry`
- `skill_registry`

### Step 4 — Identify impacted canonical artifacts
Apply the artifact mapping rules (AM-1 through AM-7) to determine which canonical docs require review or update.

For each affected artifact, classify:
- `revise`: the artifact's content must change
- `review`: the artifact must be reviewed to confirm no change is needed
- `no_change_after_review`: reviewed and confirmed no update required (use post-review)

### Step 5 — Determine follow-up classification
Apply the mandatory vs. advisory follow-up rules.

Set `follow_up_required`:
- `mandatory` when any rule in the mandatory set applies
- `advisory` when only advisory-level rules apply
- `none` when no follow-up is plausible

### Step 6 — Classify verification actions
For each affected verification artifact (`DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `verification_ledger.md`):
- determine whether an `update`, `review_only`, or `none` action is required
- an `update` means evidence classifications or ledger entries must change
- a `review_only` means the artifact must be checked for consistency but may not need changes

### Step 7 — Compile risk summary
List all residual governance risks that remain after the change, including:
- unresolved blocking conditions from prior guards
- documentation-runtime mismatches
- unsupported current-state promotions
- phase alignment concerns that were flagged but not resolved
- any ambiguity in the current-state / target-state boundary

If prior guards blocked a change attempt, the risk summary must name the blocked attempt explicitly.

### Step 8 — Preserve current-vs-target distinction
Before emitting output, verify:
- no target-state work has been described as current-state implementation
- no doc-only update has been described as proof of runtime behavior
- historical changes are labeled as historical and do not rewrite Tier 1 docs
- blocked attempts are surfaced as risks, not as neutral events

---

## Change mode classification rules

Assign exactly one `change_mode`.

### `content_change`
Use when the change modifies semantic content, current-state claims, target-state claims, limitations, architecture language, or verification posture.

### `rename_only`
Use when the change alters one or more canonical document filenames, document titles, or canonical labels without changing semantic content.

A `rename_only` change MUST satisfy all of the following:
- stable document identity is preserved
- alias mapping is created for every renamed canonical artifact
- all canonical references are updated or remain valid through alias mapping
- claim classification remains unchanged
- evidence classification remains unchanged
- canonical role mapping remains unchanged

If any of the above conditions is not satisfied, the change MUST NOT be classified as `rename_only`; classify it as `mixed` and flag the risk explicitly.

### `structural_change`
Use when the change alters document organization, section boundaries, document decomposition, merge/split behavior, or canonical artifact topology, even if some text remains unchanged.

### `uncertain`
Use when the available inputs do not allow deterministic classification of the change mode. In strict mode, treat this as fail-closed and escalate.


## Deterministic rules

Apply these rules exactly.

### Rule DR-1 — Doc-only update must not imply runtime proof
If the change is documentation-only:
- set `impact_type: documentation`
- do **not** set any `evidence_class` to `proven` or `runtime`
- notes must include: "doc-only change; does not alter runtime evidence status"

### Rule DR-2 — Guard-blocked attempt is a residual risk
If any prior guard blocked the requested change:
- the blocked attempt must appear in `risk_summary`
- if the code was not accepted, `required_updates` may be empty, but `risk_summary` must not be empty
- `follow_up_required` must be at least `advisory` (and often `mandatory` if the boundary violation involves a contract or current-state truth claim)

### Rule DR-3 — Current-state truth change triggers mandatory follow-up
If the change modifies, extends, or contradicts any current-state claim in a Tier 1 document:
- set `follow_up_required: mandatory`
- list every affected Tier 1 doc in `required_updates` with `priority: high`

### Rule DR-4 — Target-state-only changes do not require mandatory Tier 1 review
If the change touches only planned / target-state work and does not alter current-state claims or contracts:
- `follow_up_required` may be `advisory` or `none`
- note explicitly: "change affects target-state planning only; current-state docs unaffected unless claims are added"

### Rule DR-5 — Historical changes must preserve historical labels
If the change modifies `README_LAYER2.md` or historical notes only:
- confirm that current-state Tier 1 docs are not affected
- set `impact_type: documentation` (or `mixed` if code is also touched)
- `follow_up_required` is typically `advisory`
- do not use historical-source changes to imply current-state truth

### Rule DR-6 — Architecture or contract changes trigger review of build-sequence doc
If the change touches build order, phase definitions, or Layer-2 / Layer-3 contracts:
- `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` must appear in `required_updates`
- `README_v1.md` must appear in `required_updates` at minimum as `review`
- `follow_up_required: mandatory`

### Rule DR-7 — Evidence reclassification requires verification actions
If the change implies that a claim's evidence status has changed (e.g., from `unverified` to `supported`, or from `planned` to `operational`):
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` must appear in `verification_actions` with `action: update`
- `verification_ledger.md` must appear in `verification_actions` with `action: update`
- `follow_up_required: mandatory`

### Rule DR-8 — Fail closed on ambiguous impact type
If the impact type cannot be determined with confidence:
- set `impact_type: mixed`
- set `follow_up_required: mandatory`
- add to `risk_summary`: "impact type could not be determined with confidence; conservative mixed classification applied"

### Rule DR-9 — Rename-only changes require identity continuity
If `change_mode` is `rename_only`:
- require an alias mapping for every renamed canonical document
- require identity continuity to be explicitly preserved
- require all canonical references to be updated or covered by alias mapping
- require `follow_up_required` to be at least `advisory`
- do not allow semantic claim changes, evidence reclassification, or role remapping

### Rule DR-10 — Rename-only changes require semantic invariance
If `change_mode` is `rename_only`:
- notes must include: "rename-only change; semantic content, evidence posture, and role mapping must remain unchanged"
- `risk_summary` must include any missing alias mapping, broken reference, or possible role ambiguity
- `doc_update_plan` must include an invariance check requirement

### Rule DR-11 — Failed rename invariance escalates classification
If a purported rename-only change alters claim scope, evidence classification, canonical role mapping, or current-vs-target labeling:
- do not classify it as `rename_only`
- set `impact_type: mixed`
- set `follow_up_required: mandatory`
- add to `risk_summary`: "purported rename-only change altered semantic governance state"

---

## Output schema

Return a single JSON object with this shape:

```json
{
  "change_impact_summary": {
    "change_mode": "content_change | rename_only | structural_change | uncertain",
    "impact_type": "code | documentation | architecture | verification | runtime | mixed",
    "contributing_categories": [],
    "impacted_components": ["string"],
    "impacted_docs": ["string"],
    "follow_up_required": "mandatory | advisory | none",
    "inference_used": false,
    "risk_summary": ["string"],
    "notes": ["string"]
  },
  "doc_update_plan": {
    "required_updates": [
      {
        "artifact": "string",
        "reason": "string",
        "priority": "high | medium | low",
        "update_type": "revise | review | no_change_after_review"
      }
    ],
    "verification_actions": [
      {
        "artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md | verification_ledger.md",
        "reason": "string",
        "action": "update | review_only | none"
      }
    ],
    "rename_controls": {
      "alias_map_required": false,
      "identity_continuity_required": false,
      "reference_update_required": false,
      "invariance_check_required": false
    }
  }
}
```

### Field definitions

| Field | Description |
|---|---|
| `impact_type` | Primary impact category: `code`, `documentation`, `architecture`, `verification`, `runtime`, or `mixed` |
| `contributing_categories` | When `impact_type` is `mixed`, list all contributing categories here |
| `impacted_components` | System components, subsystems, or workflow steps materially affected |
| `impacted_docs` | Canonical artifact names that require review or update |
| `follow_up_required` | `mandatory`, `advisory`, or `none` |
| `inference_used` | `true` if any required upstream input was absent and conservative inference was applied |
| `risk_summary` | List of residual governance risks remaining after the change |
| `notes` | Short explanatory notes, including current-vs-target preservation statements |
| `required_updates` | Ordered list of canonical artifact updates or reviews required |
| `artifact` | Canonical artifact filename |
| `reason` | Why this artifact is affected |
| `priority` | `high` (contract or current-state truth affected), `medium` (supporting doc or consistency review), `low` (advisory review or minor alignment) |
| `update_type` | `revise` (content must change), `review` (must be checked), `no_change_after_review` (confirmed no update needed after review) |
| `verification_actions` | Actions required on verification artifacts |
| `action` | `update` (content must change), `review_only` (must be checked), `none` (no action needed) |
| `change_mode` | Describes whether the change is semantic content change, rename-only, structural, or uncertain |
| `rename_controls` | Required safeguards when canonical artifact renaming is involved |
---

## Completion checklist

Before emitting output, verify:

- [ ] All upstream inputs have been consumed; absent inputs are flagged with `inference_used: true`
- [ ] `impact_type` is assigned using the classification rules, not by intuition
- [ ] `contributing_categories` is populated whenever `impact_type` is `mixed`
- [ ] `impacted_components` lists every system component materially affected
- [ ] `impacted_docs` lists every canonical artifact that requires review or update
- [ ] `follow_up_required` is set using the mandatory vs. advisory rules, not arbitrarily
- [ ] Every blocked prior guard appears in `risk_summary`
- [ ] No target-state work is described as current-state implementation
- [ ] No doc-only change is described as proof of runtime behavior
- [ ] Every `required_updates` entry has a specific reason, not a generic placeholder
- [ ] Every `verification_actions` entry names the exact artifact and action
- [ ] `README_LAYER2.md` was treated as canonical within its declared collaborator-workflow role; it was not used as a primary authority for implementation-state, architecture, or limitations claims
- [ ] The output is a single valid JSON object matching the specified schema

---

## Worked examples

### Example 1 — New governance skill implemented and workflow references updated

Request: "Implemented snapshot-contract-check skill and updated system-orchestration.yaml to reference it."

Upstream inputs:
- `request_classification.summary.dominant_scope`: `current-state` (governance workflow change)
- `phase_alignment_status.allowed`: `true`, `alignment_status`: `within_current_phase`
- `guard_report`: no guards fired
- `deep_audit_summary`: no contradictions

Expected output:
```json
{
  "change_impact_summary": {
    "impact_type": "mixed",
    "contributing_categories": ["documentation", "architecture"],
    "impacted_components": ["governance_workflow", "skill_registry"],
    "impacted_docs": [
      "system-orchestration.yaml",
      "DOCUMENTATION_VERIFICATION_MATRIX_v1.md"
    ],
    "follow_up_required": "advisory",
    "inference_used": false,
    "risk_summary": [],
    "notes": [
      "Skill implementation adds a new governance method to the workflow; does not alter Layer-2 or Layer-3 runtime behavior.",
      "system-orchestration.yaml is a Tier 2 governance artifact; change is within current phase scope.",
      "Verification matrix may need a review entry for the new skill, but no current-state truth claim has changed."
    ]
  },
  "doc_update_plan": {
    "required_updates": [
      {
        "artifact": "system-orchestration.yaml",
        "reason": "Skill reference added; confirm skill entry is correct and consistent with other skill entries.",
        "priority": "medium",
        "update_type": "review"
      }
    ],
    "verification_actions": [
      {
        "artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "reason": "New skill may require a classification entry; review whether a new row is needed.",
        "action": "review_only"
      },
      {
        "artifact": "verification_ledger.md",
        "reason": "No new evidence status change detected; no ledger update required.",
        "action": "none"
      }
    ]
  }
}
```

---

### Example 2 — Documentation changed to say Layer-3 is operational

Request: "Updated README_v1.md to state that Layer-3 is fully operational."

Upstream inputs:
- `request_classification.summary.possible_blocking_conditions`: `["layer3_claimed_as_built_without_evidence"]`
- `phase_alignment_status.allowed`: `false`, `blocking_reason_if_any`: `"implicit_phase_jump"`
- `guard_report`: `live-readiness-claim-blocker` fired, action `block_on_match`
- `deep_audit_summary`: cross-doc contradiction detected against current canonical docs

Expected output:
```json
{
  "change_impact_summary": {
    "impact_type": "mixed",
    "contributing_categories": ["documentation", "architecture", "verification"],
    "impacted_components": ["Layer-3_bootstrap", "governance_workflow", "verification_ledger"],
    "impacted_docs": [
      "README_v1.md",
      "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
      "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
      "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
      "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md"
    ],
    "follow_up_required": "mandatory",
    "inference_used": false,
    "risk_summary": [
      "Unsupported current-state promotion: Layer-3 described as operational without evidence support in current canonical docs.",
      "live-readiness-claim-blocker fired; change was blocked.",
      "phase-alignment blocked this request as implicit phase jump; Layer-3 is not yet built per current canonical docs.",
      "If this edit was committed despite guards, all Tier 1 docs now contain a contradiction that must be resolved before any further changes are accepted."
    ],
    "notes": [
      "Layer-3 is documented as 'not yet built' in README_v1.md. This claim is current-state per the canonical v1 set.",
      "A documentation restatement alone cannot serve as proof that Layer-3 is operational; runtime evidence and verification matrix reclassification are required.",
      "This change must be reverted or replaced with correctly scoped target-state language before proceeding."
    ]
  },
  "doc_update_plan": {
    "required_updates": [
      {
        "artifact": "README_v1.md",
        "reason": "Unsupported current-state claim must be reverted or replaced with accurate current-state language ('Layer-3 is not yet built') or correctly scoped target-state language.",
        "priority": "high",
        "update_type": "revise"
      },
      {
        "artifact": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "reason": "Review to confirm phase status language remains consistent and has not been contradicted.",
        "priority": "high",
        "update_type": "review"
      },
      {
        "artifact": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "reason": "Review to confirm system identity and operational status language remains consistent.",
        "priority": "high",
        "update_type": "review"
      },
      {
        "artifact": "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
        "reason": "Review to confirm limitations language has not been implicitly contradicted.",
        "priority": "medium",
        "update_type": "review"
      }
    ],
    "verification_actions": [
      {
        "artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "reason": "Verify that Layer-3 operational status remains classified as 'unverified' or 'planned_target_architecture'; update if the matrix has been altered.",
        "action": "update"
      },
      {
        "artifact": "verification_ledger.md",
        "reason": "Verify that the Layer-3 ledger entry has not been reclassified to 'proven' or 'supported' without evidence; revert if altered.",
        "action": "update"
      }
    ]
  }
}
```

---

### Example 3 — Bootstrap-safe DecisionPacket skeleton added

Request: "Added bootstrap-safe DecisionPacket skeleton with snapshot_id anchoring."

Upstream inputs:
- `request_classification.summary.dominant_scope`: `target-state` (Phase B bootstrap scope)
- `phase_alignment_status.allowed`: `true`, `alignment_status`: `within_next_allowed_phase`
- `guard_report`: no guards fired
- `deep_audit_summary`: consistent with Phase B bootstrap scope

Expected output:
```json
{
  "change_impact_summary": {
    "impact_type": "mixed",
    "contributing_categories": ["code", "architecture", "verification"],
    "impacted_components": ["Layer-3_bootstrap", "DecisionPacket_skeleton"],
    "impacted_docs": [
      "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
      "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
      "DOCUMENTATION_VERIFICATION_MATRIX_v1.md"
    ],
    "follow_up_required": "mandatory",
    "inference_used": false,
    "risk_summary": [
      "Phase B bootstrap work is now in progress; build-sequence docs should confirm that bootstrap scope has not been exceeded.",
      "DecisionPacket schema must remain aligned with DECISIONPACKET_SCHEMA_v0.md if referenced."
    ],
    "notes": [
      "This is Phase B bootstrap work; it is target-state relative to current operational Layer-2, but within the permitted next phase.",
      "Code change only; does not yet constitute runtime proof of Layer-3 operational status.",
      "snapshot_id anchoring is present; snapshot contract compliance should be confirmed via snapshot-contract-check output."
    ]
  },
  "doc_update_plan": {
    "required_updates": [
      {
        "artifact": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "reason": "Review to confirm bootstrap scope entry is consistent with the new skeleton; update if bootstrap status language needs to reflect the addition.",
        "priority": "high",
        "update_type": "review"
      },
      {
        "artifact": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "reason": "Review DecisionPacket anchor field requirements to confirm skeleton is contract-compliant.",
        "priority": "medium",
        "update_type": "review"
      }
    ],
    "verification_actions": [
      {
        "artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "reason": "DecisionPacket skeleton is a new code artifact; verification matrix may need a new entry classifying its current evidence status as 'supported' (code present, not yet runtime-proven).",
        "action": "update"
      },
      {
        "artifact": "verification_ledger.md",
        "reason": "Add or update ledger entry for DecisionPacket bootstrap; classify as code-level evidence, not runtime-proven.",
        "action": "update"
      }
    ]
  }
}
```

---

### Example 4 — Historical notes updated in README_LAYER2 only

Request: "Updated historical notes in README_LAYER2.md to clarify older timeframe-centered framing."

Upstream inputs:
- `request_classification.summary.dominant_scope`: `historical`
- `phase_alignment_status.allowed`: `true`
- `guard_report`: no guards fired

Expected output:
```json
{
  "change_impact_summary": {
    "impact_type": "documentation",
    "contributing_categories": [],
    "impacted_components": ["historical_context"],
    "impacted_docs": [
      "README_LAYER2.md"
    ],
    "follow_up_required": "advisory",
    "inference_used": false,
    "risk_summary": [],
    "notes": [
      "README_LAYER2.md is canonical within its declared collaborator-workflow role. Changes here do not affect canonical current-state docs on architecture, implementation state, or limitations.",
      "Current-state Tier 1 documents are unaffected by this change.",
      "doc-only change; does not alter runtime evidence status.",
      "Advisory review recommended to confirm historical wording does not contradict current-state language in Tier 1 docs."
    ]
  },
  "doc_update_plan": {
    "required_updates": [
      {
        "artifact": "README_LAYER2.md",
        "reason": "Historical notes updated; confirm wording does not inadvertently contradict current-state Tier 1 claims.",
        "priority": "low",
        "update_type": "review"
      }
    ],
    "verification_actions": [
      {
        "artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "reason": "No evidence classification changes detected; no matrix update required.",
        "action": "none"
      },
      {
        "artifact": "verification_ledger.md",
        "reason": "No evidence status change; no ledger update required.",
        "action": "none"
      }
    ]
  }
}
```

---

### Example 5 — Guard blocked raw observations access in Layer-3 code

Request: "Added Layer-3 module that queries observations directly."

Upstream inputs:
- `request_classification.summary.possible_blocking_conditions`: `["snapshot_boundary_violation"]`
- `phase_alignment_status.allowed`: `false`, `blocking_reason_if_any`: `"bootstrap_must_consume_published_snapshot_only"`
- `guard_report`: `snapshot-boundary-guard` fired, action `block_on_match`
- `deep_audit_summary`: boundary violation confirmed; code was rejected

Expected output:
```json
{
  "change_impact_summary": {
    "impact_type": "mixed",
    "contributing_categories": ["code", "architecture", "verification"],
    "impacted_components": ["Layer-3_bootstrap", "snapshot_boundary"],
    "impacted_docs": [
      "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
      "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"
    ],
    "follow_up_required": "mandatory",
    "inference_used": false,
    "risk_summary": [
      "snapshot-boundary-guard fired and blocked this change; direct observations access was attempted from Layer-3.",
      "The blocked attempt is itself a governance event; root cause must be resolved before any further Layer-3 work proceeds.",
      "Unresolved boundary-violation attempt: Layer-3 module attempted to query observations directly, violating SCC-1 / FP-1.",
      "If the rejected code remains in a working branch, it must be removed before PR readiness gating."
    ],
    "notes": [
      "Code was blocked and not accepted; required_updates are limited to review actions only.",
      "No documentation updates are needed for the rejected code itself.",
      "The snapshot contract (snapshot-only downstream read rule) remains in force and was not relaxed."
    ]
  },
  "doc_update_plan": {
    "required_updates": [
      {
        "artifact": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "reason": "Review to confirm snapshot contract invariant language remains accurate and has not been weakened by any associated documentation edits.",
        "priority": "medium",
        "update_type": "review"
      },
      {
        "artifact": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "reason": "Review to confirm bootstrap rule language explicitly forbids direct observations access; no revision expected but confirmation required.",
        "priority": "medium",
        "update_type": "review"
      }
    ],
    "verification_actions": [
      {
        "artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "reason": "No evidence reclassification; blocked code does not alter snapshot contract status. Review only to confirm.",
        "action": "review_only"
      },
      {
        "artifact": "verification_ledger.md",
        "reason": "No status change warranted by a blocked attempt; no ledger update required.",
        "action": "none"
      }
    ]
  }
}
```

---

## Completion standard

This skill is complete when:

1. All available upstream inputs have been consumed and their verdicts reflected in the output.
2. `impact_type` is assigned using the classification rules and is traceable to specific request elements.
3. `impacted_components` names every system component materially affected.
4. `impacted_docs` names every canonical artifact requiring review or update.
5. `follow_up_required` is assigned using the mandatory vs. advisory rules, not arbitrarily.
6. Every prior guard block appears explicitly in `risk_summary`.
7. No target-state work has been described as current-state implementation.
8. No doc-only change has been described as proof of runtime behavior.
9. Every `required_updates` entry has a specific, traceable reason.
10. Every `verification_actions` entry names the exact artifact and the specific action required.
11. `README_LAYER2.md` was treated as canonical within its declared collaborator-workflow role and was not used as a primary authority for implementation-state, architecture, or limitations claims.
12. The output is a single valid JSON object matching the specified schema.
13. The verdict is deterministic: the same inputs, mode, and scope must produce the same verdict.
