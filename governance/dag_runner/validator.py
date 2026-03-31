from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from governance.dag_runner.models import AssembledWorkflowSpec


class ValidationError(RuntimeError):
    """Raised when the assembled workflow spec is invalid."""


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    step_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def raise_if_invalid(self) -> None:
        if self.is_valid:
            return

        lines = ["Workflow validation failed:"]
        for issue in self.issues:
            prefix = f"[{issue.code}]"
            if issue.step_id:
                prefix += f" step={issue.step_id}"
            lines.append(f"  - {prefix} {issue.message}")

        raise ValidationError("\n".join(lines))


def _parse_component(component: str) -> tuple[str, str | None]:
    """
    Split component strings like:
    - skill:doc-truth-classification
    - subagent:reviewer
    - stage_gate:phase_a
    - hook:pre-pr-governance-gate

    Returns:
        (kind, name_or_none)
    """
    if ":" not in component:
        return component.strip(), None

    kind, value = component.split(":", 1)
    return kind.strip(), value.strip() or None


def _is_supported_condition(value: Any) -> bool:
    """
    V1 condition support:
    - None
    - dict with a recognized 'type'

    Currently supported:
      - artifact_field_equals
      - artifact_field_not_equals
      - artifact_exists
      - artifact_missing
    """
    if value is None:
        return True

    if not isinstance(value, dict):
        return False

    condition_type = value.get("type")
    if not isinstance(condition_type, str) or not condition_type.strip():
        return False

    supported = {
        "artifact_field_equals",
        "artifact_field_not_equals",
        "artifact_exists",
        "artifact_missing",
    }
    return condition_type in supported


def _validate_required_sections(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not spec.workflow_steps:
        issues.append(
            ValidationIssue(
                code="missing_workflow_steps",
                message="No workflow steps were assembled.",
            )
        )

    if not spec.skills:
        issues.append(
            ValidationIssue(
                code="missing_skills",
                message="No skills were assembled.",
            )
        )

    if not spec.artifacts:
        issues.append(
            ValidationIssue(
                code="missing_artifacts",
                message="No artifacts were assembled.",
            )
        )

    if not spec.blocking_conditions:
        issues.append(
            ValidationIssue(
                code="missing_blocking_conditions",
                message="No blocking conditions were assembled.",
            )
        )

    if not spec.stage_gates:
        issues.append(
            ValidationIssue(
                code="missing_stage_gates",
                message="No stage gates were assembled.",
            )
        )

    return issues


def _validate_step_dependencies(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known_steps = set(spec.workflow_steps.keys())

    for step_id, step in spec.workflow_steps.items():
        for dep in step.depends_on:
            if dep not in known_steps:
                issues.append(
                    ValidationIssue(
                        code="missing_dependency",
                        message=f"depends_on references unknown step '{dep}'.",
                        step_id=step_id,
                        detail={"depends_on": dep},
                    )
                )

    return issues


def _validate_step_outputs(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known_artifacts = set(spec.artifacts.keys())

    for step_id, step in spec.workflow_steps.items():
        for artifact_name in step.outputs:
            if artifact_name not in known_artifacts:
                issues.append(
                    ValidationIssue(
                        code="unknown_output_artifact",
                        message=f"outputs references unknown artifact '{artifact_name}'.",
                        step_id=step_id,
                        detail={"artifact": artifact_name},
                    )
                )

    return issues


def _validate_step_raises(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known_blockers = set(spec.blocking_conditions.keys())

    for step_id, step in spec.workflow_steps.items():
        for blocker_id in step.raises:
            if blocker_id not in known_blockers:
                issues.append(
                    ValidationIssue(
                        code="unknown_blocking_condition",
                        message=f"raises references unknown blocking condition '{blocker_id}'.",
                        step_id=step_id,
                        detail={"blocking_condition": blocker_id},
                    )
                )

    return issues


def _validate_component_references(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for step_id, step in spec.workflow_steps.items():
        kind, name = _parse_component(step.component)

        if kind == "skill":
            if not name or name not in spec.skills:
                issues.append(
                    ValidationIssue(
                        code="unknown_skill_component",
                        message=f"component references unknown skill '{name}'.",
                        step_id=step_id,
                        detail={"component": step.component},
                    )
                )

        elif kind == "subagent":
            if not name or name not in spec.subagents:
                issues.append(
                    ValidationIssue(
                        code="unknown_subagent_component",
                        message=f"component references unknown subagent '{name}'.",
                        step_id=step_id,
                        detail={"component": step.component},
                    )
                )

        elif kind == "stage_gate":
            if not name or name not in spec.stage_gates:
                issues.append(
                    ValidationIssue(
                        code="unknown_stage_gate_component",
                        message=f"component references unknown stage gate '{name}'.",
                        step_id=step_id,
                        detail={"component": step.component},
                    )
                )

        elif kind == "hook":
            if not name:
                issues.append(
                    ValidationIssue(
                        code="invalid_hook_component",
                        message="hook component is missing a hook name.",
                        step_id=step_id,
                        detail={"component": step.component},
                    )
                )

        else:
            accepted_bare = {
                "final_gate",
                "blocking_evaluator",
                "verification_update",
                "artifact_gate",
                "predicate_gate",
                "workflow_step",
                "constitution",
                "stage_gates",
                "hooks",
                "subagents",
            }

            if kind not in accepted_bare and ":" not in step.component:
                issues.append(
                    ValidationIssue(
                        code="unknown_component_kind",
                        message=f"component kind '{kind}' is not recognized in V1.",
                        step_id=step_id,
                        detail={"component": step.component},
                    )
                )

    return issues


def _validate_conditions(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for step_id, step in spec.workflow_steps.items():
        if not _is_supported_condition(step.condition):
            issues.append(
                ValidationIssue(
                    code="unsupported_condition",
                    message="condition uses an unsupported V1 structure.",
                    step_id=step_id,
                    detail={"condition": step.condition},
                )
            )

        if not _is_supported_condition(step.skip_if):
            issues.append(
                ValidationIssue(
                    code="unsupported_skip_if",
                    message="skip_if uses an unsupported V1 structure.",
                    step_id=step_id,
                    detail={"skip_if": step.skip_if},
                )
            )

    return issues


def _detect_cycle_from(
    start: str,
    graph: dict[str, list[str]],
    visited: set[str],
    visiting: set[str],
    issues: list[ValidationIssue],
) -> None:
    visiting.add(start)

    for neighbor in graph.get(start, []):
        if neighbor in visiting:
            issues.append(
                ValidationIssue(
                    code="dependency_cycle",
                    message=f"Cycle detected involving '{start}' -> '{neighbor}'.",
                    step_id=start,
                    detail={"from": start, "to": neighbor},
                )
            )
            continue

        if neighbor not in visited:
            _detect_cycle_from(neighbor, graph, visited, visiting, issues)

    visiting.remove(start)
    visited.add(start)


def _validate_dependency_cycles(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    graph = {
        step_id: list(step.depends_on)
        for step_id, step in spec.workflow_steps.items()
    }

    visited: set[str] = set()

    for step_id in graph:
        if step_id not in visited:
            _detect_cycle_from(
                start=step_id,
                graph=graph,
                visited=visited,
                visiting=set(),
                issues=issues,
            )

    return issues


def validate_workflow_spec(spec: AssembledWorkflowSpec) -> ValidationResult:
    issues: list[ValidationIssue] = []

    issues.extend(_validate_required_sections(spec))
    issues.extend(_validate_step_dependencies(spec))
    issues.extend(_validate_step_outputs(spec))
    issues.extend(_validate_step_raises(spec))
    issues.extend(_validate_component_references(spec))
    issues.extend(_validate_conditions(spec))
    issues.extend(_validate_dependency_cycles(spec))

    return ValidationResult(
        is_valid=len(issues) == 0,
        issues=issues,
    )


def validate_or_raise(spec: AssembledWorkflowSpec) -> None:
    result = validate_workflow_spec(spec)
    result.raise_if_invalid()