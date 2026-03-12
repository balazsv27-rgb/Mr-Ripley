# Bootstrap Brief — Mr. Ripley Claude Code Environment

## Purpose

Bootstrap a project-specific Claude Code environment for the Mr. Ripley repository.

This bootstrap must use:
- `README_LAYER2.md` as the project truth source
- `ultimate-guide.md` as the external Claude Code pattern/reference source

The goal is to derive a **lean, production-usable, project-specific** `.claude/` environment for daily work.

Do NOT treat the guide as a runtime dependency.
Use it only to extract and adapt useful patterns.

---

## Project Context

Mr. Ripley is a layered market-state engine.

Current focus:
- **Layer-2 Truth Layer**
- ingestion + validation + immutable snapshots
- Python-based data pipeline
- SQLite truth store
- registry-driven configuration
- snapshot publishing for Layer-3 consumption

Critical architectural rule:
- Layer-3 must NEVER read "latest" data directly
- Layer-3 may only consume a published `snapshot_id`
- if data is missing or stale, no snapshot is published
- system behavior must remain **fail-closed**

---

## Authoritative Sources

### 1. Project truth source
`README_LAYER2.md`

Use it to infer:
- architecture
- repository structure
- naming conventions
- data flow
- operational constraints
- verification expectations
- domain terminology

### 2. Claude Code reference source
`ultimate-guide.md`

Use it to extract only patterns relevant to:
- CLAUDE.md structure
- .claude folder design
- commands
- agents
- hooks
- skills
- MCP selection
- context/session management
- plan-driven development workflows

---

## Bootstrap Objective

Generate a Claude Code environment optimized for:

- conservative engineering
- plan-first work
- schema-aware changes
- deterministic behavior
- validator-heavy workflows
- bounded-scope refactors
- test-and-verify loops
- low-noise, maintainable AI context

This environment should support daily work on:
- adapters
- registries
- snapshot logic
- validation logic
- schema alignment
- audit-driven refactoring

---

## Non-Negotiable Constraints

1. Preserve fail-closed behavior
2. Prefer plan-first over direct implementation for non-trivial changes
3. Prefer small-scope edits over broad autonomous rewrites
4. Always verify with tests/checks after code changes
5. Treat schema/version/snapshot contracts as high-risk surfaces
6. Avoid generic web-app/frontend patterns unless explicitly relevant
7. Avoid over-engineered multi-agent setups in the first bootstrap pass
8. Keep `CLAUDE.md` lean; deeper material belongs in `.claude/` support docs

---

## What To Extract From The Guide

Extract and adapt only patterns useful for a Python backend/data-pipeline repository:

- project memory structure
- concise CLAUDE.md patterns
- planner / implementer / reviewer agent patterns
- workflow slash commands
- hook guardrails
- security-oriented conventions
- context management rules
- MCP selection guidance for backend/data workflows

Reject or deprioritize:
- frontend/design-heavy workflows
- presentation/talk/document publishing workflows
- large multi-agent topologies for now
- UI/wireframing/image-heavy features
- general-purpose patterns that do not improve Mr. Ripley daily work

---

## First Bootstrap Deliverables

Generate drafts only, not final production content, for:

1. `CLAUDE.md`
2. `.claude/settings.json`
3. `.claude/agents/planner.md`
4. `.claude/agents/implementer.md`
5. `.claude/agents/reviewer.md`
6. `.claude/commands/workflows/plan.md`
7. `.claude/commands/workflows/work.md`
8. `.claude/commands/workflows/review.md`
9. `.claude/rules/code-conventions.md`
10. `.claude/rules/git-workflow.md`

Optional second-pass drafts:
- `.claude/hooks/run-tests.sh`
- `.claude/hooks/security-scan.sh`
- `.claude/skills/refactor-module/SKILL.md`
- `.claude/skills/security-review/SKILL.md`

---

## Expected Working Style

Use this operating pattern:

1. analyze first
2. map affected files
3. summarize dependency surface
4. propose minimal safe plan
5. execute incrementally
6. verify after each batch

When in doubt:
- prefer Grep/Glob discovery before editing
- prefer plan mode for risky work
- prefer explicit verification over self-assurance

---

## MCP Strategy

At bootstrap stage:
- no mandatory MCP required if local files are sufficient

Later MCP candidates:
- Context7 for official library docs
- Serena for symbol-aware navigation
- optional database / infra MCPs only if real need emerges

Do not assume MCP is required for basic bootstrap generation.

---

## Output Policy

When generating bootstrap artifacts:
- keep them concise
- optimize for daily engineering use
- avoid generic motivational prose
- prefer operational instructions over explanation
- write for an AI collaborator embedded in this repository

## Layer-2 Code Inspection Scope

When deriving the Claude environment, prioritize inspection of the following repository areas.

### Primary implementation surface
- `layer2/adapters/`
  - `fred_loader.py`
  - `gld_holdings_adapter.py`
  - `gold_adapter.py`
  - `move_adapter.py`
  - `quality_gate.py`
  - `snapshot_publisher.py`
- `layer2/config/`
  - `registry.py`
  - `series_registry.json`
- `layer2/`
  - `db.py`
  - `alignment.py`
  - `clock.py`
  - `index_suite.py`
  - `run_backfill.py`
  - `query_db.py`

### Project truth and policy sources
- `README_LAYER2.md`
- `CLAUDE.md`
- `.claude/bootstrap/bootstrap-brief.md`

### Secondary / low-priority sources
Use only if needed for clarification:
- `old_docs/`
- `docs/`
- `layer2/audit.md`

### Exclusions / caution zones
Do not prioritize during bootstrap unless explicitly needed:
- `.secrets/`
- `layer2/adapters/v0/`
- `legacy_marco_data/`
- `logs.txt`
- binary or image files
- local DB contents unless a task explicitly requires DB inspection