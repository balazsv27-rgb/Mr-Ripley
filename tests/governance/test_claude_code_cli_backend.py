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
    _build_artifact_json_schema,
    _parse_backend_response,
    _parse_structured_response,
    _should_retry,
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
    timeout_ms: int | None = None,
) -> AgentSpec:
    return AgentSpec(name=name, model=model, skill_bindings=["test-skill"], timeout_ms=timeout_ms)


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

    # ---------------------------------------------------------------
    # Tool-use / response-contract violation detection
    # ---------------------------------------------------------------

    def test_tool_call_markup_rejected(self) -> None:
        """Prose + <tool_call> blocks → disallowed_tool_use_response, not artifacts_dict_empty."""
        result_text = (
            "I'll use the Glob tool to find the relevant files.\n\n"
            "<tool_call>\n"
            '{"name": "Glob", "arguments": {"pattern": "**/*.json"}}\n'
            "</tool_call>\n\n"
            "<tool_call>\n"
            '{"name": "Grep", "arguments": {"pattern": "series_registry"}}\n'
            "</tool_call>"
        )
        raw = _make_cli_envelope(result_text)
        result = _parse_backend_response(raw, ["claim_classification_map"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "disallowed_tool_use_response" in result.failure
        assert "tool-call markup" in result.failure
        assert result.result_preview != ""

    def test_invoke_markup_rejected(self) -> None:
        """<invoke> style markup is also caught."""
        result_text = (
            "Let me read the file.\n\n"
            "<function_calls>\n"
            '<invoke name="Read">\n'
            '<parameter name="file_path">README.md</parameter>\n'
            "</invoke>\n"
            "</function_calls>"
        )
        raw = _make_cli_envelope(result_text)
        result = _parse_backend_response(raw, ["analysis"])
        assert result.artifacts == {}
        assert "disallowed_tool_use_response" in result.failure

    def test_extracted_tool_call_payload_rejected(self) -> None:
        """First JSON object has name+arguments but no markup tags → still rejected."""
        result_text = (
            "Based on my analysis, I need to check the registry.\n\n"
            '{"name": "Glob", "arguments": {"pattern": "*.json"}}'
        )
        raw = _make_cli_envelope(result_text)
        result = _parse_backend_response(raw, ["claim_classification_map"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "disallowed_tool_use_response" in result.failure
        assert "tool-call payload" in result.failure

    def test_direct_parsed_tool_call_payload_rejected(self) -> None:
        """Result text that IS a tool-call JSON object (no prose) → rejected."""
        result_text = json.dumps({"name": "Glob", "arguments": {"pattern": "*.json"}})
        raw = _make_cli_envelope(result_text)
        result = _parse_backend_response(raw, ["out"])
        assert result.artifacts == {}
        assert "disallowed_tool_use_response" in result.failure

    def test_prose_with_artifact_json_still_works(self) -> None:
        """Prose mentioning tools (not in markup) + valid artifact JSON → succeeds."""
        inner_json = json.dumps({
            "artifacts": {
                "result": {"produced_by": "step-1", "data": {"ok": True}},
            },
        })
        prose = (
            "I wanted to use Glob but tools are disabled. "
            "Here is my analysis:\n\n" + inner_json
        )
        raw = _make_cli_envelope(prose)
        result = _parse_backend_response(raw, ["result"])
        assert result.failure is None
        assert "result" in result.artifacts

    def test_tool_call_payload_with_artifacts_key_not_rejected(self) -> None:
        """Object with name+arguments AND artifacts key is NOT a tool-call."""
        result_text = json.dumps({
            "name": "meta",
            "arguments": {},
            "artifacts": {"out": {"produced_by": "s", "data": {}}},
        })
        raw = _make_cli_envelope(result_text)
        result = _parse_backend_response(raw, ["out"])
        assert result.failure is None
        assert "out" in result.artifacts

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


# ---------------------------------------------------------------------------
# Phase 2: Bare isolation mode
# ---------------------------------------------------------------------------

class TestBareIsolationMode:
    """Verify --bare flag in command when isolation_mode='bare'."""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_bare_flag_in_command(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(isolation_mode="bare")
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        cmd = mock_run.call_args[0][0]
        assert "--bare" in cmd

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_bare_does_not_change_cwd(self, mock_run: mock.MagicMock) -> None:
        """Bare mode must NOT set subprocess cwd (inherits process cwd)."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(isolation_mode="bare")
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        # cwd kwarg should be None (not set to temp dir)
        assert mock_run.call_args[1].get("cwd") is None

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_no_bare_in_project_mode(self, mock_run: mock.MagicMock) -> None:
        """Project mode must NOT include --bare."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(isolation_mode="project")
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        cmd = mock_run.call_args[0][0]
        assert "--bare" not in cmd

    def test_parser_accepts_bare_isolation(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["--backend-isolation", "bare"])
        assert args.backend_isolation == "bare"


# ---------------------------------------------------------------------------
# Phase 3: Per-step timeout configuration
# ---------------------------------------------------------------------------

class TestPerStepTimeout:
    """Agent-level timeout_ms overrides backend default."""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_agent_timeout_overrides_default(self, mock_run: mock.MagicMock) -> None:
        """Agent with timeout_ms=180000 -> subprocess called with timeout=180.0."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(timeout_ms=120_000)
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(timeout_ms=180_000),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        # subprocess.run should have been called with timeout=180.0
        assert mock_run.call_args[1]["timeout"] == 180.0

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_default_timeout_when_agent_has_none(self, mock_run: mock.MagicMock) -> None:
        """Agent with timeout_ms=None -> uses backend default."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(timeout_ms=120_000)
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(timeout_ms=None),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert mock_run.call_args[1]["timeout"] == 120.0

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_timeout_in_failure_detail(self, mock_run: mock.MagicMock) -> None:
        """Timeout failure message includes the effective timeout used."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=180)
        backend = ClaudeCodeCLIBackend(timeout_ms=120_000)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(timeout_ms=180_000),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is False
        assert result.failure is not None
        assert result.failure.origin == "timeout"
        assert "180000" in result.failure.detail


# ---------------------------------------------------------------------------
# Phase 4: Retry logic
# ---------------------------------------------------------------------------

class TestShouldRetry:
    """Unit tests for _should_retry() decision function."""

    def test_no_retry_on_success(self) -> None:
        parse = ParseResult(artifacts={"out": {"data": {}}}, failure=None)
        assert _should_retry(parse, attempt=0, max_retries=1) is False

    def test_retry_on_empty_result(self) -> None:
        parse = ParseResult(
            artifacts={},
            failure="result_field_empty_or_missing: type=str",
        )
        assert _should_retry(parse, attempt=0, max_retries=1) is True

    def test_no_retry_when_exhausted(self) -> None:
        parse = ParseResult(
            artifacts={},
            failure="result_field_empty_or_missing: type=str",
        )
        assert _should_retry(parse, attempt=1, max_retries=1) is False

    def test_no_retry_on_tool_use(self) -> None:
        parse = ParseResult(
            artifacts={},
            failure="disallowed_tool_use_response: tool-call markup",
        )
        assert _should_retry(parse, attempt=0, max_retries=1) is False

    def test_no_retry_on_cli_error(self) -> None:
        parse = ParseResult(
            artifacts={},
            failure="cli_is_error_flag: envelope.is_error=true",
        )
        assert _should_retry(parse, attempt=0, max_retries=1) is False

    def test_no_retry_on_parse_failure_with_content(self) -> None:
        parse = ParseResult(
            artifacts={},
            failure="inner_result_no_json_object: direct parse failed",
        )
        assert _should_retry(parse, attempt=0, max_retries=1) is False


class TestRetryLoop:
    """Integration tests for the retry loop in execute_step()."""

    @mock.patch("governance.dag_runner.execution_backend.time.sleep")
    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_retry_on_timeout_then_success(
        self, mock_run: mock.MagicMock, mock_sleep: mock.MagicMock,
    ) -> None:
        """TimeoutExpired once, succeeds on retry -> PASS with retry_count=1."""
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd="claude", timeout=120),
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
                stderr="",
            ),
        ]
        backend = ClaudeCodeCLIBackend(max_retries=1)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is True
        assert result.retry_count == 1
        assert "test_artifact" in result.artifacts_produced
        mock_sleep.assert_called_once_with(2)

    @mock.patch("governance.dag_runner.execution_backend.time.sleep")
    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_all_retries_exhausted(
        self, mock_run: mock.MagicMock, mock_sleep: mock.MagicMock,
    ) -> None:
        """All attempts timeout -> FAIL with retry_count=max."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)
        backend = ClaudeCodeCLIBackend(max_retries=2)
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
        assert result.retry_count == 2
        # Sleep called between each retry
        assert mock_sleep.call_count == 2

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_no_retry_on_os_error(self, mock_run: mock.MagicMock) -> None:
        """OSError -> immediate FAIL, retry_count=0."""
        mock_run.side_effect = OSError("No such file or directory")
        backend = ClaudeCodeCLIBackend(max_retries=2)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is False
        assert result.retry_count == 0
        assert mock_run.call_count == 1

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_no_retry_on_parse_failure(self, mock_run: mock.MagicMock) -> None:
        """Parse failure with non-empty result -> immediate FAIL, retry_count=0."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_cli_envelope("I am plain text, not JSON"),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(max_retries=2)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is True  # subprocess succeeded
        assert result.parse_failure is not None
        assert result.retry_count == 0
        assert mock_run.call_count == 1  # no retry

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_successful_run_has_zero_retries(self, mock_run: mock.MagicMock) -> None:
        """Stable run -> retry_count=0."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(max_retries=1)
        result = backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        assert result.success is True
        assert result.retry_count == 0

    def test_parser_accepts_max_retries(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["--max-retries", "3"])
        assert args.max_retries == 3

    def test_parser_default_max_retries(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.max_retries == 1


# ---------------------------------------------------------------------------
# Phase 5: Cleanup — fallback tracking, prompt simplification
# ---------------------------------------------------------------------------

class TestFallbackTracking:
    """ParseResult.fallback_used tracks which fallback path was activated."""

    def test_direct_parse_no_fallback(self) -> None:
        raw = _make_artifact_response({
            "test_artifact": {"produced_by": "test-step", "data": {}},
        })
        result = _parse_backend_response(raw, ["test_artifact"])
        assert result.failure is None
        assert result.fallback_used is None

    def test_code_fence_stripped(self) -> None:
        inner_json = json.dumps({
            "artifacts": {"out": {"produced_by": "s", "data": {}}},
        })
        result_text = f"```json\n{inner_json}\n```"
        raw = _make_cli_envelope(result_text)
        result = _parse_backend_response(raw, ["out"])
        assert result.failure is None
        assert result.fallback_used == "code_fence_stripped"

    def test_brace_extraction(self) -> None:
        inner_json = json.dumps({
            "artifacts": {"out": {"produced_by": "s", "data": {}}},
        })
        result_text = "Based on my analysis:\n\n" + inner_json
        raw = _make_cli_envelope(result_text)
        result = _parse_backend_response(raw, ["out"])
        assert result.failure is None
        assert result.fallback_used == "brace_extraction"


class TestPromptFormatSimplification:
    """build_prompt_text respects use_structured_output for format section."""

    def test_verbose_format_when_structured_output_off(self) -> None:
        from governance.dag_runner.prompt_assembly import build_prompt_text
        ctx = {
            "skill_content": "test skill",
            "agent_instructions": "",
            "artifact_inputs": {},
            "document_paths": [],
            "expected_outputs": ["claim_classification_map"],
            "step_name": "classify-claims",
            "use_structured_output": False,
        }
        text = build_prompt_text(ctx)
        assert "Do NOT wrap in markdown code fences" in text
        assert "Do NOT include any text, explanation" in text

    def test_minimal_format_when_structured_output_on(self) -> None:
        from governance.dag_runner.prompt_assembly import build_prompt_text
        ctx = {
            "skill_content": "test skill",
            "agent_instructions": "",
            "artifact_inputs": {},
            "document_paths": [],
            "expected_outputs": ["claim_classification_map"],
            "step_name": "classify-claims",
            "use_structured_output": True,
        }
        text = build_prompt_text(ctx)
        assert "Do NOT wrap in markdown code fences" not in text
        assert "Respond with a JSON object" in text
        assert "claim_classification_map" in text


# ---------------------------------------------------------------------------
# Phase 1: JSON schema generation
# ---------------------------------------------------------------------------

class TestJsonSchemaGeneration:
    """Unit tests for _build_artifact_json_schema()."""

    def test_schema_single_output(self) -> None:
        schema_str = _build_artifact_json_schema(["claim_classification_map"], "classify-claims")
        schema = json.loads(schema_str)
        props = schema["properties"]["artifacts"]["properties"]
        assert "claim_classification_map" in props
        assert props["claim_classification_map"]["type"] == "object"

    def test_schema_multiple_outputs(self) -> None:
        schema_str = _build_artifact_json_schema(
            ["change_impact_report", "doc_update_plan"], "change-impact",
        )
        schema = json.loads(schema_str)
        props = schema["properties"]["artifacts"]["properties"]
        assert "change_impact_report" in props
        assert "doc_update_plan" in props
        required = schema["properties"]["artifacts"]["required"]
        assert "change_impact_report" in required
        assert "doc_update_plan" in required

    def test_schema_requires_artifacts_key(self) -> None:
        schema_str = _build_artifact_json_schema(["out"], "step")
        schema = json.loads(schema_str)
        assert "artifacts" in schema["required"]

    def test_schema_valid_json(self) -> None:
        schema_str = _build_artifact_json_schema(["a", "b", "c"], "step")
        parsed = json.loads(schema_str)
        assert isinstance(parsed, dict)
        assert parsed["type"] == "object"


# ---------------------------------------------------------------------------
# Phase 1: Command construction with structured output
# ---------------------------------------------------------------------------

class TestCommandWithStructuredOutput:
    """Verify --json-schema appears in cmd when use_structured_output=True."""

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_json_schema_in_command_when_enabled(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(use_structured_output=True)
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        cmd = mock_run.call_args[0][0]
        assert "--json-schema" in cmd
        # The schema string follows --json-schema
        idx = cmd.index("--json-schema")
        schema_str = cmd[idx + 1]
        schema = json.loads(schema_str)
        assert "artifacts" in schema["required"]
        assert "test_artifact" in schema["properties"]["artifacts"]["properties"]

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_no_json_schema_when_disabled(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_artifact_response({"test_artifact": {"produced_by": "test-step"}}),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(use_structured_output=False)
        backend.execute_step(
            step=_make_step(),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        cmd = mock_run.call_args[0][0]
        assert "--json-schema" not in cmd

    @mock.patch("governance.dag_runner.execution_backend.subprocess.run")
    def test_no_json_schema_for_structural_steps(self, mock_run: mock.MagicMock) -> None:
        """Steps with no declared outputs skip --json-schema even when flag is on."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_make_cli_envelope("{}"),
            stderr="",
        )
        backend = ClaudeCodeCLIBackend(use_structured_output=True)
        backend.execute_step(
            step=_make_step(outputs=[]),
            agent=_make_agent(),
            config=ExecutionConfig(),
            run_state=_make_run_state(),
            spec=_make_spec(),
            prompt_context=_make_prompt_context(),
        )
        cmd = mock_run.call_args[0][0]
        assert "--json-schema" not in cmd


# ---------------------------------------------------------------------------
# Phase 1: _parse_structured_response
# ---------------------------------------------------------------------------

def _make_structured_envelope(
    structured_output: dict | None = None,
    result_text: str = "",
    is_error: bool = False,
    output_tokens: int = 42,
) -> str:
    """Build a Claude CLI envelope with structured_output field."""
    env: dict = {
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
    }
    if structured_output is not None:
        env["structured_output"] = structured_output
    return json.dumps(env)


class TestParseStructuredResponse:
    """Unit tests for _parse_structured_response()."""

    def test_extracts_from_structured_output(self) -> None:
        raw = _make_structured_envelope(
            structured_output={
                "artifacts": {
                    "claim_classification_map": {
                        "produced_by": "classify-claims",
                        "data": {"ok": True},
                    },
                },
            },
        )
        result = _parse_structured_response(raw, ["claim_classification_map"])
        assert result.failure is None
        assert "claim_classification_map" in result.artifacts
        assert result.artifacts["claim_classification_map"]["data"]["ok"] is True

    def test_falls_back_to_legacy_when_no_structured_output(self) -> None:
        """Without structured_output field, falls back to _parse_backend_response."""
        raw = _make_artifact_response({
            "test_artifact": {"produced_by": "test-step", "data": {}},
        })
        result = _parse_structured_response(raw, ["test_artifact"])
        assert result.failure is None
        assert "test_artifact" in result.artifacts

    def test_empty_structured_artifacts(self) -> None:
        raw = _make_structured_envelope(structured_output={"artifacts": {}})
        result = _parse_structured_response(raw, ["out"])
        assert result.artifacts == {}
        assert result.failure is not None
        assert "structured_artifacts_empty" in result.failure

    def test_structured_output_not_dict(self) -> None:
        raw = _make_structured_envelope(structured_output="not a dict")
        result = _parse_structured_response(raw, ["out"])
        assert result.artifacts == {}
        assert "structured_output_not_dict" in result.failure

    def test_cli_is_error_with_structured_output(self) -> None:
        raw = _make_structured_envelope(
            structured_output={"artifacts": {"out": {"data": {}}}},
            is_error=True,
        )
        result = _parse_structured_response(raw, ["out"])
        assert result.artifacts == {}
        assert "cli_is_error_flag" in result.failure

    def test_wrong_artifact_names_detected(self) -> None:
        raw = _make_structured_envelope(
            structured_output={
                "artifacts": {"wrong_name": {"produced_by": "s", "data": {}}},
            },
        )
        result = _parse_structured_response(raw, ["expected_name"])
        assert "wrong_name" in result.artifacts
        assert result.failure is not None
        assert "wrong_artifact_names" in result.failure

    def test_multiple_artifacts(self) -> None:
        raw = _make_structured_envelope(
            structured_output={
                "artifacts": {
                    "a": {"produced_by": "s", "data": {}},
                    "b": {"produced_by": "s", "data": {}},
                },
            },
        )
        result = _parse_structured_response(raw, ["a", "b"])
        assert result.failure is None
        assert len(result.artifacts) == 2


# ---------------------------------------------------------------------------
# Phase 1: CLI --use-structured-output flag
# ---------------------------------------------------------------------------

class TestCLIStructuredOutputFlag:
    """CLI argument parsing for --use-structured-output."""

    def test_parser_accepts_use_structured_output(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["--use-structured-output"])
        assert args.use_structured_output is True

    def test_parser_default_structured_output_is_false(self) -> None:
        from governance.dag_runner.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.use_structured_output is False
