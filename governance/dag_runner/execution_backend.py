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
from dataclasses import dataclass, field
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
        debug_dir: "Path | None" = None,
    ) -> AgentExecutionResult:
        """Execute a skill-bound or coordinator-agent step."""

    @abstractmethod
    def execute_structural_step(
        self,
        step: WorkflowStep,
        component_kind: str,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
        bootstrap_payload: dict[str, dict[str, Any]] | None = None,
    ) -> AgentExecutionResult:
        """Execute a structural step (no LLM) deterministically.

        When *bootstrap_payload* is provided, it maps artifact names to
        their payload dicts.  The step uses these instead of generating
        default structural placeholders.
        """


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
        debug_dir: "Path | None" = None,
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
        bootstrap_payload: dict[str, dict[str, Any]] | None = None,
    ) -> AgentExecutionResult:
        artifacts: dict[str, dict[str, Any]] = {}
        for output_name in step.outputs:
            # Bootstrap payload takes priority, then configured payloads, then default
            if bootstrap_payload and output_name in bootstrap_payload:
                artifacts[output_name] = bootstrap_payload[output_name]
            else:
                artifacts[output_name] = self._payloads.get(
                    output_name,
                    {"produced_by": step.name, "structural": True},
                )
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response text.

    Claude CLI ``result`` text frequently wraps JSON in fences like:

        ```json
        {"artifacts": {...}}
        ```

    This function extracts the inner content.  If no fences are found,
    the original text is returned unchanged (stripped).
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    # Remove opening fence line (```json, ```JSON, or bare ```)
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return stripped
    inner = stripped[first_newline + 1:]

    # Remove closing fence
    if inner.rstrip().endswith("```"):
        inner = inner.rstrip()[:-3].rstrip()

    return inner


def _extract_first_json_object(text: str) -> str | None:
    """Locate and extract the first top-level JSON object from *text*.

    Handles the common LLM pattern of emitting explanatory prose before
    the actual JSON payload::

        Based on my analysis... I cannot read ctx.json directly...

        {"artifacts": {"claim_classification_map": {...}}}

    Uses brace-depth counting to find the matching ``}`` for the first
    ``{``.  Returns the substring from the first ``{`` to its matching
    ``}``, or ``None`` if no balanced object is found.

    This is a best-effort extraction — it does not handle braces inside
    JSON string values that contain unescaped braces, but those are rare
    in LLM artifact responses.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            if in_string:
                escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


@dataclass(frozen=True)
class ParseResult:
    """Structured result from response parsing.

    ``artifacts`` — extracted artifact payloads (may be empty on failure).
    ``failure`` — human-readable reason the parse failed (None on success).
    ``result_preview`` — truncated inner result text for diagnostics.
    """

    artifacts: dict[str, dict[str, Any]]
    failure: str | None = None
    result_preview: str = ""


_PREVIEW_MAX = 500

_LEGACY_DEBUG_DIR = ".claude/run/artifacts"


def _write_step_debug(
    *,
    step_name: str,
    returncode: int,
    stdout: str,
    stderr: str,
    parsed_artifact_keys: list[str],
    parse_failure: str | None,
    result_preview: str,
    usage: dict[str, Any] | None,
    debug_dir: str | None = None,
) -> None:
    """Persist raw subprocess output for a failed backend step.

    Writes ``<step_name>_debug.json`` to the debug directory so the
    exact response can be inspected without re-running the live backend.
    Best-effort: failures here are silently ignored (diagnostic, not critical).
    """
    import os
    from pathlib import Path

    target_dir = debug_dir or _LEGACY_DEBUG_DIR
    debug_path = Path(target_dir) / f"{step_name}_debug.json"
    try:
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "step_name": step_name,
            "returncode": returncode,
            "stdout_length": len(stdout),
            "stdout_first_1000": stdout[:1000],
            "stderr_length": len(stderr),
            "stderr_first_1000": stderr[:1000],
            "parsed_artifact_keys": parsed_artifact_keys,
            "parse_failure": parse_failure,
            "result_preview": result_preview,
            "usage": usage,
        }
        # Also extract the envelope structure without the full result text
        try:
            env = json.loads(stdout)
            if isinstance(env, dict):
                result_text = env.get("result", "")
                payload["envelope_keys"] = sorted(env.keys())
                payload["envelope_type"] = env.get("type")
                payload["envelope_is_error"] = env.get("is_error")
                payload["result_type"] = type(result_text).__name__
                payload["result_length"] = len(result_text) if isinstance(result_text, str) else None
                payload["result_first_1000"] = result_text[:1000] if isinstance(result_text, str) else str(result_text)[:1000]
        except (json.JSONDecodeError, TypeError):
            payload["envelope_parse_error"] = "stdout is not valid JSON"

        with debug_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass  # diagnostic-only — never block execution


def _parse_backend_response(
    raw_output: str,
    expected_artifacts: list[str],
) -> ParseResult:
    """Extract artifact payloads from Claude CLI JSON response.

    The CLI returns a JSON envelope with a ``result`` field containing the
    LLM's response text.  That text must itself be a JSON object with an
    ``artifacts`` key mapping artifact names to their payloads.

    The result text may be raw JSON or wrapped in markdown code fences
    (e.g. `` ```json ... ``` ``).  Both forms are accepted.

    Returns a ``ParseResult`` with extracted artifacts and, on failure,
    a structured reason string explaining where parsing failed.
    """
    try:
        envelope = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError) as exc:
        return ParseResult(
            artifacts={},
            failure=f"outer_envelope_invalid_json: {exc}",
        )

    if not isinstance(envelope, dict):
        return ParseResult(
            artifacts={},
            failure=f"outer_envelope_not_dict: got {type(envelope).__name__}",
        )

    # Check for CLI-level error
    if envelope.get("is_error", False):
        return ParseResult(
            artifacts={},
            failure="cli_is_error_flag: envelope.is_error=true",
            result_preview=str(envelope.get("result", ""))[:_PREVIEW_MAX],
        )

    result_text = envelope.get("result", "")
    if not isinstance(result_text, str) or not result_text.strip():
        return ParseResult(
            artifacts={},
            failure=f"result_field_empty_or_missing: type={type(result_text).__name__}",
        )

    preview = result_text[:_PREVIEW_MAX]

    # Strip markdown code fences if present (Claude frequently wraps JSON
    # in ```json ... ``` even when instructed not to).
    result_text = _strip_code_fences(result_text)

    # Primary: try direct JSON parse of the full result text.
    # Fallback: if the model prefixed prose before the JSON object,
    # locate and extract the first balanced {...} from the text.
    result_obj = None
    try:
        result_obj = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        # Fallback: extract first JSON object from prose-prefixed text
        extracted_json = _extract_first_json_object(result_text)
        if extracted_json is not None:
            try:
                result_obj = json.loads(extracted_json)
            except (json.JSONDecodeError, TypeError):
                pass

    if result_obj is None:
        return ParseResult(
            artifacts={},
            failure="inner_result_no_json_object: direct parse failed and no balanced JSON object found in result text",
            result_preview=preview,
        )

    if not isinstance(result_obj, dict):
        return ParseResult(
            artifacts={},
            failure=f"inner_result_not_dict: got {type(result_obj).__name__}",
            result_preview=preview,
        )

    artifacts_dict = result_obj.get("artifacts", {})
    if not isinstance(artifacts_dict, dict):
        return ParseResult(
            artifacts={},
            failure=f"artifacts_key_not_dict: got {type(artifacts_dict).__name__}",
            result_preview=preview,
        )

    if not artifacts_dict:
        # Valid JSON with empty artifacts — distinct from missing key
        top_keys = sorted(result_obj.keys())[:10]
        return ParseResult(
            artifacts={},
            failure=f"artifacts_dict_empty: top-level keys={top_keys}",
            result_preview=preview,
        )

    extracted = {
        name: payload
        for name, payload in artifacts_dict.items()
        if isinstance(payload, dict)
    }

    # Report any non-dict artifact values that were filtered out
    filtered = [k for k in artifacts_dict if k not in extracted]
    if filtered and not extracted:
        return ParseResult(
            artifacts={},
            failure=f"all_artifact_payloads_not_dict: filtered={filtered}",
            result_preview=preview,
        )

    # Check whether extracted artifact names match expected names.
    # This doesn't gate extraction (the executor handles missing-output
    # fail-close), but it annotates the ParseResult for diagnostics when
    # the LLM produced artifacts under wrong names.
    if expected_artifacts and extracted:
        expected_set = set(expected_artifacts)
        produced_set = set(extracted.keys())
        missing = sorted(expected_set - produced_set)
        unexpected = sorted(produced_set - expected_set)
        if missing and unexpected:
            return ParseResult(
                artifacts=extracted,
                failure=(
                    f"wrong_artifact_names: "
                    f"expected={sorted(expected_set)}, "
                    f"produced={sorted(produced_set)}, "
                    f"missing={missing}, "
                    f"unexpected={unexpected}"
                ),
                result_preview=preview,
            )

    return ParseResult(
        artifacts=extracted,
        failure=None,
        result_preview="",
    )


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
        debug_dir: "Path | None" = None,
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
        stderr_output = proc.stderr or ""

        # Non-zero exit code → runtime failure
        if proc.returncode != 0:
            stderr_preview = stderr_output[:_PREVIEW_MAX] if stderr_output else ""
            return AgentExecutionResult(
                success=False,
                raw_output=raw_output,
                latency_ms=latency,
                stderr=stderr_output,
                failure=FailureClassification(
                    origin="runtime",
                    step_id=step.name,
                    detail=(
                        f"Claude CLI exited with code {proc.returncode}."
                        + (f" stderr: {stderr_preview}" if stderr_preview else "")
                    ),
                ),
            )

        # Parse response and extract artifacts
        parse = _parse_backend_response(raw_output, list(step.outputs))

        # Extract token count from envelope if available
        token_count = 0
        try:
            envelope = json.loads(raw_output)
            usage = envelope.get("usage", {})
            token_count = usage.get("output_tokens", 0)
        except (json.JSONDecodeError, TypeError, AttributeError):
            envelope = None

        # --- Diagnostic capture (written to session debug dir) ---
        # Persists subprocess output for failed backend-dispatched steps
        # so the exact response contract violation can be inspected.
        if not parse.artifacts or parse.failure:
            _write_step_debug(
                step_name=step.name,
                returncode=proc.returncode,
                stdout=raw_output,
                stderr=stderr_output,
                parsed_artifact_keys=list(parse.artifacts.keys()),
                parse_failure=parse.failure,
                result_preview=parse.result_preview,
                usage=envelope.get("usage") if isinstance(envelope, dict) else None,
                debug_dir=str(debug_dir) if debug_dir else None,
            )

        return AgentExecutionResult(
            success=True,
            artifacts_produced=parse.artifacts,
            raw_output=raw_output,
            latency_ms=latency,
            token_count=token_count,
            stderr=stderr_output,
            parse_failure=parse.failure,
        )

    def execute_structural_step(
        self,
        step: WorkflowStep,
        component_kind: str,
        run_state: GovernanceRunState,
        spec: AssembledWorkflowSpec,
        bootstrap_payload: dict[str, dict[str, Any]] | None = None,
    ) -> AgentExecutionResult:
        """Structural steps are deterministic — no LLM needed even in live mode."""
        artifacts: dict[str, dict[str, Any]] = {}
        for output_name in step.outputs:
            if bootstrap_payload and output_name in bootstrap_payload:
                artifacts[output_name] = bootstrap_payload[output_name]
            else:
                artifacts[output_name] = {"produced_by": step.name, "structural": True}
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)
