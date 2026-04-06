"""
Tests for governance/dag_runner/artifacts.py

Tests cover artifact policy queries using both typed GovernanceRunState objects
and persisted dict payloads (the two input forms the module accepts).

Inline fixtures are used for isolated unit tests.
The full pipeline fixture is used only for integration-level tests that require
the actual assembled spec and a real execution result.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from governance.dag_runner.artifacts import (
    ArtifactPolicyError,
    ArtifactStructureError,
    artifact_exists,
    build_artifact_summary,
    get_artifact_record,
    get_missing_required_artifacts,
    get_required_artifacts,
)
from governance.dag_runner.models import (
    ArtifactRecord,
    ArtifactSpec,
    AssembledWorkflowSpec,
    GovernanceRunState,
    ManifestSpec,
)


# ---------------------------------------------------------------------------
# Inline fixture helpers
# ---------------------------------------------------------------------------


def _make_manifest() -> ManifestSpec:
    return ManifestSpec(workflow_name="test-workflow")


def _make_spec(artifacts: dict[str, ArtifactSpec]) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=_make_manifest(),
        artifacts=artifacts,
    )


def _make_artifact_spec(name: str, required: bool) -> ArtifactSpec:
    return ArtifactSpec(name=name, required=required)


def _make_run_state(artifact_map: dict[str, ArtifactRecord]) -> GovernanceRunState:
    state = GovernanceRunState(
        run_id="test-run",
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_phase="test",
    )
    state.artifacts.update(artifact_map)
    return state


def _make_artifact_record(name: str, status: str = "present") -> ArtifactRecord:
    return ArtifactRecord(
        name=name,
        producer_step="some-step",
        status=status,  # type: ignore[arg-type]
        payload={"produced_by": "some-step"},
    )


def _dict_run_state(*records: dict) -> dict:
    """Build a minimal persisted dict payload with the given artifact records."""
    return {"artifact_records": list(records)}


def _dict_record(name: str, status: str = "present") -> dict:
    return {
        "name": name,
        "producer_step": "some-step",
        "status": status,
        "payload": {"produced_by": "some-step"},
    }


# ---------------------------------------------------------------------------
# Shared integration fixture — runs the full pipeline once per module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def full_pipeline():
    """Assemble the real spec and produce a real run state (V1 shell execution)."""
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


# ---------------------------------------------------------------------------
# 1. artifact_exists() — typed GovernanceRunState — present
# ---------------------------------------------------------------------------


def test_artifact_exists_returns_true_for_present_artifact_in_typed_state() -> None:
    record = _make_artifact_record("governance_context", status="present")
    run_state = _make_run_state({"governance_context": record})
    assert artifact_exists(run_state, "governance_context") is True


# ---------------------------------------------------------------------------
# 2. artifact_exists() — typed GovernanceRunState — missing artifact
# ---------------------------------------------------------------------------


def test_artifact_exists_returns_false_for_absent_artifact_in_typed_state() -> None:
    run_state = _make_run_state({})
    assert artifact_exists(run_state, "governance_context") is False


def test_artifact_exists_returns_false_for_unknown_name_in_typed_state() -> None:
    record = _make_artifact_record("governance_context")
    run_state = _make_run_state({"governance_context": record})
    assert artifact_exists(run_state, "claim_classification_map") is False


# ---------------------------------------------------------------------------
# 3. artifact_exists() — all non-present statuses return False
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["missing", "blocked", "stale"])
def test_artifact_exists_returns_false_for_non_present_status(status: str) -> None:
    record = _make_artifact_record("some_artifact", status=status)
    run_state = _make_run_state({"some_artifact": record})
    assert artifact_exists(run_state, "some_artifact") is False


# ---------------------------------------------------------------------------
# 4. artifact_exists() — persisted dict payload via artifact_records
# ---------------------------------------------------------------------------


def test_artifact_exists_works_for_persisted_dict_payload() -> None:
    run_state = _dict_run_state(_dict_record("governance_context", "present"))
    assert artifact_exists(run_state, "governance_context") is True


def test_artifact_exists_returns_false_for_absent_artifact_in_dict_payload() -> None:
    run_state = _dict_run_state()
    assert artifact_exists(run_state, "governance_context") is False


def test_artifact_exists_returns_false_for_non_present_in_dict_payload() -> None:
    run_state = _dict_run_state(_dict_record("governance_context", "stale"))
    assert artifact_exists(run_state, "governance_context") is False


# ---------------------------------------------------------------------------
# 5. get_required_artifacts() — deterministic list for current assembled spec
# ---------------------------------------------------------------------------


def test_get_required_artifacts_returns_sorted_deterministic_list(full_pipeline) -> None:
    spec, _ = full_pipeline
    required = get_required_artifacts(spec)

    assert isinstance(required, list)
    assert required == sorted(required), "get_required_artifacts must return a sorted list."


def test_get_required_artifacts_count_matches_spec(full_pipeline) -> None:
    spec, _ = full_pipeline
    required = get_required_artifacts(spec)

    # 16 unconditionally required artifacts (19 total - 3 conditional)
    assert len(required) == 16


def test_get_required_artifacts_includes_known_required(full_pipeline) -> None:
    spec, _ = full_pipeline
    required = get_required_artifacts(spec)

    assert "governance_context" in required
    assert "claim_classification_map" in required
    assert "pr_readiness_verdict" in required


# ---------------------------------------------------------------------------
# 6. get_required_artifacts() — excludes conditional artifacts
# ---------------------------------------------------------------------------


def test_get_required_artifacts_excludes_conditional_artifacts(full_pipeline) -> None:
    spec, _ = full_pipeline
    required = get_required_artifacts(spec)

    # These three are declared conditional: true in artifacts.yaml
    assert "doc_update_plan" not in required
    assert "invariance_verdict" not in required
    assert "verification_matrix_delta" not in required


def test_get_required_artifacts_excludes_conditional_in_inline_spec() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
        "beta": _make_artifact_spec("beta", required=False),  # conditional
        "gamma": _make_artifact_spec("gamma", required=True),
    })
    required = get_required_artifacts(spec)
    assert required == ["alpha", "gamma"]
    assert "beta" not in required


# ---------------------------------------------------------------------------
# 7. get_missing_required_artifacts() — detects a missing required artifact
# ---------------------------------------------------------------------------


def test_get_missing_required_artifacts_detects_missing() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
        "beta": _make_artifact_spec("beta", required=True),
    })
    # Only alpha is present in the run state
    run_state = _dict_run_state(_dict_record("alpha", "present"))
    missing = get_missing_required_artifacts(spec, run_state)
    assert missing == ["beta"]


def test_get_missing_required_artifacts_detects_non_present_status() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
    })
    # alpha exists but with stale status — not present
    run_state = _dict_run_state(_dict_record("alpha", "stale"))
    missing = get_missing_required_artifacts(spec, run_state)
    assert "alpha" in missing


# ---------------------------------------------------------------------------
# 8. get_missing_required_artifacts() — empty list for complete shell run state
# ---------------------------------------------------------------------------


def test_get_missing_required_artifacts_empty_for_complete_shell_run(full_pipeline) -> None:
    """After a full V1 shell execution all required artifacts should be present."""
    spec, run_state = full_pipeline
    missing = get_missing_required_artifacts(spec, run_state)
    assert missing == [], (
        f"Expected no missing required artifacts after shell run, got: {missing}"
    )


# ---------------------------------------------------------------------------
# 9. build_artifact_summary() — required keys and internally consistent counts
# ---------------------------------------------------------------------------


def test_build_artifact_summary_contains_required_keys() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
        "beta": _make_artifact_spec("beta", required=False),
    })
    run_state = _dict_run_state(_dict_record("alpha", "present"))
    summary = build_artifact_summary(spec, run_state)

    expected_keys = {
        "declared_artifacts",
        "recorded_artifacts",
        "required_artifacts",
        "required_artifact_count",
        "present_required_artifacts",
        "missing_required_artifacts",
        "required_outputs_present",
        "artifact_status_counts",
        "all_recorded_artifact_names",
        "declared_but_unrecorded_artifacts",
        "recorded_but_undeclared_artifacts",
    }
    assert expected_keys.issubset(summary.keys()), (
        f"Missing keys: {expected_keys - summary.keys()}"
    )


def test_build_artifact_summary_counts_are_internally_consistent() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
        "beta": _make_artifact_spec("beta", required=True),
        "gamma": _make_artifact_spec("gamma", required=False),
    })
    run_state = _dict_run_state(
        _dict_record("alpha", "present"),
        _dict_record("beta", "missing"),
    )
    summary = build_artifact_summary(spec, run_state)

    assert summary["declared_artifacts"] == 3
    assert summary["recorded_artifacts"] == 2
    assert summary["required_artifact_count"] == len(summary["required_artifacts"])
    assert len(summary["present_required_artifacts"]) + len(summary["missing_required_artifacts"]) == summary["required_artifact_count"]


# ---------------------------------------------------------------------------
# 10. build_artifact_summary() — required_outputs_present
# ---------------------------------------------------------------------------


def test_build_artifact_summary_required_outputs_present_true_when_all_present() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
        "beta": _make_artifact_spec("beta", required=True),
    })
    run_state = _dict_run_state(
        _dict_record("alpha", "present"),
        _dict_record("beta", "present"),
    )
    summary = build_artifact_summary(spec, run_state)
    assert summary["required_outputs_present"] is True
    assert summary["missing_required_artifacts"] == []


def test_build_artifact_summary_required_outputs_present_false_when_missing() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
        "beta": _make_artifact_spec("beta", required=True),
    })
    run_state = _dict_run_state(_dict_record("alpha", "present"))
    summary = build_artifact_summary(spec, run_state)
    assert summary["required_outputs_present"] is False
    assert "beta" in summary["missing_required_artifacts"]


def test_build_artifact_summary_required_outputs_present_for_full_shell_run(full_pipeline) -> None:
    spec, run_state = full_pipeline
    summary = build_artifact_summary(spec, run_state)
    assert summary["required_outputs_present"] is True


# ---------------------------------------------------------------------------
# 11. Malformed inputs raise ArtifactStructureError
# ---------------------------------------------------------------------------


def test_artifact_exists_raises_on_malformed_dict_missing_artifact_records() -> None:
    with pytest.raises(ArtifactStructureError, match="artifact_records"):
        artifact_exists({"some_key": "some_value"}, "alpha")


def test_artifact_exists_raises_on_non_list_artifact_records() -> None:
    with pytest.raises(ArtifactStructureError):
        artifact_exists({"artifact_records": {"not": "a list"}}, "alpha")


def test_artifact_exists_raises_on_wrong_type_run_state() -> None:
    with pytest.raises(ArtifactStructureError):
        artifact_exists("not a run state", "alpha")  # type: ignore[arg-type]


def test_artifact_structure_error_is_artifact_policy_error() -> None:
    assert issubclass(ArtifactStructureError, ArtifactPolicyError)


# ---------------------------------------------------------------------------
# 12. Declared vs recorded artifact comparison
# ---------------------------------------------------------------------------


def test_build_artifact_summary_declared_but_unrecorded() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
        "beta": _make_artifact_spec("beta", required=True),
        "gamma": _make_artifact_spec("gamma", required=False),
    })
    run_state = _dict_run_state(_dict_record("alpha", "present"))
    summary = build_artifact_summary(spec, run_state)

    assert "beta" in summary["declared_but_unrecorded_artifacts"]
    assert "gamma" in summary["declared_but_unrecorded_artifacts"]
    assert "alpha" not in summary["declared_but_unrecorded_artifacts"]


def test_build_artifact_summary_recorded_but_undeclared() -> None:
    spec = _make_spec({
        "alpha": _make_artifact_spec("alpha", required=True),
    })
    run_state = _dict_run_state(
        _dict_record("alpha", "present"),
        _dict_record("extra_artifact", "present"),
    )
    summary = build_artifact_summary(spec, run_state)

    assert "extra_artifact" in summary["recorded_but_undeclared_artifacts"]
    assert "alpha" not in summary["recorded_but_undeclared_artifacts"]


def test_build_artifact_summary_declared_vs_recorded_consistent_for_shell_run(full_pipeline) -> None:
    """
    After a full V1 shell run, most declared artifacts are recorded.

    rename-invariance-check is SKIP in shell mode (its condition references
    change_impact_report.change_type which is absent in shell payloads).
    Therefore invariance_verdict is declared but not produced at runtime.

    All other declared artifacts should appear in the recorded set, and no
    recorded artifact should be undeclared.
    """
    spec, run_state = full_pipeline
    summary = build_artifact_summary(spec, run_state)

    # Only the conditional artifact from the skipped step is absent.
    assert summary["declared_but_unrecorded_artifacts"] == ["invariance_verdict"], (
        f"Expected only 'invariance_verdict' unrecorded, got: "
        f"{summary['declared_but_unrecorded_artifacts']}"
    )
    assert summary["recorded_but_undeclared_artifacts"] == [], (
        f"Recorded but undeclared: {summary['recorded_but_undeclared_artifacts']}"
    )
    # 19 declared, 18 recorded (1 skipped step = 1 unproduced artifact).
    assert summary["declared_artifacts"] == 19
    assert summary["recorded_artifacts"] == 18


# ---------------------------------------------------------------------------
# 13. get_artifact_record() — public helper
# ---------------------------------------------------------------------------


def test_get_artifact_record_returns_record_dict_for_present_artifact_in_typed_state() -> None:
    record = _make_artifact_record("governance_context", status="present")
    run_state = _make_run_state({"governance_context": record})
    result = get_artifact_record(run_state, "governance_context")
    assert result is not None
    assert result["name"] == "governance_context"
    assert result["status"] == "present"


def test_get_artifact_record_returns_none_for_absent_artifact_in_typed_state() -> None:
    run_state = _make_run_state({})
    result = get_artifact_record(run_state, "governance_context")
    assert result is None


def test_get_artifact_record_returns_record_dict_for_present_artifact_in_dict_payload() -> None:
    run_state = _dict_run_state(_dict_record("governance_context", "present"))
    result = get_artifact_record(run_state, "governance_context")
    assert result is not None
    assert result["name"] == "governance_context"
    assert result["status"] == "present"


def test_get_artifact_record_raises_structure_error_on_malformed_dict_payload() -> None:
    with pytest.raises(ArtifactStructureError):
        get_artifact_record({"some_key": "not_artifact_records"}, "governance_context")
