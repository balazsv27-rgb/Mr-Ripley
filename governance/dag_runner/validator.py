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

    Currently supported inline condition types:
      - artifact_field_equals
      - artifact_field_not_equals
      - artifact_exists
      - artifact_missing

    Named predicate reference type (resolved via spec.predicates):
      - predicate_ref  (requires a 'name' key; validated by _validate_predicate_references)
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
        "predicate_ref",
    }
    return condition_type in supported


# V1 governance property tokens used in step.validates fields that are not
# blocking condition IDs. These represent high-level invariants validated by
# workflow steps but not necessarily tied to a declared BlockingCondition.
# Source of truth: union of this set and spec.blocking_conditions.keys().
_KNOWN_VALIDATES_TOKENS: frozenset[str] = frozenset({
    "all_blocking_conditions_cleared",
    "all_c_layer_blocking_conditions_resolved",
    "canonical_terminology_used_consistently",
    "claim_classification_unchanged",
    "contract_affecting_changes_flagged_for_doc_update_obligations",
    "doc_only_updates_do_not_prove_runtime",
    "evidence_type_consistency_preserved",
    "historical_sources_not_used_as_current_truth",
    "matrix_entries_consistent_with_canonical_doc_set",
    "no_claims_removed",
    "no_evidence_confusing_residue_in_commit_scope",
    "no_new_claims_introduced",
    "no_unexpected_runtime_artifacts_in_workspace",
    "required_canonical_docs_reviewed_per_claude_md_section_11",
    "role_mapping_preserved",
})


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


def _validate_step_validates(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    """
    Validate that every token in step.validates is a known governance token.

    Allowed token set (V1):
      - All declared blocking condition IDs from spec.blocking_conditions
      - All tokens in _KNOWN_VALIDATES_TOKENS (governance property constants)

    Any token not in this union is rejected as unknown.
    """
    issues: list[ValidationIssue] = []
    known = frozenset(spec.blocking_conditions.keys()) | _KNOWN_VALIDATES_TOKENS

    for step_id, step in spec.workflow_steps.items():
        for token in step.validates:
            if token not in known:
                issues.append(
                    ValidationIssue(
                        code="unknown_validates_token",
                        message=f"validates references unknown token '{token}'.",
                        step_id=step_id,
                        detail={"token": token},
                    )
                )

    return issues


def _validate_predicate_references(spec: AssembledWorkflowSpec) -> list[ValidationIssue]:
    """
    Validate that named predicate references in condition/skip_if fields resolve
    to declared predicates in spec.predicates.

    A named predicate reference has the form:
      {type: "predicate_ref", name: "<predicate_name>"}

    Inline structured conditions (e.g. artifact_field_equals, artifact_exists)
    are handled by _validate_conditions and are NOT predicate references.
    Only conditions with type == "predicate_ref" trigger this lookup.
    """
    issues: list[ValidationIssue] = []
    known_predicates = set(spec.predicates.keys())

    for step_id, step in spec.workflow_steps.items():
        for field_label, condition in (("condition", step.condition), ("skip_if", step.skip_if)):
            if not isinstance(condition, dict):
                continue
            if condition.get("type") != "predicate_ref":
                continue

            pred_name = condition.get("name")
            if not isinstance(pred_name, str) or not pred_name.strip():
                issues.append(
                    ValidationIssue(
                        code="invalid_predicate_reference",
                        message=(
                            f"{field_label} predicate_ref is missing a valid 'name' field."
                        ),
                        step_id=step_id,
                        detail={"field": field_label, "condition": condition},
                    )
                )
            elif pred_name not in known_predicates:
                issues.append(
                    ValidationIssue(
                        code="unknown_predicate_reference",
                        message=(
                            f"{field_label} predicate_ref '{pred_name}' is not declared "
                            "in spec.predicates."
                        ),
                        step_id=step_id,
                        detail={"field": field_label, "predicate": pred_name},
                    )
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
    issues.extend(_validate_step_validates(spec))
    issues.extend(_validate_predicate_references(spec))

    return ValidationResult(
        is_valid=len(issues) == 0,
        issues=issues,
    )


def validate_or_raise(spec: AssembledWorkflowSpec) -> None:
    result = validate_workflow_spec(spec)
    result.raise_if_invalid()