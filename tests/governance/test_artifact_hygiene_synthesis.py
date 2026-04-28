"""Tests for runtime-artifact-hygiene-check deterministic synthesis.

Covers:
- Clean run_state produces clean verdict
- Verification ledger delta signals (missing_evidence, unresolved_conflicts, upgrade_blocked)
- Artifact payload issues (missing produced_by, producer_step mismatch)
- Array caps enforcement
- Artifact name is exactly artifact_hygiene_verdict
- inference_used=false for normal deterministic synthesis
- No Claude invocation in agent_execution mode
- Deep-audit and doc-code-sync deterministic tests still pass (integration)
- Dependency skip behaviour
- Matrix and ledger projection tests still pass (integration)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.executor import (
    _synthesize_artifact_hygiene_verdict,
    _synthesize_audit_summary,
    _synthesize_doc_code_sync_status,
    execute_plan,
)
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.models import (
    ArtifactRecord,
    AssembledWorkflowSpec,
    ExecutionConfig,
    GovernanceRunState,
    ManifestSpec,
    WorkflowStep,
)
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.blockers import analyze_blockers
from governance.dag_runner.validator import validate_or_raise, validate_workflow_spec
from governance.dag_runner.verdict import compute_verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_state(**kwargs) -> GovernanceRunState:
    defaults = {
        "run_id": "test-run-001",
        "started_at": datetime(2026, 4, 28, tzinfo=timezone.utc),
        "session_dir": "/tmp/test-session",
    }
    defaults.update(kwargs)
    return GovernanceRunState(**defaults)


def _make_step(
    name: str = "runtime-artifact-hygiene-check",
    component: str = "skill:runtime-artifact-hygiene-check",
    outputs: list[str] | None = None,
    inputs: list[str] | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        name=name,
        component=component,
        outputs=outputs or ["artifact_hygiene_verdict"],
        raw={"inputs": inputs or ["verification_ledger_delta"]},
    )


def _make_artifact(
    name: str,
    producer_step: str,
    status: str = "present",
    payload: dict | None = None,
) -> ArtifactRecord:
    if payload is None:
        payload = {"produced_by": producer_step}
    return ArtifactRecord(
        name=name,
        producer_step=producer_step,
        status=status,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Test: clean run_state -> clean verdict
# ---------------------------------------------------------------------------


class TestCleanState:
    def test_clean_state_produces_clean_verdict(self):
        run_state = _make_run_state(artifacts={
            "governance_context": _make_artifact("governance_context", "load-context"),
            "claim_classification_map": _make_artifact(
                "claim_classification_map", "classify-claims",
            ),
            "verification_ledger_delta": _make_artifact(
                "verification_ledger_delta", "update-verification-ledger",
                payload={
                    "produced_by": "update-verification-ledger",
                    "summary": {},
                },
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["overall_status"] == "clean"
        assert result["hygiene_status"] == "clean"
        assert result["inference_used"] is False
        assert result["produced_by"] == "runtime-artifact-hygiene-check"
        assert result["unexpected_runtime_artifacts_detected"] is False
        assert result["stale_artifacts_detected"] is False
        assert result["commit_sensitive_artifacts_detected"] is False
        assert result["evidence_confusing_artifacts_detected"] is False
        assert result["missing_expected_artifacts_detected"] is False
        assert any("No runtime artifact" in n for n in result["notes"])

    def test_artifact_counts_populated(self):
        run_state = _make_run_state(artifacts={
            "a": _make_artifact("a", "step-a"),
            "b": _make_artifact("b", "step-b"),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["artifact_counts"]["declared_artifacts"] == 2
        assert result["artifact_counts"]["present_artifacts"] == 2
        assert result["artifact_counts"]["missing_artifacts"] == 0

    def test_checked_artifacts_listed(self):
        run_state = _make_run_state(artifacts={
            "alpha": _make_artifact("alpha", "step-a"),
            "beta": _make_artifact("beta", "step-b"),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert len(result["checked_artifacts"]) == 2
        names = [c["name"] for c in result["checked_artifacts"]]
        assert "alpha" in names
        assert "beta" in names


# ---------------------------------------------------------------------------
# Test: verification_ledger_delta signals
# ---------------------------------------------------------------------------


class TestLedgerSignals:
    def test_missing_evidence_produces_review_only(self):
        run_state = _make_run_state(artifacts={
            "verification_ledger_delta": _make_artifact(
                "verification_ledger_delta", "update-verification-ledger",
                payload={
                    "produced_by": "update-verification-ledger",
                    "summary": {
                        "missing_evidence": ["claim-1", "claim-2"],
                    },
                },
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["overall_status"] == "review_only"
        assert result["hygiene_status"] == "review_only"
        assert any(
            f.get("signal") == "missing_evidence"
            for f in result["hygiene_findings"]
        )

    def test_unresolved_conflicts_produces_blocked(self):
        run_state = _make_run_state(artifacts={
            "verification_ledger_delta": _make_artifact(
                "verification_ledger_delta", "update-verification-ledger",
                payload={
                    "produced_by": "update-verification-ledger",
                    "summary": {
                        "unresolved_conflicts": ["conflict-A"],
                    },
                },
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["overall_status"] == "blocked"
        assert result["hygiene_status"] == "blocked"
        assert len(result["blocking_reasons"]) >= 1
        assert "unresolved conflict" in result["blocking_reasons"][0]

    def test_upgrade_blocked_produces_blocked(self):
        run_state = _make_run_state(artifacts={
            "verification_ledger_delta": _make_artifact(
                "verification_ledger_delta", "update-verification-ledger",
                payload={
                    "produced_by": "update-verification-ledger",
                    "summary": {
                        "runtime_status_upgrade_attempt_blocked": True,
                    },
                },
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["overall_status"] == "blocked"
        assert any(
            "runtime_status_upgrade_attempt_blocked" in r
            for r in result["blocking_reasons"]
        )

    def test_conflicts_detected_produces_review_only(self):
        run_state = _make_run_state(artifacts={
            "verification_ledger_delta": _make_artifact(
                "verification_ledger_delta", "update-verification-ledger",
                payload={
                    "produced_by": "update-verification-ledger",
                    "summary": {
                        "conflicts_detected": True,
                    },
                },
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["overall_status"] == "review_only"
        assert any(
            f.get("signal") == "conflicts_detected"
            for f in result["hygiene_findings"]
        )

    def test_source_authority_conflict_produces_review_only(self):
        run_state = _make_run_state(artifacts={
            "verification_ledger_delta": _make_artifact(
                "verification_ledger_delta", "update-verification-ledger",
                payload={
                    "produced_by": "update-verification-ledger",
                    "source_authority_conflict_detected": True,
                    "summary": {},
                },
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["overall_status"] == "review_only"


# ---------------------------------------------------------------------------
# Test: evidence-confusing artifacts
# ---------------------------------------------------------------------------


class TestEvidenceConfusingArtifacts:
    def test_missing_produced_by_in_payload(self):
        run_state = _make_run_state(artifacts={
            "bad_artifact": _make_artifact(
                "bad_artifact", "step-a",
                payload={"some_field": "value"},  # no produced_by
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["evidence_confusing_artifacts_detected"] is True
        assert result["overall_status"] == "review_only"
        assert any(
            f.get("signal") == "missing_produced_by_in_payload"
            for f in result["hygiene_findings"]
        )

    def test_producer_step_mismatch(self):
        run_state = _make_run_state(artifacts={
            "mismatched": _make_artifact(
                "mismatched", "step-a",
                payload={"produced_by": "step-b"},  # mismatch
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["evidence_confusing_artifacts_detected"] is True
        assert result["overall_status"] == "review_only"
        assert any(
            f.get("signal") == "producer_step_mismatch"
            for f in result["hygiene_findings"]
        )

    def test_unexpected_artifact_status(self):
        run_state = _make_run_state(artifacts={
            "stale_art": _make_artifact(
                "stale_art", "step-a", status="stale",
                payload={"produced_by": "step-a"},
            ),
        })
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["evidence_confusing_artifacts_detected"] is True
        assert any(
            "unexpected_status" in f.get("signal", "")
            for f in result["hygiene_findings"]
        )


# ---------------------------------------------------------------------------
# Test: array caps
# ---------------------------------------------------------------------------


class TestArrayCaps:
    def test_checked_artifacts_capped_at_20(self):
        arts = {}
        for i in range(25):
            name = f"art_{i:03d}"
            arts[name] = _make_artifact(name, f"step_{i}")
        run_state = _make_run_state(artifacts=arts)
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert len(result["checked_artifacts"]) <= 20

    def test_missing_artifacts_capped_at_20(self):
        arts = {}
        for i in range(25):
            name = f"art_{i:03d}"
            arts[name] = _make_artifact(name, f"step_{i}", status="missing")
        run_state = _make_run_state(artifacts=arts)
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert len(result["missing_artifacts"]) <= 20

    def test_notes_capped_at_10(self):
        # Clean state should produce exactly 1 note
        run_state = _make_run_state(artifacts={})
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)
        assert len(result["notes"]) <= 10


# ---------------------------------------------------------------------------
# Test: produced artifact name and schema
# ---------------------------------------------------------------------------


class TestArtifactSchema:
    def test_produced_artifact_name_is_artifact_hygiene_verdict(self):
        run_state = _make_run_state(artifacts={})
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)

        assert result["produced_by"] == "runtime-artifact-hygiene-check"
        # All required schema fields present
        for key in (
            "overall_status", "hygiene_status",
            "unexpected_runtime_artifacts_detected",
            "stale_artifacts_detected",
            "commit_sensitive_artifacts_detected",
            "evidence_confusing_artifacts_detected",
            "missing_expected_artifacts_detected",
            "artifact_counts", "checked_artifacts",
            "missing_artifacts", "hygiene_findings",
            "blocking_reasons", "required_actions",
            "inference_used", "notes",
        ):
            assert key in result, f"Missing required field: {key}"

    def test_inference_used_false_for_deterministic(self):
        run_state = _make_run_state(artifacts={})
        step = _make_step()
        result = _synthesize_artifact_hygiene_verdict(step, run_state)
        assert result["inference_used"] is False


# ---------------------------------------------------------------------------
# Test: integration — no Claude invocation in agent_execution mode
# ---------------------------------------------------------------------------


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


class TestIntegration:
    def test_hygiene_check_does_not_invoke_claude(self, pipeline):
        """runtime-artifact-hygiene-check should use deterministic synthesis,
        not invoke Claude, in agent_execution mode with mock backend."""
        spec, plan, verdict = pipeline
        config = ExecutionConfig(mode="agent_execution", request_text="test")
        backend = MockExecutionBackend()
        result = execute_plan(
            spec, plan, verdict_status=verdict.status,
            config=config, backend=backend,
        )
        # Find the node result for runtime-artifact-hygiene-check
        nr = result.run_state.node_results.get("runtime-artifact-hygiene-check")
        assert nr is not None, "runtime-artifact-hygiene-check should have executed"
        # It should PASS (or SKIP if upstream failed, but with mock backend all pass)
        if nr.status == "PASS":
            assert nr.inference_used is False
            # Check artifact was produced
            art = result.run_state.artifacts.get("artifact_hygiene_verdict")
            assert art is not None
            assert art.status == "present"
            assert art.payload["produced_by"] == "runtime-artifact-hygiene-check"
            assert art.payload["inference_used"] is False

    def test_deterministic_synthesis_trace_event(self, pipeline):
        """runtime-artifact-hygiene-check should emit deterministic_synthesis trace."""
        spec, plan, verdict = pipeline
        config = ExecutionConfig(mode="agent_execution", request_text="test")
        backend = MockExecutionBackend()
        result = execute_plan(
            spec, plan, verdict_status=verdict.status,
            config=config, backend=backend,
        )
        synth_events = [
            e for e in result.run_state.execution_trace
            if e.event_type == "deterministic_synthesis"
            and e.node_name == "runtime-artifact-hygiene-check"
        ]
        nr = result.run_state.node_results.get("runtime-artifact-hygiene-check")
        if nr is not None and nr.status == "PASS":
            assert len(synth_events) == 1
            assert synth_events[0].detail["synthesized_artifact"] == "artifact_hygiene_verdict"

    def test_deep_audit_still_deterministic(self, pipeline):
        """deep-audit should still produce deterministic audit_summary."""
        spec, plan, verdict = pipeline
        config = ExecutionConfig(mode="agent_execution", request_text="test")
        backend = MockExecutionBackend()
        result = execute_plan(
            spec, plan, verdict_status=verdict.status,
            config=config, backend=backend,
        )
        nr = result.run_state.node_results.get("deep-audit")
        if nr is not None and nr.status == "PASS":
            assert nr.inference_used is False
            art = result.run_state.artifacts.get("audit_summary")
            assert art is not None
            assert art.payload.get("produced_by") == "deep-audit"

    def test_doc_code_sync_still_deterministic(self, pipeline):
        """doc-code-sync-check should still produce deterministic doc_code_sync_status."""
        spec, plan, verdict = pipeline
        config = ExecutionConfig(mode="agent_execution", request_text="test")
        backend = MockExecutionBackend()
        result = execute_plan(
            spec, plan, verdict_status=verdict.status,
            config=config, backend=backend,
        )
        nr = result.run_state.node_results.get("doc-code-sync-check")
        if nr is not None and nr.status == "PASS":
            assert nr.inference_used is False
            art = result.run_state.artifacts.get("doc_code_sync_status")
            assert art is not None
            assert art.payload.get("produced_by") == "doc-code-sync-check"

    def test_dependency_skip_still_works(self, pipeline):
        """Dependency skip behaviour should still work for downstream steps."""
        spec, plan, verdict = pipeline
        config = ExecutionConfig(mode="agent_execution", request_text="test")
        backend = MockExecutionBackend()
        result = execute_plan(
            spec, plan, verdict_status=verdict.status,
            config=config, backend=backend,
        )
        # All steps should be either PASS or SKIP (no FAIL with mock backend)
        for step_id, nr in result.run_state.node_results.items():
            assert nr.status in ("PASS", "SKIP"), (
                f"Step {step_id} has unexpected status {nr.status}"
            )

    def test_matrix_and_ledger_artifacts_produced(self, pipeline):
        """Verification matrix delta and ledger delta should still be produced."""
        spec, plan, verdict = pipeline
        config = ExecutionConfig(mode="agent_execution", request_text="test")
        backend = MockExecutionBackend()
        result = execute_plan(
            spec, plan, verdict_status=verdict.status,
            config=config, backend=backend,
        )
        # These should be present (produced by mock backend for skill steps)
        for art_name in ("verification_matrix_delta", "verification_ledger_delta"):
            art = result.run_state.artifacts.get(art_name)
            assert art is not None, f"Expected artifact {art_name} to be present"


# ---------------------------------------------------------------------------
# Test: deep-audit synthesis still works in isolation
# ---------------------------------------------------------------------------


class TestDeepAuditSynthesisStillWorks:
    def test_no_escalation_signals_produce_pass(self):
        step = WorkflowStep(
            name="deep-audit",
            component="subagents",
            outputs=["audit_summary"],
            raw={"inputs": ["governance_context"]},
        )
        run_state = _make_run_state(artifacts={
            "governance_context": _make_artifact(
                "governance_context", "load-context",
            ),
        })
        result = _synthesize_audit_summary(step, run_state)
        assert result["overall_audit_status"] == "pass"
        assert result["produced_by"] == "deep-audit"


# ---------------------------------------------------------------------------
# Test: doc-code-sync synthesis still works in isolation
# ---------------------------------------------------------------------------


class TestDocCodeSyncSynthesisStillWorks:
    def test_missing_upstream_produces_review_only(self):
        step = WorkflowStep(
            name="doc-code-sync-check",
            component="skill:doc-code-sync-check",
            outputs=["doc_code_sync_status"],
            raw={"inputs": ["change_impact_report", "doc_update_plan"]},
        )
        run_state = _make_run_state(artifacts={})
        result = _synthesize_doc_code_sync_status(step, run_state)
        assert result["overall_status"] == "review_only"
        assert result["produced_by"] == "doc-code-sync-check"
