# Rename / Alias Evidence Packet

Structured evidence template for terminology changes governed by CLAUDE.md §16.1.

This packet must be completed before any terminology change request can pass the DAG.

---

## 1. Affected Constitutional Sections (§16.1 criterion 1)

| Section | Content Affected | Change Type |
|---|---|---|
| §1 System Identity | "deterministic data ingestion (Layer 2)" | Alias annotation only — no text replacement |
| §3 Current vs Target | "Layer 2 = operational at snapshot boundary", "Layer 3" target components | Alias annotation only |
| §4 Stage-Gate Model | Phase A (Layer 2 Closure), Phase B (Layer 3 Bootstrap), Phase C (Layer 3 Buildout) | Alias annotation only |
| §6 Snapshot Contract | "Layer 3+ MUST read ONLY from published snapshots" | Alias annotation only |
| §11 Document Update | "README_LAYER2.md review" | No change — filename preserved |

**Assessment**: No constitutional text is replaced. Aliases appear as parenthetical annotations alongside preserved canonical terms.

---

## 2. Role-Matched Canonical Citations (§16.1 criterion 2)

Each claim type requires citation from the role-matched canonical document:

| Claim Type | Required Primary Source | Citation Status |
|---|---|---|
| Architecture naming | `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Required — must confirm alias does not conflict with documented layer boundaries |
| Implementation-state naming | `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Required — must confirm alias aligns with implemented component terminology |
| Documentation consistency scope | `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` | Required — must confirm alias does not introduce verification gaps |
| Workflow / naming enforcement | `system-orchestration.yaml` | Required — must confirm alias registration is compatible with governance workflow |
| Constitutional authority | `CLAUDE.md` | Required — §16.1 is the governing rule for this change |

**Prior rejection note (session 92aa2b79)**: The rejected request provided zero role-matched primary citations for 6 of 8 claims. This was the primary driver of the `role_citation_verdict=conflict_requires_block` signal.

---

## 3. Semantic Equivalence / Alias Declaration (§16.1 criterion 3)

§16.1 criterion 3 states: *"semantic equivalence is proven or old/new terms are kept as aliases"*

This request uses the **alias path** — canonical terms are preserved, aliases are additive.

### Proposed Aliases

| Canonical Term | Proposed Alias | Alias Status | Semantic Justification |
|---|---|---|---|
| Layer 2 / Layer-2 | Ingestion Layer | Non-canonical | Matches CLAUDE.md §1: "deterministic data ingestion (Layer 2)". Describes function, not storage. No conflation with SNAPSHOT_TRUTH or OBSERVATIONS. |
| Layer 3 / Layer-3 | Computation Layer | Non-canonical | Matches CLAUDE.md §3.2: "Layer-3 snapshot-consuming computation". Semantically neutral — no execution or decision implication. Consistent with §9 analysis-only constraint. |

### Rejected Terms (with rationale)

| Rejected Term | Intended Target | Rejection Session | Rejection Rationale |
|---|---|---|---|
| `truth_store` | Layer 2 | `92aa2b79-d234-421a-ac71-1842b4e35836` | Conflates three distinct canonical concepts: LAYER_2 (architectural layer), SNAPSHOT_TRUTH (published artifact state), and OBSERVATIONS (raw data boundary). "Store" framing implies a data-storage artifact rather than an architectural layer. Category A conflict per terminology normalization. |
| `decision_layer` | Layer 3 | `92aa2b79-d234-421a-ac71-1842b4e35836` | Directly conflicts with CLAUDE.md §9 and §10 forbidden-claim constraints. Implies capabilities the system constitutionally prohibits. Semantically adjacent to explicitly discouraged variant "decision engine". Would cause downstream governance misrouting. Category D conflict per terminology normalization. |

**Rule**: Rejected terms must not be re-proposed in future requests without new canonical evidence establishing their safety.

---

## 4. Cross-Reference Update Scope (§16.1 criterion 4)

| Artifact | Cross-References Affected | Update Required |
|---|---|---|
| CLAUDE.md | None — canonical terms preserved | No |
| README_LAYER2.md (filename) | 6+ references in CLAUDE.md §§2.1, 2.2, 2.4, 11 | No — filename not renamed |
| README_LAYER2.md (content) | Layer-2 references in body text | Optional alias annotation only |
| SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | Layer-2 / Layer-3 architectural descriptions | Optional alias annotation only |
| SYSTEM_IMPLEMENTATION_RECORD_v1.md | Layer-2 implementation state references | Optional alias annotation only |
| DOCUMENTATION_VERIFICATION_MATRIX_v1.md | Layer-2 / Layer-3 claim entries | Alias registration entry required |
| system-orchestration.yaml | Layer-2 references in workflow steps | Review only — no rename |
| Code paths (layer2/, layer2/index_suite.py) | N/A | Excluded — not touched |
| series_registry.json | N/A | Excluded — not touched |

**Assessment**: Because canonical terms are unchanged, no cross-reference updates are required. Alias annotations are additive and do not break existing reference chains.

---

## 5. Verification Matrix + Ledger Entries (§16.1 criterion 5)

### Verification Matrix

| Entry ID | Section | Claim | Proposed Status |
|---|---|---|---|
| (new) | Section 8 — Terminology | "Ingestion Layer" registered as non-canonical alias for Layer 2 | Documented current-state claim |
| (new) | Section 8 — Terminology | "Computation Layer" registered as non-canonical alias for Layer 3 | Documented current-state claim |
| (existing) | Section 3 — Execution Boundary | Execution boundary integrity confirmed — no decision-implying aliases introduced | Verified (status review) |

### Verification Ledger

| Claim ID | Claim | Evidence Source | Evidence Type | Proposed Status |
|---|---|---|---|---|
| (new) | "Ingestion Layer" alias does not conflict with execution boundary, snapshot boundary, or canonical concept set | CLAUDE.md §1, normalized_terminology_map | doc | supported |
| (new) | "Computation Layer" alias does not conflict with execution boundary, snapshot boundary, or canonical concept set | CLAUDE.md §3.2, §9, normalized_terminology_map | doc | supported |
| (new) | Rejected terms "truth_store" and "decision_layer" recorded with governance rationale | Session 92aa2b79 artifacts | mixed | supported |

---

## 6. DAG Pass/Fail Record (§16.1 criterion 6)

### Prior Run (FAILED)

| Field | Value |
|---|---|
| Session | `92aa2b79-d234-421a-ac71-1842b4e35836` |
| Request ID | `rename-layer-terms-2026-04-20` |
| Result | **BLOCKED** — 3 blocking violations |
| Blocking Artifacts | `phase_alignment_status` (allowed=false), `contract_compliance_verdict` (allowed=false), `runtime_boundary_verdict` (boundary_violation_suspected) |
| Root Causes | No role-matched citations (6/8 claims), constitutional amendment without authority, `decision_layer` execution-boundary conflict, unverified replacement terms, no alias mapping |

### Current Run (PENDING)

| Field | Value |
|---|---|
| Session | (to be assigned) |
| Request ID | `alias-layer-terms-2026-04-28` |
| Result | **PENDING** — awaiting DAG execution |
| Prerequisites | Role-matched citations must be verified against actual canonical documents before DAG run |

---

## Usage Notes

- This packet is a **reusable template** for any future terminology change request.
- All six §16.1 criteria must be satisfied before the DAG can clear the request.
- The DAG is the final authority — this packet provides evidence, not authorization.
- If the DAG blocks, update Section 6 with the new failure record and revise the affected criteria sections.
