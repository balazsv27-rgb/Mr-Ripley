# MCP Bootstrap Notes — Mr. Ripley Layer-2

Decision notes for MCP server usage during daily Layer-2 work.

---

## Current MCP Stack

Three servers configured in `.mcp.json`:
- **Serena** — semantic code navigation and symbol tracing
- **Context7** — official library documentation lookup
- **SQLite MCP** — live inspection of `layer2_truth.db`

---

## Usage Priority (from CLAUDE.md)

```
1. Local file inspection (Read, Grep, Glob)
2. Serena — cross-file symbol tracing
3. SQLite MCP — live database inspection
4. Context7 — external library documentation
```

**Default to local file reads. Only escalate to MCP when local tools are insufficient.**

---

## Serena — When to Use

**Use Serena for**:
- Tracing where `snapshot_id` is computed and consumed
- Finding all references to `compute_snapshot_id`, `_write_snapshot`, `_snapshot_exists`
- Mapping call paths into `quality_gate.py` from adapters
- Understanding DB access patterns across all 6 adapters
- Locating all consumers of `registry_version` / `config_version`
- Inspecting call graphs before modifying high-risk symbols

**Serena tracing order** (from CLAUDE.md):
1. Locate primary symbol definition
2. List all inbound references (who calls it)
3. List all outbound dependencies (what it calls)
4. Identify contract boundaries (DB, registry, snapshot logic)

**Do NOT use Serena for**:
- Reading a single file
- Simple logic inspection
- Quick edits to a known location

**Key symbols to trace with Serena**:
- `compute_snapshot_id` — snapshot_publisher.py
- `_write_snapshot` — snapshot_publisher.py
- `_snapshot_exists` — snapshot_publisher.py
- `get_connection` — db.py
- `_ensure_snapshot_schema_migrations` — db.py
- `load_registry` / `validate_registry` — registry.py
- `run_quality_gate` — quality_gate.py

---

## Context7 — When to Use

**Use Context7 for**:
- Confirming `sqlite3.connect()` behavior in Python 3.12+
- Verifying `yfinance` download() semantics and parameters
- Checking `argparse` argument parsing patterns
- Confirming Python `datetime` timezone handling
- Validating FRED API / requests library behavior

**Do NOT use Context7 for**:
- Repository code questions
- Architecture questions
- Understanding internal Layer-2 logic

**Common Context7 queries for this project**:
```
python sqlite3 connection parameters Python 3.12
yfinance download() parameters and return format
argparse add_argument type datetime
python datetime timezone UTC conversion
```

---

## SQLite MCP — When to Use

**Database file**: `layer2_truth.db`

**Primary tables**:
- `observations` — time series data (immutable)
- `snapshots` — published snapshot registry
- `snapshot_values` — series values per snapshot

**Use SQLite MCP for**:
- Verifying schema after a migration (`PRAGMA table_info(snapshots)`)
- Checking recent snapshots: `SELECT * FROM snapshots ORDER BY clock_ts DESC LIMIT 5`
- Verifying `engine_version` / `config_version` stored correctly
- Inspecting Tier-1 series counts in `snapshot_values`
- Confirming observation row counts after adapter runs
- Debugging staleness issues by querying `MAX(obs_ts)` per series

**Do NOT use SQLite MCP for**:
- Tasks where DB state is irrelevant (pure code analysis)
- Browsing data unnecessarily — query with intent

**Useful queries**:
```sql
-- Recent snapshots
SELECT snapshot_id, clock_ts, engine_version, config_version, verdict, forced
FROM snapshots ORDER BY clock_ts DESC LIMIT 5;

-- Latest observation per series
SELECT series_id, MAX(obs_ts) as latest, COUNT(*) as rows
FROM observations GROUP BY series_id ORDER BY series_id;

-- Snapshot values for latest snapshot
SELECT sv.series_id, sv.tier, sv.obs_ts, sv.value, sv.staleness_days
FROM snapshot_values sv
JOIN snapshots s ON sv.snapshot_id = s.snapshot_id
ORDER BY s.clock_ts DESC, sv.tier, sv.series_id
LIMIT 30;

-- Schema inspection
PRAGMA table_info(snapshots);
PRAGMA table_info(observations);
```

---

## MCP Decision Gate

Before invoking any MCP tool, ask:

1. Can this be answered by reading a repo file directly? → Use Read/Grep/Glob
2. Is this a cross-file symbol tracing question? → Use Serena
3. Is this about live DB state? → Use SQLite MCP
4. Is this about external library behavior? → Use Context7
5. None of the above? → Ask the user for clarification

---

## What NOT to Add to MCP

At this stage, do not add:
- Browser / web scraping MCP
- File system MCP (redundant with built-in tools)
- GitHub MCP (use `gh` CLI instead)
- Any execution / deployment MCP

The current 3-server stack is sufficient for daily Layer-2 work.
