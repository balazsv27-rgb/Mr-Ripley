"""
Tests for governance/dag_runner/predicates.py

All tests use inline fixture helpers; no disk I/O or full pipeline is required.
One light integration test exercises the four predicate types against a real
shell-executed run state to confirm the evaluator works end-to-end.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from governance.dag_runner.artifacts import ArtifactStructureError
from governance.dag_runner.models import ArtifactRecord, GovernanceRunState
from governance.dag_runner.predicates import (
    ConditionEvaluationResult,
    PredicateEvaluationError,
    PredicateStructureError,
    UnsupportedPredicateError,
    build_predicate_summary,
    evaluate_condition,
    predicate_matches,
)


# ---------------------------------------------------------------------------
# Inline fixture helpers
# ---------------------------------------------------------------------------


def _run_state(*records: ArtifactRecord) -> GovernanceRunState:
    """Build a typed GovernanceRunState pre-populated with the given artifacts."""
    state = GovernanceRunState(
        run_id="test-run",
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_phase="test",
    )
    for rec in records:
        state.artifacts[rec.name] = rec
    return state


def _dict_state(*records: dict) -> dict:
    """Build a minimal persisted dict payload with the given artifact records."""
    return {"artifact_records": list(records)}


def _record(name: str, status: str = "present", **payload_extra) -> ArtifactRecord:
    payload = {"produced_by": "some-step"}
    payload.update(payload_extra)
    return ArtifactRecord(
        name=name,
        producer_step="some-step",
        status=status,  # type: ignore[arg-type]
        payload=payload,
    )


def _dict_record(name: str, status: str = "present", **payload_extra) -> dict:
    payload = {"produced_by": "some-step"}
    payload.update(payload_extra)
    return {
        "name": name,
        "producer_step": "some-step",
        "status": status,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# 1. artifact_exists — matches when artifact is present
# ---------------------------------------------------------------------------


def test_artifact_exists_matches_when_present() -> None:
    state = _run_state(_record("governance_context"))
    result = evaluate_condition(
        {"type": "artifact_exists", "artifact": "governance_context"},
        state,
    )
    assert result.matched is True
    assert result.predicate_type == "artifact_exists"
    assert result.artifact == "governance_context"


# ---------------------------------------------------------------------------
# 2. artifact_exists — does not match when artifact is absent
# ---------------------------------------------------------------------------


def test_artifact_exists_does_not_match_when_absent() -> None:
    state = _run_state()
    result = evaluate_condition(
        {"type": "artifact_exists", "artifact": "governance_context"},
        state,
    )
    assert result.matched is False


def test_artifact_exists_does_not_match_when_status_not_present() -> None:
    state = _run_state(_record("governance_context", status="stale"))
    result = evaluate_condition(
        {"type": "artifact_exists", "artifact": "governance_context"},
        state,
    )
    assert result.matched is False


# ---------------------------------------------------------------------------
# 3. artifact_missing — matches when artifact is absent
# ---------------------------------------------------------------------------


def test_artifact_missing_matches_when_absent() -> None:
    state = _run_state()
    result = evaluate_condition(
        {"type": "artifact_missing", "artifact": "governance_context"},
        state,
    )
    assert result.matched is True
    assert result.predicate_type == "artifact_missing"


# ---------------------------------------------------------------------------
# 4. artifact_missing — does not match when artifact is present
# ---------------------------------------------------------------------------


def test_artifact_missing_does_not_match_when_present() -> None:
    state = _run_state(_record("governance_context"))
    result = evaluate_condition(
        {"type": "artifact_missing", "artifact": "governance_context"},
        state,
    )
    assert result.matched is False


# ---------------------------------------------------------------------------
# 5. artifact_field_equals — matches on equal payload field
# ---------------------------------------------------------------------------


def test_artifact_field_equals_matches_on_equal_value() -> None:
    state = _run_state(_record("my_artifact", verdict="ready"))
    result = evaluate_condition(
        {
            "type": "artifact_field_equals",
            "artifact": "my_artifact",
            "field": "verdict",
            "value": "ready",
        },
        state,
    )
    assert result.matched is True
    assert result.actual == "ready"
    assert result.expected == "ready"
    assert result.field == "verdict"


# ---------------------------------------------------------------------------
# 6. artifact_field_equals — does not match on different value
# ---------------------------------------------------------------------------


def test_artifact_field_equals_does_not_match_on_different_value() -> None:
    state = _run_state(_record("my_artifact", verdict="blocked"))
    result = evaluate_condition(
        {
            "type": "artifact_field_equals",
            "artifact": "my_artifact",
            "field": "verdict",
            "value": "ready",
        },
        state,
    )
    assert result.matched is False
    assert result.actual == "blocked"
    assert result.expected == "ready"


# ---------------------------------------------------------------------------
# 7. artifact_field_equals — does not match when artifact is missing
# ---------------------------------------------------------------------------


def test_artifact_field_equals_does_not_match_when_artifact_missing() -> None:
    state = _run_state()
    result = evaluate_condition(
        {
            "type": "artifact_field_equals",
            "artifact": "my_artifact",
            "field": "verdict",
            "value": "ready",
        },
        state,
    )
    assert result.matched is False
    assert result.actual is None
    assert "absent" in result.detail.lower()


# ---------------------------------------------------------------------------
# 8. artifact_field_equals — does not match when field is missing
# ---------------------------------------------------------------------------


def test_artifact_field_equals_does_not_match_when_field_missing() -> None:
    # Artifact present but does not have a "score" field
    state = _run_state(_record("my_artifact"))
    result = evaluate_condition(
        {
            "type": "artifact_field_equals",
            "artifact": "my_artifact",
            "field": "score",
            "value": 42,
        },
        state,
    )
    assert result.matched is False
    assert result.actual is None
    assert "absent" in result.detail.lower() or "missing" in result.detail.lower()


# ---------------------------------------------------------------------------
# 9. artifact_field_not_equals — matches on different value
# ---------------------------------------------------------------------------


def test_artifact_field_not_equals_matches_on_different_value() -> None:
    state = _run_state(_record("my_artifact", verdict="blocked"))
    result = evaluate_condition(
        {
            "type": "artifact_field_not_equals",
            "artifact": "my_artifact",
            "field": "verdict",
            "value": "ready",
        },
        state,
    )
    assert result.matched is True
    assert result.actual == "blocked"
    assert result.expected == "ready"


# ---------------------------------------------------------------------------
# 10. artifact_field_not_equals — does not match on equal value
# ---------------------------------------------------------------------------


def test_artifact_field_not_equals_does_not_match_on_equal_value() -> None:
    state = _run_state(_record("my_artifact", verdict="ready"))
    result = evaluate_condition(
        {
            "type": "artifact_field_not_equals",
            "artifact": "my_artifact",
            "field": "verdict",
            "value": "ready",
        },
        state,
    )
    assert result.matched is False
    assert result.actual == "ready"


# ---------------------------------------------------------------------------
# 11. Malformed predicate — raises PredicateStructureError
# ---------------------------------------------------------------------------


def test_missing_type_raises_predicate_structure_error() -> None:
    state = _run_state()
    with pytest.raises(PredicateStructureError, match="type"):
        evaluate_condition({"artifact": "foo"}, state)


def test_missing_artifact_key_raises_predicate_structure_error() -> None:
    state = _run_state()
    with pytest.raises(PredicateStructureError, match="artifact"):
        evaluate_condition({"type": "artifact_exists"}, state)


def test_missing_field_key_raises_predicate_structure_error() -> None:
    state = _run_state()
    with pytest.raises(PredicateStructureError):
        evaluate_condition(
            {"type": "artifact_field_equals", "artifact": "foo", "value": 1},
            state,
        )


def test_missing_value_key_raises_predicate_structure_error() -> None:
    state = _run_state()
    with pytest.raises(PredicateStructureError):
        evaluate_condition(
            {"type": "artifact_field_equals", "artifact": "foo", "field": "x"},
            state,
        )


def test_non_dict_condition_raises_predicate_structure_error() -> None:
    state = _run_state()
    with pytest.raises(PredicateStructureError):
        evaluate_condition("artifact_exists", state)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 12. Unknown predicate type — raises UnsupportedPredicateError
# ---------------------------------------------------------------------------


def test_unknown_predicate_type_raises_unsupported_error() -> None:
    state = _run_state()
    with pytest.raises(UnsupportedPredicateError, match="unsupported_type"):
        evaluate_condition({"type": "unsupported_type", "artifact": "foo"}, state)


def test_unsupported_error_is_predicate_evaluation_error() -> None:
    assert issubclass(UnsupportedPredicateError, PredicateEvaluationError)


def test_structure_error_is_predicate_evaluation_error() -> None:
    assert issubclass(PredicateStructureError, PredicateEvaluationError)


# ---------------------------------------------------------------------------
# 13. predicate_matches() — consistent with evaluate_condition()
# ---------------------------------------------------------------------------


def test_predicate_matches_returns_true_consistent_with_evaluate_condition() -> None:
    state = _run_state(_record("my_artifact"))
    condition = {"type": "artifact_exists", "artifact": "my_artifact"}
    full_result = evaluate_condition(condition, state)
    assert predicate_matches(condition, state) is full_result.matched
    assert predicate_matches(condition, state) is True


def test_predicate_matches_returns_false_consistent_with_evaluate_condition() -> None:
    state = _run_state()
    condition = {"type": "artifact_exists", "artifact": "absent_artifact"}
    full_result = evaluate_condition(condition, state)
    assert predicate_matches(condition, state) is full_result.matched
    assert predicate_matches(condition, state) is False


def test_predicate_matches_returns_bool_not_truthy() -> None:
    state = _run_state(_record("my_artifact"))
    result = predicate_matches({"type": "artifact_exists", "artifact": "my_artifact"}, state)
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# 14. Field resolution — payload and data shape support
# ---------------------------------------------------------------------------


def test_field_resolution_from_payload() -> None:
    """Primary field resolution: record["payload"][field]."""
    state = _run_state(_record("my_artifact", verdict="ready"))
    result = evaluate_condition(
        {"type": "artifact_field_equals", "artifact": "my_artifact", "field": "verdict", "value": "ready"},
        state,
    )
    assert result.matched is True
    assert result.actual == "ready"


def test_field_resolution_from_data_envelope() -> None:
    """Secondary field resolution: record["data"][field] (hook artifact_store format)."""
    dict_rec = {
        "name": "my_artifact",
        "producer_step": "some-step",
        "status": "present",
        "payload": {},                        # empty payload — no match here
        "data": {"verdict": "ready"},         # field found here
    }
    state = _dict_state(dict_rec)
    result = evaluate_condition(
        {"type": "artifact_field_equals", "artifact": "my_artifact", "field": "verdict", "value": "ready"},
        state,
    )
    assert result.matched is True
    assert result.actual == "ready"


def test_field_resolution_payload_takes_precedence_over_data() -> None:
    """payload[field] must win over data[field] when both are present."""
    dict_rec = {
        "name": "my_artifact",
        "producer_step": "some-step",
        "status": "present",
        "payload": {"verdict": "ready"},
        "data": {"verdict": "blocked"},       # payload value must win
    }
    state = _dict_state(dict_rec)
    result = evaluate_condition(
        {"type": "artifact_field_equals", "artifact": "my_artifact", "field": "verdict", "value": "ready"},
        state,
    )
    assert result.matched is True
    assert result.actual == "ready"


def test_field_resolution_top_level_fallback() -> None:
    """Tertiary field resolution: record[field] when payload and data both absent."""
    dict_rec = {
        "name": "my_artifact",
        "producer_step": "some-step",
        "status": "present",
        "payload": {},
        "verdict": "ready",                   # top-level key
    }
    state = _dict_state(dict_rec)
    result = evaluate_condition(
        {"type": "artifact_field_equals", "artifact": "my_artifact", "field": "verdict", "value": "ready"},
        state,
    )
    assert result.matched is True
    assert result.actual == "ready"


# ---------------------------------------------------------------------------
# 15. build_predicate_summary() — internally consistent counts
# ---------------------------------------------------------------------------


def test_build_predicate_summary_counts_are_consistent() -> None:
    state = _run_state(_record("alpha"), _record("beta"))
    evals = [
        evaluate_condition({"type": "artifact_exists", "artifact": "alpha"}, state),
        evaluate_condition({"type": "artifact_exists", "artifact": "gamma"}, state),  # absent
        evaluate_condition({"type": "artifact_missing", "artifact": "gamma"}, state),  # matched
    ]
    summary = build_predicate_summary(evals)

    assert summary["total"] == 3
    assert summary["matched"] == 2
    assert summary["unmatched"] == 1
    assert summary["matched"] + summary["unmatched"] == summary["total"]


def test_build_predicate_summary_by_type_counts() -> None:
    state = _run_state(_record("alpha"))
    evals = [
        evaluate_condition({"type": "artifact_exists", "artifact": "alpha"}, state),
        evaluate_condition({"type": "artifact_exists", "artifact": "beta"}, state),
        evaluate_condition({"type": "artifact_missing", "artifact": "beta"}, state),
    ]
    summary = build_predicate_summary(evals)

    assert summary["by_type"]["artifact_exists"] == 2
    assert summary["by_type"]["artifact_missing"] == 1
    assert summary["matched_by_type"].get("artifact_exists") == 1
    assert summary["matched_by_type"].get("artifact_missing") == 1


def test_build_predicate_summary_artifacts_checked_is_sorted() -> None:
    state = _run_state(_record("zeta"), _record("alpha"))
    evals = [
        evaluate_condition({"type": "artifact_exists", "artifact": "zeta"}, state),
        evaluate_condition({"type": "artifact_exists", "artifact": "alpha"}, state),
    ]
    summary = build_predicate_summary(evals)
    assert summary["artifacts_checked"] == sorted(summary["artifacts_checked"])
    assert "alpha" in summary["artifacts_checked"]
    assert "zeta" in summary["artifacts_checked"]


def test_build_predicate_summary_empty_input() -> None:
    summary = build_predicate_summary([])
    assert summary["total"] == 0
    assert summary["matched"] == 0
    assert summary["unmatched"] == 0
    assert summary["artifacts_checked"] == []
    assert summary["failing_predicates"] == []


# ---------------------------------------------------------------------------
# 16. build_predicate_summary() — useful failing predicate entries
# ---------------------------------------------------------------------------


def test_build_predicate_summary_failing_entries_contain_required_fields() -> None:
    state = _run_state(_record("my_artifact", verdict="blocked"))
    evals = [
        evaluate_condition(
            {"type": "artifact_field_equals", "artifact": "my_artifact", "field": "verdict", "value": "ready"},
            state,
        ),
    ]
    summary = build_predicate_summary(evals)

    assert len(summary["failing_predicates"]) == 1
    entry = summary["failing_predicates"][0]

    assert entry["predicate_type"] == "artifact_field_equals"
    assert entry["artifact"] == "my_artifact"
    assert entry["field"] == "verdict"
    assert entry["expected"] == "ready"
    assert entry["actual"] == "blocked"
    assert isinstance(entry["detail"], str)
    assert entry["detail"]  # non-empty


def test_build_predicate_summary_no_failing_when_all_matched() -> None:
    state = _run_state(_record("alpha"))
    evals = [
        evaluate_condition({"type": "artifact_exists", "artifact": "alpha"}, state),
    ]
    summary = build_predicate_summary(evals)
    assert summary["failing_predicates"] == []


def test_build_predicate_summary_absent_artifact_appears_in_failing_entry() -> None:
    state = _run_state()
    evals = [
        evaluate_condition({"type": "artifact_exists", "artifact": "missing_thing"}, state),
    ]
    summary = build_predicate_summary(evals)
    assert len(summary["failing_predicates"]) == 1
    entry = summary["failing_predicates"][0]
    assert entry["artifact"] == "missing_thing"
    assert "absent" in entry["detail"].lower() or "not present" in entry["detail"].lower()


# ---------------------------------------------------------------------------
# Integration — all four predicate types against a real run state
# ---------------------------------------------------------------------------


def test_all_four_predicate_types_against_real_run_state() -> None:
    """
    Light integration test: run the full V1 shell pipeline and verify
    all four predicate types evaluate correctly against the resulting run state.
    """
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
    run_state = result.run_state

    # artifact_exists — governance_context is always produced
    r1 = evaluate_condition(
        {"type": "artifact_exists", "artifact": "governance_context"}, run_state
    )
    assert r1.matched is True

    # artifact_missing — a nonexistent artifact
    r2 = evaluate_condition(
        {"type": "artifact_missing", "artifact": "__nonexistent__"}, run_state
    )
    assert r2.matched is True

    # artifact_field_equals — producer_step is in payload
    r3 = evaluate_condition(
        {
            "type": "artifact_field_equals",
            "artifact": "governance_context",
            "field": "produced_by",
            "value": "load-context",
        },
        run_state,
    )
    assert r3.matched is True

    # artifact_field_not_equals — produced_by is not a wrong step
    r4 = evaluate_condition(
        {
            "type": "artifact_field_not_equals",
            "artifact": "governance_context",
            "field": "produced_by",
            "value": "wrong-step",
        },
        run_state,
    )
    assert r4.matched is True

    # Summary should show 4 total, 4 matched
    summary = build_predicate_summary([r1, r2, r3, r4])
    assert summary["total"] == 4
    assert summary["matched"] == 4
    assert summary["unmatched"] == 0
    assert summary["failing_predicates"] == []
