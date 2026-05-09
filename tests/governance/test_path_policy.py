"""Tests for governance.dag_runner.path_policy (B3).

Covers PathPolicy, validate_path, default_governance_policy.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from governance.dag_runner.path_policy import (
    PathPolicy,
    PathPolicyViolation,
    default_governance_policy,
    validate_path,
)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Create a temporary repo root with representative files."""
    # Create allowed file structures
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "test-agent.md").write_text("# Test Agent")

    skills_dir = tmp_path / ".claude" / "skills" / "test-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("# Test Skill")

    docs_dir = tmp_path / "Documentation"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text("# Guide")

    (tmp_path / "README_v1.md").write_text("# README")

    # Create denied files
    (tmp_path / ".env").write_text("SECRET=xyz")
    (tmp_path / "key.pem").write_text("private key")
    (tmp_path / "secret.key").write_text("key data")

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]")

    return tmp_path


@pytest.fixture
def policy(repo_root: Path) -> PathPolicy:
    return default_governance_policy(repo_root)


# ── validate_path: allowed paths ──


def test_allowed_agent_path(repo_root: Path, policy: PathPolicy) -> None:
    path = repo_root / ".claude" / "agents" / "test-agent.md"
    validate_path(path, policy)  # should not raise


def test_allowed_skill_path(repo_root: Path, policy: PathPolicy) -> None:
    path = repo_root / ".claude" / "skills" / "test-skill" / "SKILL.md"
    validate_path(path, policy)  # should not raise


def test_allowed_root_md(repo_root: Path, policy: PathPolicy) -> None:
    path = repo_root / "README_v1.md"
    validate_path(path, policy)  # should not raise


def test_allowed_documentation_md(repo_root: Path, policy: PathPolicy) -> None:
    path = repo_root / "Documentation" / "guide.md"
    validate_path(path, policy)  # should not raise


# ── validate_path: denied paths ──


def test_denied_env_file(repo_root: Path, policy: PathPolicy) -> None:
    path = repo_root / ".env"
    with pytest.raises(PathPolicyViolation, match="denied pattern"):
        validate_path(path, policy)


def test_denied_pem_file(repo_root: Path, policy: PathPolicy) -> None:
    path = repo_root / "key.pem"
    with pytest.raises(PathPolicyViolation, match="denied pattern"):
        validate_path(path, policy)


def test_denied_key_file(repo_root: Path, policy: PathPolicy) -> None:
    path = repo_root / "secret.key"
    with pytest.raises(PathPolicyViolation, match="denied pattern"):
        validate_path(path, policy)


def test_denied_git_internals(repo_root: Path, policy: PathPolicy) -> None:
    path = repo_root / ".git" / "config"
    with pytest.raises(PathPolicyViolation, match="denied pattern"):
        validate_path(path, policy)


# ── validate_path: outside repo root ──


def test_path_outside_repo_root(repo_root: Path, policy: PathPolicy) -> None:
    outside = repo_root.parent / "outside.md"
    with pytest.raises(PathPolicyViolation, match="outside allowed roots"):
        validate_path(outside, policy)


# ── validate_path: file size ──


def test_file_exceeding_max_size(repo_root: Path) -> None:
    small_limit = PathPolicy(
        allowed_roots=[repo_root],
        allowed_patterns=["*.md"],
        denied_patterns=[],
        max_file_size_bytes=5,  # 5 bytes
    )
    path = repo_root / "README_v1.md"
    with pytest.raises(PathPolicyViolation, match="exceeds max size"):
        validate_path(path, small_limit)


# ── validate_path: no allowed pattern match ──


def test_no_matching_allowed_pattern(repo_root: Path) -> None:
    policy = PathPolicy(
        allowed_roots=[repo_root],
        allowed_patterns=["*.txt"],  # only .txt allowed
        denied_patterns=[],
    )
    path = repo_root / "README_v1.md"
    with pytest.raises(PathPolicyViolation, match="does not match"):
        validate_path(path, policy)


# ── default_governance_policy ──


def test_default_policy_allows_agent_paths(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    agent_path = repo_root / ".claude" / "agents" / "foo.md"
    validate_path(agent_path, policy)  # should not raise


def test_default_policy_allows_skill_paths(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    skill_path = repo_root / ".claude" / "skills" / "bar" / "SKILL.md"
    validate_path(skill_path, policy)  # should not raise


def test_default_policy_denies_env(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    env_path = repo_root / ".env"
    with pytest.raises(PathPolicyViolation):
        validate_path(env_path, policy)


# ── Layer-2 code/config governance access ──


def test_default_policy_allows_layer2_py(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    py_path = repo_root / "layer2" / "db.py"
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text("# db")
    validate_path(py_path, policy)  # should not raise


def test_default_policy_allows_layer2_adapters_py(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    adapter_path = repo_root / "layer2" / "adapters" / "gold_adapter.py"
    adapter_path.parent.mkdir(parents=True, exist_ok=True)
    adapter_path.write_text("# adapter")
    validate_path(adapter_path, policy)  # should not raise


def test_default_policy_allows_layer2_config_json(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    json_path = repo_root / "layer2" / "config" / "series_registry.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("{}")
    validate_path(json_path, policy)  # should not raise


def test_default_policy_allows_layer2_config_py(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    py_path = repo_root / "layer2" / "config" / "registry.py"
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text("# registry")
    validate_path(py_path, policy)  # should not raise


def test_default_policy_allows_latest_snapshot_json(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    snap_path = repo_root / "latest_snapshot.json"
    snap_path.write_text("{}")
    validate_path(snap_path, policy)  # should not raise


def test_default_policy_allows_workflow_packages(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    pkg_path = repo_root / ".claude" / "workflows" / "packages" / "artifacts.yaml"
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.write_text("section: artifacts")
    validate_path(pkg_path, policy)  # should not raise


def test_default_policy_still_denies_git(repo_root: Path) -> None:
    """Expanded policy must not weaken existing denied patterns."""
    policy = default_governance_policy(repo_root)
    git_path = repo_root / ".git" / "config"
    with pytest.raises(PathPolicyViolation):
        validate_path(git_path, policy)


def test_default_policy_still_denies_pem(repo_root: Path) -> None:
    policy = default_governance_policy(repo_root)
    pem_path = repo_root / "key.pem"
    with pytest.raises(PathPolicyViolation):
        validate_path(pem_path, policy)
