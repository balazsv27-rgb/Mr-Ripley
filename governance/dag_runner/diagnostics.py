"""
diagnostics.py — Per-step timing, bottleneck analysis, and run diagnostics.

Produces a diagnostic report at run end:
- Per-step latency (wall time ms)
- Per-step token consumption (when backend reports it)
- Critical path analysis (longest dependency chain)
- Bottleneck identification
- Total run duration
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from governance.dag_runner.models import (
    AssembledWorkflowSpec,
    GovernanceRunState,
    NodeResult,
)
from governance.dag_runner.planner import ExecutionPlan


@dataclass(frozen=True)
class StepDiagnostic:
    """Diagnostic for a single step."""

    step_id: str
    status: str
    latency_ms: float
    token_count: int
    component_kind: str
    inference_used: bool


@dataclass(frozen=True)
class DiagnosticReport:
    """Aggregate diagnostic report for a run."""

    total_steps: int
    executed_steps: int
    skipped_steps: int
    failed_steps: int
    total_latency_ms: float
    total_tokens: int
    step_diagnostics: list[StepDiagnostic]
    critical_path: list[str]
    bottleneck_step: str | None
    bottleneck_latency_ms: float


def _parse_component_kind(component: str) -> str:
    """Extract component kind from component string."""
    if ":" in component:
        return component.split(":", 1)[0].strip()
    return component.strip()


def _find_critical_path(
    spec: AssembledWorkflowSpec,
    plan: ExecutionPlan,
    run_state: GovernanceRunState,
) -> list[str]:
    """Find the longest dependency chain (critical path) by latency.

    Uses dynamic programming on the DAG to find the path with maximum
    cumulative latency.
    """
    ordered_ids = [n.step_id for n in plan.ordered_steps]

    # Build cumulative latency map
    cum_latency: dict[str, float] = {}
    predecessor: dict[str, str | None] = {}

    for step_id in ordered_ids:
        step = spec.workflow_steps.get(step_id)
        nr = run_state.node_results.get(step_id)
        own_latency = nr.latency_ms if nr else 0.0

        max_parent = 0.0
        best_parent: str | None = None
        if step:
            for dep in step.depends_on:
                dep_cum = cum_latency.get(dep, 0.0)
                if dep_cum > max_parent:
                    max_parent = dep_cum
                    best_parent = dep

        cum_latency[step_id] = max_parent + own_latency
        predecessor[step_id] = best_parent

    if not cum_latency:
        return []

    # Trace back from the step with highest cumulative latency
    end_step = max(cum_latency, key=lambda k: cum_latency[k])
    path: list[str] = []
    current: str | None = end_step
    while current is not None:
        path.append(current)
        current = predecessor.get(current)
    path.reverse()
    return path


def build_diagnostic_report(
    spec: AssembledWorkflowSpec,
    plan: ExecutionPlan,
    run_state: GovernanceRunState,
) -> DiagnosticReport:
    """Build a diagnostic report from a completed run."""
    step_diags: list[StepDiagnostic] = []
    total_latency = 0.0
    total_tokens = 0
    executed = 0
    skipped = 0
    failed = 0
    bottleneck_step: str | None = None
    bottleneck_latency = 0.0

    for node in plan.ordered_steps:
        nr = run_state.node_results.get(node.step_id)
        if nr is None:
            continue

        step = spec.workflow_steps.get(node.step_id)
        kind = _parse_component_kind(step.component) if step else "unknown"

        diag = StepDiagnostic(
            step_id=node.step_id,
            status=nr.status,
            latency_ms=nr.latency_ms,
            token_count=nr.token_count,
            component_kind=kind,
            inference_used=nr.inference_used,
        )
        step_diags.append(diag)

        if nr.status == "PASS":
            executed += 1
        elif nr.status == "SKIP":
            skipped += 1
        elif nr.status == "FAIL":
            failed += 1
            executed += 1

        total_latency += nr.latency_ms
        total_tokens += nr.token_count

        if nr.latency_ms > bottleneck_latency:
            bottleneck_latency = nr.latency_ms
            bottleneck_step = node.step_id

    critical_path = _find_critical_path(spec, plan, run_state)

    return DiagnosticReport(
        total_steps=len(plan.ordered_steps),
        executed_steps=executed,
        skipped_steps=skipped,
        failed_steps=failed,
        total_latency_ms=total_latency,
        total_tokens=total_tokens,
        step_diagnostics=step_diags,
        critical_path=critical_path,
        bottleneck_step=bottleneck_step,
        bottleneck_latency_ms=bottleneck_latency,
    )


def diagnostic_report_to_dict(report: DiagnosticReport) -> dict[str, Any]:
    """Serialize a diagnostic report to a JSON-safe dict."""
    return {
        "total_steps": report.total_steps,
        "executed_steps": report.executed_steps,
        "skipped_steps": report.skipped_steps,
        "failed_steps": report.failed_steps,
        "total_latency_ms": report.total_latency_ms,
        "total_tokens": report.total_tokens,
        "critical_path": report.critical_path,
        "bottleneck_step": report.bottleneck_step,
        "bottleneck_latency_ms": report.bottleneck_latency_ms,
        "steps": [
            {
                "step_id": d.step_id,
                "status": d.status,
                "latency_ms": d.latency_ms,
                "token_count": d.token_count,
                "component_kind": d.component_kind,
                "inference_used": d.inference_used,
            }
            for d in report.step_diagnostics
        ],
    }
