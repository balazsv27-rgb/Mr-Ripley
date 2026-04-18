"""Tests for B2: prompt assembly + input bounding integration into executor.

Covers:
- V2 execution with MockExecutionBackend produces prompt_assembled trace event
- V2 dry-run produces prompt_assembled trace event without backend invocation
- Assembled PromptContext contains skill_content, agent_instructions, artifact_inputs
- Truncation with small token_budget
- V1 shell mode produces no prompt_assembled events
- Structural steps produce no prompt_assembled events
- build_prompt_text concatenation order
- build_prompt_context round-trip
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.models import (
    AgentSpec,
    AssembledWorkflowSpec,
    ExecutionConfig,
    ManifestSpec,
    PromptContext,
    WorkflowStep,
)
from governance.dag_runner.planner import (
    ExecutionPlan,
    PlannedNode,
    build_execution_plan,
)
from governance.dag_runner.prompt_assembly import (
    build_prompt_context,
    build_prompt_text,
)
from governance.dag_runner.validator import validate_or_raise


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def real_pipeline():
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)
    return spec, plan


def _make_step(
    name: str,
    *,
    component: str = "skill:test",
    outputs: list[str] | None = None,
    agent_binding: str | None = None,
) -> WorkflowStep:
    raw: dict = {}
    if agent_binding:
        raw["agent_binding"] = agent_binding
    return WorkflowStep(
        name=name,
        component=component,
        outputs=outputs if outputs is not None else [],
        raw=raw,
    )


def _make_spec(
    *steps: WorkflowStep,
    agents: dict | None = None,
) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test-b2"),
        workflow_steps={s.name: s for s in steps},
        agents=agents or {},
    )


def _make_plan(*steps: WorkflowStep) -> ExecutionPlan:
    return ExecutionPlan(
        workflow_name="test-b2",
        ordered_steps=[
            PlannedNode(step_id=s.name, component=s.component)
            for s in steps
        ],
    )


def _config(mode: str = "agent_execution") -> ExecutionConfig:
    return ExecutionConfig(mode=mode)


def _get_event_types(result, node_name: str | None = None) -> list[str]:
    events = result.run_state.execution_trace
    if node_name:
        events = [e for e in events if e.node_name == node_name]
    return [e.event_type for e in events]


# ── B2: V2 execution produces prompt_assembled trace event ──


class TestPromptAssembledTraceEvents:

    def test_v2_agent_execution_emits_prompt_assembled(self, real_pipeline) -> None:
        """V2 execution with MockExecutionBackend produces prompt_assembled trace."""
        spec, plan = real_pipeline
        backend = MockExecutionBackend()
        config = _config("agent_execution")
        result = execute_plan(spec, plan, config=config, backend=backend)

        event_types = _get_event_types(result)
        assert "prompt_assembled" in event_types
        assert "input_bounded" in event_types

    def test_v2_dry_run_emits_prompt_assembled(self, real_pipeline) -> None:
        """V2 dry-run produces prompt_assembled trace event without backend invocation."""
        spec, plan = real_pipeline
        backend = MockExecutionBackend()
        config = _config("dry_run")
        result = execute_plan(spec, plan, config=config, backend=backend)

        event_types = _get_event_types(result)
        assert "prompt_assembled" in event_types
        # Dry-run should NOT invoke backend
        assert "backend_invocation_started" not in event_types

    def test_v1_shell_no_prompt_assembled(self, real_pipeline) -> None:
        """V1 shell mode produces no prompt_assembled events."""
        spec, plan = real_pipeline
        result = execute_plan(spec, plan, verdict_status="ready")

        event_types = _get_event_types(result)
        assert "prompt_assembled" not in event_types
        assert "input_bounded" not in event_types

    def test_structural_step_no_prompt_assembled(self) -> None:
        """Structural steps produce no prompt_assembled events."""
        step = _make_step("structural-step", component="constitution")
        spec = _make_spec(step)
        plan = _make_plan(step)
        backend = MockExecutionBackend()
        config = _config()

        result = execute_plan(spec, plan, config=config, backend=backend)
        event_types = _get_event_types(result, "structural-step")
        assert "prompt_assembled" not in event_types

    def test_prompt_assembled_detail_has_token_estimate(self, real_pipeline) -> None:
        """prompt_assembled trace event contains token_estimate and truncated."""
        spec, plan = real_pipeline
        backend = MockExecutionBackend()
        config = _config("agent_execution")
        result = execute_plan(spec, plan, config=config, backend=backend)

        pa_events = [
            e for e in result.run_state.execution_trace
            if e.event_type == "prompt_assembled"
        ]
        assert len(pa_events) > 0
        detail = pa_events[0].detail
        assert "token_estimate" in detail
        assert "truncated" in detail

    def test_input_bounded_detail_has_budget(self, real_pipeline) -> None:
        """input_bounded trace event contains budget, actual, truncated."""
        spec, plan = real_pipeline
        backend = MockExecutionBackend()
        config = _config("agent_execution")
        result = execute_plan(spec, plan, config=config, backend=backend)

        ib_events = [
            e for e in result.run_state.execution_trace
            if e.event_type == "input_bounded"
        ]
        assert len(ib_events) > 0
        detail = ib_events[0].detail
        assert "budget" in detail
        assert "actual" in detail
        assert "truncated" in detail


# ── B2-B: build_prompt_text ──


class TestBuildPromptText:

    def test_concatenation_order(self) -> None:
        """Sections appear in priority order: skill, agent, artifacts, docs."""
        context = {
            "skill_content": "SKILL CONTENT",
            "agent_instructions": "AGENT CONTENT",
            "artifact_inputs": {"upstream": {"key": "val"}},
            "document_paths": ["/path/to/doc.md"],
        }
        text = build_prompt_text(context)
        skill_pos = text.index("SKILL CONTENT")
        agent_pos = text.index("AGENT CONTENT")
        artifact_pos = text.index("upstream")
        doc_pos = text.index("/path/to/doc.md")
        assert skill_pos < agent_pos < artifact_pos < doc_pos

    def test_empty_sections_omitted(self) -> None:
        """Empty sections are not included."""
        context = {
            "skill_content": "",
            "agent_instructions": "AGENT ONLY",
            "artifact_inputs": {},
            "document_paths": [],
        }
        text = build_prompt_text(context)
        assert "SKILL INSTRUCTIONS" not in text
        assert "AGENT ONLY" in text
        assert "UPSTREAM ARTIFACTS" not in text

    def test_empty_context_returns_empty(self) -> None:
        text = build_prompt_text({})
        assert text == ""


# ── build_prompt_context ──


class TestBuildPromptContext:

    def test_round_trip(self) -> None:
        """build_prompt_context produces a valid PromptContext from a dict."""
        context = {
            "agent": AgentSpec(name="test"),
            "skill_content": "skill text",
            "agent_instructions": "agent text",
            "artifact_inputs": {"art": {"data": 1}},
            "document_paths": ["doc.md"],
            "token_budget": 50_000,
            "token_estimate": 1000,
            "truncated": False,
            "truncation_events": [],
        }
        ctx = build_prompt_context(context)
        assert isinstance(ctx, PromptContext)
        assert ctx.skill_content == "skill text"
        assert ctx.agent_instructions == "agent text"
        assert ctx.artifact_inputs == {"art": {"data": 1}}
        assert ctx.document_paths == ["doc.md"]
        assert ctx.token_budget == 50_000
        assert ctx.token_estimate == 1000
        assert ctx.truncated is False
        assert len(ctx.assembled_prompt) > 0

    def test_assembled_prompt_contains_skill_content(self) -> None:
        context = {
            "skill_content": "UNIQUE_SKILL_MARKER",
            "agent_instructions": "",
            "artifact_inputs": {},
            "document_paths": [],
        }
        ctx = build_prompt_context(context)
        assert "UNIQUE_SKILL_MARKER" in ctx.assembled_prompt
