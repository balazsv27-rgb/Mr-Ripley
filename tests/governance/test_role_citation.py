"""Tests for governance.dag_runner.role_citation — deterministic role-matched citation synthesis.

Covers:
- Claim ID preservation (c1-c6, no C-001 invention)
- Routing rules (implementation → SYSTEM_IMPLEMENTATION_RECORD, etc.)
- Negative guard compliance (c4 Layer-3, c5 execution)
- Strong implementation claim blocking
- Overall status aggregation
- Integration with mock backend (no Claude invocation)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from governance.dag_runner.models import (
    ArtifactRecord,
    GovernanceRunState,
    WorkflowStep,
)
from governance.dag_runner.role_citation import (
    synthesize_role_citation_verdict,
    _classify_claim_type,
    _is_negative_guard,
    _is_strong_claim,
    _build_routing_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_run_state(
    claims: list[dict] | None = None,
    doc_extracts: dict | None = None,
    code_context: dict | None = None,
    runtime_context: dict | None = None,
    spec_routing: dict | None = None,
) -> GovernanceRunState:
    """Build a minimal GovernanceRunState with governance_context and claim_classification_map."""
    rs = GovernanceRunState(run_id="test-run", started_at=datetime.now(timezone.utc))

    gc_payload: dict = {
        "produced_by": "load-context",
        "request_text": "Test request",
        "code_context": code_context or {},
        "runtime_context": runtime_context or {},
        "canonical_doc_extracts": doc_extracts or {},
    }
    rs.artifacts["governance_context"] = ArtifactRecord(
        name="governance_context",
        producer_step="load-context",
        status="present",
        payload=gc_payload,
    )

    ccm_payload: dict = {
        "produced_by": "classify-claims",
        "request_classification": {
            "request_type": "documentation_synchronization",
            "claims": claims or [],
            "summary": {"dominant_scope": "current-state"},
        },
    }
    rs.artifacts["claim_classification_map"] = ArtifactRecord(
        name="claim_classification_map",
        producer_step="classify-claims",
        status="present",
        payload=ccm_payload,
    )

    if spec_routing:
        rs.artifacts["interpretation_policy.claim_routing"] = ArtifactRecord(
            name="interpretation_policy.claim_routing",
            producer_step="load-context",
            status="present",
            payload=spec_routing,
        )

    return rs


def _make_step() -> WorkflowStep:
    return WorkflowStep(
        name="route-claims-by-role",
        component="skill:role-matched-citation-check",
        depends_on=frozenset(["normalize-terminology"]),
        outputs=frozenset(["role_citation_verdict"]),
        raises=frozenset(),
        raw={
            "id": "route-claims-by-role",
            "inputs": [
                "governance_context",
                "claim_classification_map",
                "normalized_terminology_map",
                "interpretation_policy.claim_routing",
            ],
        },
    )


_SP500_IMPL_CLAIM = {
    "claim_id": "c1",
    "claim_text": "SP500 history gap fix is complete — SPY via Yahoo adapter implemented",
    "claim_scope": "current-state",
    "evidence_class": "documented_current_state_claim",
    "source_priority": [
        "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
    ],
    "confidence_level": "medium",
}

_TODO_CLAIM = {
    "claim_id": "c2",
    "claim_text": "Remaining Layer-2 TODO items have been closed",
    "claim_scope": "current-state",
    "evidence_class": "documented_current_state_claim",
    "source_priority": [
        "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "README_LAYER2.md",
    ],
    "confidence_level": "low",
}

_DOC_SYNC_CLAIM = {
    "claim_id": "c3",
    "claim_text": "Canonical documentation needs to be updated to align with the implemented Layer-2 state",
    "claim_scope": "current-state",
    "evidence_class": "verified_in_current_documentation_set",
    "source_priority": [
        "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
    ],
}

_LAYER3_GUARD = {
    "claim_id": "c4",
    "claim_text": "Layer-3 is NOT implemented — explicit constraint preserved",
    "claim_scope": "current-state",
    "evidence_class": "verified_in_current_documentation_set",
    "source_priority": [
        "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
    ],
    "confidence_level": "high",
}

_EXEC_GUARD = {
    "claim_id": "c5",
    "claim_text": "Live execution is NOT ready — explicit constraint preserved",
    "claim_scope": "current-state",
    "evidence_class": "verified_in_current_documentation_set",
    "source_priority": [
        "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
    ],
}

_NO_RENAME_CLAIM = {
    "claim_id": "c6",
    "claim_text": "This request is a documentation synchronization — not a semantic rename or constitutional amendment",
    "claim_scope": "current-state",
    "evidence_class": "verified_in_current_documentation_set",
    "source_priority": ["CLAUDE.md"],
}

_ALL_CLAIMS = [
    _SP500_IMPL_CLAIM, _TODO_CLAIM, _DOC_SYNC_CLAIM,
    _LAYER3_GUARD, _EXEC_GUARD, _NO_RENAME_CLAIM,
]

_DOC_EXTRACTS_WITH_SP500 = {
    "SYSTEM_IMPLEMENTATION_RECORD_v1.md": {
        "file": "Documentation/SYSTEM_IMPLEMENTATION_RECORD_v1.md",
        "status": "present",
        "inference_used": False,
        "headings": ["# Implementation Record"],
        "keyword_section_count": 2,
        "keyword_sections": [
            {"keyword": "SP500", "line_number": 42, "context": "SP500_PROXY added via spy_adapter"},
            {"keyword": "TODO", "line_number": 80, "context": "TODO items tracked in addendum"},
        ],
    },
    "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md": {
        "file": "Documentation/SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
        "status": "present",
        "inference_used": False,
        "headings": ["# Architecture"],
        "keyword_section_count": 3,
        "keyword_sections": [
            {"keyword": "Layer-3", "line_number": 10, "context": "Layer-3 planned only. Not yet built."},
            {"keyword": "Phase A", "line_number": 20, "context": "Phase A complete at contract boundary."},
            {"keyword": "blocked", "line_number": 30, "context": "Phase D — Live Execution Gate: blocked. No execution layer exists."},
        ],
    },
    "SYSTEM_TECHNICAL_HANDBOOK_v1.md": {
        "file": "Documentation/SYSTEM_TECHNICAL_HANDBOOK_v1.md",
        "status": "present",
        "inference_used": False,
        "headings": ["# Technical Handbook"],
        "keyword_section_count": 1,
        "keyword_sections": [
            {"keyword": "Layer-3", "line_number": 5, "context": "Layer-3 not yet implemented."},
        ],
    },
    "DOCUMENTATION_VERIFICATION_MATRIX_v1.md": {
        "file": "Documentation/DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
        "status": "present",
        "inference_used": False,
        "headings": ["# Verification Matrix"],
        "keyword_section_count": 2,
        "keyword_sections": [
            {"keyword": "SP500", "line_number": 73, "context": "SP500 gap listed as open TODO"},
            {"keyword": "TODO", "line_number": 74, "context": "TODO: update SP500 status"},
        ],
    },
    "CLAUDE.md": {
        "file": "CLAUDE.md",
        "status": "present",
        "inference_used": False,
        "headings": ["# CLAUDE.md"],
        "keyword_section_count": 2,
        "keyword_sections": [
            {"keyword": "Layer-3", "line_number": 50, "context": "Layer-3 planned only"},
            {"keyword": "Layer-2", "line_number": 30, "context": "Layer-2 operational at snapshot boundary. Constitutional amendment rule Section 16.1."},
        ],
    },
    "README_LAYER2.md": {
        "file": "Documentation/README_LAYER2.md",
        "status": "present",
        "inference_used": False,
        "headings": ["# Layer-2 README"],
        "keyword_section_count": 1,
        "keyword_sections": [
            {"keyword": "TODO", "line_number": 100, "context": "TODO: fix SP500 history gap"},
        ],
    },
    "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md": {
        "file": "Documentation/SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
        "status": "present",
        "inference_used": False,
        "headings": ["# Limitations"],
        "keyword_section_count": 1,
        "keyword_sections": [
            {"keyword": "SP500", "line_number": 83, "context": "SP500 history gap is a known limitation"},
        ],
    },
}

_CODE_CONTEXT = {
    "series_registry": {
        "status": "present",
        "sp500_proxy_detected": True,
        "series_count": 24,
    },
    "adapter_inventory": {
        "status": "present",
        "adapter_files": ["spy_adapter.py", "gold_adapter.py"],
    },
    "execution_artifact_scan": {
        "layer3_execution_artifacts_absent": True,
        "detected_layer3_indicators": [],
    },
}

_RUNTIME_CONTEXT = {
    "layer3_runtime_absent": True,
    "latest_snapshot": {"status": "present", "snapshot_id": "test-snap"},
}


# ---------------------------------------------------------------------------
# Claim classification helpers
# ---------------------------------------------------------------------------


class TestClaimClassification:

    def test_sp500_impl_claim_type(self) -> None:
        assert _classify_claim_type(_SP500_IMPL_CLAIM) == "implementation"

    def test_todo_impl_claim_type(self) -> None:
        assert _classify_claim_type(_TODO_CLAIM) == "implementation"

    def test_doc_sync_claim_type(self) -> None:
        assert _classify_claim_type(_DOC_SYNC_CLAIM) == "documentation_consistency"

    def test_layer3_guard_type(self) -> None:
        ct = _classify_claim_type(_LAYER3_GUARD)
        assert ct == "architecture"

    def test_exec_guard_type(self) -> None:
        ct = _classify_claim_type(_EXEC_GUARD)
        assert ct == "readiness"

    def test_no_rename_type(self) -> None:
        ct = _classify_claim_type(_NO_RENAME_CLAIM)
        assert ct == "governance"


class TestNegativeGuard:

    def test_layer3_is_guard(self) -> None:
        assert _is_negative_guard(_LAYER3_GUARD) is True

    def test_exec_is_guard(self) -> None:
        assert _is_negative_guard(_EXEC_GUARD) is True

    def test_no_rename_is_guard(self) -> None:
        assert _is_negative_guard(_NO_RENAME_CLAIM) is True

    def test_sp500_not_guard(self) -> None:
        assert _is_negative_guard(_SP500_IMPL_CLAIM) is False

    def test_todo_not_guard(self) -> None:
        assert _is_negative_guard(_TODO_CLAIM) is False


class TestStrongClaim:

    def test_sp500_is_strong(self) -> None:
        assert _is_strong_claim(_SP500_IMPL_CLAIM) is True

    def test_todo_is_strong(self) -> None:
        assert _is_strong_claim(_TODO_CLAIM) is True

    def test_doc_sync_is_strong(self) -> None:
        assert _is_strong_claim(_DOC_SYNC_CLAIM) is True

    def test_guards_are_strong(self) -> None:
        assert _is_strong_claim(_LAYER3_GUARD) is True
        assert _is_strong_claim(_EXEC_GUARD) is True


# ---------------------------------------------------------------------------
# Claim ID preservation
# ---------------------------------------------------------------------------


class TestClaimIdPreservation:

    def test_upstream_ids_preserved(self) -> None:
        """All upstream claim IDs c1-c6 must appear in checked_claims."""
        rs = _make_run_state(
            claims=_ALL_CLAIMS,
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
            runtime_context=_RUNTIME_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        checked = rcs["checked_claims"]
        ids = [c["claim_id"] for c in checked]

        assert ids == ["c1", "c2", "c3", "c4", "c5", "c6"]

    def test_no_invented_ids(self) -> None:
        """No C-001 style invented IDs when upstream provides c1-c6."""
        rs = _make_run_state(
            claims=_ALL_CLAIMS,
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
            runtime_context=_RUNTIME_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        all_ids = []
        for c in rcs["checked_claims"]:
            all_ids.append(c["claim_id"])

        for cid in all_ids:
            assert not cid.startswith("C-"), f"Invented ID {cid} — must use upstream IDs"

    def test_missing_claims_returns_block(self) -> None:
        """Empty claims → conflict_requires_block with inference_used=true."""
        rs = _make_run_state(claims=[])
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        assert rcs["overall_status"] == "conflict_requires_block"
        assert rcs["inference_used"] is True


# ---------------------------------------------------------------------------
# Routing rules
# ---------------------------------------------------------------------------


class TestRoutingRules:

    def test_c1_routes_to_implementation_record(self) -> None:
        rs = _make_run_state(
            claims=[_SP500_IMPL_CLAIM],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        assert checked[0]["required_primary_source"] == "SYSTEM_IMPLEMENTATION_RECORD_v1.md"

    def test_c4_routes_to_architecture(self) -> None:
        rs = _make_run_state(
            claims=[_LAYER3_GUARD],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            runtime_context=_RUNTIME_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        assert checked[0]["required_primary_source"] == "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"

    def test_c6_routes_to_claude_md(self) -> None:
        rs = _make_run_state(
            claims=[_NO_RENAME_CLAIM],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        assert checked[0]["required_primary_source"] == "CLAUDE.md"

    def test_policy_routing_overrides_default(self) -> None:
        """interpretation_policy.claim_routing should override defaults."""
        table = _build_routing_table({
            "implementation_claims": "CUSTOM_IMPL_DOC.md",
        })
        assert table["implementation"] == "CUSTOM_IMPL_DOC.md"
        # Others unaffected
        assert table["architecture"] == "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md"


# ---------------------------------------------------------------------------
# Guard compliance
# ---------------------------------------------------------------------------


class TestGuardCompliance:

    def test_c4_layer3_compliant(self) -> None:
        """Layer-3 NOT implemented guard should be compliant with doc + code evidence."""
        rs = _make_run_state(
            claims=[_LAYER3_GUARD],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
            runtime_context=_RUNTIME_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        checked = rcs["checked_claims"]
        assert checked[0]["verdict"] == "compliant"
        assert rcs["overall_status"] == "compliant"

    def test_c5_exec_compliant(self) -> None:
        """Live execution NOT ready guard should be compliant with doc evidence."""
        rs = _make_run_state(
            claims=[_EXEC_GUARD],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            runtime_context=_RUNTIME_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        assert checked[0]["verdict"] == "compliant"

    def test_c6_no_rename_compliant(self) -> None:
        """No-rename/no-amendment guard should be compliant."""
        rs = _make_run_state(
            claims=[_NO_RENAME_CLAIM],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        # Should be compliant or review_only — not blocked
        assert checked[0]["verdict"] in ("compliant", "review_only")


# ---------------------------------------------------------------------------
# Implementation claim evaluation
# ---------------------------------------------------------------------------


class TestImplementationClaims:

    def test_c1_with_doc_and_code_evidence(self) -> None:
        """SP500 claim with doc extract + code evidence → review_only."""
        rs = _make_run_state(
            claims=[_SP500_IMPL_CLAIM],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        assert checked[0]["verdict"] == "review_only"
        assert checked[0]["role_match"] is True

    def test_c1_with_code_only_no_doc(self) -> None:
        """SP500 claim with code evidence but no doc extract → review_only with role_mismatch."""
        rs = _make_run_state(
            claims=[_SP500_IMPL_CLAIM],
            doc_extracts={},  # no doc extracts
            code_context=_CODE_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        assert checked[0]["verdict"] == "review_only"
        assert checked[0]["role_match"] is False
        assert verdict["role_matched_citation_status"]["summary"]["role_mismatch_detected"] is True

    def test_c2_without_evidence_blocks(self) -> None:
        """Broad TODO claim without any evidence → conflict_requires_block."""
        rs = _make_run_state(
            claims=[_TODO_CLAIM],
            doc_extracts={},
            code_context={},
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        assert checked[0]["verdict"] == "conflict_requires_block"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:

    def test_one_blocking_claim_blocks_overall(self) -> None:
        """Any blocking claim → overall conflict_requires_block."""
        rs = _make_run_state(
            claims=[_TODO_CLAIM],  # will block without evidence
            doc_extracts={},
            code_context={},
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        assert rcs["overall_status"] == "conflict_requires_block"
        assert rcs["summary"]["recommended_guard_action"] == "block"
        assert "c2" in rcs["summary"]["blocking_claims"]

    def test_all_compliant(self) -> None:
        """All guard claims compliant → overall compliant."""
        rs = _make_run_state(
            claims=[_LAYER3_GUARD, _EXEC_GUARD, _NO_RENAME_CLAIM],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
            runtime_context=_RUNTIME_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        assert rcs["overall_status"] == "compliant"
        assert rcs["summary"]["recommended_guard_action"] == "proceed"

    def test_review_only_without_blocking(self) -> None:
        """Review claims without blocking → overall review_only."""
        rs = _make_run_state(
            claims=[_SP500_IMPL_CLAIM],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        assert rcs["overall_status"] == "review_only"
        assert rcs["summary"]["recommended_guard_action"] == "review"

    def test_full_claim_set_aggregation(self) -> None:
        """Full c1-c6 set with evidence: guards compliant, impl review_only."""
        rs = _make_run_state(
            claims=_ALL_CLAIMS,
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
            runtime_context=_RUNTIME_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        summary = rcs["summary"]

        # Guards (c4, c5, c6) should be compliant
        assert "c4" in summary["compliant_claims"]
        assert "c5" in summary["compliant_claims"]

        # Claim IDs should be consistent
        all_ids = (
            summary["blocking_claims"]
            + summary["compliant_claims"]
            + summary["review_only_claims"]
        )
        assert sorted(all_ids) == ["c1", "c2", "c3", "c4", "c5", "c6"]


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema:

    def test_produced_by(self) -> None:
        rs = _make_run_state(claims=_ALL_CLAIMS, doc_extracts=_DOC_EXTRACTS_WITH_SP500)
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)
        assert verdict["produced_by"] == "route-claims-by-role"

    def test_checked_claim_fields(self) -> None:
        rs = _make_run_state(
            claims=[_SP500_IMPL_CLAIM],
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        checked = verdict["role_matched_citation_status"]["checked_claims"]
        assert len(checked) == 1
        c = checked[0]

        required_fields = {
            "claim_id", "claim_text", "claim_type", "required_primary_source",
            "provided_sources", "role_match", "strong_claim",
            "explicit_citation_required", "conflict_detected",
            "blocking_condition_if_any", "verdict", "reason",
        }
        assert required_fields.issubset(c.keys()), (
            f"Missing fields: {required_fields - set(c.keys())}"
        )

    def test_inference_used_false_with_full_evidence(self) -> None:
        rs = _make_run_state(
            claims=_ALL_CLAIMS,
            doc_extracts=_DOC_EXTRACTS_WITH_SP500,
            code_context=_CODE_CONTEXT,
            runtime_context=_RUNTIME_CONTEXT,
        )
        step = _make_step()
        verdict = synthesize_role_citation_verdict(step, rs)

        rcs = verdict["role_matched_citation_status"]
        assert rcs["inference_used"] is False


# ---------------------------------------------------------------------------
# Integration: deterministic execution in mock backend
# ---------------------------------------------------------------------------


def test_route_claims_by_role_is_deterministic_in_mock() -> None:
    """route-claims-by-role should execute deterministically in mock backend.

    After the fix, the executor dispatches this step via structural synthesis
    instead of invoking the Claude backend.
    """
    from governance.dag_runner.assembler import assemble_workflow_spec
    from governance.dag_runner.executor import execute_plan
    from governance.dag_runner.loader import load_workflow_packages
    from governance.dag_runner.models import ExecutionConfig
    from governance.dag_runner.planner import build_execution_plan
    from governance.dag_runner.validator import validate_or_raise
    from governance.dag_runner.execution_backend import MockExecutionBackend

    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)

    config = ExecutionConfig(
        mode="agent_execution",
        request_text="Test doc sync request",
        request_id="test-role-citation",
        request_source="test",
    )
    backend = MockExecutionBackend()

    result = execute_plan(spec, plan, config=config, backend=backend)
    rs = result.run_state

    # Check the role_citation_verdict was produced
    rcv = rs.artifacts.get("role_citation_verdict")
    assert rcv is not None, "role_citation_verdict not produced"
    assert rcv.status == "present"
    assert rcv.payload.get("produced_by") == "route-claims-by-role"

    # Check it has the expected structure
    rcs = rcv.payload.get("role_matched_citation_status")
    assert rcs is not None, "role_matched_citation_status missing"
    assert "overall_status" in rcs
    assert "checked_claims" in rcs
    assert "summary" in rcs

    # Verify the step trace shows deterministic_synthesis
    synthesis_events = [
        ev for ev in rs.execution_trace
        if ev.node_name == "route-claims-by-role"
        and ev.event_type == "deterministic_synthesis"
    ]
    assert len(synthesis_events) == 1, (
        f"Expected exactly 1 deterministic_synthesis trace for route-claims-by-role, "
        f"got {len(synthesis_events)}"
    )
    assert synthesis_events[0].detail.get("synthesized_artifact") == "role_citation_verdict"

    # Verify the node result shows inference_used=False
    nr = rs.node_results.get("route-claims-by-role")
    assert nr is not None
    assert nr.status == "PASS"
    assert nr.inference_used is False
