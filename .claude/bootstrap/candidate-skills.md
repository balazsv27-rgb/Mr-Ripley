# Candidate Skills — Mr. Ripley Layer-2

Skills are knowledge modules loaded into agent or command context.
Type: **Encoded Preference** — project-specific rules, not capability uplift.

Location: `.claude/skills/<skill-name>/SKILL.md`

---

## Skill Roster (2 skills)

| Skill | Purpose | Loaded by |
|---|---|---|
| `snapshot-contract` | Snapshot ID composition, version locking, fail-closed rules | reviewer agent, planner agent |
| `adapter-conventions` | INSERT OR IGNORE, date normalization, registry-driven patterns | implementer agent |

---

## Skill 1: snapshot-contract

**File**: `.claude/skills/snapshot-contract/SKILL.md`

```markdown
---
name: snapshot-contract
description: Layer-2 snapshot contract rules. Use when reviewing or modifying snapshot_publisher.py, db.py, quality_gate.py, or any code that touches snapshot_id, engine_version, config_version, or clock_ts.
allowed-tools: Read Grep Glob
---

# Snapshot Contract

## When to Apply

Apply this skill when:
- Reviewing any change to `snapshot_publisher.py` or `db.py`
- Verifying snapshot_id composition is intact
- Checking fail-closed behavior after quality gate changes
- Evaluating any Layer-3 interface change

## Core Contract Fields

Every published snapshot must contain:
- `snapshot_id` — 64-char SHA-256. Includes: clock_ts + engine_version + config_version + aligned series values
- `engine_version` — set via `L2_ENGINE_VERSION` env var (e.g. `gold-v3.3.0`)
- `config_version` — resolved from `registry_version` key in `series_registry.json`
- `clock_ts` — 22:00 UTC daily (configurable via `L2_CLOCK_CUT_HOUR`)

**Layer-3 contract**: reads `latest_snapshot.json` or queries `snapshots` + `snapshot_values` tables by `snapshot_id`. NEVER reads `observations` directly.

## Fail-Closed Rules

- Any Tier-1 series stale → quality gate FAIL → NO snapshot published
- Layer-3 must output nothing when no snapshot exists
- `--force` flag: quality gate still runs; snapshot marked `forced=True` permanently in DB + JSON
- Forced snapshots must be filtered out of backtests

## Snapshot Deduplication

Three-way dedup: `clock_ts + engine_version + config_version`

Same clock_ts can yield multiple valid snapshots under different engine/config versions.
Never dedup on clock_ts alone.

## Schema Immutability

`observations` rows are immutable:
- Use `INSERT OR IGNORE` — never `INSERT OR REPLACE`
- If FRED revises a value: write `revision_seq=1`, do not overwrite `rev=0`

## snapshot_id Hash Payload

```python
# Must include all four:
payload = f"{clock_ts}|{engine_version}|{config_version}|{series_values_sorted}"
snapshot_id = hashlib.sha256(payload.encode()).hexdigest()  # full 64 chars — never truncate
```

## Auto-Migration

Existing DBs gain `engine_version`/`config_version` columns via `_ensure_snapshot_schema_migrations()`.
Migrated rows get sentinel values `UNKNOWN_ENGINE_VERSION` / `UNKNOWN_CONFIG_VERSION`.
These are filterable in replay queries.

## Checklist (before approving snapshot-touching changes)

- [ ] snapshot_id still includes engine_version + config_version in hash
- [ ] Three-way dedup logic intact
- [ ] forced=True flag preserved on --force path
- [ ] Tier-1 fail-closed: any FAIL → no publish
- [ ] No `INSERT OR REPLACE` in any write path
- [ ] Layer-3 contract fields unchanged: snapshot_id, engine_version, config_version, clock_ts, verdict, forced, tier1_series, tier2_series, missing_series
```

---

## Skill 2: adapter-conventions

**File**: `.claude/skills/adapter-conventions/SKILL.md`

```markdown
---
name: adapter-conventions
description: Layer-2 adapter code conventions. Use when writing or reviewing any adapter (gold_adapter, move_adapter, gld_holdings_adapter, fred_loader) or db.py writes.
allowed-tools: Read Grep Glob
---

# Adapter Conventions

## When to Apply

Apply this skill when:
- Writing or reviewing adapter code
- Reviewing db.py write paths
- Checking incremental load logic
- Validating registry integration

## Core Conventions

### 1. Observations are immutable

```python
# CORRECT — immutable insert
cursor.execute("""
    INSERT OR IGNORE INTO observations
    (series_id, obs_ts, as_of_ts, value, revision_seq, source, ingested_at)
    VALUES (?, ?, ?, ?, 0, ?, CURRENT_TIMESTAMP)
""", (...))

# FORBIDDEN — destroys history
cursor.execute("INSERT OR REPLACE INTO ...")
```

### 2. Date comparison always normalized to strings

```python
# CORRECT — prevents str-vs-date type mismatch
existing_dates = {str(d) for d in existing_dates}
new_date_str = obs_ts.isoformat() if hasattr(obs_ts, 'isoformat') else str(obs_ts)
if new_date_str not in existing_dates:
    ...

# WRONG — silent type mismatch
if obs_ts not in existing_dates:  # may compare date vs str
    ...
```

### 3. No sqlite3 detect_types

```python
# CORRECT — deprecated in Python 3.12+
conn = sqlite3.connect(db_path)

# FORBIDDEN
conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
```

### 4. Registry-driven — no hardcoded series logic

```python
# CORRECT — reads from registry
series = registry.get_series(series_id)
threshold = series["staleness_threshold_days"]
tier = series["tier"]

# FORBIDDEN — hardcoded
if series_id == "gold_price_proxy":
    threshold = 3
```

### 5. Tier assignment is registry-authoritative

Tier-1 and Tier-2 lists must come from `series_registry.json`, not from adapter code.
Never re-enumerate Tier-1 series in adapter logic.

### 6. Batch hashes are full 64-char SHA-256

```python
# CORRECT
batch_hash = hashlib.sha256(batch_data.encode()).hexdigest()  # 64 chars

# FORBIDDEN — collision risk
batch_hash = hashlib.sha256(batch_data.encode()).hexdigest()[:16]
```

## Staleness Thresholds Reference

| Series | Threshold | Reason |
|---|---|---|
| Most Tier-1 | 3 days | Covers weekend (2d) + 1d FRED lag |
| DTWEXBGS | 10 days | Structural FRED publish lag |
| Tier-2 monthly | 45 days | BLS/BEA release lag |
| PCU2122212122210 | 9999 days | Discontinued 2017 |

## Source String Reference

| Adapter | source value |
|---|---|
| gold_adapter | `stooq_json`, `gold_api`, `yahoo_gc=f` |
| move_adapter | `yahoo_move` |
| gld_holdings_adapter | `yahoo_gld_proxy` |
| fred_loader | `fred_api` |

## Checklist (before approving adapter changes)

- [ ] No INSERT OR REPLACE
- [ ] Date comparisons use string normalization
- [ ] No detect_types in sqlite3.connect()
- [ ] No hardcoded series IDs or thresholds
- [ ] Tier assignment reads from registry
- [ ] Batch hashes are full 64-char SHA-256
- [ ] latest_obs_date() returns handle str/datetime/date objects
```

---

## Loading Skills into Agents

Add to agent frontmatter:
```yaml
skills:
  - snapshot-contract   # reviewer and planner
  - adapter-conventions # implementer
```

## Notes

- Both skills are **Encoded Preference** type — they encode project rules, not capability gaps
- Durable as long as the Layer-2 contracts remain unchanged
- Retirement signal: project architecture changes or contracts are redesigned
- Do not add a `security-guardian` or generic OWASP skill — not relevant to this pipeline
