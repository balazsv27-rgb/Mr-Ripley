"""Tests for governance.dag_runner.prompt_assembly and input_bounding."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.input_bounding import (
    BoundedInput,
    bound_inputs,
    estimate_tokens,
)
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.models import ExecutionConfig, GovernanceRunState
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.prompt_assembly import (
    assemble_step_prompt,
    build_prompt_composition_metadata,
)
from governance.dag_runner.validator import validate_or_raise


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def pipeline():
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)
    # Run V1 shell to populate artifacts
    result = execute_plan(spec, plan, verdict_status="ready")
    return spec, plan, result.run_state


# ── input_bounding ──


def test_estimate_tokens() -> None:
    assert estimate_tokens("hello world") >= 1
    assert estimate_tokens("a" * 400) == 100


def test_bound_inputs_under_budget() -> None:
    inputs = [BoundedInput(name="a", content="short", priority=1)]
    result = bound_inputs(inputs, budget=1000)
    assert result.truncated is False
    assert result.total_tokens <= 1000


def test_bound_inputs_truncates_lowest_priority() -> None:
    skill = BoundedInput(name="skill", content="x" * 4000, priority=1)  # 1000 tokens
    doc = BoundedInput(name="doc", content="y" * 4000, priority=4)  # 1000 tokens
    result = bound_inputs([skill, doc], budget=1200)
    assert result.truncated is True
    # Skill should not be truncated
    skill_out = next(i for i in result.inputs if i.name == "skill")
    assert skill_out.truncated is False
    # Doc should be truncated
    doc_out = next(i for i in result.inputs if i.name == "doc")
    assert doc_out.truncated is True


def test_bound_inputs_never_truncates_priority_1() -> None:
    skill = BoundedInput(name="skill", content="x" * 8000, priority=1)  # 2000 tokens
    result = bound_inputs([skill], budget=100)  # way under budget
    # Still not truncated — priority 1 is sacred
    skill_out = result.inputs[0]
    assert skill_out.truncated is False


# ── prompt_assembly ──


def test_assemble_prompt_for_skill_step(pipeline) -> None:
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["classify-claims"]
    result = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    assert result["agent"] is not None
    assert result["agent"].name == "claim-classification-agent"
    assert len(result["skill_content"]) > 0


def test_assemble_prompt_for_structural_step(pipeline) -> None:
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["load-context"]
    result = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    assert result["agent"] is None  # no agent binding
    assert result["skill_content"] == ""


def test_assemble_prompt_includes_artifact_inputs(pipeline) -> None:
    spec, plan, run_state = pipeline
    # normalize-terminology consumes governance_context and claim_classification_map
    step = spec.workflow_steps["normalize-terminology"]
    result = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    assert "governance_context" in result["artifact_inputs"]


def test_assemble_prompt_respects_token_budget(pipeline) -> None:
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["classify-claims"]
    result = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT, token_budget=50)
    # With a tiny budget, something should get truncated
    assert result["truncated"] is True
    assert len(result["truncation_events"]) > 0


# ── prompt_composition_metadata ──


def test_build_prompt_composition_metadata_fields(pipeline) -> None:
    """build_prompt_composition_metadata returns all required diagnostic fields."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["normalize-terminology"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # All required keys present
    required_keys = {
        "step_name",
        "skill_content_length",
        "agent_instructions_length",
        "artifact_input_names",
        "artifact_input_count",
        "document_paths",
        "document_count",
        "token_estimate",
        "token_budget",
        "truncated",
        "truncation_events",
        "expected_outputs",
    }
    assert required_keys.issubset(meta.keys()), (
        f"Missing keys: {required_keys - meta.keys()}"
    )

    # Step-specific assertions for normalize-terminology
    assert meta["step_name"] == "normalize-terminology"
    assert meta["skill_content_length"] > 0
    assert meta["agent_instructions_length"] > 0
    assert meta["artifact_input_count"] >= 1
    assert "governance_context" in meta["artifact_input_names"]
    assert meta["token_estimate"] > 0
    assert meta["token_budget"] == 100_000
    assert "normalized_terminology_map" in meta["expected_outputs"]


def test_route_claims_by_role_receives_interpretation_policy(pipeline) -> None:
    """route-claims-by-role must receive interpretation_policy.claim_routing in prompt context.

    Regression test: interpretation_policy.claim_routing is declared as an input
    in workflow-steps.yaml and agents.yaml, but was silently dropped because
    _gather_artifact_inputs only looked in run_state.artifacts.  After the fix,
    the dotted name is resolved from spec.interpretation_policy.raw.
    """
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["route-claims-by-role"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)

    # The interpretation_policy.claim_routing must appear in artifact_inputs
    assert "interpretation_policy.claim_routing" in ctx["artifact_inputs"], (
        "interpretation_policy.claim_routing was not injected into prompt context — "
        "dotted spec-path resolution is broken"
    )

    # Verify the payload contains the expected routing keys
    routing = ctx["artifact_inputs"]["interpretation_policy.claim_routing"]
    assert "architecture_claims" in routing, (
        "claim_routing payload missing architecture_claims key"
    )
    assert "implementation_claims" in routing, (
        "claim_routing payload missing implementation_claims key"
    )

    # Verify it appears in prompt_composition metadata
    meta = build_prompt_composition_metadata(ctx)
    assert "interpretation_policy.claim_routing" in meta["artifact_input_names"], (
        "interpretation_policy.claim_routing missing from prompt_composition metadata"
    )


def test_normalize_terminology_prompt_is_bounded(pipeline) -> None:
    """normalize-terminology prompt size should be inspectable without live backend."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["normalize-terminology"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # Token estimate should be well within default budget
    assert meta["token_estimate"] < meta["token_budget"], (
        f"Token estimate {meta['token_estimate']} exceeds budget {meta['token_budget']}"
    )
    assert meta["truncated"] is False

    # Skill content should be substantially smaller after SKILL.md simplification
    # (was ~51KB / 781 lines, now targeting ~150 lines / <15KB)
    assert meta["skill_content_length"] < 20_000, (
        f"Skill content too large: {meta['skill_content_length']} chars"
    )
