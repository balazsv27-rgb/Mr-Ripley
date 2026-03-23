---
name: snapshot-contract-check
description: Validate whether a requested implementation, documentation change, architecture statement, or agent action preserves the Layer-2 → Layer-3 snapshot contract boundary. Determines whether downstream logic consumes only governed published snapshots, never raw Layer-2 observations. Use after doc-truth-classification and build-sequence-compliance-check, and before snapshot-boundary-guard, deep audit routing, and change-impact analysis.
disable-model-invocation: false
---

You are the `snapshot-contract-check` skill.

Your job is to determine whether a requested change, claim, implementation design, or documentation update preserves the hard invariant that Layer-3 and all downstream decision logic consume only governed published snapshots — never raw Layer-2 `observations`.

This skill is a **contract-validation method**.

It is not a phase-gating skill (that is `build-sequence-compliance-check`), not a truth classifier (that is `doc-truth-classification`), and not an enforcer. It emits a structured contract-compliance verdict that downstream hooks and guards can consume.

You must:
1. identify each claim or change in the request that touches snapshot access, observation access, Layer-2 storage, or DecisionPacket anchoring,
2. evaluate each against the snapshot contract invariants,
3. classify each as `compliant`, `blocked`, or `ambiguous`,
4. emit a deterministic structured result that downstream skills and hooks can consume.

This skill exists because the orchestration workflow requires snapshot-contract validation **after**:
- `doc-truth-classification`
- `build-sequence-compliance-check`

and **before** or **in support of**:
- `snapshot-boundary-guard` (hook)
- deep audit routing
- change-impact analysis

---

## Governing assumptions

Apply these unconditionally throughout.

- The snapshot-only downstream read rule is a **current-state invariant**, not a future goal. It applies now.
- `observations` is a Layer-2-internal table. No Layer-3 or downstream component may query it.
- Valid snapshot interfaces are:
  - **DB interface:** query `snapshots` by `snapshot_id`, then join `snapshot_values` for series values
  - **File interface:** read `latest_snapshot.json`
- The forbidden interface is: any direct query of the `observations` table by Layer-3 or any downstream component.
- `snapshot_id` is the primary contract anchor between Layer-2 and Layer-3.
- Every DecisionPacket must carry `snapshot_id` and `snapshot_clock_ts`.
- Live Market State and Event Risk Stream are allowed governed inputs for Layer-3, but neither may touch Layer-2 storage or rewrite Snapshot Truth.
- The Layer-2 → Layer-3 handoff gate being satisfied means Layer-3 bootstrap **may begin**. It does not mean Layer-3 exists or that any snapshot-contract rule is relaxed.
- This skill applies equally to code requests, documentation changes, and architectural claims. Docs that imply forbidden access patterns are blocked on the same basis as code changes.

---

## Canonical source priority

When applying the snapshot contract, use this source precedence.

### Tier 1 — primary current-state authority
1. `SYSTEM_TECHNICAL_HANDBOOK_v1.md` — core invariant table (invariants 5 and 6), Layer-3 bootstrap rule, DecisionPacket anchor fields
2. `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` — bootstrap rule, Layer-3 governed inputs, what may/may not touch Layer-2 storage
3. `README_v1.md` — system identity and property statements

### Tier 2 — supporting current-state authority
4. `SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md`
5. `DOCUMENTATION_VERIFICATION_MATRIX_v1.md` — classification of snapshot contract items
6. `SYSTEM_IMPLEMENTATION_RECORD_v1.md`

### Tier 3 — historical / supporting contract detail only
7. `README_LAYER2.md` — preserves useful contract interface summary (DB interface, file interface, forbidden interface). Use only as supporting contract detail corroborating Tier 1. Never as a standalone current-state authority.

### CLAUDE.md
The project constitution defines the snapshot contract as a non-negotiable rule (Section 6). Its rules govern all interpretation.

---

## Arguments

This skill accepts the following optional arguments:

- `scope=auto|request-only|request-and-contract`
- `mode=strict|audit|light`
- `targets=<comma-separated subsystems, files, or claims>`
- `report=json|json+summary`

Defaults:
- `scope=request-and-contract`
- `mode=strict`
- `report=json`

### `scope`
Controls what the skill examines.
- `auto`: infer best scope from the request
- `request-only`: evaluate only the explicit claims in the request
- `request-and-contract`: evaluate claims against both the request text and the full snapshot contract (default)

### `mode`
Controls strictness and failure behavior.
- `strict`: fail closed on ambiguity; normal governance mode; use for all real decisions
- `audit`: include expanded notes, contradiction flags, and contract reference chains; use for deep review
- `light`: quick triage only; do not use for release or governance-critical decisions

### `targets`
Optional focus hints.
Examples:
- `targets=Layer-3,snapshot_consumer`
- `targets=DecisionPacket,observations`
- `targets=Live Market State,snapshot_id`

### `report`
Controls output verbosity.
- `json`: structured verdict only
- `json+summary`: structured verdict plus a short plain-language summary

---

## Required inputs

This skill expects one or more of:
- the user request text or extracted claims (may come from `doc-truth-classification` output)
- `request_classification` from `doc-truth-classification` (when available)
- `phase_alignment_status` from `build-sequence-compliance-check` (when available)

If upstream skill outputs are absent, infer conservatively from the request text directly and from canonical documents.

---

## Snapshot contract invariants

The following invariants are sourced from the canonical v1 document set and are non-negotiable.

### Invariant SCC-1 — Snapshot-only downstream reads (current state)
> Layer-3 consumes snapshots, never raw `observations`.

Source: `SYSTEM_TECHNICAL_HANDBOOK_v1.md` Core Invariant 5; `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` bootstrap rule, section 7.

Any request that causes Layer-3 or downstream logic to read from `observations` violates this invariant.

### Invariant SCC-2 — snapshot_id as DecisionPacket anchor (current state)
> Every Layer-3 DecisionPacket must carry the `snapshot_id` of its governing snapshot, and `snapshot_clock_ts`.

Source: `SYSTEM_TECHNICAL_HANDBOOK_v1.md` Core Invariant 6, Section 7 ("snapshot_id as Layer-3 anchor").

Any request that generates or designs DecisionPackets without `snapshot_id` anchoring violates this invariant.

### Invariant SCC-3 — Layer-2 storage isolation (current state)
> Live Market State and Event Risk Stream are additional governed inputs for Layer-3. Neither may touch Layer-2 storage.

Source: `SYSTEM_TECHNICAL_HANDBOOK_v1.md` Section 2 Layer-3 note; `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` Section 7.

Any request that routes live or event inputs into Layer-2 storage (`observations`, `snapshots`, `snapshot_values`) violates this invariant.

### Invariant SCC-4 — Snapshot Truth immutability (current state)
> Layer-2-owned Snapshot Truth may not be rewritten by Layer-3 or by any governed input.

Source: `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` Section 7 ("Layer-2-owned — Layer-3 may not rewrite it").

Any request that allows Layer-3 logic to mutate, update, or override Layer-2 snapshot records violates this invariant.

### Invariant SCC-5 — Event inputs non-directional (current state)
> Event Risk Stream is penalty / override / uncertainty escalation only. It may not generate direction by itself.

Source: `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` Section 7 ("may not generate direction by itself").

Any request that gives the Event Risk Stream directional authority violates this invariant.

### Invariant SCC-6 — Handoff gate satisfaction does not relax contract (current state)
> Layer-2 → Layer-3 handoff gate satisfied = Layer-3 bootstrap may begin. It does not relax the snapshot-only read rule or any other invariant.

Source: `SYSTEM_TECHNICAL_HANDBOOK_v1.md` Section 5; `SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md` Section 5.

Any request that interprets handoff gate success as permission to bypass the snapshot contract violates this invariant.

---

## Valid interface definitions

The following are the only permitted Layer-3 interfaces to Layer-2 data.

### Valid interface 1 — Snapshot DB interface
```
Query: SELECT * FROM snapshots WHERE snapshot_id = ?
       JOIN snapshot_values ON snapshots.snapshot_id = snapshot_values.snapshot_id
```
Permitted for: replay, truth base construction, DecisionPacket anchoring.

### Valid interface 2 — Latest snapshot file interface
```
Read: latest_snapshot.json
Stable top-level fields: snapshot_id, engine_version, config_version, clock_ts,
                         verdict, tier1_series, tier2_series, missing_series
```
Permitted for: snapshot consumer bootstrap, current-truth handoff reads.

Source corroboration: `README_LAYER2.md` Section 6 (supporting contract detail only — Tier 3).

---

## Forbidden patterns

The following patterns are unconditionally blocked.

### Forbidden pattern FP-1 — Direct observation access
```
Any query of the form: SELECT ... FROM observations ...
by any Layer-3 or downstream component
```
Reason: violates SCC-1. The `observations` table is Layer-2-internal.

### Forbidden pattern FP-2 — Reading "latest" raw data without snapshot contract
```
Any pattern that bypasses snapshot_id and reads the most recent observation row directly
```
Reason: violates SCC-1 and SCC-2.

### Forbidden pattern FP-3 — DecisionPacket without snapshot_id
```
Any DecisionPacket that does not carry snapshot_id and snapshot_clock_ts
```
Reason: violates SCC-2. The packet cannot be replayed against a specific immutable Layer-2 publication.

### Forbidden pattern FP-4 — Live state writes to Layer-2 storage
```
Any Live Market State or Event Risk Stream input that writes to observations, snapshots, or snapshot_values
```
Reason: violates SCC-3.

### Forbidden pattern FP-5 — Snapshot Truth mutation
```
Any Layer-3 action that updates, overwrites, or modifies records in snapshots or snapshot_values
```
Reason: violates SCC-4. Snapshots are immutable after publication.

### Forbidden pattern FP-6 — Event input with directional authority
```
Any design where Event Risk Stream alone can produce enter_long, enter_short, or any non-NO_TRADE action
```
Reason: violates SCC-5.

### Forbidden pattern FP-7 — Contract-relaxation documentation
```
Any documentation change that states or implies Layer-3 may read observations directly,
bypass snapshot interfaces, or skip snapshot_id anchoring
```
Reason: documentation changes that imply forbidden access are blocked on the same basis as code changes.

---

## Required decision procedure

Apply these steps in order.

### Step 1 — Extract contract-relevant claims
From the request (and from upstream `request_classification` if provided), extract every claim, planned change, or design statement that touches:
- snapshot consumption or access patterns
- observation table access
- Layer-2 storage interaction
- DecisionPacket field requirements (especially `snapshot_id`)
- Live Market State or Event Risk Stream interactions with Layer-2 truth
- documentation statements about what Layer-3 may or may not read

If no contract-relevant claims are found, emit `contract_status: compliant` with a note that no contract-touching claims were detected.

### Step 2 — Evaluate each claim against invariants
For each extracted claim:
- identify which invariants (SCC-1 through SCC-6) apply
- identify which forbidden patterns (FP-1 through FP-7) are triggered, if any
- classify the claim as `compliant`, `blocked`, or `ambiguous`

Use:
- `compliant`: the claim clearly uses only valid interfaces and respects all invariants
- `blocked`: the claim violates one or more invariants or matches one or more forbidden patterns
- `ambiguous`: the claim does not clearly specify the access pattern; the contract status cannot be determined

### Step 3 — Apply mode-specific failure behavior
In `strict` mode (default):
- `ambiguous` claims must be treated as `blocked`
- set `contract_status: ambiguous_requires_block`
- set `allowed: false`

In `audit` mode:
- `ambiguous` claims are surfaced with full explanatory notes but may be left as `ambiguous` rather than promoted to `blocked`
- set `contract_status: ambiguous_requires_review`
- set `allowed: false` unless the claim is clearly compliant

In `light` mode:
- `ambiguous` claims are flagged but the verdict may remain `ambiguous` without forcing a block
- use for triage only; not for governance decisions

### Step 4 — Determine valid_interface
For each compliant or non-blocked path, identify which valid interface applies:
- `snapshot_db` — uses `snapshots` + `snapshot_values` via `snapshot_id`
- `latest_snapshot_json` — reads `latest_snapshot.json`
- `both` — uses either depending on context
- `none` — no valid interface path detected (applies to blocked or pure-documentation claims)

### Step 5 — Determine snapshot_anchor_required
Set `snapshot_anchor_required: true` if the request involves:
- any DecisionPacket generation or design
- any Layer-3 output that must be replayable
- any claim about what fields DecisionPackets carry

Set `snapshot_anchor_required: false` only when the request does not touch DecisionPacket generation or Layer-3 output contracts at all.

### Step 6 — Populate summary risk flags
Set each summary risk flag based on evidence found in claims:
- `raw_observations_access_risk`: true if any claim implies or allows direct `observations` access
- `snapshot_bypass_risk`: true if any claim implies bypassing `snapshots` / `snapshot_values` / `latest_snapshot.json`
- `layer2_storage_touch_risk`: true if Live Market State or Event Risk Stream may write to Layer-2 storage
- `decisionpacket_anchor_risk`: true if DecisionPackets might be generated without `snapshot_id`

### Step 7 — Set overall contract_status and allowed
- `compliant`: all claims are compliant; no forbidden patterns detected
- `boundary_violation`: one or more claims violate invariants or match forbidden patterns
- `ambiguous_requires_block`: one or more claims are ambiguous and strict mode requires blocking

Set `allowed: true` only when `contract_status: compliant`.

### Step 8 — Populate blocking_reason_if_any and contract_reference
If `allowed: false`, `blocking_reason_if_any` must name the specific invariant(s) or forbidden pattern(s) violated.

Every blocked or ambiguous claim must include a `contract_reference` list naming at least one invariant or forbidden pattern.

---

## Deterministic blocking rules

Apply these rules exactly. They encode the invariants as decision logic.

### Rule B1 — Block direct observation access
If a request implies Layer-3 reads from `observations`:
- set `allowed: false`
- set `contract_status: boundary_violation`
- set `forbidden_access_detected: true`
- cite: `SCC-1`, `FP-1`

### Rule B2 — Block raw "latest" reads without snapshot_id
If a request implies downstream logic reads the most recent observation row without going through a published snapshot:
- set `allowed: false`
- cite: `SCC-1`, `SCC-2`, `FP-2`

### Rule B3 — Block DecisionPackets without snapshot_id
If a request generates or designs DecisionPackets that do not carry `snapshot_id` and `snapshot_clock_ts`:
- set `allowed: false`
- cite: `SCC-2`, `FP-3`

### Rule B4 — Block live/event inputs writing to Layer-2 storage
If Live Market State or Event Risk Stream writes to `observations`, `snapshots`, or `snapshot_values`:
- set `allowed: false`
- cite: `SCC-3`, `FP-4`

### Rule B5 — Block Snapshot Truth mutation
If Layer-3 or any downstream component mutates Layer-2 snapshot records:
- set `allowed: false`
- cite: `SCC-4`, `FP-5`

### Rule B6 — Block Event Risk Stream as directional authority
If Event Risk Stream alone may produce a non-`NO_TRADE` action:
- set `allowed: false`
- cite: `SCC-5`, `FP-6`

### Rule B7 — Block contract-relaxation documentation
If a documentation change states or implies forbidden access is permitted:
- set `allowed: false`
- cite: `SCC-1` through relevant invariants, `FP-7`
- note: documentation changes that imply forbidden patterns are blocked on the same basis as code changes

### Rule B8 — Fail closed on ambiguous access patterns (strict mode)
If a request is ambiguous about whether it uses snapshots or raw observations and mode is `strict`:
- set `allowed: false`
- set `contract_status: ambiguous_requires_block`
- cite: `SCC-1`

### Rule C1 — Allow compliant snapshot consumption
If a request reads from `snapshots` + `snapshot_values` via `snapshot_id`, or reads `latest_snapshot.json`, and does not write to or mutate Layer-2 storage:
- this is compliant
- `valid_interface: snapshot_db` or `latest_snapshot_json`

### Rule C2 — Allow Live Market State and Event Risk Stream as governed inputs only
If Live Market State and Event Risk Stream are used as read-only governed inputs that do not touch Layer-2 storage:
- these are compliant governed inputs
- they may trigger recompute or decision; they may not rewrite Snapshot Truth

---

## Important distinction to preserve

> The Layer-2 → Layer-3 handoff gate being satisfied means Layer-3 bootstrap **may begin**.
> It does NOT mean:
> - snapshot-only read rules are relaxed
> - direct observation access becomes permitted during bootstrap
> - DecisionPacket anchoring requirements are waived
> - any invariant is conditionally suspended

This distinction must be enforced when a request attempts to justify forbidden patterns on the basis that the handoff gate is satisfied.

---

## Output format

Return a single JSON object with this shape:

```json
{
  "snapshot_contract_status": {
    "allowed": true,
    "contract_status": "compliant | boundary_violation | ambiguous_requires_block",
    "valid_interface": "snapshot_db | latest_snapshot_json | both | none",
    "forbidden_access_detected": false,
    "snapshot_anchor_required": true,
    "blocking_reason_if_any": null,
    "checked_claims": [
      {
        "claim_id": "c1",
        "claim_text": "string",
        "assessment": "compliant | blocked | ambiguous",
        "violated_invariants": [],
        "triggered_forbidden_patterns": [],
        "valid_interface_if_compliant": "snapshot_db | latest_snapshot_json | both | none",
        "reason": "string",
        "contract_reference": ["SCC-1", "FP-1"]
      }
    ],
    "summary": {
      "raw_observations_access_risk": false,
      "snapshot_bypass_risk": false,
      "layer2_storage_touch_risk": false,
      "decisionpacket_anchor_risk": false,
      "followup_guard_recommended": true
    }
  }
}
```

### Field definitions

| Field | Description |
|---|---|
| `allowed` | `true` only when `contract_status` is `compliant` |
| `contract_status` | Overall verdict: `compliant`, `boundary_violation`, or `ambiguous_requires_block` |
| `valid_interface` | Which valid interface applies to this request |
| `forbidden_access_detected` | `true` if any claim triggers FP-1 or FP-2 (direct observation access or raw-latest reads) |
| `snapshot_anchor_required` | `true` if the request touches DecisionPacket generation or Layer-3 output contracts |
| `blocking_reason_if_any` | Short string naming the violated invariant(s) or forbidden pattern(s); `null` if compliant |
| `checked_claims` | One entry per extracted claim |
| `claim_id` | Sequential identifier (`c1`, `c2`, ...) |
| `claim_text` | Brief restatement of the claim being evaluated |
| `assessment` | `compliant`, `blocked`, or `ambiguous` |
| `violated_invariants` | List of `SCC-N` identifiers violated by this claim |
| `triggered_forbidden_patterns` | List of `FP-N` identifiers triggered by this claim |
| `valid_interface_if_compliant` | Which valid interface the compliant path uses; `none` if blocked |
| `reason` | Short explanation of the assessment |
| `contract_reference` | Governing invariant(s) or forbidden pattern(s) cited |
| `raw_observations_access_risk` | `true` if any claim implies or allows `observations` access |
| `snapshot_bypass_risk` | `true` if any claim implies bypassing snapshot interfaces |
| `layer2_storage_touch_risk` | `true` if live or event inputs may write to Layer-2 storage |
| `decisionpacket_anchor_risk` | `true` if DecisionPackets might omit `snapshot_id` |
| `followup_guard_recommended` | `true` if `snapshot-boundary-guard` or deep audit should be triggered downstream |

---

## Completion checklist

Before emitting output, verify:

- [ ] All contract-touching claims in the request have been extracted and individually assessed
- [ ] Each claim maps to at least one invariant (SCC-1 through SCC-6) or is explicitly noted as not touching any invariant
- [ ] No claim is silently treated as compliant — every compliant claim must have a positive reason
- [ ] Every blocked claim names specific violated invariants and forbidden patterns
- [ ] Every ambiguous claim in strict mode has been promoted to `blocked`
- [ ] `allowed` is `false` unless every checked claim is `compliant`
- [ ] `blocking_reason_if_any` is populated whenever `allowed` is `false`
- [ ] `snapshot_anchor_required` is `true` for any request touching DecisionPacket design
- [ ] `followup_guard_recommended` is `true` whenever `boundary_violation` or `ambiguous_requires_block` is emitted
- [ ] `README_LAYER2.md` was used only as Tier 3 supporting contract detail, never as primary authority
- [ ] Historical documents were not used to override Tier 1 invariants

---

## Worked examples

### Example 1 — Direct observation access (BLOCKED)

Request: "Implement a Layer-3 module that queries `observations` directly to get the latest values for each series."

Assessment:
```json
{
  "snapshot_contract_status": {
    "allowed": false,
    "contract_status": "boundary_violation",
    "valid_interface": "none",
    "forbidden_access_detected": true,
    "snapshot_anchor_required": false,
    "blocking_reason_if_any": "Layer-3 must never query observations directly. Use snapshots + snapshot_values via snapshot_id or read latest_snapshot.json.",
    "checked_claims": [
      {
        "claim_id": "c1",
        "claim_text": "Layer-3 module queries observations directly for latest series values",
        "assessment": "blocked",
        "violated_invariants": ["SCC-1"],
        "triggered_forbidden_patterns": ["FP-1"],
        "valid_interface_if_compliant": "none",
        "reason": "observations is Layer-2-internal. Layer-3 may not query it under any circumstance.",
        "contract_reference": ["SCC-1", "FP-1"]
      }
    ],
    "summary": {
      "raw_observations_access_risk": true,
      "snapshot_bypass_risk": true,
      "layer2_storage_touch_risk": false,
      "decisionpacket_anchor_risk": false,
      "followup_guard_recommended": true
    }
  }
}
```

---

### Example 2 — Compliant snapshot consumer with file interface (COMPLIANT)

Request: "Build a snapshot consumer that reads `latest_snapshot.json` and anchors all packets by `snapshot_id` and `snapshot_clock_ts`."

Assessment:
```json
{
  "snapshot_contract_status": {
    "allowed": true,
    "contract_status": "compliant",
    "valid_interface": "latest_snapshot_json",
    "forbidden_access_detected": false,
    "snapshot_anchor_required": true,
    "blocking_reason_if_any": null,
    "checked_claims": [
      {
        "claim_id": "c1",
        "claim_text": "Snapshot consumer reads latest_snapshot.json",
        "assessment": "compliant",
        "violated_invariants": [],
        "triggered_forbidden_patterns": [],
        "valid_interface_if_compliant": "latest_snapshot_json",
        "reason": "latest_snapshot.json is a defined valid interface. This is the correct Phase B bootstrap pattern.",
        "contract_reference": ["SCC-1"]
      },
      {
        "claim_id": "c2",
        "claim_text": "Packets anchored by snapshot_id and snapshot_clock_ts",
        "assessment": "compliant",
        "violated_invariants": [],
        "triggered_forbidden_patterns": [],
        "valid_interface_if_compliant": "latest_snapshot_json",
        "reason": "snapshot_id and snapshot_clock_ts are the required DecisionPacket anchor fields.",
        "contract_reference": ["SCC-2"]
      }
    ],
    "summary": {
      "raw_observations_access_risk": false,
      "snapshot_bypass_risk": false,
      "layer2_storage_touch_risk": false,
      "decisionpacket_anchor_risk": false,
      "followup_guard_recommended": false
    }
  }
}
```

---

### Example 3 — Compliant DB interface with snapshot_id join (COMPLIANT)

Request: "Use `snapshot_id` and `snapshot_values` to populate the Layer-3 truth base."

Assessment:
```json
{
  "snapshot_contract_status": {
    "allowed": true,
    "contract_status": "compliant",
    "valid_interface": "snapshot_db",
    "forbidden_access_detected": false,
    "snapshot_anchor_required": true,
    "blocking_reason_if_any": null,
    "checked_claims": [
      {
        "claim_id": "c1",
        "claim_text": "Layer-3 queries snapshots by snapshot_id and joins snapshot_values",
        "assessment": "compliant",
        "violated_invariants": [],
        "triggered_forbidden_patterns": [],
        "valid_interface_if_compliant": "snapshot_db",
        "reason": "This is the defined valid DB interface. snapshot_id anchoring satisfies SCC-2.",
        "contract_reference": ["SCC-1", "SCC-2"]
      }
    ],
    "summary": {
      "raw_observations_access_risk": false,
      "snapshot_bypass_risk": false,
      "layer2_storage_touch_risk": false,
      "decisionpacket_anchor_risk": false,
      "followup_guard_recommended": false
    }
  }
}
```

---

### Example 4 — Live Market State overwriting Layer-2 truth (BLOCKED)

Request: "Let Live Market State overwrite Layer-2 truth when intraday price moves are large."

Assessment:
```json
{
  "snapshot_contract_status": {
    "allowed": false,
    "contract_status": "boundary_violation",
    "valid_interface": "none",
    "forbidden_access_detected": false,
    "snapshot_anchor_required": false,
    "blocking_reason_if_any": "Live Market State may not touch Layer-2 storage or rewrite Snapshot Truth. It is a governed input only.",
    "checked_claims": [
      {
        "claim_id": "c1",
        "claim_text": "Live Market State overwrites Layer-2 truth on large intraday moves",
        "assessment": "blocked",
        "violated_invariants": ["SCC-3", "SCC-4"],
        "triggered_forbidden_patterns": ["FP-4", "FP-5"],
        "valid_interface_if_compliant": "none",
        "reason": "Live Market State may trigger recompute or decision, but may not rewrite Snapshot Truth or write to Layer-2 storage under any condition.",
        "contract_reference": ["SCC-3", "SCC-4", "FP-4", "FP-5"]
      }
    ],
    "summary": {
      "raw_observations_access_risk": false,
      "snapshot_bypass_risk": false,
      "layer2_storage_touch_risk": true,
      "decisionpacket_anchor_risk": false,
      "followup_guard_recommended": true
    }
  }
}
```

---

### Example 5 — Documentation implying direct observation access is permitted (BLOCKED)

Request: "Document that Layer-3 can read observations directly for convenience during bootstrap."

Assessment:
```json
{
  "snapshot_contract_status": {
    "allowed": false,
    "contract_status": "boundary_violation",
    "valid_interface": "none",
    "forbidden_access_detected": true,
    "snapshot_anchor_required": false,
    "blocking_reason_if_any": "Documentation changes that imply forbidden access patterns are blocked on the same basis as code changes. The snapshot-only read rule is not relaxed during bootstrap.",
    "checked_claims": [
      {
        "claim_id": "c1",
        "claim_text": "Document that Layer-3 may read observations directly during bootstrap",
        "assessment": "blocked",
        "violated_invariants": ["SCC-1", "SCC-6"],
        "triggered_forbidden_patterns": ["FP-7"],
        "valid_interface_if_compliant": "none",
        "reason": "No bootstrap exception exists for direct observation access. SCC-6 explicitly states the handoff gate does not relax snapshot contract rules. This documentation change would contradict current canonical invariants.",
        "contract_reference": ["SCC-1", "SCC-6", "FP-7"]
      }
    ],
    "summary": {
      "raw_observations_access_risk": true,
      "snapshot_bypass_risk": true,
      "layer2_storage_touch_risk": false,
      "decisionpacket_anchor_risk": false,
      "followup_guard_recommended": true
    }
  }
}
```

---

### Example 6 — DecisionPackets without snapshot_id (BLOCKED)

Request: "Generate DecisionPackets without snapshot_id for now — we can add it later."

Assessment:
```json
{
  "snapshot_contract_status": {
    "allowed": false,
    "contract_status": "boundary_violation",
    "valid_interface": "none",
    "forbidden_access_detected": false,
    "snapshot_anchor_required": true,
    "blocking_reason_if_any": "snapshot_id is a required identity field on every DecisionPacket. Packets without it cannot be replayed and violate the Layer-2 → Layer-3 contract anchor.",
    "checked_claims": [
      {
        "claim_id": "c1",
        "claim_text": "Generate DecisionPackets without snapshot_id",
        "assessment": "blocked",
        "violated_invariants": ["SCC-2"],
        "triggered_forbidden_patterns": ["FP-3"],
        "valid_interface_if_compliant": "none",
        "reason": "snapshot_id and snapshot_clock_ts are required identity fields on every DecisionPacket from the first bootstrap packet. This is not deferrable.",
        "contract_reference": ["SCC-2", "FP-3"]
      }
    ],
    "summary": {
      "raw_observations_access_risk": false,
      "snapshot_bypass_risk": false,
      "layer2_storage_touch_risk": false,
      "decisionpacket_anchor_risk": true,
      "followup_guard_recommended": true
    }
  }
}
```

---

## Completion standard

This skill is complete when:

1. Every contract-relevant claim in the request has been individually assessed and appears in `checked_claims`.
2. Every blocked or ambiguous claim names the specific invariant(s) (SCC-N) and forbidden pattern(s) (FP-N) that apply.
3. Every compliant claim names the valid interface it uses.
4. `allowed` is `true` only when all claims are `compliant`.
5. `blocking_reason_if_any` is non-null whenever `allowed` is `false`.
6. `followup_guard_recommended` is `true` whenever `boundary_violation` or `ambiguous_requires_block` is the verdict.
7. `README_LAYER2.md` was used only as Tier 3 supporting contract corroboration, never as primary authority.
8. No historical document was used to override a Tier 1 invariant.
9. The output is a single valid JSON object matching the specified schema.
10. The verdict is deterministic: the same request, mode, and scope must produce the same verdict.
