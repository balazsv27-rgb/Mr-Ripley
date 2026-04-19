"""Tests for halt-on-critical-failure control flow (R1-A / F1).

Verifies that when a step FAILs and raises a blocker with
``halts_workflow=True``, ALL subsequent steps are skipped.
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
# Test helpers
# ---------------------------------------------------------------------------


class FailingMockExecutionBackend(MockExecutionBackend):
    """Backend that returns ``success=False`` for specified steps."""

    def __init__(self, failing_steps: set[str]) -> None:
        super().__init__()
        self._failing_steps = failing_steps

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        if step.name in self._failing_steps:
            return AgentExecutionResult(
                success=False,
                failure=FailureClassification(
                    origin="contract",
                    step_id=step.name,
                    detail="forced failure for test",
                ),
            )
        return super().execute_step(step, agent, config, run_state, spec, prompt_context=prompt_context, **kwargs)

    def execute_structural_step(self, step, component_kind, run_state, spec, **kwargs):
        if step.name in self._failing_steps:
            return AgentExecutionResult(
                success=False,
                failure=FailureClassification(
                    origin="contract",
                    step_id=step.name,
                    detail="forced failure for test",
                ),
            )
        return super().execute_structural_step(step, component_kind, run_state, spec, **kwargs)


def _make_step(name: str, raises: list[str] | None = None) -> WorkflowStep:
    return WorkflowStep(
        name=name,
        component="constitution",
        raises=raises or [],
    )


def _make_spec(
    steps: dict[str, WorkflowStep],
    blocking_conditions: dict[str, BlockingCondition] | None = None,
) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test-halt", workflow_version="1.0"),
        workflow_steps=steps,
        blocking_conditions=blocking_conditions or {},
    )


def _make_plan(step_ids: list[str]) -> ExecutionPlan:
    return ExecutionPlan(
        workflow_name="test-halt",
        ordered_steps=[
            PlannedNode(step_id=sid, component="constitution")
            for sid in step_ids
        ],
    )


def _default_config() -> ExecutionConfig:
    return ExecutionConfig(mode="agent_execution", request_text="test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHaltOnCriticalFailure:
    """Halt-on-critical must skip all subsequent steps."""

    def test_halt_on_critical_skips_subsequent(self) -> None:
        steps = {
            "step-a": _make_step("step-a"),
            "step-b": _make_step("step-b", raises=["fatal_blocker"]),
            "step-c": _make_step("step-c"),
        }
        spec = _make_spec(
            steps,
            blocking_conditions={
                "fatal_blocker": BlockingCondition(
                    id="fatal_blocker", halts_workflow=True
                ),
            },
        )
        plan = _make_plan(["step-a", "step-b", "step-c"])
        backend = FailingMockExecutionBackend(failing_steps={"step-b"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        rs = result.run_state

        assert rs.node_results["step-a"].status == "PASS"
        assert rs.node_results["step-b"].status == "FAIL"
        assert rs.node_results["step-c"].status == "SKIP"
        assert "halt-on-critical-failure" in rs.node_results["step-c"].summary.lower()

    def test_non_halting_failure_continues(self) -> None:
        steps = {
            "step-a": _make_step("step-a"),
            "step-b": _make_step("step-b", raises=["soft_blocker"]),
            "step-c": _make_step("step-c"),
        }
        spec = _make_spec(
            steps,
            blocking_conditions={
                "soft_blocker": BlockingCondition(
                    id="soft_blocker", halts_workflow=False
                ),
            },
        )
        plan = _make_plan(["step-a", "step-b", "step-c"])
        backend = FailingMockExecutionBackend(failing_steps={"step-b"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        rs = result.run_state

        assert rs.node_results["step-a"].status == "PASS"
        assert rs.node_results["step-b"].status == "FAIL"
        assert rs.node_results["step-c"].status == "PASS"

    def test_halt_trace_event_recorded(self) -> None:
        steps = {
            "step-a": _make_step("step-a"),
            "step-b": _make_step("step-b", raises=["fatal_blocker"]),
            "step-c": _make_step("step-c"),
        }
        spec = _make_spec(
            steps,
            blocking_conditions={
                "fatal_blocker": BlockingCondition(
                    id="fatal_blocker", halts_workflow=True
                ),
            },
        )
        plan = _make_plan(["step-a", "step-b", "step-c"])
        backend = FailingMockExecutionBackend(failing_steps={"step-b"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)

        event_types = [e.event_type for e in result.run_state.execution_trace]
        assert "halt_on_critical_failure" in event_types

    def test_halt_blocking_event_recorded(self) -> None:
        steps = {
            "step-a": _make_step("step-a"),
            "step-b": _make_step("step-b", raises=["fatal_blocker"]),
            "step-c": _make_step("step-c"),
        }
        spec = _make_spec(
            steps,
            blocking_conditions={
                "fatal_blocker": BlockingCondition(
                    id="fatal_blocker", halts_workflow=True
                ),
            },
        )
        plan = _make_plan(["step-a", "step-b", "step-c"])
        backend = FailingMockExecutionBackend(failing_steps={"step-b"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        rs = result.run_state

        assert len(rs.blocking_conditions) == 1
        assert rs.blocking_conditions[0].blocking_id == "fatal_blocker"
        assert rs.blocking_conditions[0].severity == "critical"
        assert rs.blocking_conditions[0].resolved is False

    def test_halt_skips_all_remaining(self) -> None:
        steps = {
            "step-a": _make_step("step-a"),
            "step-b": _make_step("step-b", raises=["fatal_blocker"]),
            "step-c": _make_step("step-c"),
            "step-d": _make_step("step-d"),
            "step-e": _make_step("step-e"),
        }
        spec = _make_spec(
            steps,
            blocking_conditions={
                "fatal_blocker": BlockingCondition(
                    id="fatal_blocker", halts_workflow=True
                ),
            },
        )
        plan = _make_plan(["step-a", "step-b", "step-c", "step-d", "step-e"])
        backend = FailingMockExecutionBackend(failing_steps={"step-b"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        rs = result.run_state

        assert rs.node_results["step-a"].status == "PASS"
        assert rs.node_results["step-b"].status == "FAIL"
        for sid in ("step-c", "step-d", "step-e"):
            assert rs.node_results[sid].status == "SKIP", f"{sid} should be SKIP"
            assert "halt_on_critical_failure=True" in rs.node_results[sid].evidence

    def test_failure_without_raises_continues(self) -> None:
        """A step that FAILs but has no raises list should not halt."""
        steps = {
            "step-a": _make_step("step-a"),
            "step-b": _make_step("step-b"),  # no raises
            "step-c": _make_step("step-c"),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a", "step-b", "step-c"])
        backend = FailingMockExecutionBackend(failing_steps={"step-b"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        rs = result.run_state

        assert rs.node_results["step-a"].status == "PASS"
        assert rs.node_results["step-b"].status == "FAIL"
        assert rs.node_results["step-c"].status == "PASS"
