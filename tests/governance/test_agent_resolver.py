"""Tests for governance.dag_runner.agent_resolver."""
from __future__ import annotations

from pathlib import Path

import pytest

from governance.dag_runner.agent_resolver import (
    AgentResolverError,
    load_agent_file,
    resolve_agent,
    resolve_skill_content,
)
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.models import AgentSpec, WorkflowStep


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def spec():
    loaded = load_workflow_packages()
    return assemble_workflow_spec(loaded)


def test_resolve_agent_for_bound_step(spec) -> None:
    step = spec.workflow_steps["classify-claims"]
    agent = resolve_agent(step, spec)
    assert agent is not None
    assert agent.name == "claim-classification-agent"
    assert agent.model == "opus"


def test_resolve_agent_returns_none_for_unbound_step(spec) -> None:
    step = spec.workflow_steps["load-context"]
    agent = resolve_agent(step, spec)
    assert agent is None


def test_resolve_agent_raises_for_unknown_binding() -> None:
    step = WorkflowStep(
        name="test-step",
        component="skill:test",
        raw={"agent_binding": "nonexistent-agent"},
    )
    from governance.dag_runner.models import AssembledWorkflowSpec, ManifestSpec
    empty_spec = AssembledWorkflowSpec(manifest=ManifestSpec(workflow_name="test"))
    with pytest.raises(AgentResolverError, match="not found"):
        resolve_agent(step, empty_spec)


def test_load_agent_file_exists() -> None:
    content = load_agent_file("claim-classification-agent", _REPO_ROOT)
    assert len(content) > 0
    assert "claim" in content.lower()


def test_load_agent_file_missing() -> None:
    with pytest.raises(AgentResolverError, match="not found"):
        load_agent_file("nonexistent-agent", _REPO_ROOT)


def test_resolve_skill_content_for_agent_with_skills(spec) -> None:
    agent = spec.agents["claim-classification-agent"]
    content = resolve_skill_content(agent, _REPO_ROOT)
    assert len(content) > 0


def test_resolve_skill_content_empty_for_dispatcher(spec) -> None:
    agent = spec.agents["audit-coordinator-agent"]
    content = resolve_skill_content(agent, _REPO_ROOT)
    assert content == ""


def test_all_agents_resolve_from_workflow_steps(spec) -> None:
    """Every step with agent_binding resolves to a valid agent."""
    for step_id, step in spec.workflow_steps.items():
        agent = resolve_agent(step, spec)
        if step.raw.get("agent_binding"):
            assert agent is not None, f"Step {step_id} has binding but resolved to None"
            assert agent.name == step.raw["agent_binding"]
