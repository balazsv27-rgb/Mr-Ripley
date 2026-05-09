"""Tests for governance.dag_runner.governance_context.

Covers build_code_context(), build_runtime_context(), allowlist enforcement,
graceful missing-file handling, and inference_used=false guarantees.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance.dag_runner.governance_context import (
    GOVERNANCE_EVIDENCE_ALLOWLIST,
    build_code_context,
    build_runtime_context,
)


@pytest.fixture
def mock_repo(tmp_path: Path) -> Path:
    """Create a minimal mock repo with Layer-2 structure."""
    # series_registry.json
    config_dir = tmp_path / "layer2" / "config"
    config_dir.mkdir(parents=True)
    registry = {
        "GOLD_PM": {"source": "LBMA", "unit": "USD/oz"},
        "SPY_CLOSE": {"source": "Yahoo", "unit": "USD"},
        "SP500_PROXY": {"source": "derived", "unit": "index"},
    }
    (config_dir / "series_registry.json").write_text(json.dumps(registry))
    (config_dir / "registry.py").write_text("# registry config\n")
    (config_dir / "__init__.py").write_text("")

    # adapters
    adapter_dir = tmp_path / "layer2" / "adapters"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "gold_adapter.py").write_text("class GoldAdapter: pass\n")
    (adapter_dir / "spy_adapter.py").write_text("class SpyAdapter: pass\n")
    (adapter_dir / "__init__.py").write_text("")

    # db.py with INSERT OR IGNORE
    (tmp_path / "layer2" / "db.py").write_text(
        'INSERT_SQL = "INSERT OR IGNORE INTO observations ..."\n'
    )

    # alignment.py — clean
    (tmp_path / "layer2" / "alignment.py").write_text(
        "def align(): pass\n"
    )

    # constants.py
    (tmp_path / "layer2" / "constants.py").write_text(
        "SOME_CONST = 42\n"
    )

    return tmp_path


# ── build_code_context ──


def test_code_context_series_registry(mock_repo: Path) -> None:
    ctx = build_code_context(mock_repo)
    sr = ctx["series_registry"]
    assert sr["status"] == "present"
    assert sr["series_count"] == 3
    assert "GOLD_PM" in sr["series_names"]
    assert sr["sp500_proxy_detected"] is True
    assert sr["inference_used"] is False


def test_code_context_adapter_inventory(mock_repo: Path) -> None:
    ctx = build_code_context(mock_repo)
    ai = ctx["adapter_inventory"]
    assert ai["status"] == "present"
    assert ai["adapter_count"] == 2
    assert "gold_adapter.py" in ai["adapter_files"]
    assert "spy_adapter.py" in ai["adapter_files"]
    assert "__init__.py" not in ai["adapter_files"]
    assert ai["inference_used"] is False


def test_code_context_boundary_checks_clean(mock_repo: Path) -> None:
    ctx = build_code_context(mock_repo)
    bc = ctx["layer2_boundary_checks"]
    assert bc["inference_used"] is False
    assert bc["insert_or_replace_detected"] is False

    db_check = next(c for c in bc["checks"] if "db.py" in c["file"])
    assert db_check["insert_or_ignore_count"] == 1
    assert db_check["insert_or_replace_count"] == 0
    assert db_check["violation_detected"] is False


def test_code_context_boundary_checks_violation(mock_repo: Path) -> None:
    # Inject forbidden pattern into the mock repo's db.py
    (mock_repo / "layer2" / "db.py").write_text(
        'SQL = "INSERT OR REPLACE INTO observations ..."\n'
    )
    ctx = build_code_context(mock_repo)
    bc = ctx["layer2_boundary_checks"]
    assert bc["insert_or_replace_detected"] is True

    db_check = next(c for c in bc["checks"] if "db.py" in c["file"])
    assert db_check["violation_detected"] is True
    assert db_check["violation_type"] == "forbidden_insert_or_replace"


def test_code_context_execution_scan_clean(mock_repo: Path) -> None:
    ctx = build_code_context(mock_repo)
    es = ctx["execution_artifact_scan"]
    assert es["layer3_execution_artifacts_absent"] is True
    assert es["detected_layer3_indicators"] == []
    assert es["inference_used"] is False


def test_code_context_execution_scan_layer3_present(mock_repo: Path) -> None:
    (mock_repo / "layer3").mkdir()
    ctx = build_code_context(mock_repo)
    es = ctx["execution_artifact_scan"]
    assert es["layer3_execution_artifacts_absent"] is False
    assert "layer3" in es["detected_layer3_indicators"]


def test_code_context_missing_files(tmp_path: Path) -> None:
    """build_code_context on empty dir does not raise."""
    ctx = build_code_context(tmp_path)
    assert ctx["series_registry"]["status"] == "missing"
    assert ctx["adapter_inventory"]["status"] == "missing"
    assert ctx["layer2_boundary_checks"]["insert_or_replace_detected"] is False
    # Each check should report missing
    for check in ctx["layer2_boundary_checks"]["checks"]:
        assert check["status"] == "missing"


def test_code_context_no_sp500_proxy(mock_repo: Path) -> None:
    """No SP500_PROXY when registry lacks matching keys."""
    registry = {"GOLD_PM": {"source": "LBMA"}}
    (mock_repo / "layer2" / "config" / "series_registry.json").write_text(
        json.dumps(registry)
    )
    ctx = build_code_context(mock_repo)
    assert ctx["series_registry"]["sp500_proxy_detected"] is False


# ── build_runtime_context ──


def test_runtime_context_snapshot_present(mock_repo: Path) -> None:
    snapshot = {
        "snapshot_id": "snap-001",
        "clock_ts": "2026-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "guards": {"quality": True},
    }
    (mock_repo / "latest_snapshot.json").write_text(json.dumps(snapshot))
    ctx = build_runtime_context(mock_repo)
    ls = ctx["latest_snapshot"]
    assert ls["status"] == "present"
    assert ls["snapshot_id"] == "snap-001"
    assert ls["as_of"] == "2026-01-01T00:00:00Z"
    assert ls["engine_version"] == "0.1.0"
    assert ls["has_guards_object"] is True
    assert ls["inference_used"] is False


def test_runtime_context_snapshot_missing(tmp_path: Path) -> None:
    ctx = build_runtime_context(tmp_path)
    ls = ctx["latest_snapshot"]
    assert ls["status"] == "missing"
    assert ls["inference_used"] is False


def test_runtime_context_layer3_absent(tmp_path: Path) -> None:
    ctx = build_runtime_context(tmp_path)
    assert ctx["layer3_runtime_absent"] is True


def test_runtime_context_layer3_present(tmp_path: Path) -> None:
    (tmp_path / "layer3").mkdir()
    ctx = build_runtime_context(tmp_path)
    assert ctx["layer3_runtime_absent"] is False


# ── inference_used guarantee ──


def test_all_evidence_inference_used_false(mock_repo: Path) -> None:
    """Every evidence dict at any level must have inference_used=False."""
    code = build_code_context(mock_repo)
    runtime = build_runtime_context(mock_repo)

    def _check(obj: dict, path: str = "") -> None:
        if "inference_used" in obj:
            assert obj["inference_used"] is False, f"inference_used=True at {path}"
        for k, v in obj.items():
            if isinstance(v, dict):
                _check(v, f"{path}.{k}")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        _check(item, f"{path}.{k}[{i}]")

    _check(code, "code_context")
    _check(runtime, "runtime_context")


# ── Allowlist structure ──


def test_allowlist_contains_canonical_docs() -> None:
    docs = GOVERNANCE_EVIDENCE_ALLOWLIST["canonical_docs"]
    assert "CLAUDE.md" in docs
    assert "Documentation/README_v1.md" in docs
    assert "verification_ledger.md" in docs


def test_allowlist_contains_layer2_code() -> None:
    code = GOVERNANCE_EVIDENCE_ALLOWLIST["layer2_code"]
    assert "layer2/config/series_registry.json" in code
    assert "layer2/db.py" in code
    assert "layer2/alignment.py" in code


def test_allowlist_has_no_secrets() -> None:
    """Allowlist must not contain .env, .git, or secret paths."""
    all_paths = []
    for key, val in GOVERNANCE_EVIDENCE_ALLOWLIST.items():
        if isinstance(val, list):
            all_paths.extend(val)
        elif isinstance(val, str):
            all_paths.append(val)

    forbidden = [".env", ".git", "node_modules", ".venv", "secret"]
    for path in all_paths:
        for f in forbidden:
            assert f not in path.lower(), f"Allowlist contains forbidden path: {path}"
