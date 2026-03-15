# Candidate Hooks — Mr. Ripley Layer-2

Hooks provide automated guardrails and context injection.
For this project: safety first, cosmetic automation last.

Location: `.claude/hooks/` (scripts) + registered in `.claude/settings.json`

---

## Hook Priorities

| Priority | Hook | Event | Type | Purpose |
|---|---|---|---|---|
| HIGH | `block-insert-replace.sh` | PreToolUse | Sync | Block `INSERT OR REPLACE` in Python edits |
| HIGH | `warn-schema-touch.sh` | PreToolUse | Sync | Warn when schema-critical files are edited |
| MEDIUM | `remind-quality-gate.sh` | PostToolUse | Async | Remind to run quality gate after adapter edits |
| LOW | `git-context.sh` | UserPromptSubmit | Sync | Inject git branch + last commit context |

---

## Hook 1: Block INSERT OR REPLACE (HIGH PRIORITY)

**Event**: `PreToolUse` (Edit, Write)
**Type**: Synchronous (blocking)
**File**: `.claude/hooks/block-insert-replace.sh`

```bash
#!/bin/bash
# Blocks INSERT OR REPLACE in Python files.
# Truth-layer discipline: observations rows must never be overwritten.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
NEW_STRING=$(echo "$INPUT" | jq -r '.tool_input.new_string // .tool_input.content // ""')

# Only check Edit and Write on Python files
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0
fi

if [[ "$FILE_PATH" != *.py ]]; then
    exit 0
fi

# Block INSERT OR REPLACE
if echo "$NEW_STRING" | grep -qi "INSERT OR REPLACE"; then
    echo "BLOCKED: INSERT OR REPLACE is forbidden in Layer-2." >&2
    echo "Use INSERT OR IGNORE to preserve observation immutability." >&2
    exit 2
fi

exit 0
```

**Registration** in `settings.json`:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/block-insert-replace.sh",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

---

## Hook 2: Warn on Schema-Critical Files (HIGH PRIORITY)

**Event**: `PreToolUse` (Edit, Write)
**Type**: Synchronous (warns, does not block)
**File**: `.claude/hooks/warn-schema-touch.sh`

Fires a `systemMessage` when high-risk files are about to be edited.
Does not block — flags for human attention.

```bash
#!/bin/bash
# Warns when architecture-critical files are being edited.
# Does not block — informs Claude to proceed with extra care.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')

if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0
fi

# High-risk surfaces
HIGH_RISK_FILES=(
    "db.py"
    "snapshot_publisher.py"
    "quality_gate.py"
    "series_registry.json"
    "alignment.py"
)

BASENAME=$(basename "$FILE_PATH")

for risk_file in "${HIGH_RISK_FILES[@]}"; do
    if [[ "$BASENAME" == "$risk_file" ]]; then
        cat << EOF
{
  "systemMessage": "⚠️ HIGH-RISK SURFACE: Editing $BASENAME. Verify snapshot contract safety before committing. Run quality_gate.py and snapshot_publisher.py --dry-run after changes."
}
EOF
        exit 0
    fi
done

exit 0
```

---

## Hook 3: Remind Quality Gate After Adapter Edits (MEDIUM PRIORITY)

**Event**: `PostToolUse` (Edit, Write)
**Type**: Asynchronous (non-blocking reminder)
**File**: `.claude/hooks/remind-quality-gate.sh`

```bash
#!/bin/bash
# After editing adapter files, remind to run verification.
# Async — does not block execution.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')

if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0
fi

# Only for adapter files
if echo "$FILE_PATH" | grep -q "layer2/adapters/"; then
    cat << EOF
{
  "systemMessage": "Adapter file modified. Remember to verify: python layer2\\adapters\\quality_gate.py"
}
EOF
fi

exit 0
```

**Registration** (async):
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/remind-quality-gate.sh",
            "timeout": 5000,
            "async": true
          }
        ]
      }
    ]
  }
}
```

---

## Hook 4: Git Context Injection (LOW PRIORITY)

**Event**: `UserPromptSubmit`
**Type**: Synchronous (enriches prompt)
**File**: `.claude/hooks/git-context.sh`

Adds current branch and last commit to every prompt. Useful to avoid
temporal confusion when working on multiple branches.

```bash
#!/bin/bash
# Injects git context into every user prompt.

BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
LAST_COMMIT=$(git log -1 --format='%h %s' 2>/dev/null || echo "no commits")
DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

cat << EOF
{
  "hookSpecificOutput": {
    "additionalContext": "[Git] branch: $BRANCH | last commit: $LAST_COMMIT | uncommitted files: $DIRTY"
  }
}
EOF

exit 0
```

**Registration**:
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/git-context.sh",
            "timeout": 3000
          }
        ]
      }
    ]
  }
}
```

---

## Platform Note (Windows)

This project runs on Windows. Hook scripts using bash syntax require:
- Git Bash or WSL available on PATH
- Or rewrite hooks as `.ps1` PowerShell scripts

For PowerShell version of `block-insert-replace`:
```powershell
# .claude/hooks/block-insert-replace.ps1
$input_json = [Console]::In.ReadToEnd() | ConvertFrom-Json
$tool_name = $input_json.tool_name
$file_path = $input_json.tool_input.file_path
$new_string = $input_json.tool_input.new_string

if ($tool_name -notmatch "Edit|Write") { exit 0 }
if ($file_path -notmatch "\.py$") { exit 0 }

if ($new_string -match "INSERT OR REPLACE") {
    Write-Error "BLOCKED: INSERT OR REPLACE is forbidden. Use INSERT OR IGNORE."
    exit 2
}
exit 0
```

Register with: `"command": "powershell -ExecutionPolicy Bypass -File .claude/hooks/block-insert-replace.ps1"`

---

## What NOT to Hook

- Python formatter (black/autopep8) — adds noise without fixing correctness
- Auto-lint on every edit — too noisy for iterative edits
- Auto-commit or auto-push — never automate git writes
- Test runner on every edit — run manually during verify step instead
