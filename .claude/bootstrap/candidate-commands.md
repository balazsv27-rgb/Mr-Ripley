# Candidate Commands — Mr. Ripley Layer-2

Commands are repeatable workflow sequences invoked via slash commands.
Location: `.claude/commands/<namespace>/<name>.md` → invoked as `/<namespace>:<name>`

---

## Already Exists (wired in settings.json)

- `/workflows:plan` — `.claude/commands/workflows/plan.md`
- `/workflows:work` — `.claude/commands/workflows/work.md`
- `/workflows:review` — `.claude/commands/workflows/review.md`
- `/git:commit` — `.claude/commands/git/commit.md`
- `/git:pr` — `.claude/commands/git/pr.md`

---

## Command Designs

### `/workflows:plan`

**Purpose**: Enter a structured plan-first analysis for any non-trivial change.

**Steps**:
1. Read relevant files in primary working area
2. Use Serena to trace affected symbols if cross-file dependencies exist
3. Identify high-risk surfaces touched (schema / snapshot / quality gate / registry)
4. If high-risk surface detected → flag for plan mode + reviewer pass
5. Map all files affected
6. Propose minimal, scoped plan with explicit step sequence
7. Do NOT implement — wait for user approval

**Verification**: None — plan mode is read-only.

**Template**:
```
Analyze the following change request in plan mode only. Do not implement anything.

Change: $ARGUMENTS

Steps:
1. Read all directly affected files in layer2/
2. Trace cross-file dependencies using Serena if needed
3. Identify any high-risk surfaces (schema, snapshot logic, quality gate, registry)
4. Map all files that will change
5. Propose a minimal, scoped implementation plan with explicit step-by-step order
6. State what verification steps are required after implementation

Wait for approval before proceeding.
```

---

### `/workflows:work`

**Purpose**: Standard daily work loop — analyze, plan, implement, verify.

**Steps**:
1. Analyze the task (read files, no changes)
2. Map affected files
3. Propose minimal plan (if non-trivial, enter plan mode)
4. Implement incrementally — one logical unit at a time
5. After each unit: run verification
6. Final: run `quality_gate.py` + optionally `snapshot_publisher.py --dry-run`

**Verification commands**:
```bash
python layer2\adapters\quality_gate.py
python layer2\adapters\snapshot_publisher.py --dry-run
```

**Template**:
```
Work on the following task using the standard Layer-2 workflow.

Task: $ARGUMENTS

Protocol:
1. Analyze — read relevant files, identify scope
2. Map — list all files that will change
3. Plan — propose minimal step sequence (halt for review if schema/snapshot/registry changes)
4. Implement — make changes incrementally
5. Verify — run quality_gate.py; run snapshot_publisher.py --dry-run if snapshot logic was touched

Do not skip the verification step.
```

---

### `/workflows:review`

**Purpose**: Post-change review — check conventions, contract safety, verify.

**Steps**:
1. Read all changed files (use git diff to identify)
2. Check against code conventions (INSERT OR IGNORE, date normalization, registry-driven)
3. Verify snapshot contract fields are intact if snapshot code was touched
4. Verify fail-closed behavior is preserved
5. Run quality gate and report result
6. Flag any issues by severity: Critical / Warning / Low

**Verification commands**:
```bash
python layer2\adapters\quality_gate.py
python layer2\adapters\snapshot_publisher.py --dry-run
```

**Template**:
```
Review all recent changes using the Layer-2 review protocol.

Scope: $ARGUMENTS (default: all changes since last commit)

Protocol:
1. Identify changed files via git diff
2. Check code conventions: INSERT OR IGNORE, explicit imports, date normalization, no hardcoded series logic
3. If snapshot_publisher.py or db.py touched: verify snapshot contract fields (snapshot_id, engine_version, config_version, clock_ts) are intact
4. If quality_gate.py touched: verify Tier-1 fail-closed logic is preserved
5. Run quality_gate.py and report verdict
6. Run snapshot_publisher.py --dry-run and report result
7. Report findings: Critical (must fix) / Warning (should fix) / Low (optional)
```

---

### `/git:commit`

**Purpose**: Create a scoped commit with the Layer-2 component prefix convention.

**Convention**: `<component>: short description`

**Components**: `adapter`, `snapshot`, `db`, `registry`, `quality-gate`, `clock`, `alignment`, `docs`

**Template**:
```
Create a git commit for the current staged changes.

Follow the commit convention:
  <component>: short description

Component options: adapter, snapshot, db, registry, quality-gate, clock, alignment, docs

Steps:
1. Run git status to confirm staged files
2. Determine the primary component touched
3. Draft a concise commit message (max 72 chars)
4. Commit — do not push
```

---

### `/git:pr`

**Purpose**: Create a pull request with Layer-2 context in the description.

**Template**:
```
Create a pull request for the current branch.

PR description must include:
- What changed (component + file list)
- Why (motivation / issue fixed)
- Verification steps run (quality_gate.py result, dry-run result)
- Any high-risk surfaces touched and reviewer notes needed

Do not push to main directly. Target: main branch.
```

---

## Notes

- Commands are invoked in the main conversation context (not isolated like agents)
- Keep command files short — they are workflow prompts, not knowledge modules
- Arguments passed via `$ARGUMENTS` (e.g., `/workflows:plan fix FRED loader retry logic`)
- For high-risk surface changes, `/workflows:plan` must be run before `/workflows:work`
