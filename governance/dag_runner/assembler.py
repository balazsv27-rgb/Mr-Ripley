from __future__ import annotations

from typing import Any

from governance.dag_runner.loader import LoadedWorkflowPackages
from governance.dag_runner.models import (
    AgentSpec,
    ArtifactSpec,
    AssembledWorkflowSpec,
    BlockingCondition,
    ExecutionMetadataSpec,
    InterpretationPolicy,
    PredicateSpec,
    SkillSpec,
    StageGateSpec,
    SubagentSpec,
    VerificationLedgerSpec,
    WorkflowStep,
)


class AssemblerError(RuntimeError):
    """Raised when package assembly fails."""
 

def _package_map(loaded: LoadedWorkflowPackages) -> dict[str, dict[str, Any]]:
    """
    Convert loaded packages into a lookup map.

    Supports both:
    - full declared package path keys, e.g. 'packages/predicates.yaml'
    - basename keys, e.g. 'predicates.yaml'
    """
    result: dict[str, dict[str, Any]] = {}

    for pkg in loaded.packages:
        result[pkg.package_name] = pkg.content
        basename = pkg.package_name.split("/")[-1].split("\\")[-1]
        result[basename] = pkg.content

    return result


def _get_data_section(payload: dict[str, Any], filename: str) -> Any:
    if not isinstance(payload, dict):
        raise AssemblerError(
            f"{filename}: expected package payload to be a dict, got {type(payload).__name__}"
        )

    if "data" not in payload:
        raise AssemblerError(f"{filename}: missing required top-level 'data' section.")

    return payload["data"]


def _coerce_named_mapping(
    items: list[dict[str, Any]],
    *,
    required_name_key: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for item in items:
        if not isinstance(item, dict):
            raise AssemblerError(
                f"Expected list item to be a mapping/dict, got {type(item).__name__}: {item!r}"
            )

        name = item.get(required_name_key)
        if not isinstance(name, str) or not name.strip():
            raise AssemblerError(
                f"Missing or invalid '{required_name_key}' in item: {item!r}"
            )

        key = name.strip()
        if key in result:
            raise AssemblerError(f"Duplicate entry '{key}' found during assembly.")

        result[key] = item

    return result


def _assemble_predicates(payload: dict[str, Any]) -> dict[str, PredicateSpec]:
    data = _get_data_section(payload, "predicates.yaml")
    if not isinstance(data, dict):
        raise AssemblerError("predicates.yaml: 'data' must be a mapping/dict.")

    result: dict[str, PredicateSpec] = {}
    for name, item in data.items():
        if not isinstance(item, dict):
            raise AssemblerError(
                f"predicates.yaml: predicate '{name}' must be a mapping/dict."
            )

        result[name] = PredicateSpec(
            name=name,
            description=item.get("description"),
            raw=item,
        )

    return result


def _assemble_skills(payload: dict[str, Any]) -> dict[str, SkillSpec]:
    data = _get_data_section(payload, "skills.yaml")
    if not isinstance(data, list):
        raise AssemblerError("skills.yaml: 'data' must be a list.")

    raw_map = _coerce_named_mapping(data, required_name_key="name")
    result: dict[str, SkillSpec] = {}

    for name, item in raw_map.items():
        produces = item.get("produces", [])
        if produces is None:
            produces = []
        if not isinstance(produces, list):
            raise AssemblerError(
                f"skills.yaml: 'produces' must be a list for skill '{name}'."
            )

        result[name] = SkillSpec(
            name=name,
            description=item.get("purpose") or item.get("description"),
            produces=[str(x) for x in produces],
            raw=item,
        )

    return result


def _assemble_subagents(payload: dict[str, Any]) -> dict[str, SubagentSpec]:
    data = _get_data_section(payload, "subagents.yaml")
    if not isinstance(data, list):
        raise AssemblerError("subagents.yaml: 'data' must be a list.")

    raw_map = _coerce_named_mapping(data, required_name_key="name")
    result: dict[str, SubagentSpec] = {}

    for name, item in raw_map.items():
        result[name] = SubagentSpec(
            name=name,
            description=item.get("role") or item.get("description"),
            raw=item,
        )

    return result


def _assemble_artifacts(payload: dict[str, Any]) -> dict[str, ArtifactSpec]:
    data = _get_data_section(payload, "artifacts.yaml")
    if not isinstance(data, dict):
        raise AssemblerError("artifacts.yaml: 'data' must be a mapping/dict.")

    expected_outputs = data.get("expected_outputs", [])
    if not isinstance(expected_outputs, list):
        raise AssemblerError(
            "artifacts.yaml: 'data.expected_outputs' must be a list."
        )

    raw_map = _coerce_named_mapping(expected_outputs, required_name_key="id")
    result: dict[str, ArtifactSpec] = {}

    for artifact_id, item in raw_map.items():
        if not isinstance(item, dict):
            raise AssemblerError(
                f"artifacts.yaml: expected_outputs entry '{artifact_id}' must be a mapping/dict."
            )

        result[artifact_id] = ArtifactSpec(
            name=artifact_id,
            producer_step=item.get("produced_by"),
            required=not bool(item.get("conditional", False)),
            raw=item,
        )

    return result


def _assemble_blocking_conditions(
    payload: dict[str, Any],
) -> dict[str, BlockingCondition]:
    data = _get_data_section(payload, "blocking-conditions.yaml")
    if not isinstance(data, list):
        raise AssemblerError("blocking-conditions.yaml: 'data' must be a list.")

    raw_map = _coerce_named_mapping(data, required_name_key="id")
    result: dict[str, BlockingCondition] = {}

    for blocking_id, item in raw_map.items():
        raised_by = item.get("raised_by", [])
        if raised_by is None:
            raised_by = []
        if not isinstance(raised_by, list):
            raised_by = [raised_by]

        result[blocking_id] = BlockingCondition(
            id=blocking_id,
            severity=item.get("severity"),
            halts_workflow=bool(item.get("halts_workflow", False)),
            resolvable=bool(item.get("resolvable", False)),
            raised_by=[str(x) for x in raised_by],
            raw=item,
        )

    return result


def _assemble_stage_gates(payload: dict[str, Any]) -> dict[str, StageGateSpec]:
    data = _get_data_section(payload, "stage-gates.yaml")
    if not isinstance(data, dict):
        raise AssemblerError("stage-gates.yaml: 'data' must be a mapping/dict.")

    result: dict[str, StageGateSpec] = {}
    for name, item in data.items():
        if not isinstance(item, dict):
            raise AssemblerError(
                f"stage-gates.yaml: stage gate '{name}' must be a mapping/dict."
            )

        result[name] = StageGateSpec(
            name=name,
            description=item.get("description"),
            raw=item,
        )

    return result


def _assemble_agents(payload: dict[str, Any]) -> dict[str, AgentSpec]:
    if not payload:
        return {}

    data = _get_data_section(payload, "agents.yaml")
    if not isinstance(data, list):
        raise AssemblerError("agents.yaml: 'data' must be a list.")

    raw_map = _coerce_named_mapping(data, required_name_key="name")
    result: dict[str, AgentSpec] = {}

    for name, item in raw_map.items():
        tools = item.get("tools", []) or []
        if not isinstance(tools, list):
            tools = [tools]

        workflow_steps = item.get("workflow_steps", []) or []
        if not isinstance(workflow_steps, list):
            workflow_steps = [workflow_steps]

        skill_bindings = item.get("skill_bindings", []) or []
        if not isinstance(skill_bindings, list):
            skill_bindings = [skill_bindings]

        produces = item.get("produces", []) or []
        if not isinstance(produces, list):
            produces = [produces]

        consumes = item.get("consumes", []) or []
        if not isinstance(consumes, list):
            consumes = [consumes]

        escalation_targets = item.get("escalation_targets", []) or []
        if not isinstance(escalation_targets, list):
            escalation_targets = [escalation_targets]

        hook_reinforcement = item.get("hook_reinforcement")
        if hook_reinforcement is None or hook_reinforcement == "null":
            hook_reinforcement = None

        failure_mode = item.get("failure_mode")
        if isinstance(failure_mode, str):
            failure_mode = failure_mode.strip() or None

        # Per-agent timeout override (milliseconds, optional)
        raw_timeout = item.get("timeout_ms")
        timeout_ms = int(raw_timeout) if raw_timeout is not None else None

        result[name] = AgentSpec(
            name=name,
            role=item.get("role"),
            layer=item.get("layer"),
            model=str(item.get("model", "sonnet")),
            tools=[str(t) for t in tools],
            workflow_steps=[str(s) for s in workflow_steps],
            skill_bindings=[str(s) for s in skill_bindings],
            produces=[str(p) for p in produces],
            consumes=[str(c) for c in consumes],
            hook_reinforcement=hook_reinforcement,
            escalation_targets=escalation_targets,
            failure_mode=failure_mode,
            activation_predicate=item.get("activation_predicate"),
            timeout_ms=timeout_ms,
            raw=item,
        )

    return result


def _assemble_workflow_steps(payload: dict[str, Any]) -> dict[str, WorkflowStep]:
    data = _get_data_section(payload, "workflow-steps.yaml")
    if not isinstance(data, list):
        raise AssemblerError("workflow-steps.yaml: 'data' must be a list.")

    raw_map = _coerce_named_mapping(data, required_name_key="id")
    result: dict[str, WorkflowStep] = {}

    for step_id, item in raw_map.items():
        component = item.get("component")
        if not isinstance(component, str) or not component.strip():
            raise AssemblerError(
                f"workflow step '{step_id}' is missing a valid 'component' field."
            )

        depends_on = item.get("depends_on", []) or []
        outputs = item.get("outputs", []) or []
        validates = item.get("validates", []) or []
        raises = item.get("raises", []) or []

        for field_name, value in {
            "depends_on": depends_on,
            "outputs": outputs,
            "validates": validates,
            "raises": raises,
        }.items():
            if not isinstance(value, list):
                raise AssemblerError(
                    f"workflow step '{step_id}': '{field_name}' must be a list."
                )

        result[step_id] = WorkflowStep(
            name=step_id,
            component=component.strip(),
            depends_on=[str(x) for x in depends_on],
            outputs=[str(x) for x in outputs],
            validates=[str(x) for x in validates],
            raises=[str(x) for x in raises],
            condition=item.get("condition"),
            skip_if=item.get("skip_if"),
            raw=item,
        )

    return result


def assemble_workflow_spec(loaded: LoadedWorkflowPackages) -> AssembledWorkflowSpec:
    pkg = _package_map(loaded)

    predicates_payload = pkg.get("predicates.yaml", {})
    skills_payload = pkg.get("skills.yaml", {})
    subagents_payload = pkg.get("subagents.yaml", {})
    artifacts_payload = pkg.get("artifacts.yaml", {})
    blocking_payload = pkg.get("blocking-conditions.yaml", {})
    stage_gates_payload = pkg.get("stage-gates.yaml", {})
    workflow_steps_payload = pkg.get("workflow-steps.yaml", {})
    interpretation_payload = pkg.get("interpretation-policy.yaml", {})
    verification_payload = pkg.get("verification-ledger.yaml", {})
    execution_metadata_payload = pkg.get("execution-metadata.yaml", {})
    constitution_payload = pkg.get("constitution.yaml", {})
    hooks_payload = pkg.get("hooks.yaml", {})
    agents_payload = pkg.get("agents.yaml", {})

    return AssembledWorkflowSpec(
        manifest=loaded.manifest,
        constitution=constitution_payload,
        predicates=_assemble_predicates(predicates_payload),
        skills=_assemble_skills(skills_payload),
        subagents=_assemble_subagents(subagents_payload),
        artifacts=_assemble_artifacts(artifacts_payload),
        blocking_conditions=_assemble_blocking_conditions(blocking_payload),
        stage_gates=_assemble_stage_gates(stage_gates_payload),
        workflow_steps=_assemble_workflow_steps(workflow_steps_payload),
        interpretation_policy=InterpretationPolicy(raw=interpretation_payload),
        verification_ledger=VerificationLedgerSpec(raw=verification_payload),
        execution_metadata=ExecutionMetadataSpec(raw=execution_metadata_payload),
        agents=_assemble_agents(agents_payload),
        hooks=hooks_payload,
        raw_sections=pkg,
    )