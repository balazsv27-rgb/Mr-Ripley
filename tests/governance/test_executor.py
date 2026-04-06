"""
Tests for governance/dag_runner/executor.py

Covers both the updated integration behaviour (real workflow with runtime
predicate evaluation) and unit-style tests for individual executor runtime
semantics using small inline specs/plans.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.blockers import analyze_blockers
from governance.dag_runner.executor import ExecutionResult, ExecutorError, execute_plan
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.models import (
    AssembledWorkflowSpec,
    ManifestSpec,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan, PlannedNode, build_execution_plan
from governance.dag_runner.validator import validate_workflow_spec
from governance.dag_runner.verdict import compute_verdict


# ---------------------------------------------------------------------------
# Inline spec/plan helpers
# ---------------------------------------------------------------------------


def _make_step(
    name: str,
    *,
    component: str = "skill:test",
    outputs: list[str] | None = None,
    raises: list[str] | None = None,
    condition: dict | None = None,
    skip_if: dict | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        name=name,
        component=component,
        outputs=outputs if outputs is not None else [f"{name}_out"],
        raises=raises if raises is not None else [],
        condition=condition,
        skip_if=skip_if,
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
# 1. Integration — real workflow with runtime predicate evaluation
# ---------------------------------------------------------------------------


def test_executor_records_v1_shell_run_state() -> None:
    """
    Full pipeline integration test.

    rename-invariance-check has a condition that references change_impact_report.change_type.
    In shell mode that field is absent → condition evaluates to False → step is SKIP.

    Expected counts (updated from shell-pass baseline):
      node_results    : 18  (all steps, including the SKIP)
      execution_trace : 39  (17 normal steps × 2 events + 1 skip step × 3 events + 2 run events)
      artifacts       : 18  (invariance_verdict is not produced because step is SKIP)
    """
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validation = validate_workflow_spec(spec)
    plan = build_execution_plan(spec)
    blockers = analyze_blockers(spec, plan)
    verdict = compute_verdict(validation, blockers)

    result = execute_plan(spec, plan, verdict_status=verdict.status)
    run_state = result.run_state

    assert run_state.final_verdict == "ready"

    # All 18 steps appear in node_results (PASS or SKIP).
    assert len(run_state.node_results) == 18

    # rename-invariance-check is SKIP because its condition is not satisfied in shell mode.
    assert run_state.node_results["rename-invariance-check"].status == "SKIP"

    # invariance_verdict is not produced by the skipped step.
    assert "invariance_verdict" not in run_state.artifacts

    # All other key steps execute normally.
    assert run_state.node_results["load-context"].status == "PASS"
    assert run_state.node_results["pre-pr-governance-readiness"].status == "PASS"

    # 18 artifacts: 19 declared minus the 1 not produced by the skipped step.
    assert len(run_state.artifacts) == 18

    # 39 trace events:
    #   1 run_started
    #   17 normal steps × 2 (step_started + step_completed)
    #   1 skip step × 3 (step_started + condition_evaluated + step_skipped)
    #   1 run_completed
    assert len(run_state.execution_trace) == 39


def test_executor_condition_evaluated_event_in_real_workflow() -> None:
    """The trace must contain a condition_evaluated event for rename-invariance-check."""
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    plan = build_execution_plan(spec)

    result = execute_plan(spec, plan, verdict_status="ready")
    trace = result.run_state.execution_trace

    condition_events = [
        e for e in trace
        if e.event_type == "condition_evaluated"
        and e.node_name == "rename-invariance-check"
    ]
    assert len(condition_events) == 1
    ev = condition_events[0]
    assert ev.detail["matched"] is False
    assert ev.detail["predicate_type"] == "artifact_field_equals"


def test_executor_skip_event_in_real_workflow() -> None:
    """The trace must contain a step_skipped event for rename-invariance-check."""
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    plan = build_execution_plan(spec)

    result = execute_plan(spec, plan, verdict_status="ready")
    trace = result.run_state.execution_trace

    skip_events = [
        e for e in trace
        if e.event_type == "step_skipped"
        and e.node_name == "rename-invariance-check"
    ]
    assert len(skip_events) == 1
    assert "condition" in skip_events[0].detail["reason"].lower()


def test_executor_blocking_conditions_empty_for_clean_real_workflow() -> None:
    """No blocking events for the current clean workflow (no predicate errors)."""
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    plan = build_execution_plan(spec)

    result = execute_plan(spec, plan, verdict_status="ready")
    assert result.run_state.blocking_conditions == []


# ---------------------------------------------------------------------------
# 2. Unit — step with no condition / no skip_if executes normally
# ---------------------------------------------------------------------------


def test_step_without_predicates_executes_as_pass() -> None:
    step = _make_step("alpha", outputs=["alpha_out"])
    spec = _make_spec(step)
    plan = _make_plan(step)

    result = execute_plan(spec, plan)
    rs = result.run_state

    assert rs.node_results["alpha"].status == "PASS"
    assert "alpha_out" in rs.artifacts


# ---------------------------------------------------------------------------
# 3. Unit — condition matches → step executes normally
# ---------------------------------------------------------------------------


def test_condition_matched_step_executes_as_pass() -> None:
    """
    Step A produces alpha_out (status=present).
    Step B has condition artifact_exists('alpha_out') → True → executes.
    """
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        condition={"type": "artifact_exists", "artifact": "alpha_out"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    result = execute_plan(spec, plan)
    rs = result.run_state

    assert rs.node_results["step-b"].status == "PASS"
    assert "beta_out" in rs.artifacts


# ---------------------------------------------------------------------------
# 4. Unit — condition does not match → SKIP, no artifact produced
# ---------------------------------------------------------------------------


def test_condition_not_matched_step_is_skip() -> None:
    """
    Step B has condition artifact_exists('nonexistent') → False → SKIP.
    beta_out must not be materialised.
    """
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        condition={"type": "artifact_exists", "artifact": "nonexistent"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    result = execute_plan(spec, plan)
    rs = result.run_state

    assert rs.node_results["step-b"].status == "SKIP"
    assert "beta_out" not in rs.artifacts
    assert "alpha_out" in rs.artifacts  # step-a still produced its artifact


def test_condition_not_matched_trace_has_condition_evaluated_and_step_skipped() -> None:
    """Trace must contain condition_evaluated (matched=False) then step_skipped."""
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        condition={"type": "artifact_exists", "artifact": "nonexistent"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    result = execute_plan(spec, plan)
    trace = result.run_state.execution_trace

    step_b_events = [e for e in trace if e.node_name == "step-b"]
    event_types = [e.event_type for e in step_b_events]

    assert "step_started" in event_types
    assert "condition_evaluated" in event_types
    assert "step_skipped" in event_types
    assert "step_completed" not in event_types

    cond_ev = next(e for e in step_b_events if e.event_type == "condition_evaluated")
    assert cond_ev.detail["matched"] is False
    assert cond_ev.detail["predicate_type"] == "artifact_exists"


def test_condition_not_matched_skip_result_has_empty_produced_artifacts() -> None:
    step = _make_step(
        "step-b",
        outputs=["beta_out"],
        condition={"type": "artifact_exists", "artifact": "nonexistent"},
    )
    spec = _make_spec(step)
    plan = _make_plan(step)

    result = execute_plan(spec, plan)
    node = result.run_state.node_results["step-b"]

    assert node.status == "SKIP"
    assert node.produced_artifacts == []
    assert node.triggered_blocks == []


# ---------------------------------------------------------------------------
# 5. Unit — skip_if does not match → step executes normally
# ---------------------------------------------------------------------------


def test_skip_if_not_matched_step_executes_as_pass() -> None:
    """
    Step A produces alpha_out.
    Step B has skip_if artifact_missing('alpha_out') → False (artifact present) → executes.
    """
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        skip_if={"type": "artifact_missing", "artifact": "alpha_out"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    result = execute_plan(spec, plan)
    rs = result.run_state

    assert rs.node_results["step-b"].status == "PASS"
    assert "beta_out" in rs.artifacts


# ---------------------------------------------------------------------------
# 6. Unit — skip_if matches → SKIP, no artifact produced
# ---------------------------------------------------------------------------


def test_skip_if_matched_step_is_skip() -> None:
    """
    Step A produces alpha_out.
    Step B has skip_if artifact_exists('alpha_out') → True → SKIP.
    """
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        skip_if={"type": "artifact_exists", "artifact": "alpha_out"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    result = execute_plan(spec, plan)
    rs = result.run_state

    assert rs.node_results["step-b"].status == "SKIP"
    assert "beta_out" not in rs.artifacts


def test_skip_if_matched_trace_has_skip_if_evaluated_and_step_skipped() -> None:
    """Trace must contain skip_if_evaluated (matched=True) then step_skipped."""
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        skip_if={"type": "artifact_exists", "artifact": "alpha_out"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    result = execute_plan(spec, plan)
    trace = result.run_state.execution_trace

    step_b_events = [e for e in trace if e.node_name == "step-b"]
    event_types = [e.event_type for e in step_b_events]

    assert "step_started" in event_types
    assert "skip_if_evaluated" in event_types
    assert "step_skipped" in event_types
    assert "step_completed" not in event_types
    assert "condition_evaluated" not in event_types  # no condition on this step

    skip_ev = next(e for e in step_b_events if e.event_type == "skip_if_evaluated")
    assert skip_ev.detail["matched"] is True


# ---------------------------------------------------------------------------
# 7. Unit — condition evaluated first; skip_if not evaluated when condition fails
# ---------------------------------------------------------------------------


def test_condition_evaluated_before_skip_if_when_condition_fails() -> None:
    """
    Step has both condition (→ False) and skip_if.
    Because condition fails, skip_if must NOT be evaluated.
    """
    step = _make_step(
        "step-b",
        outputs=["beta_out"],
        condition={"type": "artifact_exists", "artifact": "nonexistent"},
        skip_if={"type": "artifact_exists", "artifact": "also_nonexistent"},
    )
    spec = _make_spec(step)
    plan = _make_plan(step)

    result = execute_plan(spec, plan)
    trace = result.run_state.execution_trace

    step_events = [e for e in trace if e.node_name == "step-b"]
    event_types = [e.event_type for e in step_events]

    assert "condition_evaluated" in event_types
    assert "skip_if_evaluated" not in event_types
    assert result.run_state.node_results["step-b"].status == "SKIP"


def test_both_predicates_evaluated_when_condition_passes_but_skip_if_does_not() -> None:
    """
    Step A produces alpha_out.
    Step B: condition artifact_exists(alpha_out) → True; skip_if artifact_missing(alpha_out) → False.
    Both evaluated; step executes (PASS).
    """
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        condition={"type": "artifact_exists", "artifact": "alpha_out"},
        skip_if={"type": "artifact_missing", "artifact": "alpha_out"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    result = execute_plan(spec, plan)
    rs = result.run_state

    assert rs.node_results["step-b"].status == "PASS"
    assert "beta_out" in rs.artifacts

    step_b_events = [e for e in rs.execution_trace if e.node_name == "step-b"]
    event_types = [e.event_type for e in step_b_events]
    assert "condition_evaluated" in event_types
    assert "skip_if_evaluated" in event_types
    assert "step_completed" in event_types


# ---------------------------------------------------------------------------
# 8. Unit — malformed predicate fails closed with ExecutorError
# ---------------------------------------------------------------------------


def test_malformed_condition_raises_executor_error() -> None:
    """A condition dict missing 'type' is malformed → ExecutorError (fail closed)."""
    step = _make_step(
        "step-b",
        outputs=["beta_out"],
        condition={"artifact": "foo"},  # missing 'type'
    )
    spec = _make_spec(step)
    plan = _make_plan(step)

    with pytest.raises(ExecutorError, match="condition predicate evaluation failed"):
        execute_plan(spec, plan)


def test_malformed_skip_if_raises_executor_error() -> None:
    """A skip_if dict missing 'type' is malformed → ExecutorError (fail closed)."""
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        skip_if={"artifact": "foo"},  # missing 'type'
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    with pytest.raises(ExecutorError, match="skip_if predicate evaluation failed"):
        execute_plan(spec, plan)


# ---------------------------------------------------------------------------
# 9. Unit — unsupported predicate type fails closed with ExecutorError
# ---------------------------------------------------------------------------


def test_unsupported_condition_type_raises_executor_error() -> None:
    """An unsupported predicate type in condition → ExecutorError (fail closed)."""
    step = _make_step(
        "step-b",
        outputs=["beta_out"],
        condition={"type": "artifact_field_any_equals", "artifact": "foo"},
    )
    spec = _make_spec(step)
    plan = _make_plan(step)

    with pytest.raises(ExecutorError, match="condition predicate evaluation failed"):
        execute_plan(spec, plan)


def test_unsupported_skip_if_type_raises_executor_error() -> None:
    """An unsupported predicate type in skip_if → ExecutorError (fail closed)."""
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        skip_if={"type": "artifact_field_any_equals", "artifact": "foo"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    with pytest.raises(ExecutorError, match="skip_if predicate evaluation failed"):
        execute_plan(spec, plan)


# ---------------------------------------------------------------------------
# 10. Unit — BlockingEvent population
# ---------------------------------------------------------------------------


def test_blocking_events_populated_via_helper_directly() -> None:
    """
    _raise_blocking_events populates run_state.blocking_conditions with one
    BlockingEvent per raises entry.
    """
    from governance.dag_runner.executor import _raise_blocking_events
    from governance.dag_runner.models import GovernanceRunState

    run_state = GovernanceRunState(
        run_id="test",
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_phase="test",
    )
    step = WorkflowStep(
        name="test-step",
        component="skill:test",
        raises=["blocker_one", "blocker_two"],
    )
    _raise_blocking_events(step, run_state, "predicate evaluation failed")

    assert len(run_state.blocking_conditions) == 2
    ids = {e.blocking_id for e in run_state.blocking_conditions}
    assert ids == {"blocker_one", "blocker_two"}
    for ev in run_state.blocking_conditions:
        assert ev.raised_by == "test-step"
        assert ev.severity == "error"
        assert ev.resolved is False


def test_blocking_conditions_empty_for_normal_condition_skip() -> None:
    """Normal SKIP (condition not met) must NOT populate blocking_conditions."""
    step = _make_step(
        "step-b",
        outputs=["beta_out"],
        raises=["some_blocker"],
        condition={"type": "artifact_exists", "artifact": "nonexistent"},
    )
    spec = _make_spec(step)
    plan = _make_plan(step)

    result = execute_plan(spec, plan)
    assert result.run_state.node_results["step-b"].status == "SKIP"
    assert result.run_state.blocking_conditions == []


def test_blocking_conditions_empty_for_normal_skip_if_skip() -> None:
    """Normal SKIP (skip_if matched) must NOT populate blocking_conditions."""
    step_a = _make_step("step-a", outputs=["alpha_out"])
    step_b = _make_step(
        "step-b",
        outputs=["beta_out"],
        raises=["some_blocker"],
        skip_if={"type": "artifact_exists", "artifact": "alpha_out"},
    )
    spec = _make_spec(step_a, step_b)
    plan = _make_plan(step_a, step_b)

    result = execute_plan(spec, plan)
    assert result.run_state.node_results["step-b"].status == "SKIP"
    assert result.run_state.blocking_conditions == []
