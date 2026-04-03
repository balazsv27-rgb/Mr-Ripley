#!/usr/bin/env python3
"""
role-matched-doc-guard
======================
Hook:    Stop (SubagentStop)
Layer:   A — Semantic Normalization
Action:  warn_or_block
Defined: .claude/workflows/packages/hooks.yaml

Reads the `role_citation_verdict` artifact and checks for two violation types:

  role_mismatch
      A canonical document was cited for a claim whose role belongs to a
      different canonical document (CLAUDE.md §2.2, §2.4).

  readme_layer2_override
      README_LAYER2.md was used to override a more role-specific canonical
      document on implementation state, architecture boundaries, or limitations
      (CLAUDE.md §2.4 critical rule).

Exit codes
----------
  0  No violations — allow the agent to stop normally.
  1  Violations present, no strong-claim attachment — warn, do not block.
  2  At least one violation is attached to a strong claim (CLAUDE.md §10) — block.

Blocking conditions raised (from blocking-conditions.yaml):
  role_mismatch_for_strong_claim
  readme_layer2_used_as_override
  canonical_conflict_unresolved

Expected artifact schema (.claude/run/artifacts/role_citation_verdict.json):
  {
    "artifact": "role_citation_verdict",
    "produced_by": "route-claims-by-role",
    "session": "<id>",
    "timestamp": "<iso8601>",
    "data": {
      "violations": [
        {
          "type": "role_mismatch" | "readme_layer2_override",
          "claim": "<claim text>",
          "cited_doc": "<document that was used>",
          "correct_doc": "<document that should have been used>",
          "strong_claim": true | false
        }
      ],
      "verdict": "pass" | "warn" | "block"
    }
  }

  violations may also be a flat list of strings for simple cases:
    ["role_mismatch", "readme_layer2_override"]
  In that case strong_claim defaults to False and the exit code is 1 (warn).
"""

import json
import os
import sys

# Ensure lib/ is importable regardless of working directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "lib"))

from artifact_store import ArtifactMalformed, ArtifactNotFound, read_artifact

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOOK_NAME = "role-matched-doc-guard"
ARTIFACT_NAME = "role_citation_verdict"

# Violation types this hook is responsible for checking
WATCHED_VIOLATION_TYPES = frozenset({"role_mismatch", "readme_layer2_override"})

# Map from violation type to the blocking condition id it raises
BLOCKING_CONDITION_MAP = {
    "role_mismatch": "role_mismatch_for_strong_claim",
    "readme_layer2_override": "readme_layer2_used_as_override",
}

# Strong-claim phrases from CLAUDE.md §10 — used to detect if the violation
# text itself describes a forbidden claim even when the artifact flag is absent
STRONG_CLAIM_PHRASES = (
    "layer 3 is implemented",
    "production-ready",
    "production ready",
    "execution is available",
    "decisions are automated",
    "externally validated",
    "system is production",
    "live execution",
)


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


def normalize_violations(raw_violations: list) -> list[dict]:
    """
    Coerce violations into a uniform list of dicts, each with at minimum:
      - type (str)
      - strong_claim (bool)
    Supports both flat string lists and structured object lists.
    """
    normalized = []
    for item in raw_violations:
        if isinstance(item, str):
            normalized.append({"type": item, "strong_claim": False})
        elif isinstance(item, dict):
            # Backfill strong_claim from claim text if not explicitly set
            entry = dict(item)
            if "strong_claim" not in entry:
                claim_text = str(entry.get("claim", "")).lower()
                entry["strong_claim"] = any(
                    phrase in claim_text for phrase in STRONG_CLAIM_PHRASES
                )
            normalized.append(entry)
    return normalized


def filter_active(violations: list[dict]) -> list[dict]:
    """Return only violations this hook is responsible for."""
    return [v for v in violations if v.get("type") in WATCHED_VIOLATION_TYPES]


def format_violation(v: dict, index: int) -> list[str]:
    """Format a single violation as a block of lines."""
    lines = [f"  [{index}] type:       {v.get('type', 'unknown')}"]
    if v.get("claim"):
        lines.append(f"       claim:      {v['claim']}")
    if v.get("cited_doc"):
        lines.append(f"       cited_doc:  {v['cited_doc']}")
    if v.get("correct_doc"):
        lines.append(f"       correct_doc:{v['correct_doc']}")
    if v.get("strong_claim"):
        lines.append("       *** STRONG CLAIM ATTACHED ***")
    return lines


def collect_blocking_conditions(violations: list[dict]) -> list[str]:
    """Return the set of blocking condition ids raised by the active violations."""
    ids = set()
    for v in violations:
        vtype = v.get("type")
        if vtype in BLOCKING_CONDITION_MAP:
            ids.add(BLOCKING_CONDITION_MAP[vtype])
        # canonical_conflict_unresolved fires when both violation types are present
    if len({v.get("type") for v in violations} & WATCHED_VIOLATION_TYPES) > 1:
        ids.add("canonical_conflict_unresolved")
    return sorted(ids)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    load_stdin_event()  # consume stdin; payload unused at this hook stage

    # --- Load artifact ---
    try:
        data = read_artifact(ARTIFACT_NAME)
    except ArtifactNotFound:
        print(
            f"[{HOOK_NAME}] WARNING: artifact '{ARTIFACT_NAME}' not found.\n"
            "  The role-citation skill (route-claims-by-role) has not produced\n"
            "  its verdict yet. This gate cannot evaluate role compliance.\n"
            "  Proceed with caution — role-citation checks are unenforced.",
            file=sys.stderr,
        )
        return 1
    except ArtifactMalformed as exc:
        print(
            f"[{HOOK_NAME}] ERROR: artifact '{ARTIFACT_NAME}' is malformed.\n"
            f"  {exc}\n"
            "  Cannot evaluate role-citation compliance.",
            file=sys.stderr,
        )
        return 1

    # --- Extract and filter violations ---
    raw_violations = data.get("violations", [])
    all_violations = normalize_violations(raw_violations)
    active = filter_active(all_violations)

    if not active:
        return 0  # clean pass

    has_strong_claim = any(v.get("strong_claim") for v in active)
    blocking_ids = collect_blocking_conditions(active)

    # --- Build output message ---
    lines = [f"[{HOOK_NAME}] Role-citation violations detected ({len(active)} active):"]
    lines.append("")
    for i, v in enumerate(active, start=1):
        lines.extend(format_violation(v, i))
        lines.append("")

    if has_strong_claim:
        lines.append("─" * 60)
        lines.append("BLOCKED — strong claim attached to role-citation violation.")
        lines.append("")
        lines.append(
            "One or more violations involve a strong claim (CLAUDE.md §10).\n"
            "Role-mismatched citations for strong claims are not permitted.\n"
            "Resolution: replace the citation with the role-correct canonical\n"
            "document as specified in correct_doc above."
        )
        lines.append("")
        lines.append(f"Blocking condition(s) raised: {', '.join(blocking_ids)}")
        lines.append(
            "These conditions must be resolved before pre-pr-governance-gate will pass."
        )
        print("\n".join(lines), file=sys.stderr)
        return 2

    # Warn path
    lines.append("─" * 60)
    lines.append("WARNING — role-citation violations require resolution.")
    lines.append("")
    lines.append(
        "No strong claim is attached, so this is a warning rather than a block.\n"
        "However, these violations WILL block at pre-pr-governance-gate if\n"
        "role_citation_verdict is not cleared before commit or push."
    )
    lines.append("")
    lines.append(
        "Required action: replace each mismatched citation with the\n"
        "role-correct canonical document and re-run route-claims-by-role."
    )
    if blocking_ids:
        lines.append(f"Conditions to resolve: {', '.join(blocking_ids)}")
    print("\n".join(lines), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
