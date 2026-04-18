"""Tests for governance.dag_runner.execution_backend."""
from __future__ import annotations

from governance.dag_runner.execution_backend import (
    ExecutionBackend,
    MockExecutionBackend,
)
from governance.dag_runner.models import (
    AgentSpec,
    AssembledWorkflowSpec,
    ExecutionConfig,
    GovernanceRunState,
    ManifestSpec,
    WorkflowStep,
)

from datetime import datetime, timezone


def _make_run_state() -> GovernanceRunState:
    return GovernanceRunState(
        run_id="test-run",
        started_at=datetime.now(timezone.utc),
    )


def _make_step(name: str = "test-step", outputs: list[str] | None = None) -> WorkflowStep:
    return WorkflowStep(
        name=name,
        component="skill:test-skill",
        outputs=["test_artifact"] if outputs is None else outputs,
    )


def _make_agent(name: str = "test-agent") -> AgentSpec:
    return AgentSpec(name=name, skill_bindings=["test-skill"])


def _make_spec() -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(manifest=ManifestSpec(workflow_name="test"))


def test_mock_backend_is_execution_backend() -> None:
    backend = MockExecutionBackend()
    assert isinstance(backend, ExecutionBackend)


def test_mock_backend_produces_artifacts_for_outputs() -> None:
    backend = MockExecutionBackend()
    step = _make_step(outputs=["artifact_a", "artifact_b"])
    result = backend.execute_step(
        step=step,
        agent=_make_agent(),
        config=ExecutionConfig(),
        run_state=_make_run_state(),
        spec=_make_spec(),
    )
    assert result.success is True
    assert "artifact_a" in result.artifacts_produced
    assert "artifact_b" in result.artifacts_produced


def test_mock_backend_uses_provided_payloads() -> None:
    custom = {"my_artifact": {"custom_key": "custom_value"}}
    backend = MockExecutionBackend(artifact_payloads=custom)
    step = _make_step(outputs=["my_artifact"])
    result = backend.execute_step(
        step=step,
        agent=_make_agent(),
        config=ExecutionConfig(),
        run_state=_make_run_state(),
        spec=_make_spec(),
    )
    assert result.artifacts_produced["my_artifact"]["custom_key"] == "custom_value"


def test_mock_backend_fallback_for_unknown_artifact() -> None:
    backend = MockExecutionBackend(artifact_payloads={"other": {"x": 1}})
    step = _make_step(outputs=["unknown_artifact"])
    result = backend.execute_step(
        step=step,
        agent=_make_agent(),
        config=ExecutionConfig(),
        run_state=_make_run_state(),
        spec=_make_spec(),
    )
    assert result.artifacts_produced["unknown_artifact"]["produced_by"] == "test-step"


def test_mock_backend_structural_step() -> None:
    backend = MockExecutionBackend()
    step = _make_step(outputs=["governance_context"])
    result = backend.execute_structural_step(
        step=step,
        component_kind="constitution",
        run_state=_make_run_state(),
        spec=_make_spec(),
    )
    assert result.success is True
    assert "governance_context" in result.artifacts_produced
    assert result.artifacts_produced["governance_context"]["structural"] is True


def test_mock_backend_empty_outputs() -> None:
    backend = MockExecutionBackend()
    step = _make_step(outputs=[])
    result = backend.execute_step(
        step=step,
        agent=_make_agent(),
        config=ExecutionConfig(),
        run_state=_make_run_state(),
        spec=_make_spec(),
    )
    assert result.success is True
    assert result.artifacts_produced == {}
