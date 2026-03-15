# Known Gaps and Approximations
## Mr. Ripley — Layer-2 Truth Layer

> **Last updated:** 2026-03-15
> **Primary sources:** `README_v1.md`, `SYSTEM_TECHNICAL_HANDBOOK_v1.md`
> **Supporting sources:** `SYSTEM_IMPLEMENTATION_RECORD_v1.md`, `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`

---

## 1. Why This Document Exists

Layer-2 is usable as a truth-layer foundation, but it is not a fully hardened system. Several real gaps, accepted approximations, and operational incomplete items exist in the current documented state.

This document separates:

- **Verified current-state behavior** — what is documented as working in the current codebase
- **Known limitations** — things that exist but are incomplete, incorrect for some use cases, or silently dropping data
- **Accepted approximations** — estimates that are deliberately used in place of unavailable verified truth; these are not bugs but must be labeled clearly in any backtest or calibration output
- **Future work** — items not yet built; must not be treated as implemented
- **Bootstrap blockers** — items that block Layer-3 core development from starting
- **Live-execution blockers** — items that block connecting any live execution path, but do NOT block Layer-3 bootstrap

> **Critical framing rule:** Do not equate current documented status with fully hardened, independently verified truth. The project's own documentation and audit log are the source of current-state claims — not an external verification matrix.

> **Canonical interim verification status:** until a formal verification matrix exists, see `SYSTEM_TECHNICAL_HANDBOOK_v1.md` §14 ("Verification Status") for the current repo-hygiene and doc/code-sync status.

---

## 2. High-Priority Bootstrap Blockers

These were the original Layer-3 bootstrap blockers. As of the 2026-03-15 documentation refresh, the contract-side blockers below are **implemented**. The current blocker for publishing a fresh compliant snapshot is operational data freshness, not snapshot-contract shape.

| Item | Why it mattered | Current status | Notes |
|---|---|---|---|
| `guards` structured object in snapshot JSON | Layer-3 evaluates hard veto conditions (`data_ok`, `idempotent_ok`, `cooldown_ok`, `risk_ok`, `supervisor_veto`) from this field | ✅ Implemented | Present in `snapshot_publisher.py` output via `build_guards()` |
| `reason_code` enum in shared constants | Layer-3 must emit only enumerated reason codes; no free text permitted at the execution boundary | ✅ Implemented | Present in `layer2/constants.py`; validation rejects free text |
| `layer1_events: []` stub | Forward-compatible slot for future Layer-1 integration | ✅ Implemented | Present in snapshot JSON; Layer-2 always emits `[]` |
| README / handbook / architecture contract sync | Contract must be documented consistently before handoff | ✅ Refreshed | Current v1 docs updated on 2026-03-15 to reflect observed implementation |

---

## 3. High-Priority Non-Blockers

These items do not block Layer-3 bootstrap but materially affect calibration quality, data trust, or replay correctness. They should be resolved in parallel after the bootstrap gate passes.

| Item | Why it matters | Affected area | Current status |
|---|---|---|---|
| Latest publish attempt blocked by stale Tier-1 data (2026-03-15) | Gold, MOVE, multiple FRED Tier-1 series, and VIX/SP500 were stale at the current clock boundary; no fresh compliant snapshot can be published until ingestion is refreshed | Daily operations | ⬜ Open operational blocker |
| `DTWEXBGS` missing point-in-time value at latest dry run | Distinct from simple staleness: quality gate reported no point-in-time data available by `clock_ts` | Alignment / ingestion verification | ⬜ Open operational blocker |
| SP500 history gap (2014–2016) | FRED data starts 2016-02-22; backtest window needs 2014-01-02; the 2015 China shock and early 2016 selloff are entirely missing from the calibration window | Calibration validity | ⬜ Not fixed — fix via SPY/Yahoo planned |
| `revision_risk` column not in `observations` | Monthly FRED series (CPI, PCE, FEDFUNDS) carry real revision exposure that is not tracked or signaled downstream; confidence penalties that should be applied are silently omitted | Vintage correctness, downstream trust | ⬜ Not yet implemented |
| Revision writer (`revision_seq=1`) not built | If FRED revises a historical value, the current system silently drops the correction; rev-0 is immutable but no mechanism exists to record the revision | Vintage correctness, data accuracy | ⬜ Not yet built |
| Gold history starts 2014-01-02 | Target coverage is 2005; the 2008 financial crisis and 2011 gold peak are entirely missing from the available calibration window | Calibration validity | ⬜ Backfill via Stooq planned |

---

## 4. Known Approximations

These are accepted estimates deliberately used in place of unavailable verified truth. They are not implementation defects. They must be labeled explicitly in any backtest, calibration, or analysis output that relies on them.

| Item | Series / Scope | What the approximation is | Why it is accepted | Impact if misread as truth |
|---|---|---|---|---|
| GLD holdings | `gld_holdings_flow_confirm` (Tier-2) | `ounces = shares_outstanding × 0.09585` — current Yahoo-reported `shares_outstanding` applied uniformly to all requested historical dates; not true per-day historical values | SPDR State Street CSV endpoint now returns PDF; yfinance is the reliable replacement; GLD shares outstanding changes slowly; large deviations are the signal, not micro-movements | A backtest treating GLD ounces as historically accurate per-day data would be using fabricated precision; the signal is approximate by construction |
| Gold price history start | `gold_price_proxy` (Tier-1) | Backfill begins 2014-01-02; this is the earliest available data from the local JSON source | Stooq rate limits make full re-fetch impractical; JSON provides 3,132 verified daily rows | Any regime or feature calculation requiring pre-2014 gold data will be missing; 2008 crisis and 2011 peak are excluded |
| SP500 history start | `SP500` (Tier-1) | FRED data begins 2016-02-22; this is an upstream FRED limitation | No alternative source has been wired yet; fix via SPY/Yahoo is planned | Calibration window missing two years of stress events; any model trained on full history pre-2016 will have incomplete equity context |
| Monthly macro series revision exposure | `CPILFESL`, `PCEPI`, `FEDFUNDS` (Tier-2) | FRED may revise these series after initial publication; `revision_risk` is not tracked in the `observations` table; downstream confidence penalty is not applied | Revision writer not yet built; `revision_seq=1` path is schema-reserved but unimplemented | A consumer treating these monthly series as point-in-time correct final values may be using pre-revision data without knowing it |

---

## 5. Data Coverage Limitations

These are gaps in historical data coverage. They differ from approximations in that the data does not exist in the current system — it is absent, not estimated.

| Series / Area | Gap | Date range affected | Severity | Notes |
|---|---|---|---|---|
| SP500 (`SP500`) | FRED source only goes back to 2016-02-22; backtest window starts 2014-01-02 | 2014-01-02 → 2016-02-21 | **High** | 2015 China shock and early 2016 equity selloff are missing; affects regime and stress calibration |
| Gold price (`gold_price_proxy`) | Backfill JSON starts 2014-01-02; target coverage is 2005 | 2005-01-01 → 2013-12-31 | Medium | 2008 financial crisis and 2011 gold peak not in calibration window |
| MOVE Index (`rates_vol_stress_move`) | History starts 2021-03-06 | Pre-2021 | Medium | Limited bond stress history; no 2018 rate shock, no 2020 COVID spike |
| GLD holdings (`gld_holdings_flow_confirm`) | History starts 2021-03-08 | Pre-2021 | Low | Tier-2 confirmation signal; approximate anyway |
| Discontinued USD series | `DTWEXM`, `DTWEXO`, `TWEXB` — all discontinued 2019–2020; still present in DB | Post-discontinuation | Low | These rows exist in the observations table but are no longer updated; bridge to `DTWEXBGS` or drop |
| `DTWEXBGS` publish lag | FRED publishes this series with a structural ~1 week lag | Ongoing | Low — handled | Staleness threshold set to 10 days to absorb this; not a defect, documented behavior |

---

## 6. Revision / Vintage Limitations

These gaps affect the temporal correctness of the observation store and the ability to handle data revisions.

| Item | What is missing | Consequence | Current status |
|---|---|---|---|
| `revision_risk` column | No column in `observations` to flag that a series row carries revision exposure | Downstream consumers (Layer-3 feature builder, calibration) have no signal that a value may be superseded by a FRED revision; confidence penalties required by `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` vintage discipline cannot be applied | ⬜ Not yet implemented — column must be added and populated for FRED monthly series |
| Revision writer (`revision_seq=1` path) | The `observations` table schema reserves `revision_seq` for future revisions; the write path for `rev=1` corrections does not exist | If FRED revises a monthly series value (common for CPI, PCE), the correction is silently dropped; the original `rev=0` row remains as the only record, with no indication it may be superseded | ⬜ Not yet built — FRED corrections are currently silently dropped |
| `as_of_ts` vintage for monthly macro | Monthly macro series are ingested with `as_of_ts` set to the ingestion time, not the BLS/BEA publication timestamp | Point-in-time alignment for replays of monthly macro data may not accurately reflect when the value was publicly known | Medium concern — current practice is documented but not validated against true publication timestamps |

---

## 7. Operational Gaps

These items do not block Layer-3 bootstrap. They block connecting any live execution path and affect day-to-day operational reliability.

| Item | What is missing | Consequence | Current status |
|---|---|---|---|
| No end-to-end orchestrator | No single script runs the full pipeline (ingest → gate → publish) sequentially | Pipeline is run manually step by step; no automated fail-fast on partial failures | ⬜ Not yet built |
| No daily scheduler | No scheduled task triggers the daily EOD pipeline | Daily data updates and snapshot publication are manual | ⬜ Not yet built |
| No alerting / notification | No alert is sent when an adapter fails, a quality gate fails, or a snapshot is blocked | Failures are silent unless the operator actively checks logs | ⬜ Not yet built |
| No retry logic with cap | No capped idempotent retry mechanism for failed adapter runs | A transient source failure leaves data stale with no recovery path | ⬜ Not yet built |
| No kill switch | No fail-closed kill switch for the pipeline | Required before any live execution path is connected; failure mode is undefined without it | ⬜ Not yet built |
| `layer2_truth.db` repo-hygiene issue | `layer2_truth.db` is documented as gitignored but was observed committed to the repository as of 2026-03-07 | Open inconsistency between documented intent and observed repo state; not yet resolved or confirmed fixed | ⬜ Open — verify `.gitignore` is correctly applied |
| `--full-reload` help text stale | The `--full-reload` CLI flag help text describes deprecated `INSERT OR REPLACE` behavior; actual behavior is now `INSERT OR IGNORE` | A developer reading the help text may believe they can overwrite existing rows; they cannot | ⬜ Low — documentation fix needed |

---

## 8. Bootstrap vs Live-Execution Classification

| Item | Blocks Layer-3 bootstrap | Blocks live execution | Does NOT block either |
|---|---|---|---|
| `guards` object absent from snapshot JSON | ✅ Yes | — | — |
| `reason_code` enum not defined | ✅ Yes | — | — |
| README/code sync not confirmed | ✅ Yes | — | — |
| SP500 history gap (2014–2016) | — | — | ✅ Does not block either — affects calibration quality only |
| `revision_risk` not tracked | — | — | ✅ Does not block either — affects confidence penalty accuracy |
| Revision writer not built | — | — | ✅ Does not block either — FRED corrections silently dropped |
| Gold history gap (pre-2014) | — | — | ✅ Does not block either — affects calibration window |
| `layer1_events: []` stub absent | — | — | ✅ Optional — recommended before bootstrap; not a hard blocker |
| No end-to-end orchestrator | — | ✅ Yes (operational hardening) | — |
| No daily scheduler | — | ✅ Yes | — |
| No alerting / notification | — | ✅ Yes | — |
| No retry logic with cap | — | ✅ Yes | — |
| No kill switch | — | ✅ Yes | — |
| MOVE history limited (from 2021) | — | — | ✅ Does not block either — calibration coverage gap only |
| Discontinued USD series in DB | — | — | ✅ Does not block either — data hygiene issue |
| `--full-reload` help text stale | — | — | ✅ Does not block either — documentation fix only |
| `layer2_truth.db` repo state | — | — | ✅ Does not block either — repo hygiene verification issue |
| `revision_risk` column absent from `observations` | — | — | ✅ Does not block either — affects vintage correctness and downstream confidence |
| Monthly macro `as_of_ts` vintage accuracy | — | — | ✅ Does not block either — affects replay precision |

---

## 9. Safe Interpretation Rules for Humans and AI

**Read these before drawing conclusions about Layer-2 state.**

1. **Approximations are not verified historical truth.** GLD ounces, gold price history (pre-2014), SP500 history (pre-2016), and monthly macro series all carry explicit approximation or coverage limitations. Label them in any backtest or calibration output.

2. **Planned fixes are not implemented fixes.** Items marked "planned" or "not yet built" in this document do not exist in the current system. Do not treat a documented plan as a completed implementation.

3. **Bootstrap readiness is not live execution readiness.** The Layer-3 bootstrap gate and the live execution gate are separate. Passing the bootstrap gate does not mean operational readiness, paper validation, calibration, or kill switch testing are complete. They are explicitly not.

4. **Current documented status is not independent certification.** The current-state claims in project documentation reflect the project's own audit log and review process — not an externally verified implementation matrix. A future line-by-line verification matrix would be the appropriate place to formally confirm individual claims.

5. **`guards`, `reason_code`, and `layer1_events` are now present in the contract.** The remaining immediate risk is not contract shape but current data freshness: a new snapshot still cannot be published while Tier-1 data is stale.

6. **Revision exposure is unacknowledged in monthly macro series.** CPI, PCE, and FEDFUNDS may have been revised by FRED after ingestion. No flag in the system marks these rows as revision-exposed. Downstream confidence penalties that the architecture requires are not yet applied.

7. **FRED corrections are silently dropped.** If FRED revises a historical value, the current system does not record the correction. The original `rev=0` row remains as the sole observation for that date, with no indication a revision exists.

8. **`layer2_truth.db` repo state is an open verification issue.** The file is documented as gitignored but was observed committed to the repository as of 2026-03-07. This has not been confirmed resolved; see `SYSTEM_TECHNICAL_HANDBOOK_v1.md` §14 ("Verification Status") for the current interim status.

9. **Do not query `observations` directly from Layer-3.** The only permitted interfaces are the `snapshots` + `snapshot_values` DB tables (via `snapshot_id`) or `latest_snapshot.json`. Direct observation access bypasses the quality gate and the versioned contract.

10. **`forced=True` snapshots are non-compliant.** Any snapshot published with `--force` is permanently marked `forced=True`. These must be filtered out of backtests, calibration runs, and replay analysis.

---

*For current-state system behavior, see `README_v1.md` and `SYSTEM_TECHNICAL_HANDBOOK_v1.md`.
For architecture sequencing and later-stage gating, see `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md`.*
