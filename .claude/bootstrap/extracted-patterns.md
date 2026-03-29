# Extracted Patterns — Mr. Ripley Layer-2

Sourced from `ultimate-guide.md` and filtered for a Python fail-closed data pipeline.

---

## 1. Memory & Context Hierarchy

From guide §3.1 / §3.2:

```
CLAUDE.md             → project rules, architecture constraints, verification commands
.claude/rules/        → code conventions, git workflow (already present)
.claude/agents/       → planner, implementer, reviewer
.claude/skills/       → snapshot-contract, adapter-conventions
.claude/commands/     → workflows/plan, workflows/work, workflows/review, git/commit
.claude/hooks/        → pre-tool safety checks, post-edit reminders
```

**Rule**: CLAUDE.md stays lean. Deep domain knowledge belongs in skills and agents.

---

## 2. Plan Mode Pattern

From guide §2.3:

- Use `/plan` or enter plan mode before touching: schema, snapshot logic, quality gate, registry
- Plan mode = read-only exploration + analysis + proposal
- Exit plan mode only after: dependency surface mapped, minimal plan proposed, user approved
- High-risk surfaces in this project: `db.py`, `snapshot_publisher.py`, `quality_gate.py`, `series_registry.json`

**Rule**: Non-trivial changes → plan mode first, always.

---

## 3. Agents: Planner / Implementer / Reviewer Separation

From guide §4.1, §4.3, §4.4:

Three agents appropriate for this project:

| Agent | Model | Tools | Purpose |
|---|---|---|---|
| `planner` | opus | Read, Grep, Glob | Analyze scope, map dependencies, propose minimal plan |
| `implementer` | sonnet | Read, Edit, Write, Grep, Glob, Bash | Execute small-scope patches per plan |
| `reviewer` | sonnet | Read, Grep, Glob | Verify snapshot contract, schema safety, conventions |

**Key rule**: Agents have isolated context — prevents prior debugging state from contaminating fresh analysis.

---

## 4. Skills: Encoded Preference Type

From guide §5.0:

Skills for this project are **Encoded Preference** skills — they encode project-specific rules Claude already understands generically but must apply with project-specific constraints.

Two strong candidates:
- `snapshot-contract`: snapshot_id composition, engine/config version locking, fail-closed rules
- `adapter-conventions`: INSERT OR IGNORE, date normalization, registry-driven, no hardcoding

These are durable as long as the Layer-2 contracts remain the same.

---

## 5. Commands: Workflow Slash Commands

From guide §6.1, §6.2:

Commands = repeatable workflow sequences, not knowledge.

For this project:
- `/workflows:plan` — structured plan-first analysis for any non-trivial change
- `/workflows:work` — standard work loop (analyze → map → plan → implement → verify)
- `/workflows:review` — post-change review (conventions, contract safety, verification)
- `/git:commit` — scoped commit with component prefix
- `/git:pr` — PR creation with Layer-2 context

**Rule**: `/workflows:work` must include a verify step: run `quality_gate.py` and optionally `snapshot_publisher.py --dry-run`.

---

## 6. Hooks: Guardrails Over Automation

From guide §7.1, §7.2, §7.3:

For a Python data pipeline, hooks serve as **safety guardrails**, not cosmetic formatters.

High-value hook events for this project:

| Event | Use |
|---|---|
| `PreToolUse` (Bash/Edit/Write) | Block `INSERT OR REPLACE` in Python edits; warn on schema-touching files |
| `PostToolUse` (Edit/Write) | Remind to run quality gate after adapter changes |
| `UserPromptSubmit` | Inject git branch + last commit context |

**Rule**: Hooks must be synchronous for validation; async only for logging.

---

## 7. Context Management

From guide §2.2 TL;DR:

| Context % | Action |
|---|---|
| 0–50% | Work freely |
| 50–70% | Be selective |
| 70–90% | `/compact` |
| 90%+ | `/clear` |

For this project: long analysis sessions (tracing snapshot_id through 4+ files) consume context fast. Use `/compact` proactively before starting a new adapter fix.

---

## 8. Decision Tree: Which Mechanism?

Adapted from guide §5.1:

```
Is this a repeatable workflow with defined steps?
  → Yes: Command (workflows/plan, workflows/work, workflows/review)

Is this domain knowledge multiple agents or sessions need?
  → Yes: Skill (snapshot-contract, adapter-conventions)

Does this need isolated context or fresh perspective?
  → Yes: Agent (planner, implementer, reviewer)

Is this a project-wide rule or constraint?
  → Yes: CLAUDE.md or .claude/rules/

Is this a safety guardrail or automation trigger?
  → Yes: Hook
```

---

## 9. Patterns Rejected for This Project

From bootstrap-brief constraints:

- ❌ 7-parallel-agent feature implementation (not relevant for single-file adapter fixes)
- ❌ Self-evolving agents (overkill at this stage)
- ❌ Named perspective agents (not useful for data pipeline work)
- ❌ Frontend/UI agent patterns
- ❌ Multi-agent orchestration topology (planner → implementer → reviewer is sufficient)
- ❌ Skill evals / benchmark mode (too much overhead for Phase 3 bootstrap)

---

## 10. Verification-First Rule

Distilled from CLAUDE.md + README_LAYER2.md §11:

Every code change affecting adapters, schema, or snapshot logic must include:

1. `python layer2\adapters\quality_gate.py`
2. `python layer2\adapters\snapshot_publisher.py --dry-run`

These are the canonical verification commands. Commands and agents must reference these explicitly.
