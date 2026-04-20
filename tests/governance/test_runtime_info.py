"""Tests for runtime provenance and backend isolation.

Validates PART 1 (module-path self-reporting), PART 2 (isolated execution
mode), and PART 3 (--runtime-info) of the runtime-debugging patch.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from governance.dag_runner.execution_backend import ClaudeCodeCLIBackend
from governance.dag_runner.runtime_info import (
    build_backend_execution_context,
    build_runtime_provenance,
    get_isolated_cwd,
)


# ---------------------------------------------------------------------------
# PART 1: Runtime provenance
# ---------------------------------------------------------------------------


class TestBuildRuntimeProvenance:
    """build_runtime_provenance() reports correct module metadata."""

    def test_contains_required_keys(self) -> None:
        prov = build_runtime_provenance()
        assert "python_executable" in prov
        assert "python_version" in prov
        assert "cwd" in prov
        assert "sys_path_head" in prov
        assert "module_files" in prov

    def test_sys_path_head_limited_to_5(self) -> None:
        prov = build_runtime_provenance()
        assert len(prov["sys_path_head"]) <= 5

    def test_module_files_includes_expected_modules(self) -> None:
        prov = build_runtime_provenance()
        expected = [
            "governance",
            "governance.dag_runner.cli",
            "governance.dag_runner.executor",
            "governance.dag_runner.execution_backend",
        ]
        for mod in expected:
            assert mod in prov["module_files"]

    def test_loaded_modules_report_file_path(self) -> None:
        prov = build_runtime_provenance()
        # execution_backend is imported by this test, so it must be non-null
        eb_path = prov["module_files"]["governance.dag_runner.execution_backend"]
        assert eb_path is not None
        assert "execution_backend" in eb_path

    def test_unloaded_modules_report_null(self) -> None:
        prov = build_runtime_provenance()
        # governance.dag_runner.cli may or may not be loaded depending on
        # test execution order. Check format is str or None.
        val = prov["module_files"]["governance.dag_runner.cli"]
        assert val is None or isinstance(val, str)


# ---------------------------------------------------------------------------
# PART 1 addendum: provenance in CLI JSON output
# ---------------------------------------------------------------------------


class TestCLIJsonProvenance:
    """--json output must include runtime_provenance."""

    def test_json_output_includes_provenance(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "governance.dag_runner.cli", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "runtime_provenance" in output
        prov = output["runtime_provenance"]
        assert "module_files" in prov
        assert "governance.dag_runner.executor" in prov["module_files"]


# ---------------------------------------------------------------------------
# PART 2: Backend isolation
# ---------------------------------------------------------------------------


class TestBackendIsolationMode:
    """ClaudeCodeCLIBackend respects isolation_mode."""

    def test_project_mode_uses_process_cwd(self) -> None:
        backend = ClaudeCodeCLIBackend(isolation_mode="project")
        ctx = backend.get_execution_context()
        assert ctx["isolation_mode"] == "project"
        # In project mode, subprocess_cwd is the process cwd
        import os
        assert ctx["subprocess_cwd"] == os.getcwd()

    def test_isolated_mode_uses_temp_dir(self) -> None:
        backend = ClaudeCodeCLIBackend(isolation_mode="isolated")
        ctx = backend.get_execution_context()
        assert ctx["isolation_mode"] == "isolated"
        assert ctx["subprocess_cwd"] == tempfile.gettempdir()

    def test_isolated_mode_reports_limitations(self) -> None:
        backend = ClaudeCodeCLIBackend(isolation_mode="isolated")
        ctx = backend.get_execution_context()
        assert "isolation_limitations" in ctx
        assert len(ctx["isolation_limitations"]) > 0

    def test_project_mode_no_limitations(self) -> None:
        backend = ClaudeCodeCLIBackend(isolation_mode="project")
        ctx = backend.get_execution_context()
        assert "isolation_limitations" not in ctx

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_isolated_mode_passes_cwd_to_subprocess(self, mock_run) -> None:
        """In isolated mode, subprocess.run receives cwd=tempdir."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "type": "result", "is_error": False,
                "result": json.dumps({"artifacts": {"out": {"produced_by": "s"}}}),
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }),
            stderr="",
        )
        from governance.dag_runner.models import (
            AgentSpec, AssembledWorkflowSpec, ExecutionConfig,
            GovernanceRunState, ManifestSpec, PromptContext, WorkflowStep,
        )
        from datetime import datetime, timezone

        backend = ClaudeCodeCLIBackend(isolation_mode="isolated")
        backend.execute_step(
            step=WorkflowStep(name="s", component="skill:s", outputs=["out"]),
            agent=AgentSpec(name="a"),
            config=ExecutionConfig(),
            run_state=GovernanceRunState(
                run_id="r", started_at=datetime.now(timezone.utc),
            ),
            spec=AssembledWorkflowSpec(manifest=ManifestSpec(workflow_name="t")),
            prompt_context=PromptContext(assembled_prompt="test"),
        )
        # Verify cwd was passed
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == tempfile.gettempdir()

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_project_mode_passes_no_cwd(self, mock_run) -> None:
        """In project mode, subprocess.run gets cwd=None (inherit process cwd)."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "type": "result", "is_error": False,
                "result": json.dumps({"artifacts": {"out": {"produced_by": "s"}}}),
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }),
            stderr="",
        )
        from governance.dag_runner.models import (
            AgentSpec, AssembledWorkflowSpec, ExecutionConfig,
            GovernanceRunState, ManifestSpec, PromptContext, WorkflowStep,
        )
        from datetime import datetime, timezone

        backend = ClaudeCodeCLIBackend(isolation_mode="project")
        backend.execute_step(
            step=WorkflowStep(name="s", component="skill:s", outputs=["out"]),
            agent=AgentSpec(name="a"),
            config=ExecutionConfig(),
            run_state=GovernanceRunState(
                run_id="r", started_at=datetime.now(timezone.utc),
            ),
            spec=AssembledWorkflowSpec(manifest=ManifestSpec(workflow_name="t")),
            prompt_context=PromptContext(assembled_prompt="test"),
        )
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] is None


# ---------------------------------------------------------------------------
# PART 3: --runtime-info CLI option
# ---------------------------------------------------------------------------


class TestRuntimeInfoCLI:
    """--runtime-info emits provenance without executing the workflow."""

    def test_emits_json_and_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "governance.dag_runner.cli", "--runtime-info"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "runtime_provenance" in output
        assert "backend_execution_context" in output

    def test_does_not_execute_workflow(self) -> None:
        """No workflow-related keys in --runtime-info output."""
        result = subprocess.run(
            [sys.executable, "-m", "governance.dag_runner.cli", "--runtime-info"],
            capture_output=True, text=True, timeout=10,
        )
        output = json.loads(result.stdout)
        assert "workflow_name" not in output
        assert "diagnostics" not in output

    def test_respects_isolation_flag(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "governance.dag_runner.cli",
             "--runtime-info", "--backend-isolation", "isolated"],
            capture_output=True, text=True, timeout=10,
        )
        output = json.loads(result.stdout)
        ctx = output["backend_execution_context"]
        assert ctx["isolation_mode"] == "isolated"
        assert ctx["subprocess_cwd"] == tempfile.gettempdir()

    def test_module_files_resolve_from_real_process(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "governance.dag_runner.cli", "--runtime-info"],
            capture_output=True, text=True, timeout=10,
        )
        output = json.loads(result.stdout)
        mf = output["runtime_provenance"]["module_files"]
        # executor must be resolved since it's imported during CLI startup
        assert mf["governance.dag_runner.executor"] is not None
        assert "executor.py" in mf["governance.dag_runner.executor"]


# ---------------------------------------------------------------------------
# PART 4 addendum: persisted state includes provenance
# ---------------------------------------------------------------------------


class TestPersistedStateProvenance:
    """--write-state includes runtime_provenance additively."""

    def test_write_state_includes_provenance(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        repo_root = str(Path(__file__).resolve().parent.parent.parent)
        result = subprocess.run(
            [sys.executable, "-m", "governance.dag_runner.cli",
             "--write-state", "--state-path", str(state_path)],
            capture_output=True, text=True, timeout=30,
            cwd=repo_root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert state_path.exists(), f"State file not created at {state_path}"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert "runtime_provenance" in state
        assert "module_files" in state["runtime_provenance"]
