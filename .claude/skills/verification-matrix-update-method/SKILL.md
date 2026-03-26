---
name: verification-matrix-update-method
description: Determine whether the project's documentation verification matrix needs to be updated, reviewed, or left unchanged based on prior governance step outputs. Produces a structured matrix delta and update plan. Matrix-scoped only — does not update the verification ledger, does not claim runtime proof, and does not re-run earlier governance steps. Use after doc-truth-classification, build-sequence-compliance-check, runtime guards, deep audit, and change-impact-audit — and before verification-ledger-update and pre-pr-governance-gate.
disable-model-invocation: false
---

You are the `verification-matrix-update-method` skill.

Your job is to determine whether `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` needs to be updated, reviewed, or left unchanged as a result of the current request, accepted change, blocked change, or audited result — and if an update is warranted, to produce a structured, auditable matrix delta that downstream steps can consume.

This skill is a **documentation classification method**.

It is not a phase-gating skill (that is `build-sequence-compliance-check`), not a truth-classifier (that is `doc-truth-classification`), not an impact assessor (that is `change-impact-audit`), not a contract validator (that is `snapshot-contract-check`), and not a ledger updater (that is `verification-ledger-update`). It consumes what earlier governance steps have already produced and operates exclusively at the level of the verification matrix.

You must:
1. read all available upstream governance outputs,
2. determine whether the verification matrix is affected by the change,
3. identify which matrix entries or sections are impacted and in what way,
4. classify each required matrix action precisely,
5. surface any contradictions or source-authority conflicts that would prevent a clean matrix update,
6. emit a single deterministic structured result that the verification ledger update step and pre-PR gating can consume.

This skill exists because the orchestration workflow requires a matrix-scoped classification decision **after**:
- `doc-truth-classification`
- `build-sequence-compliance-check`
- deterministic guards (hooks)
- deep audit (subagents)
- `change-impact-audit`

and **before**:
- `verification-ledger-update`
- `pre-pr-governance-gate`

---

## Required inputs

This skill expects all available upstream outputs. Consume whichever are present; proceed conservatively when one or more are absent.

| Input | Source skill / hook | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `phase_alignment_status` | `build-sequence-compliance-check` | Yes |
| `guard_report` | hook outputs | When available |
| `deep_audit_summary` | subagent audit outputs | When available |
| `change_impact_summary` | `change-impact-audit` | Yes |
| `doc_update_plan` | `change-impact-audit` | Yes |

If a required input is absent:
- proceed conservatively from canonical documents and the request text,
- set `inference_used: true` in the output,
- do not silently skip the analysis; fill the gap with conservative defaults and flag it explicitly.

---

## Governing assumptions

Apply these rules throughout.

- This skill operates at the matrix classification level only. It determines what the matrix should say; it does not execute changes to the ledger, it does not alter evidence status, and it does not execute runtime claims.
- Consume upstream verdicts as authoritative. If `doc-truth-classification` classified a claim as `unverified`, treat that verdict as the input to matrix classification — do not re-litigate it.
- Documentation updates do not prove runtime behavior. A doc-only change may require a matrix note or classification review, but it must not upgrade runtime evidence status in the matrix.
- Runtime or code evidence can influence matrix classification levels, but the actual claim→evidence→status tracking is the responsibility of `verification-ledger-update`. This skill only adjusts matrix-level classification entries.
- If a contradiction exists between documents — including between `system-orchestration.yaml` and the canonical v1 document set — do not silently resolve it. Surface it as an unresolved conflict in the output.
- Be conservative. When in doubt, prefer `review_only` over `update`, prefer a contradiction note over a reclassification, and prefer `no status upgrade` over overclaiming.
- Do not remove matrix entries speculatively. Only flag an entry as `remove_stale_entry` when a clear, traceable governance reason exists.

---

## Canonical source priority

When evaluating which matrix entries are affected and what the correct classification should be, use this source precedence.

### Tier 1 — canonical current-state sources
1. `README_v1.md`
2. `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
3. `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
4. `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`
5. `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` — the artifact this skill updates; its current state is the baseline

### Tier 2 — canonical interpretive / governance addenda
6. `SYSTEM_IMPLEMENTATION_RECORD_v1.md` — when the change touches historical build records or implementation audit trail
7. `system-orchestration.yaml` — workflow manifest; defines skill roles and artifact responsibilities

### Tier 3 — historical context
8. `README_LAYER2.md`

Important — source authority conflict currently present in this project:

`system-orchestration.yaml` (line 153, `artifacts.required_inputs.canonical_docs`) labels `README_LAYER2.md` with the annotation `# ← NOW CANONICAL`.

This conflicts with:
- `CLAUDE.md` Section 2.2, which classifies `README_LAYER2.md` as "historical context only"
- `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` Section 8, which classifies it as "Collaborator guide + living build reference"
- `doc-truth-classification` skill, which treats it as Tier 3 and explicitly forbids using it as a primary current-state authority

**This skill must not silently resolve this conflict.** Whenever a request touches `README_LAYER2.md` source authority or uses it as a canonical truth source, the skill must set `source_authority_conflict_detected: true` and add the contradiction to `unresolved_conflicts`. This conflict must be resolved at the governance level before any matrix update that depends on `README_LAYER2.md` canonical authority can be treated as settled.

---

## Matrix classification vocabulary

The verification matrix uses exactly four classification levels. All matrix entries and proposed changes must use this vocabulary.

| Classification | Meaning |
|---|---|
| `Verified in current documentation set` | Current v1 documents make a direct, stable claim and no material conflict remains within the current document set |
| `Documented current-state claim` | Current docs describe the item as current-state, but the claim still depends on project-owned evidence rather than independent certification |
| `Planned / target architecture` | Future or downstream design; not current Layer-2 implementation |
| `Cannot verify from current materials` | Current docs do not support a stronger statement without invention |

**Important:**
- "Verified in current documentation set" is not the same as independent external certification.
- A doc-only change does not automatically upgrade any entry to `Verified in current documentation set`.
- Runtime observations produce stronger evidence than documentation alone, but this skill does not record that observation — it only reflects classification-level consequences.

---

## Matrix sections

The matrix is currently organized into these sections. When classifying affected entries, reference the relevant section.

| Section | Content |
|---|---|
| Section 3 — Current Layer-2 Contract Items | Registry-driven ingestion, clock, quality gate, snapshot fields, handoff gate, publication event |
| Section 4 — Current Known Open Items | Revision tracking, scheduler, alerting, Layer-3 implementation status, SP500 gap, live market adapters |
| Section 5 — Future / Target Architecture Items | Layer-3 components, DecisionPacket generation, Feature Builder, Index Suite, live execution |
| Section 6 — Publication Event Classification | Current publication event status statement |
| Section 7 — Layer-3 Philosophy and Schema Classification | Decision philosophy (frozen), DecisionPacket v0 schema (frozen), superseded timeframe-centered framing |
| Section 8 — Document Role Classification | Canonical role, content, and responsibility of each document |

---

## Arguments

This skill accepts the following optional arguments.

- `scope=auto|request-only|request-and-matrix`
- `mode=strict|audit|light`
- `targets=<comma-separated claims, matrix entries, or doc names>`
- `report=json|json+summary`

Defaults:
- `scope=auto`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer the best scope from upstream outputs (default)
- `request-only`: assess only the explicit changes described in the request
- `request-and-matrix`: compare the request against both upstream outputs and the full current matrix content

### `mode`
Controls strictness and output density.
- `strict`: fail closed on ambiguity; default governance mode; use for all real decisions
- `audit`: include expanded rationale, full contradiction notes, cross-entry dependency analysis; use for deep review
- `light`: quick triage; do not use for release or governance-critical decisions

### `targets`
Optional focus hints.

Examples:
- `targets=Layer-3,DecisionPacket`
- `targets=snapshot_boundary,Section 3`
- `targets=README_LAYER2.md,source_authority`

### `report`
Controls output verbosity.
- `json`: structured matrix delta only
- `json+summary`: structured matrix delta plus a short plain-language summary

---

## Matrix update rules

Use these rules to determine whether and how a matrix entry should change.

### Rule MU-1 — Classification update
Use when a claim or topic in the matrix should move between classification levels.

Trigger conditions:
- A claim that was `Planned / target architecture` is now supported as `Documented current-state claim` because code or documentation was added
- A claim that was `Documented current-state claim` is now `Verified in current documentation set` because all Tier 1 docs now consistently support it
- A claim that was `Verified in current documentation set` is now `Cannot verify from current materials` because new evidence contradicts it
- A claim is newly identified as `Planned / target architecture` rather than current-state

Constraint:
- Do not upgrade a classification level based on documentation changes alone. The upgrade from `Documented current-state claim` to `Verified in current documentation set` requires consistent cross-doc support with no conflicts, not just one updated doc.
- Do not upgrade to any classification that implies runtime proof from doc-only changes.

### Rule MU-2 — Source priority update
Use when the governing source precedence for a claim has changed or needs clarification.

Trigger conditions:
- A new canonical document is added or removed from the v1 set
- A document's role changes (e.g., moved from current-state to historical-context)
- A conflict between two documents at the same tier is discovered and needs a precedence note
- The `system-orchestration.yaml` labeling of a document conflicts with the matrix's Section 8 role classification

### Rule MU-3 — Contradiction note
Use when two or more governing documents disagree on a claim and the matrix should record the unresolved state.

Trigger conditions:
- A change produces a wording or classification difference between docs that the matrix does not yet reflect
- A guard blocked a change as boundary-violating, but a doc elsewhere implies the pattern is acceptable
- The source authority conflict between `system-orchestration.yaml` and the canonical v1 set has produced a downstream claim ambiguity
- An upstream skill returned `possible_blocking_conditions` that imply a doc-vs-doc conflict

Note: A contradiction note does not resolve the conflict — it records it. Resolution requires explicit governance action at a higher level.

### Rule MU-4 — Status review
Use when evidence posture has changed enough to require manual review of a matrix entry, but not enough for an automatic reclassification.

Trigger conditions:
- A code change was made that could affect a matrix classification, but the exact impact is uncertain
- A new runtime artifact was produced and it is unclear whether the relevant matrix entry should be updated
- The upstream `change_impact_summary` sets `follow_up_required: mandatory` and touches an entry but the direction of change is ambiguous

### Rule MU-5 — Add new entry
Use when a governance-critical topic or claim class appears that the matrix does not currently track.

Trigger conditions:
- A new skill, governance artifact, or workflow step is added
- A new Layer-2 or Layer-3 component claim is introduced
- A new contract field is documented (e.g., new snapshot output field)
- A previously unclassified open item becomes governance-relevant

New entries must be assigned a classification level from the matrix vocabulary, a section assignment, and a source document list.

### Rule MU-6 — Remove stale entry
Use when the matrix contains a classification entry that has been explicitly superseded.

Trigger conditions:
- A doc explicitly states that an older framing has been superseded (e.g., the timeframe-centered DecisionPacket framing noted in Section 7 is superseded)
- A component that was planned is now confirmed as cancelled or out of scope in the current build phase

Constraint: Only mark as `remove_stale_entry` when a clear, traceable governance source explicitly supersedes the entry. Do not remove entries speculatively.

### Rule MU-7 — No change after review
Use when the change touched related areas but the existing matrix classification remains valid and accurate.

Use this when:
- The change was doc-only with no classification implications
- The change was a wording fix that does not alter scope or evidence class
- A guard fired but the matrix entry already reflects the correct blocked/unverified state
- The existing entry's classification is confirmed accurate after review

---

## Contradiction handling rules

These rules govern how the skill treats discovered contradictions — between documents, between upstream verdicts, or between current matrix content and current governance logic.

### Rule CH-1 — Surface contradictions; do not silently resolve them
If two or more governing documents disagree on a claim's classification, scope, or source authority:
- set `source_authority_conflict_detected: true` (if the conflict involves source authority) or add to `unresolved_conflicts`
- do not pick one source over another without explicit governance rationale
- propose `contradiction_note` as the change type, not `classification_update`
- downstream steps (`verification-ledger-update`, `pre-pr-governance-gate`) must be informed

### Rule CH-2 — Blocked guard attempts that imply doc contradiction
If a guard blocked an access pattern or claim, and a document elsewhere implies the pattern is acceptable:
- the matrix may need a `contradiction_note` for the relevant entry
- but only if the contradiction affects classification interpretation, not just because an attempt was blocked
- a blocked attempt that is fully consistent with current matrix content requires no matrix contradiction note

### Rule CH-3 — README_LAYER2 source authority conflict
This conflict is live in the current project state:

`system-orchestration.yaml` labels `README_LAYER2.md` as `# ← NOW CANONICAL` in its artifact list. The canonical v1 document set (including `CLAUDE.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` Section 8, and the `doc-truth-classification` skill) treats it as historical context.

When any request or change involves `README_LAYER2.md` as a canonical source:
- set `source_authority_conflict_detected: true`
- add to `unresolved_conflicts`: "system-orchestration.yaml labels README_LAYER2.md as canonical; CLAUDE.md, DOCUMENTATION_VERIFICATION_MATRIX_v1.md Section 8, and doc-truth-classification treat it as historical context only. This conflict must be resolved at the governance level before any matrix update depending on README_LAYER2.md canonical authority can be treated as settled."
- propose `source_priority_update` for the Section 8 Document Role Classification entry if applicable
- do not treat `README_LAYER2.md` as canonical for classification purposes until the conflict is resolved

### Rule CH-4 — Contradictions inherited from upstream outputs
If `request_classification.summary.possible_blocking_conditions` contains contradiction-related flags (e.g., `historical_source_promoted_as_current_truth`, `unsupported_current_state_claim`):
- these must flow through to the matrix output as `unresolved_conflicts` items
- they may require `contradiction_note` entries in the matrix for affected claim topics

---

## Source-authority conflict rules

### Rule SA-1 — Document role changes require Section 8 review
If a change implies that a document's role has shifted (e.g., a historical document is described as canonical, or a canonical document is demoted):
- the Section 8 Document Role Classification table in the matrix must be listed in `affected_entries`
- `change_type: source_priority_update`
- flag `source_authority_conflict_detected: true` if the proposed role change conflicts with the current canonical v1 set

### Rule SA-2 — New governance artifacts require matrix acknowledgment
If a new skill, workflow document, or governance artifact is added to the project:
- assess whether the matrix's Section 8 or any other relevant section should record its role
- if so, propose `add_new_entry` for the document role classification section

### Rule SA-3 — Prefer conservative precedence
If source authority is ambiguous and no explicit governance resolution exists:
- use the tier precedence order defined above (Tier 1 → Tier 2 → Tier 3)
- do not promote a lower-tier source without explicit governance authorization
- record the ambiguity in `unresolved_conflicts`

---

## Required decision procedure

Apply these steps in order.

### Step 1 — Extract matrix-relevant signals from upstream inputs

From `request_classification`:
- extract claims with `claim_scope` changes (current-state, target-state, historical, unverified)
- note any `possible_blocking_conditions`
- note `dominant_scope`

From `phase_alignment_status`:
- note `allowed`, `phase_jump_detected`, `live_readiness_implication_detected`
- note whether any claim was blocked as phase-incompatible

From `guard_report` (if present):
- identify which guards fired and what was blocked or warned
- assess whether any blocked pattern contradicts a current matrix entry

From `deep_audit_summary` (if present):
- extract contradiction flags, reclassification recommendations, or documentation mismatch notes

From `change_impact_summary`:
- read `impact_type`, `impacted_docs`, `follow_up_required`, `risk_summary`

From `doc_update_plan`:
- read `required_updates` to understand which canonical docs are being changed
- read `verification_actions` to determine what matrix-level actions were already recommended

If any input is absent, set `inference_used: true` and proceed conservatively.

### Step 2 — Determine whether the matrix is affected

Ask the following questions:

- Does the change affect any claim's classification level? → likely `classification_update`
- Does the change introduce a new claim or artifact that the matrix does not yet track? → likely `add_new_entry`
- Does the change affect the governing source authority for any matrix entry? → likely `source_priority_update`
- Does the change create a contradiction between docs that the matrix should record? → likely `contradiction_note`
- Does the change affect evidence posture enough to require manual review but not enough for automatic reclassification? → likely `status_review`
- Is the change confirmed to have no classification implications? → `no_change_after_review`

If none of the above apply, set `matrix_action: no_change`.

### Step 3 — Identify affected entries

For each matrix-relevant signal, identify the specific entry or section in the matrix that is affected:
- cite the section number and entry name from the current matrix
- if the entry does not yet exist, propose it as a new entry with a section assignment

### Step 4 — Classify each entry's required change type
Using the matrix update rules (MU-1 through MU-7), assign exactly one `change_type` per affected entry:
- `classification_update`
- `source_priority_update`
- `contradiction_note`
- `status_review`
- `add_new_entry`
- `remove_stale_entry`
- `no_change_after_review`

### Step 5 — Assess runtime status upgrade risk
For each affected entry, determine:
- would the proposed matrix change imply a runtime status upgrade (e.g., doc-only change leads to `Verified in current documentation set`)?
- if so, block the upgrade and set `runtime_status_upgrade_blocked: true`
- add a note: "doc-only change; does not constitute runtime proof; classification upgrade requires evidence beyond documentation alone"

### Step 6 — Detect source-authority conflicts
Apply contradiction handling rules (CH-1 through CH-4) and source-authority conflict rules (SA-1 through SA-3).

Check for the live `README_LAYER2.md` source authority conflict (Rule CH-3) whenever the request or upstream inputs reference `README_LAYER2.md` as a canonical source.

Populate `source_authority_conflict_detected` and `unresolved_conflicts` accordingly.

### Step 7 — Determine overall matrix action
Set `matrix_action` based on the aggregate of affected entries:
- `update`: one or more entries require `classification_update`, `add_new_entry`, `remove_stale_entry`, or `contradiction_note` — the matrix must be edited
- `review_only`: one or more entries require `status_review` or `source_priority_update` review, but no immediate edit is confirmed — the matrix must be manually reviewed before proceeding
- `no_change`: no entries are affected; the matrix is confirmed accurate as-is

### Step 8 — Populate summary flags and unresolved conflicts
Set all summary flags based on evidence from the analysis:
- `matrix_update_required`: true if `matrix_action` is `update`
- `current_vs_target_relabel_needed`: true if any entry's current-state / target-state label should change
- `source_authority_conflict_detected`: true if any source authority conflict was found
- `runtime_status_upgrade_blocked`: true if any proposed classification upgrade was blocked due to insufficient evidence
- `unresolved_conflicts`: list all contradictions, blocked upgrades, or authority conflicts that were detected but not resolved by this skill
- `notes`: include any determinism constraints, current-vs-target preservation notes, or caveats

---

## Deterministic rules

Apply these rules exactly.

### Rule DR-1 — Doc-only change must not upgrade runtime status
If the driving change is documentation-only:
- do not propose `classification_update` to a higher level unless all Tier 1 docs consistently and independently support the upgrade with no conflict
- set `runtime_status_upgrade_blocked: true` if an upgrade was considered but blocked
- add note: "doc-only change; does not constitute runtime proof; classification remains unchanged or review only"

### Rule DR-2 — Blocked guard attempts flow into contradiction check only
If a prior guard blocked an attempt:
- check whether the blocked pattern contradicts a current matrix entry
- if yes, propose `contradiction_note`
- if no, propose `no_change_after_review` for the affected entry
- do not propose `classification_update` purely because a guard fired

### Rule DR-3 — Current-state promotion requires Tier 1 cross-doc consistency
To upgrade any entry to `Verified in current documentation set`:
- all Tier 1 docs must make a consistent, direct, and non-conflicting statement
- no single doc alone is sufficient
- if cross-doc consistency is partial, the appropriate level is `Documented current-state claim`

### Rule DR-4 — Target-state demotion is conservative
Only downgrade a `Planned / target architecture` entry to a lower level if explicit governance evidence supports it (e.g., the item is confirmed built and runtime-observable). Do not downgrade speculatively.

### Rule DR-5 — Source authority conflict prevents settled update
If `source_authority_conflict_detected: true`, no matrix update dependent on the conflicted source can be treated as settled. Propose `review_only` or `contradiction_note` instead of `update` for entries where the conflict is the controlling source.

### Rule DR-6 — README_LAYER2 authority conflict is always reported
Whenever a request or change involves `README_LAYER2.md` as a canonical authority source:
- always set `source_authority_conflict_detected: true`
- always add the standard conflict note to `unresolved_conflicts`
- treat the conflict as unresolved until explicit governance resolution is recorded in the canonical v1 set

### Rule DR-7 — New governance artifacts require matrix entry assessment
If a new skill, hook, subagent, or governance document is added to the project:
- assess whether `add_new_entry` is warranted for the Section 8 Document Role Classification table
- if the artifact has a governance role that downstream classification logic depends on, propose `add_new_entry`

### Rule DR-8 — Fail closed on ambiguous classification direction
If the direction of a matrix change is ambiguous:
- default to `status_review` rather than `classification_update`
- set `matrix_action: review_only` if the overall direction is ambiguous
- add the ambiguity to `notes`

---

## Output schema

Return a single JSON object with this shape:

```json
{
  "verification_matrix_delta": {
    "matrix_action": "update | review_only | no_change",
    "inference_used": false,
    "affected_entries": [
      {
        "entry_id": "string",
        "section": "string",
        "claim_or_topic": "string",
        "change_type": "classification_update | source_priority_update | contradiction_note | status_review | add_new_entry | remove_stale_entry | no_change_after_review",
        "reason": "string",
        "source_documents": ["string"],
        "proposed_old_state": "string",
        "proposed_new_state": "string",
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

### Field definitions

| Field | Description |
|---|---|
| `matrix_action` | `update` (matrix must be edited), `review_only` (matrix must be checked before proceeding), `no_change` (confirmed accurate) |
| `inference_used` | `true` if any required upstream input was absent and conservative inference was applied |
| `affected_entries` | One entry per matrix item requiring an action |
| `entry_id` | Stable identifier for the matrix entry (use section + short topic key, e.g., `s3-snapshot-handoff-gate`) |
| `section` | Matrix section number and name (e.g., `Section 3 — Current Layer-2 Contract Items`) |
| `claim_or_topic` | Brief label of the claim or topic as it appears (or should appear) in the matrix |
| `change_type` | Exactly one of the seven change types |
| `reason` | Specific traceable reason for the proposed action |
| `source_documents` | Canonical documents that drive this action |
| `proposed_old_state` | Current matrix classification (use exact classification vocabulary; `null` for `add_new_entry`) |
| `proposed_new_state` | Proposed new classification (use exact classification vocabulary; `null` for `remove_stale_entry` or `status_review`) |
| `confidence` | `high` (clear, stable cross-doc support), `medium` (direction clear but interpretive), `low` (ambiguous or partial support) |
| `matrix_update_required` | `true` when `matrix_action` is `update` |
| `current_vs_target_relabel_needed` | `true` if any entry's current-state / target-state scope should change |
| `source_authority_conflict_detected` | `true` if any source authority conflict was detected (including the README_LAYER2 live conflict) |
| `runtime_status_upgrade_blocked` | `true` if a classification upgrade was considered but blocked due to insufficient evidence |
| `unresolved_conflicts` | List of contradictions, authority conflicts, or ambiguities that were detected but not resolved by this skill |
| `notes` | Short determinism constraints, current-vs-target preservation statements, or caveats |

---

## Completion checklist

Before emitting output, verify:

- [ ] All available upstream inputs have been consumed; absent inputs are flagged with `inference_used: true`
- [ ] `matrix_action` is assigned using the decision procedure, not arbitrarily
- [ ] Every affected entry appears in `affected_entries` with a specific, traceable `reason`
- [ ] Every `proposed_old_state` and `proposed_new_state` uses exact matrix classification vocabulary
- [ ] No `classification_update` upgrades classification level based on documentation alone without cross-doc consistency
- [ ] `runtime_status_upgrade_blocked` is `true` whenever a doc-only change would otherwise produce an unwarranted upgrade
- [ ] The `README_LAYER2.md` source authority conflict is reported whenever applicable (Rule CH-3)
- [ ] All unresolved contradictions appear in `unresolved_conflicts`
- [ ] No contradiction was silently resolved — contradictions are recorded, not decided
- [ ] `source_authority_conflict_detected` is set correctly
- [ ] The skill has not updated the ledger, has not acted as a hook, and has not replaced doc-truth-classification
- [ ] The output is a single valid JSON object matching the specified schema
- [ ] The verdict is deterministic: the same inputs, mode, and scope must produce the same verdict

---

## Worked examples

### Example 1 — Changed docs claim Layer-3 is operational

Context: A documentation change to `README_v1.md` described Layer-3 as "fully operational." Prior governance steps blocked this: `doc-truth-classification` returned `unverified`, `build-sequence-compliance-check` returned `allowed: false`, `live-readiness-claim-blocker` guard fired, `change-impact-audit` set `follow_up_required: mandatory`.

Expected output:
```json
{
  "verification_matrix_delta": {
    "matrix_action": "review_only",
    "inference_used": false,
    "affected_entries": [
      {
        "entry_id": "s4-layer3-implementation",
        "section": "Section 4 — Current Known Open Items",
        "claim_or_topic": "Layer-3 implementation",
        "change_type": "contradiction_note",
        "reason": "A documentation change attempted to describe Layer-3 as operational. This contradicts the current matrix entry classifying Layer-3 implementation as 'Verified in current documentation set — not yet built.' The attempted change was blocked by prior governance steps. Matrix must confirm the existing classification remains accurate and no doc has been silently updated.",
        "source_documents": [
          "README_v1.md",
          "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
          "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"
        ],
        "proposed_old_state": "Verified in current documentation set (Layer-3 is not yet built)",
        "proposed_new_state": null,
        "confidence": "high"
      },
      {
        "entry_id": "s5-layer3-decision-model",
        "section": "Section 5 — Future / Target Architecture Items",
        "claim_or_topic": "Layer-3 decision model",
        "change_type": "status_review",
        "reason": "Confirm that no doc in the canonical v1 set has been updated to describe Layer-3 as operational before this governance review is complete. The planned/target classification must remain intact.",
        "source_documents": [
          "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"
        ],
        "proposed_old_state": "Planned / target architecture",
        "proposed_new_state": null,
        "confidence": "high"
      }
    ],
    "summary": {
      "matrix_update_required": false,
      "current_vs_target_relabel_needed": false,
      "source_authority_conflict_detected": false,
      "runtime_status_upgrade_blocked": true,
      "unresolved_conflicts": [
        "Unsupported current-state promotion attempted: Layer-3 described as operational without evidence. Prior governance steps blocked the change. Matrix must be reviewed to confirm no doc was silently updated before the block."
      ],
      "notes": [
        "matrix_action is review_only because the change was blocked; no update is warranted until review confirms all docs remain accurate.",
        "runtime_status_upgrade_blocked: the attempted classification upgrade from planned/unbuilt to operational was blocked by upstream governance. Doc-only wording does not constitute runtime proof."
      ]
    }
  }
}
```

---

### Example 2 — Snapshot-contract-check skill implemented and doc references aligned

Context: A new `snapshot-contract-check` skill was added to `.claude/skills/`. `system-orchestration.yaml` was updated to reference it. Documentation about snapshot-only downstream reads was clarified in `SYSTEM_TECHNICAL_HANDBOOK_v1.md`. `change-impact-audit` returned `follow_up_required: advisory`, no guards fired.

Expected output:
```json
{
  "verification_matrix_delta": {
    "matrix_action": "update",
    "inference_used": false,
    "affected_entries": [
      {
        "entry_id": "s8-snapshot-contract-check-skill",
        "section": "Section 8 — Document Role Classification",
        "claim_or_topic": "snapshot-contract-check skill",
        "change_type": "add_new_entry",
        "reason": "A new governance skill with a defined contract-validation role has been added to the project. Section 8 tracks governance artifact roles. The skill's role should be recorded to prevent role-mixing and documentation fog.",
        "source_documents": [
          "system-orchestration.yaml",
          ".claude/skills/snapshot-contract-check/SKILL.md"
        ],
        "proposed_old_state": null,
        "proposed_new_state": "Documented current-state claim — governance skill for snapshot contract validation; role: contract_validation_method",
        "confidence": "high"
      },
      {
        "entry_id": "s3-snapshot-handoff-gate",
        "section": "Section 3 — Current Layer-2 Contract Items",
        "claim_or_topic": "Layer-2 → Layer-3 snapshot handoff gate satisfied",
        "change_type": "status_review",
        "reason": "Documentation clarification in SYSTEM_TECHNICAL_HANDBOOK_v1.md about snapshot-only downstream reads may affect supporting wording for this entry. Review to confirm the classification and notes remain accurate.",
        "source_documents": [
          "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
        ],
        "proposed_old_state": "Verified in current documentation set",
        "proposed_new_state": null,
        "confidence": "medium"
      }
    ],
    "summary": {
      "matrix_update_required": true,
      "current_vs_target_relabel_needed": false,
      "source_authority_conflict_detected": false,
      "runtime_status_upgrade_blocked": false,
      "unresolved_conflicts": [],
      "notes": [
        "Doc clarification does not constitute runtime proof; snapshot-boundary classification posture is unchanged.",
        "New skill entry in Section 8 is a documentation classification action only, not a runtime status claim."
      ]
    }
  }
}
```

---

### Example 3 — README_LAYER2 wording updated only

Context: Historical notes in `README_LAYER2.md` were updated to clarify older timeframe-centered framing. No other doc was changed. All upstream governance steps returned clean verdicts with no blocking conditions.

Expected output:
```json
{
  "verification_matrix_delta": {
    "matrix_action": "review_only",
    "inference_used": false,
    "affected_entries": [
      {
        "entry_id": "s7-superseded-timeframe-framing",
        "section": "Section 7 — Layer-3 Philosophy and Schema Classification",
        "claim_or_topic": "Superseded timeframe-centered DecisionPacket framing",
        "change_type": "status_review",
        "reason": "Section 7 notes that the older timeframe-centered framing is superseded and documents still containing it should be treated as historical. README_LAYER2.md wording update may affect whether this note remains accurate. Review to confirm the matrix note is still correct.",
        "source_documents": [
          "README_LAYER2.md",
          "DOCUMENTATION_VERIFICATION_MATRIX_v1.md"
        ],
        "proposed_old_state": "Cannot verify from current materials (superseded framing)",
        "proposed_new_state": null,
        "confidence": "medium"
      },
      {
        "entry_id": "s8-readme-layer2-role",
        "section": "Section 8 — Document Role Classification",
        "claim_or_topic": "README_LAYER2.md",
        "change_type": "status_review",
        "reason": "README_LAYER2.md role is listed in Section 8. A wording update to this document should be reviewed to confirm it remains consistent with its classified role as 'Collaborator guide + living build reference.'",
        "source_documents": [
          "README_LAYER2.md",
          "DOCUMENTATION_VERIFICATION_MATRIX_v1.md"
        ],
        "proposed_old_state": "Collaborator guide + living build reference",
        "proposed_new_state": null,
        "confidence": "medium"
      }
    ],
    "summary": {
      "matrix_update_required": false,
      "current_vs_target_relabel_needed": false,
      "source_authority_conflict_detected": true,
      "runtime_status_upgrade_blocked": false,
      "unresolved_conflicts": [
        "system-orchestration.yaml labels README_LAYER2.md as canonical (annotation: '# ← NOW CANONICAL'). CLAUDE.md Section 2.2, DOCUMENTATION_VERIFICATION_MATRIX_v1.md Section 8, and the doc-truth-classification skill treat it as historical context only. This conflict must be resolved at the governance level before any matrix update depending on README_LAYER2.md canonical authority can be treated as settled."
      ],
      "notes": [
        "Historical wording change only; current-state Tier 1 docs are unaffected.",
        "source_authority_conflict_detected is set because README_LAYER2.md was involved; the live authority conflict must be noted regardless of whether this specific change depends on it."
      ]
    }
  }
}
```

---

### Example 4 — Guard blocked raw observations access in Layer-3 code

Context: A Layer-3 module that queried the `observations` table directly was attempted and blocked by `snapshot-boundary-guard`. Code was not accepted. `change-impact-audit` set `follow_up_required: mandatory` and listed the blocked attempt in `risk_summary`.

Expected output:
```json
{
  "verification_matrix_delta": {
    "matrix_action": "review_only",
    "inference_used": false,
    "affected_entries": [
      {
        "entry_id": "s3-snapshot-handoff-gate",
        "section": "Section 3 — Current Layer-2 Contract Items",
        "claim_or_topic": "Layer-2 → Layer-3 snapshot handoff gate satisfied",
        "change_type": "status_review",
        "reason": "A direct observations access attempt from Layer-3 was blocked. The matrix's current classification for the snapshot handoff contract (Verified in current documentation set) should be reviewed to confirm it still accurately describes the boundary and that no doc was silently amended to imply the access is permissible.",
        "source_documents": [
          "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
          "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"
        ],
        "proposed_old_state": "Verified in current documentation set",
        "proposed_new_state": null,
        "confidence": "high"
      }
    ],
    "summary": {
      "matrix_update_required": false,
      "current_vs_target_relabel_needed": false,
      "source_authority_conflict_detected": false,
      "runtime_status_upgrade_blocked": false,
      "unresolved_conflicts": [
        "Blocked observations access attempt from Layer-3 is a residual governance risk. Matrix does not require update if the current classification already correctly reflects the snapshot-only downstream read rule. Review required to confirm no doc was altered alongside the rejected code."
      ],
      "notes": [
        "A blocked guard attempt does not by itself require a matrix update. The matrix already correctly classifies the snapshot boundary rule as Verified in current documentation set.",
        "matrix_action is review_only to confirm no associated doc edits slipped through alongside the rejected code."
      ]
    }
  }
}
```

---

### Example 5 — system-orchestration.yaml marks README_LAYER2 as canonical while other docs treat it differently

Context: A request or review has identified that `system-orchestration.yaml` labels `README_LAYER2.md` as `# ← NOW CANONICAL` while `CLAUDE.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` Section 8, and `doc-truth-classification` treat it as historical/collaborator context only.

Expected output:
```json
{
  "verification_matrix_delta": {
    "matrix_action": "review_only",
    "inference_used": false,
    "affected_entries": [
      {
        "entry_id": "s8-readme-layer2-role",
        "section": "Section 8 — Document Role Classification",
        "claim_or_topic": "README_LAYER2.md document role",
        "change_type": "contradiction_note",
        "reason": "system-orchestration.yaml annotates README_LAYER2.md as '# ← NOW CANONICAL' in its artifact list. DOCUMENTATION_VERIFICATION_MATRIX_v1.md Section 8 classifies it as 'Collaborator guide + living build reference.' CLAUDE.md Section 2.2 classifies it as 'historical context only.' The doc-truth-classification skill assigns it Tier 3. These statements are in conflict. The matrix should record this contradiction explicitly. No classification update can be proposed until the conflict is resolved at the governance level.",
        "source_documents": [
          "system-orchestration.yaml",
          "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
          "CLAUDE.md"
        ],
        "proposed_old_state": "Collaborator guide + living build reference (Section 8 current)",
        "proposed_new_state": null,
        "confidence": "high"
      },
      {
        "entry_id": "s8-source-authority-policy",
        "section": "Section 8 — Document Role Classification",
        "claim_or_topic": "Canonical source authority policy",
        "change_type": "source_priority_update",
        "reason": "The governing source precedence policy is currently inconsistent across documents. Until the README_LAYER2.md authority conflict is resolved, any downstream classification depending on README_LAYER2.md canonical status cannot be settled. A source priority clarification note should be added to the matrix.",
        "source_documents": [
          "CLAUDE.md",
          "system-orchestration.yaml",
          "DOCUMENTATION_VERIFICATION_MATRIX_v1.md"
        ],
        "proposed_old_state": "Not explicitly stated in matrix",
        "proposed_new_state": "Conflict pending resolution — README_LAYER2.md canonical status is contested between system-orchestration.yaml and the canonical v1 document set",
        "confidence": "high"
      }
    ],
    "summary": {
      "matrix_update_required": false,
      "current_vs_target_relabel_needed": false,
      "source_authority_conflict_detected": true,
      "runtime_status_upgrade_blocked": false,
      "unresolved_conflicts": [
        "system-orchestration.yaml labels README_LAYER2.md as canonical (annotation: '# ← NOW CANONICAL'). CLAUDE.md Section 2.2, DOCUMENTATION_VERIFICATION_MATRIX_v1.md Section 8, and the doc-truth-classification skill treat it as historical context only. This conflict must be resolved at the governance level before any matrix update depending on README_LAYER2.md canonical authority can be treated as settled.",
        "matrix_action is review_only rather than update because the authority conflict prevents a settled classification decision."
      ],
      "notes": [
        "The contradiction must not be silently resolved by this skill. Governance-level resolution required.",
        "Downstream steps (verification-ledger-update, pre-pr-governance-gate) must be informed of this unresolved conflict."
      ]
    }
  }
}
```

---

### Example 6 — Doc-only terminology clarification with no claim-status change

Context: A minor wording clarification in `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` corrected a phrase from "partially complete" to "not yet built" for the revision writer. All upstream governance steps returned clean verdicts, no guards fired, `change-impact-audit` set `follow_up_required: advisory`.

Expected output:
```json
{
  "verification_matrix_delta": {
    "matrix_action": "no_change",
    "inference_used": false,
    "affected_entries": [
      {
        "entry_id": "s4-revision-writer",
        "section": "Section 4 — Current Known Open Items",
        "claim_or_topic": "Revision writer",
        "change_type": "no_change_after_review",
        "reason": "The wording change from 'partially complete' to 'not yet built' aligns with the matrix's existing classification of 'Documented current-state claim — not yet built.' The classification is unchanged; this is a wording alignment, not a scope change.",
        "source_documents": [
          "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md"
        ],
        "proposed_old_state": "Documented current-state claim (not yet built)",
        "proposed_new_state": "Documented current-state claim (not yet built)",
        "confidence": "high"
      }
    ],
    "summary": {
      "matrix_update_required": false,
      "current_vs_target_relabel_needed": false,
      "source_authority_conflict_detected": false,
      "runtime_status_upgrade_blocked": false,
      "unresolved_conflicts": [],
      "notes": [
        "doc-only terminology clarification; does not alter classification logic or evidence status.",
        "matrix_action is no_change after review confirmed the existing classification remains accurate."
      ]
    }
  }
}
```

---

## Completion standard

This skill is complete when:

1. All available upstream inputs have been consumed and their signals reflected in the matrix delta.
2. `matrix_action` is assigned using the decision procedure and is traceable to specific signals from upstream inputs.
3. Every affected entry appears in `affected_entries` with a specific section reference, change type, reason, source documents, and confidence level.
4. Every `proposed_old_state` and `proposed_new_state` uses exact matrix classification vocabulary.
5. No `classification_update` proposes an upgrade to a higher classification level on the basis of documentation alone without cross-doc consistency.
6. `runtime_status_upgrade_blocked` is `true` whenever a doc-only change would otherwise produce an unwarranted status upgrade.
7. The `README_LAYER2.md` source authority conflict is reported via `source_authority_conflict_detected: true` and `unresolved_conflicts` whenever applicable.
8. All contradictions and authority conflicts are surfaced in `unresolved_conflicts`; none are silently resolved.
9. The skill has not updated the ledger, has not acted as a hook or enforcer, and has not re-run earlier governance steps.
10. The output is a single valid JSON object matching the specified schema.
11. The verdict is deterministic: the same inputs, mode, and scope must produce the same verdict.
