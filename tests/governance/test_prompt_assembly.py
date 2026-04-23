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
        "extra_field_1": "should be stripped",
        "extra_field_2": {"nested": "data"},
    }

    projected = _project_artifact_payload(
        "route-claims-by-role", "governance_context", full_payload,
    )

    # Projected payload should retain only the declared fields
    assert "produced_by" in projected
    assert "request_text" in projected
    assert "run_id" in projected
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
