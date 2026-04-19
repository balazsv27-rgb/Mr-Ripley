"""Tests for R3-D: minimum trace event coverage.

Verifies that V2 execution emits the required trace events:
- backend_invocation_started
- backend_invocation_completed
- backend_invocation_failed
- artifact_produced (covered by R2-A tests, verified here too)
- blocking_event_raised
"""
from __future__ import annotations

import pytest

from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.models import (
    AgentExecutionResult,
    AssembledWorkflowSpec,
    BlockingCondition,
    ExecutionConfig,
    FailureClassification,
    ManifestSpec,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan, PlannedNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FailingMockBackend(MockExecutionBackend):
    """Backend that fails for specified steps."""

    def __init__(self, failing_steps: set[str]) -> None:
        super().__init__()
        self._failing = failing_steps

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        if step.name in self._failing:
            return AgentExecutionResult(
                success=False,
                failure=FailureClassification(
                    origin="contract", step_id=step.name,
                    detail="forced failure",
                ),
            )
        return super().execute_step(step, agent, config, run_state, spec, prompt_context=prompt_context, **kwargs)

    def execute_structural_step(self, step, component_kind, run_state, spec, **kwargs):
        if step.name in self._failing:
            return AgentExecutionResult(
                success=False,
                failure=FailureClassification(
                    origin="contract", step_id=step.name,
                    detail="forced failure",
                ),
            )
        return super().execute_structural_step(
            step, component_kind, run_state, spec, **kwargs,
        )


def _make_step(name: str, **kwargs) -> WorkflowStep:
    return WorkflowStep(name=name, component="constitution", **kwargs)


def _make_spec(
    steps: dict[str, WorkflowStep],
    blocking_conditions: dict[str, BlockingCondition] | None = None,
) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test-trace", workflow_version="1.0"),
        workflow_steps=steps,
        blocking_conditions=blocking_conditions or {},
    )


def _make_plan(step_ids: list[str]) -> ExecutionPlan:
    return ExecutionPlan(
        workflow_name="test-trace",
        ordered_steps=[
            PlannedNode(step_id=sid, component="constitution")
            for sid in step_ids
        ],
    )


def _config() -> ExecutionConfig:
    return ExecutionConfig(mode="agent_execution", request_text="test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBackendInvocationTraceEvents:
    """V2 execution emits backend_invocation_started/completed/failed."""

    def test_successful_step_emits_started_and_completed(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_config(), backend=backend)
        event_types = [
            e.event_type for e in result.run_state.execution_trace
        ]
        assert "backend_invocation_started" in event_types
        assert "backend_invocation_completed" in event_types

    def test_failed_step_emits_started_and_failed(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend(failing_steps={"step-a"})

        result = execute_plan(spec, plan, config=_config(), backend=backend)
        event_types = [
            e.event_type for e in result.run_state.execution_trace
        ]
        assert "backend_invocation_started" in event_types
        assert "backend_invocation_failed" in event_types
        assert "backend_invocation_completed" not in event_types

    def test_started_precedes_completed(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_config(), backend=backend)
        events = result.run_state.execution_trace
        step_events = [
            e for e in events
            if e.node_name == "step-a"
            and e.event_type in (
                "backend_invocation_started",
                "backend_invocation_completed",
            )
        ]
        assert len(step_events) == 2
        assert step_events[0].event_type == "backend_invocation_started"
        assert step_events[1].event_type == "backend_invocation_completed"

    def test_dry_run_no_backend_invocation_events(self) -> None:
        """Dry-run mode does not invoke the backend → no invocation events."""
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()
        config = ExecutionConfig(mode="dry_run")

        result = execute_plan(spec, plan, config=config, backend=backend)
        event_types = [
            e.event_type for e in result.run_state.execution_trace
        ]
        assert "backend_invocation_started" not in event_types
        assert "backend_invocation_completed" not in event_types


class TestBlockingEventRaisedTrace:
    """blocking_event_raised emitted when a blocking event is appended."""

    def test_blocking_event_raised_on_halt(self) -> None:
        steps = {
            "step-a": _make_step("step-a", raises=["fatal"]),
            "step-b": _make_step("step-b"),
        }
        blocking = {
            "fatal": BlockingCondition(id="fatal", halts_workflow=True),
        }
        spec = _make_spec(steps, blocking_conditions=blocking)
        plan = _make_plan(["step-a", "step-b"])
        backend = FailingMockBackend(failing_steps={"step-a"})

        result = execute_plan(spec, plan, config=_config(), backend=backend)
        event_types = [
            e.event_type for e in result.run_state.execution_trace
        ]
        assert "blocking_event_raised" in event_types

    def test_blocking_event_detail_includes_severity(self) -> None:
        steps = {
            "step-a": _make_step("step-a", raises=["fatal"]),
        }
        blocking = {
            "fatal": BlockingCondition(id="fatal", halts_workflow=True),
        }
        spec = _make_spec(steps, blocking_conditions=blocking)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend(failing_steps={"step-a"})

        result = execute_plan(spec, plan, config=_config(), backend=backend)
        block_events = [
            e for e in result.run_state.execution_trace
            if e.event_type == "blocking_event_raised"
        ]
        assert len(block_events) == 1
        assert block_events[0].detail["severity"] == "critical"
        assert block_events[0].detail["halts_workflow"] is True
