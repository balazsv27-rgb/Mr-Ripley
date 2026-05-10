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

    # All required keys present (including new per-input contribution fields)
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
        "input_contributions",
        "assembled_prompt_chars",
        "assembled_prompt_tokens",
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

    # Per-input contribution diagnostics
    contributions = meta["input_contributions"]
    assert "skill_instructions" in contributions
    assert contributions["skill_instructions"]["chars"] > 0
    assert contributions["skill_instructions"]["estimated_tokens"] > 0
    assert "agent_instructions" in contributions
    assert contributions["agent_instructions"]["chars"] > 0

    # Assembled prompt totals
    assert meta["assembled_prompt_chars"] > 0
    assert meta["assembled_prompt_tokens"] > 0


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


def test_input_projection_filters_fields(pipeline) -> None:
    """Input projections strip non-essential fields from artifact payloads."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    # Simulated governance_context with extra fields
    full_payload = {
        "produced_by": "load-context",
        "run_id": "test-run-123",
        "request_text": "Check the architecture",
        "request_source": "cli",
        "bootstrap_status": "request_bearing",
        "workflow_name": "governance",
        "execution_mode": "agent_execution",
        "code_context": {"series_registry": {"status": "present"}},
        "runtime_context": {"layer3_runtime_absent": True},
        "extra_field_1": "should be stripped",
        "extra_field_2": {"nested": "data"},
    }

    projected = _project_artifact_payload(
        "route-claims-by-role", "governance_context", full_payload,
    )

    # Projected payload should retain declared fields including code/runtime context
    assert "produced_by" in projected
    assert "request_text" in projected
    assert "run_id" in projected
    assert "code_context" in projected
    assert "runtime_context" in projected
    assert "extra_field_1" not in projected
    assert "extra_field_2" not in projected

    # Artifacts without a projection pass through unchanged
    unchanged = _project_artifact_payload(
        "route-claims-by-role", "interpretation_policy.claim_routing", full_payload,
    )
    assert unchanged is full_payload  # same object — no projection defined

    # Steps without any projections pass through unchanged
    other_step = _project_artifact_payload(
        "classify-claims", "governance_context", full_payload,
    )
    assert other_step is full_payload


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


# ── phase-check artifact projection ──


def test_phase_check_claim_classification_projection_flat_schema() -> None:
    """phase-check projection works with legacy flat claims/summary schema."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "classify-claims",
        "status": "classified",
        "reason": "Long reason text that should be stripped " * 10,
        "detail": "Very long detail text " * 50,
        "claims": [
            {
                "claim_id": "c1",
                "claim_text": "Rename terminology across Layer-2",
                "classification": "current-state",
                "claim_scope": "documentation",
                "rationale": "Long rationale " * 20,
                "evidence": [{"source": "doc", "excerpt": "x" * 500}],
            },
            {
                "claim_id": "c2",
                "claim_text": "Update target architecture terms",
                "classification": "target-state",
                "claim_scope": "architecture",
                "rationale": "Another long rationale " * 20,
                "evidence": [{"source": "doc", "excerpt": "x" * 500}],
            },
        ],
        "summary": {
            "dominant_scope": "documentation",
            "needs_phase_check": True,
            "touches_current_truth": True,
            "touches_target_architecture": True,
            "touches_historical_reconciliation": False,
            "touches_verification_matrix": False,
            "touches_snapshot_contract": False,
            "possible_blocking_conditions": ["rename_scope_ambiguity"],
        },
    }

    projected = _project_artifact_payload(
        "phase-check", "claim_classification_map", full_payload,
    )

    # Must not be the same object (projection was applied)
    assert projected is not full_payload

    # Required summary fields present
    assert projected["produced_by"] == "classify-claims"
    assert projected["status"] == "classified"
    assert projected["dominant_scope"] == "documentation"
    assert projected["touches_current_truth"] is True
    assert projected["touches_target_architecture"] is True
    assert projected["possible_blocking_conditions"] == ["rename_scope_ambiguity"]
    assert projected["claim_count"] == 2

    # Compact claims present with expected keys only
    assert "claims_compact" in projected
    assert len(projected["claims_compact"]) == 2
    assert projected["claims_compact"][0]["claim_id"] == "c1"
    assert projected["claims_compact"][0]["classification"] == "current-state"
    assert projected["claims_compact"][0]["claim_scope"] == "documentation"
    # Per-claim verbose fields must be stripped
    assert "rationale" not in projected["claims_compact"][0]
    assert "evidence" not in projected["claims_compact"][0]
    assert "claim_text" not in projected["claims_compact"][0]

    # Top-level verbose fields stripped
    assert "detail" not in projected
    assert "reason" not in projected
    assert "claims" not in projected  # replaced by claims_compact

    # Size reduction: projected must be materially smaller
    import json
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.5, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_phase_check_claim_classification_projection_nested_schema() -> None:
    """phase-check projection works with real nested request_classification schema."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "classify-claims",
        "run_id": "test-run-123",
        "request_id": "test-request",
        "status": "classified",
        "request_classification": {
            "request_type": "documentation-wide terminology refactor",
            "claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "Replace Layer 2 with truth_store " * 10,
                    "claim_scope": "current-state",
                    "evidence_class": "verified_in_current_documentation_set",
                    "source_priority": ["SYSTEM_ARCHITECTURE_v1.md"],
                    "confidence_level": "high",
                    "classification_rationale": "Long rationale " * 30,
                    "notes": ["Long note " * 20, "Another note " * 20],
                },
                {
                    "claim_id": "c2",
                    "claim_text": "Replace Layer 3 with decision_layer " * 10,
                    "claim_scope": "current-state",
                    "evidence_class": "verified_in_current_documentation_set",
                    "source_priority": ["SYSTEM_ARCHITECTURE_v1.md"],
                    "confidence_level": "high",
                    "classification_rationale": "Another long rationale " * 30,
                    "notes": ["Note " * 30],
                },
            ],
            "summary": {
                "dominant_scope": "current-state",
                "needs_phase_check": True,
                "touches_current_truth": True,
                "touches_target_architecture": True,
                "touches_historical_reconciliation": True,
                "touches_verification_matrix": True,
                "touches_snapshot_contract": True,
                "possible_blocking_conditions": [
                    "contract_affecting_documentation_change",
                    "canonical_filename_rename_cascade",
                ],
            },
        },
    }

    projected = _project_artifact_payload(
        "phase-check", "claim_classification_map", full_payload,
    )

    # Must not be the same object (projection was applied)
    assert projected is not full_payload

    # Required summary fields present
    assert projected["produced_by"] == "classify-claims"
    assert projected["status"] == "classified"
    assert projected["dominant_scope"] == "current-state"
    assert projected["touches_current_truth"] is True
    assert projected["touches_target_architecture"] is True
    assert projected["possible_blocking_conditions"] == [
        "contract_affecting_documentation_change",
        "canonical_filename_rename_cascade",
    ]
    assert projected["claim_count"] == 2

    # Compact claims present with expected keys only
    assert "claims_compact" in projected
    assert len(projected["claims_compact"]) == 2
    assert projected["claims_compact"][0]["claim_id"] == "c1"
    assert projected["claims_compact"][0]["claim_scope"] == "current-state"
    # Per-claim verbose fields must be stripped
    assert "classification_rationale" not in projected["claims_compact"][0]
    assert "evidence_class" not in projected["claims_compact"][0]
    assert "source_priority" not in projected["claims_compact"][0]
    assert "notes" not in projected["claims_compact"][0]
    assert "claim_text" not in projected["claims_compact"][0]

    # Nested structure must not leak into compact output
    assert "request_classification" not in projected
    assert "run_id" not in projected
    assert "request_id" not in projected

    # Size reduction: projected must be materially smaller
    import json
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.3, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_phase_check_role_citation_projection_nested_schema() -> None:
    """phase-check projection works with nested role_matched_citation_status schema."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "route-claims-by-role",
        "role_matched_citation_status": {
            "overall_status": "review_only",
            "inference_used": True,
            "source_authority_conflict_detected": False,
            "checked_claims": [
                {
                    "claim_id": "c1",
                    "verdict": "compliant",
                    "notes": ["Long analysis note " * 30],
                },
                {
                    "claim_id": "c2",
                    "verdict": "review_only",
                    "notes": ["Another long note " * 30],
                },
                {
                    "claim_id": "c3",
                    "verdict": "blocking",
                    "notes": ["Blocking note " * 30],
                },
            ],
            "summary": {
                "role_mismatch_detected": False,
                "canonical_conflict_unresolved": False,
                "readme_layer2_used_as_override": False,
                "requires_conflict_note": False,
                "requires_doc_sync_escalation": False,
                "recommended_guard_action": "none",
                "notes": ["Very long summary note " * 50],
            },
        },
    }

    projected = _project_artifact_payload(
        "phase-check", "role_citation_verdict", full_payload,
    )

    # Must not be the same object
    assert projected is not full_payload

    # Required fields present
    assert projected["produced_by"] == "route-claims-by-role"
    assert projected["overall_status"] == "review_only"
    assert projected["source_authority_conflict_detected"] is False
    assert projected["recommended_guard_action"] == "none"
    assert projected["role_mismatch_detected"] is False
    assert projected["canonical_conflict_unresolved"] is False
    assert projected["requires_doc_sync_escalation"] is False
    assert projected["checked_claim_count"] == 3

    # Claims categorized by verdict
    assert projected["compliant_claims"] == ["c1"]
    assert projected["review_only_claims"] == ["c2"]
    assert projected["blocking_claims"] == ["c3"]

    # Verbose nested structure stripped
    assert "role_matched_citation_status" not in projected
    import json
    serialized = json.dumps(projected)
    assert "Long analysis note" not in serialized
    assert "Very long summary note" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.3, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_phase_check_role_citation_projection_flat_schema() -> None:
    """phase-check projection works with flat role_citation_verdict schema."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "route-claims-by-role",
        "inference_used": True,
        "source_authority_conflict_detected": True,
        "overall_status": "conflict_requires_block",
        "checked_claims": [
            {
                "claim_id": "C-001",
                "claim_text": "Long claim text " * 20,
                "verdict": "RC-2 Review only",
                "reason": "Long reason " * 30,
                "notes": "Long note " * 50,
            },
            {
                "claim_id": "C-003",
                "claim_text": "Another claim " * 20,
                "verdict": "blocking",
                "reason": "Block reason " * 30,
                "notes": "Block note " * 50,
            },
        ],
        "summary": {
            "role_mismatch_detected": True,
            "canonical_conflict_unresolved": True,
            "requires_doc_sync_escalation": True,
            "recommended_guard_action": "block",
            "blocking_summary": "Long blocking summary " * 20,
            "notes": "Summary notes " * 50,
        },
    }

    projected = _project_artifact_payload(
        "phase-check", "role_citation_verdict", full_payload,
    )

    # Must not be the same object
    assert projected is not full_payload

    # Required fields present
    assert projected["produced_by"] == "route-claims-by-role"
    assert projected["overall_status"] == "conflict_requires_block"
    assert projected["source_authority_conflict_detected"] is True
    assert projected["recommended_guard_action"] == "block"
    assert projected["canonical_conflict_unresolved"] is True
    assert projected["checked_claim_count"] == 2
    assert projected["blocking_claims"] == ["C-003"]

    # Verbose fields stripped
    import json
    serialized = json.dumps(projected)
    assert "Long claim text" not in serialized
    assert "Long reason" not in serialized
    assert "Long note" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.3, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_phase_check_minimal_payload_passthrough() -> None:
    """V1 shell minimal payloads pass through transforms unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal = {"produced_by": "classify-claims"}
    result = _project_artifact_payload(
        "phase-check", "claim_classification_map", minimal,
    )
    assert result is minimal  # same object — no transform applied

    minimal2 = {"produced_by": "route-claims-by-role"}
    result2 = _project_artifact_payload(
        "phase-check", "role_citation_verdict", minimal2,
    )
    assert result2 is minimal2  # same object — no transform applied


def test_phase_check_projection_metadata(pipeline) -> None:
    """phase-check prompt composition includes projection diagnostic fields."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["phase-check"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # New projection metadata keys must be present
    assert "projected_artifact_names" in meta
    assert "input_contributions_original" in meta
    assert "input_contributions_projected" in meta
    assert isinstance(meta["projected_artifact_names"], list)
    assert isinstance(meta["input_contributions_original"], dict)
    assert isinstance(meta["input_contributions_projected"], dict)

    # In V1 shell mode payloads are minimal so transforms pass through —
    # projection_log will be empty, but the structure must still be correct.
    # This test validates structure; the unit tests above validate content.


def test_phase_check_projection_log_with_rich_payload() -> None:
    """_apply_step_projections records original vs projected sizes."""
    from governance.dag_runner.prompt_assembly import _apply_step_projections

    rich_inputs = {
        "claim_classification_map": {
            "produced_by": "classify-claims",
            "status": "classified",
            "request_classification": {
                "request_type": "terminology refactor",
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_scope": "current-state",
                        "claim_text": "x" * 1000,
                        "classification_rationale": "x" * 2000,
                        "notes": ["x" * 3000],
                    },
                ],
                "summary": {
                    "dominant_scope": "documentation",
                    "touches_current_truth": True,
                    "touches_target_architecture": False,
                    "possible_blocking_conditions": [],
                },
            },
        },
        "role_citation_verdict": {
            "produced_by": "route-claims-by-role",
            "role_matched_citation_status": {
                "overall_status": "review_only",
                "source_authority_conflict_detected": False,
                "checked_claims": [
                    {"claim_id": "c1", "verdict": "compliant", "notes": ["x" * 3000]},
                ],
                "summary": {
                    "recommended_guard_action": "none",
                    "role_mismatch_detected": False,
                    "canonical_conflict_unresolved": False,
                    "requires_doc_sync_escalation": False,
                    "notes": ["x" * 5000],
                },
            },
        },
        "stage_gates": {"produced_by": "load-context", "gates": []},
    }

    projected, log = _apply_step_projections("phase-check", rich_inputs)

    # Two artifacts should be projected (stage_gates has no projection)
    assert len(log) == 2
    projected_names = {entry["artifact"] for entry in log}
    assert projected_names == {"claim_classification_map", "role_citation_verdict"}

    # Each log entry must have size fields
    for entry in log:
        assert entry["original_chars"] > 0
        assert entry["projected_chars"] > 0
        assert entry["original_tokens"] > 0
        assert entry["projected_tokens"] > 0
        # Projected must be smaller than original
        assert entry["projected_chars"] < entry["original_chars"], (
            f"{entry['artifact']}: projected {entry['projected_chars']} >= "
            f"original {entry['original_chars']}"
        )

    # stage_gates should pass through unchanged
    assert projected["stage_gates"] is rich_inputs["stage_gates"]


# ── snapshot-contract-check artifact projection ──


def test_snapshot_contract_role_citation_projection_nested_schema() -> None:
    """snapshot-contract-check projection works with nested role_matched_citation_status."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "route-claims-by-role",
        "role_matched_citation_status": {
            "overall_status": "conflict_requires_block",
            "inference_used": True,
            "source_authority_conflict_detected": True,
            "checked_claims": [
                {
                    "claim_id": "C-01",
                    "claim_text": "Layer 2 is operational " * 20,
                    "verdict": "RC-2",
                    "reason": "Long reason " * 30,
                    "notes": "Long note " * 50,
                },
                {
                    "claim_id": "C-03",
                    "claim_text": "truth_store rename " * 20,
                    "verdict": "RC-4",
                    "reason": "Long block reason " * 30,
                    "notes": "Long block note " * 50,
                },
                {
                    "claim_id": "C-05",
                    "claim_text": "README_LAYER2 status " * 10,
                    "verdict": "RC-1",
                    "reason": "Compliant " * 20,
                    "notes": "Note " * 30,
                },
            ],
            "summary": {
                "role_mismatch_detected": True,
                "canonical_conflict_unresolved": True,
                "readme_layer2_used_as_override": False,
                "requires_conflict_note": True,
                "requires_doc_sync_escalation": True,
                "recommended_guard_action": "block",
                "blocking_claims": ["C-03"],
                "block_reasons": {
                    "C-03": "Strong claim without role-matched citation",
                },
                "escalation_required": True,
                "escalation_target": "canonical-role-auditor",
                "escalation_triggers": ["role_mismatch on C-03"],
                "notes": "Very long summary note " * 100,
            },
        },
    }

    projected = _project_artifact_payload(
        "snapshot-contract-check", "role_citation_verdict", full_payload,
    )

    # Must not be the same object
    assert projected is not full_payload

    # Required governance status fields
    assert projected["produced_by"] == "route-claims-by-role"
    assert projected["overall_status"] == "conflict_requires_block"
    assert projected["source_authority_conflict_detected"] is True
    assert projected["recommended_guard_action"] == "block"
    assert projected["canonical_conflict_unresolved"] is True
    assert projected["checked_claim_count"] == 3
    assert projected["escalation_required"] is True
    assert projected["escalation_target"] == "canonical-role-auditor"

    # Blocking claims from summary
    assert projected["blocking_claims"] == ["C-03"]
    assert projected["block_reasons_summary"] == {
        "C-03": "Strong claim without role-matched citation",
    }

    # Verbose nested structure stripped
    assert "role_matched_citation_status" not in projected
    import json
    serialized = json.dumps(projected)
    assert "Long reason" not in serialized
    assert "Very long summary note" not in serialized
    assert "Long note" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.3, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_snapshot_contract_role_citation_projection_flat_schema() -> None:
    """snapshot-contract-check projection works with flat role_citation_verdict."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "route-claims-by-role",
        "inference_used": True,
        "source_authority_conflict_detected": True,
        "overall_status": "conflict_requires_block",
        "checked_claims": [
            {
                "claim_id": "C-001",
                "claim_text": "Long claim " * 20,
                "verdict": "RC-2 Review only",
                "reason": "x" * 2000,
                "notes": "x" * 3000,
            },
            {
                "claim_id": "C-003",
                "claim_text": "Another claim " * 20,
                "verdict": "RC-4",
                "reason": "x" * 2000,
                "notes": "x" * 3000,
            },
        ],
        "summary": {
            "role_mismatch_detected": True,
            "canonical_conflict_unresolved": True,
            "recommended_guard_action": "block",
            "escalation_required": True,
            "escalation_target": "canonical-role-auditor",
            "blocking_summary": "x" * 500,
            "notes": "x" * 500,
        },
    }

    projected = _project_artifact_payload(
        "snapshot-contract-check", "role_citation_verdict", full_payload,
    )

    # Must not be the same object
    assert projected is not full_payload

    # Required fields
    assert projected["produced_by"] == "route-claims-by-role"
    assert projected["overall_status"] == "conflict_requires_block"
    assert projected["source_authority_conflict_detected"] is True
    assert projected["recommended_guard_action"] == "block"
    assert projected["canonical_conflict_unresolved"] is True
    assert projected["checked_claim_count"] == 2
    assert projected["escalation_required"] is True
    assert projected["escalation_target"] == "canonical-role-auditor"

    # Blocking claims derived from checked_claims verdicts
    assert "C-003" in projected["blocking_claims"]

    # Verbose fields stripped
    import json
    serialized = json.dumps(projected)
    assert "Long claim" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.3, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_snapshot_contract_phase_alignment_projection() -> None:
    """snapshot-contract-check receives compact projection of phase_alignment_status."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "phase-check",
        "current_phase": "Phase A/B",
        "requested_phase": "inferred: Phase A/B documentation governance action",
        "allowed": False,
        "alignment_status": "ambiguous_requires_block",
        "gate_reference": [
            "phase_a_layer2_closure",
            "phase_b_layer3_bootstrap",
        ],
        "blocking_reason_if_any": "upstream_role_citation_conflict_requires_block",
        "checked_claims": [
            {
                "claim_id": "c1",
                "claim_text": "Replace Layer 2 with truth_store " * 10,
                "effective_capability": "Rename current-state terminology " * 5,
                "phase_assessment": "ambiguous",
                "gate_reference": ["phase_a_layer2_closure"],
                "reason": "Very long reason text " * 50,
            },
            {
                "claim_id": "c2",
                "claim_text": "Replace Layer 3 with decision_layer " * 10,
                "effective_capability": "Rename target architecture " * 5,
                "phase_assessment": "blocked",
                "gate_reference": ["phase_b_layer3_bootstrap"],
                "reason": "Another very long reason " * 50,
            },
        ],
        "summary": {
            "phase_jump_detected": False,
            "live_readiness_implication_detected": False,
            "scope_exceeds_current_allowance": True,
            "snapshot_boundary_risk": True,
            "followup_audit_recommended": True,
            "upstream_block_inherited": True,
            "upstream_block_source": "role_citation_verdict: conflict",
            "blocking_claims_summary": [
                "c2: decision_layer implies current existence of planned layer (target-state promotion risk)",
            ],
            "ambiguous_claims_summary": [
                "c1: truth_store needs boundary clarification",
            ],
            "allowed_claims_summary": [
                "c3: scoping constraint — allowed",
            ],
            "recommended_next_step": "Do not proceed. " * 20,
        },
    }

    projected = _project_artifact_payload(
        "snapshot-contract-check", "phase_alignment_status", full_payload,
    )

    # Must not be the same object
    assert projected is not full_payload

    # Required verdict fields
    assert projected["produced_by"] == "phase-check"
    assert projected["allowed"] is False
    assert projected["alignment_status"] == "ambiguous_requires_block"
    assert projected["gate_reference"] == [
        "phase_a_layer2_closure",
        "phase_b_layer3_bootstrap",
    ]
    assert "upstream_role_citation" in projected["blocking_reason_if_any"]

    # Summary risk flags retained
    assert projected["upstream_block_inherited"] is True
    assert projected["snapshot_boundary_risk"] is True
    assert projected["scope_exceeds_current_allowance"] is True
    assert projected["blocking_claims_summary"] == [
        "c2: decision_layer implies current existence of planned layer (target-state promotion risk)",
    ]
    assert projected["ambiguous_claims_summary"] == [
        "c1: truth_store needs boundary clarification",
    ]
    assert "Do not proceed" in projected["recommended_next_step"]

    # Verbose per-claim detail stripped
    assert "checked_claims" not in projected
    assert "current_phase" not in projected
    assert "requested_phase" not in projected

    import json
    serialized = json.dumps(projected)
    assert "Very long reason text" not in serialized
    assert "effective_capability" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.5, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_snapshot_contract_minimal_payload_passthrough() -> None:
    """V1 shell minimal payloads pass through transforms unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal_rcv = {"produced_by": "route-claims-by-role"}
    result = _project_artifact_payload(
        "snapshot-contract-check", "role_citation_verdict", minimal_rcv,
    )
    assert result is minimal_rcv  # same object — no transform applied

    minimal_pas = {"produced_by": "phase-check"}
    result2 = _project_artifact_payload(
        "snapshot-contract-check", "phase_alignment_status", minimal_pas,
    )
    assert result2 is minimal_pas  # same object — no transform applied


def test_snapshot_contract_projection_metadata(pipeline) -> None:
    """snapshot-contract-check prompt composition includes projection diagnostic fields."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["snapshot-contract-check"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # Projection metadata keys must be present
    assert "projected_artifact_names" in meta
    assert "input_contributions_original" in meta
    assert "input_contributions_projected" in meta
    assert isinstance(meta["projected_artifact_names"], list)
    assert isinstance(meta["input_contributions_original"], dict)
    assert isinstance(meta["input_contributions_projected"], dict)


def test_snapshot_contract_projection_log_with_rich_payload() -> None:
    """_apply_step_projections records original vs projected sizes for snapshot-contract-check."""
    from governance.dag_runner.prompt_assembly import _apply_step_projections

    rich_inputs = {
        "role_citation_verdict": {
            "produced_by": "route-claims-by-role",
            "role_matched_citation_status": {
                "overall_status": "conflict_requires_block",
                "source_authority_conflict_detected": True,
                "checked_claims": [
                    {
                        "claim_id": "C-01",
                        "verdict": "RC-4",
                        "notes": "x" * 5000,
                        "reason": "x" * 3000,
                    },
                ],
                "summary": {
                    "recommended_guard_action": "block",
                    "canonical_conflict_unresolved": True,
                    "blocking_claims": ["C-01"],
                    "block_reasons": {"C-01": "missing citation"},
                    "escalation_required": True,
                    "escalation_target": "auditor",
                    "notes": "x" * 8000,
                },
            },
        },
        "phase_alignment_status": {
            "produced_by": "phase-check",
            "allowed": False,
            "alignment_status": "ambiguous_requires_block",
            "gate_reference": ["phase_a"],
            "blocking_reason_if_any": "upstream block",
            "checked_claims": [
                {
                    "claim_id": "c1",
                    "reason": "x" * 5000,
                    "effective_capability": "x" * 2000,
                },
            ],
            "summary": {
                "upstream_block_inherited": True,
                "snapshot_boundary_risk": True,
                "scope_exceeds_current_allowance": True,
                "blocking_claims_summary": ["c1: blocked"],
                "ambiguous_claims_summary": [],
                "recommended_next_step": "Do not proceed",
            },
        },
    }

    projected, log = _apply_step_projections(
        "snapshot-contract-check", rich_inputs,
    )

    # Two artifacts should be projected
    assert len(log) == 2
    projected_names = {entry["artifact"] for entry in log}
    assert projected_names == {"role_citation_verdict", "phase_alignment_status"}

    # Each log entry must have size fields and show reduction
    for entry in log:
        assert entry["original_chars"] > 0
        assert entry["projected_chars"] > 0
        assert entry["original_tokens"] > 0
        assert entry["projected_tokens"] > 0
        assert entry["projected_chars"] < entry["original_chars"], (
            f"{entry['artifact']}: projected {entry['projected_chars']} >= "
            f"original {entry['original_chars']}"
        )


# ── runtime-boundary-check artifact projection ──


def test_runtime_boundary_contract_projection_nested_schema() -> None:
    """runtime-boundary-check projection extracts compact fields from nested contract_compliance_verdict."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "snapshot-contract-check",
        "snapshot_contract_status": {
            "allowed": False,
            "contract_status": "boundary_violation",
            "valid_interface": "snapshot_db",
            "forbidden_access_detected": True,
            "snapshot_anchor_required": True,
            "blocking_reason_if_any": "raw observation access detected in proposed Layer-3 consumer",
            "checked_claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "Layer-3 queries observations directly " * 20,
                    "assessment": "blocked",
                    "violated_invariants": ["SCC-1"],
                    "triggered_forbidden_patterns": ["FP-1"],
                    "valid_interface_if_compliant": "none",
                    "reason": "Very long reason text about boundary violation " * 30,
                    "contract_reference": ["SCC-1", "FP-1"],
                },
                {
                    "claim_id": "c2",
                    "claim_text": "Another claim about snapshot access " * 20,
                    "assessment": "compliant",
                    "violated_invariants": [],
                    "triggered_forbidden_patterns": [],
                    "valid_interface_if_compliant": "snapshot_db",
                    "reason": "Compliant because uses snapshot_id anchored query " * 20,
                    "contract_reference": ["SCC-2"],
                },
            ],
            "summary": {
                "raw_observations_access_risk": True,
                "snapshot_bypass_risk": False,
                "layer2_storage_touch_risk": False,
                "decisionpacket_anchor_risk": False,
                "followup_guard_recommended": True,
                "upstream_block_inherited": False,
                "blocked_in_strict_mode": True,
                "resolution_required": True,
            },
        },
    }

    projected = _project_artifact_payload(
        "runtime-boundary-check", "contract_compliance_verdict", full_payload,
    )

    # Must not be the same object (projection was applied)
    assert projected is not full_payload

    # Required top-level fields preserved
    assert projected["produced_by"] == "snapshot-contract-check"
    assert projected["allowed"] is False
    assert projected["contract_status"] == "boundary_violation"
    assert projected["forbidden_access_detected"] is True
    assert projected["snapshot_anchor_required"] is True
    assert "raw observation access" in projected["blocking_reason_if_any"]

    # Summary risk flags preserved
    assert projected["raw_observations_access_risk"] is True
    assert projected["snapshot_bypass_risk"] is False
    assert projected["layer2_storage_touch_risk"] is False
    assert projected["decisionpacket_anchor_risk"] is False
    assert projected["blocked_in_strict_mode"] is True
    assert projected["resolution_required"] is True

    # checked_claims MUST be dropped entirely
    assert "checked_claims" not in projected
    assert "snapshot_contract_status" not in projected

    import json
    serialized = json.dumps(projected)
    assert "Very long reason text" not in serialized
    assert "violated_invariants" not in serialized

    # Size reduction: must achieve ≥80% reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.2, (
        f"Projection did not achieve 80% reduction: {proj_size} vs {orig_size}"
    )


def test_runtime_boundary_contract_projection_flat_schema() -> None:
    """runtime-boundary-check projection works with flat contract_compliance_verdict."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "snapshot-contract-check",
        "allowed": True,
        "contract_status": "compliant",
        "valid_interface": "both",
        "forbidden_access_detected": False,
        "snapshot_anchor_required": True,
        "blocking_reason_if_any": None,
        "checked_claims": [
            {
                "claim_id": "c1",
                "claim_text": "Snapshot consumer reads latest_snapshot.json " * 15,
                "assessment": "compliant",
                "reason": "Uses snapshot_id anchor correctly " * 20,
            },
        ],
        "summary": {
            "raw_observations_access_risk": False,
            "snapshot_bypass_risk": False,
            "layer2_storage_touch_risk": False,
            "decisionpacket_anchor_risk": False,
        },
    }

    projected = _project_artifact_payload(
        "runtime-boundary-check", "contract_compliance_verdict", full_payload,
    )

    # Must not be same object
    assert projected is not full_payload

    # Required fields
    assert projected["produced_by"] == "snapshot-contract-check"
    assert projected["allowed"] is True
    assert projected["contract_status"] == "compliant"
    assert projected["forbidden_access_detected"] is False
    assert projected["blocking_reason_if_any"] is None

    # Summary flags
    assert projected["raw_observations_access_risk"] is False

    # checked_claims dropped
    assert "checked_claims" not in projected

    # Size reduction
    import json
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.5, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_runtime_boundary_contract_projection_minimal_passthrough() -> None:
    """V1 shell minimal payloads pass through transforms unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal = {"produced_by": "snapshot-contract-check"}
    result = _project_artifact_payload(
        "runtime-boundary-check", "contract_compliance_verdict", minimal,
    )
    assert result is minimal  # same object — no transform applied


def test_runtime_boundary_projection_metadata(pipeline) -> None:
    """runtime-boundary-check prompt composition includes projection diagnostic fields."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["runtime-boundary-check"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # Projection metadata keys must be present
    assert "projected_artifact_names" in meta
    assert "input_contributions_original" in meta
    assert "input_contributions_projected" in meta
    assert isinstance(meta["projected_artifact_names"], list)
    assert isinstance(meta["input_contributions_original"], dict)
    assert isinstance(meta["input_contributions_projected"], dict)


def test_runtime_boundary_projection_log_with_rich_payload() -> None:
    """_apply_step_projections records original vs projected sizes for runtime-boundary-check."""
    from governance.dag_runner.prompt_assembly import _apply_step_projections

    rich_inputs = {
        "contract_compliance_verdict": {
            "produced_by": "snapshot-contract-check",
            "snapshot_contract_status": {
                "allowed": False,
                "contract_status": "boundary_violation",
                "forbidden_access_detected": True,
                "snapshot_anchor_required": True,
                "blocking_reason_if_any": "raw observation access",
                "checked_claims": [
                    {
                        "claim_id": "c1",
                        "claim_text": "x" * 2000,
                        "assessment": "blocked",
                        "reason": "x" * 3000,
                        "violated_invariants": ["SCC-1"],
                        "triggered_forbidden_patterns": ["FP-1"],
                    },
                    {
                        "claim_id": "c2",
                        "claim_text": "x" * 2000,
                        "assessment": "compliant",
                        "reason": "x" * 3000,
                    },
                ],
                "summary": {
                    "raw_observations_access_risk": True,
                    "snapshot_bypass_risk": False,
                    "layer2_storage_touch_risk": False,
                    "decisionpacket_anchor_risk": False,
                },
            },
        },
        "stage_gate_report": {"produced_by": "stage-gate-enforcement", "gates": []},
    }

    projected, log = _apply_step_projections(
        "runtime-boundary-check", rich_inputs,
    )

    # Only contract_compliance_verdict should be projected
    assert len(log) == 1
    assert log[0]["artifact"] == "contract_compliance_verdict"

    # Log entry must show size reduction
    assert log[0]["original_chars"] > 0
    assert log[0]["projected_chars"] > 0
    assert log[0]["projected_chars"] < log[0]["original_chars"], (
        f"projected {log[0]['projected_chars']} >= original {log[0]['original_chars']}"
    )

    # stage_gate_report should pass through unchanged
    assert projected["stage_gate_report"] is rich_inputs["stage_gate_report"]


# ── adapter-schema-check artifact projection ──


def test_adapter_schema_runtime_boundary_projection_flat_schema() -> None:
    """adapter-schema-check projection extracts compact fields from flat runtime_boundary_verdict."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "runtime-boundary-check",
        "overall_boundary_status": "review_only",
        "inference_used": True,
        "raw_observation_access_detected": False,
        "latest_snapshot_misuse_detected": False,
        "layer2_storage_coupling_detected": False,
        "boundary_violation_suspected": True,
        "upstream_violation_inherited": True,
        "checked_items": [
            {
                "item_id": "RBC-1",
                "target": "contract_compliance_verdict (upstream)",
                "assessment": "blocked",
                "raw_observations_access_detected": False,
                "latest_snapshot_misuse_detected": False,
                "reason": "Very long reason about upstream boundary violation " * 20,
                "canonical_source": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
                "notes": [
                    "upstream block inherited " * 10,
                    "decision_layer risk " * 10,
                ],
            },
            {
                "item_id": "RBC-2",
                "target": "code_context — layer2/db.py",
                "assessment": "review",
                "reason": "Code-level file reads could not be executed " * 15,
                "notes": ["requires_snapshot_boundary_auditor " * 10],
            },
            {
                "item_id": "RBC-3",
                "target": "runtime_context",
                "assessment": "review",
                "reason": "Runtime artifacts could not be read " * 15,
                "notes": ["snapshot_bypass_risk " * 10],
            },
            {
                "item_id": "RBC-4",
                "target": "Execution boundary",
                "assessment": "blocked",
                "reason": "Upstream flagged execution connotation risk " * 20,
                "notes": ["No automated trading " * 10],
            },
        ],
        "summary": {
            "raw_observations_violation_detected": False,
            "latest_snapshot_misuse_detected": False,
            "boundary_violation_suspected": True,
            "upstream_block_inherited": True,
            "code_inspection_possible": False,
            "requires_snapshot_boundary_guard": True,
            "requires_snapshot_boundary_auditor": True,
            "requires_doc_code_sync_review": True,
            "source_authority_conflict_detected": True,
            "escalation_required": True,
            "escalation_target": "snapshot-boundary-auditor",
            "notes": [
                "Very long summary note about upstream propagation " * 20,
                "Another long note about code inspection " * 20,
                "Third long note about boundary guard " * 20,
            ],
        },
    }

    projected = _project_artifact_payload(
        "adapter-schema-check", "runtime_boundary_verdict", full_payload,
    )

    # Must not be same object (projection was applied)
    assert projected is not full_payload

    # Required boundary flags preserved
    assert projected["produced_by"] == "runtime-boundary-check"
    assert projected["overall_boundary_status"] == "review_only"
    assert projected["raw_observation_access_detected"] is False
    assert projected["latest_snapshot_misuse_detected"] is False
    assert projected["layer2_storage_coupling_detected"] is False
    assert projected["boundary_violation_suspected"] is True
    assert projected["upstream_violation_inherited"] is True

    # Summary escalation signals preserved
    assert projected["code_inspection_possible"] is False
    assert projected["requires_snapshot_boundary_guard"] is True
    assert projected["requires_snapshot_boundary_auditor"] is True
    assert projected["requires_doc_code_sync_review"] is True
    assert projected["source_authority_conflict_detected"] is True
    assert projected["escalation_required"] is True
    assert projected["escalation_target"] == "snapshot-boundary-auditor"

    # checked_items MUST be dropped entirely
    assert "checked_items" not in projected
    # summary.notes MUST be dropped
    assert "notes" not in projected

    import json
    serialized = json.dumps(projected)
    assert "Very long reason" not in serialized
    assert "Very long summary note" not in serialized
    assert "Code-level file reads" not in serialized

    # Size reduction: must achieve substantial reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.2, (
        f"Projection did not achieve 80% reduction: {proj_size} vs {orig_size}"
    )


def test_adapter_schema_runtime_boundary_projection_minimal_passthrough() -> None:
    """V1 shell minimal payloads pass through transforms unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal = {"produced_by": "runtime-boundary-check"}
    result = _project_artifact_payload(
        "adapter-schema-check", "runtime_boundary_verdict", minimal,
    )
    assert result is minimal  # same object — no transform applied


def test_adapter_schema_runtime_boundary_projection_metadata(pipeline) -> None:
    """adapter-schema-check prompt composition includes projection diagnostic fields."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["adapter-schema-check"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # Projection metadata keys must be present
    assert "projected_artifact_names" in meta
    assert "input_contributions_original" in meta
    assert "input_contributions_projected" in meta
    assert isinstance(meta["projected_artifact_names"], list)
    assert isinstance(meta["input_contributions_original"], dict)
    assert isinstance(meta["input_contributions_projected"], dict)


def test_adapter_schema_projection_log_with_rich_payload() -> None:
    """_apply_step_projections records original vs projected sizes for adapter-schema-check."""
    from governance.dag_runner.prompt_assembly import _apply_step_projections

    rich_inputs = {
        "runtime_boundary_verdict": {
            "produced_by": "runtime-boundary-check",
            "overall_boundary_status": "review_only",
            "raw_observation_access_detected": False,
            "latest_snapshot_misuse_detected": False,
            "layer2_storage_coupling_detected": False,
            "boundary_violation_suspected": True,
            "upstream_violation_inherited": True,
            "checked_items": [
                {
                    "item_id": "RBC-1",
                    "target": "upstream",
                    "assessment": "blocked",
                    "reason": "x" * 3000,
                    "notes": ["x" * 2000, "x" * 2000],
                },
                {
                    "item_id": "RBC-2",
                    "target": "code_context",
                    "assessment": "review",
                    "reason": "x" * 3000,
                    "notes": ["x" * 2000],
                },
            ],
            "summary": {
                "code_inspection_possible": False,
                "requires_snapshot_boundary_guard": True,
                "requires_snapshot_boundary_auditor": True,
                "requires_doc_code_sync_review": True,
                "source_authority_conflict_detected": True,
                "escalation_required": True,
                "escalation_target": "snapshot-boundary-auditor",
                "notes": ["x" * 5000, "x" * 3000],
            },
        },
        "governance_context": {"produced_by": "load-context", "run_id": "test"},
    }

    projected, log = _apply_step_projections(
        "adapter-schema-check", rich_inputs,
    )

    # Only runtime_boundary_verdict should be projected
    assert len(log) == 1
    assert log[0]["artifact"] == "runtime_boundary_verdict"

    # Log entry must show size reduction
    assert log[0]["original_chars"] > 0
    assert log[0]["projected_chars"] > 0
    assert log[0]["projected_chars"] < log[0]["original_chars"], (
        f"projected {log[0]['projected_chars']} >= original {log[0]['original_chars']}"
    )

    # governance_context should pass through unchanged
    assert projected["governance_context"] is rich_inputs["governance_context"]


# ── deep-audit artifact projection ──


def test_deep_audit_claim_classification_projection() -> None:
    """deep-audit projection keeps routing fields, drops claim narratives."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "classify-claims",
        "status": "classified",
        "request_classification": {
            "request_type": "documentation-wide terminology refactor",
            "claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "Replace Layer 2 with truth_store " * 20,
                    "claim_scope": "current-state",
                    "classification": "current-state",
                    "classification_rationale": "Long rationale " * 50,
                    "notes": ["Note " * 100],
                },
                {
                    "claim_id": "c2",
                    "claim_text": "Replace Layer 3 with decision_layer " * 20,
                    "claim_scope": "target-state",
                    "classification": "target-state",
                    "classification_rationale": "Another long rationale " * 50,
                    "notes": ["Note " * 100],
                },
            ],
            "summary": {
                "dominant_scope": "current-state",
                "possible_blocking_conditions": [
                    "contract_affecting_documentation_change",
                ],
            },
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "claim_classification_map", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "classify-claims"
    assert projected["status"] == "classified"
    assert projected["request_type"] == "documentation-wide terminology refactor"
    assert projected["dominant_scope"] == "current-state"
    assert projected["possible_blocking_conditions"] == [
        "contract_affecting_documentation_change",
    ]
    assert projected["claim_count"] == 2
    assert projected["claim_ids"] == ["c1", "c2"]

    # Verbose fields stripped
    assert "request_classification" not in projected
    import json
    serialized = json.dumps(projected)
    assert "classification_rationale" not in serialized
    assert "claim_text" not in serialized
    assert "notes" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.15, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_deep_audit_role_citation_projection() -> None:
    """deep-audit projection keeps escalation signals from role_citation_verdict."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "route-claims-by-role",
        "role_matched_citation_status": {
            "overall_status": "conflict_requires_block",
            "source_authority_conflict_detected": True,
            "checked_claims": [
                {
                    "claim_id": "C-01",
                    "verdict": "compliant",
                    "notes": ["Long analysis " * 50],
                    "reason": "x" * 3000,
                },
                {
                    "claim_id": "C-02",
                    "verdict": "review_only",
                    "notes": ["Long note " * 50],
                    "reason": "x" * 3000,
                },
                {
                    "claim_id": "C-03",
                    "verdict": "RC-4",
                    "notes": ["Long block note " * 50],
                    "reason": "x" * 3000,
                },
            ],
            "summary": {
                "canonical_conflict_unresolved": True,
                "requires_doc_sync_escalation": True,
                "recommended_guard_action": "block",
                "escalation_target": "canonical-role-auditor",
                "notes": ["Very long summary " * 100],
            },
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "role_citation_verdict", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "route-claims-by-role"
    assert projected["overall_status"] == "conflict_requires_block"
    assert projected["source_authority_conflict_detected"] is True
    assert projected["canonical_conflict_unresolved"] is True
    assert projected["requires_doc_sync_escalation"] is True
    assert projected["recommended_guard_action"] == "block"
    assert projected["escalation_target"] == "canonical-role-auditor"
    assert projected["blocking_claim_ids"] == ["C-03"]
    assert projected["review_only_claim_ids"] == ["C-02"]

    # Verbose fields stripped
    assert "role_matched_citation_status" not in projected
    import json
    serialized = json.dumps(projected)
    assert "Long analysis" not in serialized
    assert "Very long summary" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.1, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_deep_audit_phase_alignment_projection() -> None:
    """deep-audit projection keeps phase verdict and upstream guard signals."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "phase-check",
        "allowed": False,
        "alignment_status": "ambiguous_requires_block",
        "gate_reference": ["phase_a_layer2_closure"],
        "blocking_reason_if_any": "upstream_role_citation_conflict",
        "checked_claims": [
            {
                "claim_id": "c1",
                "claim_text": "Long claim " * 20,
                "reason": "Very long reason " * 50,
                "effective_capability": "x" * 2000,
            },
            {
                "claim_id": "c2",
                "claim_text": "Another claim " * 20,
                "reason": "Another very long reason " * 50,
                "effective_capability": "x" * 2000,
            },
        ],
        "summary": {
            "live_readiness_implication_detected": False,
            "canonical_conflict_unresolved": True,
            "role_mismatch_unresolved": True,
            "upstream_block_inherited": True,
            "blocking_claims_summary": ["c1: blocked"],
            "recommended_next_step": "Do not proceed",
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "phase_alignment_status", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "phase-check"
    assert projected["allowed"] is False
    assert projected["alignment_status"] == "ambiguous_requires_block"
    assert projected["live_readiness_implication_detected"] is False
    assert projected["canonical_conflict_unresolved"] is True
    assert projected["role_mismatch_unresolved"] is True
    assert projected["upstream_guard_action_inherited"] is True
    assert projected["high_priority_blocking_conditions_from_upstream"] == ["c1: blocked"]
    assert projected["recommended_next_step"] == "Do not proceed"

    # Verbose fields stripped
    assert "checked_claims" not in projected
    assert "gate_reference" not in projected
    import json
    serialized = json.dumps(projected)
    assert "Very long reason" not in serialized
    assert "effective_capability" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.15, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_deep_audit_contract_compliance_projection() -> None:
    """deep-audit projection keeps contract status and risk flags."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "snapshot-contract-check",
        "snapshot_contract_status": {
            "allowed": False,
            "contract_status": "boundary_violation",
            "forbidden_access_detected": True,
            "snapshot_anchor_required": True,
            "checked_claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "x" * 2000,
                    "assessment": "blocked",
                    "reason": "x" * 3000,
                },
                {
                    "claim_id": "c2",
                    "claim_text": "x" * 2000,
                    "assessment": "compliant",
                    "reason": "x" * 3000,
                },
            ],
            "summary": {
                "upstream_block_inherited": True,
                "escalation_target": "snapshot-boundary-auditor",
                "resolution_required": True,
                "raw_observations_access_risk": True,
                "snapshot_bypass_risk": False,
                "layer2_storage_touch_risk": False,
                "decisionpacket_anchor_risk": False,
            },
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "contract_compliance_verdict", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "snapshot-contract-check"
    assert projected["allowed"] is False
    assert projected["contract_status"] == "boundary_violation"
    assert projected["forbidden_access_detected"] is True
    assert projected["snapshot_anchor_required"] is True
    assert projected["upstream_block_inherited"] is True
    assert projected["escalation_target"] == "snapshot-boundary-auditor"
    assert projected["resolution_required_before_recheck"] is True
    assert projected["raw_observations_access_risk"] is True
    assert projected["snapshot_bypass_risk"] is False
    assert projected["layer2_storage_touch_risk"] is False
    assert projected["decisionpacket_anchor_risk"] is False

    # Verbose fields stripped
    assert "checked_claims" not in projected
    assert "snapshot_contract_status" not in projected
    import json
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.2, (
        f"Projection did not achieve 80% reduction: {proj_size} vs {orig_size}"
    )


def test_deep_audit_runtime_boundary_projection() -> None:
    """deep-audit projection keeps boundary flags and escalation signals."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "runtime-boundary-check",
        "overall_boundary_status": "review_only",
        "raw_observation_access_detected": False,
        "latest_snapshot_misuse_detected": False,
        "layer2_storage_coupling_detected": False,
        "boundary_violation_suspected": True,
        "upstream_violation_inherited": True,
        "checked_items": [
            {
                "item_id": "RBC-1",
                "reason": "x" * 3000,
                "notes": ["x" * 2000, "x" * 2000],
            },
            {
                "item_id": "RBC-2",
                "reason": "x" * 3000,
                "notes": ["x" * 2000],
            },
        ],
        "summary": {
            "upstream_block_inherited": True,
            "requires_snapshot_boundary_guard": True,
            "requires_snapshot_boundary_auditor": True,
            "requires_doc_code_sync_review": True,
            "source_authority_conflict_detected": True,
            "notes": ["x" * 5000],
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "runtime_boundary_verdict", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "runtime-boundary-check"
    assert projected["overall_status"] == "review_only"
    assert projected["upstream_block_inherited"] is True
    assert projected["raw_observation_access_detected"] is False
    assert projected["latest_snapshot_misuse_detected"] is False
    assert projected["layer2_storage_coupling_detected"] is False
    assert projected["boundary_violation_suspected"] is True
    assert projected["requires_snapshot_boundary_guard"] is True
    assert projected["requires_snapshot_boundary_auditor"] is True
    assert projected["requires_doc_code_sync_review"] is True
    assert projected["source_authority_conflict_detected"] is True

    # Verbose fields stripped
    assert "checked_items" not in projected
    assert "notes" not in projected
    import json
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.1, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_deep_audit_adapter_schema_projection() -> None:
    """deep-audit projection keeps adapter violation flags and escalation signals."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "adapter-schema-check",
        "overall_status": "review_only",
        "registry_violation_detected": False,
        "hardcoded_series_detected": False,
        "schema_drift_detected": True,
        "boundary_violation_detected": False,
        "checked_items": [
            {
                "item_id": "ASC-1",
                "reason": "x" * 3000,
                "notes": ["x" * 2000],
            },
            {
                "item_id": "ASC-2",
                "reason": "x" * 3000,
                "notes": ["x" * 2000, "x" * 2000],
            },
        ],
        "summary": {
            "requires_adapter_schema_guard": True,
            "requires_adapter_schema_guardian": True,
            "requires_doc_code_sync_review": True,
            "source_authority_conflict_detected": False,
            "notes": ["x" * 5000, "x" * 3000],
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "adapter_schema_verdict", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "adapter-schema-check"
    assert projected["overall_status"] == "review_only"
    assert projected["registry_violation_detected"] is False
    assert projected["hardcoded_series_detected"] is False
    assert projected["schema_drift_detected"] is True
    assert projected["boundary_violation_detected"] is False
    assert projected["requires_adapter_schema_guard"] is True
    assert projected["requires_adapter_schema_guardian"] is True
    assert projected["requires_doc_code_sync_review"] is True
    assert projected["source_authority_conflict_detected"] is False

    # Verbose fields stripped
    assert "checked_items" not in projected
    import json
    serialized = json.dumps(projected)
    assert "notes" not in projected
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.1, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_deep_audit_role_citation_projection_nested_b_schema() -> None:
    """deep-audit projection works with real LLM role_citation_status nesting."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "route-claims-by-role",
        "run_id": "test-run",
        "skill_applied": "role-matched-citation-check",
        "inference_used": True,
        "role_citation_status": {
            "overall_status": "conflict_requires_block",
            "inference_used": True,
            "source_authority_conflict_detected": True,
            "checked_claims": [
                {
                    "claim_id": "CL-001",
                    "claim_text": "truth_store is canonical replacement " * 20,
                    "verdict": "conflict_requires_block",
                    "reason": "Very long blocking reason " * 30,
                    "notes": "Long notes " * 50,
                },
                {
                    "claim_id": "CL-002",
                    "claim_text": "decision_layer rename " * 20,
                    "verdict": "RC-4",
                    "reason": "Another blocking reason " * 30,
                    "notes": "More notes " * 50,
                },
                {
                    "claim_id": "CL-003",
                    "claim_text": "Layer 2 is operational " * 20,
                    "verdict": "compliant",
                    "reason": "Compliant " * 20,
                    "notes": "Compliant notes " * 30,
                },
            ],
            "summary": {
                "canonical_conflict_unresolved": True,
                "requires_doc_sync_escalation": True,
                "recommended_guard_action": "block",
                "escalation_target": "canonical-role-auditor",
                "notes": ["Very long summary " * 100],
            },
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "role_citation_verdict", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "route-claims-by-role"
    assert projected["overall_status"] == "conflict_requires_block"
    assert projected["source_authority_conflict_detected"] is True
    assert projected["canonical_conflict_unresolved"] is True
    assert projected["requires_doc_sync_escalation"] is True
    assert projected["recommended_guard_action"] == "block"
    assert projected["escalation_target"] == "canonical-role-auditor"
    assert "CL-002" in projected["blocking_claim_ids"]

    # Verbose fields stripped
    assert "role_citation_status" not in projected
    assert "run_id" not in projected
    assert "skill_applied" not in projected
    import json
    serialized = json.dumps(projected)
    assert "Very long blocking reason" not in serialized
    assert "Very long summary" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.1, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_deep_audit_runtime_boundary_projection_nested_schema() -> None:
    """deep-audit projection works with real LLM snapshot_boundary_status nesting."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "runtime-boundary-check",
        "snapshot_boundary_status": {
            "overall_status": "ambiguous_requires_review",
            "inference_used": True,
            "checked_items": [
                {
                    "item_id": "RB-01",
                    "target": "layer2/adapters/*",
                    "assessment": "review",
                    "reason": "Very long reason about code inspection " * 30,
                    "notes": ["Long note " * 50, "Another note " * 50],
                },
                {
                    "item_id": "RB-02",
                    "target": "layer2/db.py",
                    "assessment": "review",
                    "reason": "Another very long reason " * 30,
                    "notes": ["Note " * 50],
                },
            ],
            "summary": {
                "upstream_block_inherited": True,
                "requires_snapshot_boundary_guard": True,
                "requires_snapshot_boundary_auditor": True,
                "requires_doc_code_sync_review": True,
                "source_authority_conflict_detected": True,
            },
        },
        "runtime_fields": {
            "raw_observation_access_detected": False,
            "latest_snapshot_misuse_detected": False,
            "layer2_storage_coupling_detected": False,
            "boundary_violation_suspected": True,
        },
        "escalation": {
            "trigger": "boundary_violation_suspected",
            "escalate_to": "snapshot-boundary-auditor",
            "reason": "Escalation reason " * 20,
            "mandatory": True,
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "runtime_boundary_verdict", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "runtime-boundary-check"
    assert projected["overall_status"] == "ambiguous_requires_review"
    assert projected["upstream_block_inherited"] is True
    assert projected["raw_observation_access_detected"] is False
    assert projected["latest_snapshot_misuse_detected"] is False
    assert projected["layer2_storage_coupling_detected"] is False
    assert projected["boundary_violation_suspected"] is True
    assert projected["requires_snapshot_boundary_guard"] is True
    assert projected["requires_snapshot_boundary_auditor"] is True
    assert projected["requires_doc_code_sync_review"] is True
    assert projected["source_authority_conflict_detected"] is True

    # Verbose fields stripped
    assert "snapshot_boundary_status" not in projected
    assert "runtime_fields" not in projected
    assert "escalation" not in projected
    import json
    serialized = json.dumps(projected)
    assert "Very long reason" not in serialized
    assert "checked_items" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.1, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_deep_audit_adapter_schema_projection_nested_schema() -> None:
    """deep-audit projection works with real LLM adapter_schema_status nesting."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "adapter-schema-check",
        "adapter_schema_status": {
            "overall_status": "ambiguous_requires_review",
            "inference_used": True,
            "checked_items": [
                {
                    "item_id": "AS-01",
                    "target": "layer2/adapters/*",
                    "assessment": "review",
                    "reason": "Very long reason about registry compliance " * 30,
                    "notes": ["Long note " * 50],
                },
                {
                    "item_id": "AS-02",
                    "target": "layer2/adapters/*",
                    "assessment": "review",
                    "reason": "Another very long reason " * 30,
                    "notes": ["Note " * 50, "Another " * 50],
                },
            ],
            "summary": {
                "registry_violation_detected": False,
                "hardcoded_series_detected": False,
                "schema_drift_detected": True,
                "boundary_violation_detected": False,
                "requires_adapter_schema_guard": True,
                "requires_adapter_schema_guardian": True,
                "requires_doc_code_sync_review": True,
                "source_authority_conflict_detected": False,
            },
        },
    }

    projected = _project_artifact_payload(
        "deep-audit", "adapter_schema_verdict", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "adapter-schema-check"
    assert projected["overall_status"] == "ambiguous_requires_review"
    assert projected["registry_violation_detected"] is False
    assert projected["hardcoded_series_detected"] is False
    assert projected["schema_drift_detected"] is True
    assert projected["boundary_violation_detected"] is False
    assert projected["requires_adapter_schema_guard"] is True
    assert projected["requires_adapter_schema_guardian"] is True
    assert projected["requires_doc_code_sync_review"] is True
    assert projected["source_authority_conflict_detected"] is False

    # Verbose fields stripped
    assert "adapter_schema_status" not in projected
    import json
    serialized = json.dumps(projected)
    assert "Very long reason" not in serialized
    assert "checked_items" not in serialized

    # Size reduction: must achieve >80% reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.2, (
        f"Projection did not achieve 80% reduction: {proj_size} vs {orig_size}"
    )


def test_deep_audit_minimal_payload_passthrough() -> None:
    """V1 shell minimal payloads pass through deep-audit transforms unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    artifacts_and_producers = [
        ("claim_classification_map", "classify-claims"),
        ("role_citation_verdict", "route-claims-by-role"),
        ("phase_alignment_status", "phase-check"),
        ("contract_compliance_verdict", "snapshot-contract-check"),
        ("runtime_boundary_verdict", "runtime-boundary-check"),
        ("adapter_schema_verdict", "adapter-schema-check"),
    ]

    for artifact_name, producer in artifacts_and_producers:
        minimal = {"produced_by": producer}
        result = _project_artifact_payload(
            "deep-audit", artifact_name, minimal,
        )
        assert result is minimal, (
            f"deep-audit/{artifact_name}: minimal payload was unexpectedly transformed"
        )


def test_deep_audit_projection_log_with_rich_payloads() -> None:
    """_apply_step_projections records original vs projected sizes for deep-audit."""
    from governance.dag_runner.prompt_assembly import _apply_step_projections

    rich_inputs = {
        "claim_classification_map": {
            "produced_by": "classify-claims",
            "status": "classified",
            "request_classification": {
                "request_type": "terminology refactor",
                "claims": [
                    {
                        "claim_id": "c1",
                        "claim_scope": "current-state",
                        "claim_text": "x" * 2000,
                        "classification_rationale": "x" * 3000,
                        "notes": ["x" * 3000],
                    },
                ],
                "summary": {
                    "dominant_scope": "documentation",
                    "possible_blocking_conditions": [],
                },
            },
        },
        "role_citation_verdict": {
            "produced_by": "route-claims-by-role",
            "role_matched_citation_status": {
                "overall_status": "review_only",
                "source_authority_conflict_detected": False,
                "checked_claims": [
                    {"claim_id": "c1", "verdict": "compliant", "notes": ["x" * 5000]},
                ],
                "summary": {
                    "recommended_guard_action": "none",
                    "canonical_conflict_unresolved": False,
                    "requires_doc_sync_escalation": False,
                    "notes": ["x" * 5000],
                },
            },
        },
        "phase_alignment_status": {
            "produced_by": "phase-check",
            "allowed": True,
            "alignment_status": "aligned",
            "checked_claims": [
                {"claim_id": "c1", "reason": "x" * 5000},
            ],
            "summary": {
                "upstream_block_inherited": False,
                "blocking_claims_summary": [],
                "recommended_next_step": "proceed",
            },
        },
        "contract_compliance_verdict": {
            "produced_by": "snapshot-contract-check",
            "allowed": True,
            "contract_status": "compliant",
            "forbidden_access_detected": False,
            "snapshot_anchor_required": True,
            "checked_claims": [
                {"claim_id": "c1", "reason": "x" * 5000},
            ],
            "summary": {
                "raw_observations_access_risk": False,
                "snapshot_bypass_risk": False,
                "layer2_storage_touch_risk": False,
                "decisionpacket_anchor_risk": False,
            },
        },
        "runtime_boundary_verdict": {
            "produced_by": "runtime-boundary-check",
            "overall_boundary_status": "review_only",
            "raw_observation_access_detected": False,
            "latest_snapshot_misuse_detected": False,
            "layer2_storage_coupling_detected": False,
            "boundary_violation_suspected": False,
            "upstream_violation_inherited": False,
            "checked_items": [
                {"item_id": "RBC-1", "reason": "x" * 4000, "notes": ["x" * 3000]},
            ],
            "summary": {
                "requires_snapshot_boundary_guard": False,
                "requires_snapshot_boundary_auditor": False,
                "requires_doc_code_sync_review": False,
                "source_authority_conflict_detected": False,
                "notes": ["x" * 5000],
            },
        },
        "adapter_schema_verdict": {
            "produced_by": "adapter-schema-check",
            "overall_status": "compliant",
            "registry_violation_detected": False,
            "hardcoded_series_detected": False,
            "schema_drift_detected": False,
            "boundary_violation_detected": False,
            "checked_items": [
                {"item_id": "ASC-1", "reason": "x" * 4000, "notes": ["x" * 3000]},
            ],
            "summary": {
                "requires_adapter_schema_guard": False,
                "requires_adapter_schema_guardian": False,
                "requires_doc_code_sync_review": False,
                "source_authority_conflict_detected": False,
                "notes": ["x" * 5000],
            },
        },
        # These two pass through unchanged (no projection defined)
        "guard_report": {"produced_by": "runtime-guards-summary", "guards": []},
        "stage_gate_report": {"produced_by": "stage-gate-enforcement", "gates": []},
    }

    projected, log = _apply_step_projections("deep-audit", rich_inputs)

    # Six artifacts should be projected
    assert len(log) == 6
    projected_names = {entry["artifact"] for entry in log}
    assert projected_names == {
        "claim_classification_map",
        "role_citation_verdict",
        "phase_alignment_status",
        "contract_compliance_verdict",
        "runtime_boundary_verdict",
        "adapter_schema_verdict",
    }

    # Each log entry must show size reduction
    total_original = 0
    total_projected = 0
    for entry in log:
        assert entry["original_chars"] > 0
        assert entry["projected_chars"] > 0
        assert entry["original_tokens"] > 0
        assert entry["projected_tokens"] > 0
        assert entry["projected_chars"] < entry["original_chars"], (
            f"{entry['artifact']}: projected {entry['projected_chars']} >= "
            f"original {entry['original_chars']}"
        )
        total_original += entry["original_chars"]
        total_projected += entry["projected_chars"]

    # Overall size reduction must be substantial (>70%)
    assert total_projected < total_original * 0.3, (
        f"Total projection did not achieve 70% reduction: "
        f"{total_projected} vs {total_original}"
    )

    # guard_report and stage_gate_report should pass through unchanged
    assert projected["guard_report"] is rich_inputs["guard_report"]
    assert projected["stage_gate_report"] is rich_inputs["stage_gate_report"]


def test_deep_audit_projection_metadata(pipeline) -> None:
    """deep-audit prompt composition includes projection diagnostic fields."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["deep-audit"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # Projection metadata keys must be present
    assert "projected_artifact_names" in meta
    assert "input_contributions_original" in meta
    assert "input_contributions_projected" in meta
    assert isinstance(meta["projected_artifact_names"], list)
    assert isinstance(meta["input_contributions_original"], dict)
    assert isinstance(meta["input_contributions_projected"], dict)


# ── doc-code-sync-check artifact projection ──


def test_doc_code_sync_change_impact_projection_wrapped_schema() -> None:
    """doc-code-sync-check projection works with wrapped change_impact_summary."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "change-impact-audit",
        "run_id": "test-run-123",
        "change_impact_summary": {
            "produced_by": "change-impact-audit",
            "change_mode": "documentation_only",
            "impact_type": "contract_affecting",
            "contributing_categories": ["terminology", "architecture"],
            "impacted_components": ["layer2", "snapshot_publisher"],
            "impacted_docs": [
                "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
                "README_v1.md",
            ],
            "follow_up_required": True,
            "risk_summary": [
                "Risk item 1 " * 10,
                "Risk item 2 " * 10,
                "Risk item 3 " * 10,
            ],
            "doc_only_change": True,
            "code_path_governance_required": False,
            "verification_update_required": True,
            "canonical_docs_impacted": True,
            "long_explanation": "Very long explanation text " * 100,
            "detailed_notes": ["Very long note " * 50, "Another note " * 50],
        },
    }

    projected = _project_artifact_payload(
        "doc-code-sync-check", "change_impact_report", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "change-impact-audit"
    assert projected["change_mode"] == "documentation_only"
    assert projected["impact_type"] == "contract_affecting"
    assert projected["contributing_categories"] == ["terminology", "architecture"]
    assert projected["impacted_components"] == ["layer2", "snapshot_publisher"]
    assert projected["impacted_docs"] == [
        "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "README_v1.md",
    ]
    assert projected["follow_up_required"] is True
    assert len(projected["risk_summary"]) == 3
    assert projected["sync_relevant_flags"]["doc_only_change"] is True
    assert projected["sync_relevant_flags"]["verification_update_required"] is True

    # Long fields stripped
    import json
    serialized = json.dumps(projected)
    assert "long_explanation" not in serialized
    assert "detailed_notes" not in serialized
    assert "run_id" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.5, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_doc_code_sync_change_impact_projection_flat_schema() -> None:
    """doc-code-sync-check projection works with top-level change_impact_report."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "change-impact-audit",
        "change_mode": "code_and_docs",
        "impact_type": "boundary_affecting",
        "contributing_categories": ["snapshot_contract"],
        "impacted_components": ["quality_gate"],
        "impacted_docs": ["SYSTEM_TECHNICAL_HANDBOOK_v1.md"],
        "follow_up_required": True,
        "risk_summary": ["Risk " * 10] * 8,
        "doc_only_change": False,
        "code_path_governance_required": True,
        "verification_update_required": True,
        "canonical_docs_impacted": True,
        "long_notes": "Very long narrative " * 200,
    }

    projected = _project_artifact_payload(
        "doc-code-sync-check", "change_impact_report", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "change-impact-audit"
    assert projected["change_mode"] == "code_and_docs"
    assert projected["impact_type"] == "boundary_affecting"
    assert projected["follow_up_required"] is True
    # Risk summary capped at 5
    assert len(projected["risk_summary"]) == 5
    assert projected["sync_relevant_flags"]["code_path_governance_required"] is True

    # Long fields stripped
    import json
    assert "long_notes" not in json.dumps(projected)


def test_doc_code_sync_doc_update_plan_projection_wrapped_schema() -> None:
    """doc-code-sync-check projection works with wrapped doc_update_plan."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "change-impact-audit",
        "run_id": "test-run",
        "doc_update_plan": {
            "produced_by": "change-impact-audit",
            "plan_status": "updates_required",
            "required_updates": [
                {
                    "artifact": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
                    "update_type": "terminology_alignment",
                    "priority": "high",
                    "reason": "Very long reason about why this update is needed " * 20,
                    "scope_detail": "Long detail " * 30,
                },
                {
                    "artifact": "README_v1.md",
                    "update_type": "summary_refresh",
                    "priority": "medium",
                    "reason": "Another very long reason " * 20,
                },
            ],
            "verification_actions": [
                {
                    "artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
                    "action": "update_cross_references",
                    "detail": "Long detail " * 30,
                },
            ],
            "rename_controls": {
                "allowed": True,
                "scope": "documentation_only",
                "rename_controls_rationale": "Very long rationale " * 50,
            },
            "code_path_governance": {
                "status": "not_required",
                "affected_paths": [],
                "reason": "Very long reason about code paths " * 30,
            },
            "resolution_prerequisites": [
                "Prereq 1",
                "Prereq 2",
            ],
            "plan_note": "Very long plan note " * 100,
        },
    }

    projected = _project_artifact_payload(
        "doc-code-sync-check", "doc_update_plan", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "change-impact-audit"
    assert projected["plan_status"] == "updates_required"

    # Compact required_updates — only artifact, update_type, priority
    assert len(projected["required_updates"]) == 2
    assert projected["required_updates"][0]["artifact"] == "SYSTEM_TECHNICAL_HANDBOOK_v1.md"
    assert projected["required_updates"][0]["update_type"] == "terminology_alignment"
    assert projected["required_updates"][0]["priority"] == "high"
    assert "reason" not in projected["required_updates"][0]
    assert "scope_detail" not in projected["required_updates"][0]

    # Compact verification_actions — only artifact, action
    assert len(projected["verification_actions"]) == 1
    assert projected["verification_actions"][0]["artifact"] == "DOCUMENTATION_VERIFICATION_MATRIX_v1.md"
    assert projected["verification_actions"][0]["action"] == "update_cross_references"
    assert "detail" not in projected["verification_actions"][0]

    # Rename controls — rationale stripped
    assert projected["rename_controls"]["allowed"] is True
    assert "rename_controls_rationale" not in projected["rename_controls"]

    # Code path governance — reason stripped
    assert projected["code_path_governance"]["status"] == "not_required"
    assert "reason" not in projected["code_path_governance"]

    assert projected["resolution_prerequisites"] == ["Prereq 1", "Prereq 2"]

    # Long fields stripped
    import json
    serialized = json.dumps(projected)
    assert "plan_note" not in serialized
    assert "Very long reason" not in serialized
    assert "Very long rationale" not in serialized
    assert "run_id" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.3, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_doc_code_sync_doc_update_plan_projection_flat_schema() -> None:
    """doc-code-sync-check projection works with top-level doc_update_plan fields."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "change-impact-audit",
        "plan_status": "no_updates_required",
        "required_updates": [],
        "verification_actions": [],
        "resolution_prerequisites": ["A" * 100] * 8,
        "long_narrative": "Very long text " * 200,
    }

    projected = _project_artifact_payload(
        "doc-code-sync-check", "doc_update_plan", full_payload,
    )

    assert projected is not full_payload
    assert projected["plan_status"] == "no_updates_required"
    assert projected["required_updates"] == []
    assert projected["verification_actions"] == []
    # Resolution prerequisites capped at 5
    assert len(projected["resolution_prerequisites"]) == 5

    import json
    assert "long_narrative" not in json.dumps(projected)


def test_doc_code_sync_minimal_payload_passthrough() -> None:
    """V1 shell minimal payloads pass through doc-code-sync transforms unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal_cir = {"produced_by": "change-impact-audit"}
    result = _project_artifact_payload(
        "doc-code-sync-check", "change_impact_report", minimal_cir,
    )
    assert result is minimal_cir

    minimal_dup = {"produced_by": "change-impact-audit"}
    result2 = _project_artifact_payload(
        "doc-code-sync-check", "doc_update_plan", minimal_dup,
    )
    assert result2 is minimal_dup


def test_doc_code_sync_projection_log_with_rich_payloads() -> None:
    """_apply_step_projections records original vs projected sizes for doc-code-sync-check."""
    from governance.dag_runner.prompt_assembly import _apply_step_projections

    rich_inputs = {
        "change_impact_report": {
            "produced_by": "change-impact-audit",
            "change_impact_summary": {
                "produced_by": "change-impact-audit",
                "change_mode": "documentation_only",
                "impact_type": "contract_affecting",
                "contributing_categories": ["terminology"],
                "impacted_components": ["layer2"],
                "impacted_docs": ["README_v1.md"],
                "follow_up_required": True,
                "risk_summary": ["x" * 500] * 3,
                "long_explanation": "x" * 5000,
                "detailed_notes": ["x" * 3000, "x" * 3000],
            },
        },
        "doc_update_plan": {
            "produced_by": "change-impact-audit",
            "doc_update_plan": {
                "produced_by": "change-impact-audit",
                "plan_status": "updates_required",
                "required_updates": [
                    {
                        "artifact": "README_v1.md",
                        "update_type": "refresh",
                        "priority": "high",
                        "reason": "x" * 3000,
                    },
                ],
                "verification_actions": [
                    {"artifact": "MATRIX.md", "action": "update", "detail": "x" * 2000},
                ],
                "rename_controls": {
                    "allowed": True,
                    "rename_controls_rationale": "x" * 3000,
                },
                "code_path_governance": {
                    "status": "not_required",
                    "affected_paths": [],
                    "reason": "x" * 3000,
                },
                "plan_note": "x" * 5000,
            },
        },
        "governance_context": {"produced_by": "load-context", "run_id": "test"},
    }

    projected, log = _apply_step_projections("doc-code-sync-check", rich_inputs)

    # Two artifacts should be projected
    assert len(log) == 2
    projected_names = {entry["artifact"] for entry in log}
    assert projected_names == {"change_impact_report", "doc_update_plan"}

    # Each log entry must have size fields and show reduction
    for entry in log:
        assert entry["original_chars"] > 0
        assert entry["projected_chars"] > 0
        assert entry["original_tokens"] > 0
        assert entry["projected_tokens"] > 0
        assert entry["projected_chars"] < entry["original_chars"], (
            f"{entry['artifact']}: projected {entry['projected_chars']} >= "
            f"original {entry['original_chars']}"
        )

    # governance_context should pass through unchanged
    assert projected["governance_context"] is rich_inputs["governance_context"]


def test_doc_code_sync_projection_metadata(pipeline) -> None:
    """doc-code-sync-check prompt composition includes projection diagnostic fields."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["doc-code-sync-check"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # Projection metadata keys must be present
    assert "projected_artifact_names" in meta
    assert "input_contributions_original" in meta
    assert "input_contributions_projected" in meta
    assert isinstance(meta["projected_artifact_names"], list)
    assert isinstance(meta["input_contributions_original"], dict)
    assert isinstance(meta["input_contributions_projected"], dict)


# ── Regression guard: other step transforms unaltered ──


def test_other_step_transforms_not_altered() -> None:
    """Verify that doc-code-sync-check patch does not alter transforms for other steps."""
    from governance.dag_runner.prompt_assembly import _STEP_INPUT_TRANSFORMS

    # change-impact-audit must NOT have any transforms registered
    assert "change-impact-audit" not in _STEP_INPUT_TRANSFORMS

    # deep-audit must still have exactly the same 6 artifact transforms
    deep_audit = _STEP_INPUT_TRANSFORMS["deep-audit"]
    assert set(deep_audit.keys()) == {
        "claim_classification_map",
        "role_citation_verdict",
        "phase_alignment_status",
        "contract_compliance_verdict",
        "runtime_boundary_verdict",
        "adapter_schema_verdict",
    }

    # phase-check must still have exactly 2 artifact transforms
    phase_check = _STEP_INPUT_TRANSFORMS["phase-check"]
    assert set(phase_check.keys()) == {
        "claim_classification_map",
        "role_citation_verdict",
    }

    # snapshot-contract-check must still have exactly 2 artifact transforms
    scc = _STEP_INPUT_TRANSFORMS["snapshot-contract-check"]
    assert set(scc.keys()) == {
        "role_citation_verdict",
        "phase_alignment_status",
    }

    # doc-code-sync-check must have exactly 2 artifact transforms
    dcs = _STEP_INPUT_TRANSFORMS["doc-code-sync-check"]
    assert set(dcs.keys()) == {
        "change_impact_report",
        "doc_update_plan",
    }

    # update-verification-matrix must have exactly 3 artifact transforms
    uvm = _STEP_INPUT_TRANSFORMS["update-verification-matrix"]
    assert set(uvm.keys()) == {
        "audit_summary",
        "change_impact_report",
        "doc_code_sync_status",
    }


# ── update-verification-matrix artifact projection ──


def test_verification_matrix_audit_summary_projection_rich() -> None:
    """update-verification-matrix projection keeps audit status/violations, drops narratives."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "deep-audit",
        "audit_summary": {
            "produced_by": "deep-audit",
            "overall_audit_status": "blocked",
            "fail_closed_applied": True,
            "dag_advancement_blocked": True,
            "unresolved_violations_count": 3,
            "blocking_violations_count": 2,
            "review_required_violations_count": 1,
            "dispatched_subagents": ["snapshot-boundary-auditor"],
            "critical_path": "snapshot_contract",
            "upstream_violations_consolidated": [
                {
                    "id": "V-01",
                    "source": "runtime-boundary-check",
                    "status": "blocking",
                    "blocking": True,
                    "review_required": False,
                    "routed_to": "snapshot-boundary-auditor",
                    "detail": "Very long detail " * 50,
                    "evidence": "Very long evidence " * 50,
                },
                {
                    "id": "V-02",
                    "source": "adapter-schema-check",
                    "status": "review_only",
                    "blocking": False,
                    "review_required": True,
                    "routed_to": None,
                    "detail": "Another long detail " * 50,
                },
            ],
            "audit_resolution_required": [
                "Fix snapshot boundary violation",
                "Review adapter schema drift",
            ],
            "subagent_findings": [
                {
                    "agent": "snapshot-boundary-auditor",
                    "findings": "Very long findings narrative " * 100,
                    "evidence_items": ["x" * 3000, "x" * 3000],
                },
            ],
            "dispatch_evaluation": "Long dispatch evaluation text " * 100,
            "expected_audit_scope": "Very long expected audit scope prose " * 100,
        },
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "deep-audit"
    assert projected["overall_audit_status"] == "blocked"
    assert projected["fail_closed_applied"] is True
    assert projected["dag_advancement_blocked"] is True
    assert projected["unresolved_violations_count"] == 3
    assert projected["blocking_violations_count"] == 2
    assert projected["review_required_violations_count"] == 1
    assert projected["dispatched_subagents"] == ["snapshot-boundary-auditor"]
    assert projected["critical_path"] == "snapshot_contract"

    # Compact violations — only routing fields
    uvc = projected["upstream_violations_consolidated"]
    assert len(uvc) == 2
    assert uvc[0]["id"] == "V-01"
    assert uvc[0]["source"] == "runtime-boundary-check"
    assert uvc[0]["blocking"] is True
    assert "detail" not in uvc[0]
    assert "evidence" not in uvc[0]

    assert projected["audit_resolution_required"] == [
        "Fix snapshot boundary violation",
        "Review adapter schema drift",
    ]

    # Narratives stripped
    import json
    serialized = json.dumps(projected)
    assert "subagent_findings" not in serialized
    assert "dispatch_evaluation" not in serialized
    assert "expected_audit_scope" not in serialized
    assert "Very long findings" not in serialized

    # Size reduction
    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.15, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_verification_matrix_audit_summary_projection_flat() -> None:
    """update-verification-matrix projection works with flat audit_summary."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "deep-audit",
        "overall_audit_status": "pass",
        "fail_closed_applied": False,
        "dag_advancement_blocked": False,
        "unresolved_violations_count": 0,
        "blocking_violations_count": 0,
        "review_required_violations_count": 0,
        "dispatched_subagents": [],
        "critical_path": None,
        "subagent_findings": [
            {"agent": "a", "findings": "x" * 5000},
        ],
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "deep-audit"
    assert projected["overall_audit_status"] == "pass"
    assert projected["fail_closed_applied"] is False
    assert "subagent_findings" not in projected


def test_verification_matrix_audit_summary_minimal_passthrough() -> None:
    """V1 shell minimal payloads pass through unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal = {"produced_by": "deep-audit"}
    result = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", minimal,
    )
    assert result is minimal


def test_verification_matrix_change_impact_projection_wrapped() -> None:
    """update-verification-matrix projection works with wrapped change_impact_summary."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "change-impact-audit",
        "run_id": "test-run",
        "change_impact_summary": {
            "produced_by": "change-impact-audit",
            "change_mode": "documentation_only",
            "impact_type": "contract_affecting",
            "contributing_categories": ["terminology"],
            "impacted_components": ["layer2"],
            "impacted_docs": ["README_v1.md", "SYSTEM_TECHNICAL_HANDBOOK_v1.md"],
            "follow_up_required": True,
            "risk_summary": ["Risk " * 10] * 8,
            "verification_update_required": True,
            "canonical_docs_impacted": True,
            "constitutional_doc_impacted": False,
            "blocked_change": False,
            "long_explanation": "Very long text " * 200,
            "detailed_notes": ["Long note " * 100],
        },
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "change_impact_report", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "change-impact-audit"
    assert projected["change_mode"] == "documentation_only"
    assert projected["impact_type"] == "contract_affecting"
    assert projected["impacted_docs"] == ["README_v1.md", "SYSTEM_TECHNICAL_HANDBOOK_v1.md"]
    assert projected["follow_up_required"] is True
    assert len(projected["risk_summary"]) == 5  # capped
    assert projected["matrix_relevant_flags"]["verification_update_required"] is True
    assert projected["matrix_relevant_flags"]["canonical_docs_impacted"] is True

    import json
    serialized = json.dumps(projected)
    assert "long_explanation" not in serialized
    assert "detailed_notes" not in serialized
    assert "run_id" not in serialized

    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.4, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_verification_matrix_change_impact_projection_flat() -> None:
    """update-verification-matrix projection works with top-level change_impact_report."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "change-impact-audit",
        "change_mode": "code_and_docs",
        "impact_type": "boundary_affecting",
        "contributing_categories": ["snapshot_contract"],
        "impacted_components": ["quality_gate"],
        "impacted_docs": ["SYSTEM_TECHNICAL_HANDBOOK_v1.md"],
        "follow_up_required": True,
        "risk_summary": ["Risk " * 10] * 3,
        "verification_update_required": True,
        "long_notes": "Very long narrative " * 200,
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "change_impact_report", full_payload,
    )

    assert projected is not full_payload
    assert projected["change_mode"] == "code_and_docs"
    assert projected["impact_type"] == "boundary_affecting"
    assert projected["follow_up_required"] is True
    assert projected["matrix_relevant_flags"]["verification_update_required"] is True

    import json
    assert "long_notes" not in json.dumps(projected)


def test_verification_matrix_change_impact_minimal_passthrough() -> None:
    """V1 shell minimal payloads pass through unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal = {"produced_by": "change-impact-audit"}
    result = _project_artifact_payload(
        "update-verification-matrix", "change_impact_report", minimal,
    )
    assert result is minimal


def test_verification_matrix_doc_code_sync_projection_wrapped() -> None:
    """update-verification-matrix projection works with wrapped doc_code_sync_status."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "doc-code-sync-check",
        "run_id": "test-run",
        "doc_code_sync_status": {
            "produced_by": "doc-code-sync-check",
            "overall_status": "drift_detected",
            "drift_detected": True,
            "docs_changed_without_code": True,
            "code_changed_without_docs": False,
            "doc_code_alignment_status": "misaligned",
            "follow_up_required": True,
            "verification_matrix_update_required": True,
            "impacted_docs": ["README_v1.md"],
            "impacted_code_paths": ["layer2/db.py"],
            "blocking_reasons": ["Doc drift detected in snapshot boundary section"],
            "required_actions": ["Update README_v1.md"],
            "checked_items": [
                {
                    "item": "snapshot_boundary",
                    "status": "drift",
                    "detail": "Very long detail " * 100,
                    "evidence": "Very long evidence " * 100,
                },
            ],
            "detailed_per_file_notes": ["Long note " * 100, "Another " * 100],
            "full_evidence_bodies": ["x" * 5000, "x" * 5000],
        },
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "doc_code_sync_status", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "doc-code-sync-check"
    assert projected["overall_status"] == "drift_detected"
    assert projected["drift_detected"] is True
    assert projected["docs_changed_without_code"] is True
    assert projected["code_changed_without_docs"] is False
    assert projected["doc_code_alignment_status"] == "misaligned"
    assert projected["follow_up_required"] is True
    assert projected["verification_matrix_update_required"] is True
    assert projected["impacted_docs"] == ["README_v1.md"]
    assert projected["impacted_code_paths"] == ["layer2/db.py"]
    assert projected["blocking_reasons"] == ["Doc drift detected in snapshot boundary section"]
    assert projected["required_actions"] == ["Update README_v1.md"]

    import json
    serialized = json.dumps(projected)
    assert "checked_items" not in serialized
    assert "detailed_per_file_notes" not in serialized
    assert "full_evidence_bodies" not in serialized
    assert "run_id" not in serialized

    orig_size = len(json.dumps(full_payload, indent=2))
    proj_size = len(json.dumps(projected, indent=2))
    assert proj_size < orig_size * 0.15, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_verification_matrix_doc_code_sync_projection_flat() -> None:
    """update-verification-matrix projection works with flat doc_code_sync_status."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "doc-code-sync-check",
        "overall_status": "aligned",
        "drift_detected": False,
        "docs_changed_without_code": False,
        "code_changed_without_docs": False,
        "follow_up_required": False,
        "verification_matrix_update_required": False,
        "checked_items": [
            {"item": "x", "detail": "Very long " * 200},
        ],
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "doc_code_sync_status", full_payload,
    )

    assert projected is not full_payload
    assert projected["overall_status"] == "aligned"
    assert projected["drift_detected"] is False
    assert projected["verification_matrix_update_required"] is False

    import json
    assert "checked_items" not in json.dumps(projected)


def test_verification_matrix_doc_code_sync_minimal_passthrough() -> None:
    """V1 shell minimal payloads pass through unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal = {"produced_by": "doc-code-sync-check"}
    result = _project_artifact_payload(
        "update-verification-matrix", "doc_code_sync_status", minimal,
    )
    assert result is minimal


def test_verification_matrix_projection_log_with_rich_payloads() -> None:
    """_apply_step_projections records original vs projected sizes for update-verification-matrix."""
    from governance.dag_runner.prompt_assembly import _apply_step_projections

    rich_inputs = {
        "audit_summary": {
            "produced_by": "deep-audit",
            "audit_summary": {
                "produced_by": "deep-audit",
                "overall_audit_status": "blocked",
                "fail_closed_applied": True,
                "dag_advancement_blocked": True,
                "unresolved_violations_count": 1,
                "blocking_violations_count": 1,
                "review_required_violations_count": 0,
                "dispatched_subagents": [],
                "critical_path": "snapshot",
                "upstream_violations_consolidated": [
                    {
                        "id": "V-01",
                        "source": "runtime-boundary-check",
                        "status": "blocking",
                        "blocking": True,
                        "review_required": False,
                        "routed_to": None,
                        "detail": "x" * 5000,
                    },
                ],
                "subagent_findings": [
                    {"agent": "a", "findings": "x" * 5000},
                ],
                "dispatch_evaluation": "x" * 3000,
            },
        },
        "change_impact_report": {
            "produced_by": "change-impact-audit",
            "change_impact_summary": {
                "produced_by": "change-impact-audit",
                "change_mode": "documentation_only",
                "impact_type": "contract_affecting",
                "contributing_categories": ["terminology"],
                "impacted_components": ["layer2"],
                "impacted_docs": ["README_v1.md"],
                "follow_up_required": True,
                "risk_summary": ["x" * 500] * 3,
                "long_explanation": "x" * 5000,
            },
        },
        "doc_code_sync_status": {
            "produced_by": "doc-code-sync-check",
            "doc_code_sync_status": {
                "produced_by": "doc-code-sync-check",
                "overall_status": "aligned",
                "drift_detected": False,
                "follow_up_required": False,
                "verification_matrix_update_required": False,
                "checked_items": [
                    {"item": "x", "detail": "x" * 5000},
                ],
                "detailed_per_file_notes": ["x" * 5000],
            },
        },
        # Pass-through artifact
        "governance_context": {"produced_by": "load-context", "run_id": "test"},
    }

    projected, log = _apply_step_projections(
        "update-verification-matrix", rich_inputs,
    )

    # Three artifacts should be projected
    assert len(log) == 3
    projected_names = {entry["artifact"] for entry in log}
    assert projected_names == {
        "audit_summary",
        "change_impact_report",
        "doc_code_sync_status",
    }

    # Each log entry must have size fields and show reduction
    for entry in log:
        assert entry["original_chars"] > 0
        assert entry["projected_chars"] > 0
        assert entry["original_tokens"] > 0
        assert entry["projected_tokens"] > 0
        assert entry["projected_chars"] < entry["original_chars"], (
            f"{entry['artifact']}: projected {entry['projected_chars']} >= "
            f"original {entry['original_chars']}"
        )

    # governance_context should pass through unchanged
    assert projected["governance_context"] is rich_inputs["governance_context"]


def test_verification_matrix_projection_metadata(pipeline) -> None:
    """update-verification-matrix prompt composition includes projection diagnostic fields."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["update-verification-matrix"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    # Projection metadata keys must be present
    assert "projected_artifact_names" in meta
    assert "input_contributions_original" in meta
    assert "input_contributions_projected" in meta
    assert isinstance(meta["projected_artifact_names"], list)
    assert isinstance(meta["input_contributions_original"], dict)
    assert isinstance(meta["input_contributions_projected"], dict)


# ── audit_summary projection recognises alternative schemas ──


def test_verification_matrix_audit_summary_projection_status_field() -> None:
    """Projection compacts audit_summary using 'status' instead of 'overall_audit_status'."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    payload = {
        "produced_by": "deep-audit",
        "status": "pass",
        "fail_closed_applied": False,
        "dag_advancement_blocked": False,
        "dispatched_subagents": ["agent-a"],
        "subagent_findings": [
            {"agent": "agent-a", "findings": "narrative " * 500},
        ],
        "dispatch_evaluation": "long text " * 500,
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", payload,
    )

    assert projected is not payload
    assert projected["overall_audit_status"] == "pass"
    assert projected["fail_closed_applied"] is False
    assert projected["dispatched_subagents"] == ["agent-a"]
    assert "subagent_findings" not in projected
    assert "dispatch_evaluation" not in projected


def test_verification_matrix_audit_summary_projection_overall_status_field() -> None:
    """Projection compacts audit_summary using 'overall_status'."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    payload = {
        "produced_by": "deep-audit",
        "overall_status": "blocked",
        "dispatched_subagents": ["x"],
        "subagent_findings": [{"findings": "y" * 5000}],
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", payload,
    )

    assert projected is not payload
    assert projected["overall_audit_status"] == "blocked"
    assert "subagent_findings" not in projected


def test_verification_matrix_audit_summary_projection_nested_overall() -> None:
    """Projection compacts audit_summary using nested 'overall' schema."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    payload = {
        "produced_by": "deep-audit",
        "overall": {
            "overall_audit_status": "pass",
            "fail_closed_applied": False,
            "dag_advancement_blocked": False,
            "dispatched_subagents": [],
        },
        "subagent_findings": [{"findings": "x" * 5000}],
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", payload,
    )

    assert projected is not payload
    assert projected["overall_audit_status"] == "pass"
    assert "subagent_findings" not in projected


def test_verification_matrix_audit_summary_never_passthrough_real_artifact() -> None:
    """Projection never returns full payload when recognisable audit markers exist."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload
    import json

    # Simulate large audit_summary with dispatched_subagents but no standard status fields
    payload = {
        "produced_by": "deep-audit",
        "dispatched_subagents": ["agent-a", "agent-b"],
        "subagent_findings": [
            {"agent": "agent-a", "findings": "Very long findings " * 500},
        ],
        "dispatch_evaluation": "Very long text " * 500,
        "expected_audit_scope": "More long text " * 500,
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", payload,
    )

    assert projected is not payload
    proj_size = len(json.dumps(projected))
    orig_size = len(json.dumps(payload))
    assert proj_size < orig_size * 0.5, (
        f"Projection did not compact: {proj_size} vs {orig_size}"
    )


def test_verification_matrix_audit_summary_caps_dispatched_subagents() -> None:
    """dispatched_subagents is capped at 10 entries."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    payload = {
        "produced_by": "deep-audit",
        "overall_audit_status": "pass",
        "dispatched_subagents": [f"agent-{i}" for i in range(25)],
    }

    projected = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", payload,
    )

    assert len(projected["dispatched_subagents"]) == 10


# ── update-verification-ledger artifact projections ──


def test_verification_ledger_transforms_registered() -> None:
    """update-verification-ledger must have exactly 4 artifact transforms."""
    from governance.dag_runner.prompt_assembly import _STEP_INPUT_TRANSFORMS

    uvl = _STEP_INPUT_TRANSFORMS["update-verification-ledger"]
    assert set(uvl.keys()) == {
        "verification_matrix_delta",
        "doc_code_sync_status",
        "change_impact_report",
        "audit_summary",
    }


def test_verification_ledger_matrix_delta_projection() -> None:
    """update-verification-ledger projection compacts verification_matrix_delta."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "update-verification-matrix",
        "matrix_action": "no_change",
        "classification_dispute_detected": False,
        "runtime_status_upgrade_blocked": False,
        "source_authority_conflict_detected": False,
        "inference_used": False,
        "affected_entries": [
            {
                "entry_id": f"entry-{i}",
                "section": "Layer-2",
                "claim_or_topic": f"Claim {i}",
                "change_type": "evidence_upgrade",
                "confidence": "high",
                "long_rationale": "Very long text " * 200,
                "evidence_body": "x" * 5000,
            }
            for i in range(20)
        ],
        "required_follow_up": [f"action-{i}" for i in range(15)],
        "notes": [f"note-{i}" for i in range(15)],
        "detailed_analysis": "Very verbose " * 500,
    }

    projected = _project_artifact_payload(
        "update-verification-ledger", "verification_matrix_delta", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "update-verification-matrix"
    assert projected["matrix_action"] == "no_change"
    assert projected["classification_dispute_detected"] is False
    # Affected entries capped at 10 and compact
    assert len(projected["affected_entries"]) == 10
    assert "long_rationale" not in projected["affected_entries"][0]
    assert "evidence_body" not in projected["affected_entries"][0]
    assert projected["affected_entries"][0]["entry_id"] == "entry-0"
    # required_follow_up capped at 10
    assert len(projected["required_follow_up"]) == 10
    # notes capped at 10
    assert len(projected["notes"]) == 10
    # Verbose field dropped
    assert "detailed_analysis" not in projected


def test_verification_ledger_matrix_delta_passthrough_minimal() -> None:
    """V1 shell minimal payload passes through unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal = {"produced_by": "update-verification-matrix"}
    result = _project_artifact_payload(
        "update-verification-ledger", "verification_matrix_delta", minimal,
    )
    # Minimal payload with only produced_by still gets projected (has produced_by)
    assert result["produced_by"] == "update-verification-matrix"


def test_verification_ledger_doc_code_sync_projection() -> None:
    """update-verification-ledger projection compacts doc_code_sync_status."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "doc-code-sync-check",
        "doc_code_sync_status": {
            "produced_by": "doc-code-sync-check",
            "overall_status": "drift_detected",
            "drift_detected": True,
            "docs_changed_without_code": True,
            "code_changed_without_docs": False,
            "doc_code_alignment_status": "misaligned",
            "follow_up_required": "mandatory",
            "verification_ledger_update_required": True,
            "impacted_docs": [f"doc-{i}.md" for i in range(15)],
            "impacted_code_paths": [f"path/{i}.py" for i in range(15)],
            "required_actions": [f"action-{i}" for i in range(15)],
            "blocking_reasons": [f"reason-{i}" for i in range(15)],
            "checked_items": [{"item": "x", "detail": "y" * 5000}],
            "full_evidence": "z" * 10000,
        },
    }

    projected = _project_artifact_payload(
        "update-verification-ledger", "doc_code_sync_status", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "doc-code-sync-check"
    assert projected["overall_status"] == "drift_detected"
    assert projected["drift_detected"] is True
    assert projected["verification_ledger_update_required"] is True
    # Capped at 10
    assert len(projected["impacted_docs"]) == 10
    assert len(projected["impacted_code_paths"]) == 10
    assert len(projected["required_actions"]) == 10
    assert len(projected["blocking_reasons"]) == 10
    # Verbose fields dropped
    assert "checked_items" not in projected
    assert "full_evidence" not in projected


def test_verification_ledger_doc_code_sync_flat_projection() -> None:
    """update-verification-ledger projection works with flat doc_code_sync_status."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "doc-code-sync-check",
        "overall_status": "aligned",
        "drift_detected": False,
        "follow_up_required": "none",
    }

    projected = _project_artifact_payload(
        "update-verification-ledger", "doc_code_sync_status", full_payload,
    )

    assert projected is not full_payload
    assert projected["overall_status"] == "aligned"
    assert projected["drift_detected"] is False


def test_verification_ledger_change_impact_projection() -> None:
    """update-verification-ledger projection compacts change_impact_report."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "change-impact-audit",
        "change_impact_summary": {
            "produced_by": "change-impact-audit",
            "change_mode": "documentation_only",
            "impact_type": "documentation",
            "contributing_categories": ["doc"],
            "follow_up_required": "advisory",
            "impacted_components": [f"comp-{i}" for i in range(15)],
            "impacted_docs": [f"doc-{i}.md" for i in range(15)],
            "verification_actions": [
                {"artifact": f"art-{i}", "action": "update", "reason": "x" * 500}
                for i in range(15)
            ],
            "risk_summary": [f"risk-{i}" for i in range(10)],
            "verification_ledger_update_required": True,
            "blocked_change": False,
            "doc_only_change": True,
            "detailed_notes": ["Very long note " * 200],
        },
    }

    projected = _project_artifact_payload(
        "update-verification-ledger", "change_impact_report", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "change-impact-audit"
    assert projected["change_mode"] == "documentation_only"
    assert projected["follow_up_required"] == "advisory"
    # Capped at 10
    assert len(projected["impacted_components"]) == 10
    assert len(projected["impacted_docs"]) == 10
    assert len(projected["verification_actions"]) == 10
    # Verification actions compact — no reason field
    assert "reason" not in projected["verification_actions"][0]
    assert projected["verification_actions"][0]["artifact"] == "art-0"
    # Risk summary capped at 5
    assert len(projected["risk_summary"]) == 5
    # Ledger-relevant flags preserved
    assert projected["verification_ledger_update_required"] is True
    assert projected["doc_only_change"] is True
    # Verbose field dropped
    assert "detailed_notes" not in projected


def test_verification_ledger_change_impact_flat_projection() -> None:
    """update-verification-ledger projection works with flat change_impact_report."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    full_payload = {
        "produced_by": "change-impact-audit",
        "change_mode": "code_and_docs",
        "impact_type": "mixed",
        "follow_up_required": "mandatory",
        "impacted_components": ["snapshot_publisher"],
    }

    projected = _project_artifact_payload(
        "update-verification-ledger", "change_impact_report", full_payload,
    )

    assert projected is not full_payload
    assert projected["change_mode"] == "code_and_docs"
    assert projected["impacted_components"] == ["snapshot_publisher"]


def test_verification_ledger_audit_summary_projection() -> None:
    """update-verification-ledger projection compacts audit_summary."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload
    import json

    full_payload = {
        "produced_by": "deep-audit",
        "audit_summary": {
            "overall_audit_status": "pass",
            "fail_closed_applied": False,
            "dag_advancement_blocked": False,
            "unresolved_violations_count": 0,
            "blocking_violations_count": 0,
            "review_required_violations_count": 1,
            "dispatched_subagents": [f"agent-{i}" for i in range(15)],
            "findings": [
                {"id": f"f-{i}", "detail": "x" * 500, "full_text": "y" * 5000}
                for i in range(15)
            ],
            "audit_resolution_required": [f"res-{i}" for i in range(15)],
            "dispatch_evaluation": "Very long text " * 500,
            "expected_audit_scope": "More long text " * 500,
        },
    }

    projected = _project_artifact_payload(
        "update-verification-ledger", "audit_summary", full_payload,
    )

    assert projected is not full_payload
    assert projected["produced_by"] == "deep-audit"
    assert projected["overall_audit_status"] == "pass"
    assert projected["dag_advancement_blocked"] is False
    # dispatched_subagents capped at 10
    assert len(projected["dispatched_subagents"]) == 10
    # findings capped at 10, strings truncated, full_text dropped
    assert len(projected["findings"]) == 10
    assert "full_text" not in projected["findings"][0]
    assert len(projected["findings"][0]["detail"]) == 200
    # audit_resolution_required capped at 10
    assert len(projected["audit_resolution_required"]) == 10
    # Verbose fields dropped
    assert "dispatch_evaluation" not in projected
    assert "expected_audit_scope" not in projected

    # Size reduction
    orig_size = len(json.dumps(full_payload))
    proj_size = len(json.dumps(projected))
    assert proj_size < orig_size * 0.5, (
        f"Projection did not reduce size enough: {proj_size} vs {orig_size}"
    )


def test_verification_ledger_audit_summary_passthrough_minimal() -> None:
    """V1 shell minimal audit payloads pass through unchanged."""
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    minimal = {"produced_by": "deep-audit"}
    result = _project_artifact_payload(
        "update-verification-ledger", "audit_summary", minimal,
    )
    assert result is minimal


def test_verification_ledger_no_change_shortcut_in_skill() -> None:
    """Ledger SKILL.md contains the no-change shortcut pattern."""
    skill_path = _REPO_ROOT / ".claude" / "skills" / "verification-ledger-update" / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")
    assert "no_change" in content.lower() or "no-change" in content.lower()
    assert '"ledger_action": "no_change"' in content
    assert "matrix_action" in content


def test_verification_ledger_agent_timeout_loaded() -> None:
    """verification-ledger-agent timeout_ms is 240000 in agents.yaml."""
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.assembler import assemble_workflow_spec

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    assert "verification-ledger-agent" in spec.agents
    agent = spec.agents["verification-ledger-agent"]
    assert agent.raw.get("timeout_ms") == 240000


def test_matrix_and_ledger_skill_bindings_separated() -> None:
    """Matrix and ledger agents have distinct, non-overlapping skill bindings."""
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.assembler import assemble_workflow_spec

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)

    assert "verification-matrix-agent" in spec.agents
    assert "verification-ledger-agent" in spec.agents
    matrix_agent = spec.agents["verification-matrix-agent"]
    ledger_agent = spec.agents["verification-ledger-agent"]
    # Skill bindings must not overlap
    matrix_skills = set(matrix_agent.skill_bindings)
    ledger_skills = set(ledger_agent.skill_bindings)
    assert matrix_skills & ledger_skills == set(), (
        f"Overlapping skill bindings: {matrix_skills & ledger_skills}"
    )
    # Each bound to its own skill
    assert "verification-matrix-update-method" in matrix_skills
    assert "verification-ledger-update" in ledger_skills


def test_verification_ledger_projection_log(pipeline) -> None:
    """update-verification-ledger prompt composition includes projection diagnostics."""
    spec, plan, run_state = pipeline
    step = spec.workflow_steps["update-verification-ledger"]
    ctx = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    meta = build_prompt_composition_metadata(ctx)

    assert "projected_artifact_names" in meta


def test_existing_matrix_projections_still_work() -> None:
    """Existing update-verification-matrix transforms still registered and functional."""
    from governance.dag_runner.prompt_assembly import (
        _STEP_INPUT_TRANSFORMS,
        _project_artifact_payload,
    )

    uvm = _STEP_INPUT_TRANSFORMS["update-verification-matrix"]
    assert set(uvm.keys()) == {
        "audit_summary",
        "change_impact_report",
        "doc_code_sync_status",
    }

    # Quick smoke: minimal payload passes through
    minimal = {"produced_by": "deep-audit"}
    result = _project_artifact_payload(
        "update-verification-matrix", "audit_summary", minimal,
    )
    assert result is minimal


# ── deep-audit deterministic synthesis ──


def test_deep_audit_is_structural() -> None:
    """deep-audit (subagents component) is now a structural step — no LLM invocation."""
    from governance.dag_runner.executor import _STRUCTURAL_KINDS, _BACKEND_KINDS

    assert "subagents" in _STRUCTURAL_KINDS
    assert "subagents" not in _BACKEND_KINDS


def test_deep_audit_no_escalation_signals() -> None:
    """No escalation signals -> audit_action no_audit_required."""
    from governance.dag_runner.executor import _synthesize_audit_summary
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="deep-audit",
        component="subagents",
        raw={"inputs": ["role_citation_verdict", "phase_alignment_status"]},
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # Add clean upstream artifacts
    run_state.artifacts["role_citation_verdict"] = ArtifactRecord(
        name="role_citation_verdict",
        producer_step="role-citation-check",
        status="present",
        payload={"produced_by": "role-citation-check", "overall_status": "pass"},
    )
    run_state.artifacts["phase_alignment_status"] = ArtifactRecord(
        name="phase_alignment_status",
        producer_step="phase-check",
        status="present",
        payload={"produced_by": "phase-check", "allowed": True, "alignment_status": "within_current_phase"},
    )

    result = _synthesize_audit_summary(step, run_state)

    assert result["produced_by"] == "deep-audit"
    assert result["audit_action"] == "no_audit_required"
    assert result["overall_audit_status"] == "pass"
    assert result["dag_advancement_blocked"] is False
    assert result["findings"] == []
    assert result["blocking_violations_count"] == 0


def test_deep_audit_blocking_signal() -> None:
    """Blocking escalation signal -> audit_action blocked."""
    from governance.dag_runner.executor import _synthesize_audit_summary
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="deep-audit",
        component="subagents",
        raw={"inputs": ["runtime_boundary_verdict", "adapter_schema_verdict"]},
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["runtime_boundary_verdict"] = ArtifactRecord(
        name="runtime_boundary_verdict",
        producer_step="runtime-boundary-check",
        status="present",
        payload={
            "produced_by": "runtime-boundary-check",
            "boundary_violation_suspected": True,
            "forbidden_access_detected": True,
        },
    )
    run_state.artifacts["adapter_schema_verdict"] = ArtifactRecord(
        name="adapter_schema_verdict",
        producer_step="adapter-schema-check",
        status="present",
        payload={"produced_by": "adapter-schema-check", "overall_status": "pass"},
    )

    result = _synthesize_audit_summary(step, run_state)

    assert result["produced_by"] == "deep-audit"
    assert result["audit_action"] == "blocked"
    assert result["overall_audit_status"] == "blocked"
    assert result["dag_advancement_blocked"] is True
    assert result["blocking_violations_count"] >= 1
    assert len(result["findings"]) >= 1
    # Check finding structure
    finding = result["findings"][0]
    assert "source_artifact" in finding
    assert "signal" in finding
    assert "severity" in finding
    assert "summary" in finding


def test_deep_audit_review_signal() -> None:
    """Review-only escalation signal -> synthesize_from_signals, review_only."""
    from governance.dag_runner.executor import _synthesize_audit_summary
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="deep-audit",
        component="subagents",
        raw={"inputs": ["role_citation_verdict"]},
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["role_citation_verdict"] = ArtifactRecord(
        name="role_citation_verdict",
        producer_step="role-citation-check",
        status="present",
        payload={
            "produced_by": "role-citation-check",
            "overall_status": "review_only",
            "source_authority_conflict_detected": True,
        },
    )

    result = _synthesize_audit_summary(step, run_state)

    assert result["produced_by"] == "deep-audit"
    assert result["overall_audit_status"] in ("review_only", "blocked")
    assert result["review_required_violations_count"] >= 1


def test_deep_audit_findings_capped_at_10() -> None:
    """Findings are capped at 10 entries."""
    from governance.dag_runner.executor import _synthesize_audit_summary
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="deep-audit",
        component="subagents",
        raw={"inputs": ["art1", "art2", "art3", "art4"]},
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # Each artifact has 3+ signals => >10 total findings
    for i in range(4):
        run_state.artifacts[f"art{i+1}"] = ArtifactRecord(
            name=f"art{i+1}",
            producer_step=f"step-{i}",
            status="present",
            payload={
                "produced_by": f"step-{i}",
                "source_authority_conflict_detected": True,
                "classification_dispute_detected": True,
                "boundary_violation_suspected": True,
                "registry_violation_detected": True,
            },
        )

    result = _synthesize_audit_summary(step, run_state)

    assert len(result["findings"]) <= 10


def test_deep_audit_no_claude_invocation_in_mock_backend() -> None:
    """deep-audit does not invoke Claude backend in agent_execution mode."""
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.validator import validate_or_raise
    from governance.dag_runner.planner import build_execution_plan
    from governance.dag_runner.executor import execute_plan
    from governance.dag_runner.execution_backend import MockExecutionBackend
    from governance.dag_runner.models import ExecutionConfig

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)

    config = ExecutionConfig(mode="agent_execution", request_text="Test")
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, verdict_status="ready", config=config, backend=backend)

    # deep-audit should have produced audit_summary
    audit = result.run_state.artifacts.get("audit_summary")
    assert audit is not None
    assert audit.status == "present"
    assert audit.payload["produced_by"] == "deep-audit"
    assert audit.payload["audit_action"] == "no_audit_required"

    # Verify deep-audit node result is PASS (structural)
    deep_audit_result = result.run_state.node_results.get("deep-audit")
    assert deep_audit_result is not None
    assert deep_audit_result.status == "PASS"


def test_governance_context_includes_code_and_runtime_context() -> None:
    """governance_context artifact includes code_context and runtime_context in agent_execution mode."""
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.validator import validate_or_raise
    from governance.dag_runner.planner import build_execution_plan
    from governance.dag_runner.executor import execute_plan
    from governance.dag_runner.execution_backend import MockExecutionBackend
    from governance.dag_runner.models import ExecutionConfig

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)

    config = ExecutionConfig(mode="agent_execution", request_text="Test evidence injection")
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, verdict_status="ready", config=config, backend=backend)

    gc = result.run_state.artifacts.get("governance_context")
    assert gc is not None
    assert gc.status == "present"
    payload = gc.payload

    # Must include code_context and runtime_context
    assert "code_context" in payload
    assert "runtime_context" in payload

    # code_context structure
    cc = payload["code_context"]
    assert "series_registry" in cc
    assert "adapter_inventory" in cc
    assert "layer2_boundary_checks" in cc
    assert "execution_artifact_scan" in cc

    # runtime_context structure
    rc = payload["runtime_context"]
    assert "latest_snapshot" in rc
    assert "layer3_runtime_absent" in rc


def test_deep_audit_agent_instructions_include_no_subagent_calls() -> None:
    """Audit coordinator agent .md includes 'no real subagent calls' constraint."""
    agent_path = _REPO_ROOT / ".claude" / "agents" / "audit-coordinator-agent.md"
    content = agent_path.read_text(encoding="utf-8")
    assert "no real subagent calls" in content.lower()


def test_deep_audit_agent_no_audit_shortcut_present() -> None:
    """Audit coordinator agent .md includes the no-audit shortcut."""
    agent_path = _REPO_ROOT / ".claude" / "agents" / "audit-coordinator-agent.md"
    content = agent_path.read_text(encoding="utf-8")
    assert "no_audit_required" in content


def test_deep_audit_timeout_set() -> None:
    """audit-coordinator-agent has timeout_ms: 240000."""
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.assembler import assemble_workflow_spec

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    assert "audit-coordinator-agent" in spec.agents
    agent = spec.agents["audit-coordinator-agent"]
    assert agent.raw.get("timeout_ms") == 240000


def test_dependency_skip_behavior_preserved() -> None:
    """Steps depending on a failed step are still skipped."""
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.validator import validate_or_raise
    from governance.dag_runner.planner import build_execution_plan
    from governance.dag_runner.executor import execute_plan
    from governance.dag_runner.execution_backend import MockExecutionBackend
    from governance.dag_runner.models import (
        ExecutionConfig,
        GovernanceRunState,
        ArtifactRecord,
        NodeResult,
    )

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)

    config = ExecutionConfig(
        mode="agent_execution",
        request_text="Test",
        continue_from="deep-audit",
    )
    backend = MockExecutionBackend()

    # Build a prior state where deep-audit FAILED
    prior = GovernanceRunState(run_id="test-dep-skip", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    prior.node_results["deep-audit"] = NodeResult(
        node_name="deep-audit",
        node_type="subagents",
        status="FAIL",
        summary="Simulated failure",
        evidence=[],
        produced_artifacts=[],
        triggered_blocks=[],
        inference_used=False,
    )
    # Add minimal artifacts for steps before deep-audit
    for art in ("governance_context", "claim_classification_map",
                "normalized_terminology_map", "role_citation_verdict",
                "phase_alignment_status", "contract_compliance_verdict",
                "stage_gate_report", "guard_report",
                "runtime_boundary_verdict", "adapter_schema_verdict"):
        prior.artifacts[art] = ArtifactRecord(
            name=art, producer_step="test",
            status="present", payload={"produced_by": "test"},
        )

    result = execute_plan(
        spec, plan, verdict_status="ready", config=config, backend=backend,
        prior_state=prior,
    )

    # change-impact-audit depends on deep-audit -> should be SKIP
    cia = result.run_state.node_results.get("change-impact-audit")
    assert cia is not None
    assert cia.status == "SKIP"


# ── doc-code-sync-check deterministic synthesis ──


def test_doc_code_sync_check_no_signals() -> None:
    """No upstream signals -> in_sync."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=["verification_without_evidence"],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # Provide change_impact_report and doc_update_plan with no drift signals
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="change-impact-audit",
        status="present",
        payload={
            "produced_by": "change-impact-audit",
            "change_mode": "documentation",
            "impact_type": "documentation_only",
            "doc_only_change": False,
            "code_path_governance_required": False,
            "blocked_change": False,
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="change-impact-audit",
        status="present",
        payload={
            "produced_by": "change-impact-audit",
            "plan_status": "no_updates_required",
            "required_updates": [],
            "verification_actions": [],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["produced_by"] == "doc-code-sync-check"
    assert result["overall_status"] == "in_sync"
    assert result["sync_status"] == "in_sync"
    assert result["drift_detected"] is False
    assert result["inference_used"] is False
    assert result["doc_code_alignment_status"] == "aligned"
    assert result["follow_up_required"] == "none"


def test_doc_code_sync_check_missing_inputs() -> None:
    """Missing/ambiguous upstream artifacts -> review_only with inference_used=true."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # No upstream artifacts at all

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["overall_status"] == "review_only"
    assert result["sync_status"] == "review_only"
    assert result["inference_used"] is True
    assert result["doc_code_alignment_status"] == "review_required"


def test_doc_code_sync_check_blocked_change() -> None:
    """blocked_change=true -> blocked status."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_mode": "mixed",
            "impact_type": "contract_affecting",
            "blocked_change": True,
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "plan_status": "blocked",
            "required_updates": [],
            "verification_actions": [],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["overall_status"] == "blocked"
    assert result["sync_status"] == "blocked"
    assert result["doc_code_alignment_status"] == "blocked"
    assert result["drift_detected"] is True
    assert result["follow_up_required"] == "mandatory"
    assert len(result["blocking_reasons"]) > 0
    assert result["verification_matrix_update_required"] is True
    assert result["verification_ledger_update_required"] is True


def test_doc_code_sync_check_verification_matrix_action() -> None:
    """Verification action targeting matrix -> verification_matrix_update_required=true."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_mode": "documentation",
            "impact_type": "documentation_only",
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "plan_status": "updates_required",
            "required_updates": [
                {"artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md", "update_type": "review", "priority": "medium"},
            ],
            "verification_actions": [
                {"artifact": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md", "action": "update"},
            ],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["verification_matrix_update_required"] is True
    assert result["overall_status"] == "review_only"
    assert len(result["required_actions"]) > 0


def test_doc_code_sync_check_verification_ledger_action() -> None:
    """Verification action targeting ledger -> verification_ledger_update_required=true."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_mode": "documentation",
            "impact_type": "documentation_only",
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "plan_status": "updates_required",
            "required_updates": [],
            "verification_actions": [
                {"artifact": "verification_ledger.md", "action": "update"},
            ],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["verification_ledger_update_required"] is True


def test_doc_code_sync_check_required_updates_mandatory() -> None:
    """Required updates with high priority -> follow_up mandatory."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_mode": "documentation",
            "impact_type": "documentation_only",
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "plan_status": "updates_required",
            "required_updates": [
                {"artifact": "README_v1.md", "update_type": "update", "priority": "critical"},
            ],
            "verification_actions": [],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["overall_status"] == "review_only"
    assert result["follow_up_required"] == "mandatory"


def test_doc_code_sync_check_doc_only_runtime_claims() -> None:
    """Doc-only change with runtime claims -> drift_detected and review_only."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_mode": "documentation",
            "impact_type": "documentation_only",
            "doc_only_change": True,
            "contributing_categories": ["implementation", "runtime"],
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "plan_status": "no_updates_required",
            "required_updates": [],
            "verification_actions": [],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["docs_changed_without_code"] is True
    assert result["drift_detected"] is True
    assert result["overall_status"] == "review_only"
    assert result["follow_up_required"] == "mandatory"


def test_doc_code_sync_check_doc_only_no_runtime_claims() -> None:
    """Doc-only change without runtime claims -> review_only, no drift."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_mode": "documentation",
            "impact_type": "documentation_only",
            "doc_only_change": True,
            "contributing_categories": ["documentation", "editorial"],
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "plan_status": "no_updates_required",
            "required_updates": [],
            "verification_actions": [],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["docs_changed_without_code"] is True
    assert result["drift_detected"] is False
    assert result["overall_status"] == "review_only"


def test_doc_code_sync_check_code_change_without_docs() -> None:
    """Code/runtime change without docs -> drift_detected=true and mandatory follow-up."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_mode": "code",
            "impact_type": "implementation",
            "doc_only_change": False,
            "code_path_governance_required": True,
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "plan_status": "no_updates_required",
            "required_updates": [],
            "verification_actions": [],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["code_changed_without_docs"] is True
    assert result["drift_detected"] is True
    assert result["overall_status"] == "out_of_sync"
    assert result["follow_up_required"] == "mandatory"
    assert result["doc_code_alignment_status"] == "misaligned"


def test_doc_code_sync_check_arrays_capped() -> None:
    """All arrays are capped at 10."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_mode": "mixed",
            "impact_type": "contract_affecting",
            "impacted_docs": [f"doc_{i}.md" for i in range(20)],
            "impacted_code_paths": [f"path/{i}.py" for i in range(20)],
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "plan_status": "updates_required",
            "required_updates": [
                {"artifact": f"doc_{i}.md", "update_type": "review", "priority": "low"}
                for i in range(20)
            ],
            "verification_actions": [],
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert len(result["impacted_docs"]) <= 10
    assert len(result["impacted_code_paths"]) <= 10
    assert len(result["required_actions"]) <= 10
    assert len(result["blocking_reasons"]) <= 10
    assert len(result["notes"]) <= 10


def test_doc_code_sync_check_wrapped_schema() -> None:
    """Wrapped schema (nested change_impact_summary / doc_update_plan)."""
    from governance.dag_runner.executor import _synthesize_doc_code_sync_status
    from governance.dag_runner.models import WorkflowStep, GovernanceRunState, ArtifactRecord

    step = WorkflowStep(
        name="doc-code-sync-check",
        component="skill:doc-code-sync-rules",
        outputs=["doc_code_sync_status"],
        raises=[],
    )
    run_state = GovernanceRunState(run_id="test", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    run_state.artifacts["change_impact_report"] = ArtifactRecord(
        name="change_impact_report", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "change_impact_summary": {
                "change_mode": "code",
                "impact_type": "implementation",
                "doc_only_change": False,
                "code_path_governance_required": True,
                "impacted_docs": ["README_v1.md"],
                "affected_paths": ["layer2/adapters/fred.py"],
            },
        },
    )
    run_state.artifacts["doc_update_plan"] = ArtifactRecord(
        name="doc_update_plan", producer_step="test",
        status="present",
        payload={
            "produced_by": "test",
            "doc_update_plan": {
                "plan_status": "updates_required",
                "required_updates": [
                    {"artifact": "README_v1.md", "update_type": "update", "priority": "high"},
                ],
                "verification_actions": [
                    {"artifact": "verification_matrix", "action": "review"},
                ],
            },
        },
    )

    result = _synthesize_doc_code_sync_status(step, run_state)

    assert result["code_changed_without_docs"] is True
    assert result["drift_detected"] is True
    assert result["verification_matrix_update_required"] is True
    assert result["impacted_docs"] == ["README_v1.md"]
    assert result["impacted_code_paths"] == ["layer2/adapters/fred.py"]


def test_doc_code_sync_no_claude_invocation_in_mock_backend() -> None:
    """doc-code-sync-check does not invoke Claude backend in agent_execution mode."""
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.validator import validate_or_raise
    from governance.dag_runner.planner import build_execution_plan
    from governance.dag_runner.executor import execute_plan
    from governance.dag_runner.execution_backend import MockExecutionBackend
    from governance.dag_runner.models import ExecutionConfig

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)

    config = ExecutionConfig(mode="agent_execution", request_text="Test")
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, verdict_status="ready", config=config, backend=backend)

    # doc-code-sync-check should have produced doc_code_sync_status
    sync = result.run_state.artifacts.get("doc_code_sync_status")
    assert sync is not None
    assert sync.status == "present"
    assert sync.payload["produced_by"] == "doc-code-sync-check"

    # Verify doc-code-sync-check node result is PASS (structural)
    dcsc_result = result.run_state.node_results.get("doc-code-sync-check")
    assert dcsc_result is not None
    assert dcsc_result.status == "PASS"
    assert dcsc_result.inference_used is False

    # Verify deterministic_synthesis trace event exists
    synth_events = [
        e for e in result.run_state.execution_trace
        if e.event_type == "deterministic_synthesis" and e.node_name == "doc-code-sync-check"
    ]
    assert len(synth_events) == 1
    assert synth_events[0].detail["synthesized_artifact"] == "doc_code_sync_status"


# ── document content injection ──


def test_build_prompt_text_includes_canonical_documents() -> None:
    """build_prompt_text includes [CANONICAL DOCUMENTS] section with content."""
    from governance.dag_runner.prompt_assembly import build_prompt_text

    context = {
        "skill_content": "",
        "agent_instructions": "",
        "artifact_inputs": {},
        "document_paths": ["/repo/README_v1.md"],
        "document_contents": {
            "/repo/README_v1.md": "# README v1\nThis is the project README.",
        },
        "expected_outputs": [],
        "step_name": "test-step",
    }
    text = build_prompt_text(context)
    assert "[CANONICAL DOCUMENTS]" in text
    assert "--- /repo/README_v1.md ---" in text
    assert "This is the project README." in text
    assert "[DOCUMENT PATHS]" not in text


def test_build_prompt_text_fallback_to_paths() -> None:
    """Falls back to [DOCUMENT PATHS] when no document_contents."""
    from governance.dag_runner.prompt_assembly import build_prompt_text

    context = {
        "skill_content": "",
        "agent_instructions": "",
        "artifact_inputs": {},
        "document_paths": ["/repo/README_v1.md"],
        "document_contents": {},
        "expected_outputs": [],
        "step_name": "test-step",
    }
    text = build_prompt_text(context)
    assert "[DOCUMENT PATHS]" in text
    assert "[CANONICAL DOCUMENTS]" not in text


def test_build_prompt_text_no_docs_section_when_empty() -> None:
    """No document section when both paths and contents are empty."""
    from governance.dag_runner.prompt_assembly import build_prompt_text

    context = {
        "skill_content": "",
        "agent_instructions": "",
        "artifact_inputs": {},
        "document_paths": [],
        "document_contents": {},
        "expected_outputs": [],
        "step_name": "test-step",
    }
    text = build_prompt_text(context)
    assert "[DOCUMENT PATHS]" not in text
    assert "[CANONICAL DOCUMENTS]" not in text


def test_assemble_step_prompt_populates_document_contents(pipeline) -> None:
    """assemble_step_prompt includes document_contents in returned dict."""
    spec, _plan, run_state = pipeline

    # Find a step that consumes documents
    step = spec.workflow_steps.get("classify-claims")
    if step is None:
        pytest.skip("classify-claims step not found")

    result = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)
    # document_contents should be a dict (possibly empty if no docs found)
    assert "document_contents" in result
    assert isinstance(result["document_contents"], dict)


# ── Claim ID propagation regression tests ──


def test_route_claims_by_role_receives_full_claims() -> None:
    """route-claims-by-role must receive all claim IDs from claim_classification_map.

    Regression: previously the field-list projection stripped the nested
    request_classification.claims structure, leaving only produced_by metadata.
    """
    from governance.dag_runner.prompt_assembly import _project_artifact_payload

    # Simulate the real artifact payload shape
    full_payload = {
        "produced_by": "classify-claims",
        "request_classification": {
            "request_type": "documentation_synchronization",
            "claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "SP500 history gap fix completed",
                    "claim_scope": "current-state",
                    "evidence_class": "documented_current_state_claim",
                    "source_priority": ["SYSTEM_IMPLEMENTATION_RECORD_v1.md"],
                    "classification_rationale": "Long rationale " * 20,
                    "notes": ["note 1"],
                },
                {
                    "claim_id": "c2",
                    "claim_text": "Layer-2 TODO items completed",
                    "claim_scope": "current-state",
                    "evidence_class": "documented_current_state_claim",
                    "source_priority": ["SYSTEM_IMPLEMENTATION_RECORD_v1.md"],
                    "classification_rationale": "Another long rationale " * 20,
                    "notes": ["note 2"],
                },
                {
                    "claim_id": "c3",
                    "claim_text": "Documentation requires alignment",
                    "claim_scope": "current-state",
                    "evidence_class": "documented_current_state_claim",
                    "source_priority": ["DOCUMENTATION_VERIFICATION_MATRIX_v1.md"],
                    "classification_rationale": "Rationale " * 10,
                },
            ],
            "summary": {
                "dominant_scope": "current-state",
                "touches_current_truth": True,
                "touches_target_architecture": False,
            },
        },
        "classification_notes": ["note"],
    }

    projected = _project_artifact_payload(
        "route-claims-by-role", "claim_classification_map", full_payload,
    )

    # Must have request_classification with claims
    assert "request_classification" in projected, (
        "request_classification stripped — claim IDs will be lost downstream"
    )
    rc = projected["request_classification"]
    assert "claims" in rc
    claims = rc["claims"]
    assert len(claims) == 3

    # All claim IDs must be present
    claim_ids = [c["claim_id"] for c in claims]
    assert claim_ids == ["c1", "c2", "c3"]

    # claim_text and source_priority must be preserved
    assert claims[0]["claim_text"] == "SP500 history gap fix completed"
    assert "SYSTEM_IMPLEMENTATION_RECORD_v1.md" in claims[0]["source_priority"]

    # classification_rationale should be stripped (verbose)
    for c in claims:
        assert "classification_rationale" not in c

    # Summary must be preserved
    assert rc["summary"]["dominant_scope"] == "current-state"


def test_claim_id_contract_section_in_prompt() -> None:
    """Prompt text includes [CLAIM ID CONTRACT] when upstream claim IDs exist."""
    from governance.dag_runner.prompt_assembly import build_prompt_text

    context = {
        "skill_content": "",
        "agent_instructions": "",
        "artifact_inputs": {
            "claim_classification_map": {
                "produced_by": "classify-claims",
                "request_classification": {
                    "claims": [
                        {"claim_id": "c1", "claim_text": "test"},
                        {"claim_id": "c2", "claim_text": "test2"},
                    ],
                },
            },
        },
        "document_contents": {},
        "document_paths": [],
        "expected_outputs": ["role_citation_verdict"],
        "step_name": "route-claims-by-role",
    }

    text = build_prompt_text(context)
    assert "[CLAIM ID CONTRACT]" in text
    assert "c1, c2" in text
    assert "Do NOT invent new claim ID schemes" in text


def test_no_claim_id_contract_when_no_claims() -> None:
    """Prompt text does NOT include [CLAIM ID CONTRACT] when no claims upstream."""
    from governance.dag_runner.prompt_assembly import build_prompt_text

    context = {
        "skill_content": "",
        "agent_instructions": "",
        "artifact_inputs": {
            "governance_context": {"produced_by": "load-context"},
        },
        "document_contents": {},
        "document_paths": [],
        "expected_outputs": ["claim_classification_map"],
        "step_name": "classify-claims",
    }

    text = build_prompt_text(context)
    assert "[CLAIM ID CONTRACT]" not in text


# ── code_context/runtime_context propagation regression tests ──


def test_runtime_boundary_check_receives_code_context(pipeline) -> None:
    """runtime-boundary-check must receive code_context from governance_context."""
    spec, _plan, run_state = pipeline

    step = spec.workflow_steps.get("runtime-boundary-check")
    if step is None:
        pytest.skip("runtime-boundary-check step not found")

    # Inject a governance_context with code_context into run_state
    from governance.dag_runner.models import ArtifactRecord
    run_state.artifacts["governance_context"] = ArtifactRecord(
        name="governance_context",
        producer_step="load-context",
        status="present",
        payload={
            "produced_by": "load-context",
            "code_context": {
                "series_registry": {"status": "present"},
                "adapter_inventory": {"status": "present", "adapter_count": 7},
                "layer2_boundary_checks": {"insert_or_replace_detected": False},
            },
            "runtime_context": {
                "latest_snapshot": {"status": "present", "snapshot_id": "test"},
                "layer3_runtime_absent": True,
            },
        },
    )

    result = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)

    # code_context and runtime_context should be in artifact_inputs
    assert "code_context" in result["artifact_inputs"], (
        "code_context not propagated to runtime-boundary-check"
    )
    assert "runtime_context" in result["artifact_inputs"], (
        "runtime_context not propagated to runtime-boundary-check"
    )

    cc = result["artifact_inputs"]["code_context"]
    assert cc["adapter_inventory"]["adapter_count"] == 7

    rc = result["artifact_inputs"]["runtime_context"]
    assert rc["layer3_runtime_absent"] is True


def test_adapter_schema_check_receives_code_context(pipeline) -> None:
    """adapter-schema-check must receive code_context from governance_context."""
    spec, _plan, run_state = pipeline

    step = spec.workflow_steps.get("adapter-schema-check")
    if step is None:
        pytest.skip("adapter-schema-check step not found")

    from governance.dag_runner.models import ArtifactRecord
    run_state.artifacts["governance_context"] = ArtifactRecord(
        name="governance_context",
        producer_step="load-context",
        status="present",
        payload={
            "produced_by": "load-context",
            "code_context": {
                "series_registry": {"status": "present", "series_count": 24},
                "adapter_inventory": {"status": "present"},
            },
        },
    )

    result = assemble_step_prompt(step, spec, run_state, repo_root=_REPO_ROOT)

    assert "code_context" in result["artifact_inputs"], (
        "code_context not propagated to adapter-schema-check"
    )
