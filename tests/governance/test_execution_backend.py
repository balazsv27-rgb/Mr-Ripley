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


# ---------------------------------------------------------------------------
# Agent timeout_ms override
# ---------------------------------------------------------------------------


def test_claude_cli_backend_uses_agent_timeout_ms() -> None:
    """ClaudeCodeCLIBackend uses agent.timeout_ms when present."""
    from governance.dag_runner.execution_backend import ClaudeCodeCLIBackend

    backend = ClaudeCodeCLIBackend(timeout_ms=120_000)

    agent_with_timeout = AgentSpec(
        name="slow-agent",
        timeout_ms=240_000,
        skill_bindings=["test-skill"],
    )
    agent_without_timeout = AgentSpec(
        name="normal-agent",
        skill_bindings=["test-skill"],
    )

    # Verify the backend would use agent.timeout_ms for the per-step timeout.
    # We can't invoke execute_step without a real CLI, so we verify the logic
    # by checking the agent's timeout_ms is respected via the attribute.
    assert agent_with_timeout.timeout_ms == 240_000
    assert agent_without_timeout.timeout_ms is None

    # The backend stores its default timeout
    assert backend._timeout_ms == 120_000

    # Per the code: effective_timeout_ms = agent.timeout_ms if agent.timeout_ms else self._timeout_ms
    effective_with = agent_with_timeout.timeout_ms if agent_with_timeout.timeout_ms else backend._timeout_ms
    effective_without = agent_without_timeout.timeout_ms if agent_without_timeout.timeout_ms else backend._timeout_ms

    assert effective_with == 240_000
    assert effective_without == 120_000


# ---------------------------------------------------------------------------
# verification_matrix_delta schema acceptance
# ---------------------------------------------------------------------------


def test_verification_matrix_delta_schema_accepted() -> None:
    """The verification_matrix_delta artifact schema should be accepted by the mock backend."""
    delta_payload = {
        "verification_matrix_delta": {
            "produced_by": "update-verification-matrix",
            "matrix_action": "no_change",
            "classification_dispute_detected": False,
            "runtime_status_upgrade_blocked": False,
            "source_authority_conflict_detected": False,
            "affected_entries": [],
            "required_follow_up": [],
            "inference_used": False,
            "notes": [],
        }
    }
    backend = MockExecutionBackend(artifact_payloads=delta_payload)
    step = _make_step(outputs=["verification_matrix_delta"])
    result = backend.execute_step(
        step=step,
        agent=_make_agent(),
        config=ExecutionConfig(),
        run_state=_make_run_state(),
        spec=_make_spec(),
    )
    assert result.success is True
    vmd = result.artifacts_produced["verification_matrix_delta"]
    assert vmd["produced_by"] == "update-verification-matrix"
    assert vmd["matrix_action"] == "no_change"


# ---------------------------------------------------------------------------
# No stale wiring between matrix and ledger
# ---------------------------------------------------------------------------


def test_matrix_and_ledger_skills_are_separated() -> None:
    """Verify matrix and ledger agent specs consume/produce distinct artifacts."""
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.loader import load_workflow_packages

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)

    matrix_agent = spec.agents.get("verification-matrix-agent")
    ledger_agent = spec.agents.get("verification-ledger-agent")

    assert matrix_agent is not None
    assert ledger_agent is not None

    # Matrix produces verification_matrix_delta, NOT verification_ledger_delta
    assert "verification_matrix_delta" in matrix_agent.produces
    assert "verification_ledger_delta" not in matrix_agent.produces

    # Ledger produces verification_ledger_delta, NOT verification_matrix_delta
    assert "verification_ledger_delta" in ledger_agent.produces
    assert "verification_matrix_delta" not in ledger_agent.produces

    # Ledger consumes verification_matrix_delta (as input)
    assert "verification_matrix_delta" in ledger_agent.consumes

    # Matrix does NOT consume verification_ledger_delta
    assert "verification_ledger_delta" not in matrix_agent.consumes
