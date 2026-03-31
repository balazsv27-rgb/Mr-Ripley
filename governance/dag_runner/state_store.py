from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.blockers import analyze_blockers
from governance.dag_runner.executor import ExecutionResult, execute_plan
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.validator import validate_workflow_spec
from governance.dag_runner.verdict import compute_verdict


DEFAULT_STATE_PATH = Path("governance_run_state.json")


class StateStoreError(RuntimeError):
    """Raised when state serialization or persistence fails."""


@dataclass(frozen=True)
class StoredPlanNode:
    step_id: str
    component: str
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StoredExecutionTraceEvent:
    timestamp: str
    node_name: str
    event_type: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredNodeResult:
    node_name: str
    node_type: str
    status: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    produced_artifacts: list[str] = field(default_factory=list)
    triggered_blocks: list[str] = field(default_factory=list)
    inference_used: bool = False


@dataclass(frozen=True)
class StoredArtifactRecord:
    name: str
    producer_step: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredRunState:
    workflow_name: str
    workflow_file: str
    loaded_packages: int
    workflow_steps: int
    skills: int
    artifacts: int
    blocking_conditions: int
    stage_gates: int
    subagents: int

    validation_passed: bool
    validation_issue_count: int
    validation_issues: list[dict[str, Any]] = field(default_factory=list)

    blocker_declared_count: int = 0
    blocker_referenced_count: int = 0
    blocker_orphan_count: int = 0
    blocker_unknown_reference_count: int = 0
    blocker_structurally_consistent: bool = False

    verdict_status: str = "invalid"
    verdict_reasons: list[str] = field(default_factory=list)

    planned_steps: int = 0
    execution_order: list[StoredPlanNode] = field(default_factory=list)

    run_id: str = ""
    started_at: str = ""
    final_verdict: str | None = None
    recorded_node_results: int = 0
    recorded_artifacts: int = 0
    recorded_trace_events: int = 0

    node_results: list[StoredNodeResult] = field(default_factory=list)
    artifact_records: list[StoredArtifactRecord] = field(default_factory=list)
    execution_trace: list[StoredExecutionTraceEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_stored_run_state(
    loaded,
    spec,
    validation_result,
    plan,
    blocker_summary,
    verdict,
    execution_result: ExecutionResult | None = None,
) -> StoredRunState:
    run_id = ""
    started_at = ""
    final_verdict = verdict.status
    recorded_node_results = 0
    recorded_artifacts = 0
    recorded_trace_events = 0
    node_results: list[StoredNodeResult] = []
    artifact_records: list[StoredArtifactRecord] = []
    execution_trace: list[StoredExecutionTraceEvent] = []

    if execution_result is not None:
        run_state = execution_result.run_state
        run_id = run_state.run_id
        started_at = run_state.started_at.isoformat()
        final_verdict = run_state.final_verdict
        recorded_node_results = len(run_state.node_results)
        recorded_artifacts = len(run_state.artifacts)
        recorded_trace_events = len(run_state.execution_trace)

        node_results = [
            StoredNodeResult(
                node_name=result.node_name,
                node_type=result.node_type,
                status=result.status,
                summary=result.summary,
                evidence=list(result.evidence),
                produced_artifacts=list(result.produced_artifacts),
                triggered_blocks=list(result.triggered_blocks),
                inference_used=result.inference_used,
            )
            for result in run_state.node_results.values()
        ]

        artifact_records = [
            StoredArtifactRecord(
                name=artifact.name,
                producer_step=artifact.producer_step,
                status=artifact.status,
                payload=dict(artifact.payload),
            )
            for artifact in run_state.artifacts.values()
        ]

        execution_trace = [
            StoredExecutionTraceEvent(
                timestamp=event.timestamp.isoformat(),
                node_name=event.node_name,
                event_type=event.event_type,
                detail=dict(event.detail),
            )
            for event in run_state.execution_trace
        ]

    return StoredRunState(
        workflow_name=spec.manifest.workflow_name,
        workflow_file=str(loaded.workflow_path),
        loaded_packages=len(loaded.packages),
        workflow_steps=len(spec.workflow_steps),
        skills=len(spec.skills),
        artifacts=len(spec.artifacts),
        blocking_conditions=len(spec.blocking_conditions),
        stage_gates=len(spec.stage_gates),
        subagents=len(spec.subagents),

        validation_passed=validation_result.is_valid,
        validation_issue_count=len(validation_result.issues),
        validation_issues=[
            {
                "code": issue.code,
                "message": issue.message,
                "step_id": issue.step_id,
                "detail": issue.detail,
            }
            for issue in validation_result.issues
        ],

        blocker_declared_count=len(blocker_summary.declared_blockers),
        blocker_referenced_count=len(blocker_summary.referenced_blockers),
        blocker_orphan_count=len(blocker_summary.orphan_blockers),
        blocker_unknown_reference_count=len(blocker_summary.unknown_references),
        blocker_structurally_consistent=blocker_summary.is_structurally_consistent,

        verdict_status=verdict.status,
        verdict_reasons=list(verdict.reasons),

        planned_steps=len(plan.ordered_steps),
        execution_order=[
            StoredPlanNode(
                step_id=node.step_id,
                component=node.component,
                depends_on=list(node.depends_on),
            )
            for node in plan.ordered_steps
        ],

        run_id=run_id,
        started_at=started_at,
        final_verdict=final_verdict,
        recorded_node_results=recorded_node_results,
        recorded_artifacts=recorded_artifacts,
        recorded_trace_events=recorded_trace_events,
        node_results=node_results,
        artifact_records=artifact_records,
        execution_trace=execution_trace,
    )


def write_run_state(
    state: StoredRunState,
    output_path: str | Path = DEFAULT_STATE_PATH,
) -> Path:
    output_path = Path(output_path)

    try:
        output_path.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        raise StateStoreError(
            f"Failed to write run state to {output_path}: {exc}"
        ) from exc

    return output_path.resolve()


def load_run_state(output_path: str | Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    output_path = Path(output_path)

    if not output_path.exists():
        raise StateStoreError(f"Run state file does not exist: {output_path}")

    if not output_path.is_file():
        raise StateStoreError(f"Run state path is not a file: {output_path}")

    try:
        raw = output_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateStoreError(
            f"Failed to read run state file {output_path}: {exc}"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateStoreError(
            f"Invalid JSON in run state file {output_path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise StateStoreError(
            f"Run state JSON must be an object/dict, got {type(payload).__name__}"
        )

    return payload


def generate_and_write_run_state(
    workflow_path: str | Path,
    output_path: str | Path = DEFAULT_STATE_PATH,
) -> Path:
    loaded = load_workflow_packages(workflow_path)
    spec = assemble_workflow_spec(loaded)
    validation_result = validate_workflow_spec(spec)
    plan = build_execution_plan(spec)
    blocker_summary = analyze_blockers(spec, plan)
    verdict = compute_verdict(validation_result, blocker_summary)
    execution_result = execute_plan(spec, plan, verdict_status=verdict.status)

    state = build_stored_run_state(
        loaded=loaded,
        spec=spec,
        validation_result=validation_result,
        plan=plan,
        blocker_summary=blocker_summary,
        verdict=verdict,
        execution_result=execution_result,
    )

    return write_run_state(state, output_path=output_path)