"""
execution_modes.py — CLI flag mapping and continuation validation.

Maps CLI arguments to ``ExecutionConfig`` and validates continuation
preconditions (fail-closed).
"""
from __future__ import annotations

from governance.dag_runner.models import (
    ExecutionConfig,
    GovernanceRunState,
    AssembledWorkflowSpec,
)
from governance.dag_runner.planner import ExecutionPlan


class ContinuationError(RuntimeError):
    """Raised when continuation guardrails are violated."""


def build_config_from_args(
    *,
    mode: str = "shell_v1",
    dry_run: bool = False,
    json_output: bool = False,
    graph: bool = False,
    continue_from: str | None = None,
    timeout: int | None = None,
    phase: str | None = None,
    state_path: str | None = None,
) -> ExecutionConfig:
    """Map CLI flags to an ``ExecutionConfig``."""
    if graph:
        resolved_mode = "graph_only"
    elif dry_run:
        resolved_mode = "dry_run"
    elif mode == "agent_execution":
        resolved_mode = "agent_execution"
    else:
        resolved_mode = "shell_v1"

    return ExecutionConfig(
        mode=resolved_mode,
        json_output=json_output,
        timeout_total_ms=timeout or 1_800_000,
        continue_from=continue_from,
        phase_scope=phase,
        state_bootstrap_path=state_path if continue_from else None,
    )


def validate_continuation(
    prior_state: GovernanceRunState,
    spec: AssembledWorkflowSpec,
    plan: ExecutionPlan,
    continue_from: str,
) -> list[str]:
    """Validate that continuation is safe.  Returns failure reasons (empty = valid).

    Checks (all must pass — fail closed):
    1. Workflow name matches
    2. Orchestration version matches
    3. Prior state is structurally valid (has node_results, artifacts)
    4. No fatal unresolved blockers before continuation point
    5. Prerequisite artifacts for resumed steps exist
    """
    failures: list[str] = []

    # 1. Workflow name match
    if prior_state.current_phase != plan.workflow_name:
        failures.append(
            f"Workflow name mismatch: prior='{prior_state.current_phase}', "
            f"current='{plan.workflow_name}'"
        )

    # 2. Orchestration version match
    if (
        prior_state.orchestration_version is not None
        and spec.manifest.workflow_version is not None
        and prior_state.orchestration_version != spec.manifest.workflow_version
    ):
        failures.append(
            f"Orchestration version mismatch: prior='{prior_state.orchestration_version}', "
            f"current='{spec.manifest.workflow_version}'"
        )

    # 3. Structural validity
    if not isinstance(prior_state.node_results, dict):
        failures.append("Prior state has invalid node_results structure.")
    if not isinstance(prior_state.artifacts, dict):
        failures.append("Prior state has invalid artifacts structure.")

    # 4. Verify continue_from is a valid step
    ordered_ids = [n.step_id for n in plan.ordered_steps]
    if continue_from not in ordered_ids:
        failures.append(
            f"Continuation step '{continue_from}' not found in execution plan."
        )
        return failures  # can't check prerequisites if step unknown

    continuation_index = ordered_ids.index(continue_from)

    # Check no fatal unresolved blockers before continuation point
    steps_before = set(ordered_ids[:continuation_index])
    for event in prior_state.blocking_conditions:
        if not event.resolved and event.raised_by in steps_before:
            blocker_def = spec.blocking_conditions.get(event.blocking_id)
            if blocker_def and blocker_def.halts_workflow:
                failures.append(
                    f"Fatal unresolved blocker '{event.blocking_id}' "
                    f"raised by '{event.raised_by}' before continuation point."
                )

    # 5. Prerequisite artifacts for resumed steps
    for i in range(continuation_index, len(ordered_ids)):
        step_id = ordered_ids[i]
        step = spec.workflow_steps.get(step_id)
        if step is None:
            continue

        # Check inputs declared in step.raw
        inputs = step.raw.get("inputs", []) or []
        for input_name in inputs:
            if not isinstance(input_name, str):
                continue
            # Only check artifacts that should have been produced by prior steps
            if input_name in spec.artifacts:
                producer_step = spec.artifacts[input_name].producer_step
                if producer_step and producer_step in steps_before:
                    artifact = prior_state.artifacts.get(input_name)
                    if artifact is None or artifact.status != "present":
                        failures.append(
                            f"Prerequisite artifact '{input_name}' for step "
                            f"'{step_id}' is missing or not present in prior state."
                        )

    return failures
