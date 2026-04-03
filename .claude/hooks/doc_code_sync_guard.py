#!/usr/bin/env python3
"""
doc-code-sync-guard
===================
Hook:    Stop (SubagentStop)
Layer:   D — Audit Impact
Action:  warn
Defined: .claude/workflows/packages/hooks.yaml

Reads the `doc_code_sync_status` artifact and warns when doc/code drift is
detected — i.e. code was changed without corresponding documentation updates
or documentation was updated without matching code changes.

This is a warning-only gate (exit 1).  It does not block the agent stop.
However, an unresolved `drift_detected = true` WILL block at
pre-pr-governance-gate before any commit or push.

Escalation target: doc-code-sync-auditor subagent.

Checks
------
drift_detected
    Must be false.  If true, at least one of the following drift types
    has been identified:

    code_without_doc
        Code files (layer2/, adapters, config) changed without a
        corresponding update to any canonical document from the
        documentation set (CLAUDE.md §2.1).

    doc_without_code
        Canonical documentation updated with new implementation claims
        but no corresponding code change can be verified.

    both
        Both directions of drift are present simultaneously.

Exit codes
----------
  0  No drift detected — clean pass.
  1  Drift detected — warn and flag for doc-code-sync-auditor escalation.
     (Never exits 2; this gate warns, it does not block.)

Blocking conditions raised (from blocking-conditions.yaml):
  doc_code_drift_unresolved   (flagged for pre-pr-governance-gate, not here)

Expected artifact schema (.claude/run/artifacts/doc_code_sync_status.json):
  {
    "artifact": "doc_code_sync_status",
    "produced_by": "doc-code-sync-check",
    "session": "<id>",
    "timestamp": "<iso8601>",
    "data": {
      "drift_detected": true | false,
      "drift_type": "code_without_doc" | "doc_without_code" | "both" | null,
      "verdict": "pass" | "drift",
      "affected_code_files": ["<path>", ...],
      "affected_doc_files": ["<path>", ...],
      "canonical_docs_requiring_review": ["<doc_name>", ...],
      "notes": "<optional free-text explanation>"
    }
  }
"""

import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "lib"))

from artifact_store import ArtifactMalformed, ArtifactNotFound, read_artifact  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOOK_NAME = "doc-code-sync-guard"
ARTIFACT_NAME = "doc_code_sync_status"

# Canonical documents that could require review when drift is detected.
# Order matches CLAUDE.md §2.1 priority.
CANONICAL_DOC_SET = (
    "README_v1.md",
    "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
    "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
    "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
    "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
    "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
    "README_LAYER2.md",
)

# Human-readable labels for each drift type.
_DRIFT_TYPE_LABELS = {
    "code_without_doc": "Code changed without documentation alignment",
    "doc_without_code": "Documentation updated without verified code support",
    "both": "Bidirectional drift — code and documentation are out of sync in both directions",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_stdin_event() -> dict:
    """Read and parse the JSON event payload from stdin. Returns {} on failure."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def format_file_list(label: str, files: list) -> list[str]:
    """Format a list of affected files under a label."""
    if not files:
        return []
    lines = [f"  {label}:"]
    for f in files:
        lines.append(f"    - {f}")
    return lines


def format_doc_list(docs: list) -> list[str]:
    """Format the list of canonical documents requiring review."""
    if not docs:
        return []
    lines = ["  Canonical documents requiring review:"]
    for d in docs:
        flag = "  *" if d in CANONICAL_DOC_SET else "   "
        lines.append(f"  {flag} {d}")
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    load_stdin_event()  # consume stdin; Stop payload is not used by this hook

    # --- Load artifact ---
    try:
        data = read_artifact(ARTIFACT_NAME)
    except ArtifactNotFound:
        print(
            f"[{HOOK_NAME}] WARNING: artifact '{ARTIFACT_NAME}' not found.\n"
            "  The doc-code-sync skill has not produced its status yet.\n"
            "  Doc/code drift cannot be evaluated at this stop point.\n"
            "  If code or documentation was changed this session, ensure\n"
            "  the doc-code-sync-check step has run before committing.",
            file=sys.stderr,
        )
        return 1
    except ArtifactMalformed as exc:
        print(
            f"[{HOOK_NAME}] ERROR: artifact '{ARTIFACT_NAME}' is malformed.\n"
            f"  {exc}\n"
            "  Cannot evaluate doc/code sync status.",
            file=sys.stderr,
        )
        return 1

    # --- Check drift_detected ---
    drift_detected = data.get("drift_detected", False)

    if not drift_detected:
        # Clean pass — no drift.
        return 0

    # --- Build warning message ---
    drift_type = data.get("drift_type") or "unknown"
    drift_label = _DRIFT_TYPE_LABELS.get(drift_type, drift_type)
    verdict = data.get("verdict", "drift")
    affected_code = data.get("affected_code_files") or []
    affected_docs = data.get("affected_doc_files") or []
    canonical_review = data.get("canonical_docs_requiring_review") or []
    notes = data.get("notes", "")

    lines = [
        f"[{HOOK_NAME}] Doc/code drift detected.",
        "",
        f"  Drift type:  {drift_label}",
        f"  Verdict:     {verdict}",
        "",
    ]

    if drift_type in ("code_without_doc", "both"):
        lines.extend(format_file_list("Code files changed without doc alignment", affected_code))
        if affected_code:
            lines.append("")

    if drift_type in ("doc_without_code", "both"):
        lines.extend(format_file_list("Documentation files without verified code support", affected_docs))
        if affected_docs:
            lines.append("")

    if canonical_review:
        lines.extend(format_doc_list(canonical_review))
        lines.append("")

    if notes:
        lines.append(f"  Notes: {notes}")
        lines.append("")

    lines.append("─" * 60)
    lines.append("WARNING — raising: doc_code_drift_unresolved")
    lines.append("")
    lines.append(
        "This is a warning gate.  Agent stop is not blocked.\n"
        "However, doc_code_drift_unresolved WILL block at pre-pr-governance-gate\n"
        "before any commit or push (CLAUDE.md §11)."
    )
    lines.append("")
    lines.append(
        "Required actions:\n"
        "  1. Escalate to doc-code-sync-auditor for a structured drift assessment.\n"
        "  2. Align all changed code with the canonical documentation set (CLAUDE.md §2.1).\n"
        "  3. Re-run doc-code-sync-check to produce a clean doc_code_sync_status\n"
        "     artifact before attempting commit or push."
    )
    if canonical_review:
        lines.append("")
        lines.append(
            "  Documents marked (*) are in the canonical current-state set\n"
            "  and have mandatory review obligations under CLAUDE.md §11."
        )

    print("\n".join(lines), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
