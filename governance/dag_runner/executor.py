"""
executor.py — Governance DAG runner executor.

Supports two execution paths:

**V1 shell mode** (``backend=None``, default):
    Evaluates predicates, materialises placeholder artifacts, records trace.
    No real skill or agent invocation.

**V2 backend-driven mode** (``backend`` provided):
    Routes each step by parsed component kind (not step name).
    Structural steps execute deterministically.
    Skill-bound and coordinator steps dispatch to the ``ExecutionBackend``.

Both paths share predicate evaluation and fail-closed semantics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from governance.dag_runner.artifacts import artifact_exists
from governance.dag_runner.artifact_writer import (
    ArtifactWriterError,
    write_artifact_envelope,
)
from governance.dag_runner.models import (
    ArtifactRecord,
    AssembledWorkflowSpec,
    BlockingEvent,
    ExecutionConfig,
    ExecutionTraceEvent,
    GovernanceRunState,
    NodeResult,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan

if TYPE_CHECKING:
    from governance.dag_runner.execution_backend import ExecutionBackend
    from governance.dag_runner.path_policy import PathPolicy


_LEGACY_ARTIFACT_DIR = Path(".claude/run/artifacts")


def _get_repo_root() -> Path:
    """Resolve the project repo root (two levels up from governance/dag_runner/)."""
    return Path(__file__).resolve().parent.parent.parent


from governance.dag_runner.execution_backend import (
    write_failure_debug_artifact,
    write_timeout_diagnostic_bundle,
)
from governance.dag_runner.path_policy import PathPolicyViolation


class ExecutorError(RuntimeError):
    """Raised when workflow execution fails."""


@dataclass(frozen=True)
class ExecutionResult:
    """Wrapper around the final runtime state."""

    run_state: GovernanceRunState


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_initial_run_state(
    workflow_name: str,
    orchestration_version: str | None = None,
    constitution_version: str | None = None,
    session_dir: str | None = None,
) -> GovernanceRunState:
    return GovernanceRunState(
        run_id=str(uuid4()),
        started_at=_utc_now(),
        orchestration_version=orchestration_version,
        constitution_version=constitution_version,
        current_phase=workflow_name,
        session_dir=session_dir,
    )


def _append_trace(
    run_state: GovernanceRunState,
    *,
    node_name: str,
    event_type: str,
    detail: dict,
) -> None:
    run_state.execution_trace.append(
        ExecutionTraceEvent(
            timestamp=_utc_now(),
            node_name=node_name,
            event_type=event_type,
            detail=detail,
        )
    )


def _build_governance_context_payload(
    run_state: GovernanceRunState,
    config: ExecutionConfig,
    workflow_name: str,
) -> dict[str, Any]:
    """Build a request-bearing governance_context artifact payload.

    When bootstrap input is available, the payload contains the real
    request text, source, and run metadata.  Otherwise, falls back to
    a structural-only payload (backward compat for non-semantic modes).
    """
    if config.request_text:
        return {
            "produced_by": "load-context",
            "run_id": run_state.run_id,
            "request_id": config.request_id,
            "request_text": config.request_text,
            "request_source": config.request_source,
            "workflow_name": workflow_name,
            "execution_mode": config.mode,
            "bootstrap_status": "request_bearing",
        }
    return {
        "produced_by": "load-context",
        "structural": True,
        "run_id": run_state.run_id,
        "workflow_name": workflow_name,
        "execution_mode": config.mode,
        "bootstrap_status": "structural_only",
    }


def _record_artifacts_for_step(
    run_state: GovernanceRunState,
    step_id: str,
    outputs: list[str],
) -> None:
    for artifact_name in outputs:
        run_state.artifacts[artifact_name] = ArtifactRecord(
            name=artifact_name,
            producer_step=step_id,
            status="present",
            payload={"produced_by": step_id},
        )


# ---------------------------------------------------------------------------
# Private predicate evaluation helpers
# ---------------------------------------------------------------------------


def _evaluate_step_condition(
    step: WorkflowStep,
    run_state: GovernanceRunState,
) -> tuple[bool, dict[str, Any]]:
    """
    Evaluate ``step.condition`` against the current run state.

    Returns ``(matched, eval_detail)`` where ``matched=True`` means the condition
    is satisfied and the step may execute.

    Raises ``ExecutorError`` on unsupported or malformed predicates (fail closed).
    ``ArtifactStructureError`` from ``artifacts.py`` is not caught here — it
    propagates as a system-level error.
    """
    from governance.dag_runner.predicates import (  # deferred to avoid import cycle
        PredicateEvaluationError,
        evaluate_condition,
    )
    try:
        result = evaluate_condition(step.condition, run_state)
    except PredicateEvaluationError as exc:
        raise ExecutorError(
            f"Step '{step.name}': condition predicate evaluation failed — {exc}"
        ) from exc

    return result.matched, {
        "kind": "condition",
        "predicate_type": result.predicate_type,
        "artifact": result.artifact,
        "field": result.field,
        "matched": result.matched,
        "detail": result.detail,
    }


def _evaluate_step_skip_if(
    step: WorkflowStep,
    run_state: GovernanceRunState,
) -> tuple[bool, dict[str, Any]]:
    """
    Evaluate ``step.skip_if`` against the current run state.

    Returns ``(should_skip, eval_detail)`` where ``should_skip=True`` means the
    skip_if condition is satisfied and the step should be skipped.

    Raises ``ExecutorError`` on unsupported or malformed predicates (fail closed).
    """
    from governance.dag_runner.predicates import (
        PredicateEvaluationError,
        evaluate_condition,
    )
    try:
        result = evaluate_condition(step.skip_if, run_state)
    except PredicateEvaluationError as exc:
        raise ExecutorError(
            f"Step '{step.name}': skip_if predicate evaluation failed — {exc}"
        ) from exc

    return result.matched, {
        "kind": "skip_if",
        "predicate_type": result.predicate_type,
        "artifact": result.artifact,
        "field": result.field,
        "matched": result.matched,
        "detail": result.detail,
    }


def _record_predicate_trace(
    run_state: GovernanceRunState,
    step_id: str,
    eval_detail: dict[str, Any],
) -> None:
    """Record a predicate evaluation result into the execution trace."""
    kind = eval_detail.get("kind", "predicate")
    _append_trace(
        run_state,
        node_name=step_id,
        event_type=f"{kind}_evaluated",
        detail={k: v for k, v in eval_detail.items() if k != "kind"},
    )


def _build_skipped_node_result(
    step: WorkflowStep,
    reason: str,
    evidence: list[str],
) -> NodeResult:
    """Build a ``NodeResult`` with status ``SKIP`` for a step that was not executed."""
    return NodeResult(
        node_name=step.name,
        node_type=step.component,
        status="SKIP",
        summary=reason,
        evidence=evidence,
        produced_artifacts=[],
        triggered_blocks=[],
        inference_used=False,
    )


def _raise_blocking_events(
    step: WorkflowStep,
    run_state: GovernanceRunState,
    reason: str,
) -> None:
    """
    Append a ``BlockingEvent`` for each ``raises`` entry declared on the step.

    Called only when the executor encounters a runtime predicate error (fail closed).
    Normal SKIP (intentional control flow) does not emit blocking events.
    """
    for blocker_id in step.raises:
        run_state.blocking_conditions.append(
            BlockingEvent(
                blocking_id=blocker_id,
                raised_by=step.name,
                severity="error",
                message=reason,
                resolved=False,
            )
        )


def _check_required_inputs(
    step: WorkflowStep,
    run_state: GovernanceRunState,
    spec: AssembledWorkflowSpec,
) -> list[str]:
    """Return names of required input artifacts not present in run state.

    Only checks inputs that are declared in ``spec.artifacts`` (the registry).
    Non-artifact inputs (doc paths like ``CLAUDE.md``) are silently skipped.
    Returns an empty list when all declared artifact inputs are present.
    """
    raw_inputs = step.raw.get("inputs", []) or []
    missing: list[str] = []
    for name in raw_inputs:
        if not isinstance(name, str):
            continue
        if name not in spec.artifacts:
            continue  # not a registry artifact — skip
        if not artifact_exists(run_state, name):
            missing.append(name)
    return missing


# ---------------------------------------------------------------------------
# Component-kind classification (V2)
# ---------------------------------------------------------------------------

# Structural component kinds — executed deterministically, no LLM.
_STRUCTURAL_KINDS: frozenset[str] = frozenset({
    "constitution", "stage_gates", "hooks",
    "final_gate", "blocking_evaluator", "verification_update",
    "artifact_gate", "predicate_gate", "workflow_step",
})

# Backend-dispatched component kinds — require ExecutionBackend.
_BACKEND_KINDS: frozenset[str] = frozenset({
    "skill", "subagents",
})


def _parse_component_kind(component: str) -> tuple[str, str | None]:
    """Parse ``step.component`` into ``(kind, name_or_none)``.

    Examples:
        ``"constitution"`` → ``("constitution", None)``
        ``"skill:doc-truth-classification"`` → ``("skill", "doc-truth-classification")``
        ``"stage_gates"`` → ``("stage_gates", None)``
    """
    if ":" not in component:
        return component.strip(), None
    kind, value = component.split(":", 1)
    return kind.strip(), value.strip() or None


def _is_structural_step(component: str) -> bool:
    """Return True if the step should be executed structurally (no LLM)."""
    kind, _ = _parse_component_kind(component)
    return kind in _STRUCTURAL_KINDS


def _build_failure_detail(
    *,
    failure_origin: str,
    failure_stage: str,
    returncode: int | None = None,
    parse_failure_reason: str | None = None,
    stderr_preview: str = "",
    raw_output_preview: str = "",
    debug_artifact_written: bool = False,
    debug_artifact_path: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a standardized failure_detail dict with all required fields."""
    fd: dict[str, Any] = {
        "failure_origin": failure_origin,
        "failure_stage": failure_stage,
        "returncode": returncode,
        "parse_failure_reason": parse_failure_reason,
        "stderr_preview": stderr_preview,
        "raw_output_preview": raw_output_preview,
        "debug_artifact_written": debug_artifact_written,
        "debug_artifact_path": debug_artifact_path,
    }
    fd.update(extra)
    return fd


def _write_debug_and_update(
    fd: dict[str, Any],
    *,
    step_name: str,
    run_state: GovernanceRunState,
    raw_output: str = "",
    stderr: str = "",
    debug_dir: Path | None = None,
) -> None:
    """Write a failure debug artifact and update *fd* in place with write results.

    Pre-computes the expected path and optimistically updates *fd* before
    the write so the on-disk debug artifact reflects the final metadata
    (fixes the sync issue where the written file showed
    ``debug_artifact_written=false``).
    """
    from governance.dag_runner.execution_backend import _LEGACY_DEBUG_DIR

    target_dir = str(debug_dir) if debug_dir else _LEGACY_DEBUG_DIR
    expected_path = str(Path(target_dir) / f"{step_name}_debug.json")

    # Optimistically update fd before writing so the serialized file
    # contains the final debug write metadata.
    fd["debug_artifact_written"] = True
    fd["debug_artifact_path"] = expected_path

    written, path, err = write_failure_debug_artifact(
        step_name=step_name,
        failure_detail=fd,
        raw_output=raw_output,
        stderr=stderr,
        debug_dir=str(debug_dir) if debug_dir else None,
    )

    if not written:
        # Correct the optimistic values on write failure
        fd["debug_artifact_written"] = False
        fd["debug_artifact_path"] = None
    if err:
        fd["debug_write_error"] = err
        _append_trace(
            run_state,
            node_name=step_name,
            event_type="debug_write_failed",
            detail={"error": err},
        )


def _execute_v2_step(
    step: WorkflowStep,
    run_state: GovernanceRunState,
    spec: AssembledWorkflowSpec,
    backend: ExecutionBackend,
    config: ExecutionConfig,
    dry_run: bool = False,
    path_policy: "PathPolicy | None" = None,
    strict_artifact_validation: bool = False,
    debug_dir: Path | None = None,
) -> NodeResult:
    """Execute one step via the V2 backend-driven path.

    Routes by component kind:
    - structural kinds → ``backend.execute_structural_step()``
    - skill / subagents → resolve agent, assemble prompt, ``backend.execute_step()``

    In dry-run mode, prompt is assembled for diagnostics but backend is not invoked.
    """
    from governance.dag_runner.prompt_assembly import (
        assemble_step_prompt,
        build_prompt_context,
        build_prompt_composition_metadata,
    )

    kind, _name = _parse_component_kind(step.component)

    if dry_run:
        # B2: In dry-run, assemble prompt for diagnostics/trace if non-structural
        if not _is_structural_step(step.component):
            try:
                ctx_dict = assemble_step_prompt(
                    step, spec, run_state, path_policy=path_policy,
                )
                prompt_ctx = build_prompt_context(ctx_dict)
                _append_trace(
                    run_state,
                    node_name=step.name,
                    event_type="prompt_assembled",
                    detail={
                        "token_estimate": prompt_ctx.token_estimate,
                        "truncated": prompt_ctx.truncated,
                    },
                )
                _append_trace(
                    run_state,
                    node_name=step.name,
                    event_type="input_bounded",
                    detail={
                        "budget": prompt_ctx.token_budget,
                        "actual": prompt_ctx.token_estimate,
                        "truncated": prompt_ctx.truncated,
                        "truncation_events": prompt_ctx.truncation_events,
                    },
                )
            except Exception:
                pass  # dry-run: prompt assembly failure is non-fatal

        return NodeResult(
            node_name=step.name,
            node_type=step.component,
            status="PASS",
            summary=f"Dry-run: step would execute via {kind} dispatch.",
            evidence=[f"component_kind={kind}", "dry_run=True"],
            produced_artifacts=[],
            triggered_blocks=[],
            inference_used=False,
        )

    # Track prompt context and composition metadata for timeout diagnostics
    prompt_ctx = None
    prompt_composition = None

    # R3-D: backend_invocation_started trace event
    _append_trace(
        run_state,
        node_name=step.name,
        event_type="backend_invocation_started",
        detail={"component_kind": kind, "backend": type(backend).__name__},
    )

    if _is_structural_step(step.component):
        # Build bootstrap payload for load-context step
        bootstrap_payload: dict[str, dict[str, Any]] | None = None
        if step.name == "load-context" and "governance_context" in step.outputs:
            ctx_payload = _build_governance_context_payload(
                run_state, config, run_state.current_phase or "",
            )
            bootstrap_payload = {"governance_context": ctx_payload}

        result = backend.execute_structural_step(
            step=step,
            component_kind=kind,
            run_state=run_state,
            spec=spec,
            bootstrap_payload=bootstrap_payload,
        )
    else:
        # Resolve agent for backend dispatch
        from governance.dag_runner.agent_resolver import resolve_agent
        agent = resolve_agent(step, spec)

        if agent is not None:
            _append_trace(
                run_state,
                node_name=step.name,
                event_type="agent_resolved",
                detail={"agent": agent.name, "model": agent.model},
            )

            # B2: Assemble prompt and build PromptContext
            ctx_dict = assemble_step_prompt(
                step, spec, run_state, path_policy=path_policy,
            )
            # Thread structured output flag so prompt format can be simplified
            if hasattr(backend, "_use_structured_output"):
                ctx_dict["use_structured_output"] = backend._use_structured_output
            prompt_ctx = build_prompt_context(ctx_dict)
            prompt_composition = build_prompt_composition_metadata(ctx_dict)

            _append_trace(
                run_state,
                node_name=step.name,
                event_type="prompt_assembled",
                detail={
                    "token_estimate": prompt_ctx.token_estimate,
                    "truncated": prompt_ctx.truncated,
                },
            )
            _append_trace(
                run_state,
                node_name=step.name,
                event_type="input_bounded",
                detail={
                    "budget": prompt_ctx.token_budget,
                    "actual": prompt_ctx.token_estimate,
                    "truncated": prompt_ctx.truncated,
                    "truncation_events": prompt_ctx.truncation_events,
                },
            )

            result = backend.execute_step(
                step=step,
                agent=agent,
                config=config,
                run_state=run_state,
                spec=spec,
                prompt_context=prompt_ctx,
                debug_dir=debug_dir,
            )
        else:
            # Fallback: no agent binding, treat as structural
            result = backend.execute_structural_step(
                step=step,
                component_kind=kind,
                run_state=run_state,
                spec=spec,
            )

    # Structured trace of raw backend result for diagnostics
    _append_trace(
        run_state,
        node_name=step.name,
        event_type="backend_result_received",
        detail={
            "success": result.success,
            "failure_origin": result.failure.origin if result.failure else None,
            "returncode": result.returncode,
            "raw_output_len": len(result.raw_output) if result.raw_output else 0,
            "stderr_len": len(result.stderr) if result.stderr else 0,
            "parse_failure": result.parse_failure,
            "produced_artifact_count": len(result.artifacts_produced),
            "latency_ms": result.latency_ms,
            "token_count": result.token_count,
            "retry_count": result.retry_count,
        },
    )

    # R3-D: backend_invocation_completed / backend_invocation_failed
    if result.success:
        completed_detail: dict[str, Any] = {
            "component_kind": kind,
            "artifacts_produced": list(result.artifacts_produced.keys()),
            "latency_ms": result.latency_ms,
        }
        if result.parse_failure:
            completed_detail["parse_failure"] = result.parse_failure
        if result.stderr:
            completed_detail["stderr_preview"] = result.stderr[:500]
        _append_trace(
            run_state,
            node_name=step.name,
            event_type="backend_invocation_completed",
            detail=completed_detail,
        )
    else:
        fail_detail: dict[str, Any] = {
            "component_kind": kind,
            "failure": str(result.failure) if result.failure else "unknown",
        }
        if result.stderr:
            fail_detail["stderr_preview"] = result.stderr[:500]
        _append_trace(
            run_state,
            node_name=step.name,
            event_type="backend_invocation_failed",
            detail=fail_detail,
        )

    # B5: Artifact schema validation
    if result.success and result.artifacts_produced:
        from governance.dag_runner.artifact_schema import validate_artifact_output

        all_violations = []
        for art_name, art_data in result.artifacts_produced.items():
            art_violations = validate_artifact_output(art_name, art_data, step, spec)
            all_violations.extend(art_violations)

        if all_violations:
            violation_details = [
                {"artifact": v.artifact_name, "violation": v.violation, **v.detail}
                for v in all_violations
            ]
            _append_trace(
                run_state,
                node_name=step.name,
                event_type="artifact_validated",
                detail={
                    "passed": False,
                    "violations": violation_details,
                    "strict": strict_artifact_validation,
                },
            )
            if strict_artifact_validation:
                schema_evidence = [
                    f"component_kind={kind}",
                    f"backend={type(backend).__name__}",
                ]
                schema_fd = _build_failure_detail(
                    failure_origin="contract",
                    failure_stage="schema_validation",
                    returncode=result.returncode,
                    parse_failure_reason=result.parse_failure,
                    stderr_preview=result.stderr[:500] if result.stderr else "",
                    raw_output_preview=result.raw_output[:500] if result.raw_output else "",
                    violation_count=len(all_violations),
                    violations=violation_details,
                )
                _write_debug_and_update(
                    schema_fd,
                    step_name=step.name,
                    run_state=run_state,
                    raw_output=result.raw_output,
                    stderr=result.stderr,
                    debug_dir=debug_dir,
                )
                for v in all_violations:
                    detail_str = ", ".join(
                        f"{k}={v2}" for k, v2 in v.detail.items()
                    ) if v.detail else ""
                    schema_evidence.append(
                        f"schema_violation={v.artifact_name}:"
                        f"{v.violation}"
                        + (f"({detail_str})" if detail_str else "")
                    )
                return NodeResult(
                    node_name=step.name,
                    node_type=step.component,
                    status="FAIL",
                    summary=(
                        f"Artifact schema validation failed: "
                        f"{len(all_violations)} violation(s) — "
                        + "; ".join(
                            f"{v.artifact_name}: {v.violation}"
                            for v in all_violations
                        )
                    ),
                    evidence=schema_evidence,
                    produced_artifacts=[],
                    triggered_blocks=list(step.raises),
                    inference_used=kind in _BACKEND_KINDS,
                    latency_ms=result.latency_ms,
                    token_count=result.token_count,
                    failure_detail=schema_fd,
                )
            # else: warn only — continue to record artifacts
        else:
            _append_trace(
                run_state,
                node_name=step.name,
                event_type="artifact_validated",
                detail={
                    "passed": True,
                    "artifact_count": len(result.artifacts_produced),
                },
            )

    # Record produced artifacts into run state
    for artifact_name, artifact_data in result.artifacts_produced.items():
        run_state.artifacts[artifact_name] = ArtifactRecord(
            name=artifact_name,
            producer_step=step.name,
            status="present",
            payload=artifact_data,
        )

    # Fail-close: backend-dispatched step with declared outputs must produce them.
    # A step that declares outputs but produces none indicates a backend response
    # parsing failure — the step should not silently PASS.
    # CRITICAL: only check declared outputs when the backend invocation itself
    # succeeded (result.success=True).  Backend failures (timeout, spawn error,
    # nonzero exit) must NOT fall into this block — they are handled later at
    # the backend_invocation failure path with their true failure_origin preserved.
    if not dry_run and result.success and kind in _BACKEND_KINDS and step.outputs:
        missing_outputs = [
            o for o in step.outputs if o not in result.artifacts_produced
        ]
        if missing_outputs:
            produced = list(result.artifacts_produced.keys())

            # Detect "wrong artifact name" — artifacts were extracted from
            # the response but under names that don't match declared outputs.
            unexpected_names = [n for n in produced if n not in step.outputs]

            # Extract inner result text preview from raw output
            raw_output_preview = ""
            if result.raw_output:
                try:
                    _env = json.loads(result.raw_output)
                    _rt = _env.get("result", "")
                    if isinstance(_rt, str):
                        raw_output_preview = _rt[:500]
                except Exception:
                    raw_output_preview = result.raw_output[:500]

            # Classify failure stage by root cause.
            # When the backend parse itself is the source of zero/wrong
            # artifacts, attribute to backend_parse or
            # backend_response_contract — not executor_declared_output_check.
            # executor_declared_output_check is reserved for cases where
            # the backend successfully produced artifact objects but
            # declared outputs were still not fully satisfied.
            if result.parse_failure:
                _failure_stage = "backend_parse"
            elif not produced and (result.raw_output or result.stderr):
                _failure_stage = "backend_response_contract"
            else:
                _failure_stage = "executor_declared_output_check"

            # Build structured failure_detail for machine-readable diagnostics
            fd = _build_failure_detail(
                failure_origin="runtime",
                failure_stage=_failure_stage,
                returncode=result.returncode,
                parse_failure_reason=result.parse_failure,
                stderr_preview=result.stderr[:500] if result.stderr else "",
                raw_output_preview=raw_output_preview,
                missing_outputs=missing_outputs,
                declared_outputs=list(step.outputs),
                produced_outputs=produced,
            )
            if unexpected_names:
                fd["unexpected_artifact_names"] = unexpected_names
            _write_debug_and_update(
                fd,
                step_name=step.name,
                run_state=run_state,
                raw_output=result.raw_output,
                stderr=result.stderr,
                debug_dir=debug_dir,
            )

            _append_trace(
                run_state,
                node_name=step.name,
                event_type="declared_outputs_missing",
                detail=fd,
            )

            # Build summary with actionable detail
            summary = (
                f"Declared outputs not produced by backend: "
                f"{', '.join(missing_outputs)}"
            )
            if unexpected_names:
                summary += (
                    f" (backend produced [{', '.join(unexpected_names)}]"
                    f" — expected [{', '.join(step.outputs)}])"
                )
            elif result.parse_failure:
                summary += f" (parse: {result.parse_failure})"

            # Evidence list — concise tags for backward compat
            evidence = [
                f"component_kind={kind}",
                f"backend={type(backend).__name__}",
            ]
            evidence.extend(f"missing_output={o}" for o in missing_outputs)
            if unexpected_names:
                evidence.extend(
                    f"unexpected_output={n}" for n in unexpected_names
                )
            if result.parse_failure:
                evidence.append(f"parse_failure={result.parse_failure}")

            return NodeResult(
                node_name=step.name,
                node_type=step.component,
                status="FAIL",
                summary=summary,
                evidence=evidence,
                produced_artifacts=produced,
                triggered_blocks=list(step.raises),
                inference_used=kind in _BACKEND_KINDS,
                latency_ms=result.latency_ms,
                token_count=result.token_count,
                failure_detail=fd,
            )

    if result.success:
        return NodeResult(
            node_name=step.name,
            node_type=step.component,
            status="PASS",
            summary=f"V2 {kind} execution completed.",
            evidence=[f"component_kind={kind}", f"backend={type(backend).__name__}"],
            produced_artifacts=list(result.artifacts_produced.keys()),
            triggered_blocks=list(step.raises),
            inference_used=kind in _BACKEND_KINDS,
            latency_ms=result.latency_ms,
            token_count=result.token_count,
        )

    # Backend invocation failure — map origin to specific failure_stage
    _origin = result.failure.origin if result.failure else "runtime"
    _stage_map = {
        "timeout": "backend_timeout",
        "runtime": "backend_invocation",
        "artifact": "backend_artifact",
        "contract": "backend_contract",
    }
    _backend_stage = _stage_map.get(_origin, "backend_invocation")

    fd = _build_failure_detail(
        failure_origin=_origin,
        failure_stage=_backend_stage,
        returncode=result.returncode,
        parse_failure_reason=result.parse_failure,
        stderr_preview=result.stderr[:500] if result.stderr else "",
        raw_output_preview=result.raw_output[:500] if result.raw_output else "",
        backend_failure_detail=result.failure.detail if result.failure else None,
        raw_output_len=len(result.raw_output) if result.raw_output else 0,
        stderr_len=len(result.stderr) if result.stderr else 0,
    )

    # For timeout failures, include execution context and transport evidence
    if _origin == "timeout":
        fd["timeout_ms"] = result.latency_ms
        fd["timeout_seconds"] = result.timeout_seconds
        fd["elapsed_seconds"] = result.elapsed_seconds
        fd["timeout_command"] = result.timeout_command
        fd["timeout_stdout_len"] = len(result.timeout_stdout)
        fd["timeout_stderr_len"] = len(result.timeout_stderr)
        try:
            ctx = backend.get_execution_context() if hasattr(backend, "get_execution_context") else {}
            if ctx:
                fd["subprocess_cwd"] = ctx.get("subprocess_cwd", "")
                fd["model"] = ctx.get("model", "")
                fd["backend"] = ctx.get("backend", "")
        except Exception:
            pass
        # Include prompt context summary for timeout diagnosis
        if prompt_ctx is not None:
            fd["prompt_token_estimate"] = prompt_ctx.token_estimate
            fd["prompt_token_budget"] = prompt_ctx.token_budget
            fd["prompt_truncated"] = prompt_ctx.truncated
        # Include full prompt composition metadata for timeout diagnosis
        if prompt_composition is not None:
            fd["prompt_composition"] = prompt_composition

        # Write debug artifact FIRST so fd.debug_artifact_written/path
        # are synced when the timeout bundle serializes failure_detail.
        _write_debug_and_update(
            fd,
            step_name=step.name,
            run_state=run_state,
            raw_output=result.raw_output,
            stderr=result.stderr,
            debug_dir=debug_dir,
        )

        # Write dedicated timeout diagnostic bundle with full transport evidence
        bundle_written, bundle_path, bundle_err = write_timeout_diagnostic_bundle(
            step_name=step.name,
            command=result.timeout_command,
            timeout_seconds=result.timeout_seconds,
            elapsed_seconds=result.elapsed_seconds,
            partial_stdout=result.timeout_stdout,
            partial_stderr=result.timeout_stderr,
            assembled_prompt=prompt_ctx.assembled_prompt if prompt_ctx else "",
            prompt_composition=prompt_composition,
            failure_detail=fd,
            debug_dir=str(debug_dir) if debug_dir else None,
        )
        if bundle_written and bundle_path:
            fd["timeout_diagnostic_bundle_path"] = bundle_path
        if bundle_err:
            fd["timeout_bundle_write_error"] = bundle_err

        _append_trace(
            run_state,
            node_name=step.name,
            event_type="backend_timeout",
            detail={
                "timeout_ms": result.latency_ms,
                "timeout_seconds": result.timeout_seconds,
                "elapsed_seconds": result.elapsed_seconds,
                "step_name": step.name,
                "model": fd.get("model", ""),
                "subprocess_cwd": fd.get("subprocess_cwd", ""),
                "raw_output_len": fd.get("raw_output_len", 0),
                "stderr_len": fd.get("stderr_len", 0),
                "timeout_stdout_len": len(result.timeout_stdout),
                "timeout_stderr_len": len(result.timeout_stderr),
                "timeout_diagnostic_bundle_path": bundle_path if bundle_written else None,
            },
        )
    else:
        _write_debug_and_update(
            fd,
            step_name=step.name,
            run_state=run_state,
            raw_output=result.raw_output,
            stderr=result.stderr,
            debug_dir=debug_dir,
        )
    return NodeResult(
        node_name=step.name,
        node_type=step.component,
        status="FAIL",
        summary=f"V2 {kind} execution failed: {result.failure}",
        evidence=[f"component_kind={kind}", f"backend={type(backend).__name__}"],
        produced_artifacts=list(result.artifacts_produced.keys()),
        triggered_blocks=list(step.raises),
        inference_used=kind in _BACKEND_KINDS,
        latency_ms=result.latency_ms,
        token_count=result.token_count,
        failure_detail=fd,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_plan(
    spec: AssembledWorkflowSpec,
    plan: ExecutionPlan,
    *,
    verdict_status: str | None = None,
    config: ExecutionConfig | None = None,
    backend: ExecutionBackend | None = None,
    prior_state: GovernanceRunState | None = None,
) -> ExecutionResult:
    """
    Execute a validated and planned workflow.

    When ``backend is None`` (default): V1 shell mode (unchanged).
    When ``backend`` is provided: V2 component-kind dispatch mode.
    When ``prior_state`` is provided: continuation from a prior run.
    """
    if not plan.ordered_steps:
        raise ExecutorError("Cannot execute empty execution plan.")

    effective_config = config or ExecutionConfig()

    from governance.dag_runner.session import (
        SessionError,
        create_session_dir,
        write_session_pointer,
    )

    # Continuation: carry forward prior state
    completed_steps: set[str] = set()
    if prior_state is not None and effective_config.continue_from:
        run_state = prior_state
        # Mark all previously completed steps
        completed_steps = set(prior_state.node_results.keys())

        # Ensure session dir is set (backward compat with old state files)
        if run_state.session_dir is None:
            session_root = create_session_dir(run_state.run_id)
            run_state.session_dir = str(session_root)
            write_session_pointer(session_root, run_state.run_id)
            _append_trace(
                run_state,
                node_name="__run__",
                event_type="session_created_for_legacy_continuation",
                detail={"session_dir": run_state.session_dir},
            )
        else:
            write_session_pointer(Path(run_state.session_dir), run_state.run_id)

        _append_trace(
            run_state,
            node_name="__run__",
            event_type="continuation_started",
            detail={
                "continue_from": effective_config.continue_from,
                "prior_completed_steps": len(completed_steps),
                "prior_artifacts": len(prior_state.artifacts),
                "session_dir": run_state.session_dir,
            },
        )
    else:
        run_state = _build_initial_run_state(
            workflow_name=plan.workflow_name,
            orchestration_version=spec.manifest.workflow_version,
            constitution_version=None,
        )
        # Create session directory for fresh run
        session_root = create_session_dir(run_state.run_id)
        run_state.session_dir = str(session_root)
        write_session_pointer(session_root, run_state.run_id)

    # Fail-closed: agent_execution mode requires bootstrap input on fresh runs
    if (
        effective_config.mode == "agent_execution"
        and not effective_config.continue_from
        and not effective_config.request_text
    ):
        raise ExecutorError(
            "agent_execution mode requires bootstrap input on fresh runs. "
            "Provide --request-text or --request-file."
        )

    _append_trace(
        run_state,
        node_name="__run__",
        event_type="run_started",
        detail={
            "workflow_name": plan.workflow_name,
            "planned_steps": len(plan.ordered_steps),
            "mode": effective_config.mode,
            "session_dir": run_state.session_dir,
            "has_bootstrap_input": effective_config.request_text is not None,
        },
    )

    # Resolve artifact and debug directories from session
    artifact_dir = Path(run_state.session_dir) / "artifacts"
    debug_dir = Path(run_state.session_dir) / "debug"

    halted = False

    for node in plan.ordered_steps:
        # Skip already-completed steps in continuation mode
        if node.step_id in completed_steps:
            continue
        step = spec.workflow_steps.get(node.step_id)
        if step is None:
            raise ExecutorError(
                f"Planned step '{node.step_id}' not found in assembled workflow steps."
            )

        _append_trace(
            run_state,
            node_name=node.step_id,
            event_type="step_started",
            detail={
                "component": node.component,
                "depends_on": list(node.depends_on),
            },
        )

        # -----------------------------------------------------------------
        # Dependency failure check (V2 backend-driven, non-dry-run only):
        # If any dependency step has status FAIL or SKIP, do not invoke
        # the backend.  Return SKIP with an explanation of the failed
        # dependency.  This prevents cascading failures where a downstream
        # step reports a missing-input contract error instead of
        # identifying the true root cause.
        # -----------------------------------------------------------------
        if backend is not None and effective_config.mode != "dry_run":
            failed_deps: list[str] = []
            for dep_id in step.depends_on:
                dep_result = run_state.node_results.get(dep_id)
                if dep_result is not None and dep_result.status in ("FAIL", "SKIP"):
                    failed_deps.append(f"{dep_id}={dep_result.status}")
            if failed_deps:
                dep_reason = (
                    f"Skipped due to failed/skipped dependency: "
                    f"{', '.join(failed_deps)}"
                )
                dep_evidence = [
                    f"failed_dependency={d}" for d in failed_deps
                ]
                node_result = _build_skipped_node_result(
                    step, dep_reason, dep_evidence,
                )
                run_state.node_results[node.step_id] = node_result
                _append_trace(
                    run_state,
                    node_name=node.step_id,
                    event_type="step_skipped_dependency_failed",
                    detail={
                        "reason": dep_reason,
                        "failed_deps": failed_deps,
                    },
                )
                continue

        # -----------------------------------------------------------------
        # Predicate evaluation — V1 policy:
        #   1. Evaluate condition first (if present).
        #      Not matched → SKIP; skip_if is not evaluated.
        #   2. Evaluate skip_if (if present, only when condition passed/absent).
        #      Matched → SKIP.
        #   3. Both absent or both passed → execute normally in shell mode.
        # -----------------------------------------------------------------
        should_skip = False
        skip_reason = ""
        skip_evidence: list[str] = []

        if step.condition is not None:
            try:
                condition_matched, eval_detail = _evaluate_step_condition(step, run_state)
            except ExecutorError as exc:
                _append_trace(
                    run_state,
                    node_name=node.step_id,
                    event_type="condition_evaluation_error",
                    detail={"error": str(exc)},
                )
                _raise_blocking_events(step, run_state, str(exc))
                raise

            _record_predicate_trace(run_state, node.step_id, eval_detail)

            if not condition_matched:
                should_skip = True
                skip_reason = (
                    f"Condition not satisfied: "
                    f"{eval_detail.get('detail', 'condition did not match')}"
                )
                skip_evidence = [
                    f"condition_type={eval_detail.get('predicate_type')}",
                    f"condition_artifact={eval_detail.get('artifact')}",
                    f"condition_detail={eval_detail.get('detail')}",
                ]

        if not should_skip and step.skip_if is not None:
            try:
                skip_if_matched, eval_detail = _evaluate_step_skip_if(step, run_state)
            except ExecutorError as exc:
                _append_trace(
                    run_state,
                    node_name=node.step_id,
                    event_type="skip_if_evaluation_error",
                    detail={"error": str(exc)},
                )
                _raise_blocking_events(step, run_state, str(exc))
                raise

            _record_predicate_trace(run_state, node.step_id, eval_detail)

            if skip_if_matched:
                should_skip = True
                skip_reason = (
                    f"skip_if matched: "
                    f"{eval_detail.get('detail', 'skip_if condition matched')}"
                )
                skip_evidence = [
                    f"skip_if_type={eval_detail.get('predicate_type')}",
                    f"skip_if_artifact={eval_detail.get('artifact')}",
                    f"skip_if_detail={eval_detail.get('detail')}",
                ]

        if should_skip:
            node_result = _build_skipped_node_result(step, skip_reason, skip_evidence)
            run_state.node_results[node.step_id] = node_result
            _append_trace(
                run_state,
                node_name=node.step_id,
                event_type="step_skipped",
                detail={"reason": skip_reason},
            )
            continue

        # -----------------------------------------------------------------
        # Execution dispatch
        # -----------------------------------------------------------------
        if backend is not None:
            # V2 backend-driven path — component-kind routing
            is_dry_run = effective_config.mode == "dry_run"

            # R2-A.1: Required-input artifact validation (V2 only, not dry-run)
            # In dry-run mode, no step produces real artifacts, so checking
            # inputs would false-positive every downstream step.
            missing_inputs = (
                _check_required_inputs(step, run_state, spec)
                if not is_dry_run
                else []
            )
            if missing_inputs:
                mi_fd = _build_failure_detail(
                    failure_origin="contract",
                    failure_stage="input_validation",
                    missing_inputs=missing_inputs,
                )
                _write_debug_and_update(
                    mi_fd,
                    step_name=step.name,
                    run_state=run_state,
                    debug_dir=debug_dir,
                )
                node_result = NodeResult(
                    node_name=step.name,
                    node_type=step.component,
                    status="FAIL",
                    summary=(
                        f"Missing required input artifacts: "
                        f"{', '.join(missing_inputs)}"
                    ),
                    evidence=[
                        f"missing_input={n}" for n in missing_inputs
                    ],
                    produced_artifacts=[],
                    triggered_blocks=list(step.raises),
                    inference_used=False,
                    failure_detail=mi_fd,
                )
                run_state.node_results[node.step_id] = node_result
                _append_trace(
                    run_state,
                    node_name=node.step_id,
                    event_type="required_input_missing",
                    detail={"missing_inputs": missing_inputs},
                )
                # Apply halt-on-critical (same pattern as FAIL path below)
                for blocker_id in step.raises:
                    blocker_def = spec.blocking_conditions.get(blocker_id)
                    if blocker_def and blocker_def.halts_workflow:
                        run_state.blocking_conditions.append(
                            BlockingEvent(
                                blocking_id=blocker_id,
                                raised_by=step.name,
                                severity="critical",
                                message=node_result.summary,
                                resolved=False,
                            )
                        )
                        halted = True
                        break
                if halted:
                    break
                continue

            # B3: Determine path policy for prompt assembly.
            # MockExecutionBackend does not need path enforcement
            # (its output is deterministic, no real file access at runtime).
            from governance.dag_runner.execution_backend import MockExecutionBackend
            step_path_policy: PathPolicy | None = None
            if not isinstance(backend, MockExecutionBackend):
                from governance.dag_runner.path_policy import default_governance_policy
                step_path_policy = default_governance_policy(_get_repo_root())

            # B5: Strict artifact validation for live (non-Mock) backends
            strict_validation = not isinstance(backend, MockExecutionBackend)

            try:
                node_result = _execute_v2_step(
                    step=step,
                    run_state=run_state,
                    spec=spec,
                    backend=backend,
                    config=effective_config,
                    dry_run=is_dry_run,
                    path_policy=step_path_policy,
                    strict_artifact_validation=strict_validation,
                    debug_dir=debug_dir,
                )
            except PathPolicyViolation as exc:
                # B3-C: Fail-closed on path policy violation
                node_result = NodeResult(
                    node_name=step.name,
                    node_type=step.component,
                    status="FAIL",
                    summary=f"Path policy violation: {exc}",
                    evidence=["path_policy_violation=True"],
                    produced_artifacts=[],
                    triggered_blocks=list(step.raises),
                    inference_used=False,
                )
                _append_trace(
                    run_state,
                    node_name=node.step_id,
                    event_type="path_policy_violation",
                    detail={"error": str(exc)},
                )
            run_state.node_results[node.step_id] = node_result

            # R2-A: Write artifact envelopes to disk (V2, non-dry-run, PASS)
            if node_result.status == "PASS" and not is_dry_run:
                artifact_write_failures: list[str] = []
                for art_name in node_result.produced_artifacts:
                    art_record = run_state.artifacts.get(art_name)
                    if art_record is None:
                        continue
                    try:
                        write_artifact_envelope(
                            name=art_name,
                            data=dict(art_record.payload),
                            produced_by=step.name,
                            session=run_state.run_id,
                            artifact_dir=artifact_dir,
                        )
                        _append_trace(
                            run_state,
                            node_name=node.step_id,
                            event_type="artifact_produced",
                            detail={
                                "artifact": art_name,
                                "path": str(
                                    artifact_dir / f"{art_name}.json"
                                ),
                            },
                        )
                    except ArtifactWriterError as exc:
                        artifact_write_failures.append(art_name)
                        _append_trace(
                            run_state,
                            node_name=node.step_id,
                            event_type="artifact_write_failed",
                            detail={
                                "artifact": art_name,
                                "error": str(exc),
                            },
                        )

                if artifact_write_failures:
                    # Overwrite node_result with FAIL — artifact write is
                    # fail-closed per CLAUDE.md §7.
                    aw_fd = _build_failure_detail(
                        failure_origin="artifact",
                        failure_stage="artifact_write",
                        failed_artifacts=artifact_write_failures,
                    )
                    _write_debug_and_update(
                        aw_fd,
                        step_name=step.name,
                        run_state=run_state,
                        debug_dir=debug_dir,
                    )
                    node_result = NodeResult(
                        node_name=node_result.node_name,
                        node_type=node_result.node_type,
                        status="FAIL",
                        summary=(
                            f"Artifact write failed for: "
                            f"{', '.join(artifact_write_failures)}"
                        ),
                        evidence=list(node_result.evidence) + [
                            f"artifact_write_failed={n}"
                            for n in artifact_write_failures
                        ],
                        produced_artifacts=node_result.produced_artifacts,
                        triggered_blocks=node_result.triggered_blocks,
                        inference_used=node_result.inference_used,
                        latency_ms=node_result.latency_ms,
                        token_count=node_result.token_count,
                        failure_detail=aw_fd,
                    )
                    run_state.node_results[node.step_id] = node_result

            _append_trace(
                run_state,
                node_name=node.step_id,
                event_type="step_completed" if node_result.status == "PASS" else "step_failed",
                detail={
                    "component": node.component,
                    "component_kind": _parse_component_kind(step.component)[0],
                    "produced_artifacts": node_result.produced_artifacts,
                    "triggered_blocks": node_result.triggered_blocks,
                    "status": node_result.status,
                },
            )

            # Halt-on-critical-failure: if a step FAIL raises a blocker
            # with halts_workflow=True, stop DAG traversal.
            if node_result.status == "FAIL":
                for blocker_id in step.raises:
                    blocker_def = spec.blocking_conditions.get(blocker_id)
                    if blocker_def and blocker_def.halts_workflow:
                        run_state.blocking_conditions.append(
                            BlockingEvent(
                                blocking_id=blocker_id,
                                raised_by=step.name,
                                severity="critical",
                                message=node_result.summary,
                                resolved=False,
                            )
                        )
                        # R3-D: blocking_event_raised trace event
                        _append_trace(
                            run_state,
                            node_name=node.step_id,
                            event_type="blocking_event_raised",
                            detail={
                                "blocking_id": blocker_id,
                                "severity": "critical",
                                "halts_workflow": True,
                            },
                        )
                        _append_trace(
                            run_state,
                            node_name=node.step_id,
                            event_type="halt_on_critical_failure",
                            detail={
                                "blocking_id": blocker_id,
                                "reason": node_result.summary,
                            },
                        )
                        # Skip all remaining steps
                        halted = True
                        break

            if halted:
                break
            continue

        # V1 shell execution — step ran; materialise artifacts and record result.
        _record_artifacts_for_step(run_state, node.step_id, list(step.outputs))

        node_result = NodeResult(
            node_name=node.step_id,
            node_type=node.component,
            status="PASS",
            summary="Step recorded successfully in V1 shell execution.",
            evidence=[f"component={node.component}"],
            produced_artifacts=list(step.outputs),
            triggered_blocks=list(step.raises),
            inference_used=False,
        )
        run_state.node_results[node.step_id] = node_result

        _append_trace(
            run_state,
            node_name=node.step_id,
            event_type="step_completed",
            detail={
                "component": node.component,
                "produced_artifacts": list(step.outputs),
                "triggered_blocks": list(step.raises),
            },
        )

    # Record remaining unexecuted steps as SKIP if halted by critical blocker
    if halted:
        executed_ids = set(run_state.node_results.keys())
        for remaining_node in plan.ordered_steps:
            if remaining_node.step_id not in executed_ids:
                remaining_step = spec.workflow_steps.get(remaining_node.step_id)
                if remaining_step is not None:
                    run_state.node_results[remaining_node.step_id] = (
                        _build_skipped_node_result(
                            remaining_step,
                            reason="Skipped due to halt-on-critical-failure.",
                            evidence=["halt_on_critical_failure=True"],
                        )
                    )

    run_state.final_verdict = verdict_status

    _append_trace(
        run_state,
        node_name="__run__",
        event_type="run_completed",
        detail={
            "final_verdict": verdict_status,
            "recorded_steps": len(run_state.node_results),
            "recorded_artifacts": len(run_state.artifacts),
        },
    )

    return ExecutionResult(run_state=run_state)
