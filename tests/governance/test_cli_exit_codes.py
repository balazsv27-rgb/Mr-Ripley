"""Tests for R3-A: semantic exit code mapping.

Verifies that CLI exit codes map to failure categories per the plan table.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from governance.dag_runner.cli import (
    EXIT_ARTIFACT_FAILURE,
    EXIT_CONTRACT_FAILURE,
    EXIT_OK,
    EXIT_STRUCTURAL_FAILURE,
    EXIT_VERDICT_BLOCKED,
    EXIT_VERDICT_REVIEW_ONLY,
    main,
)
from governance.dag_runner.drift_detector import DriftIssue, DriftResult
from governance.dag_runner.models import (
    AgentExecutionResult,
    AssembledWorkflowSpec,
    BlockingCondition,
    ExecutionConfig,
    FailureClassification,
    ManifestSpec,
    WorkflowStep,
)
from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.planner import ExecutionPlan, PlannedNode


class TestExitCodeCleanRun:
    """Exit code 0 for clean runs."""

    def test_clean_run_exit_code_zero(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["dag-runner"])
        assert main() == EXIT_OK

    def test_clean_json_run_exit_code_zero(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--json"])
        assert main() == EXIT_OK


class TestExitCodeStructuralFailure:
    """Exit code 1 for structural failures."""

    def test_invalid_workflow_path(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(
            sys, "argv",
            ["dag-runner", "--workflow", "/nonexistent/workflow.yaml"],
        )
        assert main() == EXIT_STRUCTURAL_FAILURE

    def test_critical_drift_exit_code_one(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["dag-runner"])
        monkeypatch.setattr(
            "governance.dag_runner.cli.detect_drift",
            lambda spec, repo_root: DriftResult(
                is_clean=False,
                critical_drifts=[
                    DriftIssue(
                        check="agent_file_existence",
                        severity="critical",
                        message="Agent missing.",
                    ),
                ],
                informational_drifts=[],
            ),
        )
        assert main() == EXIT_STRUCTURAL_FAILURE


class TestExitCodeContractFailure:
    """Exit code 2 for halt-on-critical (contract failure)."""

    def test_halt_on_critical_exit_code_two(self, monkeypatch, capsys) -> None:
        """Force a halt-on-critical via MockExecutionBackend → exit code 2."""
        from tests.governance.test_executor_halt import FailingMockExecutionBackend

        monkeypatch.setattr(sys, "argv", ["dag-runner", "--mode", "agent_execution"])

        # Patch the backend creation to use our failing backend
        original_main = main

        # We need to intercept the execution. Monkeypatch execute_plan to
        # produce a run_state with an unresolved critical blocking condition.
        def _mock_execute_plan(spec, plan, *, verdict_status=None, config=None,
                               backend=None, prior_state=None):
            from governance.dag_runner.models import (
                BlockingEvent,
                GovernanceRunState,
            )
            from governance.dag_runner.executor import ExecutionResult
            from datetime import datetime, timezone

            run_state = GovernanceRunState(
                run_id="test-halt",
                started_at=datetime.now(timezone.utc),
            )
            # Simulate a halted step
            from governance.dag_runner.models import NodeResult
            run_state.node_results["step-a"] = NodeResult(
                node_name="step-a",
                node_type="constitution",
                status="FAIL",
                summary="forced failure",
            )
            run_state.blocking_conditions.append(
                BlockingEvent(
                    blocking_id="fatal",
                    raised_by="step-a",
                    severity="critical",
                    message="forced failure",
                    resolved=False,
                )
            )
            run_state.final_verdict = verdict_status
            return ExecutionResult(run_state=run_state)

        monkeypatch.setattr(
            "governance.dag_runner.cli.execute_plan", _mock_execute_plan,
        )
        assert main() == EXIT_CONTRACT_FAILURE


class TestExitCodeArtifactFailure:
    """Exit code 4 for artifact write failures."""

    def test_artifact_failure_exit_code_four(self, monkeypatch, capsys) -> None:
        """Artifact write failure → exit code 4."""
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--mode", "agent_execution"])

        def _mock_execute_plan(spec, plan, *, verdict_status=None, config=None,
                               backend=None, prior_state=None):
            from governance.dag_runner.models import GovernanceRunState, NodeResult
            from governance.dag_runner.executor import ExecutionResult
            from datetime import datetime, timezone

            run_state = GovernanceRunState(
                run_id="test-artifact-fail",
                started_at=datetime.now(timezone.utc),
            )
            run_state.node_results["step-a"] = NodeResult(
                node_name="step-a",
                node_type="constitution",
                status="FAIL",
                summary="Artifact write failed for: alpha_out",
                evidence=["artifact_write_failed=alpha_out"],
            )
            run_state.final_verdict = verdict_status
            return ExecutionResult(run_state=run_state)

        monkeypatch.setattr(
            "governance.dag_runner.cli.execute_plan", _mock_execute_plan,
        )
        assert main() == EXIT_ARTIFACT_FAILURE


class TestExitCodeVerdictMapping:
    """Exit codes 10 and 11 for verdict statuses."""

    def test_verdict_review_only_exit_code_ten(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["dag-runner"])

        from governance.dag_runner.verdict import GovernanceVerdict
        monkeypatch.setattr(
            "governance.dag_runner.cli.compute_verdict",
            lambda validation_result, blocker_summary: GovernanceVerdict(
                status="review_only",
                reasons=["test reason"],
            ),
        )
        assert main() == EXIT_VERDICT_REVIEW_ONLY

    def test_verdict_blocked_exit_code_eleven(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["dag-runner"])

        from governance.dag_runner.verdict import GovernanceVerdict
        monkeypatch.setattr(
            "governance.dag_runner.cli.compute_verdict",
            lambda validation_result, blocker_summary: GovernanceVerdict(
                status="blocked",
                reasons=["test reason"],
            ),
        )
        assert main() == EXIT_VERDICT_BLOCKED
