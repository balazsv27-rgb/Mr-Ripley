"""Integration tests: real ClaudeCodeCLIBackend → parser → executor → failure_detail.

Every other failure-diagnostics test uses MockExecutionBackend subclasses that
hand-craft AgentExecutionResult and never call _parse_backend_response().
These tests exercise the REAL chain:

    subprocess.run (mocked) → ClaudeCodeCLIBackend.execute_step()
        → _parse_backend_response()
        → AgentExecutionResult
        → executor._execute_v2_step()
        → NodeResult.failure_detail + debug artifact file

Mock strategy:
    YES: subprocess.run, assemble_step_prompt, default_governance_policy
    NO:  _parse_backend_response, validate_artifact_output,
         write_failure_debug_artifact, executor logic
"""
from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from governance.dag_runner.execution_backend import ClaudeCodeCLIBackend
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.models import (
    AgentSpec,
    AssembledWorkflowSpec,
    ExecutionConfig,
    ManifestSpec,
    PromptContext,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan, PlannedNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STEP_NAME = "classify-claims"
_ARTIFACT_NAME = "claim_classification_map"


def _make_cli_envelope(
    result_text: str,
    *,
    is_error: bool = False,
    output_tokens: int = 150,
) -> str:
    """Build a realistic Claude CLI JSON envelope."""
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result_text,
        "duration_ms": 12000,
        "duration_api_ms": 11000,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "session_id": "test-session-id",
        "total_cost_usd": 0.05,
        "usage": {
            "input_tokens": 45000,
            "output_tokens": output_tokens,
        },
    })


def _make_step() -> WorkflowStep:
    return WorkflowStep(
        name=_STEP_NAME,
        component=f"skill:{_STEP_NAME}",
        outputs=[_ARTIFACT_NAME],
        raw={"agent_binding": _STEP_NAME},
    )


def _make_spec(step: WorkflowStep) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test-integration", workflow_version="1.0"),
        workflow_steps={step.name: step},
        agents={_STEP_NAME: AgentSpec(name=_STEP_NAME, model="sonnet")},
    )


def _make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        workflow_name="test-integration",
        ordered_steps=[
            PlannedNode(step_id=_STEP_NAME, component=f"skill:{_STEP_NAME}"),
        ],
    )


def _default_config() -> ExecutionConfig:
    return ExecutionConfig(mode="agent_execution", request_text="test input")


def _mock_subprocess(stdout: str, stderr: str = "") -> mock.MagicMock:
    """Create a mock for subprocess.run returning a CompletedProcess."""
    m = mock.MagicMock()
    m.return_value = subprocess.CompletedProcess(
        args=["claude", "-p"], returncode=0,
        stdout=stdout, stderr=stderr,
    )
    return m


@contextmanager
def _patched_prompt_and_policy():
    """Patch prompt assembly and path policy to bypass filesystem I/O."""
    # assemble_step_prompt is imported inside _execute_v2_step —
    # patch at the prompt_assembly module level.
    minimal_ctx: dict[str, Any] = {
        "skill_content": "You are a test skill. Return artifacts as JSON.",
        "agent_instructions": "",
        "artifact_inputs": {},
        "document_paths": [],
        "token_budget": 100_000,
        "token_estimate": 500,
        "truncated": False,
        "truncation_events": [],
    }
    with (
        mock.patch(
            "governance.dag_runner.prompt_assembly.assemble_step_prompt",
            return_value=minimal_ctx,
        ),
        mock.patch(
            "governance.dag_runner.path_policy.default_governance_policy",
            return_value=None,
        ),
    ):
        yield


def _run_step(subprocess_stdout: str, subprocess_stderr: str = "") -> Any:
    """Run a single classify-claims step through the full real chain.

    Returns the ExecutionResult from execute_plan().
    """
    step = _make_step()
    spec = _make_spec(step)
    plan = _make_plan()
    config = _default_config()
    backend = ClaudeCodeCLIBackend(timeout_ms=60_000)

    with (
        mock.patch(
            "governance.dag_runner.execution_backend.subprocess.run",
            _mock_subprocess(subprocess_stdout, subprocess_stderr),
        ),
        _patched_prompt_and_policy(),
    ):
        return execute_plan(
            spec, plan,
            verdict_status="ready",
            config=config,
            backend=backend,
        )


# ---------------------------------------------------------------------------
# Scenario 1: Tool-call response (the classify-claims regression)
# ---------------------------------------------------------------------------

_TOOL_CALL_RESULT = (
    "I'll analyze this request by reading the relevant files.\n\n"
    "<tool_call>\n"
    '{"name": "Glob", "arguments": {"pattern": "**/*.json"}}\n'
    "</tool_call>\n\n"
    "<tool_call>\n"
    '{"name": "Grep", "arguments": {"pattern": "series_registry"}}\n'
    "</tool_call>"
)


class TestToolCallResponse:
    """Model returned prose + <tool_call> blocks instead of artifact JSON."""

    def test_step_fails_with_backend_parse(self) -> None:
        envelope = _make_cli_envelope(_TOOL_CALL_RESULT)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.status == "FAIL"
        fd = nr.failure_detail
        assert fd["failure_stage"] == "backend_parse"
        assert "disallowed_tool_use_response" in fd["parse_failure_reason"]

    def test_raw_output_preview_contains_inner_text(self) -> None:
        envelope = _make_cli_envelope(_TOOL_CALL_RESULT)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        fd = nr.failure_detail
        assert fd["raw_output_preview"] != ""
        # The preview must be from the inner result text, not the outer envelope
        assert "tool_call" in fd["raw_output_preview"].lower()

    def test_debug_artifact_has_readable_inner_result(self) -> None:
        envelope = _make_cli_envelope(_TOOL_CALL_RESULT)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        fd = nr.failure_detail
        assert fd["debug_artifact_written"] is True
        assert fd["debug_artifact_path"] is not None

        debug_path = Path(fd["debug_artifact_path"])
        assert debug_path.exists()
        content = json.loads(debug_path.read_text(encoding="utf-8"))

        # The debug file must contain the inner result text — readable,
        # not buried inside escaped outer-envelope JSON.
        assert "result_text_first_2000" in content
        assert "<tool_call>" in content["result_text_first_2000"]
        assert "Glob" in content["result_text_first_2000"]

        # Envelope metadata must be present
        assert content["envelope_type"] == "result"
        assert content["envelope_is_error"] is False
        assert content["usage"]["output_tokens"] == 150


# ---------------------------------------------------------------------------
# Scenario 2: Empty-artifacts response
# ---------------------------------------------------------------------------


class TestEmptyArtifactsResponse:
    """Model returned valid JSON with an empty artifacts dict."""

    def test_step_fails_with_backend_parse(self) -> None:
        result_text = json.dumps({"artifacts": {}})
        envelope = _make_cli_envelope(result_text)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.status == "FAIL"
        fd = nr.failure_detail
        assert fd["failure_stage"] == "backend_parse"
        assert "artifacts_dict_empty" in fd["parse_failure_reason"]

    def test_raw_output_preview_populated(self) -> None:
        result_text = json.dumps({"artifacts": {}})
        envelope = _make_cli_envelope(result_text)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.failure_detail["raw_output_preview"] != ""


# ---------------------------------------------------------------------------
# Scenario 3: Successful response (regression guard)
# ---------------------------------------------------------------------------


class TestSuccessfulResponse:
    """Model returned correct artifact JSON — must PASS end-to-end."""

    def test_step_passes_with_correct_artifacts(self) -> None:
        result_text = json.dumps({
            "artifacts": {
                _ARTIFACT_NAME: {
                    "produced_by": _STEP_NAME,
                    "data": {
                        "classifications": [
                            {"claim": "Layer 2 is operational", "type": "current-state"},
                        ],
                    },
                },
            },
        })
        envelope = _make_cli_envelope(result_text)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.status == "PASS"
        assert _ARTIFACT_NAME in nr.produced_artifacts
        assert nr.failure_detail == {}

    def test_artifact_recorded_in_run_state(self) -> None:
        result_text = json.dumps({
            "artifacts": {
                _ARTIFACT_NAME: {
                    "produced_by": _STEP_NAME,
                    "data": {"ok": True},
                },
            },
        })
        envelope = _make_cli_envelope(result_text)
        result = _run_step(envelope)

        art = result.run_state.artifacts.get(_ARTIFACT_NAME)
        assert art is not None
        assert art.status == "present"
        assert art.payload["data"]["ok"] is True


# ---------------------------------------------------------------------------
# Scenario 4: Schema validation failure (strict mode, real backend only)
# ---------------------------------------------------------------------------


class TestSchemaValidationStrict:
    """Strict artifact validation catches produced_by mismatch.

    This only fires for non-MockExecutionBackend — exactly the gap that
    mock-only tests miss.
    """

    def test_produced_by_mismatch_fails_step(self) -> None:
        result_text = json.dumps({
            "artifacts": {
                _ARTIFACT_NAME: {
                    "produced_by": "wrong-step-name",
                    "data": {"verdict": "PASS"},
                },
            },
        })
        envelope = _make_cli_envelope(result_text)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.status == "FAIL"
        fd = nr.failure_detail
        assert fd["failure_stage"] == "schema_validation"
        assert fd["violation_count"] >= 1

    def test_missing_produced_by_fails_step(self) -> None:
        result_text = json.dumps({
            "artifacts": {
                _ARTIFACT_NAME: {
                    "data": {"verdict": "PASS"},
                },
            },
        })
        envelope = _make_cli_envelope(result_text)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.status == "FAIL"
        fd = nr.failure_detail
        assert fd["failure_stage"] == "schema_validation"


# ---------------------------------------------------------------------------
# Scenario 5: Prose-prefixed valid artifact JSON
# ---------------------------------------------------------------------------


class TestProsePrefixedResponse:
    """Model returned prose explanation followed by valid artifact JSON."""

    def test_step_passes_with_prose_prefix(self) -> None:
        inner_json = json.dumps({
            "artifacts": {
                _ARTIFACT_NAME: {
                    "produced_by": _STEP_NAME,
                    "data": {
                        "classifications": [
                            {"claim": "test", "type": "current-state"},
                        ],
                    },
                },
            },
        })
        prose = (
            "Based on my analysis of the upstream artifacts and the "
            "governance context, here is my classification:\n\n"
        )
        result_text = prose + inner_json
        envelope = _make_cli_envelope(result_text)
        result = _run_step(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.status == "PASS"
        assert _ARTIFACT_NAME in nr.produced_artifacts
        assert nr.failure_detail == {}


# ---------------------------------------------------------------------------
# Phase 1: Structured output integration tests
# ---------------------------------------------------------------------------


def _make_structured_envelope(
    structured_output: dict | None = None,
    result_text: str = "",
    *,
    is_error: bool = False,
    output_tokens: int = 150,
) -> str:
    """Build a Claude CLI envelope with structured_output field."""
    env: dict = {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result_text,
        "duration_ms": 12000,
        "duration_api_ms": 11000,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "session_id": "test-session-id",
        "total_cost_usd": 0.05,
        "usage": {
            "input_tokens": 45000,
            "output_tokens": output_tokens,
        },
    }
    if structured_output is not None:
        env["structured_output"] = structured_output
    return json.dumps(env)


def _run_step_structured(subprocess_stdout: str, subprocess_stderr: str = "") -> Any:
    """Run a single step with use_structured_output=True through the full chain."""
    step = _make_step()
    spec = _make_spec(step)
    plan = _make_plan()
    config = _default_config()
    backend = ClaudeCodeCLIBackend(timeout_ms=60_000, use_structured_output=True)

    with (
        mock.patch(
            "governance.dag_runner.execution_backend.subprocess.run",
            _mock_subprocess(subprocess_stdout, subprocess_stderr),
        ),
        _patched_prompt_and_policy(),
    ):
        return execute_plan(
            spec, plan,
            verdict_status="ready",
            config=config,
            backend=backend,
        )


class TestStructuredOutputIntegration:
    """End-to-end tests for --json-schema / structured_output path."""

    def test_schema_constrained_result_parses_correctly(self) -> None:
        """Envelope with structured_output -> artifacts extracted -> PASS."""
        envelope = _make_structured_envelope(
            structured_output={
                "artifacts": {
                    _ARTIFACT_NAME: {
                        "produced_by": _STEP_NAME,
                        "data": {
                            "classifications": [
                                {"claim": "Layer 2 is operational", "type": "current-state"},
                            ],
                        },
                    },
                },
            },
        )
        result = _run_step_structured(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.status == "PASS"
        assert _ARTIFACT_NAME in nr.produced_artifacts
        assert nr.failure_detail == {}

    def test_fallback_when_result_is_prose(self) -> None:
        """Without structured_output field, old prose+JSON fallback still works."""
        inner_json = json.dumps({
            "artifacts": {
                _ARTIFACT_NAME: {
                    "produced_by": _STEP_NAME,
                    "data": {"ok": True},
                },
            },
        })
        prose = "Based on my analysis:\n\n" + inner_json
        # No structured_output field -- just a regular envelope
        envelope = _make_cli_envelope(prose)
        result = _run_step_structured(envelope)
        nr = result.run_state.node_results[_STEP_NAME]

        assert nr.status == "PASS"
        assert _ARTIFACT_NAME in nr.produced_artifacts
