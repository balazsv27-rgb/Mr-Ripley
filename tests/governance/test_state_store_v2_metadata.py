"""Tests for R3-C: StoredNodeResult V2 metadata persistence.

Verifies that latency_ms and token_count are preserved in persisted state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.blockers import analyze_blockers
from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.models import ExecutionConfig
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.state_store import (
    build_stored_run_state,
    load_run_state,
    write_run_state,
)
from governance.dag_runner.validator import validate_or_raise, validate_workflow_spec
from governance.dag_runner.verdict import compute_verdict


@pytest.fixture(scope="module")
def pipeline():
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    validation = validate_workflow_spec(spec)
    plan = build_execution_plan(spec)
    blocker_summary = analyze_blockers(spec, plan)
    verdict = compute_verdict(validation, blocker_summary)
    return loaded, spec, validation, plan, blocker_summary, verdict


class TestStoredNodeResultV2Metadata:
    """StoredNodeResult persists latency_ms and token_count."""

    def test_v2_metadata_in_persisted_json(
        self, pipeline, tmp_path: Path,
    ) -> None:
        loaded, spec, validation, plan, blocker_summary, verdict = pipeline
        config = ExecutionConfig(mode="agent_execution")
        backend = MockExecutionBackend()

        execution_result = execute_plan(
            spec, plan, verdict_status=verdict.status,
            config=config, backend=backend,
        )

        state = build_stored_run_state(
            loaded=loaded, spec=spec,
            validation_result=validation, plan=plan,
            blocker_summary=blocker_summary, verdict=verdict,
            execution_result=execution_result,
        )
        out_path = tmp_path / "state.json"
        write_run_state(state, output_path=out_path)

        raw = load_run_state(out_path)
        for nr in raw["node_results"]:
            assert "latency_ms" in nr, f"{nr['node_name']} missing latency_ms"
            assert "token_count" in nr, f"{nr['node_name']} missing token_count"
            assert isinstance(nr["latency_ms"], (int, float))
            assert isinstance(nr["token_count"], int)

    def test_v1_state_without_metadata_loads(self, tmp_path: Path) -> None:
        """V1-era state file without latency_ms/token_count still loads."""
        v1_state = {
            "run_id": "old-run",
            "started_at": "2025-01-01T00:00:00+00:00",
            "workflow_name": "test",
            "final_verdict": "ready",
            "node_results": [
                {
                    "node_name": "step-a",
                    "node_type": "constitution",
                    "status": "PASS",
                    "summary": "old step",
                    # No latency_ms or token_count
                },
            ],
            "artifact_records": [],
            "execution_trace": [],
            "unresolved_blocking_conditions": [],
        }
        path = tmp_path / "v1_state.json"
        path.write_text(json.dumps(v1_state))

        from governance.dag_runner.state_store import load_run_state_from_path
        rs = load_run_state_from_path(path)

        assert rs.node_results["step-a"].latency_ms == 0.0
        assert rs.node_results["step-a"].token_count == 0
