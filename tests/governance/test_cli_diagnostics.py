"""Tests for R2-C: diagnostics integration in CLI.

Verifies that diagnostic reports are included in both JSON and text output.
"""
from __future__ import annotations

import json
import sys

import pytest

from governance.dag_runner.cli import main


class TestDiagnosticsCLI:
    """Diagnostics integration in the CLI pipeline."""

    def test_diagnostics_in_json_output(self, monkeypatch, capsys) -> None:
        """--json output includes a 'diagnostics' key with expected fields."""
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--json"])

        exit_code = main()

        assert exit_code == 0
        out = capsys.readouterr().out
        data = json.loads(out)

        assert "diagnostics" in data
        diag = data["diagnostics"]
        assert "total_steps" in diag
        assert "executed_steps" in diag
        assert "skipped_steps" in diag
        assert "failed_steps" in diag
        assert "total_latency_ms" in diag
        assert "total_tokens" in diag
        assert "critical_path" in diag
        assert "bottleneck_step" in diag
        assert "steps" in diag
        assert isinstance(diag["steps"], list)

    def test_diagnostics_in_text_output(self, monkeypatch, capsys) -> None:
        """Text output includes a Diagnostics section."""
        monkeypatch.setattr(sys, "argv", ["dag-runner"])

        exit_code = main()

        assert exit_code == 0
        out = capsys.readouterr().out

        assert "Diagnostics" in out
        assert "Total latency" in out
        assert "Critical path" in out
        assert "Failed steps" in out

    def test_diagnostics_step_count_matches(self, monkeypatch, capsys) -> None:
        """Diagnostics total_steps matches planned_steps."""
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--json"])

        exit_code = main()

        assert exit_code == 0
        out = capsys.readouterr().out
        data = json.loads(out)

        assert data["diagnostics"]["total_steps"] == data["planned_steps"]

    def test_diagnostics_steps_have_expected_fields(
        self, monkeypatch, capsys,
    ) -> None:
        """Each step diagnostic has the expected field set."""
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--json"])

        exit_code = main()

        assert exit_code == 0
        out = capsys.readouterr().out
        data = json.loads(out)

        for step_diag in data["diagnostics"]["steps"]:
            assert "step_id" in step_diag
            assert "status" in step_diag
            assert "latency_ms" in step_diag
            assert "token_count" in step_diag
            assert "component_kind" in step_diag
            assert "inference_used" in step_diag
