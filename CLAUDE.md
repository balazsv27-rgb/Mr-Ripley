# Claude Environment — Mr. Ripley

This repository implements the **Layer-2 Truth Layer** of the Mr. Ripley market-state engine.

Layer-2 responsibilities:

- ingest market data
- validate freshness and completeness
- enforce **fail-closed** behavior
- publish immutable **snapshots**
- provide deterministic input for Layer-3

Layer-3 must **never read observations directly** and may only consume
published `snapshot_id`s.

---

# Key Architecture Rules

1. **Fail-closed behavior**
   - If Tier-1 data is stale → no snapshot published
   - Layer-3 must output nothing.

2. **Snapshots are the contract**
   - `snapshot_id`
   - `engine_version`
   - `config_version`
   - `clock_ts`

3. **Truth layer immutability**
   - `observations` rows must never be overwritten.
   - Use `INSERT OR IGNORE`, not `REPLACE`.

4. **Version-locked replay**
   - snapshot_id includes:
     - clock_ts
     - engine_version
     - config_version
     - aligned values.

5. **Registry-driven configuration**
   - `series_registry.json` is the single source of truth.

---

# Primary Working Areas

Claude should prioritize these files:

- layer2/adapters/
- layer2/config/
- layer2/db.py
- layer2/alignment.py
- layer2/clock.py
- layer2/index_suite.py


Adapters:

- gold_adapter
- move_adapter
- gld_holdings_adapter
- fred_loader
- quality_gate
- snapshot_publisher

---

# Safe Development Workflow

For non-trivial changes:

1. analyze
2. map affected files
3. propose minimal plan
4. implement incrementally
5. run verification

Always verify using:


- quality_gate.py
- snapshot_publisher.py --dry-run


---

# High-Risk Surfaces

Treat these as **architecture-critical**:

- DB schema
- snapshot generation
- quality gate
- registry structure
- snapshot alignment rules

Changes here require:

- plan mode
- reviewer pass
- verification run

---

# Repository Context Policy

Prefer:

- grep/glob discovery
- targeted file reads
- small scoped patches

Avoid:

- sweeping rewrites
- speculative architecture changes
- modifying snapshot contracts without review

---

# Typical Daily Work

Common tasks include:

- adapter fixes
- registry updates
- staleness logic
- snapshot publishing logic
- schema alignment
- validator improvements

---

# MCP Usage

This project uses a small MCP stack to improve code navigation, documentation accuracy, and database inspection.

Configured MCP servers:

* **Serena**
* **Context7**
* **SQLite**

These servers are defined in the project `.mcp.json` and are available during development sessions. 

Claude should only invoke MCP tools when they provide **clear value beyond normal file reading**.

---

# Serena — Code Navigation & Dependency Tracing

Use **Serena** when analyzing the codebase structure or tracing relationships between modules.

Preferred use cases:

* locate symbol definitions
* trace function or class references
* analyze cross-file dependencies
* inspect call graphs
* understand adapter interaction with snapshot logic
* explore schema-related code paths

Examples:

Good Serena tasks:

* trace where `snapshot_id` is generated and consumed
* locate all uses of `registry_version`
* inspect call paths into `quality_gate`
* analyze DB access patterns across adapters

Avoid Serena when:

* reading a single file
* inspecting simple logic
* performing small edits

For those cases, prefer normal file reads.

---

# Context7 — Official Library Documentation

Use **Context7** when verifying behavior of external libraries or Python runtime features.

Preferred use cases:

* confirming Python library APIs
* reviewing SQLite documentation
* checking `yfinance` usage patterns
* confirming CLI argument behavior
* validating Python stdlib behavior (datetime, sqlite3, argparse)

Examples:

Good Context7 queries:

* Python `sqlite3` connection behavior
* `yfinance` download semantics
* `argparse` argument parsing patterns
* Python datetime timezone handling

Avoid Context7 for:

* repository code questions
* architecture questions
* internal API understanding

For those, inspect the repo directly.

---

# SQLite MCP — Truth Store Inspection

Use the **SQLite MCP server** when inspecting the local truth database.

The database file:

```
layer2_truth.db
```

Primary tables:

```
observations
snapshots
snapshot_values
```

Preferred use cases:

* inspect table schemas
* check snapshot rows
* inspect observation data
* verify snapshot publishing results
* validate DB migrations
* analyze snapshot value alignment

Examples:

Good SQLite MCP tasks:

* list recent snapshots
* inspect schema of `snapshots`
* verify `engine_version` stored correctly
* inspect values in `snapshot_values`
* verify Tier-1 series counts

Avoid SQLite MCP when:

* only code analysis is needed
* DB state is irrelevant to the task

---

# MCP Usage Priority

Claude should follow this priority order:

1. **Local file inspection**
2. **Serena for structural code navigation**
3. **SQLite MCP for database inspection**
4. **Context7 for external documentation**

Do not invoke MCP tools unnecessarily.
Prefer the **simplest tool capable of answering the question**.

---

# Example Workflow

Typical debugging sequence:

1. read relevant adapter files
2. use **Serena** to trace call relationships
3. inspect snapshot generation logic
4. use **SQLite MCP** to confirm DB state
5. consult **Context7** if library behavior is unclear

This sequence keeps analysis grounded in **actual code and data**.

---

# MCP Decision Gate

Before invoking any MCP tool, apply this rule:

1. Can the answer be obtained by **reading repository files directly**?
2. Can simple **grep/glob discovery** locate the needed code?
3. Is the question about **internal logic rather than external libraries**?
4. Is database state **irrelevant** to the problem being solved?

If **all answers are YES**, **do NOT use an MCP tool.**

MCP tools should only be invoked when they provide **capabilities unavailable through normal file inspection**, such as:

* cross-file symbol tracing (Serena)
* external documentation lookup (Context7)
* live database inspection (SQLite)

When uncertain, **default to local file inspection first.**

---

# Serena Tracing Pattern

When using Serena for code analysis, follow this order:

1. locate the **primary symbol definition**
2. list **all inbound references** (who calls it)
3. list **all outbound dependencies** (what it calls)
4. identify **contract boundaries** (DB, registry, snapshot logic)

Summarize the dependency surface **before making edits**.

Avoid editing code until the symbol’s **full call graph is understood**.

---

## Why this improves Serena dramatically

Without this rule, Claude often:

* searches symbols randomly
* reads only the definition
* misses indirect dependencies

This rule forces the agent to reconstruct the **mini call graph** before touching code.

For your repo this is **especially powerful** for things like:

* `snapshot_publisher.py`
* `quality_gate.py`
* `db.py`
* registry loading
* snapshot hashing logic

Those areas have **cross-file dependencies** where incomplete tracing causes subtle bugs.

---

## Real example in your repo

Good Serena workflow for debugging `snapshot_id` logic:

1. find `compute_snapshot_id`
2. list all call sites
3. inspect dependencies (`engine_version`, `config_version`)
4. inspect DB writes in `snapshot_publisher`
5. inspect consumers (`latest_snapshot.json`, Layer-3 contract)

Only then modify code.

---

If you'd like, I can also show you **one final 6-line Claude rule that dramatically improves refactor safety in this repo** (it specifically protects the **snapshot contract and fail-closed guarantees**).

# Snapshot Contract Safety Rule

Before modifying snapshot, quality gate, or DB schema code:

1. identify the snapshot contract fields (`snapshot_id`, `engine_version`, `config_version`, `clock_ts`)
2. confirm Layer-3 interfaces remain unchanged
3. verify Tier-1 fail-closed behavior is preserved
4. run `snapshot_publisher.py --dry-run`
5. run `quality_gate.py`

If any contract field, schema behavior, or fail-closed logic changes unexpectedly → abort the refactor.