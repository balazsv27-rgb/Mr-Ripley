#!/usr/bin/env python3
"""
pre-pr-governance-gate
======================
Hook:    PreToolUse  (matcher: Bash)
Layer:   E — Verification Hygiene / Release
Action:  block_on_fail
Defined: .claude/workflows/packages/hooks.yaml

The final release gate.  Fires before every Bash tool call and inspects
the command for `git commit` or `git push` patterns.  If neither is
found, the hook exits immediately (exit 0) without scanning anything.

When a commit or push IS detected, the hook validates that:

  1. All always-required governance artifacts are present in the
     artifact store (.claude/run/artifacts/).

  2. All conditionally-required artifacts are present for any scope
     predicate that is currently active (inferred from staged files via
     `git diff --cached --name-only`).

  3. The `pr_readiness_verdict` artifact passes all required field checks.

On any failure the hook exits 2 (block) and surfaces a structured report
identifying exactly which artifacts are missing and which readiness checks
failed.  On a clean pass it exits 0 silently.

Scope predicates and conditional artifacts
------------------------------------------
Predicates are inferred from staged file paths:

  runtime_code_scope       → any file under layer2/
  adapter_registry_scope   → any file under layer2/adapters/ or layer2/config/
  doc_update_required      → any canonical document in the staged set
  rename_only_change       → staged set contains only renames (git --diff-filter=R)
  matrix_posture_affected  → DOCUMENTATION_VERIFICATION_MATRIX file staged

Conditional artifact requirements:

  runtime_boundary_verdict   when runtime_code_scope
  adapter_schema_verdict     when adapter_registry_scope
  doc_update_plan            when doc_update_required
  invariance_verdict         when rename_only_change
  verification_matrix_delta  when matrix_posture_affected

PR readiness checks (from pr_readiness_verdict.data)
------------------------------------------------------
  unsupported_strong_claims_remain  must be false
  blocking_conditions_unresolved    must be false
  required_canonical_docs_reviewed  must be true
  canonical_references_updated      must be true
  alias_map_present_for_renames     must be true  (only when rename_only_change)

Exit codes
----------
  0  All checks pass — allow git commit/push to proceed.
  2  One or more checks fail — block immediately, surface report.

Blocking conditions raised (from blocking-conditions.yaml):
  governance_artifacts_incomplete
  pr_readiness_checks_failed

Note on PreToolUse / Bash matching
-----------------------------------
Claude Code fires PreToolUse before every Bash call.  This hook matches
all Bash calls via the settings.json matcher, then self-filters by
inspecting the command string.  Non-git-commit/push calls exit 0 immediately
with no artifact I/O.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "lib"))

from artifact_store import artifact_exists, read_artifact, ArtifactMalformed, ArtifactNotFound  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOOK_NAME = "pre-pr-governance-gate"

# Canonical document file names (CLAUDE.md §2.1) — used for predicate inference.
CANONICAL_DOC_NAMES = frozenset({
    "README_v1.md",
    "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
    "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
    "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
    "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
    "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
    "README_LAYER2.md",
})

# Always-required governance artifacts (present regardless of scope).
ALWAYS_REQUIRED_ARTIFACTS = [
    "governance_context",
    "claim_classification_map",
    "normalized_terminology_map",
    "role_citation_verdict",
    "phase_alignment_status",
    "contract_compliance_verdict",
    "stage_gate_report",
    "guard_report",
    "audit_summary",
    "change_impact_report",
    "doc_code_sync_status",
    "verification_ledger_delta",
    "artifact_hygiene_verdict",
    "pr_readiness_verdict",
]

# Conditional artifact map: predicate_name → artifact_name
CONDITIONAL_ARTIFACTS: dict[str, str] = {
    "runtime_code_scope":      "runtime_boundary_verdict",
    "adapter_registry_scope":  "adapter_schema_verdict",
    "doc_update_required":     "doc_update_plan",
    "rename_only_change":      "invariance_verdict",
    "matrix_posture_affected": "verification_matrix_delta",
}

# PR readiness checks: field → expected_value.
# Checked against pr_readiness_verdict.data.
PR_READINESS_CHECKS: dict[str, bool] = {
    "unsupported_strong_claims_remain": False,
    "blocking_conditions_unresolved":   False,
    "required_canonical_docs_reviewed": True,
    "canonical_references_updated":     True,
}

# Conditional PR readiness check: field → expected_value — only when predicate active.
PR_READINESS_CONDITIONAL: dict[str, tuple[str, bool]] = {
    "alias_map_present_for_renames": ("rename_only_change", True),
}


# ---------------------------------------------------------------------------
# Helpers — command parsing
# ---------------------------------------------------------------------------


def load_stdin_event() -> dict:
    """Parse the PreToolUse JSON payload from stdin."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def extract_bash_command(event: dict) -> str:
    """Return the bash command string from the tool event, or empty string."""
    return event.get("tool_input", {}).get("command", "")


def is_git_commit_or_push(command: str) -> bool:
    """
    Return True if the command contains a `git commit` or `git push` invocation.
    Handles multi-command strings joined with && or ;.
    """
    return bool(re.search(r'\bgit\s+(commit|push)\b', command))


# ---------------------------------------------------------------------------
# Helpers — git / predicate inference
# ---------------------------------------------------------------------------


def _run_git(args: list[str], timeout: int = 10) -> tuple[int, str]:
    """Run a git command and return (returncode, stdout). Never raises."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return -1, ""


def get_staged_files() -> list[str]:
    """Return the list of files currently staged for commit."""
    rc, out = _run_git(["diff", "--cached", "--name-only"])
    if rc != 0:
        return []
    return [f.strip() for f in out.splitlines() if f.strip()]


def get_staged_rename_only(staged_files: list[str]) -> bool:
    """
    Return True if the staged set consists exclusively of renames.
    Uses git diff --cached --diff-filter=R to count rename-only files.
    """
    if not staged_files:
        return False
    rc, renamed_out = _run_git(["diff", "--cached", "--diff-filter=R", "--name-only"])
    if rc != 0:
        return False
    renamed = {f.strip() for f in renamed_out.splitlines() if f.strip()}
    staged = set(staged_files)
    # rename_only_change is true only when every staged file is a rename
    return bool(renamed) and renamed == staged


def _normalise(path: str) -> str:
    return path.replace("\\", "/")


def evaluate_predicates(staged_files: list[str]) -> dict[str, bool]:
    """
    Infer which scope predicates are active from the staged file set.
    Returns a dict of predicate_name → bool.
    """
    predicates: dict[str, bool] = {
        "runtime_code_scope":      False,
        "adapter_registry_scope":  False,
        "doc_update_required":     False,
        "rename_only_change":      False,
        "matrix_posture_affected": False,
    }

    for raw_path in staged_files:
        p = _normalise(raw_path)

        if p.startswith("layer2/"):
            predicates["runtime_code_scope"] = True

        if p.startswith("layer2/adapters/") or p.startswith("layer2/config/"):
            predicates["adapter_registry_scope"] = True

        filename = Path(p).name
        if filename in CANONICAL_DOC_NAMES:
            predicates["doc_update_required"] = True

        if "DOCUMENTATION_VERIFICATION_MATRIX" in p:
            predicates["matrix_posture_affected"] = True

    if staged_files:
        predicates["rename_only_change"] = get_staged_rename_only(staged_files)

    return predicates


# ---------------------------------------------------------------------------
# Helpers — artifact / readiness checks
# ---------------------------------------------------------------------------


class CheckFailure(NamedTuple):
    category: str   # "missing_artifact" | "readiness_check" | "readiness_artifact"
    name: str       # artifact name or check field name
    detail: str     # human-readable explanation


def check_always_required(failures: list[CheckFailure]) -> None:
    """Append a failure for each always-required artifact that is absent."""
    for name in ALWAYS_REQUIRED_ARTIFACTS:
        if not artifact_exists(name):
            failures.append(CheckFailure(
                category="missing_artifact",
                name=name,
                detail=f"Always-required artifact '{name}' not found in artifact store.",
            ))


def check_conditional_artifacts(
    predicates: dict[str, bool],
    failures: list[CheckFailure],
) -> None:
    """Append a failure for each conditional artifact whose predicate is active but artifact absent."""
    for predicate, artifact_name in CONDITIONAL_ARTIFACTS.items():
        if predicates.get(predicate) and not artifact_exists(artifact_name):
            failures.append(CheckFailure(
                category="missing_artifact",
                name=artifact_name,
                detail=(
                    f"Conditional artifact '{artifact_name}' required because "
                    f"predicate '{predicate}' is active, but artifact not found."
                ),
            ))


def check_pr_readiness(
    predicates: dict[str, bool],
    failures: list[CheckFailure],
) -> None:
    """
    Read pr_readiness_verdict and validate all required field checks.
    Appends failures for any check that does not meet its expected value.
    Skips gracefully if the artifact is absent (already captured as missing_artifact).
    """
    try:
        data = read_artifact("pr_readiness_verdict")
    except (ArtifactNotFound, ArtifactMalformed):
        # Already recorded as a missing/malformed artifact — nothing more to do here.
        return

    # Always-active readiness checks
    for field, expected in PR_READINESS_CHECKS.items():
        actual = data.get(field)
        if actual is None:
            failures.append(CheckFailure(
                category="readiness_check",
                name=field,
                detail=(
                    f"Field '{field}' is absent from pr_readiness_verdict. "
                    f"Expected {expected}."
                ),
            ))
        elif actual != expected:
            failures.append(CheckFailure(
                category="readiness_check",
                name=field,
                detail=(
                    f"pr_readiness_verdict.{field} = {actual!r} "
                    f"(expected {expected!r})."
                ),
            ))

    # Conditional readiness checks
    for field, (predicate, expected) in PR_READINESS_CONDITIONAL.items():
        if not predicates.get(predicate):
            continue
        actual = data.get(field)
        if actual is None:
            failures.append(CheckFailure(
                category="readiness_check",
                name=field,
                detail=(
                    f"Field '{field}' is absent from pr_readiness_verdict. "
                    f"Required because predicate '{predicate}' is active. "
                    f"Expected {expected}."
                ),
            ))
        elif actual != expected:
            failures.append(CheckFailure(
                category="readiness_check",
                name=field,
                detail=(
                    f"pr_readiness_verdict.{field} = {actual!r} "
                    f"(expected {expected!r}, predicate '{predicate}' is active)."
                ),
            ))

    # Surface any failed_checks list the artifact itself declares
    failed_checks = data.get("failed_checks")
    if failed_checks:
        for fc in failed_checks:
            failures.append(CheckFailure(
                category="readiness_check",
                name=str(fc),
                detail=f"pr_readiness_verdict declares failed check: {fc!r}",
            ))


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _section(title: str) -> str:
    return f"\n  {'─' * 4} {title} {'─' * (50 - len(title))}"


def build_failure_report(
    command: str,
    failures: list[CheckFailure],
    predicates: dict[str, bool],
    staged_files: list[str],
) -> str:
    """Build the full human-readable block report."""
    lines = [
        f"[{HOOK_NAME}] Pre-PR governance gate FAILED.",
        f"  Command: {command[:120]}",
        f"  Failures: {len(failures)}",
    ]

    # Active predicates summary
    active = [p for p, v in predicates.items() if v]
    if active:
        lines.append(f"  Active predicates: {', '.join(active)}")
    if staged_files:
        lines.append(f"  Staged files ({len(staged_files)}): "
                     + ", ".join(staged_files[:6])
                     + (" …" if len(staged_files) > 6 else ""))

    # Missing artifacts
    missing = [f for f in failures if f.category == "missing_artifact"]
    if missing:
        lines.append(_section("Missing governance artifacts"))
        lines.append("")
        for f in missing:
            lines.append(f"  ✗  {f.name}")
            lines.append(f"     {f.detail}")
        lines.append("")

    # Readiness check failures
    readiness = [f for f in failures if f.category == "readiness_check"]
    if readiness:
        lines.append(_section("PR readiness check failures"))
        lines.append("")
        for f in readiness:
            lines.append(f"  ✗  {f.name}")
            lines.append(f"     {f.detail}")
        lines.append("")

    lines.append("─" * 60)
    lines.append("BLOCKED — raising: governance_artifacts_incomplete, pr_readiness_checks_failed")
    lines.append("")
    lines.append(
        "Resolution:\n"
        "  1. Run the full governance workflow to produce all required artifacts.\n"
        "  2. Resolve all blocking conditions listed in pr_readiness_verdict.\n"
        "  3. Ensure all canonical documents have been reviewed (CLAUDE.md §11).\n"
        "  4. Re-run the workflow to regenerate a clean pr_readiness_verdict.\n"
        "  5. Retry the git commit or push once all checks pass."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    event = load_stdin_event()
    command = extract_bash_command(event)

    # Self-filter: only act on git commit / push commands.
    if not is_git_commit_or_push(command):
        return 0

    # Gather staged files and evaluate scope predicates.
    staged_files = get_staged_files()
    predicates = evaluate_predicates(staged_files)

    # Run all checks, collecting failures.
    failures: list[CheckFailure] = []
    check_always_required(failures)
    check_conditional_artifacts(predicates, failures)
    check_pr_readiness(predicates, failures)

    if not failures:
        return 0

    # De-duplicate failures by (category, name).
    seen: set[tuple[str, str]] = set()
    deduped: list[CheckFailure] = []
    for f in failures:
        key = (f.category, f.name)
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    report = build_failure_report(command, deduped, predicates, staged_files)
    print(report, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
