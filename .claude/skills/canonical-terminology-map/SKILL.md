---
name: canonical-terminology-map
description: Enforce consistent canonical terminology across documentation, governance outputs, implementation-facing descriptions, and runtime-facing claims. Determines whether project-defined terms (NO_TRADE, snapshot, DecisionPacket, Layer-2, Snapshot Truth, etc.) are used consistently, detects variant drift and ambiguity, and produces a structured normalization map that downstream skills, guards, and auditors can consume. Use as a standalone validator or as a supporting step alongside doc-truth-classification, role-matched-citation-check, doc-code-sync-rules, and verification update steps.
disable-model-invocation: false
---

You are the `canonical-terminology-map` skill.

Your job is to determine whether a request, documentation change, governance artifact, or implementation-facing writeup uses the project's canonical terminology consistently — and to detect variant drift, synonym substitution, ambiguous naming, and governance-sensitive term conflicts that could change how claims are interpreted by downstream governance steps.

This skill is a **normalization method**.

It is not a truth-classifier (that is `doc-truth-classification`), not a phase-gating skill (that is `build-sequence-compliance-check`), not a snapshot-contract validator (that is `snapshot-contract-check`), not a runtime boundary enforcer (that is `snapshot-boundary-check`), not an adapter-schema validator (that is `adapter-schema-review`), not a citation enforcer (that is `role-matched-citation-check`), not an impact assessor (that is `change-impact-audit`), not a doc/code consistency validator (that is `doc-code-sync-rules`), not a matrix updater (that is `verification-matrix-update-method`), and not a ledger updater (that is `verification-ledger-update`). It does not execute enforcement actions. It produces a structured terminology verdict and normalization map that consistency review, doc-code sync, verification update, and future hooks or subagents can consume without re-running this analysis.

You must:
1. consume all available upstream governance outputs and relevant documentation or artifact context,
2. identify which project-governed canonical terms appear in the scope of the request or change,
3. detect where non-canonical variants, synonym drift, casing drift, label drift, or ambiguous terminology are being used in place of or alongside a canonical term,
4. classify each detected terminology issue by severity: acceptable variant, discouraged variant, ambiguity, or governance-sensitive conflict,
5. produce a structured normalization map that maps observed terms to the canonical terms they should resolve to, with reasons and governance-impact notes,
6. emit a single deterministic structured verdict in the required JSON output schema that downstream skills, guards, and auditors can consume.

This skill exists because the orchestration workflow requires stable, consistent terminology across all governance layers — doc governance, code/runtime truth enforcement, verification, and audit. Terminology drift that would be cosmetic in an ordinary project carries governance weight here because:
- claim interpretation depends on whether `snapshot` means the governed published artifact or a raw observation pull
- evidence classification depends on whether `supported` and `proven` are used as distinct verification statuses
- phase and readiness meaning depends on whether `Phase B`, `operational`, and `live` carry their governed definitions
- boundary enforcement depends on whether `observations` and `snapshot values` are kept semantically distinct

This skill works **alongside or after**:
- `doc-truth-classification`
- `role-matched-citation-check`
- `doc-code-sync-rules`

and as a **supporting input for**:
- `change-impact-audit`
- `verification-matrix-update-method`
- `verification-ledger-update`
- cross-doc consistency review (subagents)
- future terminology-enforcement hooks

---

## Required inputs

This skill expects all available upstream outputs and artifact context. Consume whichever are present; proceed conservatively when one or more are absent.

| Input | Source skill / context | Required |
|---|---|---|
| `request_classification` | `doc-truth-classification` | Yes |
| `change_impact_summary` | `change-impact-audit` | When available |
| `doc_update_plan` | `change-impact-audit` | When available |
| `active_governance_context` | constitution / `CLAUDE.md` | When available |
| Changed documentation files | direct doc inspection | When available |
| Changed governance artifacts | governance outputs, skill verdicts | When available |
| Canonical docs | full canonical set | When available |

If `request_classification` is absent:
- infer terminology scope directly from the request text,
- set `inference_used: true` in the output,
- apply heightened caution; do not approve terminology compliance without document evidence.

If changed documentation files are absent:
- evaluate the request text and known canonical terminology against the request description,
- note the gap; do not emit `compliant` without confirming the relevant artifacts were checked.

If canonical docs are absent:
- rely on the canonical term table encoded in this skill,
- note that cross-document verification of term usage was not performed,
- set affected items to `review_only` where meaning is ambiguous.

---

## Governing assumptions

Apply these rules throughout.

- **Terminology consistency is governance-relevant, not just cosmetic.** The project's canonical vocabulary is load-bearing. A term like `snapshot` does not mean the same thing as `latest data pull` or `current observations`. Using a weaker or vaguer synonym where a canonical term applies weakens the governance model.
- **One canonical term per governed concept.** Where the project has established a canonical term, that term must be preferred in all documentation, governance outputs, and implementation-facing descriptions. Variants are acceptable only when they are explicitly listed as acceptable and do not create ambiguity.
- **Preserve the strongest canonical form.** When a canonical term has both a strong and a weak variant, prefer the strong governed form. `NO_TRADE` is stronger than `no-trade` or `hold-fire`. `Snapshot Truth` carries more precision than `snapshot state`. Prefer precision.
- **Do not invent new canonical terms.** If a request uses a term not present in the canonical term table, the skill must flag it as unrecognized rather than silently adopting it as canonical.
- **Ambiguity is a finding, not a style preference.** When one term is used for two different governed concepts, or two terms are used for the same governed concept in a way that makes interpretation unstable, this is an `ambiguity_detected` finding that must be surfaced.
- **Governance-sensitive drift is a harder finding.** When terminology drift would change how a claim is interpreted by downstream governance steps — affecting phase meaning, readiness status, boundary semantics, or evidence classification — this is a `governance_sensitive_term_conflict` and must be treated as more severe than simple variant normalization.
- **Do not rewrite silently.** This skill produces a normalization map with explicit `from → to` actions. It does not silently rewrite text. All proposed normalizations must include a reason.
- **Be conservative.** When meaning is unclear, prefer `review_only` over approving a potentially drifted term. Prefer explicit normalization over inferred equivalence.
- **README_LAYER2.md is not a terminology override.** Casual or workflow-oriented phrasing in `README_LAYER2.md` does not establish canonical terms. If it uses a term inconsistently with a Tier 1 source, the Tier 1 source governs.

---

## Canonical source priority

When determining the authoritative definition or canonical form of a term, use role-matched selection.

### Tier 1 — canonical current-state sources

| Priority | Document | Role for this skill |
|---|---|---|
| 1 | `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Technical term definitions, field names, constraint terminology, snapshot contract vocabulary, DB discipline invariants |
| 2 | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architecture terms, layer names, phase vocabulary, component names, stage-gate language, build-order terminology |
| 3 | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Implementation-status terminology, what-is-built language, component naming in implemented state |
| 4 | `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Limitation and open-item vocabulary, readiness phrasing, approximation naming |
| 5 | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Verification-status terminology, consistency classification language |
| 6 | `README_v1.md` | Top-level orientation vocabulary, public-facing canonical phrasing, system identity term |

### Tier 2 — verification and governance artifacts

| Priority | Document | Role |
|---|---|---|
| 7 | `verification_ledger.md` | Claim → evidence → status vocabulary in the ledger context |
| 8 | `system-orchestration.yaml` | Skill names, hook names, subagent names, blocking condition labels |

### Tier 3 — supporting context only

| Priority | Document | Role |
|---|---|---|
| 9 | `README_LAYER2.md` | Collaborator-workflow phrasing; acceptable as context but must not override Tier 1 terminology for any canonical term |

**Conflict resolution rule:** When two sources define the same concept differently, the Tier 1 source with the most specific declared role for that concept type governs. For technical field names and contract vocabulary: `SYSTEM_TECHNICAL_HANDBOOK_v1.md`. For component and layer names: `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`. Do not silently adopt a variant from a lower-tier source.

---

## Arguments

This skill accepts the following optional arguments.

- `scope=auto|request-only|request-and-artifacts`
- `mode=strict|audit|light`
- `targets=<comma-separated files, terms, claims, or concept IDs>`
- `report=json|json+summary`

Defaults:
- `scope=auto`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer the best scope from the request and upstream outputs; read changed docs and artifacts when the request involves documentation changes or governance writeups (default)
- `request-only`: evaluate terminology in the request text and classification outputs only; do not read doc files
- `request-and-artifacts`: explicitly read and evaluate the changed docs and governance artifacts in addition to the request

### `mode`
Controls strictness and note density.
- `strict`: flag all non-canonical variants, ambiguities, and governance-sensitive conflicts; recommended for governance decisions
- `audit`: include expanded rationale, full term-trace analysis, cross-artifact normalization recommendations, and source-conflict traces; use for deep review sessions
- `light`: flag obvious governance-sensitive conflicts only; do not use for release or governance-critical decisions

### `targets`
Optional focus hints. Use to narrow analysis to specific terms or artifacts.

Examples:
- `targets=NO_TRADE,DecisionPacket`
- `targets=SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md,Phase-B`
- `targets=snapshot,observations,Snapshot Truth`

### `report`
Controls output verbosity.
- `json`: structured output only (canonical term map + checked items + summary)
- `json+summary`: structured output plus a short plain-language summary

---

## Canonical term table

This table defines the project's governed canonical vocabulary. It is the reference the skill uses when evaluating terminology in requests, documents, and governance artifacts.

Entries are organized by concept group. Each entry defines the canonical term, its concept scope, allowed variants, and discouraged or forbidden variants.

### Group: system identity and architecture

| Concept ID | Canonical term | Meaning / scope | Allowed variants | Discouraged variants |
|---|---|---|---|---|
| `SYSTEM_IDENTITY` | `gold-first, fail-closed, snapshot-based decision support system` | The complete identity of the Mr. Ripley system | `gold-first engine`, `Mr. Ripley system` | `live system`, `trading system`, `automated execution system` |
| `LAYER_2` | `Layer-2` | The deterministic ingestion and snapshot publication layer | `Layer 2` (for prose) | `truth layer`, `data layer`, `ingestion layer`, `L2` |
| `LAYER_3` | `Layer-3` | The decision analysis and DecisionPacket layer (planned/Phase B) | `Layer 3` (for prose) | `decision engine`, `signal layer`, `execution layer`, `L3` |
| `SNAPSHOT_TRUTH` | `Snapshot Truth` | The immutable Layer-2-owned published truth base | — | `snapshot state`, `current truth`, `market truth`, `live truth` |
| `LIVE_MARKET_STATE` | `Live Market State` | The Layer-3 state construct that consumes snapshots to represent current market posture | — | `live state`, `market state`, `current state`, `real-time state` |
| `EVENT_RISK_STREAM` | `Event Risk Stream` | The Layer-3 event-driven construct tracking scheduled or known risk events | — | `event stream`, `risk events`, `event risk`, `event queue` |

### Group: snapshot boundary concepts

| Concept ID | Canonical term | Meaning / scope | Allowed variants | Discouraged variants |
|---|---|---|---|---|
| `SNAPSHOT` | `snapshot` | A published, immutable, versioned Layer-2 truth artifact | `published snapshot` | `data pull`, `observation snapshot`, `truth pull`, `latest data` |
| `SNAPSHOT_ID` | `snapshot_id` | The identity anchor for a specific published snapshot; used for anchored downstream reads | — | `snapshot identifier`, `snap_id`, `snapshot key` |
| `LATEST_SNAPSHOT` | `latest_snapshot.json` | The published file artifact produced by the snapshot publisher; the governed entry point for downstream consumers | — | `latest snapshot`, `snapshot file`, `current snapshot`, `snapshot cache` |
| `SNAPSHOT_VALUES` | `snapshot_values` | The governed DB table containing per-series values for each published snapshot | — | `snapshot data`, `snap values`, `snapshot entries` |
| `SNAPSHOTS_TABLE` | `snapshots` | The governed DB table containing snapshot-level metadata | — | `snapshot metadata`, `snapshot records`, `snapshot table` |
| `OBSERVATIONS` | `observations` | The raw Layer-2 ingestion table; accessible only within Layer-2; never downstream | — | `raw data`, `obs`, `observation data`, `ingest data`, `Layer-2 data` |
| `SNAPSHOT_CONTRACT` | `snapshot contract` | The versioned, immutable specification governing what a published snapshot must contain | `Layer-2 → Layer-3 contract`, `handoff contract` | `snapshot spec`, `snapshot interface`, `snapshot agreement` |

### Group: decision layer concepts

| Concept ID | Canonical term | Meaning / scope | Allowed variants | Discouraged variants |
|---|---|---|---|---|
| `NO_TRADE` | `NO_TRADE` | The default fail-closed decision output when guard conditions are not satisfied | — | `no-trade`, `no trade`, `hold-fire`, `HOLD`, `no action`, `default hold`, `neutral` |
| `DECISION_PACKET` | `DecisionPacket` | The structured output artifact of Layer-3 analysis; not yet implemented | — | `decision payload`, `decision object`, `trading packet`, `decision output`, `decision struct` |
| `GUARD_TAXONOMY` | `guard taxonomy` | The governed classification of Layer-3 guards that block or gate decisions | — | `guard list`, `guard rules`, `safety rules`, `guard conditions` |
| `STATE_TAXONOMY` | `state taxonomy` | The governed classification of Layer-3 state types | — | `state types`, `state list`, `state definitions` |
| `TRIGGER_TAXONOMY` | `trigger taxonomy` | The governed classification of Layer-3 triggers | — | `trigger list`, `trigger types`, `trigger definitions` |

### Group: phase and build-sequence concepts

| Concept ID | Canonical term | Meaning / scope | Allowed variants | Discouraged variants |
|---|---|---|---|---|
| `PHASE_A` | `Phase A` | Layer-2 closure phase — complete at contract boundary | — | `phase 1`, `Layer-2 phase`, `ingestion phase` |
| `PHASE_B` | `Phase B` | Layer-3 bootstrap phase — allowed, not complete | — | `phase 2`, `Layer-3 phase`, `bootstrap phase` |
| `PHASE_C` | `Phase C` | Layer-3 structured buildout — future | — | `phase 3`, `buildout phase` |
| `PHASE_D` | `Phase D` | Live execution gate — blocked | — | `phase 4`, `execution phase`, `live phase` |
| `HANDOFF_GATE` | `Layer-2 → Layer-3 handoff gate` | The formal gate confirming Layer-2 contract delivery is complete enough for Phase B to begin | `handoff gate`, `handoff gate satisfied` | `Layer-2 done`, `Layer-2 complete`, `Layer-3 ready to start` |

### Group: Layer-2 technical vocabulary

| Concept ID | Canonical term | Meaning / scope | Allowed variants | Discouraged variants |
|---|---|---|---|---|
| `SERIES_REGISTRY` | `series_registry.json` | The single source of truth for all series metadata | `registry`, `series registry` | `series config`, `series list`, `series definitions`, `series manifest` |
| `FAIL_CLOSED` | `fail-closed` | The publication model: no output rather than incorrect output | — | `fail safe`, `conservative`, `default off`, `fail-safe` |
| `GOLD_FIRST` | `gold-first` | The system's primary decision priority orientation toward gold price as primary asset state | — | `gold focused`, `gold priority`, `XAU first` |
| `INSERT_OR_IGNORE` | `INSERT OR IGNORE` | The only permitted DB upsert pattern for observation rows | — | `upsert`, `INSERT OR REPLACE`, `insert if not exists` |
| `CLOCK_TS` | `clock_ts` | The snapshot clock timestamp field in the `snapshots` table | — | `timestamp`, `snapshot time`, `clock timestamp`, `snap_ts` |
| `AS_OF` | `as_of` | The point-in-time anchor for snapshot publication | `as_of_ts` (in `observations`) | `as of`, `publish time`, `truth time` |
| `VERDICT` | `verdict` | The snapshot-level quality gate outcome field | — | `status`, `result`, `outcome`, `gate result` |
| `TIER1_PASS` | `tier1_pass` | The count of Tier-1 series passing the quality gate in a snapshot | — | `tier 1 pass`, `t1_pass`, `tier1 pass count` |
| `TIER1_FAIL` | `tier1_fail` | The count of Tier-1 series failing the quality gate in a snapshot | — | `tier 1 fail`, `t1_fail`, `tier1 fail count` |

### Group: evidence and verification vocabulary

| Concept ID | Canonical term | Meaning / scope | Allowed variants | Discouraged variants |
|---|---|---|---|---|
| `EVIDENCE_PROVEN` | `proven` | Verification status: claim is traceable to canonical source AND supported by code/runtime evidence | — | `confirmed`, `verified`, `validated`, `certified` |
| `EVIDENCE_SUPPORTED` | `supported` | Verification status: claim has consistent canonical documentation but lacks full code/runtime proof | — | `backed`, `evidenced`, `substantiated` |
| `EVIDENCE_UNVERIFIED` | `unverified` | Verification status: claim cannot be traced to canonical sources or confirmed by evidence | — | `unchecked`, `pending`, `not verified`, `unconfirmed` |
| `EVIDENCE_CONTRADICTED` | `contradicted` | Verification status: claim conflicts with stronger evidence | — | `disproven`, `rejected`, `invalidated`, `wrong` |

### Group: implementation-state vocabulary

| Concept ID | Canonical term | Meaning / scope | Allowed variants | Discouraged variants |
|---|---|---|---|---|
| `IMPL_OPERATIONAL` | `operational` | Layer-2 current state: implemented and functioning at the contract boundary | `implemented`, `built` | `live`, `production`, `running in production`, `active` |
| `IMPL_NOT_BUILT` | `not yet built` | Component state: planned but not implemented | `not built`, `open item` | `pending`, `TBD`, `future work`, `in progress` |
| `IMPL_PLANNED` | `planned` | Architecture state: defined in target architecture, not yet in current state | `target architecture` | `designed`, `specified`, `roadmapped` |
| `IMPL_BLOCKED` | `blocked` | Phase D execution state: explicitly not allowed until gate criteria are met | — | `disabled`, `gated`, `not enabled`, `off` |

---

## Terminology dimension 1: Canonical term extraction

When evaluating a request or artifact, the first step is to identify which governed canonical terms are present in or relevant to the scope.

### Extraction procedure

1. Read the request text or changed artifact.
2. Identify all occurrences of project-governed concept words — both canonical forms and potential variants.
3. Map each occurrence to its concept group using the canonical term table.
4. Note any terms that do not appear in the canonical term table — these are candidates for `unrecognized_term` findings.
5. Produce the `canonical_terms` array in the output for each concept group that is active in the scope.

### Unrecognized terms

If a request or artifact introduces a term for a concept not present in the canonical term table, and the term appears to describe a governed concept (snapshot boundary, phase state, decision artifact, evidence status), flag it as an unrecognized term:
- set `assessment: review`
- note that the term is not in the canonical table
- do not silently adopt it as canonical
- do not invent a canonical form — surface it for human review

---

## Terminology dimension 2: Variant normalization

This dimension checks whether the request or artifact uses non-canonical variants where canonical terms should be used, and produces the normalization map.

### Normalization rules

1. **Casing variants.** `NO_TRADE` must be in all-caps with underscore. `no trade`, `No Trade`, `no-trade`, `NOTRADE` are all non-canonical and must normalize to `NO_TRADE`. Similarly, `DecisionPacket` uses PascalCase without a space.
2. **Spacing variants.** `Layer-2` uses a hyphen. `Layer 2` is an acceptable variant in prose but should be flagged for normalization in governance artifacts and formal documents. `L2` is discouraged.
3. **Synonym drift.** `hold-fire` for `NO_TRADE`, `decision payload` for `DecisionPacket`, `series config` for `series_registry.json`, `timestamp` for `clock_ts` — all must be normalized to their canonical form.
4. **Vagueness substitution.** When a general term like `data` is used where `observations` or `snapshot values` is the precise governed term, and the governed term is determinable from context, flag it for normalization.
5. **Plural/singular consistency.** `observations` is always plural (it is a table name). `snapshot` may be singular or plural depending on context. Ensure the governed form is preserved.

### When not to normalize

- Do not normalize a term if the meaning is legitimately context-dependent and no governed term is determinable.
- Do not normalize a term if it appears in a section that explicitly discusses casual phrasing or human-readable summaries, provided the canonical form is nearby or referenced.
- Do not force normalization in `light` mode for variants that are not governance-sensitive.

---

## Terminology dimension 3: Ambiguity detection

This dimension checks whether terminology creates interpretation instability — one term used for multiple concepts, or multiple terms used for one concept in the same artifact.

### What constitutes ambiguity

1. **Same term, multiple concepts.** The word `snapshot` used to mean both the published Layer-2 artifact and a local cached copy of recent observations — in the same document or request.
2. **Multiple terms, same concept.** `NO_TRADE`, `no-trade`, and `hold-fire default` all appearing for the same governed concept without a canonical resolution.
3. **Hidden governed concept.** A vague term like `current state` used where the governed concept is specifically `Live Market State` — the weaker term hides the governed one and makes claim routing ambiguous.
4. **Overloaded evidence terms.** `verified` used to mean both `proven` (the strongest evidence status) and `confirmed by review` (closer to `supported`) — creating instability in verification classification.

### Finding

When ambiguity is detected:
- set `ambiguity_detected: true` in the relevant `checked_items` entry
- identify both concepts or both terms involved
- produce a normalization action that resolves the ambiguity
- set `overall_status: ambiguity_detected` if no governance-sensitive conflict is present, or upgrade to `governance_sensitive_term_conflict` if the ambiguity would change claim interpretation, boundary meaning, or phase posture

---

## Terminology dimension 4: Governance-sensitive terminology

This dimension checks whether terminology drift affects how downstream governance steps classify, route, or evaluate claims and boundaries.

### Categories of governance-sensitive terminology

**Category A: Snapshot boundary vocabulary**

The following terms carry governed boundary meaning. Using a synonym or variant that blurs the boundary is governance-sensitive:
- `snapshot` vs. `observations` — conflating them implies downstream observation access is acceptable
- `latest_snapshot.json` vs. `latest data file` — vagueness weakens the governed interface semantics
- `Snapshot Truth` vs. `snapshot state` — the canonical form carries immutability and ownership semantics that the variant loses
- `snapshot_id`-anchored vs. unnamed read — the anchoring language is part of the replayability contract

**Category B: Phase and readiness vocabulary**

The following terms carry governed phase/readiness meaning. Using a variant that overstates or understates status is governance-sensitive:
- `operational` vs. `live` — `operational` means implemented and functioning at contract boundary; `live` implies production execution (Phase D)
- `Phase B` vs. `bootstrap` — `Phase B` is the governed phase label; `bootstrap` is acceptable as description but must not replace the phase label in governance artifacts
- `blocked` vs. `not enabled` — `blocked` carries the Phase D gate semantics; `not enabled` is too weak
- `planned` vs. `designed` — `planned` signals target architecture; `designed` could imply more progress

**Category C: Evidence and verification vocabulary**

The following terms carry governed verification-status meaning. Using them interchangeably creates classification instability:
- `proven` vs. `supported` — these are distinct verification statuses; conflating them would allow a supported claim to be treated as proven
- `supported` vs. `verified` — `verified` is not a governed verification status; using it blurs the evidence classification
- `unverified` vs. `pending` — `pending` implies future verification is planned; `unverified` is the evidence-classification term and carries no implication of planned action
- `contradicted` vs. `wrong` / `disproven` — the canonical term is `contradicted`; alternatives do not carry the same formal status

**Category D: Decision and NO_TRADE vocabulary**

The following terms carry governed decision-layer meaning:
- `NO_TRADE` must be exact — any variation removes the formal status of the default action
- `DecisionPacket` must be PascalCase without spaces — it is a specific planned artifact, not a generic concept
- `guard taxonomy` / `state taxonomy` / `trigger taxonomy` — these are formal governed classifications; casual alternatives like `guard list` or `state types` are discouraged in governance artifacts

### Finding

When governance-sensitive terminology drift is detected:
- set `governance_sensitive: true` in the relevant `checked_items` entry
- set `overall_status: governance_sensitive_term_conflict`
- describe which governance step or classification would be affected by the drift
- produce a precise normalization action

---

## Output schema

Emit a single JSON object conforming to the following structure. Field names are fixed.

```json
{
  "canonical_terminology_status": {
    "overall_status": "<compliant | review_only | normalization_required | ambiguity_detected | governance_sensitive_term_conflict>",
    "inference_used": false,
    "canonical_terms": [
      {
        "concept_id": "<string from the canonical term table>",
        "canonical_term": "<the governed canonical form>",
        "meaning": "<concise concept scope>",
        "allowed_variants": ["<string>"],
        "discouraged_variants": ["<string>"]
      }
    ],
    "checked_items": [
      {
        "item_id": "<string — unique identifier for this check>",
        "target": "<document, artifact, request section, or claim>",
        "observed_terms": ["<all term occurrences evaluated in this item>"],
        "normalization_actions": [
          {
            "from": "<observed non-canonical form>",
            "to": "<canonical form>",
            "concept_id": "<concept ID from canonical term table>",
            "reason": "<why this normalization is required>"
          }
        ],
        "ambiguity_detected": false,
        "governance_sensitive": false,
        "unrecognized_term_detected": false,
        "affected_artifacts": ["<document or artifact name>"],
        "assessment": "<compliant | review | normalize>",
        "canonical_source": "<primary canonical document cited for this term>",
        "notes": ["<additional notes for downstream steps>"]
      }
    ],
    "summary": {
      "normalization_required": false,
      "ambiguity_detected": false,
      "governance_sensitive_term_conflict_detected": false,
      "unrecognized_terms_detected": false,
      "requires_doc_sync_review": false,
      "requires_verification_followup": false,
      "source_authority_conflict_detected": false,
      "notes": ["<summary-level notes>"]
    }
  }
}
```

### Field definitions

| Field | Type | Meaning |
|---|---|---|
| `overall_status` | string | Aggregate terminology verdict across all checked items |
| `inference_used` | boolean | True if `request_classification` was absent and term scope was inferred |
| `canonical_terms` | array | Active canonical terms for this check — populated from the canonical term table for concepts in scope |
| `concept_id` | string | Identifier from the canonical term table |
| `canonical_term` | string | The governed canonical form |
| `meaning` | string | Concise concept scope |
| `allowed_variants` | array | Acceptable alternatives that do not require normalization |
| `discouraged_variants` | array | Forms that should be normalized away |
| `item_id` | string | Unique ID for this check (e.g., `"term-01"`, `"amb-02"`) |
| `target` | string | The document, artifact, or request section being evaluated |
| `observed_terms` | array | All term occurrences evaluated in this item |
| `normalization_actions` | array | Explicit from → to normalization steps with reasons |
| `from` | string | The observed non-canonical form |
| `to` | string | The canonical form it should resolve to |
| `concept_id` (action) | string | The concept this normalization addresses |
| `reason` | string | Why this normalization is governance-relevant |
| `ambiguity_detected` | boolean | True if the same term is used for multiple concepts or multiple terms for one concept |
| `governance_sensitive` | boolean | True if the terminology drift affects downstream governance interpretation |
| `unrecognized_term_detected` | boolean | True if a term appears that is not in the canonical term table but describes a governed concept |
| `affected_artifacts` | array | Documents or artifacts that contain the flagged terminology |
| `assessment` | string | Item-level verdict: `compliant`, `review`, or `normalize` |
| `canonical_source` | string | The Tier 1 canonical document that defines or governs this term |
| `notes` | array | Notes for downstream steps |
| `normalization_required` (summary) | boolean | Summary: any item requires normalization |
| `ambiguity_detected` (summary) | boolean | Summary: any item has `ambiguity_detected: true` |
| `governance_sensitive_term_conflict_detected` (summary) | boolean | Summary: any item has `governance_sensitive: true` |
| `unrecognized_terms_detected` (summary) | boolean | Summary: any unrecognized terms were flagged |
| `requires_doc_sync_review` | boolean | True if terminology findings imply documentation updates or doc-code sync review |
| `requires_verification_followup` | boolean | True if terminology findings affect how claims are classified in the verification matrix or ledger |
| `source_authority_conflict_detected` | boolean | True if `README_LAYER2.md` or a non-role-matched source is used as primary authority for a governed term |

---

## Decision rules

### `compliant`

Use when all of the following hold:
- all terms in scope are canonical or explicitly acceptable variants
- no governance-sensitive ambiguity is introduced
- no unrecognized terms describe governed concepts
- the terminology does not affect downstream governance classification

### `review_only`

Use when:
- terminology is mostly acceptable but meaning or artifact context is incomplete,
- a possible variant needs human confirmation before normalization,
- terms from `README_LAYER2.md` are used that may or may not match canonical usage in context,
- a casual synonym does not create governance risk but is not the preferred canonical form.

### `normalization_required`

Use when:
- non-canonical variants are clearly being used where a canonical term should be enforced,
- the inconsistency is visible and unambiguous even if not immediately governance-dangerous,
- a normalization action is available with a clear `from → to` mapping.

### `ambiguity_detected`

Use when:
- one term is used for multiple governed concepts,
- multiple terms are used for one governed concept in a way that creates interpretation instability,
- a weaker general term hides a stricter governed concept and the distinction matters for claim routing.

### `governance_sensitive_term_conflict`

Use when:
- terminology drift changes or risks changing how a claim is classified, routed, or enforced,
- snapshot boundary vocabulary is blurred in a way that weakens the boundary semantics,
- evidence status terms are used interchangeably, affecting verification classification,
- phase or readiness terms overstate or understate system status,
- `NO_TRADE`, `DecisionPacket`, or taxonomy terms are used in non-canonical forms in governance-relevant contexts.

---

## Patterns to detect

Apply these pattern checks when documentation and governance artifacts are available.

| Pattern | Category | Finding |
|---|---|---|
| `no trade`, `no-trade`, `hold-fire`, `HOLD`, `neutral` used for the `NO_TRADE` default | D: Decision vocabulary | `governance_sensitive_term_conflict`; normalize to `NO_TRADE` |
| `decision payload`, `decision output`, `decision struct` used for `DecisionPacket` | D: Decision vocabulary | `normalization_required`; normalize to `DecisionPacket` |
| `snapshot` used to describe a raw observation pull or local data cache | A: Boundary vocabulary | `governance_sensitive_term_conflict`; clarify and separate terms |
| `latest data`, `current snapshot`, `snapshot file` for `latest_snapshot.json` | A: Boundary vocabulary | `normalization_required`; normalize to `latest_snapshot.json` |
| `observation data`, `raw data`, `L2 data` for `observations` | A: Boundary vocabulary | `normalization_required`; normalize to `observations` |
| `timestamp` for `clock_ts` in snapshot-context | Technical field | `normalization_required`; normalize to `clock_ts` |
| `tier 1 pass count`, `t1_pass` for `tier1_pass` | Technical field | `normalization_required`; normalize to `tier1_pass` |
| `result`, `status`, `outcome` for `verdict` in snapshot-context | Technical field | `normalization_required`; normalize to `verdict` |
| `verified`, `confirmed`, `validated` used as verification status | C: Evidence vocabulary | `governance_sensitive_term_conflict`; normalize to governed status (`proven`, `supported`, `unverified`, `contradicted`) |
| `proven` and `supported` used interchangeably | C: Evidence vocabulary | `governance_sensitive_term_conflict`; distinct governed statuses |
| `live`, `production-active`, `running` used where `operational` is correct | B: Readiness vocabulary | `governance_sensitive_term_conflict`; `live` implies Phase D |
| `not enabled`, `disabled`, `gated` for `blocked` (Phase D) | B: Readiness vocabulary | `normalization_required`; normalize to `blocked` |
| `L2`, `truth layer`, `data layer` for `Layer-2` | Architecture | `normalization_required`; normalize to `Layer-2` |
| `snapshot state`, `live truth`, `market truth` for `Snapshot Truth` | A: Boundary vocabulary | `governance_sensitive_term_conflict`; `Snapshot Truth` carries immutability semantics |
| `series config`, `series list`, `series definitions` for `series_registry.json` | Technical | `normalization_required` |
| `INSERT OR REPLACE` referenced without flagging it as forbidden | Technical | `governance_sensitive_term_conflict`; the only permitted form is `INSERT OR IGNORE` |
| New alias for `DecisionPacket` introduced without canonical justification | D: Decision vocabulary | `normalization_required` or `governance_sensitive_term_conflict` |
| `README_LAYER2.md` cited as canonical authority for a term governed by a Tier 1 source | Source authority | `source_authority_conflict_detected: true` |

---

## Checklist

Before emitting the output, confirm each item.

- [ ] All governed canonical terms relevant to the scope have been identified and included in the `canonical_terms` array.
- [ ] All term occurrences in the request or changed artifacts have been evaluated.
- [ ] Casing, spacing, and spelling variants detected and included in normalization actions.
- [ ] Synonym drift detected and mapped to canonical form where determinable.
- [ ] Ambiguity (one term for multiple concepts, or multiple terms for one concept) checked and flagged if present.
- [ ] Governance-sensitive categories A–D evaluated for any active terms in scope.
- [ ] `overall_status` reflects the most severe finding across all `checked_items`.
- [ ] `governance_sensitive_term_conflict_detected` set to `true` if any item has `governance_sensitive: true`.
- [ ] `requires_doc_sync_review` set to `true` if terminology drift implies documentation updates are needed.
- [ ] `requires_verification_followup` set to `true` if terminology drift affects verification status classification.
- [ ] `source_authority_conflict_detected` set if `README_LAYER2.md` is used as primary authority for a governed term.
- [ ] `inference_used` set correctly.
- [ ] All normalization actions include `from`, `to`, `concept_id`, and `reason`.
- [ ] No new canonical terms invented — unrecognized terms flagged as `unrecognized_term_detected: true`.
- [ ] No silent rewrites — all normalization actions are explicit and traceable.

---

## Worked examples

### Example 1: `NO_TRADE` written inconsistently across three documents

**Request / context:** "One document says `no trade`, another says `NO_TRADE`, and a third says `hold-fire default` when describing the fail-closed default decision."

**Analysis:**
- The canonical term is `NO_TRADE` — all-caps, underscore-separated, as defined in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`.
- `no trade` is a casing/spacing variant and must normalize.
- `hold-fire default` is a synonym and must normalize. It also softens the formal governance status of the term.
- Multiple terms for one concept in governance artifacts creates `ambiguity_detected` and, given that `NO_TRADE` carries formal decision-layer governance meaning, this is `governance_sensitive_term_conflict`.

**Expected output (key fields):**

```json
{
  "canonical_terminology_status": {
    "overall_status": "governance_sensitive_term_conflict",
    "canonical_terms": [
      {
        "concept_id": "NO_TRADE",
        "canonical_term": "NO_TRADE",
        "meaning": "The default fail-closed decision output when guard conditions are not satisfied",
        "allowed_variants": [],
        "discouraged_variants": ["no-trade", "no trade", "hold-fire", "hold-fire default", "HOLD", "neutral"]
      }
    ],
    "checked_items": [
      {
        "item_id": "term-01",
        "target": "decision default — three documents",
        "observed_terms": ["no trade", "NO_TRADE", "hold-fire default"],
        "normalization_actions": [
          {"from": "no trade", "to": "NO_TRADE", "concept_id": "NO_TRADE", "reason": "Casing and spacing variant of the canonical term."},
          {"from": "hold-fire default", "to": "NO_TRADE", "concept_id": "NO_TRADE", "reason": "Synonym that weakens the formal governance status of the default decision action."}
        ],
        "ambiguity_detected": true,
        "governance_sensitive": true,
        "affected_artifacts": ["all three documents"],
        "assessment": "normalize",
        "canonical_source": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"
      }
    ],
    "summary": {
      "normalization_required": true,
      "ambiguity_detected": true,
      "governance_sensitive_term_conflict_detected": true,
      "requires_doc_sync_review": true
    }
  }
}
```

---

### Example 2: `snapshot` used for both governed artifact and raw observation pull

**Request / context:** "A request uses the word `snapshot` to refer both to the published `latest_snapshot.json` artifact and to an informal pull of recent observation rows for quick analysis."

**Analysis:**
- `snapshot` in the governed model means a published, immutable, versioned Layer-2 truth artifact anchored by `snapshot_id`.
- Using the same word for a raw observation pull blurs the snapshot boundary — a governance-sensitive finding.
- The raw observation pull should be described as an `observations` query, not as a snapshot.
- This is both `ambiguity_detected` and `governance_sensitive_term_conflict`.

**Expected output (key fields):**

```json
{
  "canonical_terminology_status": {
    "overall_status": "governance_sensitive_term_conflict",
    "checked_items": [
      {
        "item_id": "amb-01",
        "target": "snapshot — dual usage in request",
        "observed_terms": ["snapshot (published artifact)", "snapshot (observation pull)"],
        "normalization_actions": [
          {"from": "snapshot (observation pull context)", "to": "observations query", "concept_id": "OBSERVATIONS", "reason": "Raw observation pulls must not be called snapshots. The governed snapshot contract refers exclusively to published, versioned Layer-2 artifacts."}
        ],
        "ambiguity_detected": true,
        "governance_sensitive": true,
        "affected_artifacts": ["request text"],
        "assessment": "normalize",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["Conflating snapshot with observations blurs the snapshot boundary invariant. This confusion could weaken downstream boundary enforcement."]
      }
    ],
    "summary": {
      "governance_sensitive_term_conflict_detected": true,
      "ambiguity_detected": true,
      "requires_doc_sync_review": true
    }
  }
}
```

---

### Example 3: `supported` and `proven` used interchangeably

**Request / context:** "A governance output uses `supported` and `proven` as synonyms when describing evidence status."

**Analysis:**
- `proven` and `supported` are distinct governed verification statuses defined in the verification ledger model.
- `proven` requires traceable canonical source AND code/runtime evidence.
- `supported` requires consistent documentation evidence but lacks full code/runtime proof.
- Using them interchangeably would allow a `supported` claim to be treated as `proven`, undermining evidence classification.
- This is `governance_sensitive_term_conflict`.

**Expected output (key fields):**

```json
{
  "canonical_terminology_status": {
    "overall_status": "governance_sensitive_term_conflict",
    "checked_items": [
      {
        "item_id": "term-01",
        "target": "governance output — evidence status terminology",
        "observed_terms": ["supported", "proven"],
        "normalization_actions": [],
        "ambiguity_detected": true,
        "governance_sensitive": true,
        "affected_artifacts": ["governance output"],
        "assessment": "normalize",
        "canonical_source": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "notes": ["proven requires canonical source + code/runtime evidence. supported requires only consistent documentation. These must not be treated as synonyms. Correct each usage to its precise governed status."]
      }
    ],
    "summary": {
      "governance_sensitive_term_conflict_detected": true,
      "ambiguity_detected": true,
      "requires_verification_followup": true
    }
  }
}
```

---

### Example 4: Collaborator guide uses casual phrasing with clear canonical mapping

**Request / context:** "A collaborator guide section refers to 'the published truth file' when describing `latest_snapshot.json`, and 'the truth table' when describing `snapshot_values`. The meaning is clear from context."

**Analysis:**
- `published truth file` maps clearly to `latest_snapshot.json`. The meaning is not ambiguous. The canonical form is preferred but the variant does not weaken boundary semantics.
- `truth table` maps clearly to `snapshot_values`. Again, the meaning is not ambiguous and no boundary confusion is introduced.
- In `strict` mode: flag as `normalization_required` for consistency in formal documents; in a collaborator guide, downgrade to `review_only`.
- No governance-sensitive conflict.

**Expected output (key fields):**

```json
{
  "canonical_terminology_status": {
    "overall_status": "review_only",
    "checked_items": [
      {
        "item_id": "term-01",
        "target": "collaborator guide — casual phrasing",
        "observed_terms": ["published truth file", "truth table"],
        "normalization_actions": [
          {"from": "published truth file", "to": "latest_snapshot.json", "concept_id": "LATEST_SNAPSHOT", "reason": "Canonical form preferred for formal consistency; not governance-sensitive in this context."},
          {"from": "truth table", "to": "snapshot_values", "concept_id": "SNAPSHOT_VALUES", "reason": "Canonical table name preferred; variant is clear but informal."}
        ],
        "ambiguity_detected": false,
        "governance_sensitive": false,
        "affected_artifacts": ["README_LAYER2.md (collaborator guide section)"],
        "assessment": "review",
        "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "notes": ["Casual phrasing is acceptable in collaborator-workflow sections; canonical forms preferred in governance artifacts and formal documentation."]
      }
    ],
    "summary": {
      "normalization_required": false,
      "governance_sensitive_term_conflict_detected": false
    }
  }
}
```

---

### Example 5: Architecture docs introduce a new alias for `DecisionPacket`

**Request / context:** "An architecture doc update introduces the term `ActionBundle` to describe the Layer-3 decision output, without reference to `DecisionPacket`."

**Analysis:**
- `DecisionPacket` is the canonical term for the Layer-3 decision output artifact, defined in `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`.
- `ActionBundle` is an unrecognized term that does not appear in the canonical term table.
- Introducing a new alias without canonical justification creates terminology ambiguity and could split documentation coherence across skills, auditors, and future development.
- In `strict` mode: flag as `normalization_required` unless a canonical justification for the new term is provided.

**Expected output (key fields):**

```json
{
  "canonical_terminology_status": {
    "overall_status": "normalization_required",
    "checked_items": [
      {
        "item_id": "term-01",
        "target": "architecture doc — Layer-3 decision output alias",
        "observed_terms": ["ActionBundle"],
        "normalization_actions": [
          {"from": "ActionBundle", "to": "DecisionPacket", "concept_id": "DECISION_PACKET", "reason": "DecisionPacket is the canonical term for the Layer-3 decision output artifact. ActionBundle is an unrecognized alias without canonical justification. Introducing it splits documentation coherence."}
        ],
        "ambiguity_detected": false,
        "governance_sensitive": false,
        "unrecognized_term_detected": true,
        "affected_artifacts": ["SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"],
        "assessment": "normalize",
        "canonical_source": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "notes": ["If a name change from DecisionPacket is intentional, it must be established as canonical through a formal doc update to all relevant canonical documents before use."]
      }
    ],
    "summary": {
      "normalization_required": true,
      "unrecognized_terms_detected": true,
      "requires_doc_sync_review": true
    }
  }
}
```

---

## Completion standard

This skill's output is complete when all of the following hold.

1. The `canonical_terms` array includes an entry for every governed concept that is active in the scope of the request or artifact.
2. Every term occurrence in the request text or changed artifact has been evaluated against the canonical term table.
3. Every non-canonical form has a corresponding entry in `normalization_actions` with `from`, `to`, `concept_id`, and `reason`.
4. `overall_status` reflects the most severe finding across all items: if any item is `governance_sensitive_term_conflict`, the overall status must be `governance_sensitive_term_conflict`.
5. `governance_sensitive_term_conflict_detected` is `true` whenever any item has `governance_sensitive: true`.
6. `requires_doc_sync_review` is `true` whenever terminology findings imply that canonical documentation needs to be updated for consistency.
7. `requires_verification_followup` is `true` whenever terminology findings would affect how claims are classified in the verification matrix or ledger.
8. `source_authority_conflict_detected` is set if `README_LAYER2.md` or a non-role-matched source is used as the authority for a governed term.
9. `inference_used` is set correctly.
10. No new canonical terms are invented — unrecognized terms are always flagged as `unrecognized_term_detected: true` and surface for human review rather than silent adoption.
11. The output is valid JSON conforming to the required schema.
12. In `json+summary` mode: a plain-language summary of no more than five sentences follows the JSON block, stating the overall verdict, the primary terminology finding type, the specific terms flagged, and the downstream actions required.
