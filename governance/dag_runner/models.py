from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


NodeStatus = Literal["PASS", "WARN", "FAIL", "SKIP"]
ArtifactStatus = Literal["present", "missing", "blocked", "stale"]
FinalVerdict = Literal["ready", "review_only", "blocked", "invalid"]

# Component kinds — the execution dispatch discriminator.
# Must cover all bare component names and prefixed component patterns
# accepted by the validator.
ComponentKind = Literal[
    "constitution", "stage_gates", "hooks", "subagents",
    "skill", "stage_gate", "hook", "subagent",
    "final_gate", "blocking_evaluator", "verification_update",
    "artifact_gate", "predicate_gate", "workflow_step",
]

ExecutionMode = Literal["shell_v1", "dry_run", "agent_execution", "graph_only"]
 

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
class AgentSpec:
    """Declared agent from agents.yaml."""

    name: str
    role: str | None = None
    layer: str | None = None
    model: str = "sonnet"
    tools: list[str] = field(default_factory=list)
    workflow_steps: list[str] = field(default_factory=list)
    skill_bindings: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    hook_reinforcement: str | None = None
    escalation_targets: list[dict[str, Any]] = field(default_factory=list)
    failure_mode: str | None = None
    activation_predicate: str | None = None
    timeout_ms: int | None = None
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
class ExecutionConfig:
    """Configuration for DAG runner execution mode and behaviour."""

    mode: ExecutionMode = "shell_v1"
    json_output: bool = False
    timeout_per_step_ms: int = 120_000
    timeout_total_ms: int = 1_800_000
    continue_from: str | None = None
    phase_scope: str | None = None
    state_bootstrap_path: str | None = None
    # Bootstrap input for governance evaluation
    request_text: str | None = None
    request_id: str | None = None
    request_source: str | None = None


@dataclass(frozen=True)
class PromptContext:
    """Assembled and bounded prompt context for a single step.

    Built by prompt_assembly.py, consumed by ExecutionBackend.execute_step().
    MockExecutionBackend ignores this; live backends (ClaudeCodeCLIBackend)
    use assembled_prompt as the text sent to the subprocess.
    """

    assembled_prompt: str
    agent: AgentSpec | None = None
    skill_content: str = ""
    agent_instructions: str = ""
    artifact_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_paths: list[str] = field(default_factory=list)
    token_budget: int = 100_000
    token_estimate: int = 0
    truncated: bool = False
    truncation_events: list[dict[str, str | int]] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactEnvelope:
    """Canonical artifact envelope — the ONE write format for V2.

    Must match .claude/hooks/lib/artifact_store.py exactly.
    """

    artifact: str
    produced_by: str
    session: str
    timestamp: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureClassification:
    """Categorised failure raised during execution."""

    origin: Literal["structural", "contract", "runtime", "artifact", "timeout"]
    step_id: str
    detail: str
    recoverable: bool = False


@dataclass(frozen=True)
class AgentExecutionResult:
    """Result returned by an ExecutionBackend for one step."""

    success: bool
    artifacts_produced: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw_output: str = ""
    failure: FailureClassification | None = None
    latency_ms: float = 0.0
    token_count: int = 0
    stderr: str = ""
    parse_failure: str | None = None
    returncode: int | None = None
    retry_count: int = 0


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
    agents: dict[str, AgentSpec] = field(default_factory=dict)
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
    latency_ms: float = 0.0
    token_count: int = 0
    failure_detail: dict[str, Any] = field(default_factory=dict)


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
    session_dir: str | None = None