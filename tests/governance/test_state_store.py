"""
Tests for governance/dag_runner/state_store.py

Verifies the persisted JSON contract written by generate_and_write_run_state().
All tests read the same state file generated once per module via a shared fixture,
so the expensive pipeline runs exactly once.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from datetime import datetime

from governance.dag_runner.loader import DEFAULT_WORKFLOW_PATH
from governance.dag_runner.state_store import (
    StateStoreError,
    generate_and_write_run_state,
    load_run_state_from_path,
)


# ---------------------------------------------------------------------------
# Shared module-scoped fixture — runs the pipeline once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def state_path(tmp_path_factory) -> Path:
    """Generate governance run state to a temp file once for the whole module."""
    tmp = tmp_path_factory.mktemp("state_store")
    output = tmp / "governance_run_state.json"
    generate_and_write_run_state(DEFAULT_WORKFLOW_PATH, output_path=output)
    return output


@pytest.fixture(scope="module")
def run_state(state_path: Path) -> dict:
    """Parse the written JSON once and share it across all tests."""
    return json.loads(state_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. File is written and is valid JSON
# ---------------------------------------------------------------------------


def test_generate_and_write_run_state_writes_valid_json(state_path: Path) -> None:
    assert state_path.exists(), "Run-state file was not created."
    assert state_path.is_file()

    raw = state_path.read_text(encoding="utf-8")
    payload = json.loads(raw)  # raises if not valid JSON

    assert isinstance(payload, dict), "Top-level JSON structure must be a dict."
    assert payload, "Written run-state JSON must not be empty."


# ---------------------------------------------------------------------------
# 2. Verdict fields
# ---------------------------------------------------------------------------


def test_run_state_contains_verdict_fields(run_state: dict) -> None:
    assert "verdict_status" in run_state
    assert "verdict_reasons" in run_state
    assert "final_verdict" in run_state

    assert run_state["verdict_status"] == "ready"
    assert run_state["final_verdict"] == "ready"

    reasons = run_state["verdict_reasons"]
    assert isinstance(reasons, list)
    assert len(reasons) >= 1
    assert any("passed" in r.lower() or "consistent" in r.lower() for r in reasons), (
        "Expected at least one reason describing a passing/consistent state."
    )


# ---------------------------------------------------------------------------
# 3. Execution trace
# ---------------------------------------------------------------------------


def test_run_state_contains_execution_trace(run_state: dict) -> None:
    assert "execution_trace" in run_state
    trace = run_state["execution_trace"]
    assert isinstance(trace, list)
    assert len(trace) > 0, "Execution trace must contain at least one event."

    # Verify the count field is present and matches
    assert "recorded_trace_events" in run_state
    assert run_state["recorded_trace_events"] == len(trace)

    # Verify shape of individual trace events
    first = trace[0]
    assert "timestamp" in first
    assert "node_name" in first
    assert "event_type" in first
    assert "detail" in first

    # A completed run must have a run_started event
    event_types = [e["event_type"] for e in trace]
    assert "run_started" in event_types
    assert "run_completed" in event_types


# ---------------------------------------------------------------------------
# 4. Node results
# ---------------------------------------------------------------------------


def test_run_state_contains_node_results(run_state: dict) -> None:
    assert "node_results" in run_state
    nodes = run_state["node_results"]
    assert isinstance(nodes, list)
    assert len(nodes) > 0, "Node results must contain at least one entry."

    # Count field must be present and consistent
    assert "recorded_node_results" in run_state
    assert run_state["recorded_node_results"] == len(nodes)

    # Verify shape of individual node result entries
    first = nodes[0]
    assert "node_name" in first
    assert "node_type" in first
    assert "status" in first
    assert "summary" in first
    assert "evidence" in first
    assert "produced_artifacts" in first
    assert "triggered_blocks" in first
    assert "inference_used" in first

    # All recorded node statuses must be valid
    valid_statuses = {"PASS", "WARN", "FAIL", "SKIP"}
    for node in nodes:
        assert node["status"] in valid_statuses, (
            f"Node '{node.get('node_name')}' has unexpected status '{node['status']}'."
        )

    # The first planned step (load-context) must appear
    node_names = {n["node_name"] for n in nodes}
    assert "load-context" in node_names
    assert "pre-pr-governance-readiness" in node_names


# ---------------------------------------------------------------------------
# 5. Artifact records
# ---------------------------------------------------------------------------


def test_run_state_contains_artifact_records(run_state: dict) -> None:
    assert "artifact_records" in run_state
    records = run_state["artifact_records"]
    assert isinstance(records, list)
    assert len(records) > 0, "Artifact records must contain at least one entry."

    # Count field must be present and consistent
    assert "recorded_artifacts" in run_state
    assert run_state["recorded_artifacts"] == len(records)

    # Verify shape of individual artifact records
    first = records[0]
    assert "name" in first
    assert "producer_step" in first
    assert "status" in first
    assert "payload" in first
    assert isinstance(first["payload"], dict)

    # All artifact statuses must be valid
    valid_statuses = {"present", "missing", "blocked", "stale"}
    for rec in records:
        assert rec["status"] in valid_statuses, (
            f"Artifact '{rec.get('name')}' has unexpected status '{rec['status']}'."
        )

    # A known first-step artifact must be present
    artifact_names = {r["name"] for r in records}
    assert "governance_context" in artifact_names, (
        "'governance_context' artifact produced by load-context must be recorded."
    )


# ---------------------------------------------------------------------------
# 6. Run and workflow metadata
# ---------------------------------------------------------------------------


def test_run_state_contains_run_metadata(run_state: dict) -> None:
    # Workflow identity
    assert "workflow_name" in run_state
    assert run_state["workflow_name"] == "mr-ripley-governance-orchestration"

    assert "workflow_file" in run_state
    assert run_state["workflow_file"]  # non-empty string

    assert "loaded_packages" in run_state
    assert run_state["loaded_packages"] == 14

    # Run identity
    assert "run_id" in run_state
    assert run_state["run_id"], "run_id must be a non-empty string."

    assert "started_at" in run_state
    assert run_state["started_at"], "started_at must be a non-empty string."

    # Workflow shape metadata
    assert run_state["workflow_steps"] == 18
    assert run_state["skills"] == 13
    assert run_state["artifacts"] == 19
    assert run_state["stage_gates"] == 4
    assert run_state["subagents"] == 8

    # Validation metadata
    assert "validation_passed" in run_state
    assert run_state["validation_passed"] is True
    assert run_state["validation_issue_count"] == 0
    assert run_state["validation_issues"] == []

    # Plan metadata
    assert "planned_steps" in run_state
    assert run_state["planned_steps"] == 18


# ---------------------------------------------------------------------------
# 7. Blocker summary fields
# ---------------------------------------------------------------------------


def test_run_state_contains_blocker_summary_fields(run_state: dict) -> None:
    assert "blocker_declared_count" in run_state
    assert "blocker_referenced_count" in run_state
    assert "blocker_orphan_count" in run_state
    assert "blocker_unknown_reference_count" in run_state
    assert "blocker_structurally_consistent" in run_state

    assert run_state["blocker_declared_count"] == 12
    assert run_state["blocker_referenced_count"] == 17
    assert run_state["blocker_orphan_count"] == 0
    assert run_state["blocker_unknown_reference_count"] == 0
    assert run_state["blocker_structurally_consistent"] is True

    # Blocking conditions count in workflow shape should match declared count
    assert run_state["blocking_conditions"] == 12


# ---------------------------------------------------------------------------
# 8. Count fields are internally consistent
# ---------------------------------------------------------------------------


def test_run_state_count_fields_match_payload_lengths(run_state: dict) -> None:
    # Trace events
    assert run_state["recorded_trace_events"] == len(run_state["execution_trace"])

    # Node results
    assert run_state["recorded_node_results"] == len(run_state["node_results"])

    # Artifact records
    assert run_state["recorded_artifacts"] == len(run_state["artifact_records"])

    # recorded_artifacts must match the actual artifact_records list length.
    # Note: run_state["artifacts"] is the *declared* spec count (19), which may
    # differ from recorded_artifacts (18) when conditional steps are skipped.
    assert run_state["recorded_artifacts"] == len(run_state["artifact_records"])

    # Planned steps equals executed node results
    assert run_state["planned_steps"] == run_state["recorded_node_results"]

    # workflow_steps count matches planned steps
    assert run_state["workflow_steps"] == run_state["planned_steps"]


# ---------------------------------------------------------------------------
# 9. Compact top-level readiness fields (Phase 3 hook-facing contract)
# ---------------------------------------------------------------------------


def test_run_state_contains_compact_readiness_fields(run_state: dict) -> None:
    """All five compact readiness fields must be present in the persisted JSON."""
    assert "workflow_completed" in run_state
    assert "required_outputs_present" in run_state
    assert "unresolved_blocking_conditions" in run_state
    assert "fatal_unresolved_block_count" in run_state
    assert "pr_readiness" in run_state


def test_run_state_compact_readiness_types(run_state: dict) -> None:
    """Compact readiness fields must have the correct types."""
    assert isinstance(run_state["workflow_completed"], bool)
    assert isinstance(run_state["required_outputs_present"], bool)
    assert isinstance(run_state["unresolved_blocking_conditions"], list)
    assert isinstance(run_state["fatal_unresolved_block_count"], int)
    assert isinstance(run_state["pr_readiness"], str)


def test_run_state_clean_workflow_readiness_values(run_state: dict) -> None:
    """Current clean real workflow must persist a clean ready state."""
    assert run_state["workflow_completed"] is True
    assert run_state["required_outputs_present"] is True
    assert run_state["fatal_unresolved_block_count"] == 0
    assert run_state["pr_readiness"] == "ready"
    assert run_state["unresolved_blocking_conditions"] == []


def test_run_state_readiness_consistent_with_detailed_content(run_state: dict) -> None:
    """Compact readiness fields must be internally consistent with detailed runtime content."""
    # workflow_completed must align with run_completed in execution_trace
    event_types = [e["event_type"] for e in run_state["execution_trace"]]
    assert run_state["workflow_completed"] == ("run_completed" in event_types)

    # fatal_unresolved_block_count <= len(unresolved_blocking_conditions)
    assert run_state["fatal_unresolved_block_count"] <= len(
        run_state["unresolved_blocking_conditions"]
    )

    # pr_readiness must be one of the three allowed values
    assert run_state["pr_readiness"] in {"ready", "review_only", "blocked"}

    # pr_readiness "ready" requires workflow_completed and required_outputs_present
    if run_state["pr_readiness"] == "ready":
        assert run_state["workflow_completed"] is True
        assert run_state["required_outputs_present"] is True
        assert run_state["fatal_unresolved_block_count"] == 0


def test_run_state_existing_detailed_fields_still_present(run_state: dict) -> None:
    """Backward-compatibility: all existing detailed fields must remain."""
    # Structural verdict fields
    assert "verdict_status" in run_state
    assert "verdict_reasons" in run_state
    assert "final_verdict" in run_state

    # Execution detail
    assert "execution_trace" in run_state
    assert "node_results" in run_state
    assert "artifact_records" in run_state

    # Blocker structural summary
    assert "blocker_declared_count" in run_state
    assert "blocker_referenced_count" in run_state
    assert "blocker_orphan_count" in run_state
    assert "blocker_unknown_reference_count" in run_state
    assert "blocker_structurally_consistent" in run_state

    # Run metadata
    assert "workflow_name" in run_state
    assert "run_id" in run_state
    assert "started_at" in run_state


# ---------------------------------------------------------------------------
# load_run_state_from_path — R1-B round-trip and error tests
# ---------------------------------------------------------------------------


def test_load_run_state_from_path_round_trip(state_path: Path) -> None:
    """Write → load → verify GovernanceRunState fields match stored data."""
    reloaded = load_run_state_from_path(state_path)

    assert reloaded.run_id, "run_id should be non-empty"
    assert isinstance(reloaded.started_at, datetime)
    assert reloaded.current_phase is not None

    # Node results round-trip
    assert len(reloaded.node_results) > 0
    for key, nr in reloaded.node_results.items():
        assert key == nr.node_name, "dict key must match node_name"
        assert nr.status in ("PASS", "WARN", "FAIL", "SKIP")

    # Artifacts round-trip
    assert len(reloaded.artifacts) > 0
    for key, ar in reloaded.artifacts.items():
        assert key == ar.name, "dict key must match artifact name"
        assert ar.status in ("present", "missing", "blocked", "stale")

    # Execution trace round-trip
    assert len(reloaded.execution_trace) > 0
    event_types = [e.event_type for e in reloaded.execution_trace]
    assert "run_started" in event_types
    assert "run_completed" in event_types
    for event in reloaded.execution_trace:
        assert isinstance(event.timestamp, datetime)

    # Final verdict
    assert reloaded.final_verdict is not None


def test_load_run_state_from_path_defaults_latency_fields(state_path: Path) -> None:
    """V1 stored state lacks latency_ms/token_count — defaults to zero."""
    reloaded = load_run_state_from_path(state_path)
    for nr in reloaded.node_results.values():
        assert nr.latency_ms == 0.0
        assert nr.token_count == 0


def test_load_run_state_from_path_corrupt_json(tmp_path: Path) -> None:
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(StateStoreError):
        load_run_state_from_path(corrupt_file)


def test_load_run_state_from_path_missing_file(tmp_path: Path) -> None:
    with pytest.raises(StateStoreError):
        load_run_state_from_path(tmp_path / "nonexistent.json")


def test_load_run_state_from_path_missing_fields(tmp_path: Path) -> None:
    """Missing required fields in node_results should raise StateStoreError."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(
        '{"node_results": [{"status": "PASS"}]}',
        encoding="utf-8",
    )
    with pytest.raises(StateStoreError):
        load_run_state_from_path(bad_file)
