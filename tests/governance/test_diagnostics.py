"""Tests for governance.dag_runner.diagnostics."""
from __future__ import annotations

import pytest

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.diagnostics import (
    build_diagnostic_report,
    diagnostic_report_to_dict,
)
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.models import ExecutionConfig
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.validator import validate_or_raise


@pytest.fixture(scope="module")
def pipeline():
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)
    return spec, plan


def test_diagnostic_report_from_v1_run(pipeline) -> None:
    spec, plan = pipeline
    result = execute_plan(spec, plan, verdict_status="ready")
    report = build_diagnostic_report(spec, plan, result.run_state)
    assert report.total_steps == 18
    assert report.executed_steps + report.skipped_steps == 18


def test_diagnostic_report_from_v2_run(pipeline) -> None:
    spec, plan = pipeline
    config = ExecutionConfig(mode="agent_execution", request_text="test")
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, verdict_status="ready", config=config, backend=backend)
    report = build_diagnostic_report(spec, plan, result.run_state)
    assert report.total_steps == 18
    assert report.executed_steps >= 17


def test_critical_path_is_non_empty(pipeline) -> None:
    spec, plan = pipeline
    result = execute_plan(spec, plan, verdict_status="ready")
    report = build_diagnostic_report(spec, plan, result.run_state)
    assert len(report.critical_path) > 0
    # Critical path should start with load-context
    assert report.critical_path[0] == "load-context"


def test_diagnostic_report_serializable(pipeline) -> None:
    spec, plan = pipeline
    result = execute_plan(spec, plan, verdict_status="ready")
    report = build_diagnostic_report(spec, plan, result.run_state)
    d = diagnostic_report_to_dict(report)
    assert isinstance(d, dict)
    assert d["total_steps"] == 18
    assert isinstance(d["steps"], list)
    assert len(d["steps"]) == 18


def test_step_diagnostics_have_correct_fields(pipeline) -> None:
    spec, plan = pipeline
    result = execute_plan(spec, plan, verdict_status="ready")
    report = build_diagnostic_report(spec, plan, result.run_state)
    for diag in report.step_diagnostics:
        assert diag.step_id
        assert diag.status in ("PASS", "SKIP", "FAIL")
        assert diag.component_kind
