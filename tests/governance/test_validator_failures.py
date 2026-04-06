"""
Negative fixture suite for governance/dag_runner/validator.py

Each test provides a minimal, inline-constructed AssembledWorkflowSpec that
triggers exactly one (or more) validation failure.  No disk I/O, no YAML
loading, no CLI pipeline required.

Fixture helpers
---------------
_make_spec()   — builds a minimal valid spec; individual params override sections
_make_step()   — builds a single WorkflowStep with sane defaults
_issue_codes() — extracts validation issue codes from a ValidationResult
"""
from __future__ import annotations

from governance.dag_runner.models import (
    ArtifactSpec,
    AssembledWorkflowSpec,
    BlockingCondition,
    ManifestSpec,
    PredicateSpec,
    SkillSpec,
    StageGateSpec,
    WorkflowStep,
)
from governance.dag_runner.validator import ValidationResult, validate_workflow_spec


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str = "step-a",
    component: str = "workflow_step",
    depends_on: list[str] | None = None,
    outputs: list[str] | None = None,
    validates: list[str] | None = None,
    raises: list[str] | None = None,
    condition=None,
    skip_if=None,
) -> tuple[str, WorkflowStep]:
    return step_id, WorkflowStep(
        name=step_id,
        component=component,
        depends_on=depends_on or [],
        outputs=outputs or [],
        validates=validates or [],
        raises=raises or [],
        condition=condition,
        skip_if=skip_if,
    )


def _make_spec(
    steps: dict[str, WorkflowStep] | None = None,
    skills: dict[str, SkillSpec] | None = None,
    artifacts: dict[str, ArtifactSpec] | None = None,
    blocking_conditions: dict[str, BlockingCondition] | None = None,
    stage_gates: dict[str, StageGateSpec] | None = None,
    predicates: dict[str, PredicateSpec] | None = None,
) -> AssembledWorkflowSpec:
    """
    Build a minimal AssembledWorkflowSpec suitable for validator tests.

    All sections default to a single placeholder entry so _validate_required_sections
    does not fire unless the caller explicitly passes an empty dict.
    """
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test-workflow"),
        workflow_steps=(
            steps
            if steps is not None
            else {"noop": WorkflowStep(name="noop", component="workflow_step")}
        ),
        skills=(
            skills
            if skills is not None
            else {"noop-skill": SkillSpec(name="noop-skill")}
        ),
        artifacts=(
            artifacts
            if artifacts is not None
            else {"noop-artifact": ArtifactSpec(name="noop-artifact")}
        ),
        blocking_conditions=(
            blocking_conditions
            if blocking_conditions is not None
            else {"noop-blocker": BlockingCondition(id="noop-blocker")}
        ),
        stage_gates=(
            stage_gates
            if stage_gates is not None
            else {"noop-gate": StageGateSpec(name="noop-gate")}
        ),
        predicates=predicates if predicates is not None else {},
    )


def _issue_codes(result: ValidationResult) -> list[str]:
    return [issue.code for issue in result.issues]


# ---------------------------------------------------------------------------
# 1. Missing dependency
# ---------------------------------------------------------------------------


def test_missing_dependency_reports_invalid() -> None:
    """A step that depends_on a non-existent step must fail validation."""
    sid, step = _make_step("step-a", depends_on=["nonexistent-step"])
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "missing_dependency" in _issue_codes(result)


def test_missing_dependency_includes_detail() -> None:
    """The missing_dependency issue must name the unknown step."""
    sid, step = _make_step("step-a", depends_on=["ghost-step"])
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    issues = [i for i in result.issues if i.code == "missing_dependency"]
    assert issues, "Expected at least one missing_dependency issue."
    assert issues[0].step_id == "step-a"
    assert issues[0].detail.get("depends_on") == "ghost-step"


# ---------------------------------------------------------------------------
# 2. Missing skill reference
# ---------------------------------------------------------------------------


def test_missing_skill_reference_reports_invalid() -> None:
    """A step with component='skill:unknown-skill' must fail when that skill is absent."""
    sid, step = _make_step("step-a", component="skill:unknown-skill")
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "unknown_skill_component" in _issue_codes(result)


def test_declared_skill_reference_passes() -> None:
    """A step referencing a skill that is declared must not fire skill issues."""
    skill = SkillSpec(name="my-skill")
    sid, step = _make_step("step-a", component="skill:my-skill")
    spec = _make_spec(steps={sid: step}, skills={"my-skill": skill})
    result = validate_workflow_spec(spec)

    assert "unknown_skill_component" not in _issue_codes(result)


# ---------------------------------------------------------------------------
# 3. Missing blocker reference
# ---------------------------------------------------------------------------


def test_missing_blocker_reference_reports_invalid() -> None:
    """A step that raises an undeclared blocker ID must fail validation."""
    sid, step = _make_step("step-a", raises=["undeclared-blocker"])
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "unknown_blocking_condition" in _issue_codes(result)


def test_declared_blocker_reference_passes() -> None:
    """A step referencing a declared blocker must not fire blocker issues."""
    blocker = BlockingCondition(id="declared-blocker")
    sid, step = _make_step("step-a", raises=["declared-blocker"])
    spec = _make_spec(
        steps={sid: step},
        blocking_conditions={"declared-blocker": blocker},
    )
    result = validate_workflow_spec(spec)

    assert "unknown_blocking_condition" not in _issue_codes(result)


# ---------------------------------------------------------------------------
# 4. Unsupported condition structure
# ---------------------------------------------------------------------------


def test_unsupported_condition_type_reports_invalid() -> None:
    """A condition dict with an unrecognized type must fail validation."""
    sid, step = _make_step(
        "step-a",
        condition={"type": "totally_unsupported_type_xyz"},
    )
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "unsupported_condition" in _issue_codes(result)


def test_non_dict_condition_reports_invalid() -> None:
    """A condition that is a plain string (not a dict) must fail validation."""
    sid, step = _make_step("step-a", condition="some_string_not_a_dict")
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "unsupported_condition" in _issue_codes(result)


def test_unsupported_skip_if_type_reports_invalid() -> None:
    """A skip_if dict with an unrecognized type must fail validation."""
    sid, step = _make_step(
        "step-a",
        skip_if={"type": "unsupported_skip_type"},
    )
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "unsupported_skip_if" in _issue_codes(result)


def test_supported_inline_condition_does_not_report_unsupported() -> None:
    """A valid inline artifact_field_equals condition must not trigger condition issues."""
    sid, step = _make_step(
        "step-a",
        condition={
            "type": "artifact_field_equals",
            "artifact": "some-artifact",
            "field": "status",
            "value": "ready",
        },
    )
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert "unsupported_condition" not in _issue_codes(result)
    assert "unknown_predicate_reference" not in _issue_codes(result)


# ---------------------------------------------------------------------------
# 5. Dependency cycle
# ---------------------------------------------------------------------------


def test_two_step_dependency_cycle_reports_invalid() -> None:
    """A direct A→B, B→A cycle must fail validation with a cycle issue."""
    sa_id, step_a = _make_step("step-a", depends_on=["step-b"])
    sb_id, step_b = _make_step("step-b", depends_on=["step-a"])
    spec = _make_spec(steps={"step-a": step_a, "step-b": step_b})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "dependency_cycle" in _issue_codes(result)


def test_self_referential_cycle_reports_invalid() -> None:
    """A step that depends on itself must fail with a cycle issue."""
    sid, step = _make_step("step-a", depends_on=["step-a"])
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    # Either missing_dependency (self-ref is unknown until it's known) or
    # dependency_cycle — either signals the workflow is invalid.
    assert result.is_valid is False


# ---------------------------------------------------------------------------
# 6. Invalid validates token
# ---------------------------------------------------------------------------


def test_unknown_validates_token_reports_invalid() -> None:
    """A step that validates an undeclared governance token must fail."""
    sid, step = _make_step("step-a", validates=["totally_unknown_governance_token_xyz"])
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "unknown_validates_token" in _issue_codes(result)


def test_unknown_validates_token_includes_detail() -> None:
    """The unknown_validates_token issue must name the offending token."""
    sid, step = _make_step("step-a", validates=["ghost_token"])
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    issues = [i for i in result.issues if i.code == "unknown_validates_token"]
    assert issues
    assert issues[0].detail.get("token") == "ghost_token"
    assert issues[0].step_id == "step-a"


def test_blocking_condition_id_is_valid_validates_token() -> None:
    """A blocking condition ID used in validates must be accepted (no issue)."""
    blocker = BlockingCondition(id="my-declared-blocker")
    sid, step = _make_step("step-a", validates=["my-declared-blocker"])
    spec = _make_spec(
        steps={sid: step},
        blocking_conditions={"my-declared-blocker": blocker},
    )
    result = validate_workflow_spec(spec)

    assert "unknown_validates_token" not in _issue_codes(result)


def test_empty_validates_list_passes() -> None:
    """A step with an empty validates list must not fire any validates issue."""
    sid, step = _make_step("step-a", validates=[])
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    assert "unknown_validates_token" not in _issue_codes(result)


# ---------------------------------------------------------------------------
# 7. Invalid predicate reference
# ---------------------------------------------------------------------------


def test_unknown_predicate_reference_reports_invalid() -> None:
    """A condition with type='predicate_ref' and an undeclared name must fail."""
    sid, step = _make_step(
        "step-a",
        condition={"type": "predicate_ref", "name": "nonexistent_predicate"},
    )
    spec = _make_spec(steps={sid: step}, predicates={})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "unknown_predicate_reference" in _issue_codes(result)


def test_unknown_predicate_in_skip_if_reports_invalid() -> None:
    """A skip_if with type='predicate_ref' and undeclared name must fail."""
    sid, step = _make_step(
        "step-a",
        skip_if={"type": "predicate_ref", "name": "missing_pred"},
    )
    spec = _make_spec(steps={sid: step}, predicates={})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "unknown_predicate_reference" in _issue_codes(result)


def test_predicate_ref_missing_name_reports_invalid() -> None:
    """A predicate_ref condition without a 'name' key must fail."""
    sid, step = _make_step(
        "step-a",
        condition={"type": "predicate_ref"},  # missing 'name'
    )
    spec = _make_spec(steps={sid: step}, predicates={})
    result = validate_workflow_spec(spec)

    assert result.is_valid is False
    assert "invalid_predicate_reference" in _issue_codes(result)


def test_valid_predicate_reference_passes() -> None:
    """A predicate_ref that resolves to a declared predicate must not fire issues."""
    pred = PredicateSpec(name="my_predicate")
    sid, step = _make_step(
        "step-a",
        condition={"type": "predicate_ref", "name": "my_predicate"},
    )
    spec = _make_spec(steps={sid: step}, predicates={"my_predicate": pred})
    result = validate_workflow_spec(spec)

    assert "unsupported_condition" not in _issue_codes(result)
    assert "unknown_predicate_reference" not in _issue_codes(result)
    assert "invalid_predicate_reference" not in _issue_codes(result)


def test_valid_predicate_ref_in_skip_if_passes() -> None:
    """A declared predicate in skip_if must not fire any predicate reference issues."""
    pred = PredicateSpec(name="skip_pred")
    sid, step = _make_step(
        "step-a",
        skip_if={"type": "predicate_ref", "name": "skip_pred"},
    )
    spec = _make_spec(steps={sid: step}, predicates={"skip_pred": pred})
    result = validate_workflow_spec(spec)

    assert "unknown_predicate_reference" not in _issue_codes(result)
    assert "unsupported_skip_if" not in _issue_codes(result)


# ---------------------------------------------------------------------------
# 8. Multiple issues are accumulated, not silently truncated
# ---------------------------------------------------------------------------


def test_multiple_issues_accumulated() -> None:
    """A step with multiple problems must yield one issue per problem."""
    sid, step = _make_step(
        "step-a",
        depends_on=["missing-step"],
        raises=["missing-blocker"],
        validates=["unknown-token-xyz"],
    )
    spec = _make_spec(steps={sid: step})
    result = validate_workflow_spec(spec)

    codes = _issue_codes(result)
    assert result.is_valid is False
    assert "missing_dependency" in codes
    assert "unknown_blocking_condition" in codes
    assert "unknown_validates_token" in codes
    assert len(result.issues) >= 3


def test_two_steps_each_with_issues_both_reported() -> None:
    """Issues from multiple steps are all reported (not just the first)."""
    sa_id, step_a = _make_step("step-a", depends_on=["ghost-step"])
    sb_id, step_b = _make_step("step-b", raises=["ghost-blocker"])
    spec = _make_spec(steps={"step-a": step_a, "step-b": step_b})
    result = validate_workflow_spec(spec)

    codes = _issue_codes(result)
    assert result.is_valid is False
    assert "missing_dependency" in codes
    assert "unknown_blocking_condition" in codes


# ---------------------------------------------------------------------------
# 9. Real workflow still validates cleanly (sanity check)
# ---------------------------------------------------------------------------


def test_real_workflow_still_passes_after_validator_expansion() -> None:
    """Validator expansion must not break validation of the current real workflow."""
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.loader import load_workflow_packages

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    result = validate_workflow_spec(spec)

    assert result.is_valid is True, (
        f"Real workflow failed validation after expansion. Issues: {result.issues}"
    )
    assert result.issues == []
