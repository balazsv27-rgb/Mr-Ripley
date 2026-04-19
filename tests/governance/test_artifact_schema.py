"""Tests for B5: artifact schema validation.

Unit tests for governance.dag_runner.artifact_schema plus
integration tests verifying validation in the executor pipeline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from governance.dag_runner.artifact_schema import (
    ArtifactSchemaError,
    ArtifactSchemaViolation,
    validate_artifact_output,
)
from governance.dag_runner.execution_backend import (
    ExecutionBackend,
    MockExecutionBackend,
)
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.models import (
    AgentExecutionResult,
    AgentSpec,
    AssembledWorkflowSpec,
    ExecutionConfig,
    GovernanceRunState,
    ManifestSpec,
    PromptContext,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan, PlannedNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    name: str = "test-step",
    outputs: list[str] | None = None,
    component: str = "skill:test",
    raises: list[str] | None = None,
    agent_binding: str | None = None,
) -> WorkflowStep:
    raw: dict[str, Any] = {}
    if agent_binding:
        raw["agent_binding"] = agent_binding
    return WorkflowStep(
        name=name,
        component=component,
        outputs=outputs if outputs is not None else ["test_artifact"],
        raises=raises or [],
        raw=raw,
    )


def _make_spec(
    steps: dict[str, WorkflowStep] | None = None,
    agents: dict[str, AgentSpec] | None = None,
) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test"),
        workflow_steps=steps or {},
        agents=agents or {},
    )


def _make_run_state() -> GovernanceRunState:
    return GovernanceRunState(
        run_id="test-run",
        started_at=datetime.now(timezone.utc),
    )


def _make_plan(step_ids: list[str], component: str = "skill:test") -> ExecutionPlan:
    return ExecutionPlan(
        workflow_name="test",
        ordered_steps=[
            PlannedNode(step_id=sid, component=component)
            for sid in step_ids
        ],
    )


class _LiveStubBackend(ExecutionBackend):
    """Non-Mock backend stub for testing strict validation."""

    def __init__(self, artifacts: dict[str, dict[str, Any]] | None = None) -> None:
        self._artifacts = artifacts or {}

    def execute_step(
        self, step, agent, config, run_state, spec, prompt_context=None, **kwargs,
    ) -> AgentExecutionResult:
        return AgentExecutionResult(
            success=True,
            artifacts_produced=self._artifacts,
        )

    def execute_structural_step(
        self, step, component_kind, run_state, spec, **kwargs,
    ) -> AgentExecutionResult:
        return AgentExecutionResult(success=True)


# ===========================================================================
# Unit tests — validate_artifact_output
# ===========================================================================


class TestValidateArtifactOutput:
    """Unit tests for the validate_artifact_output function."""

    def test_valid_payload_passes(self) -> None:
        step = _make_step(outputs=["my_artifact"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "my_artifact",
            {"produced_by": "test-step", "data": {"key": "value"}},
            step,
            spec,
        )
        assert violations == []

    def test_minimal_valid_payload(self) -> None:
        """Payload with only produced_by is valid."""
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "art_a",
            {"produced_by": "test-step"},
            step,
            spec,
        )
        assert violations == []

    def test_empty_payload_violation(self) -> None:
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output("art_a", {}, step, spec)
        assert len(violations) == 1
        assert violations[0].violation == "payload_empty"
        assert violations[0].artifact_name == "art_a"

    def test_payload_not_dict_violation(self) -> None:
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output("art_a", "not a dict", step, spec)
        assert len(violations) == 1
        assert violations[0].violation == "payload_not_dict"
        assert violations[0].detail["actual_type"] == "str"

    def test_payload_none_violation(self) -> None:
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output("art_a", None, step, spec)
        assert len(violations) == 1
        assert violations[0].violation == "payload_not_dict"

    def test_missing_produced_by(self) -> None:
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "art_a",
            {"data": {"key": "value"}},
            step,
            spec,
        )
        assert any(v.violation == "missing_produced_by" for v in violations)

    def test_produced_by_mismatch(self) -> None:
        step = _make_step(name="correct-step", outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "art_a",
            {"produced_by": "wrong-step"},
            step,
            spec,
        )
        assert any(v.violation == "produced_by_mismatch" for v in violations)
        mismatch = [v for v in violations if v.violation == "produced_by_mismatch"][0]
        assert mismatch.detail["expected"] == "correct-step"
        assert mismatch.detail["actual"] == "wrong-step"

    def test_forbidden_envelope_key_artifact(self) -> None:
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "art_a",
            {"produced_by": "test-step", "artifact": "art_a"},
            step,
            spec,
        )
        assert any(v.violation == "forbidden_envelope_keys" for v in violations)

    def test_forbidden_envelope_key_session(self) -> None:
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "art_a",
            {"produced_by": "test-step", "session": "abc"},
            step,
            spec,
        )
        assert any(v.violation == "forbidden_envelope_keys" for v in violations)

    def test_forbidden_envelope_key_timestamp(self) -> None:
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "art_a",
            {"produced_by": "test-step", "timestamp": "2026-01-01"},
            step,
            spec,
        )
        assert any(v.violation == "forbidden_envelope_keys" for v in violations)

    def test_multiple_forbidden_keys(self) -> None:
        step = _make_step(outputs=["art_a"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "art_a",
            {"produced_by": "test-step", "artifact": "x", "session": "y"},
            step,
            spec,
        )
        forbidden = [v for v in violations if v.violation == "forbidden_envelope_keys"]
        assert len(forbidden) == 1
        assert set(forbidden[0].detail["keys"]) == {"artifact", "session"}

    def test_undeclared_artifact(self) -> None:
        step = _make_step(outputs=["declared_art"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "undeclared_art",
            {"produced_by": "test-step"},
            step,
            spec,
        )
        assert any(v.violation == "undeclared_artifact" for v in violations)

    def test_multiple_violations_combined(self) -> None:
        """A payload can have multiple violations at once."""
        step = _make_step(outputs=["other_art"])
        spec = _make_spec()
        violations = validate_artifact_output(
            "wrong_name",
            {"produced_by": "wrong-step", "session": "abc"},
            step,
            spec,
        )
        violation_types = {v.violation for v in violations}
        assert "produced_by_mismatch" in violation_types
        assert "forbidden_envelope_keys" in violation_types
        assert "undeclared_artifact" in violation_types


class TestArtifactSchemaViolationDataclass:
    """ArtifactSchemaViolation is a well-formed frozen dataclass."""

    def test_construction(self) -> None:
        v = ArtifactSchemaViolation(
            artifact_name="art_a",
            violation="payload_empty",
        )
        assert v.artifact_name == "art_a"
        assert v.violation == "payload_empty"
        assert v.detail == {}

    def test_with_detail(self) -> None:
        v = ArtifactSchemaViolation(
            artifact_name="art_a",
            violation="forbidden_envelope_keys",
            detail={"keys": ["session"]},
        )
        assert v.detail["keys"] == ["session"]

    def test_is_frozen(self) -> None:
        v = ArtifactSchemaViolation(artifact_name="a", violation="b")
        with pytest.raises(AttributeError):
            v.artifact_name = "changed"  # type: ignore[misc]


class TestArtifactSchemaError:
    """ArtifactSchemaError is a RuntimeError."""

    def test_is_runtime_error(self) -> None:
        assert issubclass(ArtifactSchemaError, RuntimeError)

    def test_message(self) -> None:
        err = ArtifactSchemaError("bad schema")
        assert str(err) == "bad schema"


# ===========================================================================
# Integration tests — validation in executor pipeline
# ===========================================================================


class TestArtifactValidationInExecutor:
    """Artifact validation integrated into the V2 executor pipeline."""

    def test_mock_backend_valid_artifacts_emit_trace(self) -> None:
        """MockExecutionBackend with valid artifacts emits artifact_validated(passed=True)."""
        step = _make_step("step-a", outputs=["art_a"])
        spec = _make_spec({"step-a": step})
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(
            spec, plan,
            config=ExecutionConfig(mode="agent_execution", request_text="test"),
            backend=backend,
        )
        assert result.run_state.node_results["step-a"].status == "PASS"

        trace_types = [
            e.event_type for e in result.run_state.execution_trace
        ]
        assert "artifact_validated" in trace_types
        validated = [
            e for e in result.run_state.execution_trace
            if e.event_type == "artifact_validated"
        ]
        assert validated[0].detail["passed"] is True

    def test_mock_backend_bad_artifacts_warn_only(self) -> None:
        """MockExecutionBackend with violations → warn, step still PASS."""
        # Provide a payload with a forbidden envelope key
        bad_payloads = {
            "art_a": {"produced_by": "step-a", "session": "leak"},
        }
        step = _make_step("step-a", outputs=["art_a"])
        spec = _make_spec({"step-a": step})
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend(artifact_payloads=bad_payloads)

        result = execute_plan(
            spec, plan,
            config=ExecutionConfig(mode="agent_execution", request_text="test"),
            backend=backend,
        )
        # Mock → warn only, step still passes
        assert result.run_state.node_results["step-a"].status == "PASS"

        validated = [
            e for e in result.run_state.execution_trace
            if e.event_type == "artifact_validated"
        ]
        assert len(validated) == 1
        assert validated[0].detail["passed"] is False
        assert validated[0].detail["strict"] is False

    def test_live_backend_bad_artifacts_step_fail(self) -> None:
        """Non-Mock backend with violations → step FAIL (strict)."""
        bad_artifacts = {
            "art_a": {"produced_by": "step-a", "session": "leak"},
        }
        step = _make_step(
            "step-a", outputs=["art_a"],
            agent_binding="test-agent",
        )
        agent = AgentSpec(name="test-agent", skill_bindings=["test-skill"])
        spec = _make_spec(
            {"step-a": step},
            agents={"test-agent": agent},
        )
        plan = _make_plan(["step-a"])
        backend = _LiveStubBackend(artifacts=bad_artifacts)

        result = execute_plan(
            spec, plan,
            config=ExecutionConfig(mode="agent_execution", request_text="test"),
            backend=backend,
        )
        assert result.run_state.node_results["step-a"].status == "FAIL"
        assert "schema validation" in result.run_state.node_results["step-a"].summary.lower()

        validated = [
            e for e in result.run_state.execution_trace
            if e.event_type == "artifact_validated"
        ]
        assert len(validated) == 1
        assert validated[0].detail["passed"] is False
        assert validated[0].detail["strict"] is True

    def test_live_backend_valid_artifacts_pass(self) -> None:
        """Non-Mock backend with valid artifacts → step PASS."""
        good_artifacts = {
            "art_a": {"produced_by": "step-a", "data": {"ok": True}},
        }
        step = _make_step(
            "step-a", outputs=["art_a"],
            agent_binding="test-agent",
        )
        agent = AgentSpec(name="test-agent", skill_bindings=["test-skill"])
        spec = _make_spec(
            {"step-a": step},
            agents={"test-agent": agent},
        )
        plan = _make_plan(["step-a"])
        backend = _LiveStubBackend(artifacts=good_artifacts)

        result = execute_plan(
            spec, plan,
            config=ExecutionConfig(mode="agent_execution", request_text="test"),
            backend=backend,
        )
        assert result.run_state.node_results["step-a"].status == "PASS"

        validated = [
            e for e in result.run_state.execution_trace
            if e.event_type == "artifact_validated"
        ]
        assert len(validated) == 1
        assert validated[0].detail["passed"] is True

    def test_dry_run_no_artifact_validation(self) -> None:
        """Dry-run mode does not emit artifact_validated events."""
        step = _make_step("step-a", outputs=["art_a"])
        spec = _make_spec({"step-a": step})
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(
            spec, plan,
            config=ExecutionConfig(mode="dry_run"),
            backend=backend,
        )
        trace_types = [
            e.event_type for e in result.run_state.execution_trace
        ]
        assert "artifact_validated" not in trace_types

    def test_structural_step_no_artifact_validation(self) -> None:
        """Structural steps (constitution, etc.) skip artifact validation.

        Structural steps produce artifacts but they are deterministic.
        Because structural steps return from the backend without going
        through the skill/agent path, they skip prompt assembly and
        therefore also skip the artifact validation block (which
        depends on the skill/agent path flow).
        """
        step = _make_step("step-a", outputs=["ctx"], component="constitution")
        spec = _make_spec({"step-a": step})
        plan = ExecutionPlan(
            workflow_name="test",
            ordered_steps=[
                PlannedNode(step_id="step-a", component="constitution")
            ],
        )
        backend = MockExecutionBackend()

        result = execute_plan(
            spec, plan,
            config=ExecutionConfig(mode="agent_execution", request_text="test"),
            backend=backend,
        )
        assert result.run_state.node_results["step-a"].status == "PASS"

    def test_failed_backend_invocation_no_validation(self) -> None:
        """When backend returns success=False, no artifact validation occurs."""

        class _FailBackend(ExecutionBackend):
            def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
                return AgentExecutionResult(success=False)

            def execute_structural_step(self, step, component_kind, run_state, spec, **kwargs):
                return AgentExecutionResult(success=False)

        step = _make_step("step-a", outputs=["art_a"])
        spec = _make_spec({"step-a": step})
        plan = _make_plan(["step-a"])
        backend = _FailBackend()

        result = execute_plan(
            spec, plan,
            config=ExecutionConfig(mode="agent_execution", request_text="test"),
            backend=backend,
        )
        assert result.run_state.node_results["step-a"].status == "FAIL"

        trace_types = [
            e.event_type for e in result.run_state.execution_trace
        ]
        assert "artifact_validated" not in trace_types
