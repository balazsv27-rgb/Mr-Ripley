"""Tests for ClaudeCodeCLIBackend (Phase B4).

All tests use mocked subprocess — no real Claude CLI is invoked.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from unittest import mock

import pytest

from governance.dag_runner.execution_backend import (
    ClaudeCodeCLIBackend,
    ExecutionBackend,
    MockExecutionBackend,
    ParseResult,
    _parse_backend_response,
)
from governance.dag_runner.models import (
    AgentExecutionResult,
    AgentSpec,
    AssembledWorkflowSpec,
    ExecutionConfig,
    GovernanceRunState,
    ManifestSpec,
    PromptContext,
    WorkflowStep,
)


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
    )


def _make_agent(
    name: str = "test-agent",
    model: str = "sonnet",
) -> AgentSpec:
    return AgentSpec(name=name, model=model, skill_bindings=["test-skill"])


def _make_spec() -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(manifest=ManifestSpec(workflow_name="test"))


def _make_prompt_context(prompt: str = "You are a test skill.") -> PromptContext:
    return PromptContext(assembled_prompt=prompt)


def _make_cli_envelope(
    result_text: str,
    is_error: bool = False,
    output_tokens: int = 42,
) -> str:
    """Build a realistic Claude CLI JSON envelope."""
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result_text,
        "duration_ms": 1234,
        "duration_api_ms": 1000,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "session_id": "test-session-id",
        "total_cost_usd": 0.01,
        "usage": {
            "input_tokens": 10,
            "output_tokens": output_tokens,
        },
    })


def _make_artifact_response(
    artifacts: dict[str, dict],
    output_tokens: int = 42,
) -> str:
    """Build a CLI envelope whose result text is a valid artifact JSON."""
    result_text = json.dumps({"artifacts": artifacts})
    return _make_cli_envelope(result_text, output_tokens=output_tokens)


# ---------------------------------------------------------------------------
# ClaudeCodeCLIBackend: class and interface
# ---------------------------------------------------------------------------

class TestClaudeCodeCLIBackendInterface:
    """Backend class structure and type hierarchy."""

    def test_is_execution_backend(self) -> None:
        backend = ClaudeCodeCLIBackend()
        assert isinstance(backend, ExecutionBackend)

    def test_not_mock_backend(self) -> None:
        backend = ClaudeCodeCLIBackend()
        assert not isinstance(backend, MockExecutionBackend)

    def test_default_parameters(self) -> None:
        backend = ClaudeCodeCLIBackend()
        assert backend._default_model == "sonnet"
        assert backend._timeout_ms == 120_000
        assert backend._claude_command == "claude"

    def test_custom_parameters(self) -> None:
        backend = ClaudeCodeCLIBackend(
            model="opus", timeout_ms=60_000, claude_command="/usr/local/bin/claude",
        )
        assert backend._default_model == "opus"
        assert backend._timeout_ms == 60_000
        assert backend._claude_command == "/usr/local/bin/claude"


# ---------------------------------------------------------------------------
# Fail-closed: prompt_context=None
# ---------------------------------------------------------------------------

class TestFailClosedNoPromptContext:
    """ClaudeCodeCLIBackend must fail closed when prompt_context is None."""

    def test_none_prompt_context_returns_failure(self) -> None:
        backend = ClaudeCodeCLIBackend()
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=None,
        )
        assert result.success is False
        assert result.failure is not None
        assert result.failure.origin == "runtime"
        assert "prompt_context is None" in result.failure.detail

    def test_default_prompt_context_returns_failure(self) -> None:
        """Calling without prompt_context kwarg (defaults to None) also fails."""
        backend = ClaudeCodeCLIBackend()
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
        )
        assert result.success is False
        assert result.failure is not None


# ---------------------------------------------------------------------------
# Subprocess command construction
# ---------------------------------------------------------------------------

class TestSubprocessCommand:
    """Verify the subprocess command uses `claude -p`, not API calls."""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_command_uses_claude_p(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step", "data": {}}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend()
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--output-format" in cmd
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "json"
        assert "--no-session-persistence" in cmd
        # B0 frozen contract: --tools "" disables built-in tools
        assert "--tools" in cmd
        idx_tools = cmd.index("--tools")
        assert cmd[idx_tools + 1] == ""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_model_from_agent(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"out": {"produced_by": "s", "data": {}}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(model="haiku")
        agent = _make_agent(model="opus")
        backend.execute_step(
            step=_make_step(),
            agent=agent,
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        cmd = mock_run.call_args[0][0]
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "opus"

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_model_fallback_to_default(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"out": {"produced_by": "s", "data": {}}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(model="haiku")
        agent = _make_agent(model="")
        backend.execute_step(
            step=_make_step(),
            agent=agent,
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        cmd = mock_run.call_args[0][0]
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "haiku"

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_prompt_sent_on_stdin(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"out": {"produced_by": "s", "data": {}}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend()
        prompt = "This is the assembled prompt content."
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(prompt),
        )
        assert mock_run.call_args[1]["input"] == prompt


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------

class TestSuccessfulExecution:
    """Mocked subprocess returns valid JSON → success."""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_valid_response_returns_success(self, mock_run: mock.MagicMock) -> None:
        artifacts = {
            "test_artifact": {
                "produced_by": "test-step",
                "data": {"verdict": "PASS"},
            },
        }
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response(artifacts, output_tokens=55),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend()
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is True
        assert "test_artifact" in result.artifacts_produced
        assert result.artifacts_produced["test_artifact"]["data"]["verdict"] == "PASS"
        assert result.token_count == 55
        assert result.latency_ms >= 0  # mocked subprocess returns instantly
        assert result.raw_output != ""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_multiple_artifacts(self, mock_run: mock.MagicMock) -> None:
        artifacts = {
            "art_a": {"produced_by": "s", "data": {"x": 1}},
            "art_b": {"produced_by": "s", "data": {"y": 2}},
        }
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response(artifacts),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend()
        result = backend.execute_step(
            step=_make_step(outputs=["art_a", "art_b"]),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is True
        assert len(result.artifacts_produced) == 2


# ---------------------------------------------------------------------------
# Failure scenarios
# ---------------------------------------------------------------------------

class TestFailureScenarios:
    """Timeout, error exit, spawn failure."""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_timeout_returns_failure(self, mock_run: mock.MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)
        backend = ClaudeCodeCLIBackend(timeout_ms=120_000)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is False
        assert result.failure is not None
        assert result.failure.origin == "timeout"
        assert "timed out" in result.failure.detail

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_nonzero_exit_returns_failure(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="auth failed",
        )
        backend = ClaudeCodeCLIBackend()
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is False
        assert result.failure is not None
        assert result.failure.origin == "runtime"
        assert "exited with code 1" in result.failure.detail

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_spawn_failure_returns_failure(self, mock_run: mock.MagicMock) -> None:
        mock_run.side_effect = OSError("No such file or directory: 'claude'")
        backend = ClaudeCodeCLIBackend()
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is False
        assert result.failure is not None
        assert result.failure.origin == "runtime"
        assert "spawn" in result.failure.detail.lower()

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_cli_is_error_flag(self, mock_run: mock.MagicMock) -> None:
        """CLI returns exit 0 but is_error=true → success=True but empty artifacts."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_cli_envelope("error text", is_error=True),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend()
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        # Exit code 0 → success=True at subprocess level, but no artifacts parsed
        assert result.success is True
        assert result.artifacts_produced == {}
        assert result.parse_failure is not None
        assert "cli_is_error_flag" in result.parse_failure


# ---------------------------------------------------------------------------
# Response parsing (_parse_backend_response)
# ---------------------------------------------------------------------------

class TestParseBackendResponse:
    """Unit tests for the response parser."""

    def test_valid_single_artifact(self) -> None:
        raw = _make_artifact_response({
            "ctx": {"produced_by": "step-1", "data": {"key": "val"}},
        })
        result = _parse_backend_response(raw, ["ctx"])
        assert isinstance(result, ParseResult)
        assert result.failure is None
        assert "ctx" in result.artifacts
        assert result.artifacts["ctx"]["data"]["key"] == "val"

    def test_valid_multiple_artifacts(self) -> None:
        raw = _make_artifact_response({
            "a": {"produced_by": "s", "data": {}},
            "b": {"produced_by": "s", "data": {}},
        })
        result = _parse_backend_response(raw, ["a", "b"])
        assert result.failure is None
        assert len(result.artifacts) == 2

    def test_malformed_outer_json(self) -> None:
        result = _parse_backend_response("not json at all", ["x"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "outer_envelope_invalid_json" in result.failure

    def test_empty_string(self) -> None:
        result = _parse_backend_response("", ["x"])
        assert result.artifacts == {}
        assert result.failure is not None

    def test_none_input(self) -> None:
        result = _parse_backend_response(None, ["x"])  # type: ignore[arg-type]
        assert result.artifacts == {}
        assert result.failure is not None

    def test_is_error_true(self) -> None:
        raw = _make_cli_envelope("irrelevant", is_error=True)
        result = _parse_backend_response(raw, ["x"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "cli_is_error_flag" in result.failure

    def test_result_not_json(self) -> None:
        raw = _make_cli_envelope("plain text, not JSON")
        result = _parse_backend_response(raw, ["x"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "no_json_object" in result.failure
        assert result.result_preview != ""

    def test_result_json_without_artifacts_key(self) -> None:
        raw = _make_cli_envelope(json.dumps({"no_artifacts": True}))
        result = _parse_backend_response(raw, ["x"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "artifacts_dict_empty" in result.failure

    def test_artifacts_not_dict(self) -> None:
        raw = _make_cli_envelope(json.dumps({"artifacts": "string"}))
        result = _parse_backend_response(raw, ["x"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "artifacts_key_not_dict" in result.failure

    def test_non_dict_artifact_payload_filtered(self) -> None:
        raw = _make_cli_envelope(json.dumps({
            "artifacts": {
                "good": {"produced_by": "s", "data": {}},
                "bad": "not a dict",
            },
        }))
        result = _parse_backend_response(raw, ["good", "bad"])
        assert "good" in result.artifacts
        assert "bad" not in result.artifacts

    def test_empty_result_field(self) -> None:
        raw = _make_cli_envelope("")
        result = _parse_backend_response(raw, ["x"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "result_field_empty" in result.failure

    def test_prose_prefixed_json_extracted(self) -> None:
        """Parser extracts JSON when the model prefixes prose explanation."""
        inner_json = json.dumps({
            "artifacts": {
                "claim_classification_map": {
                    "produced_by": "classify-claims",
                    "classifications": [{"claim": "test", "type": "current-state"}],
                },
            },
        })
        prose_response = (
            "I was unable to read ctx.json directly. Based on the upstream "
            "artifacts provided in the prompt, here is my classification:\n\n"
            + inner_json
        )
        raw = _make_cli_envelope(prose_response)
        result = _parse_backend_response(raw, ["claim_classification_map"])
        assert result.failure is None, f"Expected no failure, got: {result.failure}"
        assert "claim_classification_map" in result.artifacts
        assert result.artifacts["claim_classification_map"]["produced_by"] == "classify-claims"

    def test_wrong_artifact_name_detected(self) -> None:
        """Parser flags when produced artifact names differ from expected."""
        raw = _make_artifact_response({
            "claim_classification": {"produced_by": "classify-claims", "data": {}},
        })
        result = _parse_backend_response(raw, ["claim_classification_map"])
        # Artifacts ARE extracted (parser doesn't gate on name)
        assert "claim_classification" in result.artifacts
        # But failure is set explaining the name mismatch
        assert result.failure is not None
        assert "wrong_artifact_names" in result.failure
        assert "claim_classification_map" in result.failure  # missing
        assert "claim_classification" in result.failure  # unexpected

    def test_correct_artifact_name_no_failure(self) -> None:
        """No failure when produced names match expected."""
        raw = _make_artifact_response({
            "claim_classification_map": {"produced_by": "classify-claims", "data": {}},
        })
        result = _parse_backend_response(raw, ["claim_classification_map"])
        assert "claim_classification_map" in result.artifacts
        assert result.failure is None

    def test_parse_failure_propagated_to_backend_result(self) -> None:
        """Backend execute_step must propagate parse_failure from ParseResult."""
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_cli_envelope("I am plain text, not JSON"),
            stderr="some warning",
        )
        with mock.patch(
            "governance.dag_runner.execution_backend.subprocess.run",
            return_value=mock_proc,
        ):
            backend = ClaudeCodeCLIBackend()
            result = backend.execute_step(
                step=_make_step(),
                agent=_make_agent(),
                config=ExecutionConfig(),
                run_state=_make_run_state(),
                spec=_make_spec(),
                prompt_context=_make_prompt_context(),
            )
        assert result.success is True
        assert result.artifacts_produced == {}
        assert result.parse_failure is not None
        assert "no_json_object" in result.parse_failure
        assert result.stderr == "some warning"

    def test_stderr_captured_on_nonzero_exit(self) -> None:
        """Backend must capture and surface stderr on non-zero exit."""
        mock_proc = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="",
            stderr="Error: authentication required",
        )
        with mock.patch(
            "governance.dag_runner.execution_backend.subprocess.run",
            return_value=mock_proc,
        ):
            backend = ClaudeCodeCLIBackend()
            result = backend.execute_step(
                step=_make_step(),
                agent=_make_agent(),
                config=ExecutionConfig(),
                run_state=_make_run_state(),
                spec=_make_spec(),
                prompt_context=_make_prompt_context(),
            )
        assert result.success is False
        assert result.stderr == "Error: authentication required"
        assert "authentication required" in result.failure.detail


# ---------------------------------------------------------------------------
# Structural step delegation
# ---------------------------------------------------------------------------

class TestStructuralStep:
    """execute_structural_step produces deterministic output without subprocess."""

    def test_structural_step_no_subprocess(self) -> None:
        backend = ClaudeCodeCLIBackend()
        step = _make_step(outputs=["governance_context"])
        result = backend.execute_structural_step(
            step=step,
            component_kind="constitution",
            run_state=_make_run_state(),
            spec=_make_spec(),
        )
        assert result.success is True
        assert "governance_context" in result.artifacts_produced
        assert result.artifacts_produced["governance_context"]["structural"] is True

    def test_structural_step_multiple_outputs(self) -> None:
        backend = ClaudeCodeCLIBackend()
        step = _make_step(outputs=["a", "b", "c"])
        result = backend.execute_structural_step(
            step=step,
            component_kind="stage_gates",
            run_state=_make_run_state(),
            spec=_make_spec(),
        )
        assert result.success is True
        assert len(result.artifacts_produced) == 3


# ---------------------------------------------------------------------------
# CLI --backend flag
# ---------------------------------------------------------------------------

class TestCLIBackendFlag:
    """CLI argument parsing selects the correct backend."""

    def test_parser_accepts_backend_flag(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["--backend", "claude_code_cli", "--mode", "agent_execution"])
        assert args.backend == "claude_code_cli"

    def test_parser_default_backend_is_none(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.backend is None

    def test_parser_accepts_mock_backend(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["--backend", "mock"])
        assert args.backend == "mock"

    def test_parser_rejects_invalid_backend(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--backend", "invalid_backend"])
