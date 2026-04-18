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
    PromptContext,
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


# ---------------------------------------------------------------------------
# B1: PromptContext round-trip and backward compatibility
# ---------------------------------------------------------------------------


def test_prompt_context_construction_all_fields() -> None:
    """PromptContext is a frozen dataclass with all declared fields."""
    agent = _make_agent()
    ctx = PromptContext(
        assembled_prompt="You are a test skill.",
        agent=agent,
        skill_content="# SKILL.md content",
        agent_instructions="# Agent instructions",
        artifact_inputs={"upstream_out": {"data": {"key": "value"}}},
        document_paths=["README_v1.md"],
        token_budget=50_000,
        token_estimate=12_000,
        truncated=True,
        truncation_events=[{"section": "documents", "dropped": 2}],
    )
    assert ctx.assembled_prompt == "You are a test skill."
    assert ctx.agent is agent
    assert ctx.skill_content == "# SKILL.md content"
    assert ctx.agent_instructions == "# Agent instructions"
    assert ctx.artifact_inputs == {"upstream_out": {"data": {"key": "value"}}}
    assert ctx.document_paths == ["README_v1.md"]
    assert ctx.token_budget == 50_000
    assert ctx.token_estimate == 12_000
    assert ctx.truncated is True
    assert len(ctx.truncation_events) == 1


def test_prompt_context_defaults() -> None:
    """PromptContext with only required field uses correct defaults."""
    ctx = PromptContext(assembled_prompt="minimal")
    assert ctx.agent is None
    assert ctx.skill_content == ""
    assert ctx.agent_instructions == ""
    assert ctx.artifact_inputs == {}
    assert ctx.document_paths == []
    assert ctx.token_budget == 100_000
    assert ctx.token_estimate == 0
    assert ctx.truncated is False
    assert ctx.truncation_events == []


def test_prompt_context_is_frozen() -> None:
    """PromptContext is immutable."""
    ctx = PromptContext(assembled_prompt="frozen")
    import pytest
    with pytest.raises(AttributeError):
        ctx.assembled_prompt = "changed"  # type: ignore[misc]


def test_mock_backend_execute_step_with_prompt_context() -> None:
    """MockExecutionBackend.execute_step() accepts and ignores prompt_context."""
    backend = MockExecutionBackend()
    step = _make_step(outputs=["art_a"])
    ctx = PromptContext(assembled_prompt="ignored by mock")
    result = backend.execute_step(
        step=step,
        agent=_make_agent(),
        config=ExecutionConfig(),
        run_state=_make_run_state(),
        spec=_make_spec(),
        prompt_context=ctx,
    )
    assert result.success is True
    assert "art_a" in result.artifacts_produced


def test_mock_backend_execute_step_without_prompt_context() -> None:
    """MockExecutionBackend.execute_step() works without prompt_context (backward compat)."""
    backend = MockExecutionBackend()
    step = _make_step(outputs=["art_b"])
    result = backend.execute_step(
        step=step,
        agent=_make_agent(),
        config=ExecutionConfig(),
        run_state=_make_run_state(),
        spec=_make_spec(),
    )
    assert result.success is True
    assert "art_b" in result.artifacts_produced
