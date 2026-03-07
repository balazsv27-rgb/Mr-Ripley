# Layer-2 Architecture Audit Report
**Date:** 2026-03-07 | **Auditor:** Software Architecture Review | **Scope:** Layer-2 implementation vs. architecture4.md

---

## Summary

The Layer-2 implementation is technically solid and well-engineered. The core truth layer — ingestion, alignment, quality gate, and snapshot publishing — is complete and functioning. However, there are meaningful alignment gaps between what architecture4.md specifies and what has been built, most of which stem from Layer-2 being built in relative isolation from the full system contract it is supposed to serve. The most significant concerns are: the snapshot schema does not yet carry the fields Layer-3 will require (engine_version, config_version, reason_code infrastructure); the registry wiring is incomplete and creates silent drift risk; and several architectural safety properties (fail-closed behavior, idempotency guarantees, point-in-time vintage discipline) are partially but not fully implemented.

No findings here block continued development, but three issues should be resolved before Layer-3 is started, or they will require backfilling into an already-live contract boundary.

---

## Changes Tracked (readme_layer2.md — notable since last session)

These are the substantive changes documented in the README's audit log:

- **Audit 1:** `INSERT OR REPLACE` → `INSERT OR IGNORE` (truth-safety fix); date type normalization; `detect_types` removal; `latest_obs_date()` type safety
- **Audit 2:** `snapshot_id` extended to full 64-char SHA-256; `run_ts` separated from `clock_ts`; `--force` flag added; JSON stable API fields added; Tier-1 completeness hard fail added; `series_registry.json` introduced as single source of truth
- **Audit 3:** `forced` column added to `snapshots` table; batch hash truncation fixed to full 64-char; documentation corrections
- **Audit 4:** `--force` now runs real gate (no more hardcoded summary); GLD source label consistency fixed across registry/adapter/README
- **Registry wiring:** Identified as the next mandatory step but not yet completed — `snapshot_publisher.py`, `quality_gate.py`, and `fred_loader.py` still contain inline series lists rather than reading from `series_registry.json`

---

## Alignment Assessment

### What is well-aligned

**Truth layer discipline** is correctly implemented. `INSERT OR IGNORE`, point-in-time `as_of_ts` enforcement, deterministic tie-breaking (`obs_ts DESC, as_of_ts DESC, revision_seq DESC`), and the `revision_seq` schema reservation all match the architecture's "point-in-time correct features; revision-risk tracked" requirement.

**Fail-closed behavior** is structurally correct. Any Tier-1 staleness → no snapshot → Layer-3 gets nothing. This matches the architecture's hard requirement.

**Deterministic snapshot IDs** are correctly implemented as full SHA-256 hashes of clock_ts + sorted series values. This supports the replayability requirement in architecture4.md.

**Separation of `run_ts` and `clock_ts`** is correctly implemented and documented. The architecture distinguishes engine time from execution time and this is now honored.

**Layer-3 contract boundary** is structurally correct: Layer-3 is prohibited from reading `observations` directly and must consume only a published `snapshot_id`. This is the right design.

### What is partially aligned

**Fail-closed is implemented at the data level but not at the operational level.** The architecture specifies a kill switch with "alert within 60s" and "retries capped and idempotent" on unrecoverable failures. The current adapters have try/except blocks that log errors and return non-zero exit codes, but there is no orchestrator-level failure handler, no alerting path, and no retry cap. This is acceptable for now but must exist before any live execution is connected.

**Idempotency is partially implemented.** `INSERT OR IGNORE` makes the DB writes idempotent. The snapshot publisher correctly checks for existing `snapshot_id` before writing. However, the `guards.idempotent_ok` field in the DecisionPacket contract has no corresponding Layer-2 implementation — nothing currently produces or validates this field.

**Vintage / as-of macro discipline** is implemented in the alignment query but `revision_risk` tracking is not. Architecture4.md explicitly requires: "if vintage is unavailable: mark `revision_risk=true` and penalize confidence." The `observations` table has no `revision_risk` column and no adapter populates one. The monthly FRED series (CPI, PCE) are the exact case where this matters — they carry known revision risk and the system currently has no way to communicate that to Layer-3.

---

## Discrepancies / Issues

---

### CRITICAL

**C1 — Snapshot schema does not carry `engine_version` or `config_version`**

Architecture4.md specifies the DecisionPacket must include:
```
"engine_version": "gold-v3.3.0"
"config_version": "cfg-YYYYMMDD"
```
and explicitly states "gate logic must be version-locked to engine_version." The current `snapshots` table and `latest_snapshot.json` carry neither field. Since the snapshot is the contract boundary between Layer-2 and Layer-3, any Layer-3 component consuming it will have no way to version-lock its gate logic or support deterministic replay. Adding these fields after Layer-3 is built will require a breaking schema change.

**Recommendation:** Add `engine_version TEXT` and `config_version TEXT` columns to the `snapshots` table and populate both from environment variables or a versioned constants file before Layer-3 development begins. The registry version (`registry_version`) already identified as missing in Audit 2 should be the `config_version` value.

---

**C2 — Registry wiring is incomplete — three adapters carry independent series lists**

`snapshot_publisher.py`, `quality_gate.py`, and `fred_loader.py` all contain their own inline series configurations. `series_registry.json` exists as the intended single source of truth but is not yet consumed by the two most critical components (gate and publisher). This creates a live drift risk: a registry change will not propagate to the gate or publisher until wiring is complete, meaning the gate can PASS on a series the publisher does not include, or vice versa.

This is documented in the README as "NEXT — do first" but has not been done. Given that the first real snapshot has already been published, any future registry edit that is not immediately reflected in the gate/publisher will silently corrupt the snapshot contract.

**Recommendation:** Complete registry wiring for `quality_gate.py` and `snapshot_publisher.py` before publishing any more production snapshots. The `fred_loader.py` wiring is lower urgency (it affects ingestion, not the contract boundary) but should follow immediately after.

---

### MAJOR

**M1 — `revision_risk` not tracked; monthly macro series carry unacknowledged revision exposure**

CPI (`CPILFESL`), PCE (`PCEPI`), and `FEDFUNDS` are in the DB but carry no revision-risk marker. Architecture4.md explicitly requires revision risk to be tracked and to trigger confidence penalties. A Tier-2 warning for staleness does not substitute for revision-risk flagging — a fresh CPI reading can still carry high revision risk if it was just released. Layer-3 will have no signal to degrade confidence on these series unless this is implemented.

**Recommendation:** Add a `revision_risk` boolean column to `observations` (default false, not a breaking change). Populate it as `true` for monthly FRED macro series at ingestion time. Expose it in `snapshot_values` and `latest_snapshot.json`. Separately, add `is_estimate` to snapshot values for the GLD series (registry already has this field; it is not currently propagated to the snapshot output).

---

**M2 — `guards` fields are architecturally specified but have no Layer-2 implementation**

The DecisionPacket specifies:
```json
"guards": {
  "data_ok": true,
  "risk_ok": true,
  "cooldown_ok": true,
  "idempotent_ok": true,
  "supervisor_veto": false
}
```
Layer-2 currently produces `snapshot_ok` (a boolean) and a `verdict` string. There is no structured `guards` object in any output. When Layer-3 is built, it will need to evaluate these guards against the Layer-2 snapshot, but the snapshot does not provide the necessary structured inputs. `data_ok` could be derived from `snapshot_ok`, but `idempotent_ok`, `cooldown_ok`, and `risk_ok` have no corresponding Layer-2 output at all.

**Recommendation:** Add a `guards` object to `latest_snapshot.json` with at minimum `data_ok` (derived from `snapshot_ok`) and `idempotent_ok` (derived from whether a snapshot for this `clock_ts` already existed). The remaining guards belong in Layer-3 but their interface contract should be defined now.

---

**M3 — SP500 history gap is architecturally significant, not just a data gap**

The README notes SP500 only goes back to 2016 and flags it as a known issue. This matters architecturally because architecture4.md requires "deterministic replay" and "calibration criteria met before thresholds are frozen." The backtest start date is 2014; SP500 data starts 2016. Any regime model trained on pre-2016 data will be missing equity stress context. The 2015 China shock and early 2016 selloff are in the gap. This is not a minor data issue — it affects calibration validity.

**Recommendation:** Prioritize SPY via Yahoo Finance as a bridge before Layer-3 calibration begins. This is already noted in the README but should be escalated from "Medium" to "High" priority given its impact on calibration validity.

---

### MINOR

**m1 — `--full-reload` CLI help text describes deprecated behavior**

Documented in Audit 1 as a known remaining item. The flag previously used `INSERT OR REPLACE` and now uses `INSERT OR IGNORE`, meaning it no longer corrects existing values. The help text still implies it does. This is a usability hazard that could lead to a developer attempting a data correction with `--full-reload` and silently failing to apply it.

**Recommendation:** Update help text to: "Backfills missing rows in the requested date range. Does NOT overwrite existing rows — use `revision_seq=1` writes for corrections (not yet implemented)."

---

**m2 — `reason_code` is specified as ENUM_ONLY in the DecisionPacket but no enum is defined anywhere**

Architecture4.md states `reason_code` must be enumerated and no free text is permitted at the execution boundary. No enum definition exists in any Layer-2 file, registry, or documentation. When Layer-3 is built, the temptation will be to use free strings — and the architecture's constraint will have no enforcement mechanism.

**Recommendation:** Define the `reason_code` enum in a shared constants file now, even if it only contains placeholder values. This prevents free-text creep when Layer-3 is under time pressure.

---

**m3 — Layer-1 (Event Tagger) has no interface definition**

Architecture4.md defines Layer-1 as optional and disabled by default but specifies it must produce structured `Event` objects with enumerated types, and that its effects are penalty-only (raise uncertainty, trigger cooldown, add research tags). There is currently no `Event` schema, no interface definition, and no placeholder in the snapshot or registry for Layer-1 event hooks. This is low urgency since Layer-1 is disabled by default, but if it is ever activated without a defined interface, it risks becoming a free-text path into the decision boundary — exactly what the architecture prohibits.

**Recommendation:** Add a stub `layer1_events: []` field to `latest_snapshot.json` now so Layer-3 has a defined (empty) interface to code against. Define the `Event` schema in a constants or schema file.

---

**m4 — `UnknownMode` has no Layer-2 representation**

Architecture4.md defines `UnknownMode` with specific activation criteria (regime confidence below threshold, conflicting signals) and behavioral requirements (confidence floored to 0, uncertainty forced to U_max, directional execution prohibited). Layer-2 has no concept of `unknown_mode` in its outputs. The snapshot does not expose regime confidence or any input that would allow Layer-3 to evaluate UnknownMode activation deterministically.

This is not a Layer-2 implementation gap per se — UnknownMode is a Layer-3 concept — but Layer-2 needs to expose the right inputs (particularly index values once the Index Suite is built) for Layer-3 to evaluate it. This should be designed now before Layer-3 starts.

**Recommendation:** Document the expected Layer-2 inputs for UnknownMode evaluation in the Layer-3 interface spec. At minimum: stress index value, drift index value, and correlation-break index value should appear in the snapshot when the Index Suite is built.

---

## Recommendations (Priority Order)

1. **Before next snapshot is published:** Complete registry wiring for `quality_gate.py` and `snapshot_publisher.py` (C2). Run `python -m layer2.config.registry --validate` after each change.

2. **Before Layer-3 development begins:** Add `engine_version` and `config_version` to the `snapshots` table and `latest_snapshot.json` (C1). This is a breaking schema change if done after Layer-3 is consuming the snapshot.

3. **Before Layer-3 development begins:** Add structured `guards` object to snapshot output (M2) and define the `reason_code` enum in a shared constants file (m2).

4. **Before calibration begins:** Bridge SP500 history to 2014 using SPY via Yahoo (M3). Escalate from Medium to High priority.

5. **Before Layer-3 consumes macro series:** Add `revision_risk` column to `observations` and propagate to snapshot output (M1). Add `is_estimate` propagation for GLD series.

6. **Housekeeping (anytime):** Fix `--full-reload` help text (m1). Add stub `layer1_events: []` to snapshot JSON (m3). Document UnknownMode input requirements for Layer-3 interface spec (m4).

---

*Overall assessment: Layer-2 is production-quality as a data layer. The architectural risk is not in what was built but in what the snapshot contract is missing before Layer-3 consumes it. Fix C1 and C2 first — everything else can follow iteratively.*