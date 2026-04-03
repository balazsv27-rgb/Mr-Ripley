#!/usr/bin/env python3
"""
adapter-schema-guard
====================
Hook:    PostToolUse  (matcher: Edit | Write)
Layer:   C — Runtime Schema Integrity
Action:  warn_or_block
Defined: .claude/workflows/packages/hooks.yaml

Enforces that all adapter logic is registry-driven.  No hardcoded series
logic or implicit series interpretation is permitted in adapter files.

Scope predicate: adapter_registry_scope
  - layer2/adapters/**
  - layer2/config/series_registry.json   (the registry itself — exempt)
  - layer2/config/registry.py            (the registry reader — exempt)

Checks
------
registry_driven
    Adapter files must import from layer2.config.registry or otherwise
    reference the registry.  If no registry usage is found the adapter is
    operating without the canonical series source.

hardcoded_series_detected
    Inline series ID lists, dicts, or per-series conditional branches found
    in adapter code.  All series selection must be delegated to the registry.

implicit_interpretation_detected
    Inline tier, staleness, frequency, or blocks_snapshot assignments found
    in adapter code.  All series metadata must come from the registry.

Exit codes
----------
  0  No violations — allow processing to continue.
  1  Warn — hardcoded or implicit patterns detected alongside registry use.
  2  Block — adapter has no registry usage at all (contract boundary violation).

Blocking conditions raised (from blocking-conditions.yaml):
  registry_violation
  schema_drift_detected

Artifact written: .claude/run/artifacts/adapter_schema_verdict.json
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

HOOK_NAME = "adapter-schema-guard"
ARTIFACT_NAME = "adapter_schema_verdict"
PRODUCER_STEP = "adapter-schema-check"

# Files that ARE the registry — exempt from all violation checks.
REGISTRY_EXEMPT_SUFFIXES = (
    "series_registry.json",
    os.path.join("config", "registry.py"),
    "config/registry.py",
)

# Path prefixes that are in adapter_registry_scope.
ADAPTER_SCOPE_PREFIXES = (
    "layer2/adapters/",
    "layer2\\adapters\\",
    "layer2/config/",
    "layer2\\config\\",
)

# Files under these path prefixes are governance/tooling — skip entirely.
SKIP_PREFIXES = (
    ".claude/",
    ".claude\\",
)

# File extensions that contain source code worth scanning.
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".sql", ".sh", ".bash",
}

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------


class PatternGroup(NamedTuple):
    name: str         # violation key name
    patterns: list    # compiled re.Pattern objects
    label: str        # human-readable label for output


# --- Registry-usage patterns (positive check) ---
# The adapter must reference the registry in at least one of these ways.
_REGISTRY_USAGE_PATTERNS = [
    re.compile(r'\bfrom\s+layer2\.config\.registry\b', re.IGNORECASE),
    re.compile(r'\bimport\s+layer2\.config\.registry\b', re.IGNORECASE),
    re.compile(r'\bget_registry\s*\(', re.IGNORECASE),
    re.compile(r'\bseries_registry\.json\b', re.IGNORECASE),
    re.compile(r'\bregistry\.py\b', re.IGNORECASE),
    re.compile(r'\bload_registry\s*\(', re.IGNORECASE),
]

# --- Hardcoded series list / dict patterns ---
# Detects inline data structures that enumerate series IDs, bypassing the
# registry.  Patterns look for assignments of list/dict literals that contain
# series ID strings.
_HARDCODED_SERIES_PATTERNS = [
    # Python list/tuple literal with quoted uppercase FRED IDs (≥2 entries)
    # e.g.  SERIES = ["DFII10", "DGS10", "VIXCLS"]
    re.compile(
        r'''(?:SERIES|series_ids?|SERIES_LIST|TICKERS|FRED_IDS?)\s*=\s*[\[\(]\s*['"][A-Z][A-Z0-9]{2,9}['"]''',
        re.IGNORECASE,
    ),
    # Python dict literal mapping series IDs to metadata inline
    # e.g.  SERIES_MAP = {"DFII10": {...}, "DGS10": {...}}
    re.compile(
        r'''(?:SERIES_MAP|SERIES_CONFIG|series_map|series_config)\s*=\s*\{''',
        re.IGNORECASE,
    ),
    # Per-series conditional branch: if series_id == "DFII10":
    re.compile(
        r'''\bif\b[^:]*\bseries_id\b[^:]*==\s*['"][A-Z][A-Z0-9]{2,9}['"]''',
        re.IGNORECASE,
    ),
    # elif series_id == "..."
    re.compile(
        r'''\belif\b[^:]*\bseries_id\b[^:]*==\s*['"][A-Z][A-Z0-9]{2,9}['"]''',
        re.IGNORECASE,
    ),
    # Hardcoded known named series outside the registry file
    # e.g.  series_id = "gold_price_proxy"
    re.compile(
        r'''\bseries_id\s*=\s*['"](?:gold_price_proxy|rates_vol_stress_move|gld_holdings)['"]''',
        re.IGNORECASE,
    ),
]

# --- Implicit interpretation patterns ---
# Detects series metadata defined inline rather than loaded from the registry.
_IMPLICIT_INTERPRETATION_PATTERNS = [
    # Inline tier assignment: tier = 1  /  "tier": 1  /  tier=2
    re.compile(r'''\btier\s*[=:]\s*[12]\b'''),
    # Inline staleness_days assignment: staleness_days = 3
    re.compile(r'''\bstaleness_days\s*[=:]\s*\d+\b''', re.IGNORECASE),
    # Inline blocks_snapshot assignment
    re.compile(r'''\bblocks_snapshot\s*[=:]\s*(?:True|False|true|false)\b'''),
    # Inline frequency assignment to D or M (common registry fields)
    re.compile(r'''\bfrequency\s*[=:]\s*['"][DM]['"]''', re.IGNORECASE),
    # Inline include_in_snapshot assignment
    re.compile(r'''\binclude_in_snapshot\s*[=:]\s*(?:True|False|true|false)\b'''),
]

VIOLATION_GROUPS = [
    PatternGroup(
        name="hardcoded_series",
        patterns=_HARDCODED_SERIES_PATTERNS,
        label="Hardcoded series logic",
    ),
    PatternGroup(
        name="implicit_interpretation",
        patterns=_IMPLICIT_INTERPRETATION_PATTERNS,
        label="Implicit series interpretation",
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


def normalise(file_path: str) -> str:
    return file_path.replace("\\", "/")


def is_in_adapter_scope(file_path: str) -> bool:
    """Return True if the file is within adapter_registry_scope."""
    norm = normalise(file_path)
    return any(norm.startswith(p.replace("\\", "/")) for p in ADAPTER_SCOPE_PREFIXES)


def is_registry_exempt(file_path: str) -> bool:
    """Return True for registry source files that are exempt from violation checks."""
    norm = normalise(file_path)
    for suffix in REGISTRY_EXEMPT_SUFFIXES:
        if norm.endswith(suffix.replace("\\", "/")):
            return True
    return False


def is_skip_file(file_path: str) -> bool:
    """Return True for governance/tooling files that should not be scanned."""
    norm = normalise(file_path)
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


class Match(NamedTuple):
    line_no: int
    line_text: str
    pattern_desc: str


def scan_content(content: str, patterns: list) -> list[Match]:
    """Scan content line-by-line for all patterns. Returns list of Match."""
    matches = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        # Skip comment lines — false positives in docstrings / inline docs.
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        for pat in patterns:
            if pat.search(line):
                matches.append(Match(
                    line_no=line_no,
                    line_text=stripped,
                    pattern_desc=pat.pattern,
                ))
                break  # one match per line per group is sufficient
    return matches


def has_registry_usage(content: str) -> bool:
    """Return True if the content shows any evidence of registry usage."""
    for pat in _REGISTRY_USAGE_PATTERNS:
        if pat.search(content):
            return True
    return False


def format_matches(matches: list[Match], file_path: str) -> list[str]:
    """Format match list into human-readable lines."""
    return [f"  {file_path}:{m.line_no}: {m.line_text[:120]}" for m in matches]


# ---------------------------------------------------------------------------
# Artifact helpers
# ---------------------------------------------------------------------------


def _write_verdict(
    file_path: str,
    scanned: bool,
    registry_driven: bool,
    hardcoded_series_detected: bool,
    implicit_interpretation_detected: bool,
    violations: list[dict],
) -> None:
    write_artifact(
        ARTIFACT_NAME,
        {
            "file_path": file_path,
            "scanned": scanned,
            "registry_driven": registry_driven,
            "hardcoded_series_detected": hardcoded_series_detected,
            "implicit_interpretation_detected": implicit_interpretation_detected,
            "violations": violations,
        },
        produced_by=PRODUCER_STEP,
    )


def _write_clean_verdict(file_path: str, scanned: bool) -> None:
    _write_verdict(
        file_path=file_path,
        scanned=scanned,
        registry_driven=True,
        hardcoded_series_detected=False,
        implicit_interpretation_detected=False,
        violations=[],
    )


def _build_violation_list(
    details: dict[str, list[Match]],
    file_path: str,
) -> list[dict]:
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    event = load_stdin_event()

    file_path = extract_file_path(event)
    if not file_path:
        _write_clean_verdict(file_path="<unknown>", scanned=False)
        return 0

    if is_skip_file(file_path):
        _write_clean_verdict(file_path=file_path, scanned=False)
        return 0

    if not is_in_adapter_scope(file_path):
        # File is outside adapter_registry_scope — not this guard's concern.
        _write_clean_verdict(file_path=file_path, scanned=False)
        return 0

    if is_registry_exempt(file_path):
        # series_registry.json and registry.py are the registry themselves.
        _write_clean_verdict(file_path=file_path, scanned=False)
        return 0

    if not is_scannable(file_path):
        _write_clean_verdict(file_path=file_path, scanned=False)
        return 0

    content = read_file_content(file_path)
    if content is None:
        print(
            f"[{HOOK_NAME}] WARNING: could not read '{file_path}' for scanning.",
            file=sys.stderr,
        )
        _write_clean_verdict(file_path=file_path, scanned=False)
        return 0

    # --- Check 1: registry_driven (positive presence check) ---
    registry_driven = has_registry_usage(content)

    # --- Check 2 & 3: violation pattern scans ---
    violation_details: dict[str, list[Match]] = {}
    for group in VIOLATION_GROUPS:
        hits = scan_content(content, group.patterns)
        if hits:
            violation_details[group.name] = hits

    hardcoded_series_detected = "hardcoded_series" in violation_details
    implicit_interpretation_detected = "implicit_interpretation" in violation_details

    any_violation = (
        not registry_driven
        or hardcoded_series_detected
        or implicit_interpretation_detected
    )

    _write_verdict(
        file_path=file_path,
        scanned=True,
        registry_driven=registry_driven,
        hardcoded_series_detected=hardcoded_series_detected,
        implicit_interpretation_detected=implicit_interpretation_detected,
        violations=_build_violation_list(violation_details, file_path),
    )

    if not any_violation:
        return 0

    # Build the human-readable error/warning message.
    lines = [f"[{HOOK_NAME}] Adapter registry discipline violation(s) in: {file_path}"]
    lines.append("")

    if not registry_driven:
        lines.append("  [no_registry_usage]")
        lines.append(
            "  Adapter file has no import from layer2.config.registry and no\n"
            "  reference to series_registry.json or get_registry().\n"
            "  All series metadata MUST come from the registry (CLAUDE.md §8)."
        )
        lines.append("")

    if hardcoded_series_detected:
        lines.append("  [hardcoded_series]")
        lines.append(
            "  Hardcoded series ID list, dict, or per-series conditional branch\n"
            "  detected.  Series selection MUST be delegated to series_registry.json\n"
            "  via layer2.config.registry (CLAUDE.md §8)."
        )
        lines.extend(format_matches(violation_details["hardcoded_series"], file_path))
        lines.append("")

    if implicit_interpretation_detected:
        lines.append("  [implicit_interpretation]")
        lines.append(
            "  Inline series metadata (tier, staleness_days, blocks_snapshot,\n"
            "  frequency, include_in_snapshot) detected in adapter code.\n"
            "  All series metadata MUST come from the registry (CLAUDE.md §8)."
        )
        lines.extend(format_matches(violation_details["implicit_interpretation"], file_path))
        lines.append("")

    lines.append("─" * 60)

    # Determine severity.
    # Block (exit 2) when the adapter has no registry usage at all — this is a
    # fundamental contract boundary violation (CLAUDE.md §8, §16).
    # Warn (exit 1) when violations are detected alongside registry usage.
    if not registry_driven:
        lines.append("BLOCKED — raising: registry_violation")
        lines.append(
            "Resolution: import and use get_registry() from layer2.config.registry.\n"
            "No adapter may select or interpret series outside the registry."
        )
        print("\n".join(lines), file=sys.stderr)
        return 2
    else:
        lines.append("WARNING — raising: schema_drift_detected")
        lines.append(
            "Resolution: remove hardcoded series lists / inline metadata from\n"
            "adapter code.  Delegate all series selection and metadata to the\n"
            "registry.  This warning becomes a block if unresolved before PR gate."
        )
        print("\n".join(lines), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
