"""
Tests for governance/dag_runner/blockers.py

Covers both structural blocker analysis (analyze_blockers) and runtime blocker
analysis (analyze_runtime_blockers, has_unresolved_fatal_blocks).

Inline fixtures are used for isolated unit tests.
The full_pipeline fixture is used for integration-level tests.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from governance.dag_runner.blockers import (
    BlockerError,
    BlockerSummary,
    RuntimeBlockerSummary,
    analyze_blockers,
    analyze_runtime_blockers,
    has_unresolved_fatal_blocks,
)
from governance.dag_runner.models import (
    AssembledWorkflowSpec,
    BlockingCondition,
    BlockingEvent,
    GovernanceRunState,
    ManifestSpec,
)


# ---------------------------------------------------------------------------
# Inline fixture helpers
# ---------------------------------------------------------------------------


def _make_manifest() -> ManifestSpec:
    return ManifestSpec(workflow_name="test-workflow")


def _make_spec(blocking_conditions: dict[str, BlockingCondition]) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=_make_manifest(),
        blocking_conditions=blocking_conditions,
    )


def _make_blocking_condition(
    blocker_id: str,
    halts_workflow: bool = False,
    severity: str = "high",
) -> BlockingCondition:
    return BlockingCondition(
        id=blocker_id,
        severity=severity,
        halts_workflow=halts_workflow,
        resolvable=True,
    )


def _make_run_state(events: list[BlockingEvent] | None = None) -> GovernanceRunState:
    state = GovernanceRunState(
        run_id="test-run",
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_phase="test",
    )
    if events:
        state.blocking_conditions.extend(events)
    return state


def _make_event(
    blocking_id: str,
    raised_by: str = "some-step",
    resolved: bool = False,
) -> BlockingEvent:
    return BlockingEvent(
        blocking_id=blocking_id,
        raised_by=raised_by,
        resolved=resolved,
    )


# ---------------------------------------------------------------------------
# 1. Structural blocker analysis (existing)
# ---------------------------------------------------------------------------


def test_blocker_analysis_matches_current_workflow() -> None:
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.planner import build_execution_plan
    from governance.dag_runner.validator import validate_or_raise

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)

    summary = analyze_blockers(spec, plan)

    assert len(summary.declared_blockers) == 12
    assert len(summary.referenced_blockers) == 17
    assert len(summary.orphan_blockers) == 0
    assert len(summary.unknown_references) == 0
    assert summary.is_structurally_consistent is True


# ---------------------------------------------------------------------------
# 2. analyze_runtime_blockers() — empty run state
# ---------------------------------------------------------------------------


def test_analyze_runtime_blockers_empty_state_returns_zero_counts() -> None:
    spec = _make_spec({})
    run_state = _make_run_state()
    summary = analyze_runtime_blockers(run_state, spec)

    assert summary.raised_blockers == []
    assert summary.unresolved_blockers == []
    assert summary.fatal_unresolved_blockers == []
    assert summary.raised_by_step == {}
    assert summary.total_raised == 0
    assert summary.total_unresolved == 0
    assert summary.total_fatal_unresolved == 0
    assert summary.has_unresolved is False
    assert summary.has_fatal_unresolved is False


# ---------------------------------------------------------------------------
# 3. analyze_runtime_blockers() — resolved vs unresolved
# ---------------------------------------------------------------------------


def test_analyze_runtime_blockers_resolved_blocker_not_in_unresolved() -> None:
    spec = _make_spec({
        "blocker_a": _make_blocking_condition("blocker_a", halts_workflow=True),
    })
    run_state = _make_run_state([_make_event("blocker_a", resolved=True)])
    summary = analyze_runtime_blockers(run_state, spec)

    assert summary.raised_blockers == ["blocker_a"]
    assert summary.unresolved_blockers == []
    assert summary.fatal_unresolved_blockers == []
    assert summary.has_unresolved is False
    assert summary.has_fatal_unresolved is False


def test_analyze_runtime_blockers_unresolved_non_fatal_blocker() -> None:
    spec = _make_spec({
        "blocker_a": _make_blocking_condition("blocker_a", halts_workflow=False),
    })
    run_state = _make_run_state([_make_event("blocker_a", resolved=False)])
    summary = analyze_runtime_blockers(run_state, spec)

    assert summary.unresolved_blockers == ["blocker_a"]
    assert summary.fatal_unresolved_blockers == []
    assert summary.has_unresolved is True
    assert summary.has_fatal_unresolved is False


def test_analyze_runtime_blockers_unresolved_fatal_blocker() -> None:
    spec = _make_spec({
        "blocker_fatal": _make_blocking_condition("blocker_fatal", halts_workflow=True),
    })
    run_state = _make_run_state([_make_event("blocker_fatal", resolved=False)])
    summary = analyze_runtime_blockers(run_state, spec)

    assert summary.unresolved_blockers == ["blocker_fatal"]
    assert summary.fatal_unresolved_blockers == ["blocker_fatal"]
    assert summary.has_unresolved is True
    assert summary.has_fatal_unresolved is True
    assert summary.total_fatal_unresolved == 1


# ---------------------------------------------------------------------------
# 4. analyze_runtime_blockers() — mixed fatal and non-fatal
# ---------------------------------------------------------------------------


def test_analyze_runtime_blockers_distinguishes_fatal_from_non_fatal() -> None:
    spec = _make_spec({
        "fatal_blocker": _make_blocking_condition("fatal_blocker", halts_workflow=True),
        "soft_blocker": _make_blocking_condition("soft_blocker", halts_workflow=False),
    })
    run_state = _make_run_state([
        _make_event("fatal_blocker", resolved=False),
        _make_event("soft_blocker", resolved=False),
    ])
    summary = analyze_runtime_blockers(run_state, spec)

    assert sorted(summary.unresolved_blockers) == ["fatal_blocker", "soft_blocker"]
    assert summary.fatal_unresolved_blockers == ["fatal_blocker"]
    assert summary.total_unresolved == 2
    assert summary.total_fatal_unresolved == 1


# ---------------------------------------------------------------------------
# 5. analyze_runtime_blockers() — raised_by_step map
# ---------------------------------------------------------------------------


def test_analyze_runtime_blockers_raised_by_step_map() -> None:
    spec = _make_spec({
        "blocker_a": _make_blocking_condition("blocker_a"),
        "blocker_b": _make_blocking_condition("blocker_b"),
    })
    run_state = _make_run_state([
        _make_event("blocker_a", raised_by="step-one"),
        _make_event("blocker_b", raised_by="step-two"),
    ])
    summary = analyze_runtime_blockers(run_state, spec)

    assert "step-one" in summary.raised_by_step
    assert "step-two" in summary.raised_by_step
    assert summary.raised_by_step["step-one"] == ["blocker_a"]
    assert summary.raised_by_step["step-two"] == ["blocker_b"]


def test_analyze_runtime_blockers_deduplicates_ids_per_step() -> None:
    spec = _make_spec({
        "blocker_a": _make_blocking_condition("blocker_a"),
    })
    # Same step raises the same blocker twice
    run_state = _make_run_state([
        _make_event("blocker_a", raised_by="step-one"),
        _make_event("blocker_a", raised_by="step-one"),
    ])
    summary = analyze_runtime_blockers(run_state, spec)

    assert summary.raised_blockers == ["blocker_a"]
    assert summary.raised_by_step["step-one"] == ["blocker_a"]


# ---------------------------------------------------------------------------
# 6. analyze_runtime_blockers() — fail closed on unknown IDs
# ---------------------------------------------------------------------------


def test_analyze_runtime_blockers_unknown_id_raises_blocker_error() -> None:
    spec = _make_spec({})  # no declared blockers
    run_state = _make_run_state([_make_event("undeclared_blocker")])

    with pytest.raises(BlockerError, match="undeclared_blocker"):
        analyze_runtime_blockers(run_state, spec)


# ---------------------------------------------------------------------------
# 7. has_unresolved_fatal_blocks()
# ---------------------------------------------------------------------------


def test_has_unresolved_fatal_blocks_returns_false_when_no_events() -> None:
    spec = _make_spec({})
    run_state = _make_run_state()
    assert has_unresolved_fatal_blocks(run_state, spec) is False


def test_has_unresolved_fatal_blocks_returns_false_for_non_fatal_unresolved() -> None:
    spec = _make_spec({
        "soft": _make_blocking_condition("soft", halts_workflow=False),
    })
    run_state = _make_run_state([_make_event("soft", resolved=False)])
    assert has_unresolved_fatal_blocks(run_state, spec) is False


def test_has_unresolved_fatal_blocks_returns_true_for_fatal_unresolved() -> None:
    spec = _make_spec({
        "fatal": _make_blocking_condition("fatal", halts_workflow=True),
    })
    run_state = _make_run_state([_make_event("fatal", resolved=False)])
    assert has_unresolved_fatal_blocks(run_state, spec) is True


def test_has_unresolved_fatal_blocks_returns_false_when_fatal_resolved() -> None:
    spec = _make_spec({
        "fatal": _make_blocking_condition("fatal", halts_workflow=True),
    })
    run_state = _make_run_state([_make_event("fatal", resolved=True)])
    assert has_unresolved_fatal_blocks(run_state, spec) is False


# ---------------------------------------------------------------------------
# 8. Integration — full shell run produces no runtime blocking events
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def full_pipeline_runtime():
    """Run the full pipeline once and return (spec, run_state)."""
    from governance.dag_runner.assembler import assemble_workflow_spec
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
    return spec, result.run_state


def test_analyze_runtime_blockers_empty_for_shell_run(full_pipeline_runtime) -> None:
    """Shell run has no predicate errors so blocking_conditions is empty."""
    spec, run_state = full_pipeline_runtime
    summary = analyze_runtime_blockers(run_state, spec)

    assert summary.total_raised == 0
    assert summary.has_unresolved is False
    assert summary.has_fatal_unresolved is False
    assert summary.raised_by_step == {}


def test_has_unresolved_fatal_blocks_false_for_shell_run(full_pipeline_runtime) -> None:
    spec, run_state = full_pipeline_runtime
    assert has_unresolved_fatal_blocks(run_state, spec) is False
