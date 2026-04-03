#!/usr/bin/env python3
"""
live-readiness-claim-blocker
============================
Hook:    PostToolUse  (matcher: Edit | Write)
Layer:   B — Architecture Phase Contract
Action:  block_on_match
Defined: .claude/workflows/packages/hooks.yaml

Scans every file written or edited for forbidden strong claims about
production-readiness, execution capability, or live system status.

These claims are explicitly forbidden until Phase D criteria are met
(CLAUDE.md §10).  The hook blocks immediately on any detected match.

Violation categories
--------------------
live_readiness_claim_detected
    Content asserts that Layer 3 is implemented or that the system is
    live / operational beyond the current phase boundary.

execution_capability_claim_detected
    Content asserts that execution is available, decisions are automated,
    or that the system can execute trades, orders, or signals.

production_ready_claim_detected
    Content asserts that the system is production-ready or externally
    validated.

Negation filter
---------------
Lines containing clear negation words in the immediate prefix ("not",
"never", "no ", "isn't", "cannot", "can't", "won't", "wouldn't") are
excluded from matching, reducing false positives in limitation statements.

Scope
-----
Scans ALL non-governance-tooling files: code (.py, .js, .ts, etc.) and
documentation (.md, .yaml, .txt, .rst) alike, since forbidden strong
claims can appear in any written artefact.  Files under .claude/ are
exempt (governance tooling).

Exit codes
----------
  0  No violations — allow processing to continue.
  2  One or more violations detected — block (raises unsupported_current_state_claim).

Blocking conditions raised (from blocking-conditions.yaml):
  unsupported_current_state_claim

Artifact written: .claude/run/artifacts/stage_gate_report.json
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

HOOK_NAME = "live-readiness-claim-blocker"
ARTIFACT_NAME = "stage_gate_report"
PRODUCER_STEP = "stage-gate-check"

# Files under these path prefixes are governance/tooling — skip entirely.
# The plan files and CLAUDE.md itself reference forbidden phrases as examples.
SKIP_PREFIXES = (
    ".claude/",
    ".claude\\",
)

# File extensions that warrant scanning.
# Forbidden claims can appear in docs as well as code.
SCANNABLE_EXTENSIONS = {
    # Code
    ".py", ".js", ".ts", ".jsx", ".tsx", ".sql", ".sh", ".bash",
    # Documentation / configuration
    ".md", ".txt", ".yaml", ".yml", ".rst", ".json",
}

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------


class PatternGroup(NamedTuple):
    name: str       # violation key (maps to artifact field)
    patterns: list  # compiled re.Pattern objects
    label: str      # human-readable label for output


# --- Category 1: live_readiness_claim ---
# Layer 3 described as implemented, the system described as live/operational
# beyond its current phase boundary.
_LIVE_READINESS_PATTERNS = [
    # "Layer 3 is implemented / operational / complete / active / live / built / ready"
    re.compile(
        r'\bLayer[\s\-]*3\s+is\s+(implemented|operational|complete|active|running|built|ready|live)\b',
        re.IGNORECASE,
    ),
    # "Layer 3 has been implemented / built / deployed / activated / completed"
    re.compile(
        r'\bLayer[\s\-]*3\s+has\s+been\s+(implemented|built|deployed|activated|completed)\b',
        re.IGNORECASE,
    ),
    # "Layer 3 exists" (unqualified existence claim)
    re.compile(r'\bLayer[\s\-]*3\s+(?:now\s+)?exists\b', re.IGNORECASE),
    # "system is live" / "system is now live"
    re.compile(r'\bsystem\s+is\s+(?:now\s+)?live\b', re.IGNORECASE),
    # "live operation is enabled / available / active"
    re.compile(
        r'\blive\s+operation\s+(?:is\s+)?(?:enabled|available|active|running)\b',
        re.IGNORECASE,
    ),
    # "system is operational" (unqualified — allowed only in limited phase context)
    re.compile(r'\bsystem\s+is\s+(?:now\s+)?(?:fully\s+)?operational\b', re.IGNORECASE),
]

# --- Category 2: execution_capability_claim ---
# Execution described as available; decisions described as automated;
# trading/order/signal execution claimed.
_EXECUTION_CAPABILITY_PATTERNS = [
    # "execution is available / enabled / operational / active / running"
    re.compile(
        r'\bexecution\s+is\s+(?:now\s+)?(?:available|enabled|operational|active|running)\b',
        re.IGNORECASE,
    ),
    # "can (now) execute trades / orders / signals"
    re.compile(
        r'\bcan\s+(?:now\s+)?execute\s+(?:trades?|orders?|signals?)\b',
        re.IGNORECASE,
    ),
    # "decisions are (now) automated"
    re.compile(r'\bdecisions?\s+are\s+(?:now\s+)?automated\b', re.IGNORECASE),
    # "automated trading"
    re.compile(r'\bautomated\s+trading\b', re.IGNORECASE),
    # "order generation is enabled / active / available"
    re.compile(
        r'\border\s+generation\s+(?:is\s+)?(?:enabled|active|available|operational)\b',
        re.IGNORECASE,
    ),
    # "signal execution is enabled / active / available"
    re.compile(
        r'\bsignal\s+execution\s+(?:is\s+)?(?:enabled|active|available|operational)\b',
        re.IGNORECASE,
    ),
    # "execution capability is available / enabled"
    re.compile(
        r'\bexecution\s+capability\s+(?:is\s+)?(?:available|enabled|active)\b',
        re.IGNORECASE,
    ),
    # "system can execute" (unqualified)
    re.compile(r'\bsystem\s+can\s+(?:now\s+)?execute\b', re.IGNORECASE),
]

# --- Category 3: production_ready_claim ---
# Production-readiness or external validation claimed.
_PRODUCTION_READY_PATTERNS = [
    # "production-ready" / "production ready"
    re.compile(r'\bproduction[\s\-]ready\b', re.IGNORECASE),
    # "ready for production"
    re.compile(r'\bready\s+for\s+production\b', re.IGNORECASE),
    # "externally validated"
    re.compile(r'\bexternally\s+validated\b', re.IGNORECASE),
    # "system is production / certified / validated / approved"
    re.compile(
        r'\bsystem\s+is\s+(?:now\s+)?(?:certified|approved|validated)\b',
        re.IGNORECASE,
    ),
    # "production-grade" (positive claim about current state)
    re.compile(r'\bproduction[\s\-]grade\b', re.IGNORECASE),
]

VIOLATION_GROUPS = [
    PatternGroup(
        name="live_readiness_claim",
        patterns=_LIVE_READINESS_PATTERNS,
        label="Live readiness / Layer-3 existence claim",
    ),
    PatternGroup(
        name="execution_capability_claim",
        patterns=_EXECUTION_CAPABILITY_PATTERNS,
        label="Execution capability claim",
    ),
    PatternGroup(
        name="production_ready_claim",
        patterns=_PRODUCTION_READY_PATTERNS,
        label="Production-readiness / external validation claim",
    ),
]

# Words that, when appearing in the ~50-char prefix before a match, indicate
# the claim is negated and should not trigger a violation.
_NEGATION_WORDS = (
    "not ", "never ", "no ", "isn't", "aren't", "wasn't", "weren't",
    "cannot", "can't", "won't", "wouldn't", "shouldn't",
    "not yet", "does not", "do not", "did not", "is not",
    "has not", "have not", "had not",
)


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


def is_skip_file(file_path: str) -> bool:
    """Return True for governance/tooling files that should not be scanned."""
    norm = normalise(file_path)
    return norm.startswith(".claude/")


def is_scannable(file_path: str) -> bool:
    """Return True if this file type warrants claim scanning."""
    return Path(file_path).suffix.lower() in SCANNABLE_EXTENSIONS


def read_file_content(file_path: str) -> str | None:
    """Read the current file content. Returns None if unreadable."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _is_likely_negated(line: str, match: re.Match) -> bool:
    """
    Return True if the matched phrase is likely negated by a word or phrase
    appearing in the ~50-character window immediately before the match.
    """
    start = max(0, match.start() - 50)
    prefix = line[start:match.start()].lower()
    return any(neg in prefix for neg in _NEGATION_WORDS)


class Match(NamedTuple):
    line_no: int
    line_text: str
    pattern_desc: str


def scan_content(content: str, patterns: list) -> list[Match]:
    """
    Scan content line-by-line for all patterns.

    Lines that appear to negate the claim (negation filter) are skipped.
    Returns a list of Match instances.
    """
    matches = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        for pat in patterns:
            m = pat.search(line)
            if m and not _is_likely_negated(line, m):
                matches.append(Match(
                    line_no=line_no,
                    line_text=line.strip(),
                    pattern_desc=pat.pattern,
                ))
                break  # one match per line per group is sufficient
    return matches


def format_matches(matches: list[Match], file_path: str) -> list[str]:
    """Format match list into human-readable lines."""
    return [f"  {file_path}:{m.line_no}: {m.line_text[:120]}" for m in matches]


# ---------------------------------------------------------------------------
# Artifact helpers
# ---------------------------------------------------------------------------


def _build_violation_list(details: dict[str, list[Match]], file_path: str) -> list[dict]:
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


def _write_verdict(
    file_path: str,
    scanned: bool,
    live_readiness_claim_detected: bool,
    execution_capability_claim_detected: bool,
    production_ready_claim_detected: bool,
    violations: list[dict],
) -> None:
    write_artifact(
        ARTIFACT_NAME,
        {
            "file_path": file_path,
            "scanned": scanned,
            "live_readiness_claim_detected": live_readiness_claim_detected,
            "execution_capability_claim_detected": execution_capability_claim_detected,
            "production_ready_claim_detected": production_ready_claim_detected,
            "violations": violations,
        },
        produced_by=PRODUCER_STEP,
    )


def _write_clean_verdict(file_path: str, scanned: bool) -> None:
    _write_verdict(
        file_path=file_path,
        scanned=scanned,
        live_readiness_claim_detected=False,
        execution_capability_claim_detected=False,
        production_ready_claim_detected=False,
        violations=[],
    )


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

    # Run each violation group.
    violation_details: dict[str, list[Match]] = {}
    for group in VIOLATION_GROUPS:
        hits = scan_content(content, group.patterns)
        if hits:
            violation_details[group.name] = hits

    live_detected = "live_readiness_claim" in violation_details
    exec_detected = "execution_capability_claim" in violation_details
    prod_detected = "production_ready_claim" in violation_details

    any_violation = live_detected or exec_detected or prod_detected

    _write_verdict(
        file_path=file_path,
        scanned=True,
        live_readiness_claim_detected=live_detected,
        execution_capability_claim_detected=exec_detected,
        production_ready_claim_detected=prod_detected,
        violations=_build_violation_list(violation_details, file_path),
    )

    if not any_violation:
        return 0

    # Build and emit the blocking message.
    lines = [
        f"[{HOOK_NAME}] Forbidden strong claim(s) detected in: {file_path}",
        "",
        "  The following claims are FORBIDDEN until Phase D criteria are met",
        "  (CLAUDE.md §10).  Remove or rephrase using allowed language:",
        "  'planned', 'target architecture', 'not yet implemented', 'requires Phase C/D'.",
        "",
    ]

    if live_detected:
        lines.append("  [live_readiness_claim]")
        lines.append(
            "  Content asserts that Layer 3 is implemented or the system is live.\n"
            "  Layer 3 is PLANNED, not yet built (CLAUDE.md §3.2, §4)."
        )
        lines.extend(format_matches(violation_details["live_readiness_claim"], file_path))
        lines.append("")

    if exec_detected:
        lines.append("  [execution_capability_claim]")
        lines.append(
            "  Content asserts that execution is available, decisions are automated,\n"
            "  or that trading/order/signal execution is operational.\n"
            "  Execution is BLOCKED by design until Phase D (CLAUDE.md §9, §4)."
        )
        lines.extend(format_matches(violation_details["execution_capability_claim"], file_path))
        lines.append("")

    if prod_detected:
        lines.append("  [production_ready_claim]")
        lines.append(
            "  Content asserts production-readiness or external validation.\n"
            "  No such claim is permitted without Phase D proof (CLAUDE.md §10, §5)."
        )
        lines.extend(format_matches(violation_details["production_ready_claim"], file_path))
        lines.append("")

    lines.append("─" * 60)
    lines.append("BLOCKED — raising: unsupported_current_state_claim")
    lines.append(
        "Resolution: replace forbidden claim language with phase-accurate language.\n"
        "See CLAUDE.md §10 for the full list of forbidden phrases and §14 for\n"
        "allowed alternatives."
    )
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
