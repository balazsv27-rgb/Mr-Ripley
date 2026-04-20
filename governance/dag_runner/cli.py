from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from governance.dag_runner.assembler import AssemblerError, assemble_workflow_spec
from governance.dag_runner.blockers import BlockerError, analyze_blockers
from governance.dag_runner.diagnostics import build_diagnostic_report, diagnostic_report_to_dict
from governance.dag_runner.drift_detector import detect_drift
from governance.dag_runner.executor import ExecutorError, execute_plan, _parse_component_kind
from governance.dag_runner.loader import DEFAULT_WORKFLOW_PATH, LoaderError, load_workflow_packages
from governance.dag_runner.planner import PlannerError, build_execution_plan
from governance.dag_runner.state_store import (
    DEFAULT_STATE_PATH,
    StateStoreError,
    build_stored_run_state,
    write_run_state,
)
from governance.dag_runner.validator import ValidationError, validate_or_raise, validate_workflow_spec
from governance.dag_runner.verdict import VerdictError, compute_verdict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# R3-A: Semantic exit codes
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_STRUCTURAL_FAILURE = 1        # loader, assembler, validator, drift
EXIT_CONTRACT_FAILURE = 2          # halt-on-critical (halts_workflow blocker)
EXIT_RUNTIME_FAILURE = 3           # backend invocation error
EXIT_ARTIFACT_FAILURE = 4          # artifact write / validation failure
EXIT_TIMEOUT = 5                   # timeout exceeded
EXIT_VERDICT_REVIEW_ONLY = 10      # verdict = review_only
EXIT_VERDICT_BLOCKED = 11          # verdict = blocked (governance, not structural)


def _exit_code_for_execution(run_state, verdict_status: str) -> int:
    """Derive the appropriate exit code after successful execution."""
    # Check for halt-on-critical (contract failure)
    for bc in run_state.blocking_conditions:
        if not bc.resolved and bc.severity == "critical":
            return EXIT_CONTRACT_FAILURE

    # Check for artifact write failures
    for nr in run_state.node_results.values():
        if nr.status == "FAIL" and any(
            e.startswith("artifact_write_failed=") for e in nr.evidence
        ):
            return EXIT_ARTIFACT_FAILURE

    # Map verdict status
    if verdict_status == "review_only":
        return EXIT_VERDICT_REVIEW_ONLY
    if verdict_status == "blocked":
        return EXIT_VERDICT_BLOCKED

    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dag-runner",
        description="Mr. Ripley governance DAG runner CLI",
    )
    parser.add_argument(
        "--workflow",
        type=str,
        default=str(DEFAULT_WORKFLOW_PATH),
        help="Path to the root workflow YAML file.",
    )
    parser.add_argument(
        "--show-steps",
        action="store_true",
        help="Print the ordered workflow steps.",
    )
    parser.add_argument(
        "--write-state",
        action="store_true",
        help="Write persisted run state JSON.",
    )
    parser.add_argument(
        "--state-path",
        type=str,
        default=str(DEFAULT_STATE_PATH),
        help="Output path for persisted run state JSON.",
    )
    # V2 execution mode flags
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk plan and evaluate predicates without producing artifacts.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit JSON output to stdout.",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Emit DAG structure as JSON without execution.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="shell_v1",
        choices=["shell_v1", "agent_execution"],
        help="Execution mode (default: shell_v1).",
    )
    parser.add_argument(
        "--continue-from",
        type=str,
        default=None,
        help="Resume execution from the given step ID.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Total run timeout in milliseconds.",
    )
    parser.add_argument(
        "--phase",
        type=str,
        default=None,
        help="Execute only steps in the given layer (A-E).",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default=None,
        choices=["mock", "claude_code_cli"],
        help="Execution backend (default: mock). 'claude_code_cli' uses local Claude CLI.",
    )
    # Bootstrap input flags
    bootstrap = parser.add_mutually_exclusive_group()
    bootstrap.add_argument(
        "--request-text",
        type=str,
        default=None,
        help="Governance request text for evaluation.",
    )
    bootstrap.add_argument(
        "--request-file",
        type=str,
        default=None,
        help="Path to file containing the governance request (JSON or plain text).",
    )
    parser.add_argument(
        "--request-id",
        type=str,
        default=None,
        help="Optional correlation ID for the governance request.",
    )
    parser.add_argument(
        "--request-source",
        type=str,
        default=None,
        help="Optional source tag (e.g. 'pr', 'manual', 'hook').",
    )
    parser.add_argument(
        "--backend-isolation",
        type=str,
        default="project",
        choices=["project", "isolated"],
        help=(
            "Backend isolation mode. 'project' inherits repo-local Claude "
            "Code context (default). 'isolated' runs the subprocess from a "
            "neutral temp directory to avoid .claude/settings.json, hooks, "
            "and tool context interference."
        ),
    )
    parser.add_argument(
        "--runtime-info",
        action="store_true",
        help=(
            "Emit runtime provenance and backend context as JSON, then exit "
            "without executing the workflow. Use to verify which module files "
            "are actually loaded."
        ),
    )
    return parser


def _build_graph_json(spec, plan) -> dict:
    """Build machine-readable DAG structure."""
    steps = []
    edges = []

    for node in plan.ordered_steps:
        step = spec.workflow_steps.get(node.step_id)
        if step is None:
            continue
        kind, name = _parse_component_kind(step.component)
        step_dict = {
            "id": node.step_id,
            "component": step.component,
            "component_kind": kind,
            "component_name": name,
            "depends_on": list(step.depends_on),
            "outputs": list(step.outputs),
            "agent_binding": step.raw.get("agent_binding"),
            "layer": step.raw.get("layer"),
        }
        steps.append(step_dict)

        for dep in step.depends_on:
            edges.append({"from": dep, "to": node.step_id})

    agents = {}
    for agent_name, agent in spec.agents.items():
        agents[agent_name] = {
            "model": agent.model,
            "layer": agent.layer,
            "skill_bindings": agent.skill_bindings,
            "produces": agent.produces,
            "consumes": agent.consumes,
        }

    skills = {}
    for skill_name, skill in spec.skills.items():
        skills[skill_name] = {
            "produces": skill.produces,
            "description": skill.description,
        }

    artifacts = {}
    for artifact_name, artifact in spec.artifacts.items():
        artifacts[artifact_name] = {
            "producer_step": artifact.producer_step,
            "required": artifact.required,
        }

    blocking_conditions = {}
    for bc_id, bc in spec.blocking_conditions.items():
        blocking_conditions[bc_id] = {
            "severity": bc.severity,
            "halts_workflow": bc.halts_workflow,
        }

    return {
        "workflow_name": plan.workflow_name,
        "steps": steps,
        "edges": edges,
        "agents": agents,
        "skills": skills,
        "artifacts": artifacts,
        "blocking_conditions": blocking_conditions,
    }


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    # --runtime-info: emit provenance and exit without running the workflow
    if args.runtime_info:
        from governance.dag_runner.runtime_info import build_runtime_provenance
        from governance.dag_runner.execution_backend import ClaudeCodeCLIBackend
        provenance = build_runtime_provenance()
        backend_ctx = ClaudeCodeCLIBackend(
            isolation_mode=args.backend_isolation,
        ).get_execution_context()
        print(json.dumps({
            "runtime_provenance": provenance,
            "backend_execution_context": backend_ctx,
        }, indent=2))
        return EXIT_OK

    workflow_path = Path(args.workflow)
    state_path = Path(args.state_path)

    # Resolve bootstrap input: --request-file -> request_text
    resolved_request_text = args.request_text
    if args.request_file:
        request_path = Path(args.request_file)
        if not request_path.is_file():
            print(f"Request file not found: {request_path}", file=sys.stderr)
            return EXIT_STRUCTURAL_FAILURE
        try:
            raw = request_path.read_text(encoding="utf-8").strip()
            if not raw:
                print(f"Request file is empty: {request_path}", file=sys.stderr)
                return EXIT_STRUCTURAL_FAILURE
            # If the file is JSON, extract "request_text" field; otherwise use raw text
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and "request_text" in parsed:
                    resolved_request_text = parsed["request_text"]
                else:
                    resolved_request_text = raw
            except json.JSONDecodeError:
                resolved_request_text = raw
        except OSError as exc:
            print(f"Failed to read request file: {exc}", file=sys.stderr)
            return EXIT_STRUCTURAL_FAILURE

    try:
        loaded = load_workflow_packages(workflow_path)
        spec = assemble_workflow_spec(loaded)
        validate_or_raise(spec)
        validation_result = validate_workflow_spec(spec)

        # R2-B: Drift detection gate — critical drifts block execution
        drift_result = detect_drift(spec, _REPO_ROOT)
        for issue in drift_result.informational_drifts:
            print(f"DRIFT WARNING: {issue.message}", file=sys.stderr)
        if not drift_result.is_clean:
            for issue in drift_result.critical_drifts:
                print(f"CRITICAL DRIFT: {issue.message}", file=sys.stderr)
            if args.json_output:
                print(json.dumps({
                    "error": "critical_drift_detected",
                    "critical_drifts": [
                        {
                            "check": d.check,
                            "severity": d.severity,
                            "message": d.message,
                        }
                        for d in drift_result.critical_drifts
                    ],
                }, indent=2))
            return EXIT_STRUCTURAL_FAILURE

        plan = build_execution_plan(spec)

        # R3-B: --phase is accepted but not yet functional (Option B deferral)
        if args.phase:
            print(
                "WARNING: Phase scoping (--phase) is not yet implemented. "
                "Flag ignored; all steps will execute.",
                file=sys.stderr,
            )

        # Graph-only mode: emit DAG JSON and exit
        if args.graph:
            graph = _build_graph_json(spec, plan)
            if args.json_output:
                print(json.dumps(graph, indent=2))
            else:
                print(json.dumps(graph, indent=2))
            return 0

        blocker_summary = analyze_blockers(spec, plan)
        verdict = compute_verdict(validation_result, blocker_summary)

        # Build execution config for V2 modes
        from governance.dag_runner.execution_modes import build_config_from_args
        exec_config = build_config_from_args(
            mode=args.mode,
            dry_run=args.dry_run,
            json_output=args.json_output,
            graph=False,
            continue_from=args.continue_from,
            timeout=args.timeout,
            phase=args.phase,
            state_path=args.state_path,
            request_text=resolved_request_text,
            request_id=args.request_id,
            request_source=args.request_source,
        )

        # Determine backend
        backend = None
        backend_ctx = None
        prior_state = None
        if exec_config.mode in ("agent_execution", "dry_run"):
            if getattr(args, "backend", None) == "claude_code_cli":
                from governance.dag_runner.execution_backend import ClaudeCodeCLIBackend
                backend = ClaudeCodeCLIBackend(
                    timeout_ms=exec_config.timeout_per_step_ms,
                    isolation_mode=args.backend_isolation,
                )
                backend_ctx = backend.get_execution_context()
            else:
                from governance.dag_runner.execution_backend import MockExecutionBackend
                backend = MockExecutionBackend()

            # Handle continuation
            if exec_config.continue_from:
                from governance.dag_runner.state_store import load_run_state_from_path
                from governance.dag_runner.execution_modes import (
                    ContinuationError,
                    validate_continuation,
                )
                try:
                    prior_state = load_run_state_from_path(state_path)
                except Exception as exc:
                    print(f"Continuation failed: cannot load prior state: {exc}", file=sys.stderr)
                    return EXIT_STRUCTURAL_FAILURE

                failures = validate_continuation(prior_state, spec, plan, exec_config.continue_from)
                if failures:
                    print("Continuation guardrail violations:", file=sys.stderr)
                    for f in failures:
                        print(f"  - {f}", file=sys.stderr)
                    return EXIT_STRUCTURAL_FAILURE

        execution_result = execute_plan(
            spec, plan,
            verdict_status=verdict.status,
            config=exec_config,
            backend=backend,
            prior_state=prior_state,
        )

        # R2-C: Build diagnostic report from execution results
        diagnostic_report = build_diagnostic_report(
            spec, plan, execution_result.run_state,
        )

    except (
        LoaderError,
        AssemblerError,
        ValidationError,
        PlannerError,
        BlockerError,
        VerdictError,
        ExecutorError,
    ) as exc:
        print("DAG runner failed.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return EXIT_STRUCTURAL_FAILURE

    # JSON output mode
    if args.json_output:
        from governance.dag_runner.runtime_info import build_runtime_provenance
        output = {
            "workflow_name": plan.workflow_name,
            "mode": exec_config.mode if backend else "shell_v1",
            "loaded_packages": len(loaded.packages),
            "workflow_steps": len(spec.workflow_steps),
            "agents": len(spec.agents),
            "skills": len(spec.skills),
            "artifacts_declared": len(spec.artifacts),
            "artifacts_produced": len(execution_result.run_state.artifacts),
            "blocking_conditions": len(spec.blocking_conditions),
            "stage_gates": len(spec.stage_gates),
            "planned_steps": len(plan.ordered_steps),
            "executed_steps": len(execution_result.run_state.node_results),
            "trace_events": len(execution_result.run_state.execution_trace),
            "verdict": verdict.status,
            "verdict_reasons": verdict.reasons,
            "drift_clean": drift_result.is_clean,
            "drift_informational_count": len(drift_result.informational_drifts),
            "diagnostics": diagnostic_report_to_dict(diagnostic_report),
            "session_dir": execution_result.run_state.session_dir,
            "runtime_provenance": build_runtime_provenance(),
        }
        if backend_ctx:
            output["backend_execution_context"] = backend_ctx
        print(json.dumps(output, indent=2))
        return _exit_code_for_execution(
            execution_result.run_state, verdict.status,
        )

    # Text output (default)
    print("DAG runner summary")
    print("------------------")
    print(f"Workflow: {plan.workflow_name}")
    print(f"Workflow file: {loaded.workflow_path}")
    print(f"Loaded packages: {len(loaded.packages)}")
    print(f"Workflow steps: {len(spec.workflow_steps)}")
    print(f"Skills: {len(spec.skills)}")
    print(f"Agents: {len(spec.agents)}")
    print(f"Artifacts: {len(spec.artifacts)}")
    print(f"Blocking conditions: {len(spec.blocking_conditions)}")
    print(f"Stage gates: {len(spec.stage_gates)}")
    print(f"Subagents: {len(spec.subagents)}")
    print("Validation: PASS")
    print(f"Planned steps: {len(plan.ordered_steps)}")
    print(f"Executed steps: {len(execution_result.run_state.node_results)}")
    print(f"Recorded trace events: {len(execution_result.run_state.execution_trace)}")
    print(f"Verdict: {verdict.status.upper()}")
    if execution_result.run_state.session_dir:
        print(f"Session: {execution_result.run_state.session_dir}")

    if verdict.reasons:
        print("Verdict reasons:")
        for reason in verdict.reasons:
            print(f"  - {reason}")

    # R2-C: Diagnostics summary in text output
    print()
    print("Diagnostics")
    print("-----------")
    print(f"Total latency: {diagnostic_report.total_latency_ms:.0f}ms")
    print(f"Total tokens: {diagnostic_report.total_tokens}")
    if diagnostic_report.bottleneck_step:
        print(
            f"Bottleneck: {diagnostic_report.bottleneck_step} "
            f"({diagnostic_report.bottleneck_latency_ms:.0f}ms)"
        )
    print(f"Critical path: {' -> '.join(diagnostic_report.critical_path)}")
    print(f"Failed steps: {diagnostic_report.failed_steps}")

    if args.show_steps:
        print()
        print("Execution order")
        print("---------------")
        for index, node in enumerate(plan.ordered_steps, start=1):
            print(f"{index:02d}. {node.step_id} [{node.component}]")

    if args.write_state:
        try:
            from dataclasses import replace as _dc_replace
            from governance.dag_runner.runtime_info import build_runtime_provenance
            state = build_stored_run_state(
                loaded=loaded,
                spec=spec,
                validation_result=validation_result,
                plan=plan,
                blocker_summary=blocker_summary,
                verdict=verdict,
                execution_result=execution_result,
            )
            state = _dc_replace(
                state,
                runtime_provenance=build_runtime_provenance(),
                backend_execution_context=backend_ctx or {},
            )
            written_path = write_run_state(state, output_path=state_path)
        except StateStoreError as exc:
            print("Failed to persist run state.", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return EXIT_STRUCTURAL_FAILURE

        print()
        print(f"Run state written: {written_path}")

    return _exit_code_for_execution(execution_result.run_state, verdict.status)


if __name__ == "__main__":
    raise SystemExit(main())
