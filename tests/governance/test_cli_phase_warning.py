"""Tests for R3-B: --phase flag deferred warning (Option B).

Verifies that --phase emits a warning and continues with all steps.
"""
from __future__ import annotations

import sys

import pytest

from governance.dag_runner.cli import main


class TestPhaseWarning:
    """--phase flag emits a warning and executes all steps."""

    def test_phase_flag_emits_warning(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--phase", "A"])

        exit_code = main()

        err = capsys.readouterr().err
        assert "Phase scoping" in err
        assert "not yet implemented" in err

    def test_phase_flag_still_executes_all_steps(
        self, monkeypatch, capsys,
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["dag-runner", "--phase", "A"])

        exit_code = main()

        out = capsys.readouterr().out
        # All 18 steps should still execute
        assert "Planned steps: 18" in out
        assert "Executed steps: 18" in out
