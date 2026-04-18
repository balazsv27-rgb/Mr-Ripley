"""Tests for R2-B: drift detection integration in CLI.

Verifies that critical drifts block execution and informational drifts
produce warnings without blocking.
"""
from __future__ import annotations

import json
import sys

import pytest

from governance.dag_runner.cli import main
from governance.dag_runner.drift_detector import DriftIssue, DriftResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_drift() -> DriftResult:
    return DriftResult(is_clean=True, critical_drifts=[], informational_drifts=[])


def _critical_drift() -> DriftResult:
    return DriftResult(
        is_clean=False,
        critical_drifts=[
            DriftIssue(
                check="agent_file_existence",
                severity="critical",
                message="Agent 'missing-agent' has no file.",
            ),
        ],
        informational_drifts=[],
    )


def _informational_drift() -> DriftResult:
    return DriftResult(
        is_clean=True,
        critical_drifts=[],
        informational_drifts=[
            DriftIssue(
                check="hook_reinforcement_consistency",
                severity="informational",
                message="Hook does not read artifact 'foo'.",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDriftDetectionCLI:
    """Drift detection integration in the CLI pipeline."""

    def test_critical_drift_blocks_execution(self, monkeypatch, capsys) -> None:
        """Critical drift → exit 1, CRITICAL DRIFT on stderr."""
        monkeypatch.setattr(sys, "argv", ["dag-runner"])
        monkeypatch.setattr(
            "governance.dag_runner.cli.detect_drift",
            lambda spec, repo_root: _critical_drift(),
        )

        exit_code = main()

        assert exit_code == 1
        err = capsys.readouterr().err
        assert "CRITICAL DRIFT" in err

    def test_clean_drift_proceeds(self, monkeypatch, capsys) -> None:
        """No drifts → exit 0, execution proceeds normally."""
        monkeypatch.setattr(sys, "argv", ["dag-runner"])
        monkeypatch.setattr(
            "governance.dag_runner.cli.detect_drift",
            lambda spec, repo_root: _clean_drift(),
        )

        exit_code = main()

        assert exit_code == 0

    def test_informational_drift_warns_but_proceeds(
        self, monkeypatch, capsys,
    ) -> None:
        """Informational drifts → exit 0, DRIFT WARNING on stderr."""
        monkeypatch.setattr(sys, "argv", ["dag-runner"])
        monkeypatch.setattr(
            "governance.dag_runner.cli.detect_drift",
            lambda spec, repo_root: _informational_drift(),
        )

        exit_code = main()

        assert exit_code == 0
        err = capsys.readouterr().err
        assert "DRIFT WARNING" in err

    def test_critical_drift_json_output(self, monkeypatch, capsys) -> None:
        """Critical drift with --json → JSON error payload on stdout."""
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--json"])
        monkeypatch.setattr(
            "governance.dag_runner.cli.detect_drift",
            lambda spec, repo_root: _critical_drift(),
        )

        exit_code = main()

        assert exit_code == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["error"] == "critical_drift_detected"
        assert len(data["critical_drifts"]) == 1

    def test_drift_info_in_json_output(self, monkeypatch, capsys) -> None:
        """Clean run with --json → drift_clean and drift count in output."""
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--json"])
        monkeypatch.setattr(
            "governance.dag_runner.cli.detect_drift",
            lambda spec, repo_root: _clean_drift(),
        )

        exit_code = main()

        assert exit_code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["drift_clean"] is True
        assert data["drift_informational_count"] == 0
