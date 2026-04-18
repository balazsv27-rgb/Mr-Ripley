"""Tests for V2 execution modes: dry-run, graph, JSON, continuation."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.blockers import analyze_blockers
from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.execution_modes import (
    build_config_from_args,
    validate_continuation,
)
from governance.dag_runner.executor import execute_plan, _parse_component_kind
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.models import (
    ArtifactRecord,
    BlockingEvent,
    ExecutionConfig,
    GovernanceRunState,
)
from governance.dag_runner.planner import build_execution_plan
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
    return spec, plan, verdict


# ── config builder ──


def test_build_config_defaults() -> None:
    config = build_config_from_args()
    assert config.mode == "shell_v1"
    assert config.json_output is False


def test_build_config_dry_run() -> None:
    config = build_config_from_args(dry_run=True)
    assert config.mode == "dry_run"


def test_build_config_graph_overrides_mode() -> None:
    config = build_config_from_args(graph=True, mode="agent_execution")
    assert config.mode == "graph_only"


def test_build_config_agent_execution() -> None:
    config = build_config_from_args(mode="agent_execution")
    assert config.mode == "agent_execution"


# ── component-kind parsing ──


def test_parse_component_skill() -> None:
    kind, name = _parse_component_kind("skill:doc-truth-classification")
    assert kind == "skill"
    assert name == "doc-truth-classification"


def test_parse_component_constitution() -> None:
    kind, name = _parse_component_kind("constitution")
    assert kind == "constitution"
    assert name is None


def test_parse_component_stage_gates() -> None:
    kind, name = _parse_component_kind("stage_gates")
    assert kind == "stage_gates"
    assert name is None


# ── dry-run mode ──


def test_dry_run_produces_no_real_artifacts(pipeline) -> None:
    spec, plan, verdict = pipeline
    config = ExecutionConfig(mode="dry_run")
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, verdict_status=verdict.status, config=config, backend=backend)
    # In dry-run, no artifacts should be materialized
    for nr in result.run_state.node_results.values():
        if nr.status == "PASS":
            assert "dry_run=True" in nr.evidence or nr.status == "SKIP"


def test_dry_run_all_steps_pass(pipeline) -> None:
    spec, plan, verdict = pipeline
    config = ExecutionConfig(mode="dry_run")
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, verdict_status=verdict.status, config=config, backend=backend)
    pass_count = sum(1 for nr in result.run_state.node_results.values() if nr.status == "PASS")
    skip_count = sum(1 for nr in result.run_state.node_results.values() if nr.status == "SKIP")
    assert pass_count + skip_count == len(result.run_state.node_results)


# ── agent_execution mode ──


def test_agent_execution_produces_artifacts(pipeline) -> None:
    spec, plan, verdict = pipeline
    config = ExecutionConfig(mode="agent_execution")
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, verdict_status=verdict.status, config=config, backend=backend)
    # Should have artifacts for non-skipped steps
    assert len(result.run_state.artifacts) >= 17  # 18 steps minus skipped


def test_agent_execution_records_component_kind_in_trace(pipeline) -> None:
    spec, plan, verdict = pipeline
    config = ExecutionConfig(mode="agent_execution")
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, verdict_status=verdict.status, config=config, backend=backend)
    completed_events = [
        e for e in result.run_state.execution_trace
        if e.event_type == "step_completed"
    ]
    for event in completed_events:
        assert "component_kind" in event.detail


# ── V1 shell mode unchanged ──


def test_v1_shell_mode_unchanged(pipeline) -> None:
    spec, plan, verdict = pipeline
    result = execute_plan(spec, plan, verdict_status=verdict.status)
    assert result.run_state.final_verdict == verdict.status
    assert len(result.run_state.node_results) == 18


# ── continuation validation ──


def _make_prior_state(plan, spec) -> GovernanceRunState:
    """Build a valid prior state from a V1 shell run."""
    config = ExecutionConfig(mode="shell_v1")
    result = execute_plan(spec, plan, verdict_status="ready")
    return result.run_state


def test_continuation_valid(pipeline) -> None:
    spec, plan, verdict = pipeline
    prior = _make_prior_state(plan, spec)
    failures = validate_continuation(prior, spec, plan, "deep-audit")
    assert failures == []


def test_continuation_fails_on_unknown_step(pipeline) -> None:
    spec, plan, verdict = pipeline
    prior = _make_prior_state(plan, spec)
    failures = validate_continuation(prior, spec, plan, "nonexistent-step")
    assert any("not found" in f for f in failures)


def test_continuation_fails_on_version_mismatch(pipeline) -> None:
    spec, plan, verdict = pipeline
    prior = _make_prior_state(plan, spec)
    # Tamper with version
    from governance.dag_runner.models import ManifestSpec
    tampered_spec = AssembledWorkflowSpec(
        manifest=ManifestSpec(
            workflow_name=spec.manifest.workflow_name,
            workflow_version="99.99.99",
        ),
        workflow_steps=spec.workflow_steps,
        artifacts=spec.artifacts,
        blocking_conditions=spec.blocking_conditions,
    )
    # Prior state has the original version
    failures = validate_continuation(prior, tampered_spec, plan, "deep-audit")
    assert any("version mismatch" in f.lower() for f in failures)


from governance.dag_runner.models import AssembledWorkflowSpec
