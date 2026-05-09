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
    """Extract structured evidence from series_registry.json."""
    path = repo_root / "layer2" / "config" / "series_registry.json"
    data = _safe_json(path)
    if data is None:
        return {
            **_file_evidence(path, repo_root, status="missing"),
            "series_count": 0,
            "series_names": [],
        }

    if isinstance(data, dict):
        series_names = sorted(data.keys())
        sp500_proxy_exists = any(
            "sp500" in k.lower() or "spy" in k.lower()
            for k in series_names
        )
    elif isinstance(data, list):
        series_names = [
            entry.get("series_id", entry.get("name", ""))
            for entry in data
            if isinstance(entry, dict)
        ]
        sp500_proxy_exists = any(
            "sp500" in str(n).lower() or "spy" in str(n).lower()
            for n in series_names
        )
    else:
        return {
            **_file_evidence(path, repo_root),
            "series_count": 0,
            "series_names": [],
            "parse_note": "unexpected_type",
        }

    return {
        **_file_evidence(path, repo_root),
        "series_count": len(series_names),
        "series_names": series_names[:50],  # cap for prompt size
        "sp500_proxy_detected": sp500_proxy_exists,
    }


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
