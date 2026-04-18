"""Tests for governance.dag_runner.drift_detector."""
from __future__ import annotations

from pathlib import Path

import pytest

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.drift_detector import (
    DriftResult,
    detect_drift,
)
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.models import (
    AgentSpec,
    AssembledWorkflowSpec,
    ManifestSpec,
    WorkflowStep,
)
from governance.dag_runner.validator import validate_or_raise


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def spec():
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    return spec


# ── real workflow should be clean ──


def test_real_workflow_is_clean(spec) -> None:
    result = detect_drift(spec, _REPO_ROOT)
    if not result.is_clean:
        msg = "\n".join(f"  - [{d.severity}] {d.message}" for d in result.all_issues)
        pytest.fail(f"Expected clean drift result but found issues:\n{msg}")


def test_real_workflow_no_critical_drifts(spec) -> None:
    result = detect_drift(spec, _REPO_ROOT)
    assert result.critical_drifts == []


# ── synthetic drift checks ──


def _make_spec(
    agents: dict | None = None,
    steps: dict | None = None,
    skills: dict | None = None,
) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test"),
        agents=agents or {},
        workflow_steps=steps or {},
        skills=skills or {},
    )


def test_missing_agent_file_is_critical() -> None:
    spec = _make_spec(
        agents={"nonexistent-agent": AgentSpec(name="nonexistent-agent")},
    )
    result = detect_drift(spec, _REPO_ROOT)
    assert not result.is_clean
    assert any(
        d.check == "agent_file_existence" and d.severity == "critical"
        for d in result.critical_drifts
    )


def test_missing_skill_file_is_critical() -> None:
    from governance.dag_runner.models import SkillSpec
    spec = _make_spec(
        skills={"nonexistent-skill": SkillSpec(name="nonexistent-skill")},
    )
    result = detect_drift(spec, _REPO_ROOT)
    assert not result.is_clean
    assert any(
        d.check == "skill_file_existence" and d.severity == "critical"
        for d in result.critical_drifts
    )


def test_agent_step_binding_mismatch_is_critical() -> None:
    spec = _make_spec(
        agents={
            "test-agent": AgentSpec(
                name="test-agent",
                workflow_steps=["step-a"],
            ),
        },
        steps={
            "step-a": WorkflowStep(
                name="step-a",
                component="skill:test",
                raw={"agent_binding": "different-agent"},
            ),
        },
    )
    result = detect_drift(spec, _REPO_ROOT)
    assert not result.is_clean
    assert any(d.check == "agent_step_binding_mismatch" for d in result.critical_drifts)


def test_artifact_producer_mismatch_is_critical() -> None:
    spec = _make_spec(
        agents={
            "test-agent": AgentSpec(
                name="test-agent",
                workflow_steps=["step-a"],
                produces=["artifact_x"],
            ),
        },
        steps={
            "step-a": WorkflowStep(
                name="step-a",
                component="skill:test",
                outputs=["artifact_y"],
                raw={"agent_binding": "test-agent"},
            ),
        },
    )
    result = detect_drift(spec, _REPO_ROOT)
    assert not result.is_clean
    assert any(d.check == "artifact_producer_consistency" for d in result.critical_drifts)


def test_informational_drifts_do_not_block() -> None:
    result = DriftResult(
        is_clean=True,
        critical_drifts=[],
        informational_drifts=[],
    )
    assert result.is_clean
