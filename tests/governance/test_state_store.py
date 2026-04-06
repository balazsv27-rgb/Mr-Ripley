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

from governance.dag_runner.loader import DEFAULT_WORKFLOW_PATH
from governance.dag_runner.state_store import generate_and_write_run_state


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
    assert run_state["loaded_packages"] == 13

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
