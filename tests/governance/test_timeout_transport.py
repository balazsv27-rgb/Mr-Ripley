"""Tests for timeout transport diagnostics.

Verifies that:
1. TimeoutExpired with partial stdout produces a diagnostic bundle containing it
2. TimeoutExpired with stderr produces a diagnostic bundle containing it
3. failure_detail includes timeout_diagnostic_bundle_path
4. Executor debug artifact references the transport-level timeout bundle
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from governance.dag_runner.execution_backend import (
    ClaudeCodeCLIBackend,
    MockExecutionBackend,
    write_timeout_diagnostic_bundle,
)
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.models import (
    AgentExecutionResult,
    AgentSpec,
    AssembledWorkflowSpec,
    ExecutionConfig,
    FailureClassification,
    GovernanceRunState,
    ManifestSpec,
    PromptContext,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan, PlannedNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_state() -> GovernanceRunState:
    return GovernanceRunState(
        run_id="test-run",
        started_at=datetime.now(timezone.utc),
    )


def _make_step(
    name: str = "test-step",
    outputs: list[str] | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        name=name,
        component="skill:test-skill",
        outputs=["test_artifact"] if outputs is None else outputs,
        raw={"agent_binding": "test-skill"},
    )


def _make_agent(
    name: str = "test-agent",
    model: str = "sonnet",
    timeout_ms: int | None = None,
) -> AgentSpec:
    return AgentSpec(
        name=name, model=model,
        skill_bindings=["test-skill"],
        timeout_ms=timeout_ms,
    )


def _make_spec(
    steps: dict[str, WorkflowStep] | None = None,
) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test"),
        workflow_steps=steps or {},
        agents={"test-skill": AgentSpec(name="test-skill")},
    )


def _make_prompt_context(prompt: str = "You are a test skill.") -> PromptContext:
    return PromptContext(assembled_prompt=prompt)


def _make_plan(step_ids: list[str]) -> ExecutionPlan:
    return ExecutionPlan(
        workflow_name="test",
        ordered_steps=[
            PlannedNode(step_id=sid, component="skill:test-skill")
            for sid in step_ids
        ],
    )


def _default_config() -> ExecutionConfig:
    return ExecutionConfig(mode="agent_execution", request_text="test")


# ---------------------------------------------------------------------------
# Unit tests: write_timeout_diagnostic_bundle
# ---------------------------------------------------------------------------


class TestWriteTimeoutDiagnosticBundle:
    """Unit tests for the bundle writer function."""

    def test_writes_bundle_with_partial_stdout(self, tmp_path: Path) -> None:
        partial = '{"artifacts": {"claim_map": {"status": "partial'
        written, path, err = write_timeout_diagnostic_bundle(
            step_name="classify-claims",
            command=["claude", "-p", "--model", "sonnet"],
            timeout_seconds=120.0,
            elapsed_seconds=120.3,
            partial_stdout=partial,
            partial_stderr="",
            assembled_prompt="You are a classification skill.",
            debug_dir=str(tmp_path),
        )
        assert written is True
        assert path is not None
        assert err is None

        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert content["step_name"] == "classify-claims"
        assert content["bundle_type"] == "timeout_transport_diagnostic"
        assert content["partial_stdout"] == partial
        assert content["partial_stdout_length"] == len(partial)
        assert content["timeout_phase"] == "during_response"
        assert content["partial_json_detected"] is True
        assert content["timeout_seconds"] == 120.0
        assert content["elapsed_seconds"] == 120.3
        assert content["command"] == ["claude", "-p", "--model", "sonnet"]

    def test_writes_bundle_with_stderr(self, tmp_path: Path) -> None:
        stderr_text = "WARN: connection reset by peer"
        written, path, err = write_timeout_diagnostic_bundle(
            step_name="route-claims",
            command=["claude", "-p"],
            timeout_seconds=60.0,
            elapsed_seconds=60.1,
            partial_stdout="",
            partial_stderr=stderr_text,
            debug_dir=str(tmp_path),
        )
        assert written is True
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert content["partial_stderr"] == stderr_text
        assert content["partial_stderr_length"] == len(stderr_text)
        assert content["timeout_phase"] == "before_response"

    def test_bundle_includes_prompt_text(self, tmp_path: Path) -> None:
        prompt = "You are a governance skill. Classify all claims."
        written, path, _ = write_timeout_diagnostic_bundle(
            step_name="step-x",
            command=["claude", "-p"],
            timeout_seconds=120.0,
            elapsed_seconds=119.5,
            assembled_prompt=prompt,
            debug_dir=str(tmp_path),
        )
        assert written is True
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert content["assembled_prompt_first_2000"] == prompt
        assert content["assembled_prompt_length"] == len(prompt)

    def test_bundle_includes_prompt_composition(self, tmp_path: Path) -> None:
        composition = {
            "sections": ["skill_content", "agent_instructions", "artifacts"],
            "token_estimate": 45000,
        }
        written, path, _ = write_timeout_diagnostic_bundle(
            step_name="step-y",
            command=["claude", "-p"],
            timeout_seconds=120.0,
            elapsed_seconds=120.0,
            prompt_composition=composition,
            debug_dir=str(tmp_path),
        )
        assert written is True
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert content["prompt_composition"] == composition

    def test_before_response_phase_when_no_stdout(self, tmp_path: Path) -> None:
        written, path, _ = write_timeout_diagnostic_bundle(
            step_name="step-z",
            command=["claude", "-p"],
            timeout_seconds=60.0,
            elapsed_seconds=60.0,
            partial_stdout="",
            partial_stderr="",
            debug_dir=str(tmp_path),
        )
        assert written is True
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert content["timeout_phase"] == "before_response"
        assert "partial_json_detected" not in content

    def test_partial_json_detected_false_for_non_json(self, tmp_path: Path) -> None:
        written, path, _ = write_timeout_diagnostic_bundle(
            step_name="step-w",
            command=["claude", "-p"],
            timeout_seconds=60.0,
            elapsed_seconds=60.0,
            partial_stdout="Based on my analysis of the request...",
            debug_dir=str(tmp_path),
        )
        assert written is True
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert content["partial_json_detected"] is False

    def test_returns_error_on_write_failure(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        written, path, err = write_timeout_diagnostic_bundle(
            step_name="step-fail",
            command=["claude"],
            timeout_seconds=60.0,
            elapsed_seconds=60.0,
            debug_dir=str(blocker),
        )
        assert written is False
        assert path is None
        assert err is not None

    def test_bundle_filename_pattern(self, tmp_path: Path) -> None:
        written, path, _ = write_timeout_diagnostic_bundle(
            step_name="my-step",
            command=["claude", "-p"],
            timeout_seconds=60.0,
            elapsed_seconds=60.0,
            debug_dir=str(tmp_path),
        )
        assert written is True
        assert Path(path).name == "my-step_timeout_bundle.json"


# ---------------------------------------------------------------------------
# Backend-level tests: transport evidence captured from TimeoutExpired
# ---------------------------------------------------------------------------


class TestBackendTimeoutTransportCapture:
    """ClaudeCodeCLIBackend captures stdout/stderr/cmd from TimeoutExpired."""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_partial_stdout_captured(self, mock_run: mock.MagicMock) -> None:
        exc = subprocess.TimeoutExpired(cmd=["claude", "-p"], timeout=120)
        exc.stdout = '{"artifacts": {"partial'
        exc.stderr = ""
        mock_run.side_effect = exc

        backend = ClaudeCodeCLIBackend(timeout_ms=120_000, max_retries=0)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is False
        assert result.failure.origin == "timeout"
        assert result.timeout_stdout == '{"artifacts": {"partial'
        assert result.timeout_command == ["claude", "-p"]
        assert result.timeout_seconds == 120.0
        assert result.elapsed_seconds >= 0  # near-zero with mocked subprocess

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_stderr_captured(self, mock_run: mock.MagicMock) -> None:
        exc = subprocess.TimeoutExpired(cmd=["claude", "-p"], timeout=60)
        exc.stdout = ""
        exc.stderr = "WARN: API timeout after 55s"
        mock_run.side_effect = exc

        backend = ClaudeCodeCLIBackend(timeout_ms=60_000, max_retries=0)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.timeout_stderr == "WARN: API timeout after 55s"

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_none_stdout_handled_as_empty(self, mock_run: mock.MagicMock) -> None:
        exc = subprocess.TimeoutExpired(cmd=["claude", "-p"], timeout=120)
        exc.stdout = None
        exc.stderr = None
        mock_run.side_effect = exc

        backend = ClaudeCodeCLIBackend(timeout_ms=120_000, max_retries=0)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.timeout_stdout == ""
        assert result.timeout_stderr == ""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_bytes_stdout_decoded(self, mock_run: mock.MagicMock) -> None:
        exc = subprocess.TimeoutExpired(cmd=["claude", "-p"], timeout=120)
        exc.stdout = b'{"partial": true}'
        exc.stderr = b"stderr bytes"
        mock_run.side_effect = exc

        backend = ClaudeCodeCLIBackend(timeout_ms=120_000, max_retries=0)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.timeout_stdout == '{"partial": true}'
        assert result.timeout_stderr == "stderr bytes"

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_timeout_seconds_and_command_populated(self, mock_run: mock.MagicMock) -> None:
        exc = subprocess.TimeoutExpired(cmd=["claude", "-p", "--model", "opus"], timeout=180)
        exc.stdout = ""
        exc.stderr = ""
        mock_run.side_effect = exc

        backend = ClaudeCodeCLIBackend(timeout_ms=120_000, max_retries=0)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(timeout_ms=180_000),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.timeout_seconds == 180.0
        assert result.timeout_command == ["claude", "-p", "--model", "opus"]


# ---------------------------------------------------------------------------
# Executor-level tests: timeout diagnostic bundle in failure_detail
# ---------------------------------------------------------------------------


class TimeoutTransportMockBackend(MockExecutionBackend):
    """Backend that simulates a timeout with transport evidence."""

    def __init__(
        self,
        failing_steps: set[str],
        *,
        partial_stdout: str = "",
        partial_stderr: str = "",
        timeout_command: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._failing_steps = failing_steps
        self._partial_stdout = partial_stdout
        self._partial_stderr = partial_stderr
        self._timeout_command = timeout_command or ["claude", "-p"]

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        if step.name in self._failing_steps:
            return AgentExecutionResult(
                success=False,
                latency_ms=120_000.0,
                failure=FailureClassification(
                    origin="timeout",
                    step_id=step.name,
                    detail="Claude CLI subprocess timed out after 120000ms.",
                ),
                returncode=None,
                timeout_stdout=self._partial_stdout,
                timeout_stderr=self._partial_stderr,
                timeout_command=self._timeout_command,
                timeout_seconds=120.0,
                elapsed_seconds=120.3,
            )
        return super().execute_step(
            step, agent, config, run_state, spec,
            prompt_context=prompt_context, **kwargs,
        )


class TestExecutorTimeoutBundle:
    """Executor writes timeout diagnostic bundle and surfaces path in failure_detail."""

    def test_timeout_bundle_written_and_path_in_failure_detail(self) -> None:
        step = _make_step("step-a", outputs=["claim_map"])
        steps = {"step-a": step}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = TimeoutTransportMockBackend(
            {"step-a"},
            partial_stdout='{"artifacts": {"claim_map": {"partial',
            partial_stderr="WARN: slow response",
            timeout_command=["claude", "-p", "--model", "sonnet"],
        )

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        assert nr.failure_detail["failure_origin"] == "timeout"
        assert nr.failure_detail["failure_stage"] == "backend_timeout"
        # Bundle path must be present
        assert "timeout_diagnostic_bundle_path" in nr.failure_detail
        bundle_path = Path(nr.failure_detail["timeout_diagnostic_bundle_path"])
        assert bundle_path.exists()

        # Verify bundle content
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        assert bundle["bundle_type"] == "timeout_transport_diagnostic"
        assert bundle["step_name"] == "step-a"
        assert '{"artifacts"' in bundle["partial_stdout"]
        assert bundle["partial_stderr"] == "WARN: slow response"
        assert bundle["timeout_seconds"] == 120.0
        assert bundle["elapsed_seconds"] == 120.3
        assert bundle["command"] == ["claude", "-p", "--model", "sonnet"]
        assert bundle["timeout_phase"] == "during_response"
        assert bundle["partial_json_detected"] is True

    def test_timeout_bundle_contains_partial_stdout(self) -> None:
        """Partial stdout from killed subprocess is preserved in bundle."""
        partial = '{"artifacts": {"normalized_terminology_map": {"terms": ['
        step = _make_step("normalize-terms", outputs=["normalized_terminology_map"])
        steps = {"normalize-terms": step}
        spec = _make_spec(steps)
        plan = _make_plan(["normalize-terms"])
        backend = TimeoutTransportMockBackend(
            {"normalize-terms"},
            partial_stdout=partial,
        )

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["normalize-terms"]

        bundle_path = Path(nr.failure_detail["timeout_diagnostic_bundle_path"])
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        assert bundle["partial_stdout"] == partial
        assert bundle["partial_stdout_length"] == len(partial)

    def test_timeout_bundle_contains_stderr(self) -> None:
        """Stderr from killed subprocess is preserved in bundle."""
        stderr = "error: API rate limit exceeded\nretrying in 30s..."
        step = _make_step("step-b", outputs=["art_b"])
        steps = {"step-b": step}
        spec = _make_spec(steps)
        plan = _make_plan(["step-b"])
        backend = TimeoutTransportMockBackend(
            {"step-b"},
            partial_stderr=stderr,
        )

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-b"]

        bundle_path = Path(nr.failure_detail["timeout_diagnostic_bundle_path"])
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        assert bundle["partial_stderr"] == stderr

    def test_timeout_transport_fields_in_failure_detail(self) -> None:
        """Transport-level fields are surfaced in failure_detail."""
        step = _make_step("step-c", outputs=["art_c"])
        steps = {"step-c": step}
        spec = _make_spec(steps)
        plan = _make_plan(["step-c"])
        backend = TimeoutTransportMockBackend(
            {"step-c"},
            timeout_command=["claude", "-p", "--model", "opus"],
        )

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-c"]

        assert nr.failure_detail["timeout_seconds"] == 120.0
        assert nr.failure_detail["elapsed_seconds"] == 120.3
        assert nr.failure_detail["timeout_command"] == ["claude", "-p", "--model", "opus"]
        assert nr.failure_detail["timeout_stdout_len"] == 0
        assert nr.failure_detail["timeout_stderr_len"] == 0

    def test_timeout_trace_event_includes_transport_evidence(self) -> None:
        """backend_timeout trace event includes transport-level fields."""
        step = _make_step("step-d", outputs=["art_d"])
        steps = {"step-d": step}
        spec = _make_spec(steps)
        plan = _make_plan(["step-d"])
        backend = TimeoutTransportMockBackend(
            {"step-d"},
            partial_stdout="partial output here",
            partial_stderr="some warning",
        )

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        timeout_events = [
            e for e in result.run_state.execution_trace
            if e.event_type == "backend_timeout"
        ]
        assert len(timeout_events) == 1
        detail = timeout_events[0].detail
        assert detail["timeout_seconds"] == 120.0
        assert detail["elapsed_seconds"] == 120.3
        assert detail["timeout_stdout_len"] == len("partial output here")
        assert detail["timeout_stderr_len"] == len("some warning")
        assert "timeout_diagnostic_bundle_path" in detail

    def test_debug_artifact_also_written_alongside_bundle(self) -> None:
        """Standard debug artifact is still written in addition to bundle."""
        step = _make_step("step-e", outputs=["art_e"])
        steps = {"step-e": step}
        spec = _make_spec(steps)
        plan = _make_plan(["step-e"])
        backend = TimeoutTransportMockBackend({"step-e"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-e"]

        # Both debug artifact and timeout bundle should be written
        assert nr.failure_detail["debug_artifact_written"] is True
        assert nr.failure_detail["debug_artifact_path"] is not None
        assert "timeout_diagnostic_bundle_path" in nr.failure_detail
        # They should be different files
        debug_path = nr.failure_detail["debug_artifact_path"]
        bundle_path = nr.failure_detail["timeout_diagnostic_bundle_path"]
        assert debug_path != bundle_path

    def test_executor_preserves_timeout_classification(self) -> None:
        """Timeout with transport evidence does not change classification."""
        step = _make_step("step-f", outputs=["art_f"])
        steps = {"step-f": step}
        spec = _make_spec(steps)
        plan = _make_plan(["step-f"])
        backend = TimeoutTransportMockBackend(
            {"step-f"},
            partial_stdout="some partial output",
            partial_stderr="some stderr",
        )

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-f"]

        # Classification must remain timeout/backend_timeout
        assert nr.failure_detail["failure_origin"] == "timeout"
        assert nr.failure_detail["failure_stage"] == "backend_timeout"
        # Must NOT be misclassified
        assert nr.failure_detail["failure_stage"] != "executor_declared_output_check"
        assert nr.failure_detail["failure_stage"] != "backend_parse"
