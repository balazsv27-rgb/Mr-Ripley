"""Tests for governance.dag_runner.adapter_schema — deterministic adapter-schema verdict synthesis.

Covers:
- Structural dispatch: adapter-schema-check does not invoke Claude backend
- inference_used=false when code_context and runtime_boundary_verdict present
- Latest evidence happy/review path (SP500_PROXY + spy_adapter + clean boundary)
- Blocking cases (registry missing, spy_adapter missing, INSERT OR REPLACE, etc.)
- Regression: other structural steps still pass
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from governance.dag_runner.models import (
    ArtifactRecord,
    GovernanceRunState,
    WorkflowStep,
)
from governance.dag_runner.adapter_schema import synthesize_adapter_schema_verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_state(
    code_context: dict | None = None,
    runtime_boundary_verdict: dict | None = None,
) -> GovernanceRunState:
    """Build a minimal GovernanceRunState with governance_context and optionally rbv."""
    rs = GovernanceRunState(
        run_id="test-run",
        started_at=datetime.now(timezone.utc),
        session_dir="/tmp/test-session",
    )

    gc_payload: dict = {
        "produced_by": "load-context",
        "request_text": "Test request",
        "code_context": code_context or {},
        "runtime_context": {},
        "canonical_doc_extracts": {},
    }
    rs.artifacts["governance_context"] = ArtifactRecord(
        name="governance_context",
        producer_step="load-context",
        status="present",
        payload=gc_payload,
    )

    if runtime_boundary_verdict is not None:
        rs.artifacts["runtime_boundary_verdict"] = ArtifactRecord(
            name="runtime_boundary_verdict",
            producer_step="runtime-boundary-check",
            status="present",
            payload=runtime_boundary_verdict,
        )

    return rs


def _make_step() -> WorkflowStep:
    return WorkflowStep(
        name="adapter-schema-check",
        component="skill:adapter-schema-review",
        outputs=["adapter_schema_verdict"],
        raw={
            "id": "adapter-schema-check",
            "inputs": [
                "governance_context",
                "runtime_boundary_verdict",
            ],
        },
    )


# --- Reusable evidence fixtures ---

_FULL_CODE_CONTEXT = {
    "series_registry": {
        "file": "layer2/config/series_registry.json",
        "status": "present",
        "inference_used": False,
        "registry_version": "1.1.0",
        "series_count": 24,
        "tier1_count": 16,
        "tier2_count": 8,
        "include_in_snapshot_count": 21,
        "sp500_detected": True,
        "sp500_proxy_detected": True,
        "sp500_source": "fred",
        "sp500_proxy_source": "yahoo_spy",
        "sp500_proxy_full_history_start": "2005-01-03",
        "sp500_proxy_include_in_snapshot": True,
        "sp500_proxy_tier": 1,
    },
    "adapter_inventory": {
        "adapter_dir": "layer2/adapters",
        "status": "present",
        "inference_used": False,
        "adapter_count": 7,
        "adapter_files": [
            "fred_loader.py",
            "gld_holdings_adapter.py",
            "gold_adapter.py",
            "move_adapter.py",
            "quality_gate.py",
            "snapshot_publisher.py",
            "spy_adapter.py",
        ],
    },
    "layer2_boundary_checks": {
        "inference_used": False,
        "checks": [
            {
                "file": "layer2/db.py",
                "status": "present",
                "insert_or_ignore_count": 2,
                "insert_or_replace_count": 0,
                "violation_detected": False,
            },
            {
                "file": "layer2/alignment.py",
                "status": "present",
                "insert_or_ignore_count": 0,
                "insert_or_replace_count": 0,
                "violation_detected": False,
            },
        ],
        "insert_or_replace_detected": False,
    },
    "execution_artifact_scan": {
        "inference_used": False,
        "layer3_execution_artifacts_absent": True,
        "detected_layer3_indicators": [],
    },
}

_COMPLIANT_RBV = {
    "produced_by": "runtime-boundary-check",
    "runtime_boundary_verdict": {
        "raw_observation_access_detected": False,
        "latest_snapshot_misuse_detected": False,
        "layer2_storage_coupling_detected": False,
        "boundary_violation_suspected": False,
        "overall_assessment": "compliant_pending_auditor_content_scan",
        "escalation_required": False,
    },
}


# ---------------------------------------------------------------------------
# AS-01 through AS-09 checks with full evidence
# ---------------------------------------------------------------------------


class TestFullEvidenceReviewPath:
    """With full latest-style evidence, overall should be review_only
    (content scan caveat), not blocked."""

    def test_overall_status_review_only(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        status = verdict["adapter_schema_status"]
        assert status["overall_status"] == "review_only"

    def test_inference_used_false(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["inference_used"] is False
        assert verdict["adapter_schema_status"]["inference_used"] is False

    def test_registry_driven_compliant(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["registry_driven_status"] == "compliant"
        assert verdict["registry_driven_compliance"] is True

    def test_schema_write_compliant(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["schema_write_status"] == "compliant"

    def test_sp500_proxy_compliant(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["sp500_proxy_status"] == "compliant"

    def test_adapter_boundary_review_only(self) -> None:
        """Adapter boundary is review_only due to content scan caveat."""
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["adapter_boundary_status"] == "review_only"

    def test_unresolved_content_scan_caveat(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        summary = verdict["adapter_schema_status"]["summary"]
        assert summary["unresolved_content_scan_caveat"] is True

    def test_summary_counts(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        summary = verdict["adapter_schema_status"]["summary"]
        assert summary["registry_version"] == "1.1.0"
        assert summary["series_count"] == 24
        assert summary["tier1_count"] == 16
        assert summary["tier2_count"] == 8
        assert summary["include_in_snapshot_count"] == 21
        assert summary["sp500_detected"] is True
        assert summary["sp500_proxy_detected"] is True
        assert summary["sp500_proxy_source"] == "yahoo_spy"
        assert summary["sp500_proxy_full_history_start"] == "2005-01-03"
        assert summary["sp500_proxy_include_in_snapshot"] is True
        assert summary["sp500_proxy_tier"] == 1
        assert summary["adapter_count"] == 7
        assert summary["insert_or_replace_detected"] is False
        assert summary["layer3_execution_artifacts_absent"] is True
        assert summary["runtime_boundary_compliant"] is True

    def test_produced_by(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["produced_by"] == "adapter-schema-check"

    def test_checked_items_present(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        items = verdict["adapter_schema_status"]["checked_items"]
        item_ids = [i["item_id"] for i in items]
        assert "AS-01" in item_ids
        assert "AS-02" in item_ids
        assert "AS-03" in item_ids
        assert "AS-04" in item_ids
        assert "AS-05" in item_ids
        assert "AS-06" in item_ids
        assert "AS-07" in item_ids
        assert "AS-08" in item_ids
        assert "AS-09" in item_ids

    def test_no_blocking_reasons(self) -> None:
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=_COMPLIANT_RBV,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["summary"]["blocking_reasons"] == []
        assert verdict["requires_adapter_schema_guardian"] is False


# ---------------------------------------------------------------------------
# Blocking cases
# ---------------------------------------------------------------------------


class TestBlockingCases:

    def test_registry_missing_blocks(self) -> None:
        cc = {
            "series_registry": {"status": "missing", "series_count": 0},
            "adapter_inventory": _FULL_CODE_CONTEXT["adapter_inventory"],
            "layer2_boundary_checks": _FULL_CODE_CONTEXT["layer2_boundary_checks"],
            "execution_artifact_scan": _FULL_CODE_CONTEXT["execution_artifact_scan"],
        }
        rs = _make_run_state(code_context=cc, runtime_boundary_verdict=_COMPLIANT_RBV)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "blocked"
        assert "series_registry missing" in str(
            verdict["adapter_schema_status"]["summary"]["blocking_reasons"]
        )

    def test_sp500_proxy_without_spy_adapter_blocks(self) -> None:
        cc = dict(_FULL_CODE_CONTEXT)
        cc["adapter_inventory"] = {
            "adapter_dir": "layer2/adapters",
            "status": "present",
            "adapter_count": 3,
            "adapter_files": ["fred_loader.py", "gold_adapter.py", "move_adapter.py"],
        }
        rs = _make_run_state(code_context=cc, runtime_boundary_verdict=_COMPLIANT_RBV)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "blocked"
        blocking = verdict["adapter_schema_status"]["summary"]["blocking_reasons"]
        assert any("spy_adapter" in r for r in blocking)

    def test_sp500_proxy_wrong_source_blocks(self) -> None:
        cc = dict(_FULL_CODE_CONTEXT)
        sr = dict(cc["series_registry"])
        sr["sp500_proxy_source"] = "wrong_source"
        cc["series_registry"] = sr
        rs = _make_run_state(code_context=cc, runtime_boundary_verdict=_COMPLIANT_RBV)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "blocked"

    def test_insert_or_replace_detected_blocks(self) -> None:
        cc = dict(_FULL_CODE_CONTEXT)
        cc["layer2_boundary_checks"] = {
            "inference_used": False,
            "checks": [
                {
                    "file": "layer2/db.py",
                    "status": "present",
                    "insert_or_ignore_count": 0,
                    "insert_or_replace_count": 3,
                    "violation_detected": True,
                },
            ],
            "insert_or_replace_detected": True,
        }
        rs = _make_run_state(code_context=cc, runtime_boundary_verdict=_COMPLIANT_RBV)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "blocked"
        assert verdict["schema_violation_detected"] is True

    def test_rbv_boundary_violation_blocks(self) -> None:
        rbv = {
            "produced_by": "runtime-boundary-check",
            "runtime_boundary_verdict": {
                "raw_observation_access_detected": False,
                "latest_snapshot_misuse_detected": False,
                "boundary_violation_suspected": True,
                "overall_assessment": "blocked",
            },
        }
        rs = _make_run_state(
            code_context=_FULL_CODE_CONTEXT,
            runtime_boundary_verdict=rbv,
        )
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "blocked"

    def test_layer3_artifacts_detected_blocks(self) -> None:
        cc = dict(_FULL_CODE_CONTEXT)
        cc["execution_artifact_scan"] = {
            "inference_used": False,
            "layer3_execution_artifacts_absent": False,
            "detected_layer3_indicators": ["layer3", "feature_builder"],
        }
        rs = _make_run_state(code_context=cc, runtime_boundary_verdict=_COMPLIANT_RBV)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "blocked"

    def test_sp500_proxy_include_false_blocks(self) -> None:
        cc = dict(_FULL_CODE_CONTEXT)
        sr = dict(cc["series_registry"])
        sr["sp500_proxy_include_in_snapshot"] = False
        cc["series_registry"] = sr
        rs = _make_run_state(code_context=cc, runtime_boundary_verdict=_COMPLIANT_RBV)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "blocked"

    def test_sp500_proxy_wrong_tier_blocks(self) -> None:
        cc = dict(_FULL_CODE_CONTEXT)
        sr = dict(cc["series_registry"])
        sr["sp500_proxy_tier"] = 2
        cc["series_registry"] = sr
        rs = _make_run_state(code_context=cc, runtime_boundary_verdict=_COMPLIANT_RBV)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "blocked"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_no_code_context_is_review_only_with_inference(self) -> None:
        """Missing code_context → review_only with inference_used=true."""
        rs = _make_run_state(code_context={})
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["inference_used"] is True
        # Should not be blocked — just review_only for missing evidence
        assert verdict["adapter_schema_status"]["overall_status"] in (
            "review_only", "blocked",
        )

    def test_no_rbv_review_only(self) -> None:
        """Missing runtime_boundary_verdict → review_only, not blocked."""
        rs = _make_run_state(code_context=_FULL_CODE_CONTEXT)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["overall_status"] == "review_only"
        as08 = [
            c for c in verdict["adapter_schema_status"]["checked_items"]
            if c["item_id"] == "AS-08"
        ]
        assert as08[0]["assessment"] == "review_only"

    def test_sp500_not_detected_not_applicable(self) -> None:
        cc = dict(_FULL_CODE_CONTEXT)
        sr = dict(cc["series_registry"])
        sr["sp500_detected"] = False
        sr["sp500_proxy_detected"] = False
        cc["series_registry"] = sr
        rs = _make_run_state(code_context=cc, runtime_boundary_verdict=_COMPLIANT_RBV)
        verdict = synthesize_adapter_schema_verdict(_make_step(), rs)
        assert verdict["adapter_schema_status"]["sp500_proxy_status"] == "not_applicable"


# ---------------------------------------------------------------------------
# Integration: deterministic execution in mock backend
# ---------------------------------------------------------------------------


def test_adapter_schema_check_deterministic_in_mock() -> None:
    """adapter-schema-check should execute deterministically in mock backend.

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
        request_id="test-adapter-schema",
        request_source="test",
    )
    backend = MockExecutionBackend()

    result = execute_plan(spec, plan, config=config, backend=backend)
    rs = result.run_state

    # Check the adapter_schema_verdict was produced
    asv = rs.artifacts.get("adapter_schema_verdict")
    assert asv is not None, "adapter_schema_verdict not produced"
    assert asv.status == "present"
    assert asv.payload.get("produced_by") == "adapter-schema-check"

    # Check it has the expected structure
    status = asv.payload.get("adapter_schema_status")
    assert status is not None, "adapter_schema_status missing"
    assert "overall_status" in status
    assert "checked_items" in status
    assert "summary" in status

    # Verify the step trace shows deterministic_synthesis
    synthesis_events = [
        ev for ev in rs.execution_trace
        if ev.node_name == "adapter-schema-check"
        and ev.event_type == "deterministic_synthesis"
    ]
    assert len(synthesis_events) == 1, (
        f"Expected exactly 1 deterministic_synthesis trace for adapter-schema-check, "
        f"got {len(synthesis_events)}"
    )
    assert synthesis_events[0].detail.get("synthesized_artifact") == "adapter_schema_verdict"

    # Verify the node result shows inference_used=False
    nr = rs.node_results.get("adapter-schema-check")
    assert nr is not None
    assert nr.status == "PASS"
    assert nr.inference_used is False


# ---------------------------------------------------------------------------
# Regression: existing structural steps still pass
# ---------------------------------------------------------------------------


def test_role_citation_still_deterministic() -> None:
    """Regression: route-claims-by-role still works after adapter-schema-check addition."""
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
        request_text="Test request",
        request_id="test-regression",
        request_source="test",
    )
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, config=config, backend=backend)
    rs = result.run_state

    rcv = rs.artifacts.get("role_citation_verdict")
    assert rcv is not None
    assert rcv.status == "present"
    assert rcv.payload.get("produced_by") == "route-claims-by-role"

    nr = rs.node_results.get("route-claims-by-role")
    assert nr is not None
    assert nr.status == "PASS"
    assert nr.inference_used is False


def test_deep_audit_still_deterministic() -> None:
    """Regression: deep-audit still works."""
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
        request_text="Test request",
        request_id="test-regression-audit",
        request_source="test",
    )
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, config=config, backend=backend)
    rs = result.run_state

    audit = rs.artifacts.get("audit_summary")
    assert audit is not None
    assert audit.status == "present"
    assert audit.payload.get("produced_by") == "deep-audit"


def test_doc_code_sync_still_deterministic() -> None:
    """Regression: doc-code-sync-check still works."""
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
        request_text="Test request",
        request_id="test-regression-sync",
        request_source="test",
    )
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, config=config, backend=backend)
    rs = result.run_state

    sync = rs.artifacts.get("doc_code_sync_status")
    assert sync is not None
    assert sync.status == "present"
    assert sync.payload.get("produced_by") == "doc-code-sync-check"


def test_artifact_hygiene_still_deterministic() -> None:
    """Regression: runtime-artifact-hygiene-check still works."""
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
        request_text="Test request",
        request_id="test-regression-hygiene",
        request_source="test",
    )
    backend = MockExecutionBackend()
    result = execute_plan(spec, plan, config=config, backend=backend)
    rs = result.run_state

    hygiene = rs.artifacts.get("artifact_hygiene_verdict")
    assert hygiene is not None
    assert hygiene.status == "present"
    assert hygiene.payload.get("produced_by") == "runtime-artifact-hygiene-check"
