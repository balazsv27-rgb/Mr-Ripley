from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


NodeStatus = Literal["PASS", "WARN", "FAIL", "SKIP"]
ArtifactStatus = Literal["present", "missing", "blocked", "stale"]
FinalVerdict = Literal["ready", "review_only", "blocked", "invalid"]


@dataclass(frozen=True)
class ManifestSpec:
    """Root workflow manifest metadata."""

    workflow_name: str
    workflow_version: str | None = None
    assembly_mode: str | None = None
    package_dir: str | None = None
    package_files: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowPackageSpec:
    """Single loaded workflow package file."""

    package_name: str
    file_path: str
    content: dict[str, Any]


@dataclass(frozen=True)
class PredicateSpec:
    """Declared predicate from predicates.yaml."""

    name: str
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSpec:
    """Declared skill from skills.yaml."""

    name: str
    description: str | None = None
    produces: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubagentSpec:
    """Declared subagent from subagents.yaml."""

    name: str
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactSpec:
    """Declared artifact from artifacts.yaml."""

    name: str
    producer_step: str | None = None
    required: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BlockingCondition:
    """Declared blocking condition from blocking-conditions.yaml."""

    id: str
    severity: str | None = None
    halts_workflow: bool = False
    resolvable: bool = False
    raised_by: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StageGateSpec:
    """Declared stage gate from stage-gates.yaml."""

    name: str
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InterpretationPolicy:
    """Interpretation/routing policy loaded from interpretation-policy.yaml."""

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationLedgerSpec:
    """Verification ledger rules/specification."""

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionMetadataSpec:
    """Execution/runtime metadata from execution-metadata.yaml."""

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowStep:
    """Compiled workflow step from workflow-steps.yaml."""

    name: str
    component: str
    depends_on: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    validates: list[str] = field(default_factory=list)
    raises: list[str] = field(default_factory=list)
    condition: dict[str, Any] | None = None
    skip_if: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssembledWorkflowSpec:
    """Fully assembled workflow spec after package merge."""

    manifest: ManifestSpec
    constitution: dict[str, Any] = field(default_factory=dict)
    predicates: dict[str, PredicateSpec] = field(default_factory=dict)
    skills: dict[str, SkillSpec] = field(default_factory=dict)
    subagents: dict[str, SubagentSpec] = field(default_factory=dict)
    artifacts: dict[str, ArtifactSpec] = field(default_factory=dict)
    blocking_conditions: dict[str, BlockingCondition] = field(default_factory=dict)
    stage_gates: dict[str, StageGateSpec] = field(default_factory=dict)
    workflow_steps: dict[str, WorkflowStep] = field(default_factory=dict)
    interpretation_policy: InterpretationPolicy = field(
        default_factory=InterpretationPolicy
    )
    verification_ledger: VerificationLedgerSpec = field(
        default_factory=VerificationLedgerSpec
    )
    execution_metadata: ExecutionMetadataSpec = field(
        default_factory=ExecutionMetadataSpec
    )
    hooks: dict[str, Any] = field(default_factory=dict)
    raw_sections: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactRecord:
    """Runtime artifact state."""

    name: str
    producer_step: str
    status: ArtifactStatus
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BlockingEvent:
    """Runtime blocking event raised during execution."""

    blocking_id: str
    raised_by: str
    severity: str | None = None
    message: str | None = None
    resolved: bool = False


@dataclass(frozen=True)
class ExecutionTraceEvent:
    """Single execution trace entry."""

    timestamp: datetime
    node_name: str
    event_type: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeResult:
    """Result of one executed or skipped node."""

    node_name: str
    node_type: str
    status: NodeStatus
    summary: str
    evidence: list[str] = field(default_factory=list)
    produced_artifacts: list[str] = field(default_factory=list)
    triggered_blocks: list[str] = field(default_factory=list)
    inference_used: bool = False


@dataclass
class GovernanceRunState:
    """Mutable runtime state for one governance DAG run."""

    run_id: str
    started_at: datetime
    constitution_version: str | None = None
    orchestration_version: str | None = None
    current_phase: str | None = None
    active_claims: list[dict[str, Any]] = field(default_factory=list)
    node_results: dict[str, NodeResult] = field(default_factory=dict)
    artifacts: dict[str, ArtifactRecord] = field(default_factory=dict)
    blocking_conditions: list[BlockingEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    execution_trace: list[ExecutionTraceEvent] = field(default_factory=list)
    final_verdict: FinalVerdict | None = None