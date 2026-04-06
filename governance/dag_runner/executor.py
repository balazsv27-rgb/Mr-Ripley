"""
executor.py — V1 governance DAG runner executor.

Execution policy
----------------
For each planned step the executor evaluates runtime predicates in this order:

1. ``condition`` (if present):
   - Evaluate using ``predicates.evaluate_condition()``.
   - If NOT matched → emit SKIP; do not execute the step.
   - If matched (or absent) → proceed to ``skip_if`` check.

2. ``skip_if`` (if present, evaluated only when condition passed or was absent):
   - Evaluate using ``predicates.evaluate_condition()``.
   - If matched → emit SKIP; do not execute the step.
   - If NOT matched (or absent) → execute the step normally.

3. Normal V1 shell execution:
   - Record a ``NodeResult`` with status ``PASS``.
   - Materialise all declared output artifacts.

Fail-closed predicate handling
-------------------------------
If a runtime predicate is unsupported, malformed, or structurally invalid,
``ExecutorError`` is raised (fail closed).  Before raising, a trace event is
recorded and a ``BlockingEvent`` is appended to ``run_state.blocking_conditions``
for each ``raises`` entry declared on the step.

Normal SKIP (condition not met, or skip_if matched) does not emit blocking events
— those represent intentional control flow, not runtime errors.

Skipped steps do not produce artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from governance.dag_runner.models import (
    ArtifactRecord,
    BlockingEvent,
    ExecutionTraceEvent,
    GovernanceRunState,
    NodeResult,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan


class ExecutorError(RuntimeError):
    """Raised when workflow execution fails."""


@dataclass(frozen=True)
class ExecutionResult:
    """Wrapper around the final runtime state."""

    run_state: GovernanceRunState


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_initial_run_state(
    workflow_name: str,
    orchestration_version: str | None = None,
    constitution_version: str | None = None,
) -> GovernanceRunState:
    return GovernanceRunState(
        run_id=str(uuid4()),
        started_at=_utc_now(),
        orchestration_version=orchestration_version,
        constitution_version=constitution_version,
        current_phase=workflow_name,
    )


def _append_trace(
    run_state: GovernanceRunState,
    *,
    node_name: str,
    event_type: str,
    detail: dict,
) -> None:
    run_state.execution_trace.append(
        ExecutionTraceEvent(
            timestamp=_utc_now(),
            node_name=node_name,
            event_type=event_type,
            detail=detail,
        )
    )


def _record_artifacts_for_step(
    run_state: GovernanceRunState,
    step_id: str,
    outputs: list[str],
) -> None:
    for artifact_name in outputs:
        run_state.artifacts[artifact_name] = ArtifactRecord(
            name=artifact_name,
            producer_step=step_id,
            status="present",
            payload={"produced_by": step_id},
        )


# ---------------------------------------------------------------------------
# Private predicate evaluation helpers
# ---------------------------------------------------------------------------


def _evaluate_step_condition(
    step: WorkflowStep,
    run_state: GovernanceRunState,
) -> tuple[bool, dict[str, Any]]:
    """
    Evaluate ``step.condition`` against the current run state.

    Returns ``(matched, eval_detail)`` where ``matched=True`` means the condition
    is satisfied and the step may execute.

    Raises ``ExecutorError`` on unsupported or malformed predicates (fail closed).
    ``ArtifactStructureError`` from ``artifacts.py`` is not caught here — it
    propagates as a system-level error.
    """
    from governance.dag_runner.predicates import (  # deferred to avoid import cycle
        PredicateEvaluationError,
        evaluate_condition,
    )
    try:
        result = evaluate_condition(step.condition, run_state)
    except PredicateEvaluationError as exc:
        raise ExecutorError(
            f"Step '{step.name}': condition predicate evaluation failed — {exc}"
        ) from exc

    return result.matched, {
        "kind": "condition",
        "predicate_type": result.predicate_type,
        "artifact": result.artifact,
        "field": result.field,
        "matched": result.matched,
        "detail": result.detail,
    }


def _evaluate_step_skip_if(
    step: WorkflowStep,
    run_state: GovernanceRunState,
) -> tuple[bool, dict[str, Any]]:
    """
    Evaluate ``step.skip_if`` against the current run state.

    Returns ``(should_skip, eval_detail)`` where ``should_skip=True`` means the
    skip_if condition is satisfied and the step should be skipped.

    Raises ``ExecutorError`` on unsupported or malformed predicates (fail closed).
    """
    from governance.dag_runner.predicates import (
        PredicateEvaluationError,
        evaluate_condition,
    )
    try:
        result = evaluate_condition(step.skip_if, run_state)
    except PredicateEvaluationError as exc:
        raise ExecutorError(
            f"Step '{step.name}': skip_if predicate evaluation failed — {exc}"
        ) from exc

    return result.matched, {
        "kind": "skip_if",
        "predicate_type": result.predicate_type,
        "artifact": result.artifact,
        "field": result.field,
        "matched": result.matched,
        "detail": result.detail,
    }


def _record_predicate_trace(
    run_state: GovernanceRunState,
    step_id: str,
    eval_detail: dict[str, Any],
) -> None:
    """Record a predicate evaluation result into the execution trace."""
    kind = eval_detail.get("kind", "predicate")
    _append_trace(
        run_state,
        node_name=step_id,
        event_type=f"{kind}_evaluated",
        detail={k: v for k, v in eval_detail.items() if k != "kind"},
    )


def _build_skipped_node_result(
    step: WorkflowStep,
    reason: str,
    evidence: list[str],
) -> NodeResult:
    """Build a ``NodeResult`` with status ``SKIP`` for a step that was not executed."""
    return NodeResult(
        node_name=step.name,
        node_type=step.component,
        status="SKIP",
        summary=reason,
        evidence=evidence,
        produced_artifacts=[],
        triggered_blocks=[],
        inference_used=False,
    )


def _raise_blocking_events(
    step: WorkflowStep,
    run_state: GovernanceRunState,
    reason: str,
) -> None:
    """
    Append a ``BlockingEvent`` for each ``raises`` entry declared on the step.

    Called only when the executor encounters a runtime predicate error (fail closed).
    Normal SKIP (intentional control flow) does not emit blocking events.
    """
    for blocker_id in step.raises:
        run_state.blocking_conditions.append(
            BlockingEvent(
                blocking_id=blocker_id,
                raised_by=step.name,
                severity="error",
                message=reason,
                resolved=False,
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_plan(
    spec,
    plan: ExecutionPlan,
    *,
    verdict_status: str | None = None,
) -> ExecutionResult:
    """
    Execute a validated and planned workflow.

    V1 behavior:
    - Evaluates ``condition`` and ``skip_if`` predicates for each step.
    - Records ``SKIP`` for steps whose predicate prevents execution.
    - Does not execute real skill logic (shell mode).
    - Records execution trace events including predicate evaluations.
    - Materialises declared output artifacts for each executed (non-skipped) step.
    - Populates ``run_state.blocking_conditions`` on predicate evaluation errors.
    - Stores the final verdict string when provided.
    """
    if not plan.ordered_steps:
        raise ExecutorError("Cannot execute empty execution plan.")

    run_state = _build_initial_run_state(
        workflow_name=plan.workflow_name,
        orchestration_version=spec.manifest.workflow_version,
        constitution_version=None,
    )

    _append_trace(
        run_state,
        node_name="__run__",
        event_type="run_started",
        detail={
            "workflow_name": plan.workflow_name,
            "planned_steps": len(plan.ordered_steps),
        },
    )

    for node in plan.ordered_steps:
        step = spec.workflow_steps.get(node.step_id)
        if step is None:
            raise ExecutorError(
                f"Planned step '{node.step_id}' not found in assembled workflow steps."
            )

        _append_trace(
            run_state,
            node_name=node.step_id,
            event_type="step_started",
            detail={
                "component": node.component,
                "depends_on": list(node.depends_on),
            },
        )

        # -----------------------------------------------------------------
        # Predicate evaluation — V1 policy:
        #   1. Evaluate condition first (if present).
        #      Not matched → SKIP; skip_if is not evaluated.
        #   2. Evaluate skip_if (if present, only when condition passed/absent).
        #      Matched → SKIP.
        #   3. Both absent or both passed → execute normally in shell mode.
        # -----------------------------------------------------------------
        should_skip = False
        skip_reason = ""
        skip_evidence: list[str] = []

        if step.condition is not None:
            try:
                condition_matched, eval_detail = _evaluate_step_condition(step, run_state)
            except ExecutorError as exc:
                _append_trace(
                    run_state,
                    node_name=node.step_id,
                    event_type="condition_evaluation_error",
                    detail={"error": str(exc)},
                )
                _raise_blocking_events(step, run_state, str(exc))
                raise

            _record_predicate_trace(run_state, node.step_id, eval_detail)

            if not condition_matched:
                should_skip = True
                skip_reason = (
                    f"Condition not satisfied: "
                    f"{eval_detail.get('detail', 'condition did not match')}"
                )
                skip_evidence = [
                    f"condition_type={eval_detail.get('predicate_type')}",
                    f"condition_artifact={eval_detail.get('artifact')}",
                    f"condition_detail={eval_detail.get('detail')}",
                ]

        if not should_skip and step.skip_if is not None:
            try:
                skip_if_matched, eval_detail = _evaluate_step_skip_if(step, run_state)
            except ExecutorError as exc:
                _append_trace(
                    run_state,
                    node_name=node.step_id,
                    event_type="skip_if_evaluation_error",
                    detail={"error": str(exc)},
                )
                _raise_blocking_events(step, run_state, str(exc))
                raise

            _record_predicate_trace(run_state, node.step_id, eval_detail)

            if skip_if_matched:
                should_skip = True
                skip_reason = (
                    f"skip_if matched: "
                    f"{eval_detail.get('detail', 'skip_if condition matched')}"
                )
                skip_evidence = [
                    f"skip_if_type={eval_detail.get('predicate_type')}",
                    f"skip_if_artifact={eval_detail.get('artifact')}",
                    f"skip_if_detail={eval_detail.get('detail')}",
                ]

        if should_skip:
            node_result = _build_skipped_node_result(step, skip_reason, skip_evidence)
            run_state.node_results[node.step_id] = node_result
            _append_trace(
                run_state,
                node_name=node.step_id,
                event_type="step_skipped",
                detail={"reason": skip_reason},
            )
            continue

        # Normal V1 shell execution — step ran; materialise artifacts and record result.
        _record_artifacts_for_step(run_state, node.step_id, list(step.outputs))

        node_result = NodeResult(
            node_name=node.step_id,
            node_type=node.component,
            status="PASS",
            summary="Step recorded successfully in V1 shell execution.",
            evidence=[f"component={node.component}"],
            produced_artifacts=list(step.outputs),
            triggered_blocks=list(step.raises),
            inference_used=False,
        )
        run_state.node_results[node.step_id] = node_result

        _append_trace(
            run_state,
            node_name=node.step_id,
            event_type="step_completed",
            detail={
                "component": node.component,
                "produced_artifacts": list(step.outputs),
                "triggered_blocks": list(step.raises),
            },
        )

    run_state.final_verdict = verdict_status

    _append_trace(
        run_state,
        node_name="__run__",
        event_type="run_completed",
        detail={
            "final_verdict": verdict_status,
            "recorded_steps": len(run_state.node_results),
            "recorded_artifacts": len(run_state.artifacts),
        },
    )

    return ExecutionResult(run_state=run_state)
