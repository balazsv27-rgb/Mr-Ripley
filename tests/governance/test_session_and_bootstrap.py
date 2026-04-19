"""
Tests for run-scoped artifact isolation and explicit bootstrap input.

Covers:
- Session directory creation
- Fresh-run artifact isolation
- Continuation session reuse
- Hook resolution via active-session pointer
- Legacy fallback behavior
- Missing-bootstrap failure
- Real governance_context payload generation
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _load_artifact_store():
    """Load the artifact_store module from .claude/hooks/lib/ via importlib."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    module_path = repo_root / ".claude" / "hooks" / "lib" / "artifact_store.py"
    spec = importlib.util.spec_from_file_location("artifact_store", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

from governance.dag_runner.session import (
    SessionError,
    create_session_dir,
    read_session_pointer,
    resolve_artifact_dir,
    resolve_debug_dir,
    write_session_pointer,
)
from governance.dag_runner.models import (
    ArtifactRecord,
    AssembledWorkflowSpec,
    ExecutionConfig,
    GovernanceRunState,
    ManifestSpec,
    WorkflowStep,
)
from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.execution_modes import build_config_from_args
from governance.dag_runner.executor import (
    ExecutorError,
    _build_governance_context_payload,
    execute_plan,
)
from governance.dag_runner.planner import ExecutionPlan, PlannedNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    name: str,
    *,
    component: str = "skill:test",
    outputs: list[str] | None = None,
    raises: list[str] | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        name=name,
        component=component,
        outputs=outputs if outputs is not None else [f"{name}_out"],
        raises=raises or [],
    )


def _make_spec(*steps: WorkflowStep) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test-workflow"),
        workflow_steps={s.name: s for s in steps},
    )


def _make_plan(*steps: WorkflowStep) -> ExecutionPlan:
    return ExecutionPlan(
        workflow_name="test-workflow",
        ordered_steps=[
            PlannedNode(step_id=s.name, component=s.component)
            for s in steps
        ],
    )


# ---------------------------------------------------------------------------
# 1. Session directory creation
# ---------------------------------------------------------------------------


class TestSessionDirCreation:
    def test_creates_artifacts_and_debug_dirs(self, tmp_path: Path) -> None:
        run_id = "test-run-001"
        root = create_session_dir(run_id, base_dir=tmp_path)

        assert root == tmp_path / run_id
        assert (root / "artifacts").is_dir()
        assert (root / "debug").is_dir()

    def test_idempotent_on_existing_dir(self, tmp_path: Path) -> None:
        run_id = "test-run-002"
        root1 = create_session_dir(run_id, base_dir=tmp_path)
        root2 = create_session_dir(run_id, base_dir=tmp_path)
        assert root1 == root2

    def test_different_run_ids_create_different_dirs(self, tmp_path: Path) -> None:
        r1 = create_session_dir("run-a", base_dir=tmp_path)
        r2 = create_session_dir("run-b", base_dir=tmp_path)
        assert r1 != r2
        assert r1.name == "run-a"
        assert r2.name == "run-b"


# ---------------------------------------------------------------------------
# 2. Session pointer
# ---------------------------------------------------------------------------


class TestSessionPointer:
    def test_write_and_read_pointer(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "sessions" / "run-xyz"
        session_dir.mkdir(parents=True)
        pointer_path = tmp_path / "current_session.json"

        write_session_pointer(session_dir, "run-xyz", pointer_path=pointer_path)
        pointer = read_session_pointer(pointer_path)

        assert pointer["run_id"] == "run-xyz"
        assert pointer["session_dir"] == str(session_dir)
        assert "started_at" in pointer

    def test_read_missing_pointer_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SessionError, match="not found"):
            read_session_pointer(tmp_path / "nonexistent.json")

    def test_resolve_artifact_dir_from_pointer(self, tmp_path: Path) -> None:
        session_dir = create_session_dir("run-res", base_dir=tmp_path)
        pointer_path = tmp_path / "ptr.json"
        write_session_pointer(session_dir, "run-res", pointer_path=pointer_path)

        art_dir = resolve_artifact_dir(pointer_path)
        assert art_dir == session_dir / "artifacts"

    def test_resolve_debug_dir_from_pointer(self, tmp_path: Path) -> None:
        session_dir = create_session_dir("run-dbg", base_dir=tmp_path)
        pointer_path = tmp_path / "ptr.json"
        write_session_pointer(session_dir, "run-dbg", pointer_path=pointer_path)

        dbg_dir = resolve_debug_dir(pointer_path)
        assert dbg_dir == session_dir / "debug"


# ---------------------------------------------------------------------------
# 3. Fresh-run artifact isolation
# ---------------------------------------------------------------------------


class TestFreshRunIsolation:
    def test_fresh_run_creates_session_dir(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_SESSIONS_BASE",
            tmp_path / "sessions",
        )
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_POINTER_PATH",
            tmp_path / "current_session.json",
        )

        step = _make_step("step-a", component="constitution", outputs=["art_a"])
        spec = _make_spec(step)
        plan = _make_plan(step)
        backend = MockExecutionBackend()

        config = ExecutionConfig(
            mode="dry_run",
            request_text="test request",
        )

        result = execute_plan(
            spec, plan,
            verdict_status="ready",
            config=config,
            backend=backend,
        )

        assert result.run_state.session_dir is not None
        session_path = Path(result.run_state.session_dir)
        assert session_path.is_dir()
        assert (session_path / "artifacts").is_dir()
        assert (session_path / "debug").is_dir()

    def test_two_fresh_runs_get_different_sessions(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_SESSIONS_BASE",
            tmp_path / "sessions",
        )
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_POINTER_PATH",
            tmp_path / "current_session.json",
        )

        step = _make_step("step-a", component="constitution", outputs=["art_a"])
        spec = _make_spec(step)
        plan = _make_plan(step)
        backend = MockExecutionBackend()
        config = ExecutionConfig(mode="dry_run")

        r1 = execute_plan(spec, plan, verdict_status="ready", config=config, backend=backend)
        r2 = execute_plan(spec, plan, verdict_status="ready", config=config, backend=backend)

        assert r1.run_state.session_dir != r2.run_state.session_dir


# ---------------------------------------------------------------------------
# 4. Continuation session reuse
# ---------------------------------------------------------------------------


class TestContinuationSessionReuse:
    def test_continuation_reuses_prior_session_dir(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_SESSIONS_BASE",
            tmp_path / "sessions",
        )
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_POINTER_PATH",
            tmp_path / "current_session.json",
        )

        step_a = _make_step("step-a", component="constitution", outputs=["art_a"])
        step_b = _make_step("step-b", component="constitution", outputs=["art_b"])
        spec = _make_spec(step_a, step_b)
        plan = _make_plan(step_a, step_b)
        backend = MockExecutionBackend()
        config = ExecutionConfig(mode="dry_run")

        # First run
        r1 = execute_plan(spec, plan, verdict_status="ready", config=config, backend=backend)
        prior_session = r1.run_state.session_dir

        # Continuation
        cont_config = ExecutionConfig(mode="dry_run", continue_from="step-b")
        r2 = execute_plan(
            spec, plan,
            verdict_status="ready",
            config=cont_config,
            backend=backend,
            prior_state=r1.run_state,
        )

        assert r2.run_state.session_dir == prior_session


# ---------------------------------------------------------------------------
# 5. Hook resolution via active-session pointer
# ---------------------------------------------------------------------------


class TestHookResolution:
    def test_artifact_store_resolves_session_dir(self, tmp_path: Path, monkeypatch) -> None:
        # Create a session directory with an artifact
        session_dir = create_session_dir("run-hook-test", base_dir=tmp_path)
        art_path = session_dir / "artifacts" / "test_artifact.json"
        art_path.write_text(json.dumps({
            "artifact": "test_artifact",
            "produced_by": "test-step",
            "session": "run-hook-test",
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {"key": "value"},
        }))

        # Write pointer
        pointer_path = tmp_path / "current_session.json"
        write_session_pointer(session_dir, "run-hook-test", pointer_path=pointer_path)

        # Load and patch artifact_store
        artifact_store = _load_artifact_store()
        monkeypatch.setattr(artifact_store, "_POINTER_PATH", pointer_path)

        # Verify resolution
        resolved = artifact_store._resolve_artifact_dir()
        assert resolved == session_dir / "artifacts"

        # Verify read_artifact works
        data = artifact_store.read_artifact("test_artifact")
        assert data == {"key": "value"}

    def test_artifact_store_exists_in_session(self, tmp_path: Path, monkeypatch) -> None:
        session_dir = create_session_dir("run-exists-test", base_dir=tmp_path)
        art_path = session_dir / "artifacts" / "some_artifact.json"
        art_path.write_text(json.dumps({
            "artifact": "some_artifact",
            "produced_by": "test",
            "session": "x",
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {},
        }))

        pointer_path = tmp_path / "current_session.json"
        write_session_pointer(session_dir, "run-exists-test", pointer_path=pointer_path)

        artifact_store = _load_artifact_store()
        monkeypatch.setattr(artifact_store, "_POINTER_PATH", pointer_path)

        assert artifact_store.artifact_exists("some_artifact") is True
        assert artifact_store.artifact_exists("nonexistent") is False


# ---------------------------------------------------------------------------
# 6. Legacy fallback behavior
# ---------------------------------------------------------------------------


class TestLegacyFallback:
    def test_no_pointer_falls_back_to_legacy(self, tmp_path: Path, monkeypatch) -> None:
        artifact_store = _load_artifact_store()

        # Point to a nonexistent pointer
        monkeypatch.setattr(artifact_store, "_POINTER_PATH", tmp_path / "no_such_pointer.json")

        # Should fall back to ARTIFACT_DIR (legacy)
        resolved = artifact_store._resolve_artifact_dir()
        assert resolved == artifact_store.ARTIFACT_DIR

    def test_malformed_pointer_falls_back(self, tmp_path: Path, monkeypatch) -> None:
        artifact_store = _load_artifact_store()

        pointer_path = tmp_path / "bad_pointer.json"
        pointer_path.write_text("not valid json {{{")
        monkeypatch.setattr(artifact_store, "_POINTER_PATH", pointer_path)

        resolved = artifact_store._resolve_artifact_dir()
        assert resolved == artifact_store.ARTIFACT_DIR


# ---------------------------------------------------------------------------
# 7. Missing-bootstrap failure
# ---------------------------------------------------------------------------


class TestMissingBootstrapFailure:
    def test_agent_execution_without_request_fails(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_SESSIONS_BASE",
            tmp_path / "sessions",
        )
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_POINTER_PATH",
            tmp_path / "current_session.json",
        )

        step = _make_step("step-a", component="constitution", outputs=["art_a"])
        spec = _make_spec(step)
        plan = _make_plan(step)
        backend = MockExecutionBackend()

        config = ExecutionConfig(mode="agent_execution")  # no request_text

        with pytest.raises(ExecutorError, match="bootstrap input"):
            execute_plan(
                spec, plan,
                verdict_status="ready",
                config=config,
                backend=backend,
            )

    def test_dry_run_without_request_succeeds(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_SESSIONS_BASE",
            tmp_path / "sessions",
        )
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_POINTER_PATH",
            tmp_path / "current_session.json",
        )

        step = _make_step("step-a", component="constitution", outputs=["art_a"])
        spec = _make_spec(step)
        plan = _make_plan(step)
        backend = MockExecutionBackend()

        config = ExecutionConfig(mode="dry_run")  # no request_text — allowed

        result = execute_plan(
            spec, plan,
            verdict_status="ready",
            config=config,
            backend=backend,
        )
        assert result.run_state.session_dir is not None

    def test_shell_v1_without_request_succeeds(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_SESSIONS_BASE",
            tmp_path / "sessions",
        )
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_POINTER_PATH",
            tmp_path / "current_session.json",
        )

        step = _make_step("step-a", component="constitution", outputs=["art_a"])
        spec = _make_spec(step)
        plan = _make_plan(step)

        config = ExecutionConfig(mode="shell_v1")  # no request, no backend

        result = execute_plan(
            spec, plan,
            verdict_status="ready",
            config=config,
        )
        assert result.run_state.session_dir is not None


# ---------------------------------------------------------------------------
# 8. Real governance_context payload generation
# ---------------------------------------------------------------------------


class TestGovernanceContextPayload:
    def test_request_bearing_payload(self) -> None:
        run_state = GovernanceRunState(
            run_id="test-run-123",
            started_at=datetime.now(timezone.utc),
        )
        config = ExecutionConfig(
            mode="agent_execution",
            request_text="Rename NO_TRADE to HOLIDAY",
            request_id="req-456",
            request_source="manual",
        )

        payload = _build_governance_context_payload(
            run_state, config, "governance-workflow",
        )

        assert payload["produced_by"] == "load-context"
        assert payload["run_id"] == "test-run-123"
        assert payload["request_text"] == "Rename NO_TRADE to HOLIDAY"
        assert payload["request_id"] == "req-456"
        assert payload["request_source"] == "manual"
        assert payload["workflow_name"] == "governance-workflow"
        assert payload["execution_mode"] == "agent_execution"
        assert payload["bootstrap_status"] == "request_bearing"

    def test_structural_only_payload(self) -> None:
        run_state = GovernanceRunState(
            run_id="test-run-789",
            started_at=datetime.now(timezone.utc),
        )
        config = ExecutionConfig(mode="dry_run")  # no request_text

        payload = _build_governance_context_payload(
            run_state, config, "governance-workflow",
        )

        assert payload["produced_by"] == "load-context"
        assert payload["structural"] is True
        assert payload["bootstrap_status"] == "structural_only"
        assert payload["run_id"] == "test-run-789"
        assert "request_text" not in payload

    def test_load_context_produces_request_bearing_artifact(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_SESSIONS_BASE",
            tmp_path / "sessions",
        )
        monkeypatch.setattr(
            "governance.dag_runner.session._DEFAULT_POINTER_PATH",
            tmp_path / "current_session.json",
        )

        step = _make_step(
            "load-context",
            component="constitution",
            outputs=["governance_context"],
        )
        spec = _make_spec(step)
        plan = _make_plan(step)
        backend = MockExecutionBackend()

        config = ExecutionConfig(
            mode="agent_execution",
            request_text="Test governance request",
            request_id="req-001",
            request_source="test",
        )

        result = execute_plan(
            spec, plan,
            verdict_status="ready",
            config=config,
            backend=backend,
        )

        # Check the governance_context artifact in run state
        ctx = result.run_state.artifacts.get("governance_context")
        assert ctx is not None
        assert ctx.status == "present"
        assert ctx.payload["request_text"] == "Test governance request"
        assert ctx.payload["request_id"] == "req-001"
        assert ctx.payload["request_source"] == "test"
        assert ctx.payload["bootstrap_status"] == "request_bearing"


# ---------------------------------------------------------------------------
# 9. Config builder with bootstrap fields
# ---------------------------------------------------------------------------


class TestConfigBuilder:
    def test_bootstrap_fields_passed_through(self) -> None:
        config = build_config_from_args(
            mode="agent_execution",
            request_text="some request",
            request_id="r-1",
            request_source="pr",
        )
        assert config.request_text == "some request"
        assert config.request_id == "r-1"
        assert config.request_source == "pr"

    def test_defaults_to_none(self) -> None:
        config = build_config_from_args()
        assert config.request_text is None
        assert config.request_id is None
        assert config.request_source is None
