Based on the full audit with C2 retracted, here is the consolidated final output:

---

# Layer-2 Architecture Audit Report — Final
**Date:** 2026-03-07 | **Auditor:** Software Architecture Review | **Scope:** Layer-2 implementation vs. architecture4.md

---

## Summary

The Layer-2 implementation is technically sound and well-engineered. Registry wiring is complete across all six adapters. The core truth layer — ingestion, alignment, quality gate, and snapshot publishing — is functioning correctly. The primary risks are at the **Layer-2 → Layer-3 contract boundary**: the snapshot schema is missing versioning fields that architecture4.md explicitly requires for replayability and gate version-locking, and several structured guard/governance fields needed by Layer-3 have no Layer-2 representation yet. None of these block continued Layer-2 work, but three must be resolved before Layer-3 development begins or they will require a breaking schema migration against a live contract.

---

## Changes Tracked

Changes documented across the four audit cycles in README_LAYER2.md:

- **Audit 1:** `INSERT OR REPLACE` → `INSERT OR IGNORE` (truth-safety); date type normalization across all adapters; `detect_types` removed (Python 3.12 compatibility); `latest_obs_date()` type safety hardened
- **Audit 2:** `snapshot_id` extended to full 64-char SHA-256; `run_ts` separated from `clock_ts`; `--force` flag introduced; stable API fields added to `latest_snapshot.json`; Tier-1 completeness hard fail added to publisher; `series_registry.json` introduced as single source of truth; `registry.py` loader and validator built
- **Audit 3:** `forced` column added to `snapshots` table and schema; batch hash truncation fixed to full 64-char; documentation corrections (five adapters → six; schema section completed)
- **Audit 4:** `--force` now always runs the real quality gate (hardcoded summary eliminated); GLD source label made consistent across registry, adapter, and README (`spdr_gld_archive`)
- **Registry wiring completed:** All six adapters confirmed reading from `series_registry.json`. README Section 10 to-do list is stale on this point — wiring items marked pending are already done in code.

---

## Alignment Assessment

### Well-aligned

- **Truth-layer discipline:** `INSERT OR IGNORE`, point-in-time `as_of_ts` enforcement, deterministic tie-breaking (`obs_ts DESC, as_of_ts DESC, revision_seq DESC`), and `revision_seq` schema reservation all correctly implement the architecture's "point-in-time correct features; revision-risk tracked" requirement
- **Fail-closed behavior:** Any Tier-1 staleness → no snapshot → Layer-3 receives nothing. Structurally matches the architecture's hard requirement
- **Deterministic snapshot IDs:** Full SHA-256 of `clock_ts` + sorted series values correctly supports the replayability requirement
- **`run_ts` / `clock_ts` separation:** Engine time vs. execution time correctly distinguished in logs, DB, and JSON output
- **Registry as single source of truth:** All six adapters confirmed consuming `series_registry.json` for series metadata, staleness thresholds, tier assignments, and snapshot inclusion rules. No inline hardcoding of series configuration remains
- **Layer-3 contract boundary:** Layer-3 prohibition on reading `observations` directly is structurally enforced — only published `snapshot_id` is the valid consumption interface

### Partially aligned

- **Fail-closed at data level but not operational level:** Adapters return non-zero exit codes on failure but there is no orchestrator-level failure handler, alerting path, or retry cap. Architecture4.md requires "kill switch engaged, alert within 60s, retries capped and idempotent"
- **Idempotency:** DB writes and snapshot deduplication are idempotent. However, `guards.idempotent_ok` from the DecisionPacket contract has no corresponding Layer-2 output
- **Vintage / as-of discipline:** Alignment query correctly enforces point-in-time boundaries. However, `revision_risk` tracking is absent — architecture4.md explicitly requires marking and penalizing revision-exposed series

---

## Discrepancies / Issues

---

### CRITICAL

**C1 — Snapshot schema missing `engine_version` and `config_version`**

Architecture4.md specifies:
```json
"engine_version": "gold-v3.3.0",
"config_version": "cfg-YYYYMMDD"
```
and states gate logic must be version-locked to `engine_version`. Neither field exists in the `snapshots` table or `latest_snapshot.json`. Layer-3 will have no mechanism to version-lock its gate logic or support deterministic replay against a specific config state. Adding these fields after Layer-3 is consuming the snapshot requires a breaking schema change.

The `registry_version` gap identified in Audit 2 but never closed is the natural `config_version` value and should be implemented as part of the same fix.

**Audit note:** Verified by reading `snapshot_publisher.py` (`_write_snapshot`, `write_snapshot_json`) and the `snapshots` DDL in `db.py` — neither contains `engine_version` or `config_version` fields. Cross-checked against architecture4.md DecisionPacket specification.

---

### MAJOR

**M1 — `revision_risk` not tracked; monthly macro series carry unacknowledged revision exposure**

`CPILFESL`, `PCEPI`, and `FEDFUNDS` are ingested with no revision-risk marker. Architecture4.md requires: "if vintage is unavailable: mark `revision_risk=true` and penalize confidence." A Tier-2 staleness warning does not substitute — a freshly released CPI figure still carries revision risk. Layer-3 will have no signal to degrade confidence on these series.

**Audit note:** Verified by reading `db.py` DDL (`_DDL_OBSERVATIONS`) — no `revision_risk` column exists. Verified `fred_loader.py` `build_obs_rows()` — no revision_risk field populated. Cross-checked against architecture4.md vintage discipline requirement.

---

**M2 — `guards` fields are architecturally specified but have no Layer-2 representation**

Architecture4.md specifies a structured `guards` object:
```json
"guards": {
  "data_ok": true,
  "risk_ok": true,
  "cooldown_ok": true,
  "idempotent_ok": true,
  "supervisor_veto": false
}
```
Layer-2 currently outputs `snapshot_ok` (boolean) and `verdict` (string). There is no structured `guards` object. `data_ok` could be derived from `snapshot_ok`, but `idempotent_ok`, `cooldown_ok`, and `risk_ok` have no Layer-2 output at all. Layer-3 cannot evaluate the hard veto conditions from the snapshot alone.

**Audit note:** Verified by reading `write_snapshot_json()` in `snapshot_publisher.py` and the full `latest_snapshot.json` field list in the README — no `guards` object present anywhere.

---

**M3 — SP500 history gap materially affects calibration validity**

SP500 data starts 2016; backtest window starts 2014. The 2015 China shock and early 2016 equity selloff fall in the gap. Architecture4.md requires calibration over an adequate sample including stress periods before thresholds are frozen. A regime model trained without this data will have incomplete stress-period coverage, undermining the calibration validity requirement.

**Audit note:** Verified from README Section 3 DB state table — `SP500` row shows `2016-02-22` as earliest date. Cross-checked against backtest start date `2014-01-02` stated in README Section 5.

---

### MINOR

**m1 — `--full-reload` help text describes deprecated behavior**

The flag previously triggered `INSERT OR REPLACE` and overwrote existing rows. After the Audit 1 fix it now uses `INSERT OR IGNORE` and silently skips them. The help text still implies correction capability. A developer attempting a historical data correction with `--full-reload` will silently fail to apply it.

**Audit note:** Verified by reading `--full-reload` help strings in `fred_loader.py`, `gold_adapter.py`, `gld_holdings_adapter.py`, and `move_adapter.py` — all still describe overwrite behavior.

---

**m2 — `reason_code` enum is specified but never defined**

Architecture4.md states `reason_code` must be enumerated and no free text is permitted at the execution boundary. No enum definition exists in any Layer-2 file, registry, or documentation. Without a defined enum, Layer-3 development will default to free strings under time pressure, directly violating the architecture's no-free-text-at-execution-boundary rule.

---

**m3 — README Section 10 to-do list is stale**

Three registry wiring items marked "⬜ NEXT" are already completed in code. A collaborator reading the README will incorrectly believe these are outstanding. This creates false onboarding risk.

**Audit note:** Verified by reading registry import and usage in all six adapter files — wiring is confirmed complete. README to-do table has not been updated to reflect this.

---

**m4 — `layer1_events` has no interface stub in snapshot output**

Architecture4.md defines Layer-1 as optional and disabled by default but specifies it must produce structured `Event` objects with penalty-only effects. No `layer1_events` field exists in `latest_snapshot.json`. If Layer-1 is ever activated without a pre-defined interface, it risks becoming a free-text path into the decision boundary.

---

**m5 — `UnknownMode` inputs are not exposed in snapshot output**

Architecture4.md defines `UnknownMode` activation criteria (regime confidence below threshold, conflicting signals) and mandates specific behavioral responses. Layer-2 exposes no regime confidence, stress index, drift index, or correlation-break index values in the snapshot. Layer-3 cannot evaluate `UnknownMode` deterministically without these inputs. These belong to the Index Suite (not yet built) but their interface contract should be defined before Layer-3 development starts.

---

## Recommendations (Priority Order)

| Priority | Finding | Action | When |
|---|---|---|---|
| 1 | C1 | Add `engine_version` and `config_version` (= `registry_version`) to `snapshots` table and `latest_snapshot.json` | Before Layer-3 starts |
| 2 | M2 | Add structured `guards` object to snapshot JSON with at minimum `data_ok` and `idempotent_ok` | Before Layer-3 starts |
| 3 | m2 | Define `reason_code` enum in a shared constants file | Before Layer-3 starts |
| 4 | M3 | Bridge SP500 to 2014 via SPY/Yahoo Finance | Before calibration |
| 5 | M1 | Add `revision_risk` boolean to `observations` table; populate for monthly FRED series; propagate to snapshot output | Before Layer-3 consumes macro data |
| 6 | m3 | Update README Section 10 to-do list to mark registry wiring as complete | Housekeeping — immediate |
| 7 | m1 | Fix `--full-reload` help text across all four adapters | Housekeeping |
| 8 | m4 | Add stub `layer1_events: []` to `latest_snapshot.json` | Before Layer-1 interface design |
| 9 | m5 | Document UnknownMode input requirements; add placeholder fields to snapshot when Index Suite is built | Before Index Suite design |

---

**Overall verdict:** Layer-2 is production-quality as a data and truth layer. The architectural risk is concentrated at the snapshot contract boundary. Fixing C1, M2, and m2 before Layer-3 development begins eliminates the highest-cost rework risk. All other findings are addressable incrementally without breaking changes.