# Skills Reference

This document describes every implemented governance skill in the Mr. Ripley project.
It is derived from the individual `SKILL.md` files in `.claude/skills/` and the orchestration manifest at `.claude/workflows/system-orchestration.yaml`.

Each skill is documented with: role, description, type, category, governing assumptions, canonical source priority, inputs, outputs, skill dependencies, and its assigned workflow step.

---

## Master Overview

| # | Skill | Role | Type | Category | Workflow Step | Layer |
|---|---|---|---|---|---|---|
| 1 | `doc-truth-classification` | claim_classification_method | Classification | Semantic / Documentary | `classify-claims` | A |
| 2 | `canonical-terminology-map` | normalization_method | Normalization | Semantic / Documentary | `normalize-terminology` | A |
| 3 | `role-matched-citation-check` | interpretation_method | Source Validation | Semantic / Documentary | `route-claims-by-role` | A |
| 4 | `build-sequence-compliance-check` | phase_alignment_method | Phase Gating | Architecture / Phase / Contract | `phase-check` | B |
| 5 | `snapshot-contract-check` | contract_validation_method | Contract Validation | Architecture / Phase / Contract | `snapshot-contract-check` | B |
| 6 | `snapshot-boundary-check` | runtime_integrity_method | Runtime Integrity | Runtime / Schema / Boundary | `runtime-boundary-check` | C |
| 7 | `adapter-schema-review` | schema_validation_method | Schema Validation | Runtime / Schema / Boundary | `adapter-schema-check` | C |
| 8 | `change-impact-audit` | impact_assessment_method | Impact Assessment | Audit / Impact | `change-impact-audit` | D |
| 9 | `doc-code-sync-rules` | consistency_method | Consistency Validation | Audit / Impact | `doc-code-sync-check` | D |
| 10 | `verification-matrix-update-method` | doc_classification_method | Verification Classification | Verification / Hygiene / Release | `update-verification-matrix` | E |
| 11 | `verification-ledger-update` | evidence_tracking_method | Evidence Tracking | Verification / Hygiene / Release | `update-verification-ledger` | E |
| 12 | `runtime-artifact-hygiene-check` | workspace_integrity_method | Workspace Integrity | Verification / Hygiene / Release | `runtime-artifact-hygiene-check` | E |

---

## Execution Layers

| Layer | Name | Skills |
|---|---|---|
| A | Semantic / Normalization | `doc-truth-classification`, `canonical-terminology-map`, `role-matched-citation-check` |
| B | Architecture / Phase / Contract Gating | `build-sequence-compliance-check`, `snapshot-contract-check` |
| C | Runtime / Schema / Boundary Integrity | `snapshot-boundary-check`, `adapter-schema-review` |
| D | Audit / Impact | `change-impact-audit`, `doc-code-sync-rules` |
| E | Verification / Hygiene / Release Readiness | `verification-matrix-update-method`, `verification-ledger-update`, `runtime-artifact-hygiene-check` |

---

## Dependency Chain

```
load-context (constitution)
  └── classify-claims            [doc-truth-classification]
        └── normalize-terminology [canonical-terminology-map]
              └── route-claims-by-role [role-matched-citation-check]
                    └── phase-check  [build-sequence-compliance-check]
                          └── snapshot-contract-check [snapshot-contract-check]
                                └── stage-gate-enforcement (stage_gates)
                                      └── runtime-boundary-check [snapshot-boundary-check]
                                            └── adapter-schema-check [adapter-schema-review]
                                                  └── runtime-guards-summary (hooks)
                                                        └── deep-audit (subagents)
                                                              └── change-impact-audit [change-impact-audit]
                                                                    └── doc-code-sync-check [doc-code-sync-rules]
                                                                          └── update-verification-matrix [verification-matrix-update-method]
                                                                                └── update-verification-ledger [verification-ledger-update]
                                                                                      └── runtime-artifact-hygiene-check [runtime-artifact-hygiene-check]
                                                                                            └── pre-pr-governance-readiness (hooks)
```

---

## Skill 1 — `doc-truth-classification`

### Overview

| Field | Value |
|---|---|
| **Name** | `doc-truth-classification` |
| **Role** | claim_classification_method |
| **Type** | Classification |
| **Category** | Semantic / Documentary Governance |
| **Workflow Step** | `classify-claims` |
| **Layer** | A — Semantic / Normalization |
| **Execution Priority** | 1 (first skill invoked after constitution load) |
| **SKILL.md Path** | `.claude/skills/doc-truth-classification/SKILL.md` |

### Description

Classifies every major claim or requested change in the user's request as `current-state`, `target-state`, `historical`, or `unverified`, using canonical source priority and evidence-aware confidence rules. This is the foundational classification step. All downstream skills consume its output (`request_classification`). It is a classification method only — it does not enforce permissions, execute phase gating, or update any artifact.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Prefer the canonical v1 document set for current-state interpretation. |
| 2 | `README_LAYER2.md` is canonical within its declared role as collaborator guide and living build reference for Layer-2 implementation and operational navigation. It must not be used as primary source for claims outside that declared role. |
| 3 | Distinguish strictly between what is implemented now, what is planned, what is historical, and what is unsupported. |
| 4 | Do not promote target architecture to current implementation status. |
| 5 | Do not promote historical wording to current truth unless the current v1 set explicitly supports it. |
| 6 | Do not decide whether work is allowed — only classify and surface routing flags for downstream enforcement. |
| 7 | Fail closed on ambiguous claims: if support is weak or conflicting, assign `unverified`. |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** (canonical current-state) | `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (canonical record of what is actually implemented and realized; primary source for implementation-state claims) |
| **Tier 2** (interpretive / governance addenda) | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` (Layer-3 decision philosophy, DecisionPacket schema, architectural framing), `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (current implementation state and boundary status) |
| **Tier 3** (canonical within declared collaborator-workflow role) | `README_LAYER2.md` |

### Inputs

| Input | Source | Required |
|---|---|---|
| User request or change under review | Caller | Yes |
| `governance_context` | `load-context` (constitution) | Yes |
| Canonical docs (Tier 1–2) | Canonical document set | Yes |

### Outputs

| Output | Description |
|---|---|
| `claim_classification_map` | Structured JSON: per-claim `claim_scope`, `evidence_class`, `source_priority`, `confidence_level`, `classification_rationale` |
| Routing flags | `needs_phase_check`, `touches_current_truth`, `touches_target_architecture`, `touches_historical_reconciliation`, `touches_verification_matrix`, `touches_snapshot_contract`, `possible_blocking_conditions` |

### Claim Scope Values

| Value | Meaning |
|---|---|
| `current-state` | Claim concerns something the v1 canonical set describes as existing, operational, or currently true (including currently absent/incomplete items) |
| `target-state` | Claim concerns future architecture, Phase B/C/D work, or design intent not yet implemented |
| `historical` | Claim concerns preserved implementation history, superseded examples, or older wording |
| `unverified` | Claim is not sufficiently supported by current materials |

### Evidence Class Values

| Value | Meaning |
|---|---|
| `verified_in_current_documentation_set` | Strong stable cross-doc support in Tier 1 |
| `documented_current_state_claim` | Current docs describe it, but depends on project-owned evidence |
| `planned_target_architecture` | Mapped to `target-state` claims |
| `cannot_verify_from_current_materials` | `historical` or unsupported claims |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `load-context` (constitution) | Required predecessor |

| Depended On By | All other skills consume `request_classification` |
|---|---|

---

## Skill 2 — `canonical-terminology-map`

### Overview

| Field | Value |
|---|---|
| **Name** | `canonical-terminology-map` |
| **Role** | normalization_method |
| **Type** | Normalization |
| **Category** | Semantic / Documentary Governance |
| **Workflow Step** | `normalize-terminology` |
| **Layer** | A — Semantic / Normalization |
| **Execution Priority** | 2 |
| **SKILL.md Path** | `.claude/skills/canonical-terminology-map/SKILL.md` |

### Description

Enforces consistent use of project-defined canonical terms across all documentation, governance outputs, implementation-facing descriptions, and runtime-facing claims. Detects variant drift, synonym substitution, casing drift, label drift, and governance-sensitive term conflicts. Produces a structured normalization map consumed by downstream interpretation, consistency, and verification steps. Terminology consistency is governance-relevant here — not cosmetic — because term meaning directly affects claim interpretation, evidence classification, boundary enforcement, and phase/readiness gating.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Terminology consistency is governance-relevant, not cosmetic. Using a weaker synonym for a canonical term weakens the governance model. |
| 2 | One canonical term per governed concept. Where the project has established a canonical term, it must be preferred in all contexts. |
| 3 | Preserve the strongest canonical form (e.g., `NO_TRADE` over `no-trade`; `Snapshot Truth` over `snapshot state`). |
| 4 | Do not invent new canonical terms. Unrecognised terms must be flagged, not silently adopted. |
| 5 | If `request_classification` is absent, infer from request text with heightened caution and set `inference_used: true`. |
| 6 | If canonical docs are absent, rely on the canonical term table encoded in the skill and flag that cross-document verification was not performed. |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** (canonical current-state) | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (canonical record of what is actually implemented and realized; primary source for implementation-state claims), `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `README_v1.md` |
| **Tier 2** (verification / governance artifacts) | `verification_ledger.md`, `system-orchestration.yaml` |
| **Tier 3** (canonical within declared collaborator-workflow role) | `README_LAYER2.md` |
| **Constitution** | `CLAUDE.md` (terminological authority) |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | When available |
| `doc_update_plan` | `change-impact-audit` | When available |
| `active_governance_context` | Constitution / `CLAUDE.md` | When available |
| Changed documentation files | Direct doc inspection | When available |
| Canonical docs | Full canonical set | When available |

### Outputs

| Output | Description |
|---|---|
| `normalized_terminology_map` | Per-term verdict: observed term → canonical term, severity classification, governance impact note |

### Terminology Issue Severity Levels

| Severity | Meaning |
|---|---|
| `acceptable_variant` | Variant is explicitly listed as acceptable with no ambiguity risk |
| `discouraged_variant` | Variant is non-canonical but interpretable; should be corrected |
| `ambiguity` | Term is ambiguous in context; requires clarification |
| `governance_sensitive_conflict` | Term usage changes how a claim would be interpreted by downstream governance |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor (`request_classification` consumed) |

| Feeds Into | Why |
|---|---|
| `role-matched-citation-check` | Normalized terms feed interpretation routing |
| `change-impact-audit` | Provides terminology normalization context |
| `verification-matrix-update-method` | Supporting input |
| `verification-ledger-update` | Supporting input |
| Cross-doc consistency subagents | Terminology audit support |

---

## Skill 3 — `role-matched-citation-check`

### Overview

| Field | Value |
|---|---|
| **Name** | `role-matched-citation-check` |
| **Role** | interpretation_method |
| **Type** | Source Validation / Interpretation |
| **Category** | Semantic / Documentary Governance |
| **Workflow Step** | `route-claims-by-role` |
| **Layer** | A — Semantic / Normalization |
| **Execution Priority** | 3 |
| **SKILL.md Path** | `.claude/skills/role-matched-citation-check/SKILL.md` |

### Description

Verifies that each claim is supported by the canonical document whose declared role best matches the claim type. Detects role-mismatched citations, unresolved source conflicts, and `README_LAYER2.md` override attempts. Implements the `interpretation_policy.claim_routing` table from the orchestration manifest. Strong claims that lack a role-correct citation are flagged; conflicts are surfaced without invented reconciliation. Produces `role_citation_verdict` consumed by all downstream gating steps.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Canonical documents are authoritative by role — not interchangeable by convenience. |
| 2 | `README_LAYER2.md` is canonical in its declared collaborator-workflow role only. It must not override role-specific documents on implementation state, architecture, or limitations. |
| 3 | Strong claims without role-correct citation are non-compliant. |
| 4 | Unresolved source conflicts must be cited explicitly; no invented reconciliation is permitted. |
| 5 | On conflict, apply: identify claim type → choose role-matched document → cite conflict → treat unresolved contradiction as documentation inconsistency. |

### Claim Routing Table (from `interpretation_policy`)

| Claim Type | Required Canonical Source |
|---|---|
| Architecture / boundary | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` |
| Implementation state | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| Limitations / approximations | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` |
| Collaborator workflow / Layer-2 navigation | `README_LAYER2.md` |
| Documentation consistency | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` |
| Technical constraints / engineering rules | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` |
| Top-level orientation | `README_v1.md` |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** (role-matched primary) | Document matching the claim type per routing table above |
| **Tier 2** (supporting) | Remaining canonical v1 set |
| **Tier 3** (historical only) | `README_LAYER2.md` (outside its declared role) |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `normalized_terminology_map` | `canonical-terminology-map` | Yes |
| `active_governance_context` | Constitution / `CLAUDE.md` | When available |
| Proposed or cited source documents | Upstream request or prior context | When available |
| Canonical doc set | All seven canonical documents | When available |

### Outputs

| Output | Description |
|---|---|
| `role_citation_verdict` | Per-claim: role fit assessment, citation compliance, conflict flags, `README_LAYER2` override detection |

### Blocking Conditions Raised

| Blocking Condition | Trigger |
|---|---|
| `canonical_conflict_unresolved` | Source conflict detected with no clean role-matched resolution |
| `role_mismatch_for_strong_claim` | Strong claim supported only by a role-mismatched document |
| `readme_layer2_used_as_override` | `README_LAYER2.md` cited as authority outside its declared collaborator-workflow role |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `canonical-terminology-map` | Required predecessor |

| Feeds Into | Why |
|---|---|
| `build-sequence-compliance-check` | Role verdict gates phase alignment |
| All deterministic hooks | `role-matched-doc-guard` consumes this |
| Deep audit (subagents) | `canonical-role-auditor` escalation |
| `change-impact-audit` | Impact scoping |
| `verification-matrix-update-method` | Classification posture |
| `verification-ledger-update` | Evidence sourcing |

### Reinforcing Hook

| Hook | Trigger | Action |
|---|---|---|
| `role-matched-doc-guard` | `SubagentStop` | `warn_or_block` on role-mismatch or `README_LAYER2` override |

---

## Skill 4 — `build-sequence-compliance-check`

### Overview

| Field | Value |
|---|---|
| **Name** | `build-sequence-compliance-check` |
| **Role** | phase_alignment_method |
| **Type** | Phase Gating |
| **Category** | Architecture / Phase / Contract Governance |
| **Workflow Step** | `phase-check` |
| **Layer** | B — Architecture / Phase / Contract Gating |
| **Execution Priority** | 4 |
| **SKILL.md Path** | `.claude/skills/build-sequence-compliance-check/SKILL.md` |

### Description

Determines whether the requested change is compatible with the documented build sequence and current stage-gate logic. Detects implicit phase jumping, forbidden scope at the current phase, and live-readiness implications before Phase D. Applies the project phase model (Phase A–D) and emits `phase_alignment_status` for all downstream gating steps. Operates after claim classification and role routing; before snapshot-contract validation, runtime guards, deep audit, and change-impact analysis.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | The build sequence is authoritative for implementation order. |
| 2 | Phase A contract-boundary success allows Layer-3 bootstrap to begin but does not imply full hardening, Layer-3 existence, or live execution readiness. |
| 3 | Phase-compatible expansion is allowed only within the documented scope of the current or next permitted phase. |
| 4 | Implicit phase jumping must be rejected. |
| 5 | Live-readiness implications must be blocked before Phase D. |
| 6 | Requests that exceed currently allowed scope must be flagged even if the design is valid long-term. |
| 7 | Documentation changes that imply a later phase is already reached are subject to the same phase gating as code changes. |
| 8 | Fail closed on ambiguous phase promotion. |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** (authoritative build-order) | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `system-orchestration.yaml`, `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (canonical record of what is actually implemented and realized; primary source for implementation-state claims) |
| **Tier 2** (verification / status support) | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` |
| **Tier 3** (canonical within declared collaborator-workflow role) | `README_LAYER2.md` |

### Phase Model

| Phase | Status | Allowed Scope |
|---|---|---|
| **Phase A** — Layer-2 closure | Complete at contract boundary | Layer-3 bootstrap start permitted |
| **Phase B** — Layer-3 bootstrap | Allowed, not completed | Snapshot consumer, DecisionPacket skeleton, `NO_TRADE` default, state/guard taxonomy stubs, 2–3 deterministic calculations |
| **Phase C** — Layer-3 structured buildout | Future | Feature Builder, Index Suite, Regime Gate, Supervisor Engine, full DecisionPacket emission, Live Market State adapters, Event Risk Stream integration |
| **Phase D** — Live execution gate | Blocked | Only after: paper validation, calibration, frozen schema, operational readiness, kill switch tested |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `role_citation_verdict` | `role-matched-citation-check` | Yes |
| `current_phase` | Inferred from canonical docs or provided | Yes |
| `stage_gates` | Orchestration manifest | Yes |

### Outputs

| Output | Description |
|---|---|
| `phase_alignment_status` | `allowed`, `alignment_status`, `gate_reference`, `blocking_reason_if_any`, per-claim phase assessment, summary flags |

### Alignment Status Values

| Value | Meaning |
|---|---|
| `within_current_phase` | Request stays within the documented current phase |
| `within_next_allowed_phase` | Request targets the immediately next permitted phase |
| `beyond_allowed_phase` | Request exceeds currently allowed scope |
| `ambiguous_requires_block` | Cannot safely determine phase alignment; block required |
| `forbidden_live_readiness` | Request implies live execution capability before Phase D |

### Blocking Conditions Raised

| Blocking Condition | Trigger |
|---|---|
| `unsupported_current_state_claim` | Phase C/D work presented as current-state or implied as already reached |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `role-matched-citation-check` | Required predecessor |

| Feeds Into | Why |
|---|---|
| `snapshot-contract-check` | Phase status informs contract scope |
| `stage-gate-enforcement` | Primary phase gate input |
| `change-impact-audit` | Phase assessment defines impact scope |
| `verification-matrix-update-method` | Matrix classification requires phase context |
| `verification-ledger-update` | Ledger evidence level depends on phase |

---

## Skill 5 — `snapshot-contract-check`

### Overview

| Field | Value |
|---|---|
| **Name** | `snapshot-contract-check` |
| **Role** | contract_validation_method |
| **Type** | Contract Validation |
| **Category** | Architecture / Phase / Contract Governance |
| **Workflow Step** | `snapshot-contract-check` |
| **Layer** | B — Architecture / Phase / Contract Gating |
| **Execution Priority** | 5 |
| **SKILL.md Path** | `.claude/skills/snapshot-contract-check/SKILL.md` |

### Description

Validates whether a requested implementation, documentation change, architecture statement, or agent action preserves the hard invariant that Layer-3 and all downstream logic consume only governed published snapshots — never raw Layer-2 `observations`. Applies six non-negotiable contract invariants (SCC-1 through SCC-6) and seven forbidden patterns (FP-1 through FP-7). Emits `contract_compliance_verdict` consumed by `snapshot-boundary-guard`, deep audit routing, and change-impact analysis. Distinct from `snapshot-boundary-check`: this skill validates contract design; `snapshot-boundary-check` validates runtime code behavior.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | The snapshot-only downstream read rule is a current-state invariant — not a future goal. It applies now. |
| 2 | `observations` is a Layer-2-internal table. No Layer-3 or downstream component may query it under any circumstance. |
| 3 | Valid interfaces: (1) `SELECT * FROM snapshots WHERE snapshot_id = ? JOIN snapshot_values` (DB interface); (2) read `latest_snapshot.json` (file interface). |
| 4 | `snapshot_id` is the primary contract anchor. Every DecisionPacket must carry `snapshot_id` and `snapshot_clock_ts`. |
| 5 | Live Market State and Event Risk Stream are allowed governed inputs but may never touch Layer-2 storage or rewrite Snapshot Truth. |
| 6 | Handoff gate satisfaction = Layer-3 bootstrap may begin. It does NOT relax any snapshot contract rule. |
| 7 | Documentation changes that imply forbidden access patterns are blocked on the same basis as code changes. |
| 8 | In `strict` mode (default): `ambiguous` claims are treated as `blocked`. |

### Contract Invariants

| ID | Invariant | Source |
|---|---|---|
| SCC-1 | Layer-3 consumes snapshots, never raw `observations` | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` Invariant 5 |
| SCC-2 | Every DecisionPacket must carry `snapshot_id` and `snapshot_clock_ts` | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` Invariant 6 |
| SCC-3 | Live Market State and Event Risk Stream may not touch Layer-2 storage | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` §2; `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` §7 |
| SCC-4 | Snapshot Truth is immutable; Layer-3 may not rewrite it | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` §7 |
| SCC-5 | Event Risk Stream is penalty/override/escalation only; may not generate direction by itself | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` §7 |
| SCC-6 | Handoff gate satisfaction does not relax any contract rule | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` §5 |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `README_v1.md` |
| **Tier 2** | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| **Tier 3** (supporting contract detail only) | `README_LAYER2.md` — valid interface summary; not primary authority |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `phase_alignment_status` | `build-sequence-compliance-check` | Yes |
| Canonical docs (Tier 1–2) | Canonical document set | When available |

### Outputs

| Output | Description |
|---|---|
| `contract_compliance_verdict` | `allowed`, `contract_status`, `valid_interface`, `forbidden_access_detected`, `snapshot_anchor_required`, per-claim assessment with invariant/pattern references, summary risk flags |

### Blocking Conditions Raised

| Blocking Condition | Trigger |
|---|---|
| `snapshot_boundary_violation` | Any claim violates SCC-1 through SCC-4 |
| `raw_observations_used_in_layer3` | Claim implies direct `observations` access by Layer-3 |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `build-sequence-compliance-check` | Required predecessor |

| Feeds Into | Why |
|---|---|
| `stage-gate-enforcement` | Contract compliance is a gate input |
| `snapshot-boundary-guard` hook | Hook reads `contract_compliance_verdict` |
| `snapshot-boundary-check` | Provides design-level contract context for runtime validation |
| `change-impact-audit` | Contract violations drive impact scope |
| `deep-audit` | `snapshot-boundary-auditor` escalation trigger |

---

## Skill 6 — `snapshot-boundary-check`

### Overview

| Field | Value |
|---|---|
| **Name** | `snapshot-boundary-check` |
| **Role** | runtime_integrity_method |
| **Type** | Runtime Integrity |
| **Category** | Runtime / Schema / Boundary Integrity |
| **Workflow Step** | `runtime-boundary-check` |
| **Layer** | C — Runtime / Schema / Boundary Integrity |
| **Execution Priority** | 6 |
| **SKILL.md Path** | `.claude/skills/snapshot-boundary-check/SKILL.md` |

### Description

Validates runtime and code boundary integrity for the Layer-2 → Layer-3 handoff. Where `snapshot-contract-check` validates contract design, this skill validates whether actual runtime code, implementation changes, and runtime artifacts preserve that boundary. Checks five boundary dimensions: raw observation access in code, snapshot interface discipline, `latest_snapshot.json` misuse, Snapshot Truth ownership, and Layer-2 storage-touch discipline. Feeds `snapshot-boundary-guard` hook and `snapshot-boundary-auditor` subagent.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | This skill validates runtime behavior, not contract design. It is not a substitute for `snapshot-contract-check`. |
| 2 | Does not execute enforcement — that is `snapshot-boundary-guard`'s role. |
| 3 | Does not update canonical documentation artifacts. |
| 4 | If `request_classification` is absent, infer from request text with heightened caution and set `inference_used: true`. |
| 5 | Do not approve boundary compliance without code or runtime evidence. |
| 6 | Fail closed on ambiguous access patterns. |

### Five Boundary Dimensions

| Dimension | What Is Checked |
|---|---|
| Raw observation access | No Layer-3 or downstream component queries `observations` table directly |
| Snapshot interface discipline | All reads go through `snapshots`/`snapshot_values` join or `latest_snapshot.json` |
| `latest_snapshot.json` discipline | File not treated as mutable scratch, unmanaged cache, or informal override |
| Snapshot Truth ownership | No Layer-3 action rewrites or supersedes Layer-2 Snapshot Truth |
| Layer-2 storage-touch discipline | No Live Market State or Event Risk Stream writes to Layer-2 storage |

### Canonical Source Priority

| Tier | Documents / Context |
|---|---|
| **Tier 1** | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` |
| **Tier 2** | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `README_v1.md` |
| **Code / Runtime** | `layer2/adapters/*`, `layer2/db.py`, `latest_snapshot.json`, `layer2_truth.db` |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `contract_compliance_verdict` | `snapshot-contract-check` | Yes |
| `stage_gate_report` | `stage-gate-enforcement` | Yes |
| Changed files / code paths | Direct code inspection | When available |
| Runtime artifacts | `latest_snapshot.json`, `layer2_truth.db` | When available |
| Guard / audit outputs | `snapshot-boundary-guard`, `snapshot-boundary-auditor` | When available |
| Canonical docs | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | When available |

### Outputs

| Output | Description |
|---|---|
| `runtime_boundary_verdict` | Per-dimension compliance verdict with code-level evidence; escalation recommendation for `snapshot-boundary-auditor` |

### Blocking Conditions Raised

| Blocking Condition | Trigger |
|---|---|
| `snapshot_boundary_violation` | Any runtime code or artifact violates the boundary dimensions |
| `raw_observations_used_in_layer3` | Code-level evidence of direct `observations` access downstream |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `snapshot-contract-check` | Required predecessor (design-level contract context) |
| `stage-gate-enforcement` | Required predecessor |

| Feeds Into | Why |
|---|---|
| `snapshot-boundary-guard` hook | Enforcement hook reads this verdict |
| `snapshot-boundary-auditor` subagent | Escalation trigger |
| `runtime-guards-summary` | Consolidated guard report |
| `change-impact-audit` | Boundary violations affect impact scope |

### Reinforcing Hook

| Hook | Trigger | Checks | Action |
|---|---|---|---|
| `snapshot-boundary-guard` | `PostToolUse` (Edit\|Write) | No downstream `observations` access; no `latest_snapshot.json` misuse | `block_on_match` |

---

## Skill 7 — `adapter-schema-review`

### Overview

| Field | Value |
|---|---|
| **Name** | `adapter-schema-review` |
| **Role** | schema_validation_method |
| **Type** | Schema Validation |
| **Category** | Runtime / Schema / Boundary Integrity |
| **Workflow Step** | `adapter-schema-check` |
| **Layer** | C — Runtime / Schema / Boundary Integrity |
| **Execution Priority** | 7 |
| **SKILL.md Path** | `.claude/skills/adapter-schema-review/SKILL.md` |

### Description

Validates registry-driven adapter compliance and schema discipline at the Layer-2 ingestion/runtime boundary. Evaluates adapter code, configuration, and documentation claims against four compliance dimensions: registry compliance, hardcoding detection, schema consistency, and implementation boundary fit. `series_registry.json` is the single source of truth for all series definitions — adapters must not hardcode series logic. Feeds `adapter-schema-guard` hook and `adapter-schema-guardian` subagent.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Does not execute enforcement — that is `adapter-schema-guard`'s role. |
| 2 | Does not update canonical documentation artifacts. |
| 3 | The physical path `truth_layer/` and manifest convention `layer2/` refer to the same artifacts. Evaluate whichever is present. |
| 4 | If `request_classification` is absent, infer from request text with heightened caution and set `inference_used: true`. |
| 5 | Do not approve compliance without code/config evidence. |

### Four Compliance Dimensions

| Dimension | What Is Checked |
|---|---|
| Registry compliance | All series identifiers and source mappings come from `series_registry.json`, not embedded in code |
| Hardcoding detection | No hardcoded series definitions, names, or adapter selection logic in adapter code |
| Schema consistency | Adapter outputs are consistent with the documented Layer-2 DB schema and truth model |
| Implementation boundary fit | Adapters do not couple to Layer-3 logic or bypass the Layer-2 publication boundary |

### Canonical Source Priority

| Tier | Documents / Context |
|---|---|
| **Tier 1** | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` |
| **Tier 2** | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| **Code / Config** | `layer2/config/series_registry.json`, `layer2/adapters/*`, `layer2/db.py`, `layer2/alignment.py` |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `runtime_boundary_verdict` | `snapshot-boundary-check` | Yes |
| `active_governance_context` | Constitution / `CLAUDE.md` | When available |
| Adapter source code | `layer2/adapters/*` | When available |
| Registry config | `layer2/config/series_registry.json` | When available |
| DB schema module | `layer2/db.py` | When available |
| Alignment module | `layer2/alignment.py` | When available |
| Guard / audit outputs | `adapter-schema-guard`, `adapter-schema-guardian` | When available |

### Outputs

| Output | Description |
|---|---|
| `adapter_schema_verdict` | Per-dimension compliance verdict; escalation recommendation for `adapter-schema-guardian` |

### Blocking Conditions Raised

| Blocking Condition | Trigger |
|---|---|
| `registry_violation` | Adapter bypasses `series_registry.json` or hardcodes series logic |
| `schema_drift_detected` | Adapter output schema diverges from documented Layer-2 DB schema |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `snapshot-boundary-check` | Required predecessor (runtime boundary context) |

| Feeds Into | Why |
|---|---|
| `adapter-schema-guard` hook | Enforcement hook reads this verdict |
| `adapter-schema-guardian` subagent | Escalation trigger |
| `runtime-guards-summary` | Consolidated guard report |
| `change-impact-audit` | Schema violations affect impact scope |

### Reinforcing Hook

| Hook | Trigger | Checks | Action |
|---|---|---|---|
| `adapter-schema-guard` | `PostToolUse` (Edit\|Write) | Registry-driven usage enforced; no hardcoded series definitions | `warn_or_block` |

---

## Skill 8 — `change-impact-audit`

### Overview

| Field | Value |
|---|---|
| **Name** | `change-impact-audit` |
| **Role** | impact_assessment_method |
| **Type** | Impact Assessment |
| **Category** | Audit / Impact |
| **Workflow Step** | `change-impact-audit` |
| **Layer** | D — Audit / Impact |
| **Execution Priority** | 8 (after `deep-audit` subagent step) |
| **SKILL.md Path** | `.claude/skills/change-impact-audit/SKILL.md` |

### Description

Converts the outputs of all earlier governance steps into a machine-readable `change_impact_report` and `doc_update_plan`. Identifies which canonical artifacts are affected by the change, categorizes impact types, flags residual governance risks, and determines whether follow-up (mandatory, advisory, or not required) is needed. Does not re-run phase gating, re-classify claims, or re-check the snapshot contract — it consumes those verdicts as authoritative inputs and prepares the ground for verification matrix updates, ledger updates, and pre-PR readiness.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Assesses impact only — does not re-run phase gating, re-classify claims, or re-check contracts. |
| 2 | Upstream verdicts are consumed as authoritative. Blocked claims remain blocked. |
| 3 | Preserve the current-vs-target distinction. A target-state change must not be described as a current-state implementation change. |
| 4 | Documentation updates do not prove runtime behavior. Doc-only changes may require matrix review but must not automatically elevate evidence status to `proven`. |
| 5 | Runtime observations have higher evidentiary weight than documentation alone. |
| 6 | If prior guards blocked a change, the blocked attempt is itself a governance event and must appear in the impact summary. |
| 7 | Fail closed on ambiguity: default to `mixed` impact type and flag it. |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** | `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md`, `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| **Tier 2** | `README_LAYER2.md` (collaborator-workflow scope only) |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `phase_alignment_status` | `build-sequence-compliance-check` | Yes |
| `guard_report` | Hook outputs (snapshot-boundary-guard, adapter-schema-guard, etc.) | When available |
| `deep_audit_summary` | Subagent audit outputs | When available |
| `role_citation_verdict` | `role-matched-citation-check` | When available |
| `stage_gate_report` | `stage-gate-enforcement` | When available |

### Outputs

| Output | Description |
|---|---|
| `change_impact_report` | Categorized impact summary: affected artifacts, impact types, residual governance risks |
| `doc_update_plan` | Structured list of canonical documents that require review or update (per `CLAUDE.md` §11) |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `build-sequence-compliance-check` | Required predecessor |
| `snapshot-boundary-check` + `adapter-schema-review` | Required predecessors (via guard_report) |
| `deep-audit` subagent step | Required predecessor |

| Feeds Into | Why |
|---|---|
| `doc-code-sync-rules` | Sync check uses impact report and doc_update_plan |
| `verification-matrix-update-method` | Impact report defines what the matrix needs to reflect |
| `verification-ledger-update` | Impact report informs which claims need ledger entries |
| `runtime-artifact-hygiene-check` | Hygiene check uses impact summary |

---

## Skill 9 — `doc-code-sync-rules`

### Overview

| Field | Value |
|---|---|
| **Name** | `doc-code-sync-rules` |
| **Role** | consistency_method |
| **Type** | Consistency Validation |
| **Category** | Audit / Impact |
| **Workflow Step** | `doc-code-sync-check` |
| **Layer** | D — Audit / Impact |
| **Execution Priority** | 9 |
| **SKILL.md Path** | `.claude/skills/doc-code-sync-rules/SKILL.md` |

### Description

Validates whether documentation claims remain aligned with actual code, runtime behavior, and required project contracts. Detects drift in both directions: code/runtime changed without corresponding documentation updates, and documentation changes not backed by code or runtime evidence. Produces `doc_code_sync_status` for the `doc-code-sync-guard` hook, `doc-code-sync-auditor` subagent, and the pre-PR governance gate.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Does not execute enforcement — that is `doc-code-sync-guard`'s role. |
| 2 | Does not update canonical documentation artifacts. |
| 3 | Validates both directions of drift: docs behind code, and docs ahead of code/runtime. |
| 4 | Documentation changes that overstate code/runtime evidence must be flagged. |
| 5 | If `request_classification` is absent, infer from request text with heightened caution. |
| 6 | Do not approve `in_sync` without confirming relevant artifacts were checked. |

### Five Sync Dimensions

| Dimension | What Is Checked |
|---|---|
| Contract-change sync | Docs updated when contract changed (CLAUDE.md §11 obligation) |
| Snapshot field consistency | Snapshot fields documented consistently with `SYSTEM_TECHNICAL_HANDBOOK_v1.md` |
| Implementation claim alignment | Implementation claims in docs match `SYSTEM_IMPLEMENTATION_RECORD_v1.md` |
| Runtime truth alignment | Docs do not claim runtime behavior unsupported by code/runtime evidence |
| Missing update detection | Identifies which canonical docs require update but have not been touched |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** | Full canonical v1 set (all seven documents) |
| **Code / Runtime** | `layer2/adapters/*`, `layer2/db.py`, `layer2/alignment.py`, `latest_snapshot.json`, `layer2_truth.db` |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | Yes |
| `doc_update_plan` | `change-impact-audit` | Yes |
| `verification_matrix_delta` | `verification-matrix-update-method` | When available |
| `verification_ledger_delta` | `verification-ledger-update` | When available |
| `active_governance_context` | Constitution / `CLAUDE.md` | When available |
| Changed documentation files | Direct doc inspection | When available |
| Changed code / runtime artifacts | Direct code or runtime inspection | When available |
| Canonical docs | Full canonical set | When available |

### Outputs

| Output | Description |
|---|---|
| `doc_code_sync_status` | Per-dimension sync verdict; list of affected canonical docs; escalation recommendation for `doc-code-sync-auditor` |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `build-sequence-compliance-check` | Required predecessor |
| `change-impact-audit` | Required predecessor |

| Feeds Into | Why |
|---|---|
| `doc-code-sync-guard` hook | Guard reads sync verdict |
| `doc-code-sync-auditor` subagent | Escalation trigger |
| `verification-matrix-update-method` | Sync status informs matrix posture |
| `verification-ledger-update` | Sync status informs claim evidence tracking |
| `pre-pr-governance-readiness` | Final gate requires sync clearance |

### Reinforcing Hook

| Hook | Trigger | Checks | Action |
|---|---|---|---|
| `doc-code-sync-guard` | `SubagentStop` | Docs updated if contract changed; snapshot fields consistent; implementation claims aligned | `warn` → escalate to `doc-code-sync-auditor` |

---

## Skill 10 — `verification-matrix-update-method`

### Overview

| Field | Value |
|---|---|
| **Name** | `verification-matrix-update-method` |
| **Role** | doc_classification_method |
| **Type** | Verification Classification |
| **Category** | Verification / Hygiene / Release Readiness |
| **Workflow Step** | `update-verification-matrix` |
| **Layer** | E — Verification / Hygiene / Release Readiness |
| **Execution Priority** | 10 |
| **SKILL.md Path** | `.claude/skills/verification-matrix-update-method/SKILL.md` |

### Description

Determines whether `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` needs to be updated, reviewed, or left unchanged based on prior governance step outputs. Produces a structured `verification_matrix_delta`. Matrix-scoped only: updates classification posture in the matrix. Does not update the verification ledger, does not re-classify claims, does not claim runtime proof, and does not re-run earlier governance steps. The matrix and ledger are distinct artifacts with distinct responsibilities.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Matrix-scoped only. Does not update the ledger, alter evidence status, or execute runtime claims. |
| 2 | Upstream verdicts are consumed as authoritative. Does not re-litigate `doc-truth-classification` or `build-sequence-compliance-check` outcomes. |
| 3 | Documentation updates do not prove runtime behavior. A doc-only change may require a matrix note but must not upgrade runtime evidence status. |
| 4 | Runtime/code evidence can influence matrix classification levels, but claim→evidence→status tracking belongs to `verification-ledger-update`. |
| 5 | Unresolved doc-to-doc contradictions must be surfaced, not silently resolved. |
| 6 | Be conservative: prefer `review_only` over `update`, prefer contradiction note over reclassification, prefer no status upgrade over overclaiming. |
| 7 | Do not remove matrix entries speculatively. Only flag `remove_stale_entry` when a clear traceable governance reason exists. |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** | `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`, `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` (baseline), `SYSTEM_IMPLEMENTATION_RECORD_v1.md` (canonical record of what is actually implemented and realized; primary source for implementation-state claims) |
| **Tier 2** | `system-orchestration.yaml` (workflow manifest) |
| **Tier 3** (canonical within declared collaborator-workflow role) | `README_LAYER2.md` |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `phase_alignment_status` | `build-sequence-compliance-check` | Yes |
| `change_impact_summary` | `change-impact-audit` | Yes |
| `doc_update_plan` | `change-impact-audit` | Yes |
| `guard_report` | Hook outputs | When available |
| `deep_audit_summary` | Subagent outputs | When available |

### Outputs

| Output | Description |
|---|---|
| `verification_matrix_delta` | Structured matrix update plan: affected entries, required actions (`update`, `review_only`, `no_change`, `remove_stale_entry`), contradiction notes |

### Matrix Action Types

| Action | Meaning |
|---|---|
| `update` | Matrix entry requires a concrete change based on governance evidence |
| `review_only` | Entry needs human review; cannot be updated deterministically |
| `no_change` | Entry is unaffected by the current change |
| `remove_stale_entry` | Entry is clearly outdated with traceable governance justification |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `build-sequence-compliance-check` | Required predecessor |
| `change-impact-audit` | Required predecessor |
| Guards and deep audit | Inputs when available |

| Feeds Into | Why |
|---|---|
| `verification-ledger-update` | Ledger update consumes `verification_matrix_delta` |
| `pre-pr-governance-readiness` | Matrix delta is a pre-PR gate input |

---

## Skill 11 — `verification-ledger-update`

### Overview

| Field | Value |
|---|---|
| **Name** | `verification-ledger-update` |
| **Role** | evidence_tracking_method |
| **Type** | Evidence Tracking |
| **Category** | Verification / Hygiene / Release Readiness |
| **Workflow Step** | `update-verification-ledger` |
| **Layer** | E — Verification / Hygiene / Release Readiness |
| **Execution Priority** | 11 |
| **SKILL.md Path** | `.claude/skills/verification-ledger-update/SKILL.md` |

### Description

Determines whether `verification_ledger.md` needs to be updated as a result of the current request, accepted change, blocked change, or audited result. Produces a structured `verification_ledger_delta` tracking claim → evidence → status. Ledger-scoped only: updates claim/evidence/status tracking. Does not update the verification matrix, does not re-classify claims, and does not act as a phase gate. The matrix governs classification posture; the ledger governs claim evidence tracking. These are distinct concerns. Any wiring that treats this skill as equivalent to `verification-matrix-update-method` must be flagged as stale orchestration wiring.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Ledger-scoped only. Does not alter matrix classification, execute runtime claims, or re-run prior governance steps. |
| 2 | Upstream verdicts are consumed as authoritative. Blocked claims stay blocked; `unverified` claims are not upgraded here. |
| 3 | Evidence type determines maximum achievable status: doc-only cannot produce `proven`; runtime observation can when aligned with code and claim semantics. |
| 4 | The ledger tracks evidence, not wording. |
| 5 | Preserve the current-vs-target distinction. Target-state claims must not receive `proven` or `supported` without current-state evidence. |
| 6 | If a contradiction exists between a claim and stronger evidence, mark `contradicted` — do not silently normalise. |
| 7 | Be conservative: prefer `supported` over `proven`, prefer `unverified` over overclaiming. |
| 8 | Stale orchestration wiring (treating this skill as `verification-matrix-update-method`) must be surfaced in the `notes` field, not followed. |

### Evidence Type Hierarchy

| Evidence Type | Maximum Achievable Status |
|---|---|
| `runtime` observation | `proven` (when aligned with code and claim) |
| `code` alignment | `supported` to `proven` (with runtime corroboration) |
| `doc` only | `supported` at most; never `proven` |

### Claim Status Values

| Status | Meaning |
|---|---|
| `proven` | Claim is supported by runtime evidence aligned with code and documentation |
| `supported` | Claim is documented and code-aligned, but runtime proof is absent or incomplete |
| `unverified` | Claim lacks sufficient evidence to be classified as `supported` or `proven` |
| `contradicted` | Higher-authority evidence conflicts with the claim |

### Canonical Source Priority

| Tier | Documents |
|---|---|
| **Tier 1** | Full canonical v1 set |
| **Ledger artifact** | `verification_ledger.md` (current state is the baseline) |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `phase_alignment_status` | `build-sequence-compliance-check` | Yes |
| `change_impact_summary` | `change-impact-audit` | Yes |
| `doc_update_plan` | `change-impact-audit` | Yes |
| `verification_matrix_delta` | `verification-matrix-update-method` | Yes |
| `guard_report` | Hook outputs | When available |
| `deep_audit_summary` | Subagent outputs | When available |
| `active_governance_context` | Constitution / `CLAUDE.md` | When available |
| `verification_ledger.md` | Existing ledger state | When present |

### Outputs

| Output | Description |
|---|---|
| `verification_ledger_delta` | Structured ledger update: per-claim evidence type, status, preferred canonical source, unresolved conflicts, notes |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `role-matched-citation-check` | Required predecessor |
| `build-sequence-compliance-check` | Required predecessor |
| `change-impact-audit` | Required predecessor |
| `verification-matrix-update-method` | Required predecessor |
| Guards and deep audit | Inputs when available |

| Feeds Into | Why |
|---|---|
| `runtime-artifact-hygiene-check` | Hygiene check uses `verification_ledger_delta` |
| `pre-pr-governance-readiness` | Ledger delta is a pre-PR gate requirement |

---

## Skill 12 — `runtime-artifact-hygiene-check`

### Overview

| Field | Value |
|---|---|
| **Name** | `runtime-artifact-hygiene-check` |
| **Role** | workspace_integrity_method |
| **Type** | Workspace Integrity |
| **Category** | Verification / Hygiene / Release Readiness |
| **Workflow Step** | `runtime-artifact-hygiene-check` |
| **Layer** | E — Verification / Hygiene / Release Readiness |
| **Execution Priority** | 12 (final skill before pre-PR gate) |
| **SKILL.md Path** | `.claude/skills/runtime-artifact-hygiene-check/SKILL.md` |

### Description

Validates workspace and runtime artifact hygiene. Detects artifacts that are stale, commit-sensitive, evidence-confusing, or outside the governed runtime model. The project's dual-layer governance model depends on runtime artifacts being explicitly classified: an ungoverned `latest_snapshot.json` could be the most current evidence of a successful Layer-2 run, a stale test artifact, or a developer scratch file — and the distinction has governance consequences. Does not execute cleanup — that is the role of downstream guards and pre-PR gate checks. Produces `artifact_hygiene_verdict` for the pre-PR governance gate.

### Governing Assumptions

| # | Assumption |
|---|---|
| 1 | Does not execute cleanup or enforcement actions. Produces a verdict consumed by pre-PR gate and audit. |
| 2 | Governed runtime artifacts are `latest_snapshot.json` and `layer2_truth.db`. Their presence and state are always in scope. |
| 3 | If visible workspace artifacts are absent, evaluate from request description alone and set affected items to `review_only`. |
| 4 | Do not emit `clean` without artifact-level confirmation. |
| 5 | Flag `latest_snapshot.json` and `layer2_truth.db` for review whenever referenced or implicated by the request. |
| 6 | If `request_classification` is absent, infer artifact scope from request text with heightened caution. |

### Five Hygiene Dimensions

| Dimension | What Is Checked |
|---|---|
| Artifact class | Is the artifact expected/governed, unexpected, or unknown? |
| Commit sensitivity | Would committing this artifact introduce risk (credentials, stale state, unreviewed data)? |
| Evidence sensitivity | Would this artifact be misinterpreted as runtime proof when it is not? |
| Staleness / drift | Is the artifact stale, outdated, or from a prior test run that no longer reflects current state? |
| Runtime model consistency | Does the artifact reflect the governed runtime model or deviate from it? |

### Governed Runtime Artifacts

| Artifact | Role | Governance Status |
|---|---|---|
| `latest_snapshot.json` | Layer-2 publication artifact; Layer-3 valid file interface | Must be classified: governed publication vs stale scratch file |
| `layer2_truth.db` | Layer-2 persistent storage | Must be classified: active governed DB vs stale test artifact |

### Canonical Source Priority

| Tier | Documents / Context |
|---|---|
| **Tier 1** | `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` |
| **Tier 2** | Full canonical v1 set |
| **Workspace** | Visible runtime artifacts, changed files list |

### Inputs

| Input | Source | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | When available |
| `verification_ledger_delta` | `verification-ledger-update` | When available |
| `active_governance_context` | Constitution / `CLAUDE.md` | When available |
| Visible runtime / workspace artifacts | Direct workspace inspection | When available |
| Changed files list | PR diff / request context | When available |
| Canonical docs | Full canonical set | When available |

### Outputs

| Output | Description |
|---|---|
| `artifact_hygiene_verdict` | Per-artifact classification across five dimensions; cleanup or review requirements; `clean` / `requires_action` / `review_only` overall verdict |

### Hygiene Verdict Values

| Value | Meaning |
|---|---|
| `clean` | All in-scope artifacts are classified, governed, and commit-safe |
| `requires_action` | One or more artifacts require cleanup or explicit governance declaration before PR |
| `review_only` | Artifacts could not be fully verified from available context; human review required |

### Skill Dependencies

| Depends On | Type |
|---|---|
| `doc-truth-classification` | Required predecessor |
| `change-impact-audit` | Required predecessor |
| `verification-ledger-update` | Required predecessor |

| Feeds Into | Why |
|---|---|
| `pre-pr-governance-readiness` | Hygiene verdict is a required pre-PR gate input |

---

## Cross-Skill Hook Alignment

| Hook | Reinforcing Skill | Reinforcing Phase | Action |
|---|---|---|---|
| `role-matched-doc-guard` | `role-matched-citation-check` | `route-claims-by-role` (Layer A) | `warn_or_block` on role mismatch or `README_LAYER2` override |
| `live-readiness-claim-blocker` | `build-sequence-compliance-check` + stage gates | `stage-gate-enforcement` (Layer B) | `block_on_match` for Phase D claims before Phase D |
| `snapshot-boundary-guard` | `snapshot-boundary-check` | `runtime-boundary-check` (Layer C) | `block_on_match` on raw observation access |
| `adapter-schema-guard` | `adapter-schema-review` | `adapter-schema-check` (Layer C) | `warn_or_block` on registry violations or hardcoding |
| `doc-code-sync-guard` | `doc-code-sync-rules` | `doc-code-sync-check` (Layer D) | `warn` → escalate to `doc-code-sync-auditor` |
| `pre-pr-governance-gate` | All Layer E skills | `pre-pr-governance-readiness` (Layer E) | `block_on_fail` if any blocking condition unresolved |

---

## Cross-Skill Subagent Alignment

| Subagent | Triggered By Skill | Escalation Condition |
|---|---|---|
| `canonical-role-auditor` | `role-matched-citation-check` | `canonical_conflict_unresolved` or `role_mismatch_for_strong_claim` |
| `implementation-history-reconciler` | `doc-truth-classification` | Non-canonical historical source presented as current truth |
| `architecture-sequence-auditor` | `build-sequence-compliance-check` | Ambiguous or conflicting build-order claims |
| `snapshot-boundary-auditor` | `snapshot-boundary-check` | `snapshot_boundary_violation` |
| `adapter-schema-guardian` | `adapter-schema-review` | `registry_violation` or `schema_drift_detected` |
| `cross-doc-consistency-auditor` | `doc-code-sync-rules` | Doc/doc consistency conflict across canonical documents |
| `doc-code-sync-auditor` | `doc-code-sync-rules` | Doc/runtime mismatch unresolved by `doc-code-sync-rules` |
| `verification-matrix-auditor` | `verification-matrix-update-method` | Matrix classification dispute or matrix inconsistency |

---

## Blocking Conditions Summary

| Blocking Condition | Raised By Skill | Enforced By Hook | Resolved By |
|---|---|---|---|
| `snapshot_boundary_violation` | `snapshot-contract-check`, `snapshot-boundary-check` | `snapshot-boundary-guard` | Code fix + re-run Layer C |
| `raw_observations_used_in_layer3` | `snapshot-contract-check`, `snapshot-boundary-check` | `snapshot-boundary-guard` | Code fix + re-run Layer C |
| `registry_violation` | `adapter-schema-review` | `adapter-schema-guard` | Registry config fix + re-run Layer C |
| `schema_drift_detected` | `adapter-schema-review` | `adapter-schema-guard` | Schema alignment + re-run Layer C |
| `unsupported_current_state_claim` | `build-sequence-compliance-check`, stage gates | `live-readiness-claim-blocker` | Re-scope claim to correct phase |
| `canonical_conflict_unresolved` | `role-matched-citation-check` | `role-matched-doc-guard` | Explicit conflict citation + subagent escalation |
| `role_mismatch_for_strong_claim` | `role-matched-citation-check` | `role-matched-doc-guard` | Correct to role-matched source |
| `readme_layer2_used_as_override` | `role-matched-citation-check` | `role-matched-doc-guard` | Replace with role-correct canonical source |
| `verification_without_evidence` | `verification-ledger-update` | Skill self-enforced | Provide traceable evidence before status upgrade |
| `pr_governance_not_satisfied` | `pre-pr-governance-readiness` | `pre-pr-governance-gate` | Resolve all open conditions in prior layers |
