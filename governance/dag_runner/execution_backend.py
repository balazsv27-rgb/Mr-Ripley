"""
execution_backend.py — Pluggable execution backend interface.

The executor depends on this interface, not on Claude directly.
V2A ships with MockExecutionBackend only.
V2B adds ClaudeCodeCLIBackend (one-shot local CLI subprocess).
"""
from __future__ import annotations

import json
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Any

from governance.dag_runner.models import (
    AgentExecutionResult,
    AgentSpec,
    AssembledWorkflowSpec,
    ExecutionConfig,
    FailureClassification,
    GovernanceRunState,
    PromptContext,
    WorkflowStep,
)


class ExecutionBackend(ABC):
    """Interface for step execution.

    The executor dispatches to this interface for all skill-bound and
    coordinator-agent steps.  Structural steps (constitution, stage_gates,
    hooks) are handled deterministically by the executor itself, but may
    optionally delegate to ``execute_structural_step`` for consistency.
    """

    @abstractmethod
    def execute_step(
        self,
        step: WorkflowStep,
        agent: AgentSpec,
        config: ExecutionConfig,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
        prompt_context: PromptContext | None = None,
    ) -> AgentExecutionResult:
        """Execute a skill-bound or coordinator-agent step."""

    @abstractmethod
    def execute_structural_step(
        self,
        step: WorkflowStep,
        component_kind: str,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
    ) -> AgentExecutionResult:
        """Execute a structural step (no LLM) deterministically."""


class MockExecutionBackend(ExecutionBackend):
    """V2A default — produces deterministic artifact payloads without Claude.

    Accepts an optional ``artifact_payloads`` dict mapping artifact names
    to their ``data`` dicts.  When a step produces an artifact whose name
    appears in the map, the corresponding data is used.  Otherwise a
    minimal placeholder is produced.
    """

    def __init__(
        self,
        artifact_payloads: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._payloads: dict[str, dict[str, Any]] = artifact_payloads or {}

    def execute_step(
        self,
        step: WorkflowStep,
        agent: AgentSpec,
        config: ExecutionConfig,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
        prompt_context: PromptContext | None = None,
    ) -> AgentExecutionResult:
        artifacts: dict[str, dict[str, Any]] = {}
        for output_name in step.outputs:
            artifacts[output_name] = self._payloads.get(
                output_name,
                {"produced_by": step.name},
            )
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)

    def execute_structural_step(
        self,
        step: WorkflowStep,
        component_kind: str,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
    ) -> AgentExecutionResult:
        artifacts: dict[str, dict[str, Any]] = {}
        for output_name in step.outputs:
            artifacts[output_name] = self._payloads.get(
                output_name,
                {"produced_by": step.name, "structural": True},
            )
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)


def _parse_backend_response(
    raw_output: str,
    expected_artifacts: list[str],
) -> dict[str, dict[str, Any]]:
    """Extract artifact payloads from Claude CLI JSON response.

    The CLI returns a JSON envelope with a ``result`` field containing the
    LLM's response text.  That text must itself be a JSON object with an
    ``artifacts`` key mapping artifact names to their payloads.

    Returns a dict of artifact name → payload.  On any parse failure returns
    an empty dict (fail-closed: the step will fail artifact validation).
    """
    try:
        envelope = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError):
        return {}

    if not isinstance(envelope, dict):
        return {}

    # Check for CLI-level error
    if envelope.get("is_error", False):
        return {}

    result_text = envelope.get("result", "")
    if not isinstance(result_text, str) or not result_text.strip():
        return {}

    try:
        result_obj = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        return {}

    if not isinstance(result_obj, dict):
        return {}

    artifacts_dict = result_obj.get("artifacts", {})
    if not isinstance(artifacts_dict, dict):
        return {}

    return {
        name: payload
        for name, payload in artifacts_dict.items()
        if isinstance(payload, dict)
    }


class ClaudeCodeCLIBackend(ExecutionBackend):
    """V2B live backend — dispatches to local claude CLI subprocess.

    Uses ``claude -p`` (one-shot print mode) with assembled prompt on stdin.
    No direct API calls, no external billing, no repository-managed API
    dependency (uses local Claude Code runtime).
    """

    def __init__(
        self,
        model: str = "sonnet",
        timeout_ms: int = 120_000,
        claude_command: str = "claude",
    ) -> None:
        self._default_model = model
        self._timeout_ms = timeout_ms
        self._claude_command = claude_command

    def execute_step(
        self,
        step: WorkflowStep,
        agent: AgentSpec,
        config: ExecutionConfig,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
        prompt_context: PromptContext | None = None,
    ) -> AgentExecutionResult:
        # Fail closed when no prompt context is provided
        if prompt_context is None:
            return AgentExecutionResult(
                success=False,
                failure=FailureClassification(
                    origin="runtime",
                    step_id=step.name,
                    detail="prompt_context is None — cannot dispatch to CLI backend without assembled prompt.",
                ),
            )

        # Select model: prefer agent-level override, fall back to constructor default
        model = agent.model if agent.model else self._default_model

        cmd = [
            self._claude_command,
            "-p",
            "--output-format", "json",
            "--model", model,
            "--no-session-persistence",
            "--tools", "",
        ]

        timeout_s = self._timeout_ms / 1000.0
        t0 = time.monotonic()

        try:
            proc = subprocess.run(
                cmd,
                input=prompt_context.assembled_prompt,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            latency = (time.monotonic() - t0) * 1000.0
            return AgentExecutionResult(
                success=False,
                latency_ms=latency,
                failure=FailureClassification(
                    origin="timeout",
                    step_id=step.name,
                    detail=f"Claude CLI subprocess timed out after {self._timeout_ms}ms.",
                ),
            )
        except OSError as exc:
            latency = (time.monotonic() - t0) * 1000.0
            return AgentExecutionResult(
                success=False,
                latency_ms=latency,
                failure=FailureClassification(
                    origin="runtime",
                    step_id=step.name,
                    detail=f"Failed to spawn Claude CLI subprocess: {exc}",
                ),
            )

        latency = (time.monotonic() - t0) * 1000.0
        raw_output = proc.stdout or ""

        # Non-zero exit code → runtime failure
        if proc.returncode != 0:
            return AgentExecutionResult(
                success=False,
                raw_output=raw_output,
                latency_ms=latency,
                failure=FailureClassification(
                    origin="runtime",
                    step_id=step.name,
                    detail=f"Claude CLI exited with code {proc.returncode}.",
                ),
            )

        # Parse response and extract artifacts
        artifacts = _parse_backend_response(raw_output, list(step.outputs))

        # Extract token count from envelope if available
        token_count = 0
        try:
            envelope = json.loads(raw_output)
            usage = envelope.get("usage", {})
            token_count = usage.get("output_tokens", 0)
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

        return AgentExecutionResult(
            success=True,
            artifacts_produced=artifacts,
            raw_output=raw_output,
            latency_ms=latency,
            token_count=token_count,
        )

    def execute_structural_step(
        self,
        step: WorkflowStep,
        component_kind: str,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
    ) -> AgentExecutionResult:
        """Structural steps are deterministic — no LLM needed even in live mode."""
        artifacts: dict[str, dict[str, Any]] = {}
        for output_name in step.outputs:
            artifacts[output_name] = {"produced_by": step.name, "structural": True}
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)
