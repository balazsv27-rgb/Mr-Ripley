# Documentation Verification Matrix v1

## 1. Purpose of This Document

This matrix exists to reduce:
- architecture / implementation confusion
- bootstrap / live-readiness confusion
- approximation / truth confusion
- AI overstatement
- misuse of retained historical documentation as canonical current-state truth

It is a classification document, not an architecture proposal, not a review memo, and not an implementation-certification artifact.

---

## 2. Classification Rules

| Classification | Meaning |
|---|---|
| **Verified in current documentation set** | The canonical current-state documents make a direct, stable claim about the item and the claim is supported consistently across the current documentation set. This is still **not** independent certification. |
| **Documented current-state claim** | The item is described as current-state behavior or status in the canonical current documentation, but the docs themselves also indicate that line-by-line implementation verification is incomplete or pending. |
| **Planned / target architecture** | The item belongs to future architecture, later-stage sequencing, or downstream layers and is not claimed as current Layer-2 implementation. |
| **Cannot verify from current materials** | The current documentation set does not provide enough evidence to classify the item more strongly without inventing proof. |

**Important distinction:**
- “Documented current-state claim” is **not** the same as independent verification.
- `SYSTEM_IMPLEMENTATION_RECORD_v1.md` is retained historical / implementation context, **not** canonical current-state truth.

---

## 3. Layer-2 Contract Items

| Item | Classification | Primary evidence source | Conflict / ambiguity note | Notes / interpretation risk |
|---|---|---|---|---|
| Registry-driven ingestion | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | Registry is described as the single source of truth for series metadata, thresholds, and tiers. |
| Fail-closed quality gate | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | Tier-1 failure blocks publication; Layer-3 receives nothing rather than stale / incomplete data. |
| Immutable observations behavior | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | `INSERT OR IGNORE`, rev-0 rows not overwritten; revision writer remains absent. |
| Version-locked snapshot contract | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | Snapshots carry `engine_version` and `config_version`; consumers are expected to validate them. |
| Snapshot-only downstream boundary | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | Layer-3 must consume published snapshots, not raw observation-table reads. |
| No direct `observations` reads for Layer-3 | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md | No material conflict in current v1 docs | Repeated explicitly in README, handbook, and safe interpretation rules. |
| Canonical persisted snapshot interface (`snapshots` + `snapshot_values`) | Documented current-state claim | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | Current docs state this clearly; independent verification is still pending | Treated as canonical DB interface for downstream consumption. |
| Convenience handoff interface (`latest_snapshot.json`) | Documented current-state claim | README_v1.md; SYSTEM_IMPLEMENTATION_RECORD_v1.md | Historical record and README align; no current v1 conflict | Explicitly documented as convenience interface, not canonical persisted interface. |
| `guards` object in snapshot JSON | Planned / target architecture | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No conflict: all current docs say absent / required before bootstrap | Required before Layer-3 bootstrap starts; not yet implemented. |
| `reason_code` enum | Planned / target architecture | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No conflict: all current docs say absent / required before bootstrap | Required to prevent free-text creep at the execution boundary. |

---

## 4. Temporal and Data-Governance Items

| Item | Classification | Primary evidence source | Conflict / ambiguity note | Notes / interpretation risk |
|---|---|---|---|---|
| `clock_ts` / `clock_date` usage | Verified in current documentation set | SYSTEM_TECHNICAL_HANDBOOK_v1.md; README_v1.md | No material conflict in current v1 docs | Handbook defines the clock model and the relationship between `clock_ts`, `clock_date`, and replay behavior. |
| `as_of` discipline | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | Joint constraint `obs_ts <= clock_date` and `as_of_ts <= clock_ts` is central to point-in-time discipline. |
| Alignment rules | Documented current-state claim | SYSTEM_TECHNICAL_HANDBOOK_v1.md | No conflict in docs; line-by-line code verification remains pending | Handbook documents deterministic SQL tie-breaking and single-pass alignment. |
| Staleness governance | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | Threshold logic and Tier-1/Tier-2 behavior are described consistently. |
| 22:00 UTC policy wording | Verified in current documentation set | SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_IMPLEMENTATION_RECORD_v1.md | No material conflict in current v1 docs | Explicitly described as operational policy choice, not natural law. |
| Weekend / holiday / trading-calendar absorption | Documented current-state claim | SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_IMPLEMENTATION_RECORD_v1.md | No material conflict in current docs | Thresholds are documented as absorbing weekends / holidays / structural publication lag. |
| Source registry governance | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | Registry remains the single source of truth for series governance. |

---

## 5. Layer-3 Bootstrap Gate Items

| Item | Classification | Primary evidence source | Conflict / ambiguity note | Notes / interpretation risk |
|---|---|---|---|---|
| `guards` requirement | Planned / target architecture | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No conflict: all current docs classify as required before bootstrap | Explicit bootstrap blocker. |
| `reason_code` requirement | Planned / target architecture | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No conflict: all current docs classify as required before bootstrap | Explicit bootstrap blocker. |
| Layer-2 closure for bootstrap | Documented current-state claim | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No material conflict; current docs consistently define closure narrowly | Closure means stable snapshot handoff, not full Layer-2 perfection. |
| README/code sync requirement | Documented current-state claim | README_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No material conflict in current docs | Treated as required before Layer-3 bootstrap starts. |
| Doc/code sync pass status | Cannot verify from current materials | SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md | Current docs explicitly say not yet completed | Status is clearly open; current docs do not provide evidence of completion. |
| `layer1_events` optionality | Documented current-state claim | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No material conflict; docs consistently call it optional / recommended | Forward-compatible interface stability item, not a bootstrap blocker. |
| Bootstrap blockers vs non-blockers | Verified in current documentation set | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No material conflict in current v1 docs | Separation of blockers vs non-blockers is one of the clearest strengths of the docset. |

---

## 6. Live Execution / Operational Gate Items

| Item | Classification | Primary evidence source | Conflict / ambiguity note | Notes / interpretation risk |
|---|---|---|---|---|
| Daily scheduler | Planned / target architecture | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md | No conflict: current docs treat as required before live execution only | Not a bootstrap blocker. |
| Alerting | Planned / target architecture | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md | No conflict: current docs treat as live-only operational hardening | Not a bootstrap blocker. |
| Retry / rerun controls | Planned / target architecture | SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No material conflict in current docs | Belongs to operational readiness, not Layer-3 bootstrap. |
| Kill switch | Planned / target architecture | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No material conflict in current docs | Required before live execution, not before bootstrap. |
| Session-aware execution policy | Planned / target architecture | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No conflict: explicitly placed in execution layer / later gate | Docs are consistent that this does not belong to Layer-2 bootstrap. |
| Operational readiness hardening | Planned / target architecture | README_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No material conflict in current docs | Paper validation, calibration, kill switch testing, and operational stack all belong later. |
| Live execution gate as separate later gate | Verified in current documentation set | README_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No material conflict in current v1 docs | One of the clearest and most consistent themes in the current docset. |

---

## 7. Approximation and Limitation Items

| Item | Classification | Primary evidence source | Conflict / ambiguity note | Notes / interpretation risk |
|---|---|---|---|---|
| GLD proxy treatment | Verified in current documentation set | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current v1 docs | Explicitly treated as accepted approximation, not defect; must be labeled in backtests. |
| Gold history start limitations | Verified in current documentation set | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md | No material conflict in current v1 docs | Missing pre-2014 calibration window is consistently documented. |
| SP500 history gap | Verified in current documentation set | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md | No material conflict in current v1 docs | Explicitly high-priority non-blocker for bootstrap, calibration-affecting. |
| Revision exposure (`revision_risk`) | Planned / target architecture | README_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md | No conflict: current docs say required conceptually but not implemented | Must not be misread as already tracked. |
| Data coverage gaps | Verified in current documentation set | SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; README_v1.md | No material conflict in current v1 docs | Coverage gaps are clearly separated from approximations. |
| Repo-hygiene issue status (`layer2_truth.db`) | Cannot verify from current materials | SYSTEM_TECHNICAL_HANDBOOK_v1.md; SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; README_v1.md | Current docs explicitly keep this open; docs note observed inconsistency and pending re-verification | Must not be treated as resolved. |
| Revision writer (`revision_seq=1`) | Planned / target architecture | SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md; SYSTEM_TECHNICAL_HANDBOOK_v1.md | No material conflict in current docs | Missing write path means FRED corrections are silently dropped. |
| Monthly macro `as_of_ts` vintage accuracy | Documented current-state claim | SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md | No direct contradiction, but this is documented as a medium concern rather than independently verified gap | Replay precision for monthly macro may not match true publication timestamps. |

---

## 8. Historical vs Canonical Documentation Boundary

| Document | Role | Classification | Conflict / ambiguity note | Notes |
|---|---|---|---|---|
| `README_v1.md` | Entry-point summary for current system state | Canonical current-state document | None | Use first for concise project position and handoff summary. |
| `SYSTEM_TECHNICAL_HANDBOOK_v1.md` | Deep technical reference for current system state | Canonical current-state document | None | Use for structured engineering truth and interim verification status. |
| `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` | Current limitations / approximations / interpretation-risk source | Canonical current-state document | None | Use for blockers, non-blockers, approximations, and AI-safe interpretation rules. |
| `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` | Architecture sequencing, handoff boundary, later-stage gating | Architecture sequencing / boundary source | Must not be treated as implementation proof | Use for sequencing and boundary interpretation, especially bootstrap vs live gate. |
| `SYSTEM_IMPLEMENTATION_RECORD_v1.md` | Long-form build record and retained historical context | Retained historical implementation reference | Not canonical current-state truth if it conflicts with v1 set | Use for historical build detail, audit history, and long-form implementation context. |

---

## 9. High-Risk Misread Areas

1. **Treating planned architecture as implemented reality.**
   `guards`, `reason_code`, `revision_risk`, revision writer, and session-aware execution policy are repeatedly documented as absent / later / not yet implemented. They must not be promoted to current implementation.

2. **Treating bootstrap readiness as live execution readiness.**
   The current docs are explicit that bootstrap and live execution are separate gates. Conflating them would overstate project readiness.

3. **Treating approximations as true historical coverage.**
   GLD proxy data, pre-2014 gold coverage, pre-2016 SP500 coverage, and monthly revision exposure all carry approximation or coverage limits.

4. **Treating repo-hygiene notes as resolved.**
   The `layer2_truth.db` repository-state issue is explicitly open in the current docs and must remain open until re-verified.

5. **Treating current documented status as independent verification.**
   The docs are disciplined, but they also explicitly note that a formal verification matrix did not yet exist until this document. Current-state claims are not equivalent to external certification.

6. **Misusing the implementation record as canonical truth.**
   The implementation record is retained for build history and detail. It is useful, but subordinate to the current v1 set for current-state interpretation.

---

## 10. Reviewer / AI Usage Rules

1. Use `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`, and `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md` as the primary current-state set.
2. Use `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` for sequencing, handoff, and bootstrap-vs-live boundary interpretation — not as implementation proof.
3. Use `SYSTEM_IMPLEMENTATION_RECORD_v1.md` only as retained historical implementation context.
4. Do not claim verification beyond the current documentation evidence.
5. Surface uncertainty explicitly rather than smoothing it over.
6. If two current documents make materially different claims, classify conservatively and record the conflict.
7. Do not convert approximations into verified truth.
8. Do not convert open verification issues into resolved status.
9. Do not treat “documented current-state claim” as independent certification.
10. Treat this matrix as the classification layer for future documentation review and documentation-update automation.
