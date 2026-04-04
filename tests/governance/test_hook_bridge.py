"""
Tests for governance/dag_runner/hook_bridge.py

Tests use small inline JSON fixtures written to tmp_path.
No full CLI pipeline is required for any test here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance.dag_runner.hook_bridge import (
    HookBridgeError,
    RunStateDecodeError,
    RunStateNotFoundError,
    RunStateStructureError,
    get_final_verdict,
    get_pr_readiness,
    get_recorded_trace_events,
    get_required_artifact,
    has_unresolved_blocks,
    load_run_state,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _minimal_state(**overrides) -> dict:
    """Return a structurally valid minimal run-state dict."""
    base = {
        "workflow_name": "test-workflow",
        "final_verdict": "ready",
        "verdict_status": "ready",
        "blocker_unknown_reference_count": 0,
        "blocker_orphan_count": 0,
        "blocker_structurally_consistent": True,
        "artifact_records": [],
        "execution_trace": [],
    }
    base.update(overrides)
    return base


def _write(tmp_path: Path, data, filename: str = "run_state.json") -> Path:
    """Write data as JSON to tmp_path and return the path."""
    p = tmp_path / filename
    if isinstance(data, str):
        p.write_text(data, encoding="utf-8")
    else:
        p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _artifact_record(name: str, producer: str = "some-step", status: str = "present", **payload_extra) -> dict:
    payload = {"produced_by": producer}
    payload.update(payload_extra)
    return {"name": name, "producer_step": producer, "status": status, "payload": payload}


# ---------------------------------------------------------------------------
# 1. load_run_state — success
# ---------------------------------------------------------------------------


def test_load_run_state_success(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state())
    state = load_run_state(p)
    assert state["workflow_name"] == "test-workflow"
    assert state["final_verdict"] == "ready"


# ---------------------------------------------------------------------------
# 2. load_run_state — missing file raises RunStateNotFoundError
# ---------------------------------------------------------------------------


def test_load_run_state_missing_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "does_not_exist.json"
    with pytest.raises(RunStateNotFoundError):
        load_run_state(p)


# ---------------------------------------------------------------------------
# 3. load_run_state — invalid JSON raises RunStateDecodeError
# ---------------------------------------------------------------------------


def test_load_run_state_invalid_json_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "{ this is not valid json }")
    with pytest.raises(RunStateDecodeError):
        load_run_state(p)


# ---------------------------------------------------------------------------
# 4. load_run_state — malformed payload raises RunStateStructureError
# ---------------------------------------------------------------------------


def test_load_run_state_missing_required_key_raises(tmp_path: Path) -> None:
    # Remove 'artifact_records' — a required structural key
    bad = _minimal_state()
    del bad["artifact_records"]
    p = _write(tmp_path, bad)
    with pytest.raises(RunStateStructureError, match="artifact_records"):
        load_run_state(p)


def test_load_run_state_no_verdict_key_raises(tmp_path: Path) -> None:
    bad = _minimal_state()
    del bad["final_verdict"]
    del bad["verdict_status"]
    p = _write(tmp_path, bad)
    with pytest.raises(RunStateStructureError, match="verdict"):
        load_run_state(p)


def test_load_run_state_non_list_artifact_records_raises(tmp_path: Path) -> None:
    bad = _minimal_state(artifact_records={"not": "a list"})
    p = _write(tmp_path, bad)
    with pytest.raises(RunStateStructureError, match="artifact_records"):
        load_run_state(p)


def test_load_run_state_non_list_execution_trace_raises(tmp_path: Path) -> None:
    bad = _minimal_state(execution_trace="not a list")
    p = _write(tmp_path, bad)
    with pytest.raises(RunStateStructureError, match="execution_trace"):
        load_run_state(p)


def test_load_run_state_json_root_not_dict_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "[1, 2, 3]")
    with pytest.raises(RunStateStructureError):
        load_run_state(p)


# ---------------------------------------------------------------------------
# 5. get_final_verdict — returns expected status
# ---------------------------------------------------------------------------


def test_get_final_verdict_returns_final_verdict_first(tmp_path: Path) -> None:
    # 'final_verdict' should take priority over 'verdict_status'
    p = _write(tmp_path, _minimal_state(final_verdict="ready", verdict_status="blocked"))
    assert get_final_verdict(p) == "ready"


def test_get_final_verdict_falls_back_to_verdict_status(tmp_path: Path) -> None:
    state = _minimal_state()
    state["final_verdict"] = None
    p = _write(tmp_path, state)
    assert get_final_verdict(p) == "ready"


def test_get_final_verdict_blocked(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state(final_verdict="blocked", verdict_status="blocked"))
    assert get_final_verdict(p) == "blocked"


def test_get_final_verdict_returns_none_when_both_null(tmp_path: Path) -> None:
    state = _minimal_state()
    state["final_verdict"] = None
    state["verdict_status"] = None
    p = _write(tmp_path, state)
    assert get_final_verdict(p) is None


# ---------------------------------------------------------------------------
# 6. get_required_artifact — returns artifact when present
# ---------------------------------------------------------------------------


def test_get_required_artifact_returns_record(tmp_path: Path) -> None:
    rec = _artifact_record("role_citation_verdict", "route-claims-by-role")
    p = _write(tmp_path, _minimal_state(artifact_records=[rec]))
    result = get_required_artifact("role_citation_verdict", p)
    assert result is not None
    assert result["name"] == "role_citation_verdict"
    assert result["producer_step"] == "route-claims-by-role"
    assert result["status"] == "present"


# ---------------------------------------------------------------------------
# 7. get_required_artifact — returns None for absent artifact
# ---------------------------------------------------------------------------


def test_get_required_artifact_returns_none_when_absent(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state(artifact_records=[]))
    assert get_required_artifact("missing_artifact", p) is None


def test_get_required_artifact_returns_none_when_name_not_in_list(tmp_path: Path) -> None:
    rec = _artifact_record("governance_context", "load-context")
    p = _write(tmp_path, _minimal_state(artifact_records=[rec]))
    assert get_required_artifact("claim_classification_map", p) is None


# ---------------------------------------------------------------------------
# 8. get_recorded_trace_events — returns trace list
# ---------------------------------------------------------------------------


def test_get_recorded_trace_events_returns_list(tmp_path: Path) -> None:
    events = [
        {"timestamp": "2024-01-01T00:00:00", "node_name": "__run__", "event_type": "run_started", "detail": {}},
        {"timestamp": "2024-01-01T00:00:01", "node_name": "load-context", "event_type": "step_started", "detail": {}},
    ]
    p = _write(tmp_path, _minimal_state(execution_trace=events))
    result = get_recorded_trace_events(p)
    assert len(result) == 2
    assert result[0]["event_type"] == "run_started"


def test_get_recorded_trace_events_returns_empty_list_when_no_events(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state(execution_trace=[]))
    assert get_recorded_trace_events(p) == []


def test_get_recorded_trace_events_returns_copy(tmp_path: Path) -> None:
    events = [{"timestamp": "t", "node_name": "n", "event_type": "e", "detail": {}}]
    p = _write(tmp_path, _minimal_state(execution_trace=events))
    result = get_recorded_trace_events(p)
    result.append({"extra": "item"})  # mutating return value should not affect next call
    assert len(get_recorded_trace_events(p)) == 1


# ---------------------------------------------------------------------------
# 9. get_pr_readiness — resolves from artifact record when not top-level
# ---------------------------------------------------------------------------


def test_get_pr_readiness_resolves_from_artifact_when_no_top_level(tmp_path: Path) -> None:
    rec = _artifact_record("pr_readiness_verdict", "pre-pr-governance-readiness")
    p = _write(tmp_path, _minimal_state(artifact_records=[rec]))
    result = get_pr_readiness(p)
    assert result is not None
    assert result["name"] == "pr_readiness_verdict"


def test_get_pr_readiness_prefers_top_level_over_artifact(tmp_path: Path) -> None:
    top_level_pr = {"all_checks_passed": True, "custom": "data"}
    rec = _artifact_record("pr_readiness_verdict", "pre-pr-governance-readiness")
    state = _minimal_state(artifact_records=[rec])
    state["pr_readiness"] = top_level_pr
    p = _write(tmp_path, state)
    result = get_pr_readiness(p)
    # Top-level dict should be returned
    assert result == top_level_pr


def test_get_pr_readiness_returns_none_when_absent(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state(artifact_records=[]))
    assert get_pr_readiness(p) is None


# ---------------------------------------------------------------------------
# 10. has_unresolved_blocks — True when unknown references exist
# ---------------------------------------------------------------------------


def test_has_unresolved_blocks_true_when_unknown_references(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state(
        blocker_unknown_reference_count=3,
        final_verdict="blocked",
    ))
    assert has_unresolved_blocks(p) is True


def test_has_unresolved_blocks_true_when_verdict_blocked(tmp_path: Path) -> None:
    # Zero unknown references but verdict is blocked
    p = _write(tmp_path, _minimal_state(
        blocker_unknown_reference_count=0,
        final_verdict="blocked",
    ))
    assert has_unresolved_blocks(p) is True


# ---------------------------------------------------------------------------
# 11. has_unresolved_blocks — False when blocker section is present and clean
# ---------------------------------------------------------------------------


def test_has_unresolved_blocks_false_when_clean(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state(
        blocker_unknown_reference_count=0,
        blocker_orphan_count=0,
        blocker_structurally_consistent=True,
        final_verdict="ready",
    ))
    assert has_unresolved_blocks(p) is False


def test_has_unresolved_blocks_false_when_review_only_and_no_unknowns(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state(
        blocker_unknown_reference_count=0,
        final_verdict="review_only",
    ))
    assert has_unresolved_blocks(p) is False


# ---------------------------------------------------------------------------
# 12. has_unresolved_blocks — fails closed when blocker structure absent
# ---------------------------------------------------------------------------


def test_has_unresolved_blocks_fails_closed_when_no_blocker_structure_or_verdict(
    tmp_path: Path,
) -> None:
    # Manually craft a state that passes minimal structure validation
    # but has no blocker fields and no verdict fields — not possible after
    # _validate_minimal_structure (which requires verdict), so we test the
    # extraction helper directly instead.
    from governance.dag_runner.hook_bridge import (
        RunStateStructureError,
        _extract_blocking_conditions,
    )

    no_blocker_no_verdict = {
        "workflow_name": "test",
        "artifact_records": [],
        "execution_trace": [],
        # deliberately no blocker_* keys and no verdict keys
    }
    with pytest.raises(RunStateStructureError, match="blocker"):
        _extract_blocking_conditions(no_blocker_no_verdict)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_all_bridge_exceptions_are_hook_bridge_error() -> None:
    assert issubclass(RunStateNotFoundError, HookBridgeError)
    assert issubclass(RunStateDecodeError, HookBridgeError)
    assert issubclass(RunStateStructureError, HookBridgeError)


# ---------------------------------------------------------------------------
# Path handling — accepts str and Path
# ---------------------------------------------------------------------------


def test_load_accepts_str_path(tmp_path: Path) -> None:
    p = _write(tmp_path, _minimal_state())
    state = load_run_state(str(p))
    assert state["workflow_name"] == "test-workflow"
