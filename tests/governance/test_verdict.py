"""
Tests for governance/dag_runner/verdict.py

Covers:
- compute_structural_verdict() — structural-only verdict (mirrors compute_verdict)
- compute_verdict() — backward-compatible; delegates to compute_structural_verdict
- compute_runtime_verdict() — runtime-aware verdict using run_state + artifact_summary
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from governance.dag_runner.blockers import BlockerReference, BlockerSummary
from governance.dag_runner.models import (
    AssembledWorkflowSpec,
    BlockingCondition,
    BlockingEvent,
    ExecutionTraceEvent,
    GovernanceRunState,
    ManifestSpec,
)
from governance.dag_runner.validator import ValidationResult
from governance.dag_runner.verdict import (
    GovernanceVerdict,
    compute_runtime_verdict,
    compute_structural_verdict,
    compute_verdict,
)


# ---------------------------------------------------------------------------
# Inline fixture helpers
# ---------------------------------------------------------------------------


def _valid_result() -> ValidationResult:
    return ValidationResult(is_valid=True, issues=[])


def _invalid_result() -> ValidationResult:
    from governance.dag_runner.validator import ValidationIssue

    return ValidationResult(
        is_valid=False,
        issues=[ValidationIssue(code="TEST_ERR", message="test error")],
    )


def _clean_blocker_summary() -> BlockerSummary:
    return BlockerSummary(
        declared_blockers=["blocker_a"],
        referenced_blockers=[BlockerReference(blocker_id="blocker_a", raised_by_step="step-1")],
        orphan_blockers=[],
        unknown_references=[],
    )


def _orphan_blocker_summary() -> BlockerSummary:
    return BlockerSummary(
        declared_blockers=["blocker_a"],
        referenced_blockers=[],
        orphan_blockers=["blocker_a"],
        unknown_references=[],
    )


def _unknown_ref_blocker_summary() -> BlockerSummary:
    return BlockerSummary(
        declared_blockers=[],
        referenced_blockers=[BlockerReference(blocker_id="undeclared", raised_by_step="step-1")],
        orphan_blockers=[],
        unknown_references=[BlockerReference(blocker_id="undeclared", raised_by_step="step-1")],
    )


def _make_manifest() -> ManifestSpec:
    return ManifestSpec(workflow_name="test-workflow")


def _make_spec(blocking_conditions: dict[str, BlockingCondition] | None = None) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=_make_manifest(),
        blocking_conditions=blocking_conditions or {},
    )


def _make_blocking_condition(bid: str, halts_workflow: bool = True) -> BlockingCondition:
    return BlockingCondition(id=bid, halts_workflow=halts_workflow)


def _make_run_state(
    events: list[BlockingEvent] | None = None,
    *,
    completed: bool = True,
) -> GovernanceRunState:
    state = GovernanceRunState(
        run_id="test-run",
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_phase="test",
    )
    if events:
        state.blocking_conditions.extend(events)
    if completed:
        state.execution_trace.append(
            ExecutionTraceEvent(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                node_name="__run__",
                event_type="run_completed",
                detail={},
            )
        )
    return state


def _present_artifact_summary() -> dict:
    return {
        "required_outputs_present": True,
        "missing_required_artifacts": [],
    }


def _missing_artifact_summary(missing: list[str]) -> dict:
    return {
        "required_outputs_present": False,
        "missing_required_artifacts": missing,
    }


# ---------------------------------------------------------------------------
# 1. compute_structural_verdict() — mirrors compute_verdict logic
# ---------------------------------------------------------------------------


def test_compute_structural_verdict_ready_when_clean() -> None:
    verdict = compute_structural_verdict(_valid_result(), _clean_blocker_summary())
    assert verdict.status == "ready"
    assert verdict.reasons == ["Validation passed and blocker structure is consistent."]


def test_compute_structural_verdict_blocked_on_validation_failure() -> None:
    verdict = compute_structural_verdict(_invalid_result(), _clean_blocker_summary())
    assert verdict.is_blocked
    assert "Validation failed" in verdict.reasons[0]


def test_compute_structural_verdict_blocked_on_unknown_references() -> None:
    verdict = compute_structural_verdict(_valid_result(), _unknown_ref_blocker_summary())
    assert verdict.is_blocked
    assert "Unknown blocker references" in verdict.reasons[0]


def test_compute_structural_verdict_review_only_on_orphan_blockers() -> None:
    verdict = compute_structural_verdict(_valid_result(), _orphan_blocker_summary())
    assert verdict.is_review_only
    assert "not referenced" in verdict.reasons[0]


# ---------------------------------------------------------------------------
# 2. compute_verdict() — backward compatibility
# ---------------------------------------------------------------------------


def test_compute_verdict_is_ready_for_current_workflow() -> None:
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.blockers import analyze_blockers
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.planner import build_execution_plan
    from governance.dag_runner.validator import validate_workflow_spec

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validation = validate_workflow_spec(spec)
    plan = build_execution_plan(spec)
    blockers = analyze_blockers(spec, plan)

    verdict = compute_verdict(validation, blockers)

    assert verdict.status == "ready"
    assert verdict.reasons == [
        "Validation passed and blocker structure is consistent."
    ]


def test_compute_verdict_matches_compute_structural_verdict() -> None:
    """compute_verdict must return identical results to compute_structural_verdict."""
    for validation, blockers in [
        (_valid_result(), _clean_blocker_summary()),
        (_invalid_result(), _clean_blocker_summary()),
        (_valid_result(), _orphan_blocker_summary()),
        (_valid_result(), _unknown_ref_blocker_summary()),
    ]:
        v1 = compute_verdict(validation, blockers)
        v2 = compute_structural_verdict(validation, blockers)
        assert v1.status == v2.status
        assert v1.reasons == v2.reasons


# ---------------------------------------------------------------------------
# 3. compute_runtime_verdict() — structural gates
# ---------------------------------------------------------------------------


def test_compute_runtime_verdict_blocked_on_validation_failure() -> None:
    spec = _make_spec()
    run_state = _make_run_state()
    verdict = compute_runtime_verdict(
        _invalid_result(),
        _clean_blocker_summary(),
        run_state,
        _present_artifact_summary(),
        spec,
    )
    assert verdict.is_blocked
    assert "Validation failed" in verdict.reasons[0]


def test_compute_runtime_verdict_blocked_on_unknown_blocker_refs() -> None:
    spec = _make_spec()
    run_state = _make_run_state()
    verdict = compute_runtime_verdict(
        _valid_result(),
        _unknown_ref_blocker_summary(),
        run_state,
        _present_artifact_summary(),
        spec,
    )
    assert verdict.is_blocked
    assert "Unknown blocker references" in verdict.reasons[0]


# ---------------------------------------------------------------------------
# 4. compute_runtime_verdict() — fatal runtime blockers → blocked
# ---------------------------------------------------------------------------


def test_compute_runtime_verdict_blocked_on_fatal_unresolved_blocker() -> None:
    spec = _make_spec({"fatal_blocker": _make_blocking_condition("fatal_blocker", halts_workflow=True)})
    event = BlockingEvent(blocking_id="fatal_blocker", raised_by="some-step", resolved=False)
    run_state = _make_run_state([event])

    verdict = compute_runtime_verdict(
        _valid_result(),
        _clean_blocker_summary(),
        run_state,
        _present_artifact_summary(),
        spec,
    )
    assert verdict.is_blocked
    assert "fatal_blocker" in verdict.reasons[0]


def test_compute_runtime_verdict_not_blocked_when_fatal_blocker_resolved() -> None:
    spec = _make_spec({"fatal_blocker": _make_blocking_condition("fatal_blocker", halts_workflow=True)})
    event = BlockingEvent(blocking_id="fatal_blocker", raised_by="some-step", resolved=True)
    run_state = _make_run_state([event])

    verdict = compute_runtime_verdict(
        _valid_result(),
        _clean_blocker_summary(),
        run_state,
        _present_artifact_summary(),
        spec,
    )
    # Resolved fatal → does not block
    assert not verdict.is_blocked


# ---------------------------------------------------------------------------
# 5. compute_runtime_verdict() — non-fatal unresolved → review_only
# ---------------------------------------------------------------------------


def test_compute_runtime_verdict_review_only_on_non_fatal_unresolved_blocker() -> None:
    spec = _make_spec({"soft_blocker": _make_blocking_condition("soft_blocker", halts_workflow=False)})
    event = BlockingEvent(blocking_id="soft_blocker", raised_by="some-step", resolved=False)
    run_state = _make_run_state([event])

    verdict = compute_runtime_verdict(
        _valid_result(),
        _clean_blocker_summary(),
        run_state,
        _present_artifact_summary(),
        spec,
    )
    assert verdict.is_review_only
    assert "soft_blocker" in verdict.reasons[0]


# ---------------------------------------------------------------------------
# 6. compute_runtime_verdict() — missing required artifacts → review_only
# ---------------------------------------------------------------------------


def test_compute_runtime_verdict_review_only_when_required_artifacts_missing() -> None:
    spec = _make_spec()
    run_state = _make_run_state()

    verdict = compute_runtime_verdict(
        _valid_result(),
        _clean_blocker_summary(),
        run_state,
        _missing_artifact_summary(["some_artifact"]),
        spec,
    )
    assert verdict.is_review_only
    assert "some_artifact" in verdict.reasons[0]


# ---------------------------------------------------------------------------
# 7. compute_runtime_verdict() — incomplete workflow → review_only
# ---------------------------------------------------------------------------


def test_compute_runtime_verdict_review_only_when_workflow_not_complete() -> None:
    spec = _make_spec()
    run_state = _make_run_state(completed=False)

    verdict = compute_runtime_verdict(
        _valid_result(),
        _clean_blocker_summary(),
        run_state,
        _present_artifact_summary(),
        spec,
    )
    assert verdict.is_review_only
    assert "run_completed" in verdict.reasons[0]


# ---------------------------------------------------------------------------
# 8. compute_runtime_verdict() — orphan structural blockers → review_only
# ---------------------------------------------------------------------------


def test_compute_runtime_verdict_review_only_on_orphan_blockers() -> None:
    spec = _make_spec()
    run_state = _make_run_state()

    verdict = compute_runtime_verdict(
        _valid_result(),
        _orphan_blocker_summary(),
        run_state,
        _present_artifact_summary(),
        spec,
    )
    assert verdict.is_review_only
    assert "not referenced" in verdict.reasons[0]


# ---------------------------------------------------------------------------
# 9. compute_runtime_verdict() — ready when everything is clean
# ---------------------------------------------------------------------------


def test_compute_runtime_verdict_ready_when_all_clean() -> None:
    spec = _make_spec()
    run_state = _make_run_state()

    verdict = compute_runtime_verdict(
        _valid_result(),
        _clean_blocker_summary(),
        run_state,
        _present_artifact_summary(),
        spec,
    )
    assert verdict.is_ready
    assert "all required artifacts present" in verdict.reasons[0]


# ---------------------------------------------------------------------------
# 10. Integration — compute_runtime_verdict for full shell run
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def full_pipeline_for_runtime_verdict():
    """Run the full pipeline once; return (spec, validation, blocker_summary, run_state)."""
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.artifacts import build_artifact_summary
    from governance.dag_runner.blockers import analyze_blockers
    from governance.dag_runner.executor import execute_plan
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.planner import build_execution_plan
    from governance.dag_runner.validator import validate_workflow_spec
    from governance.dag_runner.verdict import compute_verdict

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validation = validate_workflow_spec(spec)
    plan = build_execution_plan(spec)
    blockers = analyze_blockers(spec, plan)
    verdict = compute_verdict(validation, blockers)
    result = execute_plan(spec, plan, verdict_status=verdict.status)
    run_state = result.run_state
    artifact_summary = build_artifact_summary(spec, run_state)
    return spec, validation, blockers, run_state, artifact_summary


def test_compute_runtime_verdict_ready_for_full_shell_run(
    full_pipeline_for_runtime_verdict,
) -> None:
    spec, validation, blocker_summary, run_state, artifact_summary = (
        full_pipeline_for_runtime_verdict
    )
    verdict = compute_runtime_verdict(
        validation, blocker_summary, run_state, artifact_summary, spec
    )
    assert verdict.is_ready
    assert "all required artifacts present" in verdict.reasons[0]
