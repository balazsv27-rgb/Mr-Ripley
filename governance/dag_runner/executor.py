from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from governance.dag_runner.models import (
    ArtifactRecord,
    ExecutionTraceEvent,
    GovernanceRunState,
    NodeResult,
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


def _record_artifacts_for_step(run_state: GovernanceRunState, step_id: str, outputs: list[str]) -> None:
    for artifact_name in outputs:
        run_state.artifacts[artifact_name] = ArtifactRecord(
            name=artifact_name,
            producer_step=step_id,
            status="present",
            payload={"produced_by": step_id},
        )


def execute_plan(
    spec,
    plan: ExecutionPlan,
    *,
    verdict_status: str | None = None,
) -> ExecutionResult:
    """
    Execute a validated and planned workflow in V1 shell mode.

    V1 behavior:
    - does not execute real skill logic
    - records execution trace
    - records simple NodeResult objects
    - materializes declared output artifacts for each step
    - stores a final verdict string if provided
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