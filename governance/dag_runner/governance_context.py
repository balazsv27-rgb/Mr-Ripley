"""
governance_context.py — Bounded evidence synthesis for governance steps.

Reads explicitly allowlisted project files and synthesizes compact,
structured ``code_context`` and ``runtime_context`` evidence for
injection into the ``governance_context`` artifact.

Design constraints:
- NO arbitrary filesystem traversal — explicit allowlist only.
- NO raw file dumping — compact structured evidence with provenance.
- NO mutation, deletion, shell execution, or network access.
- Missing files are noted as absent, never fatal.
- All direct observations carry ``inference_used: false``.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Governance evidence allowlist
# ---------------------------------------------------------------------------

GOVERNANCE_EVIDENCE_ALLOWLIST: dict[str, Any] = {
    "canonical_docs": [
        "CLAUDE.md",
        "Documentation/README_v1.md",
        "Documentation/SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "Documentation/SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
        "Documentation/SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "Documentation/DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "Documentation/README_LAYER2.md",
        "verification_ledger.md",
    ],
    "layer2_code": [
        "layer2/config/series_registry.json",
        "layer2/config/registry.py",
        "layer2/alignment.py",
        "layer2/db.py",
        "layer2/constants.py",
    ],
    "layer2_adapters_glob": "layer2/adapters/*.py",
    "runtime_metadata": [
        "latest_snapshot.json",
    ],
}


def _safe_read(path: Path) -> str | None:
    """Read a text file, returning None on any failure."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _safe_json(path: Path) -> dict | list | None:
    """Parse a JSON file, returning None on any failure."""
    text = _safe_read(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _file_evidence(
    path: Path,
    repo_root: Path,
    status: str = "present",
) -> dict[str, Any]:
    """Build a minimal file evidence dict."""
    try:
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")
    return {"file": rel, "status": status, "inference_used": False}


# ---------------------------------------------------------------------------
# Series registry synthesis
# ---------------------------------------------------------------------------

def _synthesize_series_registry(repo_root: Path) -> dict[str, Any]:
    """Extract structured evidence from series_registry.json.

    Parses the registry's ``series`` array to extract per-series metadata,
    tier counts, snapshot inclusion, and SP500/SP500_PROXY status.
    """
    path = repo_root / "layer2" / "config" / "series_registry.json"
    data = _safe_json(path)
    if data is None:
        return {
            **_file_evidence(path, repo_root, status="missing"),
            "registry_version": None,
            "series_count": 0,
            "series_ids": [],
            "validation_errors": ["file missing or unparseable"],
        }

    # Handle dict with top-level "series" array (canonical format)
    if isinstance(data, dict) and "series" in data and isinstance(data["series"], list):
        series_list = data["series"]
        registry_version = data.get("registry_version")
    elif isinstance(data, list):
        # Legacy: bare array of series dicts
        series_list = data
        registry_version = None
    elif isinstance(data, dict):
        # Dict but missing "series" key — malformed
        return {
            **_file_evidence(path, repo_root),
            "registry_version": data.get("registry_version"),
            "series_count": 0,
            "series_ids": [],
            "validation_errors": [
                "dict payload missing 'series' array key",
                f"top_level_keys={sorted(data.keys())}",
            ],
        }
    else:
        return {
            **_file_evidence(path, repo_root),
            "registry_version": None,
            "series_count": 0,
            "series_ids": [],
            "validation_errors": ["unexpected_type"],
        }

    # Extract per-series metadata
    series_ids: list[str] = []
    tier1_count = 0
    tier2_count = 0
    include_in_snapshot_count = 0
    snapshot_series_ids: list[str] = []
    sp500_entry: dict[str, Any] | None = None
    sp500_proxy_entry: dict[str, Any] | None = None
    validation_errors: list[str] = []

    for i, entry in enumerate(series_list):
        if not isinstance(entry, dict):
            validation_errors.append(f"series[{i}] is not a dict")
            continue
        sid = entry.get("series_id", "")
        if not sid:
            validation_errors.append(f"series[{i}] missing series_id")
            continue
        series_ids.append(sid)
        tier = entry.get("tier")
        if tier == 1:
            tier1_count += 1
        elif tier == 2:
            tier2_count += 1
        if entry.get("include_in_snapshot"):
            include_in_snapshot_count += 1
            snapshot_series_ids.append(sid)
        if sid == "SP500":
            sp500_entry = entry
        elif sid == "SP500_PROXY":
            sp500_proxy_entry = entry

    result: dict[str, Any] = {
        **_file_evidence(path, repo_root),
        "registry_version": registry_version,
        "series_count": len(series_ids),
        "series_ids": series_ids[:50],  # cap for prompt size
        "tier1_count": tier1_count,
        "tier2_count": tier2_count,
        "include_in_snapshot_count": include_in_snapshot_count,
        "snapshot_series_ids": snapshot_series_ids[:50],
        "sp500_detected": sp500_entry is not None,
        "sp500_proxy_detected": sp500_proxy_entry is not None,
    }

    # SP500 detail
    if sp500_entry is not None:
        result["sp500_source"] = sp500_entry.get("source")
    if sp500_proxy_entry is not None:
        result["sp500_proxy_source"] = sp500_proxy_entry.get("source")
        result["sp500_proxy_full_history_start"] = sp500_proxy_entry.get(
            "full_history_start",
        )
        result["sp500_proxy_include_in_snapshot"] = sp500_proxy_entry.get(
            "include_in_snapshot",
        )
        result["sp500_proxy_tier"] = sp500_proxy_entry.get("tier")

    if validation_errors:
        result["validation_errors"] = validation_errors

    return result


# ---------------------------------------------------------------------------
# Adapter inventory synthesis
# ---------------------------------------------------------------------------

def _synthesize_adapter_inventory(repo_root: Path) -> dict[str, Any]:
    """List adapter files in layer2/adapters/."""
    adapter_dir = repo_root / "layer2" / "adapters"
    if not adapter_dir.is_dir():
        return {
            "adapter_dir": "layer2/adapters",
            "status": "missing",
            "inference_used": False,
            "adapter_count": 0,
            "adapter_files": [],
        }

    files = sorted(
        f.name
        for f in adapter_dir.iterdir()
        if f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
    )

    return {
        "adapter_dir": "layer2/adapters",
        "status": "present",
        "inference_used": False,
        "adapter_count": len(files),
        "adapter_files": files,
    }


# ---------------------------------------------------------------------------
# Boundary pattern checks
# ---------------------------------------------------------------------------

_INSERT_OR_IGNORE_RE = re.compile(r"INSERT\s+OR\s+IGNORE", re.IGNORECASE)
_INSERT_OR_REPLACE_RE = re.compile(r"INSERT\s+OR\s+REPLACE", re.IGNORECASE)


def _synthesize_boundary_checks(repo_root: Path) -> dict[str, Any]:
    """Scan key Layer-2 files for boundary-relevant patterns."""
    results: dict[str, Any] = {
        "inference_used": False,
        "checks": [],
    }

    files_to_scan = [
        repo_root / "layer2" / "db.py",
        repo_root / "layer2" / "alignment.py",
    ]

    for path in files_to_scan:
        content = _safe_read(path)
        if content is None:
            results["checks"].append({
                **_file_evidence(path, repo_root, status="missing"),
                "insert_or_ignore_count": 0,
                "insert_or_replace_count": 0,
            })
            continue

        ignore_count = len(_INSERT_OR_IGNORE_RE.findall(content))
        replace_count = len(_INSERT_OR_REPLACE_RE.findall(content))

        check: dict[str, Any] = {
            **_file_evidence(path, repo_root),
            "insert_or_ignore_count": ignore_count,
            "insert_or_replace_count": replace_count,
        }
        if replace_count > 0:
            check["violation_detected"] = True
            check["violation_type"] = "forbidden_insert_or_replace"
        else:
            check["violation_detected"] = False

        results["checks"].append(check)

    # Summary flags
    results["insert_or_replace_detected"] = any(
        c.get("violation_detected") for c in results["checks"]
    )

    return results


# ---------------------------------------------------------------------------
# Execution artifact scan
# ---------------------------------------------------------------------------

def _synthesize_execution_scan(repo_root: Path) -> dict[str, Any]:
    """Check for absence of Layer-3 execution artifacts."""
    # Layer-3 components that should NOT exist yet
    layer3_indicators = [
        "layer3",
        "feature_builder",
        "regime_gate",
        "supervisor_engine",
        "decision_engine",
    ]
    detected = []
    for indicator in layer3_indicators:
        path = repo_root / indicator
        if path.exists():
            detected.append(indicator)

    return {
        "inference_used": False,
        "layer3_execution_artifacts_absent": len(detected) == 0,
        "detected_layer3_indicators": detected,
    }


# ---------------------------------------------------------------------------
# Canonical document extraction
# ---------------------------------------------------------------------------

# Keywords for bounded extraction from canonical documents
_EXTRACTION_KEYWORDS: tuple[str, ...] = (
    "SP500", "SP500_PROXY", "TODO", "Layer-2", "Layer-3",
    "remaining", "revision log", "implementation addendum",
    "live execution", "blocked", "verification ledger",
    "governance workflow", "Phase A", "Phase B",
    "include_in_snapshot", "not yet built", "not yet implemented",
)

# Maximum lines to extract per document
_MAX_EXTRACT_LINES = 150
# Maximum characters per extract section
_MAX_SECTION_CHARS = 3000


def _extract_headings(content: str) -> list[str]:
    """Extract markdown headings from content."""
    headings: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped)
    return headings[:50]  # cap


def _extract_keyword_sections(
    content: str,
    keywords: tuple[str, ...] = _EXTRACTION_KEYWORDS,
    context_lines: int = 3,
) -> list[dict[str, Any]]:
    """Extract compact sections around keyword matches.

    Returns a list of {keyword, line_number, context} dicts.
    Caps total extracted lines to ``_MAX_EXTRACT_LINES``.
    """
    lines = content.splitlines()
    sections: list[dict[str, Any]] = []
    seen_ranges: set[int] = set()
    total_lines = 0

    for kw in keywords:
        kw_lower = kw.lower()
        for i, line in enumerate(lines):
            if kw_lower in line.lower() and i not in seen_ranges:
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                context_block = "\n".join(lines[start:end])
                if len(context_block) > _MAX_SECTION_CHARS:
                    context_block = context_block[:_MAX_SECTION_CHARS] + "..."
                sections.append({
                    "keyword": kw,
                    "line_number": i + 1,
                    "context": context_block,
                })
                for j in range(start, end):
                    seen_ranges.add(j)
                total_lines += end - start
                if total_lines >= _MAX_EXTRACT_LINES:
                    return sections

    return sections


def _synthesize_doc_extract(
    path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    """Extract bounded structured information from a single canonical doc."""
    content = _safe_read(path)
    if content is None:
        return {
            **_file_evidence(path, repo_root, status="missing"),
            "headings": [],
            "keyword_sections": [],
        }

    headings = _extract_headings(content)
    keyword_sections = _extract_keyword_sections(content)

    result: dict[str, Any] = {
        **_file_evidence(path, repo_root),
        "char_count": len(content),
        "line_count": len(content.splitlines()),
        "headings": headings,
        "keyword_section_count": len(keyword_sections),
    }

    # Only include keyword sections if they exist — keeps small docs compact
    if keyword_sections:
        result["keyword_sections"] = keyword_sections

    return result


def build_canonical_doc_extracts(repo_root: Path) -> dict[str, Any]:
    """Extract bounded structured information from all canonical documents.

    Returns a dict keyed by document name with headings, keyword sections,
    and presence/absence status for each canonical document.

    Never raises — all file-read errors are captured as missing status.
    """
    docs = GOVERNANCE_EVIDENCE_ALLOWLIST["canonical_docs"]
    extracts: dict[str, Any] = {}

    for doc_path_str in docs:
        path = repo_root / doc_path_str
        # Use the filename (without directory) as the key for readability
        key = Path(doc_path_str).name
        extracts[key] = _synthesize_doc_extract(path, repo_root)

    return extracts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_code_context(repo_root: Path) -> dict[str, Any]:
    """Synthesize structured code evidence from allowlisted Layer-2 files.

    Returns a compact dict with provenance for each finding.
    Never raises — all file-read errors are captured as missing status.
    """
    return {
        "series_registry": _synthesize_series_registry(repo_root),
        "adapter_inventory": _synthesize_adapter_inventory(repo_root),
        "layer2_boundary_checks": _synthesize_boundary_checks(repo_root),
        "execution_artifact_scan": _synthesize_execution_scan(repo_root),
    }


def build_runtime_context(repo_root: Path) -> dict[str, Any]:
    """Synthesize structured runtime metadata evidence.

    Returns a compact dict with provenance for each finding.
    Never raises — all file-read errors are captured as missing status.
    """
    snapshot_path = repo_root / "latest_snapshot.json"
    snapshot_data = _safe_json(snapshot_path)

    if snapshot_data is None:
        snapshot_evidence: dict[str, Any] = {
            **_file_evidence(snapshot_path, repo_root, status="missing"),
        }
    elif isinstance(snapshot_data, dict):
        snapshot_evidence = {
            **_file_evidence(snapshot_path, repo_root),
            "snapshot_id": snapshot_data.get("snapshot_id"),
            "as_of": snapshot_data.get("as_of") or snapshot_data.get("clock_ts"),
            "engine_version": snapshot_data.get("engine_version"),
            "has_guards_object": "guards" in snapshot_data,
        }
    else:
        snapshot_evidence = {
            **_file_evidence(snapshot_path, repo_root),
            "parse_note": "unexpected_type",
        }

    return {
        "latest_snapshot": snapshot_evidence,
        "layer3_runtime_absent": not (repo_root / "layer3").exists(),
    }
