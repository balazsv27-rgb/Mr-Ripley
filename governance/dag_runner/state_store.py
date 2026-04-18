from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from governance.dag_runner.artifacts import build_artifact_summary
from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.blockers import analyze_blockers, analyze_runtime_blockers
from governance.dag_runner.models import (
    ArtifactRecord,
    BlockingEvent,
    ExecutionTraceEvent,
    GovernanceRunState,
    NodeResult,
)
from governance.dag_runner.executor import ExecutionResult, execute_plan
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.validator import validate_workflow_spec
from governance.dag_runner.verdict import (
    compute_runtime_verdict,
    compute_verdict,
    is_workflow_complete,
)


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

    # Compact top-level readiness fields (Phase 3 hook-facing contract)
    workflow_completed: bool = False
    required_outputs_present: bool = False
    unresolved_blocking_conditions: list[dict[str, Any]] = field(default_factory=list)
    fatal_unresolved_block_count: int = 0
    pr_readiness: str = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _serialize_blocking_event(event) -> dict[str, Any]:
    """Serialize a BlockingEvent to a compact hook-readable dict."""
    return {
        "blocking_id": event.blocking_id,
        "raised_by": event.raised_by,
        "severity": event.severity,
        "resolved": event.resolved,
        "message": event.message,
    }


def _compute_pr_readiness(runtime_verdict_status: str) -> str:
    """Map runtime verdict status to compact PR readiness string."""
    mapping = {"ready": "ready", "review_only": "review_only", "blocked": "blocked"}
    return mapping.get(runtime_verdict_status, "blocked")


def _build_top_level_readiness_fields(
    run_state,
    artifact_summary: dict[str, Any],
    runtime_blocker_summary,
    runtime_verdict,
) -> dict[str, Any]:
    """Compute compact top-level readiness fields from runtime analysis outputs."""
    unresolved = [
        _serialize_blocking_event(event)
        for event in run_state.blocking_conditions
        if not event.resolved
    ]
    return {
        "workflow_completed": is_workflow_complete(run_state),
        "required_outputs_present": bool(artifact_summary.get("required_outputs_present", False)),
        "unresolved_blocking_conditions": unresolved,
        "fatal_unresolved_block_count": runtime_blocker_summary.total_fatal_unresolved,
        "pr_readiness": _compute_pr_readiness(runtime_verdict.status),
    }


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

    # Compact readiness field defaults (used when no execution result is available)
    readiness_workflow_completed = False
    readiness_required_outputs_present = False
    readiness_unresolved_blocking_conditions: list[dict[str, Any]] = []
    readiness_fatal_unresolved_block_count = 0
    readiness_pr_readiness = "blocked"

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

        # Derive compact top-level readiness fields from existing runtime modules
        artifact_summary = build_artifact_summary(spec, run_state)
        runtime_blocker_summary = analyze_runtime_blockers(run_state, spec)
        runtime_verdict = compute_runtime_verdict(
            validation_result, blocker_summary, run_state, artifact_summary, spec
        )
        readiness = _build_top_level_readiness_fields(
            run_state, artifact_summary, runtime_blocker_summary, runtime_verdict
        )
        readiness_workflow_completed = readiness["workflow_completed"]
        readiness_required_outputs_present = readiness["required_outputs_present"]
        readiness_unresolved_blocking_conditions = readiness["unresolved_blocking_conditions"]
        readiness_fatal_unresolved_block_count = readiness["fatal_unresolved_block_count"]
        readiness_pr_readiness = readiness["pr_readiness"]

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

        workflow_completed=readiness_workflow_completed,
        required_outputs_present=readiness_required_outputs_present,
        unresolved_blocking_conditions=readiness_unresolved_blocking_conditions,
        fatal_unresolved_block_count=readiness_fatal_unresolved_block_count,
        pr_readiness=readiness_pr_readiness,
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


def load_run_state_from_path(path: Path) -> GovernanceRunState:
    """Load persisted run state JSON and reconstruct a ``GovernanceRunState``.

    This is the reverse of ``build_stored_run_state`` followed by
    ``write_run_state``.  Fields not preserved in the stored format
    (``latency_ms``, ``token_count``) default to zero.  Fields not
    stored at all (``orchestration_version``, ``constitution_version``)
    default to ``None``.

    Raises ``StateStoreError`` on any structural or parsing issue (fail closed).
    """
    raw = load_run_state(path)  # validates file, JSON, dict

    try:
        # --- metadata ---
        run_id = raw.get("run_id", "")
        started_at_str = raw.get("started_at", "")
        started_at = (
            datetime.fromisoformat(started_at_str)
            if started_at_str
            else datetime.now(timezone.utc)
        )
        current_phase = raw.get("workflow_name")
        final_verdict = raw.get("final_verdict")

        # --- node_results: list[dict] -> dict[str, NodeResult] ---
        node_results: dict[str, NodeResult] = {}
        for nr_dict in raw.get("node_results", []):
            nr = NodeResult(
                node_name=nr_dict["node_name"],
                node_type=nr_dict["node_type"],
                status=nr_dict["status"],
                summary=nr_dict["summary"],
                evidence=list(nr_dict.get("evidence", [])),
                produced_artifacts=list(nr_dict.get("produced_artifacts", [])),
                triggered_blocks=list(nr_dict.get("triggered_blocks", [])),
                inference_used=bool(nr_dict.get("inference_used", False)),
                latency_ms=float(nr_dict.get("latency_ms", 0.0)),
                token_count=int(nr_dict.get("token_count", 0)),
            )
            node_results[nr.node_name] = nr

        # --- artifacts: list[dict] -> dict[str, ArtifactRecord] ---
        artifacts: dict[str, ArtifactRecord] = {}
        for ar_dict in raw.get("artifact_records", []):
            ar = ArtifactRecord(
                name=ar_dict["name"],
                producer_step=ar_dict["producer_step"],
                status=ar_dict["status"],
                payload=dict(ar_dict.get("payload", {})),
            )
            artifacts[ar.name] = ar

        # --- blocking_conditions: list[dict] -> list[BlockingEvent] ---
        blocking_conditions: list[BlockingEvent] = []
        for bc_dict in raw.get("unresolved_blocking_conditions", []):
            blocking_conditions.append(
                BlockingEvent(
                    blocking_id=bc_dict["blocking_id"],
                    raised_by=bc_dict["raised_by"],
                    severity=bc_dict.get("severity"),
                    message=bc_dict.get("message"),
                    resolved=bool(bc_dict.get("resolved", False)),
                )
            )

        # --- execution_trace: list[dict] -> list[ExecutionTraceEvent] ---
        execution_trace: list[ExecutionTraceEvent] = []
        for et_dict in raw.get("execution_trace", []):
            ts_str = et_dict.get("timestamp", "")
            ts = (
                datetime.fromisoformat(ts_str)
                if ts_str
                else datetime.now(timezone.utc)
            )
            execution_trace.append(
                ExecutionTraceEvent(
                    timestamp=ts,
                    node_name=et_dict["node_name"],
                    event_type=et_dict["event_type"],
                    detail=dict(et_dict.get("detail", {})),
                )
            )

        return GovernanceRunState(
            run_id=run_id,
            started_at=started_at,
            constitution_version=None,
            orchestration_version=None,
            current_phase=current_phase,
            node_results=node_results,
            artifacts=artifacts,
            blocking_conditions=blocking_conditions,
            execution_trace=execution_trace,
            final_verdict=final_verdict,
        )

    except (KeyError, TypeError, ValueError) as exc:
        raise StateStoreError(
            f"Failed to reconstruct GovernanceRunState from {path}: {exc}"
        ) from exc


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