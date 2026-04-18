"""
execution_backend.py — Pluggable execution backend interface.

The executor depends on this interface, not on Claude directly.
V2A ships with MockExecutionBackend only.
V2B adds ClaudeCodeCLIBackend.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from governance.dag_runner.models import (
    AgentExecutionResult,
    AgentSpec,
    AssembledWorkflowSpec,
    ExecutionConfig,
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
