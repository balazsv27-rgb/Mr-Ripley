"""
Tests for governance/dag_runner/cli.py — end-to-end CLI integration.

Tests invoke main() directly with a monkeypatched sys.argv so that argparse
reads the test arguments instead of pytest's own arguments.
Output is captured with capsys.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from governance.dag_runner.cli import main


# ---------------------------------------------------------------------------
# 1. Basic run — no extra arguments
# ---------------------------------------------------------------------------


def test_cli_basic_run_succeeds(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["dag-runner"])

    exit_code = main()

    assert exit_code == 0, "CLI basic run must exit with code 0."
    out = capsys.readouterr().out

    # Core summary markers that are stable in the current output
    assert "Validation" in out
    assert "Verdict" in out
    assert "Planned steps" in out
    assert "Executed steps" in out


def test_cli_basic_run_reports_ready_verdict(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["dag-runner"])

    exit_code = main()

    assert exit_code == 0
    out = capsys.readouterr().out

    # Verdict must be READY for the current workflow
    assert "READY" in out


def test_cli_basic_run_reports_workflow_name(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["dag-runner"])

    exit_code = main()

    assert exit_code == 0
    out = capsys.readouterr().out

    assert "mr-ripley-governance-orchestration" in out


def test_cli_basic_run_reports_step_counts(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["dag-runner"])

    exit_code = main()

    assert exit_code == 0
    out = capsys.readouterr().out

    # Both planned and executed step counts should appear
    assert "Planned steps: 18" in out
    assert "Executed steps: 18" in out


# ---------------------------------------------------------------------------
# 2. --show-steps
# ---------------------------------------------------------------------------


def test_cli_show_steps_succeeds(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["dag-runner", "--show-steps"])

    exit_code = main()

    assert exit_code == 0
    out = capsys.readouterr().out

    # Execution order section must appear
    assert "Execution order" in out


def test_cli_show_steps_includes_first_step(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["dag-runner", "--show-steps"])

    exit_code = main()

    assert exit_code == 0
    out = capsys.readouterr().out

    # The first topological step must be listed
    assert "load-context" in out


def test_cli_show_steps_lists_all_steps(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["dag-runner", "--show-steps"])

    exit_code = main()

    assert exit_code == 0
    out = capsys.readouterr().out

    # All 18 steps must appear — the last step number will be "18."
    # Check for the prefix that would only appear if ≥18 steps were printed.
    assert "18." in out


# ---------------------------------------------------------------------------
# 3. --write-state
# ---------------------------------------------------------------------------


def test_cli_write_state_creates_file(monkeypatch, capsys, tmp_path: Path) -> None:
    state_file = tmp_path / "governance_run_state.json"
    monkeypatch.setattr(
        sys, "argv",
        ["dag-runner", "--write-state", "--state-path", str(state_file)],
    )

    exit_code = main()

    assert exit_code == 0, "CLI --write-state run must exit with code 0."
    assert state_file.exists(), "Run-state file must be created by --write-state."
    assert state_file.is_file()


def test_cli_write_state_produces_valid_json(monkeypatch, capsys, tmp_path: Path) -> None:
    state_file = tmp_path / "governance_run_state.json"
    monkeypatch.setattr(
        sys, "argv",
        ["dag-runner", "--write-state", "--state-path", str(state_file)],
    )

    exit_code = main()

    assert exit_code == 0
    raw = state_file.read_text(encoding="utf-8")
    payload = json.loads(raw)  # raises if not valid JSON

    assert isinstance(payload, dict)
    assert payload  # non-empty


def test_cli_write_state_json_contains_verdict(monkeypatch, capsys, tmp_path: Path) -> None:
    state_file = tmp_path / "governance_run_state.json"
    monkeypatch.setattr(
        sys, "argv",
        ["dag-runner", "--write-state", "--state-path", str(state_file)],
    )

    exit_code = main()

    assert exit_code == 0
    payload = json.loads(state_file.read_text(encoding="utf-8"))

    assert payload.get("final_verdict") == "ready"
    assert payload.get("verdict_status") == "ready"


def test_cli_write_state_reports_written_path(monkeypatch, capsys, tmp_path: Path) -> None:
    state_file = tmp_path / "governance_run_state.json"
    monkeypatch.setattr(
        sys, "argv",
        ["dag-runner", "--write-state", "--state-path", str(state_file)],
    )

    exit_code = main()

    assert exit_code == 0
    out = capsys.readouterr().out

    # CLI should print confirmation that the file was written
    assert "Run state written" in out


# ---------------------------------------------------------------------------
# 4. Full run — --show-steps --write-state combined
# ---------------------------------------------------------------------------


def test_cli_full_run_succeeds_and_writes_state(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    state_file = tmp_path / "full_run_state.json"
    monkeypatch.setattr(
        sys, "argv",
        [
            "dag-runner",
            "--show-steps",
            "--write-state",
            "--state-path", str(state_file),
        ],
    )

    exit_code = main()

    assert exit_code == 0

    out = capsys.readouterr().out

    # Console output must contain both the summary and the execution order
    assert "Verdict" in out
    assert "Execution order" in out
    assert "load-context" in out

    # State file must be created and contain valid JSON
    assert state_file.exists()
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload.get("final_verdict") == "ready"


def test_cli_full_run_output_and_state_are_consistent(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    """Console step count must match what the written state file records."""
    state_file = tmp_path / "consistency_check.json"
    monkeypatch.setattr(
        sys, "argv",
        [
            "dag-runner",
            "--show-steps",
            "--write-state",
            "--state-path", str(state_file),
        ],
    )

    exit_code = main()

    assert exit_code == 0

    payload = json.loads(state_file.read_text(encoding="utf-8"))

    executed = payload.get("recorded_node_results", 0)
    planned = payload.get("planned_steps", 0)

    out = capsys.readouterr().out
    assert f"Executed steps: {executed}" in out
    assert f"Planned steps: {planned}" in out
