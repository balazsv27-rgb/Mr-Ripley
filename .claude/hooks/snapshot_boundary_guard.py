#!/usr/bin/env python3
"""
snapshot-boundary-guard
=======================
Hook:    PostToolUse  (matcher: Edit | Write)
Layer:   C — Runtime Schema Integrity
Action:  block_on_match
Defined: .claude/workflows/packages/hooks.yaml

Scans every file written or edited for three categories of snapshot-boundary
violation, then writes the `runtime_boundary_verdict` artifact and blocks if
any violation is detected.

Violation categories
--------------------
raw_observation_access_detected
    Non-layer2 code reads the `observations` table directly, bypassing the
    snapshot boundary.  Layer-2 files are exempt — they own that table.

latest_snapshot_misuse_detected
    Code uses the string literal 'latest' as a snapshot_id value (e.g. in a
    WHERE clause or JSON key), which is explicitly forbidden by CLAUDE.md §6.3.
    Reading latest_snapshot.json as the published output pointer is allowed;
    querying/indexing by snapshot_id='latest' is not.

layer2_storage_coupling_detected
    Non-layer2 code directly imports `layer2.db`, references `layer2_truth.db`,
    or opens a SQLite connection to the Layer-2 internal database, creating a
    storage-coupling dependency that bypasses the snapshot contract.
    Layer-2 files are exempt.

Exit codes
----------
  0  No violations — allow processing to continue.
  2  One or more violations detected — block (raises snapshot_boundary_violation).

Blocking conditions raised (from blocking-conditions.yaml):
  snapshot_boundary_violation
  raw_observations_used_in_layer3

Artifact written: .claude/run/artifacts/runtime_boundary_verdict.json
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "lib"))

from artifact_store import write_artifact  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOOK_NAME = "snapshot-boundary-guard"
ARTIFACT_NAME = "runtime_boundary_verdict"
PRODUCER_STEP = "runtime-boundary-check"

# Files under these path prefixes are Layer-2 — exempt from
# raw_observation_access and layer2_storage_coupling checks.
LAYER2_PREFIXES = (
    "layer2/",
    "layer2\\",
    os.path.join("layer2", ""),
)

# Files under these path prefixes are governance/tooling — skip entirely.
SKIP_PREFIXES = (
    ".claude/",
    ".claude\\",
)

# File extensions that contain source code worth scanning.
# Documentation-only files are skipped for code-pattern checks.
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".sql", ".sh", ".bash",
}

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

class PatternGroup(NamedTuple):
    name: str           # human label for messages
    patterns: list      # compiled re.Pattern objects
    exempt_layer2: bool # if True, skip for layer2/ files


# Patterns that indicate raw observations table access from downstream code.
_RAW_OBS_PATTERNS = [
    # SQL: SELECT / query directly against observations table
    re.compile(r'\bFROM\s+observations\b', re.IGNORECASE),
    re.compile(r'\bJOIN\s+observations\b', re.IGNORECASE),
    # Python: execute() call with observations in the SQL string
    re.compile(r'''(?:execute|executemany)\s*\(\s*['"][^'"]*\bobservations\b''', re.IGNORECASE),
    # Python: string literal containing FROM observations
    re.compile(r'''['"][^'"]*FROM\s+observations\b''', re.IGNORECASE),
]

# Patterns that indicate the forbidden use of 'latest' as a snapshot_id.
_LATEST_SNAPSHOT_PATTERNS = [
    # SQL: WHERE snapshot_id = 'latest'
    re.compile(r'''\bsnapshot_id\s*[=!]=\s*['"]latest['"]''', re.IGNORECASE),
    re.compile(r'''WHERE\b[^;'"]*\bsnapshot_id\b[^;'"]*['"]latest['"]''', re.IGNORECASE),
    # Python/JSON: "snapshot_id": "latest"  or  snapshot_id="latest"
    re.compile(r'''['"]snapshot_id['"]\s*:\s*['"]latest['"]''', re.IGNORECASE),
    re.compile(r'''\bsnapshot_id\s*=\s*['"]latest['"]''', re.IGNORECASE),
    # Dict lookup: .get("snapshot_id", "latest")  or  ["snapshot_id"] == "latest"
    re.compile(r'''\["snapshot_id"\]\s*==\s*['"]latest['"]''', re.IGNORECASE),
]

# Patterns that indicate direct Layer-2 storage coupling from downstream code.
_L2_COUPLING_PATTERNS = [
    # Python imports of layer2.db
    re.compile(r'\bfrom\s+layer2\.db\b', re.IGNORECASE),
    re.compile(r'\bimport\s+layer2\.db\b', re.IGNORECASE),
    # Direct reference to the Layer-2 DB file
    re.compile(r'\blayer2_truth\.db\b', re.IGNORECASE),
    # sqlite3.connect() targeting layer2 path
    re.compile(r'''sqlite3\.connect\s*\(\s*['"][^'"]*layer2''', re.IGNORECASE),
]

PATTERN_GROUPS = [
    PatternGroup(
        name="raw_observation_access",
        patterns=_RAW_OBS_PATTERNS,
        exempt_layer2=True,
    ),
    PatternGroup(
        name="latest_snapshot_misuse",
        patterns=_LATEST_SNAPSHOT_PATTERNS,
        exempt_layer2=False,  # forbidden everywhere
    ),
    PatternGroup(
        name="layer2_storage_coupling",
        patterns=_L2_COUPLING_PATTERNS,
        exempt_layer2=True,
    ),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_stdin_event() -> dict:
    """Parse the PostToolUse JSON payload from stdin."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def extract_file_path(event: dict) -> str | None:
    """Pull the affected file path from the tool event."""
    tool_input = event.get("tool_input", {})
    return tool_input.get("file_path") or tool_input.get("filePath")


def is_layer2_file(file_path: str) -> bool:
    """Return True if the file is part of the Layer-2 implementation."""
    norm = file_path.replace("\\", "/")
    return norm.startswith("layer2/") or "/layer2/" in norm


def is_skip_file(file_path: str) -> bool:
    """Return True for governance/tooling files that should not be scanned."""
    norm = file_path.replace("\\", "/")
    return norm.startswith(".claude/")


def is_scannable(file_path: str) -> bool:
    """Return True if this file type warrants code-pattern scanning."""
    return Path(file_path).suffix.lower() in CODE_EXTENSIONS


def read_file_content(file_path: str) -> str | None:
    """Read the current file content. Returns None if unreadable."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def extract_written_content(event: dict) -> str:
    """
    Extract the text that was written in this specific tool call.
    For Edit: returns new_string (the inserted text).
    For Write: returns content.
    Falls back to empty string if unavailable.
    """
    tool_input = event.get("tool_input", {})
    tool_name = event.get("tool_name", "")
    if tool_name == "Edit":
        return tool_input.get("new_string", "")
    if tool_name == "Write":
        return tool_input.get("content", "")
    return ""


class Match(NamedTuple):
    line_no: int
    line_text: str
    pattern_desc: str


def scan_content(content: str, patterns: list) -> list[Match]:
    """Scan content line-by-line for all patterns. Returns list of Match."""
    matches = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        for pat in patterns:
            if pat.search(line):
                matches.append(Match(
                    line_no=line_no,
                    line_text=line.strip(),
                    pattern_desc=pat.pattern,
                ))
                break  # one match per line per group is enough
    return matches


def format_matches(matches: list[Match], file_path: str) -> list[str]:
    """Format match list into human-readable lines."""
    lines = []
    for m in matches:
        lines.append(f"  {file_path}:{m.line_no}: {m.line_text[:120]}")
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    event = load_stdin_event()

    file_path = extract_file_path(event)
    if not file_path:
        # No file path in event — nothing to scan, pass silently.
        _write_clean_verdict(file_path="<unknown>", scanned=False)
        return 0

    if is_skip_file(file_path):
        _write_clean_verdict(file_path=file_path, scanned=False)
        return 0

    if not is_scannable(file_path):
        _write_clean_verdict(file_path=file_path, scanned=False)
        return 0

    # Read the full current file content (post-edit).
    content = read_file_content(file_path)
    if content is None:
        # File unreadable — warn but do not block (could be a new file mid-write).
        print(
            f"[{HOOK_NAME}] WARNING: could not read '{file_path}' for scanning.",
            file=sys.stderr,
        )
        _write_clean_verdict(file_path=file_path, scanned=False)
        return 0

    layer2 = is_layer2_file(file_path)

    # Run each pattern group and collect violations.
    violation_details: dict[str, list[Match]] = {}
    for group in PATTERN_GROUPS:
        if group.exempt_layer2 and layer2:
            continue
        hits = scan_content(content, group.patterns)
        if hits:
            violation_details[group.name] = hits

    raw_obs_detected = "raw_observation_access" in violation_details
    latest_detected = "latest_snapshot_misuse" in violation_details
    coupling_detected = "layer2_storage_coupling" in violation_details

    any_violation = raw_obs_detected or latest_detected or coupling_detected

    # Always write the artifact (hooks.yaml reads it; other steps may too).
    verdict_data = {
        "file_path": file_path,
        "scanned": True,
        "layer2_file": layer2,
        "raw_observation_access_detected": raw_obs_detected,
        "latest_snapshot_misuse_detected": latest_detected,
        "layer2_storage_coupling_detected": coupling_detected,
        "violations": _build_violation_list(violation_details, file_path),
    }
    write_artifact(ARTIFACT_NAME, verdict_data, produced_by=PRODUCER_STEP)

    if not any_violation:
        return 0

    # Build and emit the blocking message.
    lines = [f"[{HOOK_NAME}] Snapshot-boundary violation(s) detected in: {file_path}"]
    lines.append("")

    if raw_obs_detected:
        lines.append("  [raw_observation_access]")
        lines.append(
            "  Non-layer2 code reads the `observations` table directly.\n"
            "  Downstream code MUST read only from published snapshots (CLAUDE.md §6.1)."
        )
        lines.extend(format_matches(violation_details["raw_observation_access"], file_path))
        lines.append("")

    if latest_detected:
        lines.append("  [latest_snapshot_misuse]")
        lines.append(
            "  Code uses 'latest' as a snapshot_id value.\n"
            "  snapshot_id='latest' is explicitly forbidden (CLAUDE.md §6.3).\n"
            "  Use a concrete snapshot_id from the snapshots table or latest_snapshot.json."
        )
        lines.extend(format_matches(violation_details["latest_snapshot_misuse"], file_path))
        lines.append("")

    if coupling_detected:
        lines.append("  [layer2_storage_coupling]")
        lines.append(
            "  Non-layer2 code directly imports layer2.db or references layer2_truth.db.\n"
            "  Downstream code MUST NOT couple to Layer-2 storage (CLAUDE.md §6.1)."
        )
        lines.extend(format_matches(violation_details["layer2_storage_coupling"], file_path))
        lines.append("")

    lines.append("─" * 60)
    lines.append("BLOCKED — raising: snapshot_boundary_violation")
    lines.append(
        "Resolution: remove all direct observation access, 'latest' snapshot_id\n"
        "references, and layer2.db imports from non-layer2 code."
    )
    print("\n".join(lines), file=sys.stderr)
    return 2


def _build_violation_list(details: dict[str, list[Match]], file_path: str) -> list[dict]:
    """Convert internal match structures into the artifact violations list."""
    out = []
    for category, matches in details.items():
        for m in matches:
            out.append({
                "type": category,
                "file": file_path,
                "line": m.line_no,
                "text": m.line_text[:200],
            })
    return out


def _write_clean_verdict(file_path: str, scanned: bool) -> None:
    """Write a clean (no-violation) verdict artifact."""
    write_artifact(
        ARTIFACT_NAME,
        {
            "file_path": file_path,
            "scanned": scanned,
            "layer2_file": is_layer2_file(file_path) if file_path != "<unknown>" else False,
            "raw_observation_access_detected": False,
            "latest_snapshot_misuse_detected": False,
            "layer2_storage_coupling_detected": False,
            "violations": [],
        },
        produced_by=PRODUCER_STEP,
    )


if __name__ == "__main__":
    sys.exit(main())
